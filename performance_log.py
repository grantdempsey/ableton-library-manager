"""Local, per-session rotating timing records with no library paths or content."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import json
import logging
import os
from pathlib import Path
import platform
import threading
import time
import uuid
import housekeeping


SESSION_ID = uuid.uuid4().hex
MAX_LOG_BYTES = 2 * 1024 * 1024
_LOCK = threading.Lock()
_ENVIRONMENT = {"python": platform.python_version(), "platform": platform.system()}
_ACTIVE_PHASES = ContextVar("performance_log_phases", default=None)
_MAINTAINED_DIRECTORIES = set()


def _protect_session(directory):
    active = directory / ".locks" / (SESSION_ID + ".active")
    if os.path.lexists(active) and housekeeping._is_link(active):
        raise OSError(f"Refusing linked performance marker: {active}")
    active.write_text(str(os.getpid()), encoding="ascii")


def log_directory():
    # Follow redirected profile/index locations used by test and package fixtures.
    import sorter_engine
    return Path(sorter_engine.ASSET_INDEX_FILE).absolute().parent / "performance_logs"


def record(operation, started, *, outcome="completed", error_type=None, **metrics):
    """Append scalar measurements; logging failures never interrupt library work."""
    elapsed = max(0.0, time.perf_counter() - started)
    payload = {
        "version": 1, "session": SESSION_ID,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        **_ENVIRONMENT, "operation": operation, "outcome": outcome,
        "seconds": elapsed,
    }
    payload.update({
        key: value for key, value in metrics.items()
        if key not in payload and isinstance(value, (int, float, bool))
    })
    if error_type is not None:
        payload["error_type"] = error_type
    try:
        contents = json.dumps(payload, allow_nan=False) + "\n"
        with _LOCK:
            directory = log_directory()
            directory.mkdir(parents=True, exist_ok=True)
            with housekeeping.exclusive_lock(
                directory / ".locks" / (SESSION_ID + ".lock"), blocking=True
            ) as acquired:
                if not acquired:
                    raise OSError("Could not lock performance log session")
                _protect_session(directory)
                path = directory / f"performance-{SESSION_ID}.jsonl"
                if os.path.lexists(path) and housekeeping._is_link(path):
                    raise OSError(f"Refusing linked performance log: {path}")
                if path.exists() and path.stat().st_size + len(contents.encode("utf-8")) > MAX_LOG_BYTES:
                    os.replace(path, path.with_suffix(".jsonl.previous"))
                with path.open("a", encoding="utf-8") as handle:
                    handle.write(contents)
            if directory not in _MAINTAINED_DIRECTORIES:
                for error in housekeeping.retain_performance_logs(directory):
                    logging.getLogger(__name__).warning("Performance log retention: %s", error)
                _MAINTAINED_DIRECTORIES.add(directory)
    except (OSError, TypeError, ValueError) as error:
        logging.getLogger(__name__).warning("Could not save local performance measurements: %s", error)


@contextmanager
def measure_phase(name):
    """Accumulate a numeric phase duration in its enclosing timed record.

    Phase names are static operation labels; only elapsed seconds are persisted.
    """
    phases = _ACTIVE_PHASES.get()
    if phases is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        phases[name] = phases.get(name, 0.0) + max(0.0, time.perf_counter() - started)


def _phase_metrics(phases):
    return {f"phase_{name}_seconds": seconds for name, seconds in phases.items()}


def timed(operation, metrics=None):
    """Measure complete synchronous calls, preserving results and raised errors."""
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            started = time.perf_counter()
            phases = {}
            token = _ACTIVE_PHASES.set(phases)
            try:
                try:
                    result = function(*args, **kwargs)
                except Exception as error:
                    record(
                        operation, started, outcome="failed",
                        error_type=type(error).__name__,
                        **_phase_metrics(phases)
                    )
                    raise
                try:
                    values = metrics(result, *args, **kwargs) if metrics else {}
                except (AttributeError, IndexError, KeyError, OSError, TypeError, ValueError) as error:
                    logging.getLogger(__name__).warning(
                        "Could not collect local performance measurements: %s", error
                    )
                    record(
                        operation, started, outcome="measurement_failed",
                        error_type=type(error).__name__,
                        **_phase_metrics(phases)
                    )
                    return result
                values = dict(values)
                values.update(_phase_metrics(phases))
                record(operation, started, **values)
                return result
            finally:
                _ACTIVE_PHASES.reset(token)
        return measured
    return decorate

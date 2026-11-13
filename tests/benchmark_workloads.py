"""Reproducible, disposable benchmarks for the Phase 4 performance baseline.

Run from the repository root:
    python tests/benchmark_workloads.py --indexed-files 10000 --io-files 500
    python tests/benchmark_workloads.py --library "<User Library>" --report "<new report.json>"
"""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import threading
import time
import tracemalloc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ableton_tags
import library_jobs
import live_tag_sync
import sorter_engine
from tab_organize import OrganizeTab


class _Window:
    def after(self, _delay, callback):
        callback()


def _timed(function, repeats):
    samples = []
    result = None
    for _ in range(repeats):
        started = time.perf_counter()
        result = function()
        samples.append(time.perf_counter() - started)
    return result, statistics.median(samples), samples


def _peak_python_bytes(function):
    tracemalloc.start()
    before, _ = tracemalloc.get_traced_memory()
    tracemalloc.reset_peak()
    try:
        result = function()
        _current, peak = tracemalloc.get_traced_memory()
        return result, max(0, peak - before)
    finally:
        tracemalloc.stop()


def _make_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"x" * size)


def _populate_index(library, real_sample, indexed_files):
    connection = sorter_engine._asset_index_connection()
    destination = str(library / "Samples" / "One-Shots" / "Other One-Shots")
    now = time.time()
    assets = []
    tags = []
    for index in range(indexed_files):
        filename = f"Bench Kick Sample {index:08}.wav"
        path = str(real_sample if index == 0 else Path(destination) / filename)
        assets.append((
            path, filename, 1, now, destination, "benchmark", 1.0, "benchmark",
        ))
        if index % 10 == 0:
            tags.append((path, "favorite", 1, "personal"))
    with connection:
        connection.executemany(
            "INSERT INTO assets "
            "(path, filename, size, modified_time, destination, "
            "classification_reason, confidence, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            assets,
        )
        connection.executemany(
            "INSERT INTO asset_tags (asset_path, tag, enabled, source) "
            "VALUES (?, ?, ?, ?)",
            tags,
        )
    connection.close()


def _run_sort(source, destination, *, preview_only, done, status):
    sorter = sorter_engine.ParallelLibrarySorter(
        str(source), str(destination), _Window(), status, lambda *_args: done.set(),
        copy_mode=True, smart_learning_enabled=False, preview_only=preview_only,
    )
    sorter.start_parallel_sort()
    return sorter


def _benchmark_cancellation(source, destination):
    done = threading.Event()
    sorter = _run_sort(
        source, destination, preview_only=True, done=done, status=lambda _message: None,
    )
    deadline = time.monotonic() + 120
    while not done.is_set() and sorter.processed_files < 1 and time.monotonic() < deadline:
        time.sleep(0.001)
    if done.is_set():
        raise RuntimeError("The cancellation fixture completed before a cancellation request.")
    requested_at = time.perf_counter()
    sorter.cancel()
    if not done.wait(max(0, deadline - time.monotonic())):
        raise TimeoutError("The sorter did not finish after cancellation.")
    if sorter.worker_thread is not None:
        sorter.worker_thread.join()
    return {
        "seconds_from_request_to_completion": time.perf_counter() - requested_at,
        "processed_files_at_request": sorter.processed_files,
        "cancelled": sorter.cancel_event.is_set(),
    }


def _benchmark_import(source, destination, expected_files):
    done = threading.Event()
    sorter = _run_sort(
        source, destination, preview_only=False, done=done, status=lambda _message: None,
    )
    started = time.perf_counter()
    if not done.wait(300):
        sorter.cancel()
        raise TimeoutError("The import fixture did not finish within five minutes.")
    elapsed = time.perf_counter() - started
    if sorter.worker_thread is not None:
        sorter.worker_thread.join()
    output = destination / "Samples" / "One-Shots" / "Kicks"
    written = sum(1 for path in output.glob("*.wav")) if output.is_dir() else 0
    if written != expected_files or sorter.stats["Errors/Skipped Files"]:
        raise RuntimeError(
            f"Import benchmark was incomplete: {written}/{expected_files} outputs, "
            f"{sorter.stats['Errors/Skipped Files']} errors."
        )
    return {
        "seconds": elapsed,
        "files": written,
        "bytes": sum(path.stat().st_size for path in output.glob("*.wav")),
        "files_per_second": written / elapsed if elapsed else None,
    }


def _benchmark_backup(library, backup_root):
    page = type("BackupBenchmark", (), {
        "get_backup_directory": lambda self, _target: str(backup_root),
        "write_console_message": lambda self, _message: None,
    })()
    started = time.perf_counter()
    _target, archive = OrganizeTab.run_safeguard_archiver_thread(page, str(library))
    elapsed = time.perf_counter() - started
    size = Path(archive).stat().st_size
    return {
        "seconds": elapsed,
        "files": sum(1 for path in library.rglob("*") if path.is_file()),
        "archive_bytes": size,
        "archive": os.path.basename(archive),
    }


def run_benchmarks(indexed_files=10000, io_files=500, file_bytes=16384, repeats=5):
    with tempfile.TemporaryDirectory(prefix="ableton-library-bench-") as temporary:
        root = Path(temporary)
        library = root / "library"
        library.mkdir()
        real_sample = library / "Samples" / "One-Shots" / "Other One-Shots" / "Bench Kick Sample 00000000.wav"
        _make_file(real_sample, file_bytes)
        import_source = root / "incoming"
        cancel_source = root / "cancel-fixture"
        backup_library = root / "backup-fixture"
        for index in range(io_files):
            _make_file(import_source / f"Benchmark Kick Import {index:06}.wav", file_bytes)
            _make_file(cancel_source / f"Benchmark Kick Cancel {index:06}.wav", file_bytes)
        backup_files = min(io_files, 500)
        for index in range(backup_files):
            _make_file(backup_library / f"backup_{index:06}.bin", file_bytes)

        with ExitStack() as stack:
            config_file = root / "library_config.json"
            index_file = root / "library_assets.db"
            for name, value in (
                ("CONFIG_FILE", str(config_file)),
                ("ASSET_INDEX_FILE", str(index_file)),
                ("CONFIG_BACKUP_DIR", str(root / "config_backups")),
                ("MOVE_LOG_DIR", str(root / "move_logs")),
            ):
                stack.enter_context(patch.object(sorter_engine, name, value))
            stack.enter_context(patch.object(
                library_jobs, "coordinator",
                library_jobs.LibraryJobCoordinator(root / "library_jobs.lock"),
            ))
            profile = sorter_engine._default_config()
            profile["ACTIVE_LIBRARY_PATH"] = str(library)
            sorter_engine._write_config(profile, create_backup=False)
            sorter_engine.load_external_config()
            _populate_index(library, real_sample, indexed_files)
            ableton_tags.prepare_edit([str(real_sample)], "Drums|Kick").commit()

            first_page_started = time.perf_counter()
            first_page = sorter_engine.list_indexed_assets(
                limit=101, library_root=str(library),
            )
            first_page_seconds = time.perf_counter() - first_page_started
            warm_search_text = f"Bench {indexed_files - 1:08}"
            warm_search, warm_search_seconds, _ = _timed(
                lambda: sorter_engine.list_indexed_assets(
                    warm_search_text, limit=101, library_root=str(library),
                ),
                repeats,
            )
            _page_result, first_page_peak = _peak_python_bytes(
                lambda: sorter_engine.list_indexed_assets(
                    limit=101, library_root=str(library),
                )
            )
            _search_result, warm_search_peak = _peak_python_bytes(
                lambda: sorter_engine.list_indexed_assets(
                    warm_search_text, limit=101, library_root=str(library),
                )
            )

            state, snapshot = live_tag_sync.poll_live_metadata(str(library))
            if state == "pending":
                state, snapshot = live_tag_sync.poll_live_metadata(
                    str(library), candidate=snapshot,
                )
            if state != "refreshed":
                raise RuntimeError(f"Could not establish sidecar polling baseline: {state}")
            poll_result, poll_seconds, _ = _timed(
                lambda: live_tag_sync.poll_live_metadata(str(library), baseline=snapshot),
                repeats,
            )
            if poll_result[0] != "checked":
                raise RuntimeError(f"Expected unchanged sidecars to be checked, got {poll_result[0]}")

            backup = _benchmark_backup(backup_library, root / "backups")
            cancellation = _benchmark_cancellation(cancel_source, library)
            imported = _benchmark_import(import_source, library, io_files)

            return {
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "sqlite": sorter_engine.sqlite3.sqlite_version,
                },
                "fixture": {
                    "indexed_files": indexed_files,
                    "io_files": io_files,
                    "backup_files": backup_files,
                    "bytes_per_file": file_bytes,
                    "query_repeats": repeats,
                },
                "measurements": {
                    "first_page_query": {
                        "seconds": first_page_seconds,
                        "page_rows": min(100, len(first_page)),
                        "rows_fetched_including_next_page_probe": len(first_page),
                        "peak_python_bytes": first_page_peak,
                    },
                    "warm_search_query": {
                        "median_seconds": warm_search_seconds,
                        "rows_returned": len(warm_search),
                        "peak_python_bytes": warm_search_peak,
                    },
                    "unchanged_sidecar_poll": {
                        "median_seconds": poll_seconds,
                        "result": poll_result[0],
                        "indexed_files": indexed_files,
                    },
                    "backup": backup,
                    "cancellation": cancellation,
                    "import_copy": imported,
                },
                "measurement_notes": [
                    "Search timings measure the indexed data query, not Tk widget rendering.",
                    "Peak memory is Python tracemalloc allocation during one query; it excludes native SQLite allocations.",
                    "All benchmark fixtures, config, index, locks and backup output are temporary and removed at exit.",
                ],
            }


def benchmark_library(library, index_file, search_text="kick", repeats=5):
    """Measure existing library reads using an isolated, consistent index snapshot."""
    library = Path(library).resolve(strict=True)
    index_file = Path(index_file).resolve(strict=True)
    if not library.is_dir() or not index_file.is_file():
        raise ValueError("Choose an existing library directory and asset index file.")
    if repeats < 1:
        raise ValueError("Query repeats must be positive.")
    with tempfile.TemporaryDirectory(prefix="ableton-library-read-bench-") as temporary:
        snapshot_file = Path(temporary) / "assets.db"
        source = sorter_engine.sqlite3.connect(index_file.as_uri() + "?mode=ro", uri=True)
        try:
            target = sorter_engine.sqlite3.connect(snapshot_file)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()
        with patch.object(sorter_engine, "ASSET_INDEX_FILE", str(snapshot_file)):
            count = sorter_engine.count_indexed_assets(str(library))
            if not count:
                raise ValueError("No sounds are indexed for this library. Rescan it in the app first.")
            started = time.perf_counter()
            page = sorter_engine.list_indexed_assets(limit=101, library_root=str(library))
            first_seconds = time.perf_counter() - started
            def search():
                return sorter_engine.list_indexed_assets(
                    search_text, limit=101, library_root=str(library),
                )

            search()  # Warm the query before collecting repeated timings.
            matches, search_seconds, search_samples = _timed(search, repeats)
            _, page_peak = _peak_python_bytes(
                lambda: sorter_engine.list_indexed_assets(limit=101, library_root=str(library))
            )
            _, search_peak = _peak_python_bytes(search)
            connection = sorter_engine._asset_index_connection()
            try:
                paths, folders = live_tag_sync._scope(connection, str(library))
                baseline = live_tag_sync._fingerprint(paths, folders)
            finally:
                connection.close()

            def unchanged_poll():
                state, _ = live_tag_sync.poll_live_metadata(str(library), baseline=baseline)
                if state != "checked":
                    raise ValueError("Library metadata changed during the benchmark. Retry when it is stable.")
                return state

            _, poll_seconds, poll_samples = _timed(unchanged_poll, repeats)
            return {
                "mode": "read_only_library",
                "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
                "environment": {
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "sqlite": sorter_engine.sqlite3.sqlite_version,
                },
                "fixture": {
                    "indexed_sounds": count,
                    "poll_scope_records": len(paths),
                    "sidecars": len(baseline[1]),
                    "query_repeats": repeats,
                },
                "measurements": {
                    "first_page_query": {
                        "seconds": first_seconds,
                        "page_rows": min(100, len(page)),
                        "peak_python_bytes": page_peak,
                    },
                    "warm_search_query": {
                        "median_seconds": search_seconds,
                        "samples_seconds": search_samples,
                        "rows_fetched": len(matches),
                        "peak_python_bytes": search_peak,
                    },
                    "unchanged_sidecar_poll": {
                        "median_seconds": poll_seconds,
                        "samples_seconds": poll_samples,
                    },
                },
                "measurement_notes": [
                    "Queries use a temporary SQLite backup of the existing index; no rescan is performed.",
                    "Sidecar reads include ancestor metadata folders, matching the app's polling scope.",
                    "No imports, previews, backups, tag writes or real index updates are performed.",
                    "Query timings exclude UI rendering and snapshot creation; caches are not flushed.",
                    "Memory is Python allocation only, excluding native SQLite and total process memory.",
                    "Paths, filenames, tag values and search text are omitted from this report.",
                ],
            }


def save_report(report, output, library=None):
    """Save a new report outside the library without overwriting any existing file."""
    output = Path(output).resolve()
    if library is not None:
        library = Path(library).resolve()
        if output == library or library in output.parents:
            raise ValueError("Save the performance report outside the User Library.")
    contents = json.dumps(report, indent=2) + "\n"
    handle = output.open("x", encoding="utf-8")
    try:
        with handle:
            handle.write(contents)
    except OSError:
        output.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indexed-files", type=int, default=10000)
    parser.add_argument("--io-files", type=int, default=500)
    parser.add_argument("--file-bytes", type=int, default=16384)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--library", help="Existing User Library to benchmark read-only.")
    parser.add_argument("--index", default=sorter_engine.ASSET_INDEX_FILE,
                        help="Existing app asset index (used only with --library).")
    parser.add_argument("--search", default="kick", help="Warm search query for --library mode.")
    parser.add_argument("--report", help="New JSON report file; required with --library.")
    args = parser.parse_args()
    if min(args.indexed_files, args.io_files, args.file_bytes, args.repeats) < 1:
        parser.error("all counts and sizes must be positive")
    if args.library and not args.report:
        parser.error("--library requires --report pointing outside the User Library")
    try:
        if args.library:
            report = benchmark_library(args.library, args.index, args.search, args.repeats)
        else:
            report = run_benchmarks(args.indexed_files, args.io_files, args.file_bytes, args.repeats)
        if args.report:
            save_report(report, args.report, args.library)
        print(json.dumps(report, indent=2))
    except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
        parser.exit(1, f"Benchmark failed: {error}\n")


if __name__ == "__main__":
    main()

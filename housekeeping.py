"""Conservative maintenance and read-only storage accounting."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time
import uuid


LOG_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
LOG_MAX_BYTES = 50 * 1024 * 1024
CANDIDATE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
CANDIDATE_MAX_BYTES = 5 * 1024 * 1024 * 1024
_LOG_NAME = re.compile(r"performance-([0-9a-f]{32})\.jsonl(?:\.previous)?\Z")
_CANDIDATE_NAME = re.compile(r"candidate-([0-9a-f]{32})\Z")


def _is_link(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def profile_directory():
    import sorter_engine
    return Path(sorter_engine.ASSET_INDEX_FILE).absolute().parent


@contextmanager
def exclusive_lock(path, *, blocking=False):
    """Lock a stable, never-unlinked lock file across application processes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if _is_link(path.parent) or (os.path.lexists(path) and _is_link(path)):
        raise OSError(f"Refusing symbolic-link lock: {path}")
    handle = path.open("a+b")
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, os.SEEK_END)
            if not handle.tell():
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as error:
                if blocking or error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                locked = True
            except BlockingIOError:
                pass
        yield locked
    finally:
        if locked:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _session_active(directory, session):
    marker = directory / ".locks" / (session + ".active")
    if os.path.lexists(marker) and _is_link(marker):
        raise OSError(f"Refusing symbolic-link active marker: {marker}")
    try:
        pid = int(marker.read_text(encoding="ascii"))
    except FileNotFoundError:
        # Older sessions did not advertise a PID; their writer may still be alive.
        return True
    except (ValueError, UnicodeError) as error:
        raise OSError(f"Invalid active marker {marker}: {error}") from error
    if pid <= 0:
        raise OSError(f"Invalid process ID in {marker}")
    return _process_active(pid)


def _process_active(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:  # ERROR_INVALID_PARAMETER: no such process
                return False
            if error == 5:  # Access denied means the process may be active.
                return True
            raise ctypes.WinError(error)
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise ctypes.WinError(ctypes.get_last_error())
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def retain_performance_logs(directory=None, *, now=None, max_age=LOG_MAX_AGE_SECONDS,
                            max_bytes=LOG_MAX_BYTES):
    """Prune only recognized inactive session logs, oldest first; return errors."""
    directory = Path(directory) if directory is not None else profile_directory() / "performance_logs"
    now = time.time() if now is None else now
    errors, files = [], []
    if not directory.exists():
        return errors
    if _is_link(directory):
        return [f"{directory}: symbolic-link log directory skipped"]
    try:
        for path in directory.iterdir():
            match = _LOG_NAME.fullmatch(path.name)
            if not match:
                continue
            try:
                info = path.lstat()
                if stat.S_ISREG(info.st_mode):
                    files.append((info.st_mtime, info.st_size, path, match.group(1)))
            except OSError as error:
                errors.append(f"{path}: {error}")
    except OSError as error:
        return [f"{directory}: {error}"]
    total = sum(size for _, size, _, _ in files)
    for modified, size, path, session in sorted(files):
        if now - modified <= max_age and total <= max_bytes:
            continue
        try:
            with exclusive_lock(directory / ".locks" / (session + ".lock")) as acquired:
                if not acquired:
                    continue
                if _session_active(directory, session):
                    continue
                current = path.lstat()
                if (not stat.S_ISREG(current.st_mode) or current.st_mtime != modified
                        or current.st_size != size):
                    continue
                path.unlink()
                total -= size
        except FileNotFoundError:
            continue
        except OSError as error:
            errors.append(f"{path}: {error}")
    return errors


_PRIVATE_NAMES = {
    "library_config.json", "library_assets.db", "sidebar_cache.json", "saved_searches.json",
    "config_backups", "move_logs", "performance_logs", "alm transfer recovery",
    "ableton library backups", "options.txt", "log.txt",
}


def _candidate_data(candidate):
    match = _CANDIDATE_NAME.fullmatch(candidate.name)
    if not match or _is_link(candidate) or not candidate.is_dir():
        raise ValueError("not a managed candidate")
    marker = candidate / ".alm-candidate.json"
    if not marker.is_file() or _is_link(marker):
        raise ValueError("candidate marker missing or linked")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("version") != 2 or data.get("id") != match.group(1)
            or data.get("state") not in {"building", "failed", "complete", "validated"}
            or type(data.get("pid")) is not int or data["pid"] <= 0
            or (data.get("compiler_pid") is not None
                and (type(data["compiler_pid"]) is not int or data["compiler_pid"] <= 0))):
        raise ValueError("invalid or legacy candidate marker")
    return data


def _scan_tree(path):
    """Preflight every entry before removal; never traverse links or private state."""
    total = 0
    for current, dirs, files in os.walk(path, topdown=True, followlinks=False,
                                        onerror=lambda e: (_ for _ in ()).throw(e)):
        for name in dirs + files:
            entry = Path(current) / name
            info = entry.lstat()
            lowered = name.lower()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                    or lowered in _PRIVATE_NAMES or lowered.endswith(
                        (".bak", ".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm", ".db-journal", ".jsonl", ".log")
                    )
                    or lowered.startswith("user_library_backup_")):
                raise ValueError(f"protected or linked entry: {entry}")
            if stat.S_ISREG(info.st_mode):
                if info.st_nlink > 1:
                    raise ValueError(f"hard-linked entry: {entry}")
                total += info.st_size
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"unsupported entry: {entry}")
    return total


def _running_under(path):
    """Fail closed if process executable locations cannot be established."""
    root = os.path.normcase(os.path.abspath(path)) + os.sep
    if sys.platform.startswith("linux") and Path("/proc").is_dir():
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                executable = os.readlink(proc / "exe")
            except FileNotFoundError:
                continue
            except OSError as error:
                raise OSError(f"Cannot inspect process {proc.name}: {error}") from error
            if os.path.normcase(os.path.abspath(executable)).startswith(root):
                return True
        return False
    if os.name == "nt":
        files = [str(file) for file in path.rglob("*")
                 if file.is_file() and file.suffix.lower() in {".exe", ".dll", ".pyd", ".com", ".sys"}]
        return _windows_files_in_use(files)
    raise OSError("Running executable inspection unavailable on this platform")


def _windows_files_in_use(files):
    """Ask Restart Manager whether any executable or extension is in use."""
    if not files:
        return False
    import ctypes
    from ctypes import wintypes
    manager = ctypes.WinDLL("rstrtmgr")
    manager.RmStartSession.argtypes = (ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR)
    manager.RmRegisterResources.argtypes = (wintypes.DWORD, wintypes.UINT, ctypes.POINTER(wintypes.LPCWSTR),
                                             wintypes.UINT, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p)
    manager.RmGetList.argtypes = (wintypes.DWORD, ctypes.POINTER(wintypes.UINT),
                                 ctypes.POINTER(wintypes.UINT), ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD))
    manager.RmEndSession.argtypes = (wintypes.DWORD,)
    session, key = wintypes.DWORD(), ctypes.create_unicode_buffer(33)
    status = manager.RmStartSession(ctypes.byref(session), 0, key)
    if status:
        raise OSError(f"Restart Manager session failed: Windows error {status}")
    try:
        for offset in range(0, len(files), 512):
            batch = files[offset:offset + 512]
            array = (wintypes.LPCWSTR * len(batch))(*batch)
            status = manager.RmRegisterResources(session, len(batch), array, 0, None, 0, None)
            if status:
                raise OSError(f"Restart Manager registration failed: Windows error {status}")
        needed, count, reason = wintypes.UINT(), wintypes.UINT(), wintypes.DWORD()
        status = manager.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        if status == 234:  # ERROR_MORE_DATA: at least one process uses a resource.
            return True
        if status:
            raise OSError(f"Restart Manager inspection failed: Windows error {status}")
        return bool(needed.value or count.value)
    finally:
        manager.RmEndSession(session)


def mark_validated(candidate):
    """Mark a completed candidate validated after external smoke/archive verification."""
    candidate = Path(candidate).absolute()
    match = _CANDIDATE_NAME.fullmatch(candidate.name)
    if not match:
        raise ValueError("not a managed candidate")
    if _is_link(candidate.parent):
        raise ValueError("linked build directory")
    with exclusive_lock(candidate.parent / ".candidate-locks" / (match.group(1) + ".lock")) as acquired:
        if not acquired:
            raise OSError("candidate is in use")
        data = _candidate_data(candidate)
        if data["state"] not in {"complete", "validated"}:
            raise ValueError("candidate has not completed")
        if not (candidate / "dist").is_dir() or _is_link(candidate / "dist"):
            raise ValueError("candidate distribution missing or linked")
        data["state"] = "validated"
        marker = candidate / ".alm-candidate.json"
        marker.write_text(json.dumps(data), encoding="utf-8")


def clean_candidates(output_root, *, now=None, max_age=CANDIDATE_MAX_AGE_SECONDS,
                     max_bytes=CANDIDATE_MAX_BYTES):
    """Prune managed inactive candidates/work; return removed paths and blocked reasons."""
    root = Path(output_root)
    now = time.time() if now is None else now
    removed, blocked, candidates = [], [], []
    if not root.exists():
        return removed, blocked
    try:
        if _is_link(root):
            raise OSError("linked build directory")
        for candidate in root.iterdir():
            if not _CANDIDATE_NAME.fullmatch(candidate.name):
                continue
            try:
                data = _candidate_data(candidate)
                size = _scan_tree(candidate)
                candidates.append((candidate.stat().st_mtime, size, candidate, data))
            except (OSError, ValueError, TypeError) as error:
                blocked.append(f"{candidate}: {error}")
    except OSError as error:
        return removed, [f"{root}: {error}"]
    total = sum(size for _, size, _, _ in candidates)
    for modified, size, candidate, original in sorted(candidates):
        if now - modified <= max_age and total <= max_bytes:
            continue
        try:
            with exclusive_lock(root / ".candidate-locks" / (original["id"] + ".lock")) as acquired:
                if not acquired:
                    raise ValueError("active candidate lock")
                data = _candidate_data(candidate)
                if data != original:
                    raise ValueError("candidate marker changed")
                if _process_active(data["pid"]):
                    raise ValueError("build process is active")
                compiler = data.get("compiler_pid")
                if data["state"] == "building" and compiler is None:
                    raise ValueError("abandoned build lacks compiler process identity")
                if compiler and _process_active(compiler):
                    raise ValueError("compiler process is active")
                _scan_tree(candidate)
                if data["state"] == "complete":
                    raise ValueError("distribution not explicitly validated")
                target = candidate / "work" if data["state"] == "validated" else candidate
                if data["state"] == "validated" and not target.exists():
                    raise ValueError("validated distribution is protected; no disposable work")
                if target == candidate:
                    allowed = {".alm-candidate.json", "build_info.json", "work", "dist", "AbletonLibraryManager.spec"}
                    if any(p.name not in allowed for p in candidate.iterdir()):
                        raise ValueError("unknown candidate contents")
                    if _running_under(candidate):
                        raise ValueError("application running from candidate")
                removed_size = _scan_tree(target)
                if target == candidate:
                    quarantine = root / (".cleanup-" + uuid.uuid4().hex)
                    candidate.rename(quarantine)
                    try:
                        if _running_under(quarantine):
                            raise ValueError("application running from candidate")
                        _scan_tree(quarantine)
                        shutil.rmtree(quarantine)
                    except (OSError, ValueError):
                        if quarantine.exists():
                            quarantine.rename(candidate)
                        raise
                else:
                    shutil.rmtree(target)
                total -= removed_size
                removed.append(str(target))
        except (OSError, ValueError, TypeError) as error:
            blocked.append(f"{candidate}: {error}")
    if total > max_bytes:
        blocked.append(f"Managed builds still occupy {total:,} bytes (target {max_bytes:,}); protected or unavailable content remains.")
    return removed, blocked


def storage_summary(*, build_root=None, library_path=None):
    """Count known local state without following links or changing any files."""
    root = profile_directory()
    categories = {
        "Performance logs": [root / "performance_logs"],
        "Undo and move history": [root / "move_logs"],
        "Configuration backups": [root / "config_backups", root / "library_config.json.bak"],
        "Profile and index": [root / name for name in
                              ("library_config.json", "library_assets.db", "library_assets.db-wal",
                               "library_assets.db-shm", "sidebar_cache.json", "saved_searches.json")],
    }
    results, errors = {}, []
    def count(path):
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                errors.append(f"{path}: symbolic link skipped")
                return 0
            if stat.S_ISREG(info.st_mode):
                return info.st_size
            if stat.S_ISDIR(info.st_mode):
                return sum(count(child) for child in path.iterdir())
            errors.append(f"{path}: unsupported file type")
        except FileNotFoundError:
            return 0
        except OSError as error:
            errors.append(f"{path}: {error}")
        return 0
    for name, paths in categories.items():
        results[name] = sum(count(path) for path in paths)
    notes = []
    if build_root is None and not getattr(sys, "frozen", False) and "__file__" in globals():
        build_root = Path(__file__).absolute().parent / "release_builds"
    if build_root is None:
        results["Build artifacts"] = None
        notes.append("Build artifacts: location unknown in a packaged app; not measured.")
    else:
        build_root = Path(build_root)
        results["Build artifacts"] = count(build_root)
        notes.append(f"Build artifacts: {build_root}; distributions, unvalidated, active and unknown builds are protected.")
        try:
            if build_root.exists():
                for candidate in build_root.iterdir():
                    if candidate.name == ".candidate-locks":
                        continue
                    try:
                        data = _candidate_data(candidate)
                        if data["state"] in {"complete", "validated"}:
                            notes.append(f"Protected {data['state']} distribution: {candidate}")
                        elif _process_active(data["pid"]):
                            notes.append(f"Active build protected: {candidate}")
                    except (OSError, ValueError, TypeError) as error:
                        notes.append(f"Unmanaged or blocked build content protected: {candidate} ({error})")
        except OSError as error:
            errors.append(f"{build_root}: {error}")
        if results["Build artifacts"] > CANDIDATE_MAX_BYTES:
            notes.append("Build storage exceeds the 5 GiB target; protected or unrecognized content may prevent cleanup.")
    if library_path is None:
        import sorter_engine
        library_path = sorter_engine.ACTIVE_LIBRARY_PATH
    if not library_path or not os.path.isabs(library_path):
        results["Library ZIP backups"] = None
        notes.append("Library ZIP backups: location unknown; not measured.")
    else:
        backup_dir = Path(library_path).parent / "Ableton Library Backups"
        total = 0
        try:
            info = backup_dir.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise OSError("linked backup directory skipped")
            for path in backup_dir.iterdir():
                if path.name.startswith("User_Library_Backup_") and path.suffix.lower() == ".zip":
                    total += count(path)
            results["Library ZIP backups"] = total
            notes.append(f"Library ZIP backups: {backup_dir} (selected library only).")
        except FileNotFoundError:
            results["Library ZIP backups"] = 0
            notes.append(f"Library ZIP backups: {backup_dir} (selected library only; directory absent).")
        except OSError as error:
            results["Library ZIP backups"] = None
            errors.append(f"{backup_dir}: {error}")
    return {"profile_directory": str(root), "categories": results, "errors": errors, "notes": notes}

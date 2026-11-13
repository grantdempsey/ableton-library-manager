"""Exclusive ownership for library-affecting jobs across app instances."""
import errno
import os
from pathlib import Path
import stat
import threading

import library_state


class _ProcessJobLock:
    def __init__(self, path):
        self.path = os.fspath(path)
        self.handle = None

    def acquire(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        if os.path.islink(self.path):
            raise OSError(f"Refusing a linked library job lock: {self.path}")
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, flags, 0o600)
        try:
            handle = os.fdopen(descriptor, "r+b", buffering=0)
        except BaseException:
            os.close(descriptor)
            raise
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError(f"Library job lock is not a regular file: {self.path}")
            if os.fstat(descriptor).st_size == 0:
                handle.write(b"\0")
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    if (error.errno in (errno.EACCES, errno.EDEADLK, errno.EAGAIN)
                            or getattr(error, "winerror", None) == 33):
                        handle.close()
                        return False
                    raise
            else:
                import fcntl
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    return False
            self.handle = handle
            return True
        except BaseException:
            if not handle.closed:
                handle.close()
            raise

    def release(self):
        handle, self.handle = self.handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class LibraryJobLease:
    def __init__(self, coordinator, label, process_lock):
        self._coordinator = coordinator
        self.label = label
        self._process_lock = process_lock

    @property
    def active(self):
        with self._coordinator._lock:
            return self._coordinator._active is self

    def release(self):
        with self._coordinator._lock:
            if self._coordinator._active is self:
                self._coordinator._active = None
                self._process_lock.release()

    def __enter__(self):
        return self

    def __exit__(self, _kind, _value, _traceback):
        self.release()


class LibraryJobCoordinator:
    """Serialize library writers within this process and across app instances."""

    def __init__(self, lock_path=None):
        self._lock = threading.Lock()
        self._active = None
        if lock_path is None:
            lock_path = Path(library_state.user_data_directory()) / "library_jobs.lock"
        self._process_lock = _ProcessJobLock(lock_path)

    @property
    def active_label(self):
        with self._lock:
            return self._active.label if self._active is not None else None

    def claim(self, label):
        with self._lock:
            if self._active is not None:
                return None
            if not self._process_lock.acquire():
                return None
            lease = LibraryJobLease(self, label, self._process_lock)
            self._active = lease
            return lease


coordinator = LibraryJobCoordinator()

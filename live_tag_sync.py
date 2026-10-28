import hashlib
import os
from pathlib import Path

import ableton_tags
import sorter_engine


def _scope(connection, library_root):
    root = Path(os.path.abspath(library_root))
    if not root.is_dir():
        raise NotADirectoryError(f"Library is unavailable: {root}")
    clause, parameters = sorter_engine._library_root_clause(str(root), "path")
    paths = tuple(row[0] for row in connection.execute(
        f"SELECT path FROM assets WHERE {clause} ORDER BY path", parameters
    ))
    folders = {root, *root.parents}
    for path in paths:
        folder = Path(os.path.abspath(path)).parent
        folders.update((folder, *folder.parents))
    return paths, tuple(sorted(folders))


def _fingerprint(paths, folders):
    sidecars = []
    for folder in folders:
        info = folder / "Ableton Folder Info"
        if info.is_symlink():
            raise ValueError(f"Linked metadata folders cannot be monitored: {info}")
        try:
            entries = list(info.iterdir())
        except FileNotFoundError:
            continue
        for path in entries:
            if ableton_tags.is_metadata_stub(path.name) or path.suffix.lower() != ".xmp":
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Unsupported Ableton sidecar location: {path}")
            sidecars.append((str(path), hashlib.sha256(path.read_bytes()).digest()))
    return paths, tuple(sorted(sidecars))


def poll_live_metadata(library_root, baseline=None, candidate=None):
    """Waits for two identical probes, then refreshes only the manual tag cache."""
    connection = sorter_engine._asset_index_connection()
    try:
        paths, folders = _scope(connection, library_root)
        snapshot = _fingerprint(paths, folders)
        if snapshot == baseline:
            return "checked", snapshot
        if snapshot != candidate:
            return "pending", snapshot
        assignments = {}
        for folder in folders:
            for path, tags in ableton_tags.read_folder_tags(str(folder)).items():
                assignments.setdefault(path, set()).update(tags)
        if _fingerprint(paths, folders) != snapshot:
            raise ValueError("Live metadata changed during refresh; waiting for a stable snapshot.")
        connection.execute("BEGIN IMMEDIATE")
        current_paths, current_folders = _scope(connection, library_root)
        if current_paths != paths or current_folders != folders:
            raise ValueError("Indexed paths changed during metadata refresh; retrying.")
        for path in paths:
            sorter_engine._cache_ableton_tags(connection, path, assignments)
        if _fingerprint(paths, folders) != snapshot:
            raise ValueError("Live metadata changed before cache commit; cached tags retained.")
        connection.commit()
        return "refreshed", snapshot
    finally:
        connection.close()

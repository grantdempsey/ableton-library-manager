"""Stable per-user paths and conservative, repeatable legacy-state migration."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile


_STATE_FILES = (
    "library_config.json", "library_config.json.bak", "library_assets.db",
    "saved_searches.json", "sidebar_cache.json",
)
_STATE_DIRECTORIES = ("config_backups", "move_logs")
_MANIFEST = "migration_manifest.json"
_ALIASES = "legacy_path_aliases.json"
_LEGACY_PROFILES = "legacy_profiles.json"


class StateMigrationError(OSError):
    pass


def user_data_directory(*, system=None, home=None, environment=None):
    system = system or sys.platform
    home = os.path.expanduser("~") if home is None else os.fspath(home)
    environment = os.environ if environment is None else environment
    if system == "win32" or system.startswith("win"):
        base = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        base = base or os.path.join(home, "AppData", "Local")
    elif system == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = environment.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(os.path.abspath(base), "AbletonLibraryManager")


def default_user_library(*, system=None, home=None, environment=None):
    system = system or sys.platform
    home = os.path.expanduser("~") if home is None else os.fspath(home)
    environment = os.environ if environment is None else environment
    if system == "win32" or system.startswith("win"):
        candidates = [os.path.join(home, "Documents", "Ableton", "User Library")]
        one_drive = environment.get("OneDrive")
        if one_drive:
            candidates.append(os.path.join(one_drive, "Documents", "Ableton", "User Library"))
        candidates.append(os.path.join(home, "OneDrive", "Documents", "Ableton", "User Library"))
    elif system == "darwin":
        candidates = [os.path.join(home, "Music", "Ableton", "User Library")]
    else:
        candidates = [os.path.join(home, "Documents", "Ableton", "User Library")]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(candidates[0])


def legacy_state_directories(*, cwd=None, executable=None, source=None):
    candidates = [cwd or os.getcwd()]
    if executable:
        candidates.append(os.path.dirname(os.path.abspath(executable)))
    if source:
        candidates.append(os.path.dirname(os.path.abspath(source)))
    unique = []
    seen = set()
    for candidate in candidates:
        path = os.path.abspath(candidate)
        key = os.path.normcase(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _fingerprint(path):
    info = os.stat(path, follow_symlinks=False)
    result = {"size": info.st_size, "modified_ns": info.st_mtime_ns}
    if Path(path).name == "library_assets.db":
        wal = Path(f"{path}-wal")
        result["wal"] = _fingerprint(wal) if wal.exists() else None
    return result


def _digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-",
            suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _copy_exclusive(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise StateMigrationError(f"Refusing linked or non-file legacy state: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "wb") as target, source.open("rb") as original:
            descriptor = None
            shutil.copyfileobj(original, target, 1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        shutil.copystat(source, destination, follow_symlinks=False)
        if _digest(source) != _digest(destination):
            raise StateMigrationError(f"Copied legacy state failed verification: {source}")
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        raise


def _copy_database(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise StateMigrationError(f"Refusing linked or non-file legacy database: {source}")
    if any(Path(f"{source}-{suffix}").is_symlink() for suffix in ("wal", "shm")):
        raise StateMigrationError(f"Refusing linked SQLite sidecar beside legacy database: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".library-index-", suffix=".db", dir=destination.parent)
    os.close(descriptor)
    published = False
    complete = False
    try:
        source_uri = source.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as original:
            with closing(sqlite3.connect(temporary, timeout=30)) as target:
                original.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise StateMigrationError(f"Legacy SQLite integrity check failed: {result}")
                target.commit()
        shutil.copystat(source, temporary)
        try:
            os.link(temporary, destination)
            published = True
        except FileExistsError:
            raise
        except OSError:
            try:
                descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                published = True
                with os.fdopen(descriptor, "wb") as target, open(temporary, "rb") as original:
                    shutil.copyfileobj(original, target, 1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
            except BaseException:
                if published:
                    destination.unlink(missing_ok=True)
                raise
        with closing(sqlite3.connect(destination.resolve().as_uri() + "?mode=ro", uri=True)) as copied:
            if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise StateMigrationError(f"Migrated SQLite integrity check failed: {destination}")
        complete = True
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        if published and not complete:
            destination.unlink(missing_ok=True)


def _same_contents(first, second):
    try:
        return _digest(first) == _digest(second)
    except OSError:
        return False


def legacy_profile_paths(destination):
    path = Path(destination) / _LEGACY_PROFILES
    if not path.exists():
        return []
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise StateMigrationError("Legacy profile registry must contain profile paths.")
    return values


def migrate_legacy_state(legacy_directories, destination):
    """Copy known runtime state without deleting or overwriting any existing file."""
    destination = Path(destination).absolute()
    destination.mkdir(parents=True, exist_ok=True)
    manifest_path = destination / _MANIFEST
    aliases_path = destination / _ALIASES
    profiles_path = destination / _LEGACY_PROFILES
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
    except (OSError, json.JSONDecodeError, TypeError) as error:
        raise StateMigrationError(f"Application state migration metadata is unreadable: {error}") from error
    if not isinstance(manifest, dict) or not isinstance(aliases, dict):
        raise StateMigrationError("Application state migration metadata has an invalid shape.")
    if any(
        not isinstance(source, str) or not isinstance(entry, dict)
        or not isinstance(entry.get("fingerprint"), dict)
        or not isinstance(entry.get("target"), str)
        for source, entry in manifest.items()
    ) or any(
        not isinstance(source, str) or not isinstance(target, str)
        for source, target in aliases.items()
    ):
        raise StateMigrationError("Application state migration metadata has an invalid entry.")
    try:
        profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.exists() else []
    except (OSError, ValueError) as error:
        raise StateMigrationError(f"Could not read legacy profile registry: {error}") from error
    if not isinstance(profiles, list) or any(not isinstance(path, str) for path in profiles):
        raise StateMigrationError("Legacy profile registry must contain profile paths.")
    profiles = set(profiles)
    profiles.update(path for path in manifest if Path(path).name == "library_config.json")
    for directory in legacy_directories:
        profile = Path(directory).absolute() / "library_config.json"
        if profile.is_file() and profile.parent != destination:
            profiles.add(str(profile))
    _write_json(profiles_path, sorted(profiles))
    warnings = []
    errors = []
    for root in legacy_directories:
        root = Path(root).absolute()
        if root == destination:
            continue
        root_invalid = False
        for name in _STATE_FILES:
            source = root / name
            if os.path.lexists(source) and (source.is_symlink() or not source.is_file()):
                errors.append(f"Refused linked or non-file legacy state: {source}")
                root_invalid = True
        for name in _STATE_DIRECTORIES:
            source = root / name
            if os.path.lexists(source) and (source.is_symlink() or not source.is_dir()):
                errors.append(f"Refused linked or non-directory legacy state: {source}")
                root_invalid = True
        database = root / "library_assets.db"
        for suffix in ("wal", "shm"):
            sidecar = Path(f"{database}-{suffix}")
            if os.path.lexists(sidecar) and sidecar.is_symlink():
                errors.append(f"Refused linked SQLite sidecar beside legacy database: {sidecar}")
                root_invalid = True
        if root_invalid:
            continue
        root_conflict = False
        for name in ("library_config.json", "library_assets.db"):
            source_core, target_core = root / name, destination / name
            if not source_core.is_file() or not target_core.is_file():
                continue
            source_key = str(source_core)
            source_fingerprint = _fingerprint(source_core)
            entry = manifest.get(source_key)
            previously_migrated = (
                isinstance(entry, dict) and entry.get("fingerprint") == source_fingerprint
                and entry.get("target") == str(target_core)
            )
            has_unmigrated_wal = (
                name == "library_assets.db"
                and os.path.lexists(f"{source_core}-wal")
                and not previously_migrated
            )
            if not previously_migrated and (
                has_unmigrated_wal or not _same_contents(source_core, target_core)
            ):
                root_conflict = True
                warnings.append(
                    f"Kept the stable profile; conflicting legacy {name} and its related state "
                    f"remain together at {root}."
                )
                break
        if root_conflict:
            continue
        for name in _STATE_FILES:
            source = root / name
            if not source.exists():
                continue
            target = destination / name
            if source.is_symlink() or not source.is_file():
                errors.append(f"Refused linked legacy state: {source}")
                continue
            try:
                fingerprint = _fingerprint(source)
                previous = manifest.get(str(source))
                if previous == {"fingerprint": fingerprint, "target": str(target)} and target.is_file():
                    aliases[str(source)] = str(target)
                    continue
                if target.exists():
                    if _same_contents(source, target):
                        aliases[str(source)] = str(target)
                        manifest[str(source)] = {"fingerprint": fingerprint, "target": str(target)}
                    else:
                        warnings.append(
                            f"Kept existing stable {name}; different legacy copy remains at {source}."
                        )
                    continue
                if name == "library_assets.db":
                    _copy_database(source, target)
                else:
                    _copy_exclusive(source, target)
                aliases[str(source)] = str(target)
                manifest[str(source)] = {"fingerprint": fingerprint, "target": str(target)}
            except (OSError, sqlite3.Error, StateMigrationError) as error:
                errors.append(f"Could not migrate {source}: {error}")
        for directory in _STATE_DIRECTORIES:
            source_directory = root / directory
            if not source_directory.exists():
                continue
            if source_directory.is_symlink() or not source_directory.is_dir():
                errors.append(f"Refused linked legacy state directory: {source_directory}")
                continue
            target_directory = destination / directory
            target_directory.mkdir(parents=True, exist_ok=True)
            for source in sorted(source_directory.iterdir()):
                if source.is_symlink() or not source.is_file():
                    errors.append(f"Refused linked/non-file legacy state: {source}")
                    continue
                try:
                    fingerprint = _fingerprint(source)
                    entry = manifest.get(str(source))
                    if entry and entry.get("fingerprint") == fingerprint and Path(entry["target"]).is_file():
                        aliases[str(source)] = entry["target"]
                        continue
                    target = target_directory / source.name
                    if target.exists() and not _same_contents(source, target):
                        suffix = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:10]
                        target = target_directory / f"legacy-{suffix}-{source.name}"
                    if not target.exists():
                        _copy_exclusive(source, target)
                    aliases[str(source)] = str(target)
                    manifest[str(source)] = {"fingerprint": fingerprint, "target": str(target)}
                except (OSError, sqlite3.Error, StateMigrationError) as error:
                    errors.append(f"Could not migrate {source}: {error}")
    if errors:
        _write_json(aliases_path, aliases)
        _write_json(manifest_path, manifest)
        raise StateMigrationError("Legacy application state was preserved but not fully migrated:\n"
                                  + "\n".join(errors))
    for old_path, new_path in list(aliases.items()):
        if not old_path.endswith(".jsonl") or not Path(new_path).is_file():
            continue
        try:
            records = [json.loads(line) for line in Path(new_path).read_text(encoding="utf-8").splitlines() if line.strip()]
            changed = False
            for record in records:
                recovery = record.get("recovery")
                if recovery in aliases and recovery != aliases[recovery]:
                    record["recovery"] = aliases[recovery]
                    changed = True
            if changed:
                temporary = None
                try:
                    with tempfile.NamedTemporaryFile(
                        mode="w", encoding="utf-8", dir=Path(new_path).parent,
                        prefix=f".{Path(new_path).name}-", suffix=".tmp", delete=False,
                    ) as handle:
                        temporary = handle.name
                        for record in records:
                            handle.write(json.dumps(record) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, new_path)
                finally:
                    if temporary and os.path.exists(temporary):
                        os.unlink(temporary)
        except (OSError, ValueError, TypeError) as error:
            warnings.append(f"Could not update migrated undo references in {new_path}: {error}")
    _write_json(aliases_path, aliases)
    _write_json(manifest_path, manifest)
    return warnings


def resolve_legacy_path(path, aliases_file):
    if not isinstance(path, (str, os.PathLike)) or not os.fspath(path):
        raise StateMigrationError("Legacy path mapping requires a non-empty path.")
    path = os.path.abspath(path)
    try:
        aliases = json.loads(Path(aliases_file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return path
    except (OSError, json.JSONDecodeError, TypeError) as error:
        raise StateMigrationError(f"Could not read legacy path mappings: {error}") from error
    resolved = aliases.get(path, path)
    return os.path.abspath(resolved)

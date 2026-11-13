# sorter_engine.py - Piece 1: Core Configuration Matrices & Global State Setup
import os
import ntpath
import sys
import json
import re
import zlib
import hashlib
import stat
import shutil
import subprocess
import threading
import tempfile
import uuid
import time
import copy
from functools import wraps
import sqlite3
import datetime
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import ableton_tags
import tag_evidence
import serum_presets
import library_jobs
import library_state
import performance_log

# Core Shared Platform State Configuration Mapping
def _runtime_file(name):
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        directory = os.path.expanduser("~/Library/Application Support/AbletonLibraryManager")
        return os.path.join(directory, name)
    return os.path.join(library_state.user_data_directory(
        system=sys.platform, home=os.path.expanduser("~"), environment=os.environ,
    ), name)


CONFIG_FILE = _runtime_file("library_config.json")
ASSET_INDEX_FILE = _runtime_file("library_assets.db")
ACTIVE_LIBRARY_PATH = library_state.default_user_library()
STATE_MIGRATION_WARNINGS = []
_STATE_MIGRATION_DONE = False
_DEFAULT_CONFIG_FILE = CONFIG_FILE
_DEFAULT_ASSET_INDEX_FILE = ASSET_INDEX_FILE
AUDIO_EXTS = {
    ".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".oga", ".m4a",
    ".aac", ".wma", ".opus", ".caf", ".au", ".snd"
}
SUPPORTED_PRESET_EXTS = {
    ".fxp", ".fxb", ".serumpreset", ".vital", ".adg", ".adv", ".alc",
    ".amxd", ".nki", ".nkm", ".nksf", ".aupreset", ".h2p", ".h2p2",
}
INDEXABLE_SOUND_EXTS = AUDIO_EXTS | {".mid", ".midi"}
INDEXABLE_SOUND_SUFFIXES = tuple(sorted(INDEXABLE_SOUND_EXTS))

# Global lookup lists initialized as empty targets for GUI thread mapping hooks
BPM_RANGES = []
DRUM_KEYWORDS = {}
SYNTH_EXTS = {}
NATIVE_EXTS = {}
IGNORED_DIRECTORIES = ["Ableton Folder Info", "Backup", "Crash Recovery", "Factory Packages"]
RULE_METADATA = {}
SMART_LEARNING_ENABLED = True
MIN_RULE_EVIDENCE = 20
LEARNING_COUNTS = {}
LEARNED_RULE_CANDIDATES = []
LOOP_LEVELS = ("bpm", "key")
LOOP_LAYOUT = list(LOOP_LEVELS)
_ASSET_SCHEMA_READY = set()
_ASSET_SCHEMA_LOCK = threading.Lock()
_CONFIG_LOCK = threading.RLock()
_UNSPECIFIED_CONFIG = object()
CONFIG_LOAD_ERROR = None
XO_CONFIG_LOAD_ERROR = None


def serialized_config(function):
    @wraps(function)
    def synchronized(*args, **kwargs):
        with _CONFIG_LOCK:
            return function(*args, **kwargs)
    return synchronized

NESTING_GUARD_FOLDERS = {
    "samples", "one-shots", "loops", "percussion", "midi",
    "serum presets", "live instrument racks", "max for live devices",
}

def _default_learning_state():
    return {
        "SMART_LEARNING_ENABLED": True,
        "LEARNING_COUNTS": {},
        "LEARNED_RULE_CANDIDATES": [],
        "RULE_METADATA": {}
    }

def _default_config():
    return {
        "ACTIVE_LIBRARY_PATH": library_state.default_user_library(),
        "BPM_RANGES": [[0, 99, "99 BPM and Below"], [100, 114, "100-114 BPM"],
                       [115, 129, "115-129 BPM"], [130, 149, "130-149 BPM"],
                       [150, 174, "150-174 BPM"], [175, 999, "175 BPM and Above"]],
        "DRUM_KEYWORDS": {
            "(?:^|[^a-zA-Z0-9])kick(?:s)?(?:$|[^a-zA-Z0-9])": "Kicks",
            "(?:^|[^a-zA-Z0-9])snare(?:s)?(?:$|[^a-zA-Z0-9])": "Snares",
            "(?:^|[^a-zA-Z0-9])(?:hi)?hat(?:s)?(?:$|[^a-zA-Z0-9])": "Hi-Hats",
            "(?:^|[^a-zA-Z0-9])open\\s*hat(?:$|[^a-zA-Z0-9])": "Hi-Hats",
            "(?:^|[^a-zA-Z0-9])closed\\s*hat(?:$|[^a-zA-Z0-9])": "Hi-Hats",
            "(?:^|[^a-zA-Z0-9])clap(?:s)?(?:$|[^a-zA-Z0-9])": "Claps",
            "(?:^|[^a-zA-Z0-9])rim(?:shot)?(?:$|[^a-zA-Z0-9])": "Snares",
            "(?:^|[^a-zA-Z0-9])tom(?:s)?(?:$|[^a-zA-Z0-9])": "Toms",
            "(?:^|[^a-zA-Z0-9])shaker(?:s)?(?:$|[^a-zA-Z0-9])": "Percussion/Shakers",
            "(?:^|[^a-zA-Z0-9])perc(?:ussion)?(?:$|[^a-zA-Z0-9])": "Percussion",
            "(?:^|[^a-zA-Z0-9])cym(?:bal)?(?:s)?(?:$|[^a-zA-Z0-9])": "Cymbals & Crashes",
            "(?:^|[^a-zA-Z0-9])808(?:s)?(?:$|[^a-zA-Z0-9])": "808 Sub Bass"
        },
        "SYNTH_EXTS": {".fxp": serum_presets.USER_FOLDER, ".fxb": "Serum Banks",
                       ".serumpreset": serum_presets.USER_FOLDER},
        "NATIVE_EXTS": {".adg": "Live Instrument Racks", ".amxd": "Max For Live Devices"},
        "IGNORED_DIRECTORIES": ["eastwest", "kontakt library", "spectrasonics", "steam",
                               "vstplugins", "common files"],
        "LOOP_LAYOUT": list(LOOP_LEVELS),
        **_default_learning_state()
    }

def _validate_route_folder(folder):
    if not isinstance(folder, str) or not folder.strip():
        raise ValueError("Routing destination must be a non-empty relative folder.")
    parts = re.split(r"[/\\]", folder)
    if (ntpath.splitdrive(folder)[0] or folder.startswith(("/", "\\"))
            or any(part in (".", "..") or not part.strip()
                   or part.rstrip(" .") != part for part in parts)
            or any(character in folder for character in ('\x00', ':'))):
        raise ValueError(f"Routing destination must stay inside the selected library: {folder!r}")


def _resolved_route_path(path):
    resolved = os.path.realpath(path)
    if os.name == "nt":
        if resolved.startswith("\\\\?\\UNC\\"):
            resolved = "\\\\" + resolved[8:]
        elif resolved.startswith("\\\\?\\") and re.match(r"[a-zA-Z]:\\", resolved[4:]):
            resolved = resolved[4:]
    return os.path.normcase(resolved)


def _validate_destination(library_root, destination):
    destination = destination.replace("\\", os.sep).replace("/", os.sep)
    root = os.path.abspath(library_root)
    target = os.path.abspath(destination)
    try:
        lexical_inside = os.path.normcase(os.path.commonpath((root, target))) == os.path.normcase(root)
        resolved_root = _resolved_route_path(root)
        resolved_target = _resolved_route_path(target)
        resolved_inside = os.path.normcase(
            os.path.commonpath((resolved_root, resolved_target))
        ) == os.path.normcase(resolved_root)
    except ValueError:
        lexical_inside = resolved_inside = False
    if not lexical_inside or not resolved_inside:
        raise ValueError(f"Routing destination escapes the selected library: {destination}")
    path = Path(target)
    while os.path.normcase(str(path)) != os.path.normcase(root):
        junction = (
            os.name == "nt" and os.path.lexists(path)
            and path.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        )
        if path.is_symlink() or junction:
            raise ValueError(f"Linked routing destination is not supported: {path}")
        path = path.parent
    return os.path.normpath(destination)


def _validate_config(data):
    if not isinstance(data, dict):
        raise ValueError("Configuration must contain a JSON object.")
    bpm_ranges = data.get("BPM_RANGES", [])
    if not isinstance(bpm_ranges, list) or any(
        not isinstance(item, (list, tuple)) or len(item) != 3 or
        not isinstance(item[0], (int, float)) or not isinstance(item[1], (int, float)) or
        not isinstance(item[2], str)
        for item in bpm_ranges
    ):
        raise ValueError("BPM_RANGES must contain [minimum, maximum, label] entries.")
    for key in ("DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS"):
        if not isinstance(data.get(key, {}), dict):
            raise ValueError(f"{key} must be an object.")
        for folder in data.get(key, {}).values():
            _validate_route_folder(folder)
    if not isinstance(data.get("IGNORED_DIRECTORIES", []), list):
        raise ValueError("IGNORED_DIRECTORIES must be a list.")
    if any(not isinstance(value, str) or not value.strip()
           for value in data.get("IGNORED_DIRECTORIES", [])):
        raise ValueError("IGNORED_DIRECTORIES must contain nonempty folder names.")
    if not isinstance(data.get("LEARNING_COUNTS", {}), dict):
        raise ValueError("LEARNING_COUNTS must be an object.")
    if not isinstance(data.get("LEARNED_RULE_CANDIDATES", []), list):
        raise ValueError("LEARNED_RULE_CANDIDATES must be a list.")
    custom_types = data.get("XO_CUSTOM_TYPES", {})
    if not isinstance(custom_types, dict) or any(
        not isinstance(name, str) or not isinstance(words, list)
        or any(not isinstance(word, str) for word in words)
        for name, words in custom_types.items()
    ):
        raise ValueError("XO_CUSTOM_TYPES must map folder names to lists of keywords.")
    if not isinstance(data.get("RULE_METADATA", {}), dict):
        raise ValueError("RULE_METADATA must be an object.")
    active_library = data.get("ACTIVE_LIBRARY_PATH", library_state.default_user_library())
    if not isinstance(active_library, str) or not active_library.strip():
        raise ValueError("ACTIVE_LIBRARY_PATH must be a non-empty path.")
    layout = data.get("LOOP_LAYOUT", list(LOOP_LEVELS))
    if (not isinstance(layout, list) or len(set(layout)) != len(layout)
            or any(level not in LOOP_LEVELS for level in layout)):
        raise ValueError("LOOP_LAYOUT must list each of 'bpm' and 'key' at most once.")
    return data


def _validate_config_with_xo_fallback(data):
    """Keep non-XO profile settings available without trusting malformed XO folders."""
    global XO_CONFIG_LOAD_ERROR
    try:
        return _validate_config(data)
    except ValueError as error:
        if not isinstance(data, dict) or "XO_CUSTOM_TYPES" not in str(error):
            raise
        safe_data = dict(data)
        safe_data.pop("XO_CUSTOM_TYPES", None)
        validated = _validate_config(safe_data)
        XO_CONFIG_LOAD_ERROR = f"XO folder configuration is invalid: {error}"
        return validated


@serialized_config
def load_external_config():
    """Reads configuration matrices directly from disk to keep UI settings synced."""
    global BPM_RANGES, DRUM_KEYWORDS, SYNTH_EXTS, NATIVE_EXTS, IGNORED_DIRECTORIES
    global RULE_METADATA
    global SMART_LEARNING_ENABLED, LEARNING_COUNTS, LEARNED_RULE_CANDIDATES, LOOP_LAYOUT
    global ACTIVE_LIBRARY_PATH, CONFIG_LOAD_ERROR
    if not os.path.exists(CONFIG_FILE):
        _write_config(_default_config(), create_backup=False)
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_rules = _validate_config_with_xo_fallback(json.load(f))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        backup_path = f"{CONFIG_FILE}.bak"
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                user_rules = _validate_config_with_xo_fallback(json.load(f))
            os.replace(backup_path, CONFIG_FILE)
        except (OSError, json.JSONDecodeError, ValueError) as backup_error:
            CONFIG_LOAD_ERROR = (
                f"Configuration is invalid ({error}) and no valid backup was found "
                f"({backup_error})."
            )
            raise ValueError(CONFIG_LOAD_ERROR) from error
    upgraded_serum_rules = False
    for extension in serum_presets.PRESET_EXTENSIONS:
        if user_rules.get("SYNTH_EXTS", {}).get(extension) in (
            "Serum Presets", "Serum Presets/Serum 2 Presets/Presets/User",
        ):
            user_rules["SYNTH_EXTS"][extension] = serum_presets.USER_FOLDER
            upgraded_serum_rules = True
    active_library = user_rules.get("ACTIVE_LIBRARY_PATH", library_state.default_user_library())
    if not os.path.isabs(active_library):
        active_library = os.path.abspath(active_library)
    if user_rules.get("ACTIVE_LIBRARY_PATH") != active_library:
        user_rules["ACTIVE_LIBRARY_PATH"] = active_library
    if upgraded_serum_rules:
        _write_config(user_rules)
    CONFIG_LOAD_ERROR = None
    return _apply_config_values(user_rules)


def _apply_config_values(user_rules):
    global BPM_RANGES, DRUM_KEYWORDS, SYNTH_EXTS, NATIVE_EXTS, IGNORED_DIRECTORIES
    global RULE_METADATA, SMART_LEARNING_ENABLED, LEARNING_COUNTS
    global LEARNED_RULE_CANDIDATES, LOOP_LAYOUT, ACTIVE_LIBRARY_PATH
    BPM_RANGES = [tuple(x) for x in user_rules.get("BPM_RANGES", [])]
    DRUM_KEYWORDS = user_rules.get("DRUM_KEYWORDS", {})
    SYNTH_EXTS = user_rules.get("SYNTH_EXTS", {})
    NATIVE_EXTS = user_rules.get("NATIVE_EXTS", {})
    IGNORED_DIRECTORIES = user_rules.get("IGNORED_DIRECTORIES", [])
    SMART_LEARNING_ENABLED = bool(user_rules.get("SMART_LEARNING_ENABLED", True))
    LEARNING_COUNTS = user_rules.get("LEARNING_COUNTS", {})
    LEARNED_RULE_CANDIDATES = user_rules.get("LEARNED_RULE_CANDIDATES", [])
    RULE_METADATA = user_rules.get("RULE_METADATA", {})
    LOOP_LAYOUT = list(user_rules.get("LOOP_LAYOUT", LOOP_LEVELS))
    active_library = user_rules.get("ACTIVE_LIBRARY_PATH", library_state.default_user_library())
    ACTIVE_LIBRARY_PATH = os.path.abspath(os.path.normpath(active_library))
    for index, pattern in enumerate(DRUM_KEYWORDS):
        RULE_METADATA.setdefault(pattern, {
            "priority": len(DRUM_KEYWORDS) - index,
            "enabled": True,
            "exclude": []
        })
    return user_rules


_apply_config_values(_default_config())


def initialize_runtime_storage():
    """Migrate the current working/profile state before the app loads persisted settings."""
    global _STATE_MIGRATION_DONE, STATE_MIGRATION_WARNINGS
    if _STATE_MIGRATION_DONE:
        return list(STATE_MIGRATION_WARNINGS)
    if CONFIG_FILE != _DEFAULT_CONFIG_FILE or ASSET_INDEX_FILE != _DEFAULT_ASSET_INDEX_FILE:
        return []
    root = library_state.user_data_directory(
        system=sys.platform, home=os.path.expanduser("~"), environment=os.environ,
    )
    executable = sys.executable if getattr(sys, "frozen", False) else None
    roots = library_state.legacy_state_directories(
        executable=executable, source=__file__,
    )
    warnings = library_state.migrate_legacy_state(roots, root)
    STATE_MIGRATION_WARNINGS = list(warnings)
    _STATE_MIGRATION_DONE = True
    return list(warnings)


@serialized_config
def set_active_library_path(path):
    """Persist the app-wide User Library selection before publishing it in memory."""
    global ACTIVE_LIBRARY_PATH
    path = os.path.abspath(os.path.normpath(os.fspath(path)))
    if not os.path.isdir(path):
        raise ValueError(f"Choose an existing User Library folder: {path}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
        data = _validate_config(json.load(handle))
    data["ACTIVE_LIBRARY_PATH"] = path
    _write_config(data)
    ACTIVE_LIBRARY_PATH = path
    return path

@serialized_config
def _write_config(data, create_backup=True, *, expected_content=_UNSPECIFIED_CONFIG):
    """Writes configuration through a temporary file so interrupted writes do not corrupt it."""
    _validate_config(data)
    directory = os.path.dirname(os.path.abspath(CONFIG_FILE))
    os.makedirs(directory, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory,
            prefix=".library-config-", suffix=".tmp", delete=False
        ) as handle:
            temporary_path = handle.name
            json.dump(data, handle, indent=4)
            handle.flush()
            os.fsync(handle.fileno())
        if expected_content is not _UNSPECIFIED_CONFIG:
            current = None
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "rb") as handle:
                    current = handle.read()
            if current != expected_content:
                raise ValueError("Rules or profile changed during review. Retry with current settings.")
        if create_backup and os.path.exists(CONFIG_FILE):
            shutil.copy2(CONFIG_FILE, f"{CONFIG_FILE}.bak")
            backup_config()
        os.replace(temporary_path, CONFIG_FILE)
    finally:
        if temporary_path is not None and os.path.exists(temporary_path):
            os.unlink(temporary_path)


@serialized_config
def save_ignored_directories(directories):
    """Persist exclusions before publishing them to the shared in-memory state."""
    with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
        data = _validate_config(json.load(handle))
    data["IGNORED_DIRECTORIES"] = sorted(set(directories) | {"No Key Info"})
    _write_config(data)
    _apply_config_values(data)


def pending_legacy_exclusions():
    """Find unreviewed safety exclusions in registered legacy profiles."""
    with open(CONFIG_FILE, encoding="utf-8") as handle:
        current = _validate_config(json.load(handle))
    reviewed = current.get("LEGACY_EXCLUSIONS_REVIEWED", {})
    if not isinstance(reviewed, dict):
        raise ValueError("Legacy exclusion review settings must be a mapping.")
    existing = {value.casefold() for value in current.get("IGNORED_DIRECTORIES", [])}
    pending = []
    for path in library_state.legacy_profile_paths(os.path.dirname(os.path.abspath(CONFIG_FILE))):
        if not os.path.lexists(path):
            continue
        if os.path.islink(path) or not os.path.isfile(path):
            raise ValueError(f"Cannot safely review legacy profile: {path}")
        with open(path, "rb") as handle:
            contents = handle.read()
        digest = hashlib.sha256(contents).hexdigest()
        if reviewed.get(path) == digest:
            continue
        data = _validate_config(json.loads(contents))
        missing = sorted({
            value for value in data.get("IGNORED_DIRECTORIES", [])
            if value.casefold() not in existing
        })
        if missing:
            pending.append({"path": path, "digest": digest, "missing": missing})
    return pending


@serialized_config
def merge_legacy_exclusions(path, *, expected_digest=None):
    """Merge only safety exclusions, preserving the current profile's other settings."""
    path = os.path.abspath(os.fspath(path))
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError("Choose an existing, unlinked legacy profile.")
    with open(path, "rb") as handle:
        contents = handle.read()
    digest = hashlib.sha256(contents).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("Legacy profile changed during review. Review it again.")
    legacy = _validate_config(json.loads(contents))
    with open(CONFIG_FILE, encoding="utf-8") as handle:
        current = _validate_config(json.load(handle))
    current["IGNORED_DIRECTORIES"] = sorted(
        set(current.get("IGNORED_DIRECTORIES", []))
        | set(legacy.get("IGNORED_DIRECTORIES", [])) | {"No Key Info"}
    )
    reviewed = current.setdefault("LEGACY_EXCLUSIONS_REVIEWED", {})
    if not isinstance(reviewed, dict):
        raise ValueError("Legacy exclusion review settings must be a mapping.")
    reviewed[path] = digest
    _write_config(current)
    _apply_config_values(current)
    return list(IGNORED_DIRECTORIES)

CONFIG_BACKUP_DIR = "config_backups"
CONFIG_BACKUP_LIMIT = 10
MOVE_LOG_DIR = "move_logs"

def _backup_dir():
    if os.path.isabs(CONFIG_BACKUP_DIR):
        return CONFIG_BACKUP_DIR
    return os.path.join(os.path.dirname(os.path.abspath(CONFIG_FILE)), CONFIG_BACKUP_DIR)

def _move_log_dir():
    if os.path.isabs(MOVE_LOG_DIR):
        return MOVE_LOG_DIR
    return os.path.join(os.path.dirname(os.path.abspath(ASSET_INDEX_FILE)), MOVE_LOG_DIR)

def backup_config():
    """Saves a timestamped copy of the rules file and keeps only the newest few."""
    if not os.path.exists(CONFIG_FILE):
        return None
    os.makedirs(_backup_dir(), exist_ok=True)
    newest = list_config_backups()[:1]
    if newest:
        try:
            with open(newest[0], 'rb') as a, open(CONFIG_FILE, 'rb') as b:
                if a.read() == b.read():
                    return newest[0]
        except OSError:
            pass
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = os.path.join(_backup_dir(), f"library_config_{stamp}.json")
    shutil.copy2(CONFIG_FILE, target)
    for old in list_config_backups()[CONFIG_BACKUP_LIMIT:]:
        try:
            os.remove(old)
        except OSError:
            pass
    return target

def list_config_backups():
    """Backup file paths, newest first."""
    folder = _backup_dir()
    if not os.path.isdir(folder):
        return []
    return sorted(
        (os.path.join(folder, name) for name in os.listdir(folder)
         if name.startswith("library_config_") and name.endswith(".json")),
        reverse=True
    )

@serialized_config
def restore_config_backup(path):
    """Restores a backup, first saving the current rules so the restore itself can be reverted."""
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    _validate_config(data)
    _write_config(data)
    load_external_config()

def _default_rule_core(pattern):
    """First plain word of a rule pattern, e.g. 'kick' for both the \\bkick(s)?\\b and boundary-group styles."""
    cleaned = pattern.replace("(?:^|[^a-zA-Z0-9])", " ").replace("(?:$|[^a-zA-Z0-9])", " ")
    match = re.search(r"[a-z0-9]+", re.sub(r"\\[a-zA-Z]", " ", cleaned).lower())
    return match.group(0) if match else pattern

def missing_default_rules():
    """Built-in rules that are no longer present, in the style used by the user's own rules.
    A default sound rule counts as present if any rule sending to the same folder starts with the same word."""
    defaults = _default_config()
    missing = {}
    drum_absent = {}
    for pattern, folder in defaults["DRUM_KEYWORDS"].items():
        core = _default_rule_core(pattern)
        present = any(
            target == folder and core in _default_rule_core(existing)
            or existing == pattern
            for existing, target in DRUM_KEYWORDS.items()
        )
        if not present:
            style = pattern.replace("(?:^|[^a-zA-Z0-9])", "\\b").replace("(?:$|[^a-zA-Z0-9])", "\\b")
            drum_absent[style] = folder
    if drum_absent:
        missing["DRUM_KEYWORDS"] = drum_absent
    for key, current_rules in (("SYNTH_EXTS", SYNTH_EXTS), ("NATIVE_EXTS", NATIVE_EXTS)):
        absent = {k: v for k, v in defaults[key].items() if k not in current_rules}
        if absent:
            missing[key] = absent
    return missing

def library_status_summary():
    """Cheap snapshot for the Home tab."""
    summary = {"sounds": None, "rules": 0, "rules_enabled": 0, "suggestions": 0,
               "last_cleanup": None, "last_cleanup_files": 0, "backups": len(list_config_backups())}
    summary["rules"] = len(DRUM_KEYWORDS)
    summary["rules_enabled"] = sum(
        1 for pattern in DRUM_KEYWORDS if RULE_METADATA.get(pattern, {}).get("enabled", True)
    )
    summary["suggestions"] = sum(
        1 for candidate in LEARNED_RULE_CANDIDATES if is_reviewable_learning_candidate(candidate)
    )
    if os.path.exists(ASSET_INDEX_FILE):
        try:
            summary["sounds"] = count_indexed_assets()
        except sqlite3.Error:
            summary["sounds"] = None
    log = latest_move_log()
    if log:
        summary["last_cleanup_files"], summary["last_cleanup"] = describe_move_log(log)
    return summary

def _new_move_log_path():
    os.makedirs(_move_log_dir(), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    descriptor, path = tempfile.mkstemp(prefix=f"moves_{stamp}_", suffix=".jsonl", dir=_move_log_dir())
    os.close(descriptor)
    return path


_MOVE_LOG_LOCK = threading.RLock()


def _append_move_record(log_path, source, destination, **details):
    record_id = details.setdefault("record_id", uuid.uuid4().hex)
    with _MOVE_LOG_LOCK:
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(json.dumps({
                "source": os.path.normpath(source),
                "destination": os.path.normpath(destination), **details,
            }) + "\n")
            log.flush()
            os.fsync(log.fileno())
    return record_id


def _save_move_records(path, records):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(path)),
            suffix=".tmp", delete=False,
        ) as handle:
            temporary = handle.name
            for record in records:
                handle.write(json.dumps(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def _transfer_application(reason, confidence, tags, *, log_path=None, record_id=None, direction="forward"):
    return {
        "version": 1, "index": os.path.abspath(ASSET_INDEX_FILE),
        "reason": reason, "confidence": confidence, "tags": list(tags),
        "log_path": os.path.abspath(log_path) if log_path else None,
        "record_id": record_id, "direction": direction,
    }


def _application_move_record(journal):
    application = journal["application"]
    if (not isinstance(application, dict) or application.get("version") != 1
            or application.get("direction") not in {"forward", "undo"}
            or not isinstance(application.get("reason"), str)
            or not isinstance(application.get("confidence"), (int, float))
            or not isinstance(application.get("tags"), list)
            or not all(isinstance(tag, str) for tag in application["tags"])):
        raise ValueError("Invalid application recovery intent; journal retained.")
    mapped_index = library_state.resolve_legacy_path(
        application.get("index", ""), os.path.join(os.path.dirname(CONFIG_FILE), "legacy_path_aliases.json")
    )
    if mapped_index != os.path.abspath(ASSET_INDEX_FILE):
        raise ValueError("Recovery belongs to a different index/profile; reopen the original manager folder.")
    ableton_tags._check_transfer_path(ASSET_INDEX_FILE)
    original_log_path = application.get("log_path")
    if original_log_path is None:
        if not journal["copy"] or application.get("record_id") is not None:
            raise ValueError("Move recovery is missing its undo record; journal retained.")
        return None, None
    log_path = library_state.resolve_legacy_path(
        original_log_path, os.path.join(os.path.dirname(CONFIG_FILE), "legacy_path_aliases.json")
    )
    if (not isinstance(log_path, str) or not os.path.isabs(log_path)
            or os.path.dirname(log_path) != os.path.abspath(_move_log_dir())
            or not os.path.basename(log_path).startswith("moves_")
            or not log_path.endswith(".jsonl")):
        raise ValueError("Recovery undo log is outside this profile; journal retained.")
    ableton_tags._check_transfer_path(log_path)
    with open(log_path, encoding="utf-8") as handle:
        records = [json.loads(line) for line in handle if line.strip()]
    if any(not isinstance(record, dict) for record in records):
        raise ValueError("Invalid recovery undo log entries; journal retained.")
    matching = [record for record in records if record.get("record_id") == application.get("record_id")]
    if not application.get("record_id") or len(matching) != 1:
        raise ValueError("Recovery undo record is missing or ambiguous; journal retained.")
    record = matching[0]
    first, second = (
        ("destination", "source") if application["direction"] == "undo" else ("source", "destination")
    )
    if any(os.path.normcase(os.path.abspath(record[key])) != os.path.normcase(journal[target])
           for key, target in ((first, "source"), (second, "destination"))):
        raise ValueError("Recovery undo paths changed; journal retained.")
    identity = record.get("destination_identity") or (
        _file_identity(record["recovery"]) if record.get("operation") == "duplicate" else None
    )
    if identity is None or any(identity[key] != journal["source_identity"][key] for key in ("size", "sha256")):
        raise ValueError("Recovery undo identity changed; journal retained.")
    return records, record


def _reconcile_transfer_application(journal, outcome):
    if journal.get("application") is None:
        return
    with _MOVE_LOG_LOCK:
        records, record = _application_move_record(journal)
        if outcome == "validate":
            return
        application = journal["application"]
        if outcome == "committed":
            destination = journal["destination"]
            try:
                connection = _asset_index_connection()
                try:
                    index_asset(
                        destination, os.path.dirname(destination), application["reason"],
                        application["confidence"], application["tags"],
                        previous_path=journal["source"] if not journal["copy"] else None,
                        _connection=connection,
                    )
                    _cache_ableton_tags(connection, destination, {
                        os.path.normcase(destination): ableton_tags.sample_tags(destination),
                    })
                    connection.commit()
                finally:
                    connection.close()
            except (OSError, ValueError, sqlite3.Error) as error:
                raise OSError(f"Transfer audio committed but index reconciliation failed; recovery retained: {error}") from error
            ableton_tags._transfer_checkpoint("application_index_committed")
        if record is not None:
            if application["direction"] == "forward":
                if outcome == "rolled_back":
                    record["undo_complete"] = True
                    record["transfer_rolled_back"] = True
                    _save_move_records(application["log_path"], records)
            elif outcome == "committed":
                record["undo_files_restored"] = True
                record["undo_complete"] = True
                _save_move_records(application["log_path"], records)
            ableton_tags._transfer_checkpoint("application_undo_committed")


def recover_library_transfers(paths):
    """Recover files and replay their recorded index/undo changes before removing journals."""
    return ableton_tags.recover_transfers(paths, reconcile=_reconcile_transfer_application)


def recover_startup_transfers(library_root):
    """Recover pending transfer journals in the active library and app move history."""
    journals = set()
    errors = []
    if os.path.lexists(library_root):
        try:
            journals.update(ableton_tags.find_transfer_recovery(library_root))
        except (OSError, ValueError) as error:
            errors.append(f"Could not scan active User Library for interrupted transfers: {error}")

    log_directory = _move_log_dir()
    if os.path.lexists(log_directory):
        try:
            ableton_tags._check_transfer_path(log_directory)
            for name in sorted(os.listdir(log_directory)):
                if not name.startswith("moves_") or not name.endswith(".jsonl"):
                    continue
                log_path = os.path.join(log_directory, name)
                try:
                    ableton_tags._check_transfer_path(log_path)
                    with open(log_path, encoding="utf-8") as handle:
                        records = [json.loads(line) for line in handle if line.strip()]
                    if any(not isinstance(record, dict) for record in records):
                        raise ValueError(f"Invalid move-log records: {log_path}")
                    alias_file = os.path.join(os.path.dirname(CONFIG_FILE), "legacy_path_aliases.json")
                    recovery_directories = set()
                    for record in records:
                        for key in ("source", "destination"):
                            sample = record.get(key)
                            if not isinstance(sample, str) or not os.path.isabs(sample):
                                continue
                            recovery_directory = (
                                Path(sample).absolute().parent / "Ableton Folder Info"
                                / ableton_tags._RECOVERY_FOLDER
                            )
                            recovery_directories.add(recovery_directory)
                    for recovery_directory in recovery_directories:
                        if not os.path.lexists(recovery_directory):
                            continue
                        ableton_tags._check_transfer_path(recovery_directory)
                        for journal_path in recovery_directory.glob("*.json"):
                            ableton_tags._check_transfer_path(journal_path)
                            with journal_path.open(encoding="utf-8") as journal_file:
                                journal = json.load(journal_file)
                            if not isinstance(journal, dict):
                                raise ValueError(f"Invalid transfer recovery journal: {journal_path}")
                            application = journal.get("application")
                            if not isinstance(application, dict):
                                continue
                            journal_log = application.get("log_path")
                            if not isinstance(journal_log, str):
                                continue
                            mapped_log = library_state.resolve_legacy_path(journal_log, alias_file)
                            if os.path.normcase(mapped_log) == os.path.normcase(os.path.abspath(log_path)):
                                journals.add(str(journal_path))
                except (OSError, ValueError, KeyError, TypeError) as error:
                    errors.append(f"Could not inspect move history {log_path}: {error}")
        except (OSError, ValueError) as error:
            errors.append(f"Could not scan application move history: {error}")

    recovered = recover_library_transfers(sorted(journals))
    return {
        "journals_found": len(journals),
        "recovered": recovered["recovered"],
        "errors": errors + recovered["errors"],
    }


def _recover_move_log_transfers(log_path, records):
    pending = set()
    folders = set()
    for record in records:
        for key in ("source", "destination"):
            folders.add(Path(record[key]).absolute().parent / "Ableton Folder Info" / ableton_tags._RECOVERY_FOLDER)
    for folder in folders:
        ableton_tags._check_transfer_path(folder)
        for path in folder.glob("*.json"):
            ableton_tags._check_transfer_path(path)
            with path.open(encoding="utf-8") as handle:
                journal = json.load(handle)
            if not isinstance(journal, dict):
                raise ValueError(f"Invalid transfer recovery journal: {path}")
            application = journal.get("application")
            if isinstance(application, dict) and application.get("log_path") == os.path.abspath(log_path):
                pending.add(str(path))
    return recover_library_transfers(sorted(pending))

def latest_move_log():
    """Newest move log that still has something to undo, or None."""
    folder = _move_log_dir()
    if not os.path.isdir(folder):
        return None
    logs = sorted(
        (os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".jsonl")),
        reverse=True
    )
    for log in logs:
        if os.path.getsize(log) > 0 and describe_move_log(log)[0]:
            return log
    return None

def describe_move_log(log_path):
    """Returns (unresolved_file_count, created_text) for a move log."""
    with open(log_path, 'r', encoding='utf-8') as f:
        count = sum(1 for line in f if line.strip() and not json.loads(line).get("undo_complete"))
    created = datetime.datetime.fromtimestamp(os.path.getmtime(log_path)).strftime("%b %d, %Y %I:%M %p")
    return count, created

def undo_move_log(log_path, progress=None, *, record_ids=None):
    """Restore all or explicitly selected log entries without overwriting files."""
    with open(log_path, 'r', encoding='utf-8') as f:
        records = [json.loads(line) for line in f if line.strip()]
    if record_ids is not None:
        record_ids = set(record_ids)
        known_ids = {record.get("record_id") for record in records}
        if not record_ids or None in record_ids or not record_ids <= known_ids:
            raise ValueError("Select existing move-log record IDs before attempting undo.")
    selected_records = [
        record for record in records
        if record_ids is None or record.get("record_id") in record_ids
    ]
    results = {"restored": 0, "skipped": 0, "errors": []}
    recovered = _recover_move_log_transfers(log_path, selected_records)
    if recovered["errors"]:
        results["errors"].extend(recovered["errors"])
        return results
    if recovered["recovered"]:
        with open(log_path, encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
    connection = None
    try:
        connection = _asset_index_connection()
    except (OSError, sqlite3.Error) as error:
        connection = None
        results["errors"].append(f"Undo index could not be opened: {error}")
    touched_dirs = set()
    completed = []
    for index, record in enumerate(reversed(records)):
        if record_ids is not None and record.get("record_id") not in record_ids:
            continue
        if record.get("undo_complete"):
            continue
        source, destination = record["source"], record["destination"]
        try:
            already_restored = record.get("undo_files_restored", False)
            if (record.get("operation") != "duplicate" and not os.path.lexists(destination)
                    and os.path.isfile(source) and not os.path.islink(source)
                    and record.get("destination_identity") is not None
                    and _file_identity(source) == record["destination_identity"]):
                already_restored = True
            if not already_restored and (not os.path.exists(destination) or os.path.exists(source)):
                results["skipped"] += 1
                continue
            if record.get("operation") == "duplicate":
                if not already_restored and connection is not None and "expected_destination_personal" in record:
                    actual = dict(connection.execute(
                        "SELECT tag, enabled FROM asset_tags WHERE asset_path = ? AND source = 'personal'",
                        (destination,),
                    ))
                    if actual != record["expected_destination_personal"]:
                        raise ValueError("Duplicate destination app tags changed; recovery was retained.")
                if not already_restored:
                    ableton_tags.restore_duplicate(
                        source, destination, record["recovery"],
                        record["source_live_tags"], record["destination_live_tags"],
                        record["merged_live_tags"],
                    )
                    record["undo_files_restored"] = True
                    results["restored"] += 1
                if connection is not None:
                    for path, snapshot in (
                        (source, record.get("source_index")),
                        (destination, record.get("destination_index")),
                    ):
                        connection.execute("DELETE FROM asset_tags WHERE asset_path = ?", (path,))
                        connection.execute("DELETE FROM assets WHERE path = ?", (path,))
                        if snapshot is not None:
                            index_asset(
                                path, snapshot["destination"], snapshot["reason"],
                                snapshot["confidence"], snapshot["tags"] + snapshot["disabled_tags"],
                                _connection=connection,
                            )
                            stored_tags = snapshot.get("stored_tags")
                            if stored_tags is None:
                                stored_tags = [
                                    (tag, enabled,
                                     "ableton" if tag.startswith(ableton_tags.CACHE_PREFIX) else
                                     "generated" if tag.startswith(("category:", "name:")) else "personal")
                                    for enabled, values in ((1, snapshot["tags"]), (0, snapshot["disabled_tags"]))
                                    for tag in values
                                ]
                            connection.executemany(
                                "INSERT OR REPLACE INTO asset_tags (asset_path, tag, enabled, source) "
                                "VALUES (?, ?, ?, ?)",
                                [(path, tag, enabled, source) for tag, enabled, source in stored_tags],
                            )
                            _cache_ableton_tags(connection, path, {
                                os.path.normcase(os.path.abspath(path)): ableton_tags.sample_tags(path)
                            })
                    completed.append(record)
                continue
            expected = record.get("destination_identity")
            if expected is None:
                results["errors"].append(
                    f"Legacy undo entry has no destination identity; review and restore manually: {destination}"
                )
                results["skipped"] += 1
                continue
            restored_path = source if already_restored else destination
            if os.path.islink(restored_path) or _file_identity(restored_path) != expected:
                results["skipped"] += 1
                results["errors"].append(f"Destination changed since cleanup; left in place: {destination}")
                continue
            if not already_restored:
                os.makedirs(os.path.dirname(source), exist_ok=True)
                if connection is not None:
                    connection.commit()
                    for finished in completed:
                        finished["undo_complete"] = True
                previous = get_indexed_asset(destination)
                record.setdefault("record_id", uuid.uuid4().hex)
                with _MOVE_LOG_LOCK:
                    _save_move_records(log_path, records)
                application = _transfer_application(
                    previous["reason"] if previous else "undo_cleanup",
                    previous["confidence"] if previous else 1.0,
                    [tag for tag in previous["tags"] if not tag.startswith("category:")] if previous else [],
                    log_path=log_path, record_id=record["record_id"], direction="undo",
                )
                try:
                    ableton_tags.transfer_sample(
                        destination, source, application=application, reconcile=_reconcile_transfer_application,
                    )
                except (OSError, ValueError) as error:
                    if (not os.path.lexists(destination) and os.path.isfile(source)
                            and _file_identity(source) == expected):
                        record["undo_files_restored"] = True
                        results["restored"] += 1
                        raise OSError(
                            f"File restored but index update failed; recovery journal retained for retry: {error}"
                        ) from error
                    raise
                record["undo_files_restored"] = True
                record["undo_complete"] = True
                touched_dirs.add(os.path.dirname(destination))
                results["restored"] += 1
                completed.append(record)
                continue
            if connection is not None:
                connection.execute("SAVEPOINT undo_asset")
                try:
                    connection.execute(
                        "UPDATE assets SET path = ?, filename = ?, destination = ? WHERE path = ?",
                        (source, os.path.basename(source), os.path.dirname(source), destination)
                    )
                    connection.execute(
                        "DELETE FROM asset_tags WHERE asset_path = ? AND tag LIKE 'category:%'", (destination,))
                    connection.execute("UPDATE asset_tags SET asset_path = ? WHERE asset_path = ?", (source, destination))
                    _cache_ableton_tags(
                        connection, source,
                        {os.path.normcase(os.path.abspath(source)): ableton_tags.sample_tags(source)}
                    )
                    connection.execute("RELEASE SAVEPOINT undo_asset")
                    completed.append(record)
                except (sqlite3.Error, OSError, ValueError) as error:
                    connection.execute("ROLLBACK TO SAVEPOINT undo_asset")
                    connection.execute("RELEASE SAVEPOINT undo_asset")
                    results["errors"].append(f"File restored but index update failed for {source}: {error}")
        except (OSError, ValueError, sqlite3.Error) as error:
            results["errors"].append(f"{destination}: {error}")
        if progress and index % 200 == 0:
            progress(index + 1, len(records))
    if connection is not None:
        try:
            connection.commit()
            for record in completed:
                record["undo_complete"] = True
        except sqlite3.Error as error:
            results["errors"].append(f"Files restored but index changes could not be saved: {error}")
        finally:
            connection.close()
    for folder in sorted(touched_dirs, key=len, reverse=True):
        try:
            os.rmdir(folder)
        except OSError:
            pass
    if (not results["errors"] and not results["skipped"]
            and all(record.get("undo_complete") for record in records)):
        os.replace(log_path, log_path + ".undone")
    elif any(record.get("undo_files_restored") or record.get("undo_complete") for record in records):
        try:
            _save_move_records(log_path, records)
        except OSError as error:
            results["errors"].append(f"Undo retry checkpoint could not be saved: {error}")
    return results

def _sidebar_cache_path():
    return os.path.join(os.path.dirname(os.path.abspath(ASSET_INDEX_FILE)), "sidebar_cache.json")

def _index_fingerprint():
    try:
        info = os.stat(ASSET_INDEX_FILE)
    except OSError:
        return None
    return [info.st_mtime_ns, info.st_size]

def load_sidebar_snapshot(library_root):
    """Returns cached sidebar data if the asset index has not changed since it was saved."""
    try:
        with open(_sidebar_cache_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if (
            data.get("fingerprint") == _index_fingerprint()
            and data.get("library_root") == str(library_root)
            and data.get("version") == 2
        ):
            return {
                "static_counts": data["static_counts"],
                "favorites": data["favorites"],
                "tags": [(tag, count) for tag, count in data["tags"]],
            }
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None

def save_sidebar_snapshot(library_root, static_counts, favorites, tags, fingerprint):
    """Stores sidebar data. The fingerprint must be read before the data was queried."""
    if fingerprint is None:
        return
    payload = {
        "version": 2, "fingerprint": fingerprint, "library_root": str(library_root),
        "static_counts": static_counts, "favorites": favorites,
        "tags": [[tag, count] for tag, count in tags],
    }
    temp_path = _sidebar_cache_path() + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, _sidebar_cache_path())
    except OSError:
        pass

def _asset_index_connection():
    connection = sqlite3.connect(ASSET_INDEX_FILE)
    schema_key = os.path.abspath(ASSET_INDEX_FILE)
    with _ASSET_SCHEMA_LOCK:
        schema_ready = schema_key in _ASSET_SCHEMA_READY
        if schema_ready:
            return connection
    connection.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            path TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_time REAL NOT NULL,
            destination TEXT NOT NULL,
            classification_reason TEXT NOT NULL,
            confidence REAL NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS asset_tags (
            asset_path TEXT NOT NULL,
            tag TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            source TEXT NOT NULL DEFAULT 'personal',
            PRIMARY KEY (asset_path, tag),
            FOREIGN KEY (asset_path) REFERENCES assets(path) ON DELETE CASCADE
        )
    """)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_tags_enabled_tag_path "
        "ON asset_tags (enabled, tag, asset_path)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_asset_tags_path_enabled_tag "
        "ON asset_tags (asset_path, enabled, tag)"
    )
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(asset_tags)")
    }
    if "enabled" not in columns:
        connection.execute(
            "ALTER TABLE asset_tags ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1"
        )
    if "source" not in columns:
        connection.execute(
            "ALTER TABLE asset_tags ADD COLUMN source TEXT NOT NULL DEFAULT 'personal'"
        )
    connection.execute(
        "UPDATE asset_tags SET source = 'generated' "
        "WHERE tag LIKE 'category:%' OR tag LIKE 'name:%'"
    )
    connection.execute(
        "CREATE VIEW IF NOT EXISTS visible_asset_tags AS "
        "SELECT * FROM asset_tags WHERE source IN ('generated', 'ableton') OR tag = 'favorite'"
    )
    connection.commit()
    with _ASSET_SCHEMA_LOCK:
        _ASSET_SCHEMA_READY.add(schema_key)
    return connection

def index_asset(
    path, destination, reason, confidence, tags, previous_path=None,
    _connection=None
):
    """Stores classification and tags, optionally migrating an indexed file after a move."""
    file_stat = os.stat(path)
    normalized_path = os.path.normpath(path)
    normalized_previous_path = (
        os.path.normpath(previous_path) if previous_path else None
    )
    connection = _connection or _asset_index_connection()
    try:
        if normalized_previous_path and normalized_previous_path != normalized_path:
            previous_exists = connection.execute(
                "SELECT 1 FROM assets WHERE path = ?",
                (normalized_previous_path,)
            ).fetchone()
            if previous_exists:
                connection.execute(
                    "INSERT OR IGNORE INTO assets "
                    "SELECT ?, filename, size, modified_time, destination, "
                    "classification_reason, confidence, updated_at "
                    "FROM assets WHERE path = ?",
                    (normalized_path, normalized_previous_path)
                )
                connection.execute(
                    "INSERT OR IGNORE INTO asset_tags (asset_path, tag, enabled, source) "
                    "SELECT ?, tag, enabled, source FROM asset_tags WHERE asset_path = ? "
                    "AND source != 'ableton'",
                    (normalized_path, normalized_previous_path)
                )
                connection.execute(
                    "DELETE FROM asset_tags WHERE asset_path = ?",
                    (normalized_previous_path,)
                )
                connection.execute(
                    "DELETE FROM assets WHERE path = ?",
                    (normalized_previous_path,)
                )
        connection.execute(
            """
            INSERT INTO assets
                (path, filename, size, modified_time, destination,
                 classification_reason, confidence, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(path) DO UPDATE SET
                filename=excluded.filename,
                size=excluded.size,
                modified_time=excluded.modified_time,
                destination=excluded.destination,
                classification_reason=excluded.classification_reason,
                confidence=excluded.confidence,
                updated_at=excluded.updated_at
            """,
            (normalized_path, os.path.basename(path), file_stat.st_size,
             file_stat.st_mtime, destination, reason, confidence)
        )
        generated_tags = sorted({
            tag for tag in tags
            if tag and (tag.startswith("category:") or tag.startswith("name:"))
        })
        if generated_tags:
            placeholders = ",".join("?" for _tag in generated_tags)
            connection.execute(
                f"DELETE FROM asset_tags WHERE asset_path = ? "
                f"AND source = 'generated' AND tag NOT IN ({placeholders})",
                [normalized_path, *generated_tags]
            )
        else:
            connection.execute(
                "DELETE FROM asset_tags WHERE asset_path = ? AND source = 'generated'",
                (normalized_path,)
            )
        connection.executemany(
            "INSERT OR IGNORE INTO asset_tags "
            "(asset_path, tag, enabled, source) VALUES (?, ?, 1, ?)",
            [
                (normalized_path, tag, "generated" if tag.startswith(("category:", "name:")) else "personal")
                for tag in sorted(set(tags))
                if tag and (tag == "favorite" or tag.startswith(("category:", "name:")))
            ]
        )
        if _connection is None:
            connection.commit()
    finally:
        if _connection is None:
            connection.close()

def _prune_missing_assets(connection, library_root):
    """Removes confirmed-missing and AppleDouble metadata records within scope."""
    root = os.path.normpath(library_root)
    if not stat.S_ISDIR(os.stat(root).st_mode):
        raise NotADirectoryError(root)
    root_clause, parameters = _library_root_clause(root)
    paths = connection.execute(
        f"SELECT a.path FROM assets a WHERE {root_clause}", parameters
    ).fetchall()
    missing = []
    for (path,) in paths:
        if ableton_tags.is_metadata_stub(path):
            missing.append((path,))
            continue
        try:
            os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            missing.append((path,))
    connection.executemany(
        "DELETE FROM asset_tags WHERE asset_path = ?", missing
    )
    connection.executemany("DELETE FROM assets WHERE path = ?", missing)
    return len(missing)


def index_existing_library(library_root):
    """Synchronizes supported library files and removes confirmed-missing records."""
    root = os.path.normpath(library_root)
    if not stat.S_ISDIR(os.stat(root).st_mode):
        raise NotADirectoryError(root)
    indexed_count = 0
    scanned_paths = []
    live_assignments = {}
    stack = [root]
    visited = set()
    connection = _asset_index_connection()
    try:
        for ancestor in Path(os.path.abspath(root)).parents:
            for path, tags in ableton_tags.read_folder_tags(str(ancestor)).items():
                live_assignments.setdefault(path, set()).update(tags)
        existing_assets = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT path, size, modified_time FROM assets"
            )
        }
        while stack:
            current = stack.pop()
            normalized_current = os.path.normpath(current)
            if normalized_current in visited:
                continue
            visited.add(normalized_current)
            folder_tags = ableton_tags.read_folder_tags(normalized_current)
            for path, tags in folder_tags.items():
                live_assignments.setdefault(path, set()).update(tags)
            entries = os.scandir(normalized_current)
            with entries:
                for entry in entries:
                    if ableton_tags.is_metadata_stub(entry.name):
                        continue
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name.lower() not in {
                            ignored.lower() for ignored in IGNORED_DIRECTORIES
                        }:
                            stack.append(entry.path)
                        continue
                    if not entry.is_file():
                        continue
                    extension = os.path.splitext(entry.name)[1].lower()
                    if extension not in INDEXABLE_SOUND_EXTS:
                        continue
                    file_stat = entry.stat()
                    normalized_path = os.path.normpath(entry.path)
                    indexed_count += 1
                    scanned_paths.append(normalized_path)
                    if existing_assets.get(normalized_path) == (
                        file_stat.st_size, file_stat.st_mtime
                    ):
                        continue
                    destination = os.path.dirname(entry.path)
                    tags = [f"category:{os.path.basename(destination)}"]
                    tags.extend(derive_filename_tags(entry.name))
                    index_asset(
                        entry.path, destination, "existing_library", 1.0,
                        sorted(set(tags)), _connection=connection
                    )
        for path in scanned_paths:
            _cache_ableton_tags(connection, path, live_assignments)
        _prune_missing_assets(connection, root)
        connection.commit()
        return indexed_count
    finally:
        connection.close()

def _cache_ableton_tags(connection, path, assignments):
    """Replaces Live-derived cache rows only; sidecars remain authoritative."""
    connection.execute(
        "DELETE FROM asset_tags WHERE asset_path = ? AND source = 'ableton'", (path,)
    )
    tags = assignments.get(os.path.normcase(os.path.abspath(path)), [])
    connection.executemany(
        "INSERT INTO asset_tags (asset_path, tag, enabled, source) "
        "VALUES (?, ?, 1, 'ableton')",
        [(path, ableton_tags.CACHE_PREFIX + tag) for tag in tags]
    )


def refresh_live_tag_cache(paths):
    """Refreshes only Live-derived rows after an explicit sidecar operation."""
    assignments = {
        os.path.normcase(os.path.abspath(path)): ableton_tags.sample_tags(path)
        for path in paths
    }
    connection = _asset_index_connection()
    try:
        for path in paths:
            if connection.execute(
                "SELECT 1 FROM assets WHERE path = ?", (os.path.normpath(path),)
            ).fetchone() is None:
                raise ValueError(f"Sound is no longer indexed: {path}")
            _cache_ableton_tags(connection, os.path.normpath(path), assignments)
        connection.commit()
    finally:
        connection.close()

def get_indexed_asset(path):
    """Returns one indexed asset with its visible tags, or None when not indexed."""
    connection = _asset_index_connection()
    try:
        asset = connection.execute(
            "SELECT path, filename, size, modified_time, destination, "
            "classification_reason, confidence, updated_at FROM assets WHERE path = ?",
            (os.path.normpath(path),)
        ).fetchone()
        if asset is None:
            return None
        tag_rows = [
            row for row in connection.execute(
                "SELECT tag, enabled, source FROM visible_asset_tags WHERE asset_path = ? ORDER BY tag",
                (os.path.normpath(path),)
            )
        ]
        tags = [
            row[0] for row in tag_rows if row[1]
        ]
        disabled_tags = [
            row[0] for row in tag_rows if not row[1]
        ]
        return {
            "path": asset[0], "filename": asset[1], "size": asset[2],
            "modified_time": asset[3], "destination": asset[4],
            "reason": asset[5], "confidence": asset[6],
            "updated_at": asset[7], "tags": tags, "disabled_tags": disabled_tags,
            "ableton_tags": [
                row[0][len(ableton_tags.CACHE_PREFIX):] for row in tag_rows
                if row[1] and row[2] == "ableton"
            ]
        }
    finally:
        connection.close()

def get_asset_tags(path):
    """Returns active classification, Live and favorite tags; legacy app tags stay dormant."""
    connection = _asset_index_connection()
    try:
        return [
            row[0] for row in connection.execute(
                "SELECT tag FROM visible_asset_tags WHERE asset_path = ? AND enabled = 1 ORDER BY tag",
                (os.path.normpath(path),)
            )
        ]
    finally:
        connection.close()

def _snapshot_indexed_asset(path):
    """Includes dormant rows only for lossless recovery, never for classification or display."""
    snapshot = get_indexed_asset(path)
    if snapshot is not None:
        connection = _asset_index_connection()
        try:
            snapshot["stored_tags"] = connection.execute(
                "SELECT tag, enabled, source FROM asset_tags WHERE asset_path = ? ORDER BY tag",
                (os.path.normpath(path),),
            ).fetchall()
        finally:
            connection.close()
    return snapshot

def get_all_indexed_asset_tags():
    """Loads enabled indexed tags once for a sorter run."""
    connection = _asset_index_connection()
    try:
        tags_by_path = {}
        for asset_path, tag in connection.execute(
            "SELECT asset_path, tag FROM visible_asset_tags "
            "WHERE enabled = 1 ORDER BY asset_path, tag"
        ):
            tags_by_path.setdefault(asset_path, []).append(tag)
        return tags_by_path
    finally:
        connection.close()

def _read_routing_tags():
    """Read routing inputs without creating, migrating or updating the index."""
    path = Path(ASSET_INDEX_FILE).absolute()
    if not path.exists():
        return {}
    snapshot = None
    connection = None
    try:
        with path.open("rb") as stream:
            wal_mode = stream.read(20)[18:20] == b"\x02\x02"
        if wal_mode:
            # Even mode=ro creates WAL bookkeeping in the original directory.
            snapshot = tempfile.TemporaryDirectory(prefix="alm-routing-index-")
            wal = Path(str(path) + "-wal")
            inputs = [path] + ([wal] if wal.exists() else [])
            identities = {item: _file_identity(item) for item in inputs}
            for item in inputs:
                copied = Path(snapshot.name) / item.name
                shutil.copyfile(item, copied)
                if _file_identity(copied)["sha256"] != identities[item]["sha256"]:
                    raise ValueError("Routing index changed while taking a read-only snapshot.")
            if wal.exists() != (wal in identities) or any(
                _file_identity(item) != identity for item, identity in identities.items()
            ):
                raise ValueError("Routing index changed while taking a read-only snapshot.")
            path = Path(snapshot.name) / path.name
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "asset_tags" not in tables:
            raise ValueError("Existing index has no asset_tags table; repair it before previewing.")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(asset_tags)")}
        if not {"asset_path", "tag"} <= columns:
            raise ValueError("Existing index has an unsupported tag schema.")
        filters = []
        if "enabled" in columns:
            filters.append("enabled = 1")
        if "source" in columns:
            filters.append("(source IN ('generated', 'ableton') OR tag = 'favorite')")
        query = "SELECT asset_path, tag FROM asset_tags"
        if filters:
            query += " WHERE " + " AND ".join(filters)
        result = {}
        for asset_path, tag in connection.execute(query + " ORDER BY asset_path, tag"):
            result.setdefault(asset_path, []).append(tag)
        return result
    finally:
        if connection is not None:
            connection.close()
        if snapshot is not None:
            snapshot.cleanup()

def _parse_asset_search(search_text):
    """Splits simple browser syntax into positive and negative search constraints."""
    parsed = {"terms": [], "excluded_terms": [], "tags": [], "excluded_tags": [],
              "types": [], "bpms": [], "keys": [], "reasons": [],
              "any_tags": [], "live_states": [], "missing_groups": []}
    for raw_token in re.findall(r'"[^"]+"|\S+', search_text.lower()):
        token = raw_token.strip('"')
        excluded = token.startswith("-")
        if excluded:
            token = token[1:]
        if not token:
            continue
        name, separator, value = token.partition(":")
        target = None
        if separator and name in {"anytag", "live", "missing-group"}:
            if excluded or not value:
                raise ValueError(f"Invalid discovery filter: {raw_token}")
            if name == "live" and value not in {"none", "tagged"}:
                raise ValueError("Use live:none or live:tagged.")
            parsed[{"anytag": "any_tags", "live": "live_states", "missing-group": "missing_groups"}[name]].append(value)
            continue
        if separator and name in {"tag", "type", "bpm", "key", "reason"}:
            target = {
                "tag": "tags", "type": "types", "bpm": "bpms",
                "key": "keys", "reason": "reasons"
            }[name]
        if target:
            (parsed[f"excluded_{target}"] if excluded else parsed[target]).append(value)
        else:
            parsed["excluded_terms" if excluded else "terms"].append(token)
    return parsed


def _discovery_clauses(parsed):
    """Shared predicates for results, counts, selection snapshots, and tag facets."""
    clauses, parameters = [], []
    if parsed["any_tags"]:
        clauses.append(
            "EXISTS (SELECT 1 FROM visible_asset_tags sd WHERE sd.asset_path = a.path "
            "AND sd.enabled = 1 AND LOWER(sd.tag) IN ("
            + ",".join("?" for _tag in parsed["any_tags"]) + "))"
        )
        parameters.extend(parsed["any_tags"])
    for state in parsed["live_states"]:
        clauses.append(
            ("NOT " if state == "none" else "")
            + "EXISTS (SELECT 1 FROM visible_asset_tags sl WHERE sl.asset_path = a.path "
            "AND sl.enabled = 1 AND sl.source = 'ableton')"
        )
    for group in parsed["missing_groups"]:
        if "|" in group or not group.strip():
            raise ValueError("Missing-group filters require a single Live group name.")
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM visible_asset_tags sg WHERE sg.asset_path = a.path "
            "AND sg.enabled = 1 AND sg.source = 'ableton' "
            "AND LOWER(SUBSTR(sg.tag, 1, ?)) = ?)"
        )
        prefix = ableton_tags.CACHE_PREFIX + group + "|"
        parameters.extend([len(prefix), prefix])
    return clauses, parameters

def _library_root_clause(root_path, column="a.path"):
    """Returns a parameterized clause restricting paths to one directory tree."""
    if not root_path:
        return "", []
    normalized_root = os.path.normcase(os.path.normpath(root_path))
    prefix = os.path.join(normalized_root, "")
    escaped_prefix = prefix.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    return (
        f"(LOWER({column}) = LOWER(?) OR LOWER({column}) LIKE LOWER(?) ESCAPE '!')",
        [normalized_root, f"{escaped_prefix}%"],
    )

def _asset_rows_with_tags(connection, rows, paths_only=False):
    if paths_only:
        return list(dict.fromkeys(row[0] for row in rows))
    paths = [row[0] for row in rows]
    tags_by_path = {path: [] for path in paths}
    if paths:
        placeholders = ",".join("?" for _ in paths)
        tag_rows = connection.execute(
            f"SELECT asset_path, tag FROM visible_asset_tags "
            f"WHERE enabled = 1 AND asset_path IN ({placeholders}) ORDER BY tag",
            paths
        ).fetchall()
        for path, tag in tag_rows:
            tags_by_path[path].append(tag)
    return [
        {
            "path": path, "filename": filename, "destination": destination,
            "reason": reason, "confidence": confidence,
            "tags": tags_by_path[path]
        }
        for path, filename, destination, reason, confidence in rows
    ]

def list_indexed_assets(
    search_text="", tag_filter="", favorites_only=False, limit=250, offset=0,
    library_root=None, count_only=False, paths_only=False
):
    """Returns indexed assets using terms, exclusions, and structured browser filters."""
    connection = _asset_index_connection()
    try:
        clauses = []
        parameters = []
        root_clause, root_parameters = _library_root_clause(library_root)
        if root_clause:
            clauses.append(root_clause)
            parameters.extend(root_parameters)
        extension_clauses = " OR ".join(
            "LOWER(a.path) LIKE ?" for _extension in INDEXABLE_SOUND_SUFFIXES
        )
        clauses.append(f"({extension_clauses})")
        parameters.extend(f"%{extension}" for extension in INDEXABLE_SOUND_SUFFIXES)
        parsed = _parse_asset_search(search_text)
        discovery_clauses, discovery_parameters = _discovery_clauses(parsed)
        clauses.extend(discovery_clauses)
        parameters.extend(discovery_parameters)
        simple_collection = (
            not discovery_clauses
            and
            not parsed["terms"] and not parsed["excluded_terms"]
            and not parsed["tags"] and not parsed["excluded_tags"]
            and not parsed["bpms"] and not parsed["keys"]
            and not parsed["reasons"] and len(parsed["types"]) == 1
            and not favorites_only and not tag_filter.strip()
        )
        if simple_collection:
            collection_type = parsed["types"][0]
            if collection_type == "midi":
                collection_clause = (
                    "(LOWER(a.path) LIKE '%.mid' OR LOWER(a.path) LIKE '%.midi')"
                )
                collection_parameters = []
            elif collection_type in {"loop", "one-shot"}:
                folder_term = "loop" if collection_type == "loop" else "one-shot"
                collection_clause = (
                    "LOWER(a.destination) LIKE ? OR LOWER(a.path) LIKE ?"
                )
                collection_parameters = [f"%{folder_term}%", f"%{folder_term}%"]
            else:
                collection_clause = ""
                collection_parameters = []
            if collection_clause:
                where_sql = (
                    f"{root_clause + ' AND ' if root_clause else ''}"
                    f"({extension_clauses}) AND ({collection_clause})"
                )
                query_parameters = (
                    root_parameters
                    + [f"%{extension}" for extension in INDEXABLE_SOUND_EXTS]
                    + collection_parameters
                )
                if count_only:
                    return connection.execute(
                        f"SELECT COUNT(*) FROM assets a WHERE {where_sql}",
                        query_parameters
                    ).fetchone()[0]
                rows = connection.execute(
                    f"""
                    SELECT a.path, a.filename, a.destination,
                           a.classification_reason, a.confidence
                    FROM assets a
                    WHERE {where_sql}
                    ORDER BY a.filename COLLATE NOCASE
                    LIMIT ? OFFSET ?
                    """,
                    query_parameters + [limit, offset]
                ).fetchall()
                return _asset_rows_with_tags(connection, rows, paths_only)
        combined_collection_tag = (
            not discovery_clauses
            and
            bool(tag_filter.strip())
            and not favorites_only
            and not parsed["terms"] and not parsed["excluded_terms"]
            and not parsed["tags"] and not parsed["excluded_tags"]
            and not parsed["bpms"] and not parsed["keys"]
            and not parsed["reasons"] and len(parsed["types"]) == 1
        )
        if combined_collection_tag:
            collection_type = parsed["types"][0]
            if collection_type == "midi":
                collection_clause = (
                    "(LOWER(a.path) LIKE '%.mid' OR LOWER(a.path) LIKE '%.midi')"
                )
                collection_parameters = []
            elif collection_type in {"loop", "one-shot"}:
                folder_term = "loop" if collection_type == "loop" else "one-shot"
                collection_clause = (
                    "LOWER(a.destination) LIKE ? OR LOWER(a.path) LIKE ?"
                )
                collection_parameters = [f"%{folder_term}%", f"%{folder_term}%"]
            else:
                collection_clause = ""
                collection_parameters = []
            if collection_clause:
                where_sql = (
                    f"{root_clause + ' AND ' if root_clause else ''}"
                    f"({extension_clauses}) AND ({collection_clause})"
                )
                query_parameters = (
                    [tag_filter.strip().lower()]
                    + root_parameters
                    + [f"%{extension}" for extension in INDEXABLE_SOUND_EXTS]
                    + collection_parameters
                )
                if count_only:
                    return connection.execute(
                        f"""
                        SELECT COUNT(*) FROM assets a
                        JOIN visible_asset_tags tf ON tf.asset_path = a.path
                            AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?
                        WHERE {where_sql}
                        """,
                        query_parameters
                    ).fetchone()[0]
                rows = connection.execute(
                    f"""
                    SELECT a.path, a.filename, a.destination,
                           a.classification_reason, a.confidence
                    FROM assets a
                    JOIN visible_asset_tags tf ON tf.asset_path = a.path
                        AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?
                    WHERE {where_sql}
                    ORDER BY a.filename COLLATE NOCASE
                    LIMIT ? OFFSET ?
                    """,
                    query_parameters + [limit, offset]
                ).fetchall()
                return _asset_rows_with_tags(connection, rows, paths_only)
        simple_tag_filter = (
            not search_text.strip() and bool(tag_filter.strip())
            and not favorites_only
        )
        if simple_tag_filter:
            where_sql = (
                f"{root_clause + ' AND ' if root_clause else ''}"
                f"({extension_clauses})"
            )
            query_parameters = (
                [tag_filter.strip().lower()]
                + root_parameters
                + [f"%{extension}" for extension in INDEXABLE_SOUND_EXTS]
            )
            if count_only:
                return connection.execute(
                    f"""
                    SELECT COUNT(*) FROM assets a
                    JOIN visible_asset_tags tf ON tf.asset_path = a.path
                        AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?
                    WHERE {where_sql}
                    """,
                    query_parameters
                ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT a.path, a.filename, a.destination,
                       a.classification_reason, a.confidence
                FROM assets a
                JOIN visible_asset_tags tf ON tf.asset_path = a.path
                    AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?
                WHERE {root_clause + ' AND ' if root_clause else ''}
                      ({extension_clauses})
                ORDER BY a.filename COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                query_parameters
                + [limit, offset]
            ).fetchall()
            return _asset_rows_with_tags(connection, rows, paths_only)
        simple_favorites_filter = (
            not search_text.strip() and not tag_filter.strip()
            and favorites_only
        )
        if simple_favorites_filter:
            where_sql = (
                f"{root_clause + ' AND ' if root_clause else ''}"
                f"({extension_clauses})"
            )
            query_parameters = (
                root_parameters
                + [f"%{extension}" for extension in INDEXABLE_SOUND_EXTS]
            )
            if count_only:
                return connection.execute(
                    f"""
                    SELECT COUNT(*) FROM assets a
                    JOIN visible_asset_tags tf ON tf.asset_path = a.path
                        AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = 'favorite'
                    WHERE {where_sql}
                    """,
                    query_parameters
                ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT a.path, a.filename, a.destination,
                       a.classification_reason, a.confidence
                FROM assets a
                JOIN visible_asset_tags tf ON tf.asset_path = a.path
                    AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = 'favorite'
                WHERE {root_clause + ' AND ' if root_clause else ''}
                      ({extension_clauses})
                ORDER BY a.filename COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                query_parameters
                + [limit, offset]
            ).fetchall()
            return _asset_rows_with_tags(connection, rows, paths_only)
        simple_browser_query = not (
            parsed["terms"] or parsed["excluded_terms"] or parsed["tags"]
            or parsed["excluded_tags"] or parsed["types"] or parsed["bpms"]
            or parsed["keys"] or parsed["reasons"] or tag_filter.strip()
            or favorites_only or discovery_clauses
        )
        if simple_browser_query:
            rows = connection.execute(
                f"""
                SELECT a.path, a.filename, a.destination, a.classification_reason,
                       a.confidence
                FROM assets a
                WHERE {root_clause + ' AND ' if root_clause else ''}
                      ({extension_clauses})
                ORDER BY a.filename COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                root_parameters
                + [f"%{extension}" for extension in INDEXABLE_SOUND_SUFFIXES]
                + [limit, offset]
            ).fetchall()
            return _asset_rows_with_tags(connection, rows, paths_only)
        for term in parsed["terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "(LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM visible_asset_tags ts WHERE ts.asset_path = a.path "
                "AND ts.enabled = 1 AND LOWER(ts.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for term in parsed["excluded_terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "NOT (LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM visible_asset_tags tx WHERE tx.asset_path = a.path "
                "AND tx.enabled = 1 AND LOWER(tx.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for tag in parsed["tags"]:
            clauses.append(
                "EXISTS (SELECT 1 FROM visible_asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) = ?)"
            )
            parameters.append(tag.lower())
        for tag in parsed["excluded_tags"]:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM visible_asset_tags sx WHERE sx.asset_path = a.path "
                "AND sx.enabled = 1 AND LOWER(sx.tag) = ?)"
            )
            parameters.append(tag.lower())
        for value in parsed["types"] + parsed["bpms"] + parsed["keys"]:
            pattern = f"%{value}%"
            clauses.append(
                "(LOWER(a.path) LIKE ? OR LOWER(a.destination) LIKE ? OR EXISTS "
                "(SELECT 1 FROM visible_asset_tags sv WHERE sv.asset_path = a.path "
                "AND sv.enabled = 1 AND LOWER(sv.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern])
        for reason in parsed["reasons"]:
            clauses.append("LOWER(a.classification_reason) = ?")
            parameters.append(reason)
        tag_join = ""
        tag_join_parameters = []
        if tag_filter.strip():
            tag_join += (
                " JOIN visible_asset_tags tf ON tf.asset_path = a.path "
                "AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?"
            )
            tag_join_parameters.append(tag_filter.strip().lower())
        if favorites_only:
            tag_join += (
                " JOIN visible_asset_tags tfav ON tfav.asset_path = a.path "
                "AND tfav.enabled = 1 AND LOWER(TRIM(tfav.tag)) = 'favorite'"
            )
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        if count_only:
            return connection.execute(
                f"SELECT COUNT(*) FROM assets a{tag_join} {where_clause}",
                tag_join_parameters + parameters
            ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT a.path, a.filename, a.destination, a.classification_reason,
                   a.confidence
            FROM assets a
            {tag_join}
            {where_clause}
            ORDER BY a.filename COLLATE NOCASE
            LIMIT ? OFFSET ?
            """,
            tag_join_parameters + parameters + [limit, offset]
        ).fetchall()
        return _asset_rows_with_tags(connection, rows, paths_only)
    finally:
        connection.close()

def summarize_asset_selection(paths):
    """Aggregates cached assignments in bounded queries, rejecting stale selections."""
    paths = list(dict.fromkeys(os.path.normpath(path) for path in paths))
    live_counts = Counter()
    generated_counts = Counter()
    connection = _asset_index_connection()
    try:
        connection.execute("BEGIN")
        for start in range(0, len(paths), 500):
            batch = paths[start:start + 500]
            placeholders = ",".join("?" for _path in batch)
            indexed = {
                row[0] for row in connection.execute(
                    f"SELECT path FROM assets WHERE path IN ({placeholders})", batch
                )
            }
            missing = set(batch) - indexed
            if missing:
                raise ValueError(f"Selection is out of date; sound no longer indexed: {sorted(missing)[0]}")
            for tag, source, count in connection.execute(
                f"SELECT tag, source, COUNT(*) FROM visible_asset_tags "
                f"WHERE enabled = 1 AND asset_path IN ({placeholders}) GROUP BY tag, source",
                batch
            ):
                if source == "ableton":
                    live_counts[tag[len(ableton_tags.CACHE_PREFIX):]] += count
                elif source == "generated":
                    generated_counts[tag] += count
        return {
            "live_counts": dict(live_counts),
            "generated_counts": dict(generated_counts),
        }
    finally:
        connection.close()


def list_indexed_tags(library_root=None, search_text="", favorites_only=False):
    """Returns distinct user-visible tags and their asset counts."""
    connection = _asset_index_connection()
    try:
        extension_clauses = " OR ".join(
            "LOWER(a.path) LIKE ?" for _extension in INDEXABLE_SOUND_SUFFIXES
        )
        root_clause, root_parameters = _library_root_clause(library_root)
        clauses = ["1 = 1"]
        cte_parameters = [
            f"%{extension}" for extension in INDEXABLE_SOUND_SUFFIXES
        ]
        parameters = []
        parsed = _parse_asset_search(search_text)
        discovery_clauses, discovery_parameters = _discovery_clauses(parsed)
        clauses.extend(discovery_clauses)
        parameters.extend(discovery_parameters)
        for term in parsed["terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "(LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM visible_asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for term in parsed["excluded_terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "NOT (LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM visible_asset_tags sx WHERE sx.asset_path = a.path "
                "AND sx.enabled = 1 AND LOWER(sx.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for tag in parsed["tags"]:
            clauses.append(
                "EXISTS (SELECT 1 FROM visible_asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) = ?)"
            )
            parameters.append(tag.lower())
        for tag in parsed["excluded_tags"]:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM visible_asset_tags sx WHERE sx.asset_path = a.path "
                "AND sx.enabled = 1 AND LOWER(sx.tag) = ?)"
            )
            parameters.append(tag.lower())
        for value in parsed["types"] + parsed["bpms"] + parsed["keys"]:
            pattern = f"%{value}%"
            clauses.append(
                "(LOWER(a.path) LIKE ? OR LOWER(a.destination) LIKE ? OR EXISTS "
                "(SELECT 1 FROM visible_asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern])
        if favorites_only:
            clauses.append(
                "EXISTS (SELECT 1 FROM visible_asset_tags sf WHERE sf.asset_path = a.path "
                "AND sf.enabled = 1 AND LOWER(TRIM(sf.tag)) = 'favorite')"
            )
        if root_clause:
            clauses.append(root_clause)
            parameters.extend(root_parameters)
        return connection.execute(
            "WITH a AS MATERIALIZED (SELECT * FROM assets a "
            f"WHERE {extension_clauses}) "
            "SELECT t.tag, COUNT(*) FROM visible_asset_tags t "
            "JOIN a ON a.path = t.asset_path "
            f"WHERE t.enabled = 1 AND {' AND '.join(clauses)} "
            "GROUP BY t.tag ORDER BY t.tag COLLATE NOCASE",
            cte_parameters + parameters
        ).fetchall()
    finally:
        connection.close()

def count_indexed_assets(
    library_root=None, search_text="", tag_filter="", favorites_only=False
):
    """Returns the number of sound and MIDI records visible in the browser."""
    if search_text or tag_filter or favorites_only:
        return list_indexed_assets(
            search_text, tag_filter, favorites_only,
            library_root=library_root, count_only=True
        )
    connection = _asset_index_connection()
    try:
        extension_clauses = " OR ".join(
            "LOWER(a.path) LIKE ?" for _extension in INDEXABLE_SOUND_SUFFIXES
        )
        root_clause, root_parameters = _library_root_clause(library_root)
        root_sql = f" AND {root_clause}" if root_clause else ""
        return connection.execute(
            f"SELECT COUNT(*) FROM assets a WHERE ({extension_clauses}){root_sql}",
            [f"%{extension}" for extension in INDEXABLE_SOUND_SUFFIXES]
            + root_parameters
        ).fetchone()[0]
    finally:
        connection.close()

def add_asset_tag(path, tag):
    """Updates the favorite marker; arbitrary app-only tags are no longer supported."""
    normalized_tag = tag.strip().lower()
    if normalized_tag != "favorite":
        raise ValueError("App-only tags have been removed. Use Edit Live tags instead.")
    connection = _asset_index_connection()
    try:
        if connection.execute(
            "SELECT 1 FROM assets WHERE path = ?", (os.path.normpath(path),)
        ).fetchone() is None:
            raise ValueError("Asset is not indexed.")
        connection.execute(
            "INSERT INTO asset_tags (asset_path, tag, enabled, source) VALUES (?, ?, 1, 'personal') "
            "ON CONFLICT(asset_path, tag) DO UPDATE SET enabled = 1",
            (os.path.normpath(path), normalized_tag)
        )
        connection.commit()
    finally:
        connection.close()

def remove_asset_tag(path, tag):
    """Removes the favorite marker from an indexed asset."""
    if tag.strip().lower() != "favorite":
        raise ValueError("App-only tags have been removed. Use Edit Live tags instead.")
    connection = _asset_index_connection()
    try:
        connection.execute(
            "DELETE FROM asset_tags WHERE asset_path = ? AND tag = ?",
            (os.path.normpath(path), tag.strip().lower())
        )
        connection.commit()
    finally:
        connection.close()

def bulk_update_asset_tags(paths, tag, enabled=True, remove=False):
    """Updates favorites for several indexed assets atomically."""
    normalized_tag = tag.strip().lower()
    if normalized_tag != "favorite":
        raise ValueError("App-only tags have been removed. Use Edit Live tags instead.")
    normalized_paths = sorted({os.path.normpath(path) for path in paths})
    if not normalized_paths:
        raise ValueError("Select at least one indexed sound.")
    connection = _asset_index_connection()
    try:
        connection.execute("BEGIN")
        for start in range(0, len(normalized_paths), 500):
            batch = normalized_paths[start:start + 500]
            placeholders = ",".join("?" for _path in batch)
            indexed_count = connection.execute(
                f"SELECT COUNT(*) FROM assets WHERE path IN ({placeholders})", batch
            ).fetchone()[0]
            if indexed_count != len(batch):
                raise ValueError("One or more selected sounds are no longer indexed. Refresh the Library.")
            if remove:
                connection.execute(
                    f"DELETE FROM asset_tags WHERE tag = ? AND asset_path IN ({placeholders})",
                    [normalized_tag, *batch]
                )
            else:
                connection.executemany(
                    "INSERT INTO asset_tags (asset_path, tag, enabled, source) "
                    "VALUES (?, ?, ?, 'personal') "
                    "ON CONFLICT(asset_path, tag) DO UPDATE SET enabled = excluded.enabled",
                    [(path, normalized_tag, 1 if enabled else 0) for path in batch]
                )
        connection.commit()
    finally:
        connection.close()

def set_asset_tag_enabled(path, tag, enabled):
    """Enables or disables an existing tag without deleting its assignment."""
    if tag.strip().lower().startswith(ableton_tags.CACHE_PREFIX):
        raise ValueError("Ableton tags are read-only here. Use Live tags... or edit in Live and rescan.")
    if not tag.strip().lower().startswith(("category:", "name:")) and tag.strip().lower() != "favorite":
        raise ValueError("App-only tags have been removed. Use Edit Live tags instead.")
    connection = _asset_index_connection()
    try:
        result = connection.execute(
            "UPDATE asset_tags SET enabled = ? WHERE asset_path = ? AND tag = ?",
            (1 if enabled else 0, os.path.normpath(path), tag.strip().lower())
        )
        if result.rowcount == 0:
            raise ValueError("Tag is not assigned to this asset.")
        connection.commit()
    finally:
        connection.close()

def derive_filename_tags(filename):
    """Extracts conservative, searchable name tags without treating them as routing rules."""
    stem = os.path.splitext(filename.lower())[0]
    tokens = re.findall(r"[a-z0-9]+", stem)
    ignored = {"sample", "audio", "sound", "version", "final", "edit", "processed"}
    return [f"name:{token}" for token in tokens if len(token) >= 3 and token not in ignored]

def find_nested_folder_repairs(root_path):
    """Finds files whose canonical organization folders repeat in their relative path."""
    root_path = os.path.normpath(root_path)
    suggestions = []
    visited = set()
    stack = [root_path]
    while stack:
        current = os.path.normpath(stack.pop())
        if current in visited or "Ableton Folder Info" in current:
            continue
        visited.add(current)
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if ableton_tags.is_metadata_stub(entry.name):
                continue
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            relative_parts = os.path.relpath(entry.path, root_path).split(os.sep)
            folder_parts = relative_parts[:-1]
            canonical_parts = [part.lower() for part in folder_parts]
            repeated = {
                part for part in canonical_parts
                if part in NESTING_GUARD_FOLDERS and canonical_parts.count(part) > 1
            }
            if not repeated:
                continue
            repaired_parts = []
            seen = set()
            for part in folder_parts:
                key = part.lower()
                if key in NESTING_GUARD_FOLDERS:
                    if key in seen:
                        continue
                    seen.add(key)
                repaired_parts.append(part)
            proposed_path = os.path.normpath(
                os.path.join(root_path, *repaired_parts, relative_parts[-1])
            )
            if os.path.normcase(proposed_path) == os.path.normcase(entry.path):
                continue
            suggestions.append({
                "source": os.path.normpath(entry.path),
                "destination": proposed_path,
                "reason": "Repeated organization folder: " + ", ".join(sorted(repeated)),
            })
    return sorted(suggestions, key=lambda item: item["source"].lower())

def repair_nested_folder_files(suggestions):
    """Moves approved repair suggestions without overwriting existing files."""
    results = {"moved": 0, "skipped": 0, "errors": []}
    log_path = None
    for suggestion in suggestions:
        source = os.path.normpath(suggestion["source"])
        destination = os.path.normpath(suggestion["destination"])
        if not os.path.isfile(source) or os.path.exists(destination):
            results["skipped"] += 1
            continue
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            identity = _file_identity(source)
            if log_path is None:
                log_path = _new_move_log_path()
            previous = get_indexed_asset(source)
            record_id = _append_move_record(log_path, source, destination, destination_identity=identity)
            application = _transfer_application(
                previous["reason"] if previous else "nested_folder_repair",
                previous["confidence"] if previous else 1.0,
                previous["tags"] if previous else [],
                log_path=log_path, record_id=record_id,
            )
            ableton_tags.transfer_sample(
                source, destination, application=application, reconcile=_reconcile_transfer_application,
            )
            results["moved"] += 1
        except (OSError, ValueError, sqlite3.Error) as error:
            results["errors"].append(f"{source}: {error}")
    return results

@serialized_config
def set_smart_learning_enabled(enabled):
    """Persists the user's learning preference without changing active sorting rules."""
    global SMART_LEARNING_ENABLED
    SMART_LEARNING_ENABLED = bool(enabled)
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data["SMART_LEARNING_ENABLED"] = SMART_LEARNING_ENABLED
    _write_config(data)

def build_learned_rule_pattern(token):
    """Builds and validates a safe word-based pattern for a candidate rule."""
    pattern = rf"\b{re.escape(token)}\w*\b"
    re.compile(pattern)
    return pattern

def iter_active_drum_rules():
    """Returns enabled rules in explicit priority order, retaining legacy rule order."""
    rules = []
    for pattern, folder in DRUM_KEYWORDS.items():
        metadata = RULE_METADATA.get(pattern, {})
        if metadata.get("enabled", True):
            rules.append((int(metadata.get("priority", 0)), pattern, folder, metadata))
    return [(pattern, folder, metadata) for _, pattern, folder, metadata in
            sorted(rules, key=lambda item: item[0], reverse=True)]

def explain_filename(filename, folder_path=""):
    """Shows how a filename would be sorted: the winning rule, other rules that also match, and rules blocked by an exclusion."""
    name = os.path.basename(filename.strip())
    ext = os.path.splitext(name)[1].lower()
    lowered = name.lower()
    normalized = re.sub(r'[_#\-]', ' ', lowered)
    folder_lower = folder_path.lower()
    result = {"filename": name, "file_type": None, "winner": None, "others": [], "excluded": [], "destination": None}
    if ext in NATIVE_EXTS:
        result["file_type"] = (ext, NATIVE_EXTS[ext])
        result["destination"] = NATIVE_EXTS[ext]
        return result
    if ext in SYNTH_EXTS:
        result["file_type"] = (ext, SYNTH_EXTS[ext])
        result["destination"] = serum_presets.destination(name, SYNTH_EXTS[ext])
        return result
    if ext in ('.mid', '.midi'):
        result["file_type"] = (ext, "Midi")
        result["destination"] = "Midi"
        return result
    for pattern, folder, metadata in iter_active_drum_rules():
        hit = any(_safe_search(pattern, text) for text in (normalized, lowered, folder_lower) if text)
        if not hit:
            continue
        blocked = any(
            _safe_search(exclusion, text)
            for exclusion in metadata.get("exclude", [])
            for text in (normalized, lowered, folder_lower) if text
        )
        if blocked:
            result["excluded"].append((pattern, folder))
        elif result["winner"] is None:
            result["winner"] = (pattern, folder)
            result["destination"] = "Samples/One-Shots/" + folder
        else:
            result["others"].append((pattern, folder))
    return result

def _safe_search(pattern, text):
    try:
        return bool(re.search(pattern, text))
    except re.error:
        return False

def _pattern_samples(pattern, limit=24):
    """Builds example filenames that a rule pattern matches, for comparing rules."""
    try:
        import re._parser as parser
        import re._constants as const
    except ImportError:
        return []
    try:
        parsed = parser.parse(pattern)
    except re.error:
        return []

    def class_char(items):
        if any(op is const.NEGATE for op, _ in items):
            return " "
        for op, arg in items:
            if op is const.LITERAL:
                return chr(arg)
            if op is const.RANGE:
                return chr(arg[0])
            if op is const.CATEGORY:
                return " " if "SPACE" in str(arg) and "NOT" not in str(arg) else "1" if "DIGIT" in str(arg) else "a"
        return "a"

    def expand(items):
        results = [""]
        for op, arg in items:
            if op is const.LITERAL:
                options = [chr(arg)]
            elif op is const.IN:
                options = [class_char(arg)]
            elif op is const.ANY:
                options = ["a"]
            elif op is const.CATEGORY:
                options = [class_char([(op, arg)])]
            elif op is const.SUBPATTERN:
                options = expand(list(arg[-1]))
            elif op is const.BRANCH:
                options = [text for branch in arg[1] for text in expand(list(branch))]
            elif op in (const.MAX_REPEAT, const.MIN_REPEAT):
                low, _high, body = arg
                inner = expand(list(body))
                options = ([""] if low == 0 else []) + inner
            else:
                options = [""]
            results = list(dict.fromkeys(
                prefix + option for prefix in results for option in options
            ))[:limit]
        return results

    samples = []
    for sample in expand(list(parsed)):
        sample = sample.strip()
        if len(sample) >= 2 and sample not in samples:
            try:
                if re.search(pattern, sample) or re.search(pattern, sample.lower()):
                    samples.append(sample)
            except re.error:
                return []
    return samples

def _rule_matches(pattern, sample):
    try:
        return bool(re.search(pattern, sample) or re.search(pattern, sample.lower()))
    except re.error:
        return False

def _ordered_rule_patterns(data):
    """Returns every rule pattern from highest to lowest priority."""
    keywords = data.get("DRUM_KEYWORDS", {})
    metadata = data.get("RULE_METADATA", {})
    total = len(keywords)
    ranked = [
        (int(metadata.get(pattern, {}).get("priority", total - index)), index, pattern)
        for index, pattern in enumerate(keywords)
    ]
    return [pattern for _, _, pattern in sorted(ranked, key=lambda item: (-item[0], item[1]))]

def _apply_rule_order(data, ordered):
    """Stores a strictly descending, unique priority for every rule in order."""
    metadata = data.setdefault("RULE_METADATA", {})
    for position, pattern in enumerate(ordered):
        entry = metadata.setdefault(pattern, {"enabled": True, "exclude": []})
        entry["priority"] = len(ordered) - position

def plan_rule_placement(pattern, folder, data=None):
    """Chooses where a new rule belongs so it does not steal or lose files unexpectedly.

    A rule that is broader than the new one (it matches the new rule's examples
    but not the reverse) must rank below it, otherwise it would swallow its files.
    A rule that is more specific than the new one must stay above it.
    Returns (index, rules_to_stay_below, rules_to_stay_above) with index counted
    from the top of the current priority order.
    """
    if data is None:
        data = {"DRUM_KEYWORDS": DRUM_KEYWORDS, "RULE_METADATA": RULE_METADATA}
    ordered = [p for p in _ordered_rule_patterns(data) if p != pattern]
    metadata = data.get("RULE_METADATA", {})
    keywords = data.get("DRUM_KEYWORDS", {})
    new_samples = _pattern_samples(pattern)
    broader, narrower = [], []
    for index, other in enumerate(ordered):
        if keywords.get(other) == folder or not metadata.get(other, {}).get("enabled", True):
            continue
        other_samples = _pattern_samples(other)
        other_covers_new = any(_rule_matches(other, s) for s in new_samples)
        new_covers_other = any(_rule_matches(pattern, s) for s in other_samples)
        if other_covers_new and not new_covers_other:
            broader.append(index)
        elif new_covers_other and not other_covers_new:
            narrower.append(index)
    if broader:
        index = min(broader)
    elif narrower:
        index = max(narrower) + 1
    else:
        index = len(ordered)
    return (
        index,
        [ordered[i] for i in broader],
        [ordered[i] for i in narrower],
    )

def suggest_rule_priority(pattern, folder):
    """Previews where a new rule would rank, without changing anything."""
    index, broader, narrower = plan_rule_placement(pattern, folder)
    total = len([p for p in DRUM_KEYWORDS if p != pattern]) + 1
    return {"position": index + 1, "total": total, "above": broader, "below": narrower}

@serialized_config
def add_rule_with_smart_priority(pattern, folder):
    """Adds a rule, ranks it using plan_rule_placement, and persists the change."""
    re.compile(pattern)
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data["DRUM_KEYWORDS"] = dict(DRUM_KEYWORDS)
    data["RULE_METADATA"] = {k: dict(v) for k, v in RULE_METADATA.items()}
    index, broader, narrower = plan_rule_placement(pattern, folder, data)
    ordered = [p for p in _ordered_rule_patterns(data) if p != pattern]
    data["DRUM_KEYWORDS"][pattern] = folder
    data["RULE_METADATA"].setdefault(pattern, {"enabled": True, "exclude": []})
    ordered.insert(index, pattern)
    _apply_rule_order(data, ordered)
    _write_config(data)
    load_external_config()
    return {"position": index + 1, "total": len(ordered),
            "above": broader, "below": narrower}

@serialized_config
def move_rule(pattern, direction):
    """Moves a rule one step up (-1) or down (+1) in priority and persists it."""
    if pattern not in DRUM_KEYWORDS:
        raise ValueError("Rule pattern was not found.")
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data["DRUM_KEYWORDS"] = dict(DRUM_KEYWORDS)
    data["RULE_METADATA"] = {k: dict(v) for k, v in RULE_METADATA.items()}
    ordered = _ordered_rule_patterns(data)
    index = ordered.index(pattern)
    target = index + (-1 if direction < 0 else 1)
    if target < 0 or target >= len(ordered):
        return False
    ordered[index], ordered[target] = ordered[target], ordered[index]
    _apply_rule_order(data, ordered)
    _write_config(data)
    load_external_config()
    return True

def find_rule_competitions():
    """Lists pairs of enabled rules that can match the same filename but sort it differently.

    Each item is (winner_pattern, loser_pattern, winner_folder, loser_folder, example).
    """
    competitions = []
    rules = iter_active_drum_rules()
    samples = {pattern: _pattern_samples(pattern) for pattern, _, _ in rules}
    for index, (pattern, folder, _) in enumerate(rules):
        for other_pattern, other_folder, _ in rules[index + 1:]:
            if folder == other_folder:
                continue
            shared = [
                s for s in samples[pattern] + samples[other_pattern]
                if _rule_matches(pattern, s) and _rule_matches(other_pattern, s)
            ]
            if shared:
                competitions.append((pattern, other_pattern, folder, other_folder, shared[0]))
    return competitions

def find_shadowed_rules():
    """Enabled rules that can never win: every filename they match is already claimed by a higher-priority rule.

    Returns {pattern: [higher_pattern, ...]}. Judged from example filenames, so it errs on the side of silence.
    """
    shadowed = {}
    rules = iter_active_drum_rules()
    for index, (pattern, _folder, _meta) in enumerate(rules):
        samples = [s for s in _pattern_samples(pattern) if _rule_matches(pattern, s)]
        if not samples or index == 0:
            continue
        higher = [(p, m) for p, _f, m in rules[:index] if not m.get("exclude")]
        if all(any(_rule_matches(p, s) for p, _m in higher) for s in samples):
            shadowed[pattern] = [p for p, _m in higher if any(_rule_matches(p, s) for s in samples)]
    return shadowed

def find_rule_conflicts():
    """Finds enabled rules that can match the same filename."""
    return [item[:4] for item in find_rule_competitions()]
@serialized_config
def set_rule_metadata(pattern, *, enabled=None, priority=None, exclude=None):
    """Updates lifecycle metadata for an existing rule and persists it."""
    if pattern not in DRUM_KEYWORDS:
        raise ValueError("Rule pattern was not found.")
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data["DRUM_KEYWORDS"] = DRUM_KEYWORDS
    metadata = data.setdefault("RULE_METADATA", {}).setdefault(pattern, {
        "priority": 0, "enabled": True, "exclude": []
    } if pattern not in RULE_METADATA else dict(RULE_METADATA[pattern]))
    if enabled is not None:
        metadata["enabled"] = bool(enabled)
    if priority is not None:
        metadata["priority"] = int(priority)
    if exclude is not None:
        metadata["exclude"] = list(exclude)
    _write_config(data)
    load_external_config()

def is_reviewable_learning_candidate(candidate):
    """Keep retained historical candidates below today's support floor out of review."""
    count = candidate.get("count", 0)
    return (
        candidate.get("status", "pending") == "pending"
        and isinstance(count, int) and not isinstance(count, bool)
        and count >= MIN_RULE_EVIDENCE
    )


@serialized_config
def record_learning_evidence(evidence, minimum_count=MIN_RULE_EVIDENCE):
    """Accumulates evidence and returns newly created review candidates."""
    global LEARNING_COUNTS, LEARNED_RULE_CANDIDATES
    if not SMART_LEARNING_ENABLED:
        return []

    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)

    counts = data.setdefault("LEARNING_COUNTS", {})
    candidates = data.setdefault("LEARNED_RULE_CANDIDATES", [])
    created = []
    for (token, target), count in Counter(evidence).items():
        key = f"{token}|{target}"
        entry = counts.setdefault(key, {"token": token, "target": target, "count": 0})
        entry["count"] += count
        pending = next((
            c for c in candidates if c.get("token") == token and c.get("target") == target
            and c.get("status", "pending") == "pending"
        ), None)
        if pending is not None:
            if pending.get("evidence_source") not in {"live_manual", "filename_vocabulary"}:
                pending["count"] = entry["count"]
            continue
        if entry["count"] < minimum_count:
            continue
        candidate = {
            "token": token,
            "target": target,
            "count": entry["count"],
            "pattern": build_learned_rule_pattern(token),
            "status": "pending",
            "evidence_source": "historical_observations",
        }
        candidates.append(candidate)
        created.append(candidate)

    if created or evidence:
        data["LEARNING_COUNTS"] = counts
        data["LEARNED_RULE_CANDIDATES"] = candidates
        _write_config(data)
        load_external_config()
    return created

def review_learning_candidate(token, target, decision):
    """Approves or rejects one pending candidate and persists the decision."""
    review_learning_candidates(((token, target),), decision)


def review_learning_candidates(selections, decision):
    """Validate all selected candidates before persisting any rule or decision."""
    if decision not in {"approved", "rejected"}:
        raise ValueError("Candidate decision must be approved or rejected.")
    selections = tuple(dict.fromkeys(selections))
    if not selections:
        raise ValueError("Select at least one pending learning candidate.")
    data = {}
    original = None
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'rb') as f:
            original = f.read()
        data = json.loads(original)
    candidates = data.setdefault("LEARNED_RULE_CANDIDATES", [])
    matching = []
    for token, target in selections:
        candidate = next((
            item for item in candidates
            if item.get("token") == token and item.get("target") == target
            and item.get("status", "pending") == "pending"
        ), None)
        if candidate is None:
            raise ValueError("Pending learning candidate was not found.")
        matching.append(candidate)
    if decision == "approved":
        if not all(is_reviewable_learning_candidate(candidate) for candidate in matching):
            raise ValueError(
                f"Suggestions require at least {MIN_RULE_EVIDENCE} supporting observations. "
                "Below-threshold historical suggestions cannot be approved."
            )
        import rule_suggester
        refreshed = rule_suggester.revalidate_candidates(matching)
        if not all(is_reviewable_learning_candidate(candidate) for candidate in refreshed):
            raise ValueError(
                f"Current evidence falls below {MIN_RULE_EVIDENCE} supporters. "
                "No selected suggestions were approved."
            )
        for candidate, current in zip(matching, refreshed):
            candidate.update(current)
            target = candidate["target"]
            data.setdefault("DRUM_KEYWORDS", {})[candidate["pattern"]] = target
            data.setdefault("RULE_METADATA", {})[candidate["pattern"]] = {
                "enabled": True, "exclude": []
            }
            data["DRUM_KEYWORDS"] = {**DRUM_KEYWORDS, **data["DRUM_KEYWORDS"]}
            data["RULE_METADATA"] = {**RULE_METADATA, **data["RULE_METADATA"]}
            index, _, _ = plan_rule_placement(candidate["pattern"], target, data)
            ordered = [p for p in _ordered_rule_patterns(data) if p != candidate["pattern"]]
            ordered.insert(index, candidate["pattern"])
            _apply_rule_order(data, ordered)
    for candidate in matching:
        candidate["status"] = decision
    current = None
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'rb') as f:
            current = f.read()
    if current != original:
        raise ValueError("Rules or profile changed during review. No selected suggestions were approved; retry.")
    _write_config(data, expected_content=original)
    load_external_config()

# sorter_engine.py - Piece 2: Class Initialization & Background Thread Routing
def _check_unlinked_path(path):
    for part in (path, *path.parents):
        junction = (
            os.name == "nt" and os.path.lexists(part)
            and part.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        )
        if part.is_symlink() or junction:
            raise ValueError(f"Linked paths are not supported: {part}")


class ParallelLibrarySorter:
    def __init__(self, src_path, dest_path, window_el, update_status_callback, done_callback, copy_mode=False,
                 smart_learning_enabled=None, preview_only=False, *, audio_only=False,
                 supported_only=False, approved_plan=None):
        """Initializes the multi-threaded file distribution and structural optimization engine."""
        self.src = os.path.normpath(src_path)
        self.dest = os.path.normpath(dest_path)
        self.window = window_el
        self.update_status = update_status_callback
        self.done_callback = done_callback
        self.copy_mode = copy_mode
        self.smart_learning_enabled = SMART_LEARNING_ENABLED if smart_learning_enabled is None else bool(smart_learning_enabled)
        self.preview_only = bool(preview_only)
        self.audio_only = bool(audio_only)
        self.supported_only = bool(supported_only)
        self.approved_plan = copy.deepcopy(approved_plan)
        self.reviewed_plan = None
        self.skipped_records = []
        self._scan_inventory = []
        
        self.total_files = 0
        self.processed_files = 0
        self.raw_unmatched_tokens = []
        self.harvested_metadata = {}
        self.manual_live_assignments = {}
        self.preview_records = []
        self.operation_plan = []
        self._planning_only = False
        self._plan_lock = threading.Lock()
        self._reserved_destinations = {}
        self._planned_directories = set()
        self._completed_plan_sources = set()
        self.move_log_path = None
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.cancel_requested_at = None
        self.phase_seconds = {}
        self._destination_metadata_folders = set()
        self._destination_metadata = {}
        self.operation_errors = []
        self.indexed_tags_by_path = {}
        self.indexed_tags_cache_loaded = False
        
        # Operational Analytics Register Ledger Matrix Tracking
        self.stats = {
            "Native Live Racks (.adg, .amxd, .alc, .adv)": 0, 
            "Synth Presets & Wavetables (.fxp, .vital)": 0, 
            "Loops Separated by BPM & Key": 0, 
            "One-Shots Grouped by Drum Type": 0, 
            "Skipped Duplicate Items": 0, 
            "Non-audio Files Excluded": 0,
            "Errors/Skipped Files": 0,
            "New Metadata Rules Learned & Written": 0,
            "New Learning Candidates": 0
        }

    def start_parallel_sort(self, *, job_lease=None):
        """Spins up background threading networks to execute operations without freezing the UI."""
        lease = self._claim_job("Import/cleanup preview" if self.preview_only else "Import/cleanup", job_lease)
        if lease is None:
            return
        started = time.perf_counter()
        def background_execution_pipeline():
            try:
                planning_started = time.perf_counter()
                _validate_config({
                    "DRUM_KEYWORDS": DRUM_KEYWORDS, "SYNTH_EXTS": SYNTH_EXTS,
                    "NATIVE_EXTS": NATIVE_EXTS,
                })
                routing_state = self._routing_state()
                metadata_before = self._metadata_state()
                nested_serum_root = os.path.join(self.dest, "Serum Presets", "Serum 2 Presets")
                if (any(serum_presets.is_user_folder(folder) for folder in SYNTH_EXTS.values())
                        and os.path.isdir(nested_serum_root)):
                    raise ValueError(
                        "The Serum 2 resource folder is still nested inside Serum Presets. "
                        "Complete the reviewed relocation of the entire Serum 2 Presets folder "
                        "to the User Library root before importing or organizing. "
                        "Do not merge resource folders; no files were moved."
                    )
                self.window.after(0, lambda: self.update_status("Extracting Ableton browser tagging metadata..."))
                
                self.harvested_metadata = harvest_ableton_metadata(self.src)
                try:
                    self.indexed_tags_by_path = _read_routing_tags()
                    self.indexed_tags_cache_loaded = True
                except sqlite3.Error as error:
                    raise OSError(f"Cannot read saved routing/index tags; no files were moved: {error}") from error

                self.window.after(0, lambda: self.update_status("Scanning directory layout safely..."))

                execution_manifest, self._scan_inventory, scan_skips = self._scan_manifest()
                self.skipped_records = list(scan_skips)
                self.stats["Non-audio Files Excluded"] = sum(
                    row["reason"] == "file_type_excluded" for row in scan_skips
                )
                if self.cancel_event.is_set():
                    return
                self.total_files = len(execution_manifest)
                try:
                    self.manual_live_assignments = ableton_tags.read_sample_assignments(
                        os.path.join(folder, name) for folder, name in execution_manifest
                        if os.path.splitext(name)[1].lower() in AUDIO_EXTS
                    )
                except (OSError, ValueError) as error:
                    self.record_operation_error(self.src, self.dest, "read_manual_live_tags", error)
                    self.increment_stat_safe("Errors/Skipped Files")
                    self.window.after(0, lambda error=error: self.update_status(
                        f"Manual Live metadata could not be read; operation aborted: {error}"
                    ))
                    return
                
                self.window.after(0, lambda: self.update_status(
                    "Planning exact destinations and checking file identities..."
                ))
                self._planning_only = True
                try:
                    for root, filename in execution_manifest:
                        if self.cancel_event.is_set():
                            return
                        self.process_single_file(root, filename)
                finally:
                    self._planning_only = False
                self.phase_seconds["planning_seconds"] = time.perf_counter() - planning_started
                validation_started = time.perf_counter()
                if self._routing_state() != routing_state:
                    raise ValueError(
                        "Routing settings changed during destination planning; no files were moved. Preview again."
                    )
                if self._metadata_state() != metadata_before:
                    raise ValueError("Source metadata changed during planning. Preview again; no files were moved.")
                if self.operation_errors or self.cancel_event.is_set():
                    return
                _, current_inventory, current_skips = self._scan_manifest()
                if self.cancel_event.is_set():
                    return
                if current_inventory != self._scan_inventory or current_skips != scan_skips:
                    raise ValueError("Source inventory changed during planning; no files were moved. Preview again.")
                for record in self.operation_plan:
                    self._validate_planned_inputs(record)
                if self._folder_metadata_state(self._destination_metadata_folders) != self._destination_metadata:
                    raise ValueError("Destination metadata changed during planning; no files were moved.")
                self.reviewed_plan = self._make_reviewed_plan(routing_state, metadata_before)
                if self.approved_plan is not None:
                    self.validate_approved_plan(self.approved_plan)
                self.phase_seconds["approval_validation_seconds"] = time.perf_counter() - validation_started
                if self.preview_only:
                    return

                transfer_started = time.perf_counter()
                if self.operation_plan and not self.preview_only:
                    # A duplicate may depend on an earlier planned copy/move of the same name.
                    groups = {}
                    for record in self.operation_plan:
                        groups.setdefault(self._destination_key(record["destination_path"]), []).append(record)
                    self.processed_files = self.total_files - len(self.operation_plan)
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        batch_size = 256
                        grouped_records = list(groups.values())
                        for batch_start in range(0, len(grouped_records), batch_size):
                            if self.cancel_event.is_set():
                                break
                            batch = grouped_records[batch_start:batch_start + batch_size]
                            futures = [
                                executor.submit(self._execute_group, records)
                                for records in batch
                            ]
                            for future in as_completed(futures):
                                try:
                                    future.result()
                                except Exception as worker_error:
                                    self.window.after(
                                        0,
                                        lambda error=worker_error: self.update_status(
                                            f"File worker error: {error}"
                                        )
                                    )
                            self.window.after(
                                0,
                                lambda completed=self.processed_files: self.update_status(
                                    f"Batch complete ({completed}/{self.total_files})"
                                )
                            )

                self.phase_seconds["transfer_seconds"] = time.perf_counter() - transfer_started
                if self.raw_unmatched_tokens and self.smart_learning_enabled and not self.preview_only:
                    try:
                        candidates = record_learning_evidence(self.raw_unmatched_tokens)
                        self.stats["New Learning Candidates"] = len(candidates)
                    except (OSError, ValueError, json.JSONDecodeError, re.error) as learning_error:
                        learning_message = str(learning_error)
                        self.window.after(0, lambda: self.update_status(
                            f"Learning evidence could not be saved: {learning_message}"))

                if not self.copy_mode and not self.preview_only:
                    self.window.after(0, lambda: self.update_status("Scrubbing empty leftover directories..."))
                    force_delete_empty_folders(self.src)

                if not self.preview_only and not self.cancel_event.is_set():
                    try:
                        connection = _asset_index_connection()
                        try:
                            _prune_missing_assets(connection, self.dest)
                            connection.commit()
                        finally:
                            connection.close()
                    except (OSError, sqlite3.Error) as index_error:
                        self.record_operation_error(
                            self.dest, "", "index reconciliation", index_error
                        )
                        self.increment_stat_safe("Errors/Skipped Files")
                        self.window.after(
                            0, lambda error=index_error: self.update_status(
                                f"Asset index could not be reconciled: {error}"
                            )
                        )
                    
                if self.cancel_event.is_set():
                    self.window.after(0, lambda: self.update_status("Operation cancelled. No new files will be processed."))
                else:
                    self.window.after(0, lambda: self.update_status("Task optimization complete!"))
            except Exception as pipeline_err:
                self.record_operation_error(self.src, self.dest, "pipeline", pipeline_err)
                self.increment_stat_safe("Errors/Skipped Files")
                self.window.after(0, lambda error=pipeline_err: self.update_status(f"Error: {error}"))
            finally:
                try:
                    self._record_performance(started)
                finally:
                    lease.release()
                    self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))

        self._start_owned_thread(background_execution_pipeline, lease, "library-sorter")

    def _claim_job(self, label, inherited=None):
        try:
            self._validate_audio_only_mode()
            if CONFIG_LOAD_ERROR or XO_CONFIG_LOAD_ERROR:
                raise ValueError(CONFIG_LOAD_ERROR or XO_CONFIG_LOAD_ERROR)
            pending = pending_legacy_exclusions() if os.path.isfile(CONFIG_FILE) else []
            if pending:
                names = sorted({name for entry in pending for name in entry["missing"]})
                raise ValueError(
                    "Previous Skip Folders settings need review before importing or organizing: "
                    + ", ".join(names) + ". Open Skip Folders > Review previous settings."
                )
        except (OSError, ValueError) as error:
            if inherited is not None:
                inherited.release()
            self.record_operation_error(self.src, self.dest, "Skip Folders safety check", error)
            self.increment_stat_safe("Errors/Skipped Files")
            self.window.after(0, lambda error=error: self.update_status(str(error)))
            self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))
            return None
        lease = inherited if inherited is not None else library_jobs.coordinator.claim(label)
        if lease is not None and not lease.active:
            lease = None
        if lease is None:
            error = ValueError(
                f"Library is busy: {library_jobs.coordinator.active_label}. "
                "Wait for that operation to finish or cancel it before retrying."
            )
            self.record_operation_error(self.src, self.dest, "job ownership", error)
            self.increment_stat_safe("Errors/Skipped Files")
            self.window.after(0, lambda: self.update_status(str(error)))
            self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))
        return lease

    def _start_owned_thread(self, target, lease, name):
        self.worker_thread = threading.Thread(target=target, name=name, daemon=False)
        try:
            self.worker_thread.start()
        except RuntimeError as error:
            lease.release()
            self.record_operation_error(self.src, self.dest, "worker startup", error)
            self.increment_stat_safe("Errors/Skipped Files")
            self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))

    def cancel(self):
        """Requests cancellation without interrupting the file currently being processed."""
        if self.cancel_requested_at is None:
            self.cancel_requested_at = time.perf_counter()
        self.cancel_event.set()

    def _record_performance(self, started, operation=None):
        completed = len(self._completed_plan_sources)
        planned = len(self.operation_plan)
        transferred_bytes = sum(
            record["source_identity"]["size"] for record in self.operation_plan
            if record["source"] in self._completed_plan_sources and record["action"] != "duplicate"
        )
        if operation == "serum_resource_import":
            planned = self.total_files
            completed = (
                self.stats["Serum 2 Resource Files Copied"] + self.stats["Skipped Duplicate Items"]
                if not self.preview_only else 0
            )
            transferred_bytes = self._resource_bytes_copied
        elapsed = max(time.perf_counter() - started, 0.000001)
        cancelled = self.cancel_event.is_set()
        errors = self.stats["Errors/Skipped Files"]
        performance_log.record(
            operation or ("organize" if self.src == self.dest else "import"),
            started,
            outcome="cancelled" if cancelled else "failed" if errors else "completed",
            preview=self.preview_only, copy_mode=self.copy_mode,
            audio_only=self.audio_only,
            excluded_non_audio=self.stats["Non-audio Files Excluded"],
            total_files=self.total_files, processed_files=self.processed_files,
            planned_files=planned, completed_files=completed,
            transferred_bytes=transferred_bytes, errors=errors,
            files_per_second=completed / elapsed, bytes_per_second=transferred_bytes / elapsed,
            processed_files_per_second=self.processed_files / elapsed,
            cancellation_seconds=(
                max(0.0, time.perf_counter() - self.cancel_requested_at)
                if self.cancel_requested_at is not None else None
            ),
            **self.phase_seconds,
        )

    def is_running(self):
        """Returns whether the sorter worker is still active."""
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def _accepts_file(self, filename):
        extension = os.path.splitext(filename)[1].lower()
        if self.audio_only:
            return extension in AUDIO_EXTS
        if self.supported_only:
            return extension in AUDIO_EXTS or (
                extension in SUPPORTED_PRESET_EXTS
                and (extension in SYNTH_EXTS or extension in NATIVE_EXTS)
            )
        return True

    def _scan_manifest(self):
        manifest, inventory, skipped = [], [], []
        stack, visited = [self.src], set()
        while stack:
            if self.cancel_event.is_set():
                return manifest, inventory, skipped
            if len(visited) >= 50000:
                raise ValueError("The scan exceeded its folder safety limit. No files were moved.")
            root = os.path.normpath(stack.pop())
            if root in visited or "Ableton Folder Info" in root:
                continue
            visited.add(root)
            if len(Path(os.path.relpath(root, self.src)).parts) > 6:
                skipped.append({"source": root, "reason": "depth_limit"})
                continue
            try:
                with os.scandir(root) as entries:
                    for entry in entries:
                        if ableton_tags.is_metadata_stub(entry.name):
                            continue
                        if entry.is_symlink():
                            skipped.append({"source": entry.path, "reason": "linked_content"})
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if any(ignore.lower() in entry.path.lower()
                                   for ignore in IGNORED_DIRECTORIES if ignore.strip()):
                                skipped.append({"source": entry.path, "reason": "skip_folder"})
                            else:
                                stack.append(entry.path)
                        elif entry.is_file():
                            info = entry.stat(follow_symlinks=False)
                            inventory.append({
                                "source": entry.path, "size": info.st_size,
                                "modified_ns": info.st_mtime_ns,
                            })
                            if entry.name == "library_config.json" or entry.name.endswith((".py", ".pyw")):
                                skipped.append({"source": entry.path, "reason": "application_file"})
                            elif not self._accepts_file(entry.name):
                                skipped.append({"source": entry.path, "reason": "file_type_excluded"})
                            else:
                                manifest.append((root, entry.name))
                                if len(manifest) % 1000 == 0:
                                    self.window.after(0, lambda count=len(manifest): self.update_status(
                                        f"Scanning directory layout safely... {count:,} files found"
                                    ))
            except OSError as error:
                raise OSError(f"Could not scan {root}; no files were moved: {error}") from error
        return (
            sorted(manifest, key=lambda item: (
                os.path.normcase(os.path.join(*item)).casefold(), os.path.join(*item),
            )),
            sorted(inventory, key=lambda item: item["source"]),
            sorted(skipped, key=lambda item: (item["source"], item["reason"])),
        )

    def _validate_planned_inputs(self, record):
        source, destination = record["source"], record["destination_path"]
        _validate_destination(self.dest, destination)
        if os.path.islink(source) or _file_identity(source) != record["source_identity"]:
            raise ValueError(f"Source changed during planning; no files were moved: {source}")
        if record["action"] == "duplicate" and not record["provider"]:
            if not os.path.isfile(destination) or _file_identity(destination) != record["destination_identity"]:
                raise ValueError(f"Duplicate destination changed during planning: {destination}")
        elif record["action"] != "in_place" and os.path.lexists(destination):
            raise FileExistsError(f"Planned destination is now occupied: {destination}")

    def _metadata_state(self):
        source = Path(self.src).absolute()
        folders = {source, *source.parents}
        def scan_error(error):
            raise OSError(f"Could not inspect source metadata; no files were moved: {error}") from error
        if source.is_dir():
            for root, directories, files in os.walk(source, followlinks=False, onerror=scan_error):
                if len(Path(root).relative_to(source).parts) >= 6:
                    directories[:] = [name for name in directories if name == "Ableton Folder Info"]
                directories[:] = [
                    name for name in directories if not os.path.islink(os.path.join(root, name))
                    and (name == "Ableton Folder Info" or not any(
                        ignored.casefold() in os.path.join(root, name).casefold()
                        for ignored in IGNORED_DIRECTORIES if ignored.strip()
                    ))
                ]
                if "Ableton Folder Info" in Path(root).parts:
                    folders.add(Path(root).parent)
        sidecars = self._folder_metadata_state(folders)
        profile = None
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "rb") as handle:
                profile = hashlib.sha256(handle.read()).hexdigest()
        return {
            "sidecars": sidecars, "profile_sha256": profile,
            "indexed_tags_sha256": hashlib.sha256(
                json.dumps(_read_routing_tags(), sort_keys=True).encode("utf-8")
            ).hexdigest(),
        }

    @staticmethod
    def _folder_metadata_state(folders):
        sidecars = {}
        for folder in sorted(folders):
            metadata = folder / "Ableton Folder Info"
            _check_unlinked_path(metadata)
            if not metadata.exists():
                continue
            for path in sorted(metadata.iterdir()):
                if path.suffix.lower() != ".xmp" or ableton_tags.is_metadata_stub(path.name):
                    continue
                _check_unlinked_path(path)
                sidecars[str(path)] = _file_identity(path)
        return sidecars

    def _make_reviewed_plan(self, routing_state, metadata_state):
        return {
            "version": 1, "kind": "ordinary",
            "source_root": os.path.abspath(self.src), "destination_root": os.path.abspath(self.dest),
            "copy_mode": bool(self.copy_mode), "audio_only": self.audio_only,
            "supported_only": self.supported_only, "smart_learning": self.smart_learning_enabled,
            "settings": routing_state, "metadata": metadata_state,
            "destination_metadata": copy.deepcopy(self._destination_metadata),
            "inventory": sorted(self._scan_inventory, key=lambda item: item["source"]),
            "records": copy.deepcopy(self.operation_plan),
            "skipped": sorted(self.skipped_records, key=lambda item: (item["source"], item["reason"])),
            "learning_evidence": sorted(self.raw_unmatched_tokens),
            "total_files": self.total_files,
            "integration_limits": [
                "Copying or moving files does not change Live, Serum or XO preferences.",
                "Review copied presets in their plugin to verify sample/resource dependencies.",
            ],
        }

    def validate_approved_plan(self, plan):
        if not isinstance(plan, dict) or plan.get("version") != 1:
            raise ValueError("Unsupported approved plan. Generate a new preview.")
        if self.reviewed_plan is None or json.dumps(plan, sort_keys=True) != json.dumps(
            self.reviewed_plan, sort_keys=True,
        ):
            raise ValueError(
                "The approved plan is stale: inputs, metadata, settings or destinations changed. "
                "No files were transferred. Preview again."
            )

    def export_plan(self, path):
        if self.reviewed_plan is None or self.operation_errors or self.cancel_event.is_set():
            raise ValueError("Only complete, successful previews can be exported.")
        output = os.path.realpath(os.path.abspath(os.fspath(path)))
        for root in (self.src, self.dest):
            base = os.path.realpath(os.path.abspath(root))
            if (os.path.splitdrive(base)[0].casefold() == os.path.splitdrive(output)[0].casefold()
                    and os.path.commonpath((base, output)) == base):
                raise ValueError("Export the plan outside the source and destination libraries.")
        with open(output, "x", encoding="utf-8") as handle:
            try:
                json.dump(self.reviewed_plan, handle, indent=2, ensure_ascii=True, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            except (OSError, ValueError, TypeError):
                handle.close()
                os.unlink(output)
                raise

    def _validate_audio_only_mode(self):
        if not self.audio_only:
            return
        source = os.path.normcase(os.path.abspath(self.src))
        destination = os.path.normcase(os.path.abspath(self.dest))
        if (os.path.splitdrive(source)[0] == os.path.splitdrive(destination)[0]
                and os.path.commonpath((source, destination)) in (source, destination)):
            raise ValueError("Audio-only import requires separate, non-overlapping source and destination folders.")
        if serum_presets.is_resource_root(self.src):
            raise ValueError(
                "Complete Serum resource imports require the normal copy-only resource workflow. "
                "Turn off Audio samples only."
            )

    def get_metadata_drum_target(self, filename):
        """Cross-references file data maps against internal metadata arrays."""
        fn_lower = filename.lower()
        if fn_lower in self.harvested_metadata:
            tags = self.harvested_metadata[fn_lower]
            tag_priority_map = [
                ('kick', 'Kicks'), ('snare', 'Snares'), ('hat', 'Hi-Hats'), 
                ('clap', 'Claps'), ('tom', 'Toms'), ('perc', 'Percussion'), 
                ('shaker', 'Percussion/Shakers'), ('vocal', 'Vocals & Chants'),
                ('vox', 'Vocals & Chants'), ('sub', '808 Sub Bass'), ('808', '808 Sub Bass'),
                ('bass', 'Synth Bass One-Shots'), ('pluck', 'Melodic & Synth One-Shots'),
                ('lead', 'Melodic & Synth One-Shots'), ('pad', 'Melodic & Synth One-Shots'),
                ('ambient', 'Cinematic & Ambience'), ('drone', 'Cinematic & Ambience'),
                ('texture', 'Cinematic & Ambience'), ('glitch', 'Glitches & Micro-Percussion'),
                ('fx', 'Sound FX'), ('effect', 'Sound FX')
            ]
            for target_key, folder_name in tag_priority_map:
                if any(target_key in t for t in tags): 
                    return folder_name, target_key
        return None, None

    def log_move(self, source, destination, **details):
        """Appends one move to the run's undo log as soon as it happens, so a crash still leaves a usable log."""
        with self.lock:
            if self.move_log_path is None:
                self.move_log_path = _new_move_log_path()
            if not details:
                details["destination_identity"] = _file_identity(destination)
            details.setdefault("job_kind", "organize" if self.src == self.dest else "import")
            details.setdefault("source_root", self.src)
            details.setdefault("destination_root", self.dest)
            return _append_move_record(self.move_log_path, source, destination, **details)

    def retain_duplicate_for_undo(self, source, destination, tags):
        os.makedirs(_move_log_dir(), exist_ok=True)
        descriptor, recovery = tempfile.mkstemp(prefix="duplicate-", suffix=".audio", dir=_move_log_dir())
        os.close(descriptor)
        try:
            shutil.copy2(source, recovery)
            source_tags = ableton_tags.sample_tags(source)
            destination_tags = ableton_tags.sample_tags(destination)
            source_index = _snapshot_indexed_asset(source)
            destination_index = _snapshot_indexed_asset(destination)
            expected_personal = {}
            for snapshot in (source_index, destination_index):
                if snapshot is not None:
                    for tag, enabled, tag_source in snapshot["stored_tags"]:
                        if tag_source == "personal":
                            expected_personal[tag] = enabled
            for tag in tags:
                if tag == "favorite":
                    expected_personal.setdefault(tag, 1)
            return self.log_move(
                source, destination, operation="duplicate", recovery=recovery,
                destination_identity=_file_identity(source),
                source_live_tags=source_tags, destination_live_tags=destination_tags,
                merged_live_tags=sorted(set(source_tags + destination_tags)),
                source_index=source_index, destination_index=destination_index,
                expected_destination_personal=expected_personal,
            )
        except (OSError, ValueError, sqlite3.Error):
            os.remove(recovery)
            raise

    def increment_stat_safe(self, key):
        """Thread-safe counter increments for runtime statistics logging."""
        with self.lock:
            if key in self.stats: 
                self.stats[key] += 1

    def record_operation_error(self, source, destination, operation, error):
        """Retain an actionable per-file failure for the completion report."""
        with self.lock:
            self.operation_errors.append({
                "source": os.path.normpath(source) if source else "",
                "destination": os.path.normpath(destination) if destination else "",
                "operation": operation,
                "error_type": type(error).__name__,
                "error": str(error) or "Unknown file operation error"
            })

    def process_single_file(self, root, f):
        """Plan one file, or plan and execute it for single-file callers."""
        global BPM_RANGES, DRUM_KEYWORDS, SYNTH_EXTS, NATIVE_EXTS
        
        try:
            if self.cancel_event.is_set():
                return
            self._validate_audio_only_mode()
            f = str(f)
            f_lower = f.lower()
            root_lower = str(root).lower()
            
            # Extract the actual extension string from the tuple split
            ext_tuple = os.path.splitext(f_lower)
            ext = ext_tuple[1].strip() if len(ext_tuple) > 1 else ""
            if not self._accepts_file(f):
                self.increment_stat_safe("Non-audio Files Excluded")
                self.skipped_records.append({"source": os.path.join(root, f), "reason": "file_type_excluded"})
                return
            
            s_path = os.path.normpath(os.path.join(root, f))
            sort_user_preset = (
                serum_presets.user_relative_path(s_path) is not None
                and ext in serum_presets.PRESET_EXTENSIONS and ext in SYNTH_EXTS
                and serum_presets.is_user_folder(SYNTH_EXTS[ext])
            )
            if serum_presets.is_resource_path(root) and not sort_user_preset:
                self.skipped_records.append({"source": s_path, "reason": "serum_resource_preserved"})
                return
            target_dir = None
            stat_key = "Errors/Skipped Files"
            classification_reason = "unclassified"
            classification_confidence = 0.25
            if self.indexed_tags_cache_loaded:
                indexed_tags = self.indexed_tags_by_path.get(s_path, [])
            else:
                try:
                    indexed_tags = (
                        _read_routing_tags().get(s_path, []) if self.preview_only else get_asset_tags(s_path)
                    )
                except sqlite3.Error:
                    indexed_tags = []
            tags = [
                tag for tag in list(self.harvested_metadata.get(f_lower, [])) + indexed_tags
                if not tag.startswith(("category:", "name:"))
            ]
            
            f_normalized = re.sub(r'[_#\-]', ' ', f_lower)
            
            try:
                normalized_root = os.path.relpath(s_path, self.src)
            except ValueError:
                normalized_root = ""
            path_segments = [seg.lower() for seg in normalized_root.split(os.sep) if seg.strip()]

            # 🌟 INFINITE LOOP INCEPTION BLOCKER: 
            # If the source folder structure is already recursively looping, escape immediately!
            if path_segments.count("samples") > 1 or path_segments.count("loops") > 1 or path_segments.count("midi") > 1 or path_segments.count("percussion") > 1:
                return

            # 🌟 PARENT-FOLDER SAFETY GUARD:
            # If the file is ALREADY sitting inside one of your top-level organized system blocks,
            # DO NOT parse its folder name for keywords. This completely stops Percussion\Percussion loops.
            is_already_sorted = False
            relayout_loop = False
            if path_segments:
                top_level_folder = path_segments[0]
                if top_level_folder in ["percussion", "midi", "serum presets", "live instrument racks", "max for live devices"]:
                    is_already_sorted = True
                elif top_level_folder == "samples" and len(path_segments) > 1 and path_segments[1] in ["one-shots", "loops"]:
                    # The catch-all folder is re-checked so new and existing rules can still claim its files.
                    is_catch_all = len(path_segments) > 2 and path_segments[1] == "one-shots" and path_segments[2] == "other one-shots"
                    is_already_sorted = not is_catch_all
                    # Loops in folders this app created follow the current loop layout; custom folders are left alone.
                    relayout_loop = (path_segments[1] == "loops" and ext in AUDIO_EXTS
                                     and is_generated_loop_folder(path_segments[2:-1]))

            recover_serum_preset = (
                bool(path_segments) and path_segments[0] == "live instrument racks"
                and ext == ".serumpreset" and ext in SYNTH_EXTS and ext not in NATIVE_EXTS
            )
            migrate_loose_serum_preset = (
                len(path_segments) == 2 and path_segments[0] == "serum presets"
                and ext in serum_presets.PRESET_EXTENSIONS and ext in SYNTH_EXTS
                and ext not in NATIVE_EXTS and serum_presets.is_user_folder(SYNTH_EXTS[ext])
            )
            if (is_already_sorted and not relayout_loop and not recover_serum_preset
                    and not migrate_loose_serum_preset):
                return
            synth_target = ""
            if ext in SYNTH_EXTS:
                synth_target = serum_presets.destination(
                    f, SYNTH_EXTS[ext], source=s_path,
                    source_root=self.src if os.path.abspath(self.src) != os.path.abspath(self.dest) else None,
                )

            if relayout_loop:
                classification_reason = "loop_name_or_metadata"
                classification_confidence = 0.80
                target_dir = os.path.join(
                    self.dest, "Samples", "Loops", *loop_subfolders(f_normalized, f_lower))
                stat_key = "Loops Separated by BPM & Key"

            # 1. KEYWORD GRID OVERRIDE PATTERN SCAN
            grid_matched_folder = None
            if not is_already_sorted:
                for pattern, folder, metadata in iter_active_drum_rules():
                    excluded = any(
                        re.search(exclusion, f_normalized) or
                        re.search(exclusion, f_lower) or
                        re.search(exclusion, root_lower)
                        for exclusion in metadata.get("exclude", [])
                    )
                    if not excluded and (re.search(pattern, f_normalized) or
                                         re.search(pattern, f_lower) or
                                         re.search(pattern, root_lower)):
                        grid_matched_folder = folder
                        break
                    
            if grid_matched_folder:
                if ext in NATIVE_EXTS:
                    target_dir = os.path.join(self.dest, NATIVE_EXTS[ext])
                elif ext in SYNTH_EXTS:
                    target_dir = os.path.join(
                        self.dest, synth_target)
                elif ext in ('.mid', '.midi'):
                    target_dir = os.path.join(self.dest, "Midi")
                else:
                    target_dir = os.path.join(
                        self.dest, *tag_evidence.one_shot_folder(grid_matched_folder))

                if ext in NATIVE_EXTS or ext in SYNTH_EXTS or ext in ('.mid', '.midi'):
                    classification_reason = "file_extension"
                    classification_confidence = 0.90
                elif classification_reason == "unclassified":
                    classification_reason = "filename_rule"
                    classification_confidence = 0.95
                
                if ext in NATIVE_EXTS: stat_key = "Native Live Racks (.adg, .amxd, .alc, .adv)"
                elif ext in SYNTH_EXTS: stat_key = "Synth Presets & Wavetables (.fxp, .vital)"
                elif ext == '.mid' or ext == '.midi': stat_key = "Loops Separated by BPM & Key"
                else: stat_key = "One-Shots Grouped by Drum Type"

            # 2. ABLETON METADATA AUTO-TAG CHECK FALLBACK
            if not target_dir and ext in AUDIO_EXTS:
                meta_drum_folder, raw_tag = self.get_metadata_drum_target(f)
                if meta_drum_folder:
                    classification_reason = "ableton_metadata"
                    classification_confidence = 0.85
                    target_dir = os.path.join(
                        self.dest, *tag_evidence.one_shot_folder(meta_drum_folder))
                    stat_key = "One-Shots Grouped by Drum Type"
                    
                    try:
                        base_name_str = os.path.splitext(f_lower)[0]
                        base_clean = re.sub(r'[\d_\-]', ' ', base_name_str)
                        tokens = [t for t in base_clean.split() if len(t) >= 3]
                        if tokens:
                            with self.lock:
                                for token in tokens:
                                    self.raw_unmatched_tokens.append((token, meta_drum_folder))
                    except Exception:
                        pass

            # 3. CONTEXT-BASED GENERIC FALLBACK ROUTING
            if not target_dir:
                if ext in NATIVE_EXTS:
                    classification_reason = "file_extension"
                    classification_confidence = 0.90
                    target_dir = os.path.join(self.dest, NATIVE_EXTS.get(ext, "Live Instrument Racks"))
                    stat_key = "Native Live Racks (.adg, .amxd, .alc, .adv)"
                elif ext in SYNTH_EXTS:
                    classification_reason = "file_extension"
                    classification_confidence = 0.90
                    target_dir = os.path.join(
                        self.dest, synth_target)
                    stat_key = "Synth Presets & Wavetables (.fxp, .vital)"
                elif ext == '.mid' or ext == '.midi':
                    classification_reason = "file_extension"
                    classification_confidence = 0.90
                    target_dir = os.path.join(self.dest, "Midi")
                    stat_key = "Loops Separated by BPM & Key"
                elif ext in AUDIO_EXTS:
                    is_meta_loop = f_lower in self.harvested_metadata and any('loop' in t for t in self.harvested_metadata[f_lower])
                    has_bpm = re.search(r'\b\d{2,3}\s*(bpm|BPM)\b', f_normalized)
                    is_text_loop = any(k in f_normalized or k in root_lower for k in ['loop', 'fill', 'roll', 'groove']) or has_bpm
                    
                    if is_meta_loop or is_text_loop:
                        classification_reason = "loop_name_or_metadata"
                        classification_confidence = 0.80
                        target_dir = os.path.join(
                            self.dest, "Samples", "Loops", *loop_subfolders(f_normalized, f_lower))
                        stat_key = "Loops Separated by BPM & Key"
                    else:
                        classification_reason = "audio_fallback"
                        classification_confidence = 0.35
                        target_dir = os.path.join(self.dest, "Samples", "One-Shots", "Other One-Shots")
                        stat_key = "One-Shots Grouped by Drum Type"
                elif "presets" in root_lower or "instruments" in root_lower:
                    classification_reason = "parent_folder"
                    classification_confidence = 0.65
                    target_dir = os.path.join(self.dest, "Live Instrument Racks")
                    stat_key = "Native Live Racks (.adg, .amxd, .alc, .adv)"
                else:
                    self.skipped_records.append({"source": s_path, "reason": "unsupported_file_type"})
                    return

            target_dir = _validate_destination(self.dest, target_dir)
            _validate_destination(self.dest, os.path.join(target_dir, f))
            manual = tag_evidence.interpret_manual_tags(
                self.manual_live_assignments.get(os.path.normcase(os.path.abspath(s_path)), ())
            )
            if os.path.normpath(root) == target_dir and (
                not manual.assignments
            ):
                self.skipped_records.append({"source": s_path, "reason": "already_organized"})
                return
            tags = sorted(set(
                tags + derive_filename_tags(f) +
                [f"category:{os.path.basename(target_dir)}"]
            ))
            with self._plan_lock:
                record = self._reserve_destination(s_path, target_dir, f)
            record.update({
                "source": s_path, "filename": f, "destination": target_dir,
                "reason": classification_reason, "confidence": classification_confidence,
                "tags": tags, "stat_key": stat_key,
            })
            self.operation_plan.append(record)
            if self.preview_only or self._planning_only:
                tag_suggestion = None
                if manual.assignments:
                    suggested = (
                        os.path.normpath(os.path.join(self.dest, *tag_evidence.suggested_folder(manual.sound_type)))
                        if manual.sound_type and not manual.is_loop and manual.one_shot_eligible and ext in AUDIO_EXTS else None
                    )
                    if ext not in AUDIO_EXTS:
                        status = "non-audio item; no audio one-shot destination suggested"
                    elif not manual.one_shot_eligible:
                        status = "manual kit, multisample or impulse-response role; no one-shot suggestion"
                    elif not manual.alternatives:
                        status = "manual role only; no sound type inferred"
                    elif not manual.sound_type:
                        status = "conflicting manual sound types: " + ", ".join(manual.alternatives)
                    elif manual.is_loop or stat_key == "Loops Separated by BPM & Key":
                        status = "loop routing retained; one-shot suggestion not applicable"
                        if manual.is_loop and stat_key != "Loops Separated by BPM & Key":
                            status = "manual loop assignment conflicts with one-shot plan; review required"
                        suggested = None
                    elif suggested == target_dir:
                        status = "supports existing classification"
                    elif classification_reason == "audio_fallback":
                        status = "suggested alternative to catch-all"
                    else:
                        status = "conflicts with existing classification; review required"
                    tag_suggestion = {
                        "source": "live_manual", "assignments": list(manual.assignments),
                        "sound_type": manual.sound_type, "destination": suggested, "status": status,
                    }
                record["tag_suggestion"] = tag_suggestion
                if self.preview_only:
                    self.preview_records.append(record)
                    if record["action"] == "duplicate":
                        self.increment_stat_safe("Skipped Duplicate Items")
                return

            self._execute_record(record)
        except Exception as error:
            operation = "preview" if self.preview_only else ("copy" if self.copy_mode else "move")
            self.record_operation_error(
                locals().get("s_path", os.path.join(root, str(f))),
                locals().get("record", {}).get("destination_path", locals().get("target_dir", "")),
                operation,
                error
            )
            self.increment_stat_safe("Errors/Skipped Files")
        finally:
            with self.lock: 
                self.processed_files += 1

    @staticmethod
    def _destination_key(path):
        return os.path.abspath(path).casefold()

    @staticmethod
    def _routing_state():
        return json.dumps({
            "DRUM_KEYWORDS": DRUM_KEYWORDS, "RULE_METADATA": RULE_METADATA,
            "SYNTH_EXTS": SYNTH_EXTS, "NATIVE_EXTS": NATIVE_EXTS,
            "BPM_RANGES": BPM_RANGES, "LOOP_LAYOUT": LOOP_LAYOUT,
            "IGNORED_DIRECTORIES": IGNORED_DIRECTORIES,
        })

    def _reserve_destination(self, source, target_dir, filename):
        if os.path.islink(source) or not os.path.isfile(source):
            raise ValueError(f"Source must be an existing, unlinked file: {source}")
        directory = Path(os.path.abspath(target_dir))
        library = Path(os.path.abspath(self.dest))
        directory_keys = []
        while True:
            if os.path.lexists(directory) and not directory.is_dir():
                raise FileExistsError(f"A file blocks the planned destination folder: {directory}")
            directory_key = self._destination_key(directory)
            directory_keys.append(directory_key)
            reserved = self._reserved_destinations.get(directory_key)
            if reserved and reserved[1] is not None:
                raise FileExistsError(f"A planned file blocks the destination folder: {directory}")
            if directory == library:
                break
            directory = directory.parent
        folder = Path(target_dir).absolute()
        folders = {folder, *folder.parents} - self._destination_metadata_folders
        for metadata_folder in folders:
            _check_unlinked_path(metadata_folder / "Ableton Folder Info")
            ableton_tags.read_folder_tags(str(metadata_folder))
        self._destination_metadata.update(self._folder_metadata_state(folders))
        self._destination_metadata_folders.update(folders)
        source_identity = _file_identity(source)
        self._planned_directories.update(directory_keys)
        base, extension = os.path.splitext(filename)
        counter = 0
        while True:
            if self.cancel_event.is_set():
                raise ValueError("Destination planning cancelled; no file was transferred.")
            name = filename if not counter else f"{base}_{counter}{extension}"
            destination = os.path.join(target_dir, name)
            _validate_destination(self.dest, destination)
            key = self._destination_key(destination)
            reserved = self._reserved_destinations.get(key)
            identity = None
            provider = None
            if reserved:
                destination, identity, provider = reserved
            elif key in self._planned_directories:
                pass
            elif os.path.lexists(destination):
                if os.path.isfile(destination):
                    identity = _file_identity(destination)
                self._reserved_destinations[key] = (destination, identity, None)
            else:
                self._reserved_destinations[key] = (destination, source_identity, source)
                return {
                    "destination_path": destination, "source_identity": source_identity,
                    "destination_identity": None, "provider": None,
                    "action": "copy" if self.copy_mode else "move",
                    "collision": "rename" if counter else "none",
                }
            if identity and (identity["size"], identity["sha256"]) == (
                source_identity["size"], source_identity["sha256"]
            ):
                if (provider is None and os.path.normcase(source) != os.path.normcase(destination)
                        and os.path.samefile(source, destination)):
                    raise ValueError(f"Source and destination refer to the same file: {destination}")
                return {
                    "destination_path": destination, "source_identity": source_identity,
                    "destination_identity": identity, "provider": provider,
                    "action": "in_place" if os.path.normcase(source) == os.path.normcase(destination) else "duplicate",
                    "collision": "identical",
                }
            counter += 1

    def _execute_group(self, records):
        for record in records:
            if self.cancel_event.is_set():
                return
            try:
                self._execute_record(record)
            except Exception as error:
                self.record_operation_error(
                    record["source"], record["destination_path"],
                    "copy" if self.copy_mode else "move", error,
                )
                self.increment_stat_safe("Errors/Skipped Files")
            finally:
                with self.lock:
                    self.processed_files += 1

    def _execute_record(self, record):
        if self.cancel_event.is_set() or record["action"] == "in_place":
            return
        source, destination = record["source"], record["destination_path"]
        target_dir = os.path.dirname(destination)
        _validate_destination(self.dest, destination)
        if os.path.islink(source) or _file_identity(source) != record["source_identity"]:
            raise ValueError(f"Source changed after destination planning; preview again: {source}")
        duplicate = record["action"] == "duplicate"
        if duplicate:
            if record["provider"] and record["provider"] not in self._completed_plan_sources:
                raise ValueError(f"Planned duplicate depends on a file that was not transferred: {destination}")
            if not os.path.isfile(destination) or _file_identity(destination) != record["destination_identity"]:
                raise ValueError(f"Duplicate destination changed after planning; preview again: {destination}")
        elif os.path.lexists(destination):
            raise FileExistsError(f"Planned destination is now occupied; preview again: {destination}")
        os.makedirs(target_dir, exist_ok=True)
        _validate_destination(self.dest, destination)
        record_id = None
        if not self.copy_mode:
            if duplicate:
                record_id = self.retain_duplicate_for_undo(source, destination, record["tags"])
            else:
                record_id = self.log_move(source, destination, destination_identity=record["source_identity"])
        application = _transfer_application(
            record["reason"], record["confidence"], record["tags"],
            log_path=self.move_log_path if record_id else None, record_id=record_id,
        )
        ableton_tags.transfer_sample(
            source, destination, copy=self.copy_mode, duplicate=duplicate,
            application=application, reconcile=_reconcile_transfer_application,
        )
        self._completed_plan_sources.add(source)
        self.increment_stat_safe("Skipped Duplicate Items" if duplicate else record["stat_key"])
        current = self.processed_files + 1
        if current % 25 == 0 or current == self.total_files:
            self.window.after(0, lambda count=current: self.update_status(
                f"Filing Asset ({count}/{self.total_files}) -> {os.path.basename(destination)}"
            ))

# sorter_engine.py - Piece 7: Low-Level Data Validation & XML Tag Harvesters
    def force_delete_empty_folders(self, target_path):
        """Class method wrapper hook that allows test runners to cleanly trigger 
        the structural folder scrub utility across targeted path strings.
        """
        return force_delete_empty_folders(target_path)


class SerumResourceImporter(ParallelLibrarySorter):
    """Copy resources unchanged while sorting User presets by type and pack."""

    def __init__(self, src_path, dest_path, window_el, update_status_callback, done_callback,
                 copy_mode=True, preview_only=False, *, approved_plan=None):
        super().__init__(
            src_path, dest_path, window_el, update_status_callback, done_callback,
            copy_mode=copy_mode, smart_learning_enabled=False, preview_only=preview_only,
            approved_plan=approved_plan,
        )
        self.stats.update({
            "Serum 2 Resource Files Copied": 0,
            "Serum 2 Resource Files Planned": 0,
            "Serum 2 Resource Folders Created": 0,
        })
        self._resource_bytes_copied = 0

    @staticmethod
    def _check_path(path):
        _check_unlinked_path(path)

    def _resource_plan(self):
        source = Path(os.path.abspath(self.src))
        target = Path(os.path.abspath(self.dest)) / "Serum 2 Presets"
        self._check_path(source)
        self._check_path(target)
        if not self.copy_mode:
            raise ValueError("Complete Serum 2 resource imports are copy-only; originals must be kept.")
        if not all((source / name).is_dir() for name in ("Presets", "Tables", "Samples")):
            raise ValueError(
                "Select the complete Serum 2 resource folder containing Presets, Tables and Samples, "
                "not an individual preset subfolder."
            )
        try:
            common = os.path.commonpath((str(source), str(target)))
        except ValueError:
            common = ""
        if os.path.normcase(common) in (os.path.normcase(str(source)), os.path.normcase(str(target))):
            raise ValueError("Serum source and destination must not overlap; no files were copied.")
        directories = [target]
        files = []
        planned_paths = set()
        stack = [source]
        while stack:
            if self.cancel_event.is_set():
                return [], []
            directory = stack.pop()
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    self._check_path(path)
                    destination = target / path.relative_to(source)
                    self._check_path(destination)
                    if entry.is_dir(follow_symlinks=False):
                        directories.append(destination)
                        stack.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        relative = path.relative_to(source)
                        if (tuple(part.casefold() for part in relative.parts[:2]) == ("presets", "user")
                                and path.suffix.lower() in serum_presets.PRESET_EXTENSIONS):
                            destination = Path(os.path.abspath(self.dest)) / serum_presets.destination(
                                path.name, serum_presets.USER_FOLDER,
                                source=str(path), source_root=str(source / "Presets" / "User"),
                            ) / path.name
                            self._check_path(destination)
                            if destination.parent not in directories:
                                directories.append(destination.parent)
                        key = self._destination_key(str(destination))
                        if key in planned_paths:
                            raise FileExistsError(f"Multiple Serum resources map to the same destination: {destination}")
                        planned_paths.add(key)
                        identity = _file_identity(path)
                        duplicate = False
                        if destination.exists():
                            if not destination.is_file():
                                raise FileExistsError(f"A resource file conflicts with a folder: {destination}")
                            existing = _file_identity(destination)
                            duplicate = (identity["size"], identity["sha256"]) == (
                                existing["size"], existing["sha256"])
                            if not duplicate:
                                raise FileExistsError(
                                    f"Different resource file already exists: {destination}. "
                                    "Nothing was copied; choose a clean destination or resolve the conflict."
                                )
                        files.append((path, destination, identity, duplicate))
                    else:
                        raise ValueError(f"Unsupported resource entry: {path}")
        for directory in directories:
            self._check_path(directory)
            for parent in (directory, *directory.parents):
                if self._destination_key(str(parent)) in planned_paths:
                    raise NotADirectoryError(f"A planned resource folder conflicts with a preset file: {parent}")
                if parent.exists() and not parent.is_dir():
                    raise NotADirectoryError(f"A resource folder conflicts with a file: {parent}")
        return directories, files

    def _copy_resource(self, source, destination, identity):
        self._check_path(source)
        self._check_path(destination)
        if _file_identity(source) != identity:
            raise ValueError(f"Source changed after preview; not copied: {source}")
        with destination.open("xb") as output:
            try:
                with source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
                if _file_identity(source) != identity:
                    raise ValueError(f"Source changed during copy: {source}")
                copied = _file_identity(destination)
                if (copied["size"], copied["sha256"]) != (identity["size"], identity["sha256"]):
                    raise ValueError(f"Copied resource failed verification: {destination}")
            except (OSError, ValueError):
                output.close()
                destination.unlink()
                raise
        shutil.copystat(source, destination)

    def start_parallel_sort(self, *, job_lease=None):
        lease = self._claim_job("Serum resource preview" if self.preview_only else "Serum resource import", job_lease)
        if lease is None:
            return
        started = time.perf_counter()
        def pipeline():
            current_source = self.src
            current_destination = os.path.join(self.dest, "Serum 2 Presets")
            try:
                planning_started = time.perf_counter()
                self.window.after(0, lambda: self.update_status(
                    "Checking complete Serum 2 resource tree and destination conflicts..."
                ))
                directories, files = self._resource_plan()
                if self.cancel_event.is_set():
                    return
                self.phase_seconds["planning_seconds"] = time.perf_counter() - planning_started
                validation_started = time.perf_counter()
                if (directories, files) != self._resource_plan():
                    raise ValueError("Serum resource inputs changed during planning; no files were copied.")
                if self.cancel_event.is_set():
                    return
                self.total_files = len(files)
                self.reviewed_plan = {
                    "version": 1, "kind": "serum_resources",
                    "source_root": os.path.abspath(self.src), "destination_root": os.path.abspath(self.dest),
                    "copy_mode": bool(self.copy_mode),
                    "directories": [str(path) for path in directories],
                    "records": [{
                        "source": str(source), "destination_path": str(destination),
                        "source_identity": identity, "action": "duplicate" if duplicate else "copy",
                        "destination_identity": _file_identity(destination) if duplicate else None,
                    } for source, destination, identity, duplicate in files],
                    "settings": self._routing_state(), "skipped": [],
                    "integration_steps": [
                        "Select the copied Serum 2 Presets root as the plugin resource location.",
                        "Rescan Folders on Disk in Serum's preset browser after external changes.",
                        "Open a representative preset and verify its dependencies in Serum.",
                        "Original resources are retained; plugin preferences are not changed automatically.",
                    ],
                }
                if self.approved_plan is not None:
                    self.validate_approved_plan(self.approved_plan)
                self.phase_seconds["approval_validation_seconds"] = time.perf_counter() - validation_started
                transfer_started = time.perf_counter()
                if self.preview_only:
                    for source, destination, _identity, duplicate in files:
                        if self.cancel_event.is_set():
                            break
                        self.preview_records.append({
                            "source": str(source), "filename": str(source.relative_to(Path(os.path.abspath(self.src)))),
                            "destination": str(destination.parent),
                            "destination_path": str(destination),
                            "action": "duplicate" if duplicate else "copy",
                            "collision": "identical" if duplicate else "none",
                            "reason": "serum_resource_duplicate" if duplicate else "serum_resource_copy",
                            "confidence": 1.0, "tags": [],
                        })
                        key = "Skipped Duplicate Items" if duplicate else "Serum 2 Resource Files Planned"
                        self.increment_stat_safe(key)
                        self.processed_files += 1
                elif not self.cancel_event.is_set():
                    for directory in directories:
                        if self.cancel_event.is_set():
                            break
                        self._check_path(directory)
                        if not directory.exists():
                            directory.mkdir(parents=True, exist_ok=True)
                            self.increment_stat_safe("Serum 2 Resource Folders Created")
                    for source, destination, identity, duplicate in files:
                        if self.cancel_event.is_set():
                            break
                        current_source = str(source)
                        current_destination = str(destination)
                        if duplicate:
                            self._check_path(source)
                            self._check_path(destination)
                            current = _file_identity(destination)
                            if (_file_identity(source) != identity
                                    or (current["size"], current["sha256"]) != (
                                        identity["size"], identity["sha256"])):
                                raise ValueError(f"Duplicate changed during import: {destination}")
                            self.increment_stat_safe("Skipped Duplicate Items")
                        else:
                            self._copy_resource(source, destination, identity)
                            self._resource_bytes_copied += identity["size"]
                            self.increment_stat_safe("Serum 2 Resource Files Copied")
                        self.processed_files += 1
                        if self.processed_files % 100 == 0:
                            count = self.processed_files
                            self.window.after(0, lambda count=count: self.update_status(
                                f"Serum 2 resources checked/copied: {count:,}/{self.total_files:,}"
                            ))
                if not self.preview_only:
                    self.phase_seconds["transfer_seconds"] = time.perf_counter() - transfer_started
                message = (
                    "Serum 2 import cancelled; completed copies were kept, originals were not changed."
                    if self.cancel_event.is_set() else
                    "Serum 2 resource preview complete; no files changed."
                    if self.preview_only else
                    "Serum 2 resource import complete; User presets sorted by type and pack, other resource paths preserved."
                )
                self.window.after(0, lambda: self.update_status(message))
            except (OSError, ValueError) as error:
                self.record_operation_error(current_source, current_destination,
                                            "Serum 2 resource import", error)
                self.increment_stat_safe("Errors/Skipped Files")
                self.window.after(0, lambda error=error: self.update_status(
                    f"Serum 2 import stopped: {error}"
                ))
            finally:
                try:
                    self._record_performance(started, "serum_resource_import")
                finally:
                    lease.release()
                    self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))

        self._start_owned_thread(pipeline, lease, "serum-resource-import")


# ---------------------------------------------------------------------------------
# Low-Level Disk IO System Utilities (Sitting cleanly outside class scope)
# ---------------------------------------------------------------------------------

def _file_identity(filepath):
    with open(filepath, "rb") as handle:
        before = os.fstat(handle.fileno())
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"File changed while checking identity: {filepath}")
    return {"size": after.st_size, "sha256": digest, "modified_ns": after.st_mtime_ns}


def calculate_crc32(filepath):
    """Calculates data checksums to prevent filing duplicate audio assets."""
    try:
        with open(filepath, 'rb') as f:
            crc = 0
            while chunk := f.read(65536):
                crc = zlib.crc32(chunk, crc)
            return crc & 0xFFFFFFFF
    except Exception: return None

_KEY_PATTERN = (r'(?<!\w)([a-gA-G][#b]?m(?:in)?|'
                r'[a-gA-G][#b]?(?:maj)?|\d{1,2}[a-dB-D])(?!\w)')
_KEY_FOLDER_RE = re.compile(r'[a-g][#b]?m(?:in)?|[a-g][#b]?(?:maj)?|\d{1,2}[a-d]')


def loop_bpm_folder(f_normalized, f_lower):
    match = re.search(r'(?<!\w)(\d{2,3})\s*bpm(?!\w)', f_normalized)
    if not match:
        match = re.search(r'(?<!\w)(\d{2,3})(?!\w)', f_lower)
    if match:
        try:
            bpm = int(match.group(1))
        except ValueError:
            return "Unsorted Tempos"
        if 40 <= bpm <= 250:
            for low, high, folder_name in BPM_RANGES:
                if low <= bpm <= high:
                    return folder_name
    return "Unsorted Tempos"


def loop_key_folder(f_normalized):
    match = re.search(_KEY_PATTERN, f_normalized)
    return match.group(1).upper() if match else "No Key Info"


def loop_subfolders(f_normalized, f_lower, layout=None):
    """Folder names under Samples/Loops for one loop, following the chosen layout."""
    parts = []
    for level in (LOOP_LAYOUT if layout is None else layout):
        parts.append(loop_bpm_folder(f_normalized, f_lower) if level == "bpm"
                     else loop_key_folder(f_normalized))
    return parts


def is_generated_loop_folder(segments):
    """True when every folder level is one this app creates (BPM range, key, or its fallback)."""
    labels = {label.lower() for _low, _high, label in BPM_RANGES} | {"unsorted tempos", "no key info"}
    return all(seg in labels or _KEY_FOLDER_RE.fullmatch(seg) for seg in segments)


def recommend_loop_layout(library_root, should_cancel=None):
    """Recommend executable filename layout and audit independent manual tag evidence."""
    if not os.path.isdir(library_root):
        raise OSError("The configured User Library is unavailable. Check its location before scanning.")
    totals = {"loops": 0}
    found = {level: 0 for level in LOOP_LEVELS}
    distinct = {level: set() for level in LOOP_LEVELS}
    paths = []
    for dirpath, dirnames, filenames in os.walk(library_root):
        if should_cancel and should_cancel():
            raise ValueError("Loop layout recommendation was cancelled.")
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRECTORIES]
        for filename in filenames:
            if ableton_tags.is_metadata_stub(filename):
                continue
            if os.path.splitext(filename)[1].lower() not in AUDIO_EXTS:
                continue
            paths.append(os.path.normpath(os.path.join(dirpath, filename)))
    manual = ableton_tags.read_sample_assignments(paths)
    audit = {
        "manual_loops": 0, "tag_only_loops": 0, "role_conflicts": 0,
        "complete_keys": 0, "ambiguous_keys": 0, "incomplete_keys": 0,
        "key_conflicts": 0, "keys_missing_from_filenames": 0, "examples": [],
    }
    for path in paths:
        if should_cancel and should_cancel():
            raise ValueError("Loop layout recommendation was cancelled.")
        filename = os.path.basename(path)
        f_lower = filename.lower()
        f_normalized = re.sub(r'[_#\-]', ' ', f_lower)
        has_bpm = re.search(r'\b\d{2,3}\s*(bpm|BPM)\b', f_normalized)
        filename_loop = bool(has_bpm or any(k in f_normalized for k in ('loop', 'fill', 'roll', 'groove')))
        assignments = manual.get(os.path.normcase(os.path.abspath(path)), ())
        evidence = tag_evidence.interpret_manual_tags(assignments)
        manual_key = tag_evidence.interpret_manual_key(assignments)
        notes = []
        if evidence.is_loop:
            audit["manual_loops"] += 1
            if not filename_loop:
                audit["tag_only_loops"] += 1
                notes.append("manual loop role without a filename loop hint")
        one_shot = any(tag.casefold() == "type|one shot" for tag in assignments)
        if (filename_loop or evidence.is_loop) and (one_shot or not evidence.one_shot_eligible):
            audit["role_conflicts"] += 1
            notes.append("manual role conflicts with a loop/one-shot interpretation")
        if filename_loop or evidence.is_loop:
            filename_key = loop_key_folder(f_normalized)
            if manual_key.ambiguous:
                audit["ambiguous_keys"] += 1
                notes.append("multiple manual roots or modes; no key inferred")
            elif manual_key.key:
                audit["complete_keys"] += 1
                if filename_key == "No Key Info":
                    audit["keys_missing_from_filenames"] += 1
                    notes.append("manual key is absent from the filename routing plan")
                elif tag_evidence.key_identity(filename_key) not in (None, manual_key.key):
                    audit["key_conflicts"] += 1
                    notes.append("manual key disagrees with the filename key")
            elif manual_key.assignments:
                audit["incomplete_keys"] += 1
                notes.append("manual key needs both one root and one mode")
        if notes and len(audit["examples"]) < 10:
            audit["examples"].append({
                "path": path, "assignments": list(evidence.assignments + manual_key.assignments),
                "manual_key": manual_key.key, "notes": notes,
            })
        if not filename_loop:
            continue
        totals["loops"] += 1
        bpm = loop_bpm_folder(f_normalized, f_lower)
        if bpm != "Unsorted Tempos":
            found["bpm"] += 1
            distinct["bpm"].add(bpm)
        key = loop_key_folder(f_normalized)
        if key != "No Key Info":
            found["key"] += 1
            distinct["key"].add(key)
    loops = totals["loops"]
    stats = {level: {"coverage": (found[level] / loops if loops else 0.0),
                     "folders": len(distinct[level])} for level in LOOP_LEVELS}
    usable = [level for level in LOOP_LEVELS if stats[level]["coverage"] >= 0.5]
    usable.sort(key=lambda level: (stats[level]["folders"], LOOP_LEVELS.index(level)))
    if not loops:
        usable = list(LOOP_LEVELS)
    return {"layout": usable, "loops": loops, "stats": stats, "tag_evidence": audit}


def force_delete_empty_folders(root_dir):
    """Recursively sweeps and clears out dead paths from storage blocks."""
    count = 0
    for root, dirs, _ in os.walk(root_dir, topdown=False):
        if serum_presets.is_resource_path(root):
            continue
        for d in dirs:
            dir_path = os.path.join(root, d)
            if serum_presets.is_resource_path(dir_path):
                continue
            try:
                if os.name == "nt":
                    os.chmod(dir_path, stat.S_IWRITE)
                if not os.listdir(dir_path):
                    os.rmdir(dir_path)
                    count += 1
            except Exception: pass
    return count

def harvest_ableton_metadata(src_directory):
    """Parses xmp.cfg metadata blocks to extract native project tags."""
    metadata_map = {}
    for root, dirs, files in os.walk(src_directory):
        if os.path.basename(root) == "Ableton Folder Info":
            cfg_path = os.path.join(root, "xmp.cfg")
            if not os.path.exists(cfg_path): continue
            try:
                tree = ET.parse(cfg_path)
                xml_root = tree.getroot()
                for content_tag in xml_root.findall('.//ContentExtId'):
                    filename = content_tag.get('Name')
                    if not filename: continue
                    tags_list = []
                    for tag_entry in content_tag.findall('.//Tag'):
                        tag_id = tag_entry.get('Id')
                        if tag_id: tags_list.append(tag_id.split('/')[-1].lower())
                    if tags_list:
                        normalized_name = os.path.normpath(filename).lower()
                        existing_tags = metadata_map.setdefault(normalized_name, [])
                        metadata_map[normalized_name] = sorted(
                            set(existing_tags + tags_list)
                        )
                        basename_key = os.path.basename(normalized_name)
                        if basename_key != normalized_name:
                            existing_basename_tags = metadata_map.setdefault(basename_key, [])
                            metadata_map[basename_key] = sorted(
                                set(existing_basename_tags + tags_list)
                            )
            except Exception: pass
    return metadata_map

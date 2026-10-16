# sorter_engine.py - Piece 1: Core Configuration Matrices & Global State Setup
import os
import sys
import json
import re
import zlib
import stat
import shutil
import subprocess
import threading
import sqlite3
import datetime
import xml.etree.ElementTree as ET
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

# Core Shared Platform State Configuration Mapping
CONFIG_FILE = "library_config.json"
ASSET_INDEX_FILE = "library_assets.db"
AUDIO_EXTS = {
    ".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".oga", ".m4a",
    ".aac", ".wma", ".opus", ".caf", ".au", ".snd"
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
LEARNING_COUNTS = {}
LEARNED_RULE_CANDIDATES = []
_ASSET_SCHEMA_READY = set()
_ASSET_SCHEMA_LOCK = threading.Lock()

ROUTING_TAG_FOLDERS = {
    "role:kick": "Kicks",
    "role:snare": "Snares",
    "role:hat": "Hi-Hats",
    "role:clap": "Claps",
    "role:tom": "Toms",
    "role:perc": "Percussion",
    "role:shaker": "Percussion/Shakers",
    "role:vocal": "Vocals & Chants",
    "role:fx": "Sound FX",
    "instrument:bass": "Synth Bass One-Shots",
    "instrument:808": "808 Sub Bass",
    "instrument:synth": "Melodic & Synth One-Shots",
    "instrument:ambient": "Cinematic & Ambience",
}

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
        "SYNTH_EXTS": {".fxp": "Serum Presets", ".fxb": "Serum Banks"},
        "NATIVE_EXTS": {".adg": "Live Instrument Racks", ".amxd": "Max For Live Devices"},
        "IGNORED_DIRECTORIES": ["eastwest", "kontakt library", "spectrasonics", "steam",
                               "vstplugins", "common files"],
        **_default_learning_state()
    }

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
    if not isinstance(data.get("IGNORED_DIRECTORIES", []), list):
        raise ValueError("IGNORED_DIRECTORIES must be a list.")
    if not isinstance(data.get("LEARNING_COUNTS", {}), dict):
        raise ValueError("LEARNING_COUNTS must be an object.")
    if not isinstance(data.get("LEARNED_RULE_CANDIDATES", []), list):
        raise ValueError("LEARNED_RULE_CANDIDATES must be a list.")
    if not isinstance(data.get("RULE_METADATA", {}), dict):
        raise ValueError("RULE_METADATA must be an object.")
    return data

def load_external_config():
    """Reads configuration matrices directly from disk to keep UI settings synced."""
    global BPM_RANGES, DRUM_KEYWORDS, SYNTH_EXTS, NATIVE_EXTS, IGNORED_DIRECTORIES
    global RULE_METADATA
    global SMART_LEARNING_ENABLED, LEARNING_COUNTS, LEARNED_RULE_CANDIDATES
    if not os.path.exists(CONFIG_FILE):
        _write_config(_default_config(), create_backup=False)
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            user_rules = _validate_config(json.load(f))
    except (OSError, json.JSONDecodeError, ValueError) as error:
        backup_path = f"{CONFIG_FILE}.bak"
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                user_rules = _validate_config(json.load(f))
            os.replace(backup_path, CONFIG_FILE)
        except (OSError, json.JSONDecodeError, ValueError) as backup_error:
            raise ValueError(
                f"Configuration is invalid ({error}) and no valid backup was found "
                f"({backup_error})."
            ) from error
    BPM_RANGES = [tuple(x) for x in user_rules.get("BPM_RANGES", [])]
    DRUM_KEYWORDS = user_rules.get("DRUM_KEYWORDS", {})
    SYNTH_EXTS = user_rules.get("SYNTH_EXTS", {})
    NATIVE_EXTS = user_rules.get("NATIVE_EXTS", {})
    IGNORED_DIRECTORIES = user_rules.get("IGNORED_DIRECTORIES", [])
    SMART_LEARNING_ENABLED = bool(user_rules.get("SMART_LEARNING_ENABLED", True))
    LEARNING_COUNTS = user_rules.get("LEARNING_COUNTS", {})
    LEARNED_RULE_CANDIDATES = user_rules.get("LEARNED_RULE_CANDIDATES", [])
    RULE_METADATA = user_rules.get("RULE_METADATA", {})
    for index, pattern in enumerate(DRUM_KEYWORDS):
        RULE_METADATA.setdefault(pattern, {
            "priority": len(DRUM_KEYWORDS) - index,
            "enabled": True,
            "exclude": []
        })
    return user_rules

def _write_config(data, create_backup=True):
    """Writes configuration through a temporary file so interrupted writes do not corrupt it."""
    _validate_config(data)
    temporary_path = f"{CONFIG_FILE}.tmp"
    with open(temporary_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    if create_backup and os.path.exists(CONFIG_FILE):
        shutil.copy2(CONFIG_FILE, f"{CONFIG_FILE}.bak")
        backup_config()
    os.replace(temporary_path, CONFIG_FILE)

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
        1 for candidate in LEARNED_RULE_CANDIDATES if candidate.get("status", "pending") == "pending"
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
    return os.path.join(_move_log_dir(), f"moves_{stamp}.jsonl")

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
        if os.path.getsize(log) > 0:
            return log
    return None

def describe_move_log(log_path):
    """Returns (file_count, created_text) for a move log."""
    with open(log_path, 'r', encoding='utf-8') as f:
        count = sum(1 for line in f if line.strip())
    created = datetime.datetime.fromtimestamp(os.path.getmtime(log_path)).strftime("%b %d, %Y %I:%M %p")
    return count, created

def undo_move_log(log_path, progress=None):
    """Moves every file in the log back to where it came from. Nothing is overwritten."""
    with open(log_path, 'r', encoding='utf-8') as f:
        records = [json.loads(line) for line in f if line.strip()]
    results = {"restored": 0, "skipped": 0, "errors": []}
    connection = None
    try:
        connection = _asset_index_connection()
    except (OSError, sqlite3.Error):
        connection = None
    touched_dirs = set()
    for index, record in enumerate(reversed(records)):
        source, destination = record["source"], record["destination"]
        try:
            if not os.path.exists(destination) or os.path.exists(source):
                results["skipped"] += 1
                continue
            os.makedirs(os.path.dirname(source), exist_ok=True)
            os.replace(destination, source)
            touched_dirs.add(os.path.dirname(destination))
            results["restored"] += 1
            if connection is not None:
                try:
                    connection.execute("UPDATE assets SET path = ? WHERE path = ?", (source, destination))
                    connection.execute(
                        "DELETE FROM asset_tags WHERE asset_path = ? AND tag LIKE 'category:%'", (destination,))
                    connection.execute("UPDATE asset_tags SET asset_path = ? WHERE asset_path = ?", (source, destination))
                except sqlite3.Error:
                    pass
        except OSError as error:
            results["errors"].append(f"{destination}: {error}")
        if progress and index % 200 == 0:
            progress(index + 1, len(records))
    if connection is not None:
        try:
            connection.commit()
        finally:
            connection.close()
    for folder in sorted(touched_dirs, key=len, reverse=True):
        try:
            os.rmdir(folder)
        except OSError:
            pass
    if not results["errors"]:
        os.replace(log_path, log_path + ".undone")
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
            and data.get("version") == 1
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
        "version": 1, "fingerprint": fingerprint, "library_root": str(library_root),
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
                    "INSERT OR IGNORE INTO asset_tags (asset_path, tag) "
                    "SELECT ?, tag FROM asset_tags WHERE asset_path = ?",
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
                for tag in sorted(set(tags)) if tag and not tag.startswith("user:")
            ]
        )
        if _connection is None:
            connection.commit()
    finally:
        if _connection is None:
            connection.close()

def index_existing_library(library_root):
    """Indexes supported files already present in a User Library without moving them."""
    root = os.path.normpath(library_root)
    if not os.path.isdir(root):
        return 0
    indexed_count = 0
    stack = [root]
    visited = set()
    connection = _asset_index_connection()
    try:
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
            try:
                entries = os.scandir(normalized_current)
            except OSError:
                continue
            with entries:
                for entry in entries:
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
        connection.commit()
        return indexed_count
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
                "SELECT tag, enabled FROM asset_tags WHERE asset_path = ? ORDER BY tag",
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
            "updated_at": asset[7], "tags": tags, "disabled_tags": disabled_tags
        }
    finally:
        connection.close()

def get_asset_tags(path):
    """Returns stored tags for a path without treating personal tags as routing rules."""
    connection = _asset_index_connection()
    try:
        return [
            row[0] for row in connection.execute(
                "SELECT tag FROM asset_tags WHERE asset_path = ? AND enabled = 1 ORDER BY tag",
                (os.path.normpath(path),)
            )
        ]
    finally:
        connection.close()

def get_all_indexed_asset_tags():
    """Loads enabled indexed tags once for a sorter run."""
    connection = _asset_index_connection()
    try:
        tags_by_path = {}
        for asset_path, tag in connection.execute(
            "SELECT asset_path, tag FROM asset_tags "
            "WHERE enabled = 1 ORDER BY asset_path, tag"
        ):
            tags_by_path.setdefault(asset_path, []).append(tag)
        return tags_by_path
    finally:
        connection.close()

def _parse_asset_search(search_text):
    """Splits simple browser syntax into positive and negative search constraints."""
    parsed = {"terms": [], "excluded_terms": [], "tags": [], "excluded_tags": [],
              "types": [], "bpms": [], "keys": [], "reasons": []}
    for raw_token in re.findall(r'"[^"]+"|\S+', search_text.lower()):
        token = raw_token.strip('"')
        excluded = token.startswith("-")
        if excluded:
            token = token[1:]
        if not token:
            continue
        name, separator, value = token.partition(":")
        target = None
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

def _library_root_clause(root_path, column="a.path"):
    """Returns a parameterized clause restricting paths to one directory tree."""
    if not root_path:
        return "", []
    normalized_root = os.path.normcase(os.path.normpath(root_path))
    return (
        f"(LOWER({column}) = LOWER(?) OR LOWER({column}) LIKE LOWER(?))",
        [normalized_root, f"{normalized_root}{os.sep}%"],
    )

def _asset_rows_with_tags(connection, rows):
    paths = [row[0] for row in rows]
    tags_by_path = {path: [] for path in paths}
    if paths:
        placeholders = ",".join("?" for _ in paths)
        tag_rows = connection.execute(
            f"SELECT asset_path, tag FROM asset_tags "
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
    library_root=None, count_only=False
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
        simple_collection = (
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
                return _asset_rows_with_tags(connection, rows)
        combined_collection_tag = (
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
                        JOIN asset_tags tf ON tf.asset_path = a.path
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
                    JOIN asset_tags tf ON tf.asset_path = a.path
                        AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?
                    WHERE {where_sql}
                    ORDER BY a.filename COLLATE NOCASE
                    LIMIT ? OFFSET ?
                    """,
                    query_parameters + [limit, offset]
                ).fetchall()
                return _asset_rows_with_tags(connection, rows)
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
                    JOIN asset_tags tf ON tf.asset_path = a.path
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
                JOIN asset_tags tf ON tf.asset_path = a.path
                    AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?
                WHERE {root_clause + ' AND ' if root_clause else ''}
                      ({extension_clauses})
                ORDER BY a.filename COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                query_parameters
                + [limit, offset]
            ).fetchall()
            return _asset_rows_with_tags(connection, rows)
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
                    JOIN asset_tags tf ON tf.asset_path = a.path
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
                JOIN asset_tags tf ON tf.asset_path = a.path
                    AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = 'favorite'
                WHERE {root_clause + ' AND ' if root_clause else ''}
                      ({extension_clauses})
                ORDER BY a.filename COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                query_parameters
                + [limit, offset]
            ).fetchall()
            return _asset_rows_with_tags(connection, rows)
        simple_browser_query = not (
            parsed["terms"] or parsed["excluded_terms"] or parsed["tags"]
            or parsed["excluded_tags"] or parsed["types"] or parsed["bpms"]
            or parsed["keys"] or parsed["reasons"] or tag_filter.strip()
            or favorites_only
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
            return _asset_rows_with_tags(connection, rows)
        for term in parsed["terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "(LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM asset_tags ts WHERE ts.asset_path = a.path "
                "AND ts.enabled = 1 AND LOWER(ts.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for term in parsed["excluded_terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "NOT (LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM asset_tags tx WHERE tx.asset_path = a.path "
                "AND tx.enabled = 1 AND LOWER(tx.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for tag in parsed["tags"]:
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) = ?)"
            )
            parameters.append(tag.lower())
        for tag in parsed["excluded_tags"]:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM asset_tags sx WHERE sx.asset_path = a.path "
                "AND sx.enabled = 1 AND LOWER(sx.tag) = ?)"
            )
            parameters.append(tag.lower())
        for value in parsed["types"] + parsed["bpms"] + parsed["keys"]:
            pattern = f"%{value}%"
            clauses.append(
                "(LOWER(a.path) LIKE ? OR LOWER(a.destination) LIKE ? OR EXISTS "
                "(SELECT 1 FROM asset_tags sv WHERE sv.asset_path = a.path "
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
                " JOIN asset_tags tf ON tf.asset_path = a.path "
                "AND tf.enabled = 1 AND LOWER(TRIM(tf.tag)) = ?"
            )
            tag_join_parameters.append(tag_filter.strip().lower())
        if favorites_only:
            tag_join += (
                " JOIN asset_tags tfav ON tfav.asset_path = a.path "
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
        return _asset_rows_with_tags(connection, rows)
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
        for term in parsed["terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "(LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for term in parsed["excluded_terms"]:
            pattern = f"%{term}%"
            clauses.append(
                "NOT (LOWER(a.filename) LIKE ? OR LOWER(a.path) LIKE ? OR "
                "LOWER(a.destination) LIKE ? OR EXISTS ("
                "SELECT 1 FROM asset_tags sx WHERE sx.asset_path = a.path "
                "AND sx.enabled = 1 AND LOWER(sx.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern, pattern])
        for tag in parsed["tags"]:
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) = ?)"
            )
            parameters.append(tag.lower())
        for tag in parsed["excluded_tags"]:
            clauses.append(
                "NOT EXISTS (SELECT 1 FROM asset_tags sx WHERE sx.asset_path = a.path "
                "AND sx.enabled = 1 AND LOWER(sx.tag) = ?)"
            )
            parameters.append(tag.lower())
        for value in parsed["types"] + parsed["bpms"] + parsed["keys"]:
            pattern = f"%{value}%"
            clauses.append(
                "(LOWER(a.path) LIKE ? OR LOWER(a.destination) LIKE ? OR EXISTS "
                "(SELECT 1 FROM asset_tags st WHERE st.asset_path = a.path "
                "AND st.enabled = 1 AND LOWER(st.tag) LIKE ?))"
            )
            parameters.extend([pattern, pattern, pattern])
        if favorites_only:
            clauses.append(
                "EXISTS (SELECT 1 FROM asset_tags sf WHERE sf.asset_path = a.path "
                "AND sf.enabled = 1 AND LOWER(TRIM(sf.tag)) = 'favorite')"
            )
        if root_clause:
            clauses.append(root_clause)
            parameters.extend(root_parameters)
        return connection.execute(
            "WITH a AS MATERIALIZED (SELECT * FROM assets a "
            f"WHERE {extension_clauses}) "
            "SELECT t.tag, COUNT(*) FROM asset_tags t "
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
    """Adds one normalized user tag to an indexed asset."""
    normalized_tag = tag.strip().lower()
    if not normalized_tag:
        raise ValueError("Tag cannot be empty.")
    if len(normalized_tag) > 80 or "\n" in normalized_tag:
        raise ValueError("Tag must be 80 characters or fewer and contain no newlines.")
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
    """Removes one user-visible tag from an indexed asset."""
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
    """Applies one personal tag change to several indexed assets atomically."""
    normalized_tag = tag.strip().lower()
    if not normalized_tag:
        raise ValueError("Tag cannot be empty.")
    if len(normalized_tag) > 80 or "\n" in normalized_tag:
        raise ValueError("Tag must be 80 characters or fewer and contain no newlines.")
    normalized_paths = sorted({os.path.normpath(path) for path in paths})
    if not normalized_paths:
        raise ValueError("Select at least one indexed sound.")
    connection = _asset_index_connection()
    try:
        if remove:
            placeholders = ",".join("?" for _path in normalized_paths)
            connection.execute(
                f"DELETE FROM asset_tags WHERE tag = ? AND asset_path IN ({placeholders})",
                [normalized_tag, *normalized_paths]
            )
        else:
            connection.executemany(
                "INSERT INTO asset_tags (asset_path, tag, enabled, source) "
                "VALUES (?, ?, ?, 'personal') "
                "ON CONFLICT(asset_path, tag) DO UPDATE SET enabled = excluded.enabled",
                [(path, normalized_tag, 1 if enabled else 0) for path in normalized_paths]
            )
        connection.commit()
    finally:
        connection.close()

def set_asset_tag_enabled(path, tag, enabled):
    """Enables or disables an existing tag without deleting its assignment."""
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

def resolve_routing_tags(tags):
    """Resolves explicit routing tags; ordinary descriptive/personal tags are ignored."""
    tag_set = {tag.strip().lower() for tag in tags}
    if "type:loop" in tag_set:
        return "loop", None
    if "type:one-shot" in tag_set or "type:oneshot" in tag_set:
        for tag, folder in ROUTING_TAG_FOLDERS.items():
            if tag in tag_set:
                return "one-shot", folder
        return "one-shot", None
    for tag, folder in ROUTING_TAG_FOLDERS.items():
        if tag in tag_set:
            return "one-shot", folder
    return None, None

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
    for suggestion in suggestions:
        source = os.path.normpath(suggestion["source"])
        destination = os.path.normpath(suggestion["destination"])
        if not os.path.isfile(source) or os.path.exists(destination):
            results["skipped"] += 1
            continue
        try:
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.move(source, destination)
            results["moved"] += 1
        except OSError as error:
            results["errors"].append(f"{source}: {error}")
    return results

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
        result["destination"] = SYNTH_EXTS[ext]
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

def record_learning_evidence(evidence, minimum_count=5):
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
        if entry["count"] < minimum_count:
            continue
        if any(c.get("token") == token and c.get("target") == target
               and c.get("status", "pending") == "pending" for c in candidates):
            continue
        candidate = {
            "token": token,
            "target": target,
            "count": entry["count"],
            "pattern": build_learned_rule_pattern(token),
            "status": "pending"
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
    if decision not in {"approved", "rejected"}:
        raise ValueError("Candidate decision must be approved or rejected.")

    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    candidates = data.setdefault("LEARNED_RULE_CANDIDATES", [])
    matching = [
        candidate for candidate in candidates
        if candidate.get("token") == token and candidate.get("target") == target
        and candidate.get("status", "pending") == "pending"
    ]
    if not matching:
        raise ValueError("Pending learning candidate was not found.")

    candidate = matching[0]
    candidate["status"] = decision
    if decision == "approved":
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
    _write_config(data)
    load_external_config()

# Force load on module call so imports immediately populate global configuration states
load_external_config()

# sorter_engine.py - Piece 2: Class Initialization & Background Thread Routing
class ParallelLibrarySorter:
    def __init__(self, src_path, dest_path, window_el, update_status_callback, done_callback, copy_mode=False,
                 smart_learning_enabled=None, preview_only=False):
        """Initializes the multi-threaded file distribution and structural optimization engine."""
        self.src = os.path.normpath(src_path)
        self.dest = os.path.normpath(dest_path)
        self.window = window_el
        self.update_status = update_status_callback
        self.done_callback = done_callback
        self.copy_mode = copy_mode
        self.smart_learning_enabled = SMART_LEARNING_ENABLED if smart_learning_enabled is None else bool(smart_learning_enabled)
        self.preview_only = bool(preview_only)
        
        self.total_files = 0
        self.processed_files = 0
        self.raw_unmatched_tokens = []
        self.harvested_metadata = {}
        self.preview_records = []
        self.move_log_path = None
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.worker_thread = None
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
            "Errors/Skipped Files": 0,
            "New Metadata Rules Learned & Written": 0,
            "New Learning Candidates": 0
        }

    def start_parallel_sort(self):
        """Spins up background threading networks to execute operations without freezing the UI."""
        def background_execution_pipeline():
            # 🌟 TRACKING FLAG: Prevents the UI done_callback from being triggered multiple times
            callback_triggered = False
            
            try:
                if not self.copy_mode and not self.preview_only:
                    self.window.after(0, lambda: self.update_status("Executing background system sanity check..."))
                    ghost_presets = os.path.normpath(os.path.join(self.dest, "Presets", "Instruments", "Presets", "Instruments"))
                    one_shots_root = os.path.normpath(os.path.join(self.dest, "Samples", "One-Shots"))
                    
                    if os.path.exists(ghost_presets):
                        repair_script = f"""
                        if (Test-Path -LiteralPath '{ghost_presets}') {{
                            $Files = Get-ChildItem -LiteralPath '{ghost_presets}' -File -ErrorAction SilentlyContinue
                            foreach ($File in $Files) {{
                                Set-ItemProperty -LiteralPath $File.FullName -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
                                Move-Item -LiteralPath $File.FullName -Destination '{os.path.normpath(os.path.join(self.dest, "Live Instrument Racks"))}' -Force -Confirm:$false
                            }}
                            Remove-Item -LiteralPath '{ghost_presets}' -Recurse -Force -ErrorAction SilentlyContinue
                        }}
                        """
                        try:
                            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", repair_script],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        except Exception: pass

                    if os.path.exists(one_shots_root):
                        try:
                            for folder in os.listdir(one_shots_root):
                                cat_path = os.path.join(one_shots_root, folder)
                                if os.path.isdir(cat_path):
                                    for target_ghost in ["Samples", "Loops"]:
                                        ghost_target_path = os.path.normpath(os.path.join(cat_path, target_ghost))
                                        if os.path.exists(ghost_target_path):
                                            dynamic_repair = f"""
                                            $GhostPath = '{ghost_target_path}'
                                            $FlatRoot = '{cat_path}'
                                            if (Test-Path -LiteralPath $GhostPath) {{
                                                $Files = Get-ChildItem -LiteralPath $GhostPath -Recurse -File -ErrorAction SilentlyContinue
                                                foreach ($File in $Files) {{
                                                    Set-ItemProperty -LiteralPath $File.FullName -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
                                                    Move-Item -LiteralPath $File.FullName -Destination $FlatRoot -Force -Confirm:$false
                                                }}
                                                Remove-Item -LiteralPath $GhostPath -Recurse -Force -ErrorAction SilentlyContinue
                                            }}
                                            """
                                            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", dynamic_repair],
                                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
                        except Exception: pass

                    try:
                        extracted_count = self.nuclear_powershell_flatten(self.src)
                        if extracted_count > 0:
                            self.stats["Native Live Racks (.adg, .amxd, .alc, .adv)"] += extracted_count
                    except Exception: pass

                self.window.after(0, lambda: self.update_status("Extracting Ableton browser tagging metadata..."))
                
                try: self.harvested_metadata = harvest_ableton_metadata(self.src)
                except Exception: self.harvested_metadata = {}
                try:
                    self.indexed_tags_by_path = get_all_indexed_asset_tags()
                    self.indexed_tags_cache_loaded = True
                except sqlite3.Error:
                    self.indexed_tags_by_path = {}
                    self.indexed_tags_cache_loaded = True

                self.window.after(0, lambda: self.update_status("Scanning directory layout safely..."))

                execution_manifest = []
                stack = [self.src]
                visited_paths = set()
                max_depth_guard = 0
                scanned_entries = 0

                while stack:
                    if self.cancel_event.is_set():
                        self.window.after(0, lambda: self.update_status("Operation cancelled. Finishing current file safely."))
                        return
                    max_depth_guard += 1
                    if max_depth_guard > 50000: 
                        break

                    current_dir = stack.pop()
                    current_norm = os.path.normpath(current_dir)

                    if current_norm in visited_paths or "Ableton Folder Info" in current_norm:
                        continue
                    visited_paths.add(current_norm)

                    relative_branch = current_norm.replace(self.src, "").strip(os.sep)
                    branch_segments = [seg for seg in relative_branch.split(os.sep) if seg.strip()]
                    if len(branch_segments) > 6:
                        continue

                    try:
                        for entry in os.scandir(current_norm):
                            if entry.is_symlink():
                                continue
                                
                            entry_norm = os.path.normpath(entry.path)
                            entry_lower = entry_norm.lower()

                            if entry.is_dir(follow_symlinks=False):
                                if any(ignore.lower() in entry_lower for ignore in IGNORED_DIRECTORIES if ignore.strip()):
                                    continue
                                    
                                stack.append(entry.path)
                            elif entry.is_file():
                                if entry.name == "library_config.json" or entry.name.endswith(".py") or entry.name.endswith(".pyw"):
                                    continue
                                execution_manifest.append((current_norm, entry.name))
                                scanned_entries += 1
                                if scanned_entries % 1000 == 0:
                                    count_snapshot = scanned_entries
                                    self.window.after(
                                        0,
                                        lambda count=count_snapshot: self.update_status(
                                            f"Scanning directory layout safely... "
                                            f"{count:,} files found"
                                        )
                                    )
                    except Exception:
                        pass

                self.total_files = len(execution_manifest)
                
                if self.total_files == 0 and self.stats["Native Live Racks (.adg, .amxd, .alc, .adv)"] == 0:
                    self.window.after(0, lambda: self.update_status("Scan complete. Library folders match rule taxonomies."))
                    if not callback_triggered:
                        callback_triggered = True
                        self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))
                    return

                if self.total_files > 0:
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        batch_size = 256
                        for batch_start in range(0, self.total_files, batch_size):
                            if self.cancel_event.is_set():
                                break
                            batch = execution_manifest[batch_start:batch_start + batch_size]
                            futures = [
                                executor.submit(self.process_single_file, *item)
                                for item in batch
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
                                lambda completed=min(
                                    batch_start + len(batch), self.total_files
                                ): self.update_status(
                                    f"Batch complete ({completed}/{self.total_files})"
                                )
                            )

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
                    
                if self.cancel_event.is_set():
                    self.window.after(0, lambda: self.update_status("Operation cancelled. No new files will be processed."))
                else:
                    self.window.after(0, lambda: self.update_status("Task optimization complete!"))
                if not callback_triggered:
                    callback_triggered = True
                    self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))
                
                # 🌟 CRITICAL FIX: Explicitly exit the background thread execution pipeline right here!
                # This completely blocks the function from sliding down into the generic 'except' handler.
                return
            
            except Exception as pipeline_err:
                self.window.after(0, lambda: self.update_status(f"Error: {str(pipeline_err)}"))
                if not callback_triggered:
                    callback_triggered = True
                    self.window.after(0, lambda: self.done_callback(self.stats, self.copy_mode))

        self.worker_thread = threading.Thread(
            target=background_execution_pipeline,
            name="library-sorter",
            daemon=True
        )
        self.worker_thread.start()

    def cancel(self):
        """Requests cancellation without interrupting the file currently being processed."""
        self.cancel_event.set()

    def is_running(self):
        """Returns whether the sorter worker is still active."""
        return self.worker_thread is not None and self.worker_thread.is_alive()

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

    def log_move(self, source, destination):
        """Appends one move to the run's undo log as soon as it happens, so a crash still leaves a usable log."""
        with self.lock:
            if self.move_log_path is None:
                self.move_log_path = _new_move_log_path()
            with open(self.move_log_path, 'a', encoding='utf-8') as log:
                log.write(json.dumps({"source": os.path.normpath(source),
                                      "destination": os.path.normpath(destination)}) + "\n")

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
        """Processes categorization, namespacing adjustments, and moves files to target folders instantly."""
        global BPM_RANGES, DRUM_KEYWORDS, SYNTH_EXTS, NATIVE_EXTS
        
        try:
            if self.cancel_event.is_set():
                return
            f = str(f)
            f_lower = f.lower()
            root_lower = str(root).lower()
            
            # Extract the actual extension string from the tuple split
            ext_tuple = os.path.splitext(f_lower)
            ext = ext_tuple[1].strip() if len(ext_tuple) > 1 else ""
            
            s_path = os.path.normpath(os.path.join(root, f))
            target_dir = None
            stat_key = "Errors/Skipped Files"
            classification_reason = "unclassified"
            classification_confidence = 0.25
            if self.indexed_tags_cache_loaded:
                indexed_tags = self.indexed_tags_by_path.get(s_path, [])
            else:
                try:
                    indexed_tags = get_asset_tags(s_path)
                except sqlite3.Error:
                    indexed_tags = []
            tags = list(self.harvested_metadata.get(f_lower, [])) + indexed_tags
            routing_type, routing_folder = resolve_routing_tags(indexed_tags)
            force_loop = routing_type == "loop"
            force_one_shot = routing_type == "one-shot"
            
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
            if path_segments:
                top_level_folder = path_segments[0]
                if top_level_folder in ["percussion", "midi", "serum presets", "live instrument racks", "max for live devices"]:
                    is_already_sorted = True
                elif top_level_folder == "samples" and len(path_segments) > 1 and path_segments[1] in ["one-shots", "loops"]:
                    # The catch-all folder is re-checked so new and existing rules can still claim its files.
                    is_catch_all = len(path_segments) > 2 and path_segments[1] == "one-shots" and path_segments[2] == "other one-shots"
                    is_already_sorted = not is_catch_all

            if is_already_sorted:
                return

            # 1. KEYWORD GRID OVERRIDE PATTERN SCAN
            grid_matched_folder = None
            if not is_already_sorted and routing_folder and ext in AUDIO_EXTS:
                grid_matched_folder = routing_folder
                classification_reason = "routing_tag"
                classification_confidence = 0.98
            elif not is_already_sorted and not force_loop:
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
                if classification_reason == "unclassified":
                    classification_reason = "filename_rule"
                    classification_confidence = 0.95
                if "/" in grid_matched_folder or "\\" in grid_matched_folder:
                    target_dir = os.path.join(self.dest, *re.split(r'[/\\]', grid_matched_folder))
                else:
                    if ext in NATIVE_EXTS: 
                        target_dir = os.path.join(self.dest, NATIVE_EXTS.get(ext, "Live Instrument Racks"))
                    elif ext in SYNTH_EXTS: 
                        target_dir = os.path.join(self.dest, SYNTH_EXTS.get(ext, "Serum Presets"))
                    elif ext == '.mid' or ext == '.midi':
                        target_dir = os.path.join(self.dest, "Midi")
                    else: 
                        if grid_matched_folder.lower() in ["percussion", "shakers", "congas", "bongo"]:
                            target_dir = os.path.join(self.dest, "Percussion", "Shakers")
                        else:
                            target_dir = os.path.join(self.dest, "Samples", "One-Shots", grid_matched_folder)
                
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
                    if meta_drum_folder.lower() in ["percussion", "shakers"]:
                        target_dir = os.path.join(self.dest, "Percussion", "Shakers")
                    else:
                        target_dir = os.path.join(self.dest, "Samples", "One-Shots", meta_drum_folder)
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
                    target_dir = os.path.join(self.dest, SYNTH_EXTS.get(ext, "Serum Presets"))
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
                    
                    if force_loop or (not force_one_shot and (is_meta_loop or is_text_loop)):
                        classification_reason = "routing_tag" if force_loop else "loop_name_or_metadata"
                        classification_confidence = 0.98 if force_loop else 0.80
                        match = re.search(
                            r'(?<!\w)(\d{2,3})\s*bpm(?!\w)', f_normalized
                        )
                        if not match: match = re.search(r'(?<!\w)(\d{2,3})(?!\w)', f_lower)
                        
                        bpm_folder = "Unsorted Tempos"
                        if match:
                            try:
                                p_bpm = int(match.group(1))
                                if 40 <= p_bpm <= 250:
                                    for low, high, folder_name in BPM_RANGES:
                                        if low <= p_bpm <= high:
                                            bpm_folder = folder_name
                                            break
                            except ValueError: pass
                        
                        key_match = re.search(
                            r'(?<!\w)([a-gA-G][#b]?m(?:in)?|'
                            r'[a-gA-G][#b]?(?:maj)?|\d{1,2}[a-dB-D])(?!\w)',
                            f_normalized
                        )
                        musical_key = key_match.group(1).upper() if key_match else "No Key Info"
                        
                        target_dir = os.path.join(self.dest, "Samples", "Loops", bpm_folder, musical_key)
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
                    return

            target_dir = os.path.normpath(target_dir)
            if os.path.normpath(root) == target_dir:
                return
            tags = sorted(set(
                tags + derive_filename_tags(f) +
                [f"category:{os.path.basename(target_dir)}"]
            ))
            if self.preview_only:
                try:
                    with self.lock:
                        index_asset(s_path, target_dir, classification_reason,
                                    classification_confidence, tags)
                except (OSError, sqlite3.Error) as index_error:
                    self.window.after(0, lambda: self.update_status(
                        f"Asset index could not be updated: {index_error}"))
                with self.lock:
                    self.preview_records.append({
                        "source": os.path.normpath(s_path),
                        "filename": f,
                        "destination": target_dir,
                        "reason": classification_reason,
                        "confidence": classification_confidence,
                        "tags": tags
                    })
                    self.processed_files += 1
                return

            if self.cancel_event.is_set():
                return

            d_path = os.path.normpath(os.path.join(target_dir, f))
            
            if os.path.normpath(root) == target_dir: return

            os.makedirs(target_dir, exist_ok=True)
            try: os.chmod(s_path, stat.S_IWRITE)
            except Exception: pass
            
            if os.path.exists(d_path):
                s_crc = calculate_crc32(s_path)
                d_crc = calculate_crc32(d_path)
                if s_crc is not None and s_crc == d_crc:
                    self.increment_stat_safe("Skipped Duplicate Items")
                    if not self.copy_mode and not self.preview_only:
                        try: os.remove(s_path)
                        except Exception: pass
                    return
                else:
                    counter = 1
                    base_name, file_ext = os.path.splitext(f)
                    while os.path.exists(d_path):
                        d_path = os.path.normpath(os.path.join(target_dir, f"{base_name}_{counter}{file_ext}"))
                        counter += 1

            current_processed = self.processed_files + 1
            if current_processed % 25 == 0 or current_processed == self.total_files:
                self.window.after(0, lambda: self.update_status(f"Filing Asset ({current_processed}/{self.total_files}) -> {f}"))
            
            if not self.copy_mode and not self.preview_only:
                os.replace(s_path, d_path)
                self.log_move(s_path, d_path)
            else:
                shutil.copy2(s_path, d_path)
            try:
                with self.lock:
                    index_asset(
                        d_path, target_dir, classification_reason,
                        classification_confidence, tags,
                        previous_path=s_path if not self.copy_mode else None
                    )
            except (OSError, sqlite3.Error) as index_error:
                self.window.after(0, lambda: self.update_status(
                    f"Asset index could not be updated: {index_error}"))
            
            self.increment_stat_safe(stat_key)
        except Exception as error:
            operation = "preview" if self.preview_only else ("copy" if self.copy_mode else "move")
            self.record_operation_error(
                locals().get("s_path", os.path.join(root, str(f))),
                locals().get("d_path", locals().get("target_dir", "")),
                operation,
                error
            )
            self.increment_stat_safe("Errors/Skipped Files")
        finally:
            with self.lock: 
                self.processed_files += 1

# sorter_engine.py - Piece 7: Low-Level Data Validation & XML Tag Harvesters
    def nuclear_powershell_flatten(self, user_library_path):
        """Bypasses deep Windows directory ceilings by flattening nested items via PowerShell."""
        user_library_path = os.path.normpath(user_library_path)
        nested_target = os.path.join(user_library_path, "Presets", "Instruments", "Presets", "Instruments")
        target_root = os.path.join(user_library_path, "Live Instrument Racks")
        prune_target = os.path.join(user_library_path, "Presets", "Instruments", "Presets")
        
        if not os.path.exists(nested_target): return 0

        ps_script = f"""
        $NestedPath = '{nested_target}'
        $TargetRoot = '{target_root}'
        $PruneTarget = '{prune_target}'
        if (-not (Test-Path -LiteralPath $TargetRoot)) {{
            New-Item -ItemType Directory -Path $TargetRoot -Force | Out-Null
        }}
        if (Test-Path -LiteralPath $NestedPath) {{
            $Files = Get-ChildItem -LiteralPath $NestedPath -File -ErrorAction SilentlyContinue
            foreach ($File in $Files) {{
                Set-ItemProperty -LiteralPath $File.FullName -Name IsReadOnly -Value $false -ErrorAction SilentlyContinue
                Move-Item -LiteralPath $File.FullName -Destination $TargetRoot -Force -Confirm:$false
            }}
        }}
        if (Test-Path -LiteralPath $PruneTarget) {{
            Remove-Item -LiteralPath $PruneTarget -Recurse -Force -ErrorAction SilentlyContinue
        }}
        """
        try:
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            return len(os.listdir(target_root)) if os.path.exists(target_root) else 0
        except Exception: return 0

    def force_delete_empty_folders(self, target_path):
        """Class method wrapper hook that allows test runners to cleanly trigger 
        the structural folder scrub utility across targeted path strings.
        """
        return force_delete_empty_folders(target_path)


# ---------------------------------------------------------------------------------
# Low-Level Disk IO System Utilities (Sitting cleanly outside class scope)
# ---------------------------------------------------------------------------------

def calculate_crc32(filepath):
    """Calculates data checksums to prevent filing duplicate audio assets."""
    try:
        with open(filepath, 'rb') as f:
            crc = 0
            while chunk := f.read(65536):
                crc = zlib.crc32(chunk, crc)
            return crc & 0xFFFFFFFF
    except Exception: return None

def force_delete_empty_folders(root_dir):
    """Recursively sweeps and clears out dead paths from storage blocks."""
    count = 0
    for root, dirs, _ in os.walk(root_dir, topdown=False):
        for d in dirs:
            dir_path = os.path.join(root, d)
            try:
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

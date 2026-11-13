"""Builds an XO-friendly folder of sounds grouped by sound type, using hard links.

XO can filter its sample pool by folder name. Existing Samples/One-Shots
categories are preserved; uncategorized audio uses filename/folder keywords.
Files are flattened into one output folder per category.
Hard links mean no extra disk space; originals are never modified or moved.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import sorter_engine
import ableton_tags
import tag_evidence
from typing import NotRequired, TypedDict


class XoEvidence(TypedDict):
    path: str
    assignments: list[str]
    status: str
    sound_type: str | None
    is_loop: bool


class XoPlanStats(TypedDict):
    scanned: int
    unclassified: int
    loops_skipped: int
    manual_classified: NotRequired[int]
    manual_conflicts: NotRequired[int]
    evidence: NotRequired[list[XoEvidence]]

# Order matters: on a score tie, earlier types win.
SOUND_TYPES = {
    "Kicks": {"kick", "kicks", "bd", "bassdrum", "kik"},
    "Snares": {"snare", "snares", "sd", "rimshot"},
    "Claps": {"clap", "claps", "snap", "snaps"},
    "Hi-Hats": {"hihat", "hihats", "hat", "hats", "hh", "openhat", "closedhat"},
    "Cymbals": {"cymbal", "cymbals", "crash", "crashes", "ride", "splash"},
    "Toms": {"tom", "toms"},
    "Percussion": {
        "perc", "percs", "percussion", "shaker", "shakers", "tambourine", "tamb",
        "conga", "congas", "bongo", "bongos", "cowbell", "clave", "woodblock",
        "triangle", "rim", "timbale", "djembe", "taiko", "tabla", "donk", "gong",
        "cabasa", "maracas", "maraca", "dholak", "zarb", "framedrum", "talkingdrum",
        "drum", "drums", "toy", "toys", "guiro", "agogo", "bodhran", "darbuka", "udu",
        "cajon", "castanet", "castanets", "whistle", "tonalstrike", "strike",
    },
    "808 & Sub Bass": {"808", "808s", "sub", "subs", "subbass"},
    "Bass": {"bass", "basses", "reese", "wobble"},
    "Leads": {"lead", "leads", "arp", "arps", "arpeggio", "supersaw"},
    "Pads": {"pad", "pads", "drone", "drones"},
    "Keys & Piano": {
        "piano", "pianos", "keys", "key", "rhodes", "organ", "wurli", "wurlitzer",
        "clav", "harpsichord", "epiano",
    },
    "Guitar & Bass Guitar": {"guitar", "guitars", "strum", "banjo", "ukulele"},
    "Strings & Orchestral": {
        "string", "strings", "violin", "viola", "cello", "orchestra", "orchestral",
        "harp", "pizzicato", "ensemble",
    },
    "Brass & Winds": {
        "brass", "trumpet", "trombone", "horn", "horns", "sax", "saxophone",
        "flute", "clarinet", "oboe", "wind", "winds", "pan", "panflute",
    },
    "Bells & Mallets": {
        "bell", "bells", "chime", "chimes", "glock", "glockenspiel", "marimba",
        "xylophone", "vibraphone", "vibes", "kalimba", "mallet", "mallets",
        "celesta", "musicbox",
    },
    "Plucks & Synths": {"pluck", "plucks", "synth", "synths", "stab", "stabs", "chord", "chords"},
    "Vocals": {
        "vocal", "vocals", "vox", "voice", "voices", "choir", "chant", "chants",
        "acapella", "adlib", "adlibs", "shout", "whisper", "singer", "talk", "speech",
    },
    "Nature": {
        "nature", "rain", "thunder", "storm", "bird", "birds", "birdsong", "forest",
        "ocean", "sea", "waves", "wave", "water", "river", "stream", "waterfall",
        "fire", "wind", "jungle", "insects", "crickets", "frog", "frogs", "animal",
        "animals", "wildlife", "dog", "cat", "cicada", "swamp", "beach", "creek",
        "drip", "drips", "splash", "bubbles", "leaves", "snow", "campfire",
        "fireplace", "shower", "seagull", "owl", "wolf",
    },
    "Foley": {
        "foley", "footstep", "footsteps", "door", "doors", "cloth", "paper",
        "glass", "metal", "wood", "wooden", "rattle", "scrape", "scrapes", "click",
        "clicks", "crunch", "knock", "impact", "rubble", "gravel", "keys", "zipper",
        "typing", "keyboard", "machine", "mechanical", "tool", "tools", "pour",
        "coin", "coins", "car", "traffic", "engine", "phone", "bottle", "cup",
    },
    "Ambience & Textures": {
        "ambience", "ambient", "ambiance", "atmos", "atmosphere", "atmospheric",
        "texture", "textures", "soundscape", "cinematic", "dark", "space",
        "noise", "vinyl", "crackle", "tape", "hum", "room", "tone",
    },
    "FX & Transitions": {
        "fx", "sfx", "riser", "risers", "uplifter", "downlifter", "sweep", "sweeps",
        "whoosh", "swoosh", "transition", "transitions", "glitch", "glitches",
        "reverse", "rev", "laser", "zap", "boom", "hit", "hits", "stutter",
        "impacts", "drop", "build", "buildup", "siren", "alarm", "explosion",
    },
}

# Tokens too generic to decide a type on their own when a better match exists.
WEAK_TOKENS = {"hit", "hits", "key", "keys", "wave", "pan", "rim", "dark", "space",
               "drum", "drums", "strike", "car", "cup",
               "room", "tone", "wind", "sub", "tom", "pad", "click", "metal", "wood",
               "paper", "glass", "machine", "tool", "tools", "drop", "build", "talk",
               "texture", "textures"}

LOOP_TOKENS = {"loop", "loops", "lp"}
AUDIO_EXTS = {".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a", ".aac",
              ".opus", ".oga", ".caf", ".au", ".snd", ".wma"}

_TOKEN_TYPE = {}
_TYPE_ORDER = {}


def _raise_walk_error(error):
    raise error


def _inside(path, root):
    try:
        path = os.path.normcase(os.path.realpath(path))
        root = os.path.normcase(os.path.realpath(root))
        common = os.path.commonpath((path, root))
        return os.path.normcase(common) == os.path.normcase(root)
    except ValueError:
        return False


def _filesystem_device(path):
    path = os.path.abspath(path)
    while True:
        try:
            return os.stat(path).st_dev
        except (FileNotFoundError, NotADirectoryError):
            parent = os.path.dirname(path)
            if parent == path:
                raise
            path = parent


def same_filesystem(source, destination):
    """Checks filesystem identity, resolving a not-yet-created destination to its parent."""
    source_device = _filesystem_device(source)
    destination_device = _filesystem_device(destination)
    return source_device == destination_device


def _validated_type_folder(name):
    if (
        not isinstance(name, str) or not name or name in {".", ".."}
        or name != name.strip() or name.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name)
        or re.match(
            r"^(CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9]|LPT[1-9])(?:\.|$)",
            name, re.IGNORECASE
        )
    ):
        raise ValueError(f"Invalid XO filter folder name: {name!r}")
    return name


def _validate_custom_types(custom):
    if not isinstance(custom, dict):
        raise ValueError("XO custom folders must be an object.")
    built_in_names = {name.casefold(): name for name in SOUND_TYPES}
    seen_names = {}
    for name, words in custom.items():
        _validated_type_folder(name)
        if not isinstance(words, list) or any(not isinstance(word, str) for word in words):
            raise ValueError(f"XO custom folder {name!r} must contain a list of keywords.")
        folded = name.casefold()
        existing = built_in_names.get(folded) or seen_names.get(folded)
        if existing is not None and existing != name:
            raise ValueError(
                f"XO folder {name!r} differs only by letter case from {existing!r}."
            )
        seen_names[folded] = name
    return custom


def _load_profile():
    if not os.path.exists(sorter_engine.CONFIG_FILE):
        sorter_engine.XO_CONFIG_LOAD_ERROR = None
        return sorter_engine._default_config()
    try:
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = sorter_engine._validate_config(json.load(handle))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        message = (
            f"Configuration could not be loaded from "
            f"{sorter_engine.CONFIG_FILE}: {error}"
        )
        sorter_engine.XO_CONFIG_LOAD_ERROR = message
        raise ValueError(message) from error
    sorter_engine.XO_CONFIG_LOAD_ERROR = None
    return data


def load_custom_types():
    """Returns the user's {folder name: [keywords]} from the validated config file."""
    data = _load_profile()
    try:
        return _validate_custom_types(data.get("XO_CUSTOM_TYPES", {}))
    except (ValueError, TypeError) as error:
        sorter_engine.XO_CONFIG_LOAD_ERROR = (
            f"XO folder configuration in {sorter_engine.CONFIG_FILE} is invalid: {error}"
        )
        raise ValueError(sorter_engine.XO_CONFIG_LOAD_ERROR) from error


@sorter_engine.serialized_config
def save_custom_types(custom):
    """Persists custom types; a built-in name adds keywords to it, a new name creates a folder."""
    _validate_custom_types(custom)
    data = _load_profile()
    data["XO_CUSTOM_TYPES"] = custom
    sorter_engine._write_config(data)
    _rebuild_custom_types(custom)
    sorter_engine.XO_CONFIG_LOAD_ERROR = None


def parse_keywords(text):
    return sorted({w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 2})


def _all_types(custom):
    """Built-in types merged with custom keywords; custom-only types come first so they win ties."""
    custom = _validate_custom_types(custom)
    merged = {
        name: {word.casefold() for word in words}
        for name, words in custom.items() if name not in SOUND_TYPES
    }
    for name, words in SOUND_TYPES.items():
        merged[name] = set(words) | {word.casefold() for word in custom.get(name, ())}
    return merged


def all_types():
    """Returns built-in types merged with the validated user keywords."""
    return _all_types(load_custom_types())


def _rebuild_custom_types(custom):
    types = _all_types(custom)
    _TOKEN_TYPE.clear()
    for type_name, words in types.items():
        for word in words:
            _TOKEN_TYPE.setdefault(word, []).append(type_name)
    _TYPE_ORDER.clear()
    _TYPE_ORDER.update({name: i for i, name in enumerate(types)})


def apply_custom_types():
    """Rebuilds the token lookup tables only after the profile loads successfully."""
    _rebuild_custom_types(load_custom_types())


_rebuild_custom_types({})

_STOP_WORDS = {"loop", "loops", "bpm", "one", "shot", "oneshot", "dry", "wet", "with", "from", "and",
               "the", "vol", "pack", "kit", "sample", "samples", "audio", "wav", "demo", "free",
               "maj", "min", "minor", "major", "version", "bonus", "final"}


def suggest_types(library_root, min_files=25, should_cancel=None, include_loops=True, *, use_live_tags=False):
    """Finds words common in files no type recognizes; each could become its own folder.

    Words found in most unrecognized files are almost always a pack or brand name,
    so they are skipped. Returns [{word, count, example}] most common first.
    """
    counts, examples, loop_counts, total = {}, {}, {}, 0
    excluded = set()
    manual_loops = set()
    if use_live_tags:
        plan, stats = build_plan(
            library_root, include_loops=include_loops, should_cancel=should_cancel, use_live_tags=True
        )
        excluded.update(path for paths in plan.values() for path in paths)
        for item in stats.get("evidence", []):
            if item["is_loop"]:
                manual_loops.add(item["path"])
            if "excluded from build" in item["status"]:
                excluded.add(item["path"])
    for dirpath, dirnames, filenames in os.walk(library_root, onerror=_raise_walk_error):
        if should_cancel and should_cancel():
            break
        dirnames[:] = [d for d in dirnames if d not in sorter_engine.IGNORED_DIRECTORIES]
        for filename in filenames:
            if ableton_tags.is_metadata_stub(filename):
                continue
            if os.path.splitext(filename)[1].lower() not in AUDIO_EXTS:
                continue
            path = os.path.normpath(os.path.join(dirpath, filename))
            if path in excluded:
                continue
            sound_type, is_loop = classify(path, library_root)
            is_loop = is_loop or path in manual_loops
            if sound_type is not None or (is_loop and not include_loops):
                continue
            total += 1
            stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", os.path.splitext(filename)[0])
            for word in set(re.findall(r"[a-z]{4,}", stem.lower())):
                counts[word] = counts.get(word, 0) + 1
                if is_loop:
                    loop_counts[word] = loop_counts.get(word, 0) + 1
                examples.setdefault(word, filename)
    known = set(_TOKEN_TYPE) | _STOP_WORDS
    return [
        {"word": word, "count": count, "example": examples[word], "loops": loop_counts.get(word, 0)}
        for word, count in sorted(counts.items(), key=lambda item: -item[1])
        if count >= min_files and count <= total * 0.5 and word not in known
    ]


def _tokens(text):
    """Splits on punctuation and camelCase, and collapses adjacent words (hi hat -> hihat)."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = []
    for i, word in enumerate(words):
        out.append(word)
        if i + 1 < len(words):
            out.append(word + words[i + 1])
        if len(word) > 3 and word.endswith("s"):
            out.append(word[:-1])
    return out


def _score_tokens(tokens, weight, scores):
    for token in tokens:
        for sound_type in _TOKEN_TYPE.get(token, ()):
            points = weight * (0.4 if token in WEAK_TOKENS else 1.0)
            scores[sound_type] = scores.get(sound_type, 0.0) + points


def _organized_category(parts):
    if (
        len(parts) >= 4
        and parts[0].casefold() == "samples"
        and parts[1].casefold() == "one-shots"
        and parts[2].casefold() != "other one-shots"
    ):
        return _validated_type_folder(parts[2])
    return None


def classify(path, library_root):
    """Returns (sound_type or None, is_loop) for one file."""
    rel = os.path.relpath(path, library_root)
    parts = rel.split(os.sep)
    stem = os.path.splitext(parts[-1])[0]
    file_tokens = _tokens(stem)
    folder_tokens = []
    for part in parts[:-1]:
        folder_tokens.extend(_tokens(part))
    is_loop = bool(LOOP_TOKENS & set(file_tokens + folder_tokens))
    category = _organized_category(parts)
    if category is not None:
        return category, is_loop
    scores = {}
    _score_tokens(file_tokens, 2.0, scores)
    _score_tokens(folder_tokens, 1.0, scores)
    if not scores:
        return None, is_loop
    best = max(scores, key=lambda name: (scores[name], -_TYPE_ORDER[name]))
    return tag_evidence.TYPE_TO_FOLDER.get(best, best), is_loop


def build_plan(library_root, include_loops=False, selected_types=None, should_cancel=None, *, use_live_tags=False):
    """Walks the library and returns {sound_type: [source paths]} plus summary counts."""
    apply_custom_types()
    plan = {}
    stats: XoPlanStats = {"scanned": 0, "unclassified": 0, "loops_skipped": 0}
    paths = []
    for dirpath, dirnames, filenames in os.walk(library_root, onerror=_raise_walk_error):
        if should_cancel and should_cancel():
            break
        dirnames[:] = [d for d in dirnames if d not in sorter_engine.IGNORED_DIRECTORIES]
        for filename in filenames:
            if ableton_tags.is_metadata_stub(filename):
                continue
            if os.path.splitext(filename)[1].lower() not in AUDIO_EXTS:
                continue
            path = os.path.normpath(os.path.join(dirpath, filename))
            if os.path.islink(path):
                continue
            paths.append(path)
    manual = ableton_tags.read_sample_assignments(paths) if use_live_tags else {}
    if use_live_tags:
        stats.update({"manual_classified": 0, "manual_conflicts": 0, "evidence": []})
    for path in paths:
        if should_cancel and should_cancel():
            break
        stats["scanned"] += 1
        sound_type, is_loop = classify(path, library_root)
        if use_live_tags:
            evidence = tag_evidence.interpret_manual_tags(manual.get(os.path.normcase(os.path.abspath(path)), ()))
            is_loop = is_loop or evidence.is_loop
            if evidence.assignments or evidence.is_loop:
                if not evidence.one_shot_eligible:
                    status = "manual kit, multisample or impulse-response role; excluded from build"
                    sound_type = None
                elif not evidence.alternatives:
                    status = "manual role only; existing grouping retained"
                elif not evidence.sound_type:
                    stats["manual_conflicts"] += 1
                    status = "conflicting manual sound types; excluded from build"
                    sound_type = None
                else:
                    manual_type = tag_evidence.TYPE_TO_FOLDER[evidence.sound_type]
                    origin = (
                        "library category"
                        if _organized_category(os.path.relpath(path, library_root).split(os.sep))
                        else "keyword type"
                    )
                    status = "manual Live type" + (
                        f" overrides {origin} {sound_type}" if sound_type and sound_type != manual_type else ""
                    )
                    sound_type = manual_type
                    stats["manual_classified"] += 1
                stats["evidence"].append({
                    "path": path, "assignments": list(evidence.assignments),
                    "status": status, "sound_type": sound_type, "is_loop": is_loop
                })
        if sound_type is None:
            stats["unclassified"] += 1
            continue
        if is_loop and not include_loops:
            stats["loops_skipped"] += 1
            continue
        if selected_types is not None and sound_type not in selected_types:
            continue
        plan.setdefault(sound_type, []).append(path)
    return plan, stats


def _unique_name(dest_dir, source):
    name = os.path.basename(source)
    target = os.path.join(dest_dir, name)
    if not os.path.lexists(target):
        return target, False
    try:
        if os.path.samefile(source, target):
            return target, True
    except OSError:
        pass
    stem, ext = os.path.splitext(name)
    digest = hashlib.sha1(source.encode("utf-8", "ignore")).hexdigest()[:6]
    counter = 0
    while True:
        suffix = f"_{counter}" if counter else ""
        target = os.path.join(dest_dir, f"{stem}_{digest}{suffix}{ext}")
        if not os.path.lexists(target):
            return target, False
        try:
            if os.path.samefile(source, target):
                return target, True
        except OSError:
            pass
        counter += 1


_OUTPUT_MANIFEST = ".alm-xo-output.json"

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class _OutputFileBasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation", ctypes.c_longlong), ("access", ctypes.c_longlong),
            ("write", ctypes.c_longlong), ("change", ctypes.c_longlong),
            ("attributes", wintypes.DWORD),
        ]

    _output_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _output_kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    _output_kernel.CreateFileW.restype = wintypes.HANDLE
    _output_kernel.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
    )
    _output_kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _output_kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    _output_kernel.CloseHandle.restype = wintypes.BOOL


def _output_file_identity(path):
    info = path.stat()
    change_time = info.st_ctime_ns
    if os.name == "nt":
        # Windows st_ctime is creation time; use the filesystem's change clock for hash reuse.
        handle = _output_kernel.CreateFileW(str(path), 0x80, 7, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            basic = _OutputFileBasicInfo()
            if not _output_kernel.GetFileInformationByHandleEx(handle, 0, ctypes.byref(basic), ctypes.sizeof(basic)):
                raise ctypes.WinError(ctypes.get_last_error())
            change_time = basic.change
        finally:
            if not _output_kernel.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, change_time)


class BuildCancelled(Exception):
    """Cancellation before publication leaves existing output untouched."""


def _check_build_cancelled(should_cancel):
    if should_cancel and should_cancel():
        raise BuildCancelled()


def _output_digest(path, digest_cache, should_cancel, status, phase, count):
    info = path.stat()
    identity = _output_file_identity(path)
    if info.st_ino and identity in digest_cache:
        return digest_cache[identity]
    digest = hashlib.sha256()
    read_bytes = 0
    with path.open("rb") as stream:
        while True:
            _check_build_cancelled(should_cancel)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            read_bytes += len(chunk)
            if status:
                status(f"{phase}: {count:,} files · {path.name} "
                       f"({read_bytes / (1024 * 1024):,.1f} / {info.st_size / (1024 * 1024):,.1f} MB)")
    if identity != _output_file_identity(path):
        raise ValueError(f"XO file changed during verification: {path}")
    value = digest.hexdigest()
    if info.st_ino:
        digest_cache[identity] = value
    return value


def _output_snapshot(folder, *, digest_cache=None, should_cancel=None, status=None,
                     phase="Checking output", hash_contents=True):
    _unlinked_output_path(Path(folder))
    digest_cache = {} if digest_cache is None else digest_cache
    files, directories = {}, []
    for current, dirs, names in os.walk(folder, onerror=_raise_walk_error, followlinks=False):
        _check_build_cancelled(should_cancel)
        for index, name in enumerate(dirs + names, 1):
            _check_build_cancelled(should_cancel)
            if status and index % 100 == 0:
                status(f"{phase}: inspecting folder entries ({index:,})…")
            path = Path(current) / name
            info = path.lstat()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"Linked paths are not allowed in XO output: {path}")
        for name in dirs:
            directories.append((Path(current) / name).relative_to(folder).as_posix())
        for name in names:
            _check_build_cancelled(should_cancel)
            path = Path(current) / name
            if not path.is_file():
                raise ValueError(f"Unsupported XO output entry: {path}")
            count = len(files) + 1
            if status:
                status(f"{phase}: {count:,} files · {path.name}")
            if hash_contents:
                value = _output_digest(path, digest_cache, should_cancel, status, phase, count)
            else:
                info = path.stat()
                value = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            files[path.relative_to(folder).as_posix()] = value
    return {"files": files, "directories": sorted(directories)}


def _unlinked_output_path(path):
    for entry in (path, *path.parents):
        if entry.exists() or entry.is_symlink():
            info = entry.lstat()
            if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError(f"XO output cannot use a linked path: {entry}")


def review_output_destination(dest_root, library_root, *, digest_cache=None, should_cancel=None, status=None):
    """Validate output ownership and return the exact contents reviewed for replacement."""
    destination = Path(os.path.abspath(dest_root))
    library = Path(os.path.realpath(library_root))
    canonical_destination = Path(os.path.realpath(destination))
    home = Path(os.path.realpath(Path.home()))
    if canonical_destination == Path(canonical_destination.anchor) or canonical_destination in {
        home, *(home / name for name in ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"))
    }:
        raise ValueError("Choose a dedicated XO output subfolder, not a home or standard user folder.")
    _unlinked_output_path(destination)
    if _inside(destination, library) or _inside(library, destination):
        raise ValueError("The XO folder and User Library must not overlap.")
    if not destination.exists():
        return {"exists": False, "managed": False, "snapshot": None}
    if not destination.is_dir():
        raise ValueError("The XO destination must be a folder.")
    if status:
        status("Checking previous output…")
    snapshot = _output_snapshot(
        destination, digest_cache=digest_cache, should_cancel=should_cancel,
        status=status, phase="Checking previous output",
    )
    manifest = destination / _OUTPUT_MANIFEST
    managed = manifest.exists()
    if managed:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        contents = {
            "files": {name: digest for name, digest in snapshot["files"].items() if name != _OUTPUT_MANIFEST},
            "directories": snapshot["directories"],
        }
        if not isinstance(data, dict) or data.get("schema") != 1 or data.get("contents") != contents:
            raise ValueError("The managed XO folder was changed outside the builder. Preserve those changes "
                             "and choose a new destination before rebuilding.")
    info = destination.stat()
    return {
        "exists": True, "managed": managed, "snapshot": snapshot,
        "identity": [info.st_dev, info.st_ino],
    }


def _remove_output_snapshot(folder, snapshot, *, digest_cache=None, status=None, hash_contents=True):
    if _output_snapshot(
        folder, digest_cache=digest_cache, status=status, phase="Checking old-output cleanup",
        hash_contents=hash_contents,
    ) != snapshot:
        raise ValueError(f"XO output changed during cleanup; retained at {folder}")
    for count, name in enumerate(snapshot["files"], 1):
        if status:
            status(f"Removing previous output: {count:,} / {len(snapshot['files']):,} files")
        (folder / name).unlink()
    for name in sorted(snapshot["directories"], key=lambda value: value.count("/"), reverse=True):
        (folder / name).rmdir()
    folder.rmdir()


def rebuild_folder(plan, dest_root, library_root, progress=None, should_cancel=None, *,
                   reviewed_destination=None, adopt_existing=False, status=None,
                   digest_cache=None):
    """Publish a complete managed replacement; keep existing output on failure/cancellation."""
    destination = Path(os.path.abspath(dest_root))
    digest_cache = {} if digest_cache is None else digest_cache
    reviewed = review_output_destination(
        destination, library_root, digest_cache=digest_cache, should_cancel=should_cancel, status=status,
    )
    if reviewed_destination is not None and reviewed != reviewed_destination:
        raise ValueError("XO output changed after confirmation. Review the destination again.")
    nonempty = reviewed["exists"] and bool(
        reviewed["snapshot"]["files"] or reviewed["snapshot"]["directories"]
    )
    if nonempty and not reviewed["managed"] and not adopt_existing:
        raise ValueError("Existing XO output is not app-managed. Confirm adoption before replacing it.")
    if status:
        status("Checking source files…")
    for sources in plan.values():
        for source in sources:
            _check_build_cancelled(should_cancel)
            path = Path(os.path.abspath(source))
            _unlinked_output_path(path)
            if not path.is_file() or not _inside(path, os.path.realpath(library_root)):
                raise ValueError(f"XO source must be a file inside the User Library: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".alm-xo-build-", dir=destination.parent))
    backup = None
    published = False
    try:
        if status:
            status("Creating replacement links/copies…")
        result = build_folder(plan, staging, library_root, progress, should_cancel)
        result.update(published=False, retained_backup=None)
        if result["failed"] or result["cancelled"] or (should_cancel and should_cancel()):
            result["cancelled"] = result["cancelled"] or bool(should_cancel and should_cancel())
            return result
        contents = _output_snapshot(
            staging, digest_cache=digest_cache, should_cancel=should_cancel,
            status=status, phase="Verifying replacement",
        )
        (staging / _OUTPUT_MANIFEST).write_text(
            json.dumps({"schema": 1, "contents": contents}, indent=2) + "\n", encoding="utf-8",
        )
        if review_output_destination(
            destination, library_root, digest_cache=digest_cache, should_cancel=should_cancel, status=status,
        ) != reviewed:
            raise ValueError("XO output changed while building. Existing output was not replaced.")
        if should_cancel and should_cancel():
            result["cancelled"] = True
            return result
        if status:
            status("Switching to the verified replacement…")
        if reviewed["exists"]:
            backup = destination.with_name(destination.name + ".previous-" + uuid.uuid4().hex)
            destination.rename(backup)
        try:
            staging.rename(destination)
        except OSError as error:
            if backup is not None:
                try:
                    backup.rename(destination)
                except OSError as rollback_error:
                    raise OSError(f"Could not publish XO output ({error}); rollback failed "
                                  f"({rollback_error}). Previous output remains at {backup}.") from error
            raise
        published = True
        result["published"] = True
        if backup is not None:
            if nonempty and not reviewed["managed"]:
                result["retained_backup"] = str(backup)
            else:
                try:
                    _remove_output_snapshot(backup, reviewed["snapshot"], digest_cache=digest_cache, status=status)
                except (OSError, ValueError) as error:
                    raise OSError(f"New XO output is ready, but previous-output cleanup failed: "
                                  f"{error}. Review {backup}.") from error
        return result
    except BuildCancelled:
        return {
            "linked": 0, "copied": 0, "existing": 0, "failed": 0, "cancelled": True,
            "errors": [], "published": False, "retained_backup": None,
        }
    finally:
        if not published and staging.exists():
            if status:
                status("Discarding incomplete replacement; previous output is unchanged…")
            _remove_output_snapshot(
                staging, _output_snapshot(staging, hash_contents=False), hash_contents=False,
            )


def build_folder(plan, dest_root, library_root, progress=None, should_cancel=None):
    """Hard-links (or copies, across filesystems) each file into dest_root/<type>/."""
    dest_root = os.path.realpath(os.path.abspath(dest_root))
    library_root = os.path.realpath(os.path.abspath(library_root))
    if _inside(dest_root, library_root) or _inside(library_root, dest_root):
        raise ValueError("The XO folder and User Library must not overlap.")
    result = {
        "linked": 0, "copied": 0, "existing": 0, "failed": 0,
        "cancelled": False, "errors": [],
    }
    total = sum(len(files) for files in plan.values())
    done = 0
    for sound_type, files in plan.items():
        sound_type = _validated_type_folder(sound_type)
        dest_dir = os.path.join(dest_root, sound_type)
        resolved_dest_dir = os.path.realpath(dest_dir)
        if not _inside(resolved_dest_dir, dest_root):
            raise ValueError(f"XO filter folder escapes its destination: {sound_type!r}")
        os.makedirs(dest_dir, exist_ok=True)
        if not _inside(os.path.realpath(dest_dir), dest_root):
            raise ValueError(f"XO filter folder escapes its destination: {sound_type!r}")
        for source in files:
            if should_cancel and should_cancel():
                result["cancelled"] = True
                return result
            done += 1
            if progress:
                progress(done, total)
            target, exists = _unique_name(dest_dir, source)
            if exists:
                result["existing"] += 1
                continue
            try:
                can_link = same_filesystem(source, dest_dir)
            except OSError as error:
                result["failed"] += 1
                result["errors"].append({
                    "source": source,
                    "destination": target,
                    "error": str(error),
                })
                continue
            while True:
                if can_link:
                    try:
                        os.link(source, target)
                        result["linked"] += 1
                        break
                    except FileExistsError:
                        target, exists = _unique_name(dest_dir, source)
                        if exists:
                            result["existing"] += 1
                            break
                    except OSError:
                        can_link = False
                if not can_link:
                    try:
                        with open(source, "rb") as incoming:
                            with open(target, "xb") as outgoing:
                                try:
                                    shutil.copyfileobj(incoming, outgoing)
                                    outgoing.flush()
                                    shutil.copystat(source, target)
                                except OSError:
                                    outgoing.close()
                                    os.remove(target)
                                    raise
                        result["copied"] += 1
                        break
                    except FileExistsError:
                        target, exists = _unique_name(dest_dir, source)
                        if exists:
                            result["existing"] += 1
                            break
                    except OSError as error:
                        result["failed"] += 1
                        result["errors"].append({
                            "source": source,
                            "destination": target,
                            "error": str(error),
                        })
                        break
    if progress:
        progress(total, total)
    return result

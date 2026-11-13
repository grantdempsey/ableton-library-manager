"""Serum type/pack routing without rewriting presets or dependent resources."""

from collections.abc import Iterable
import json
import os
import re
import struct
from pathlib import Path


PRESET_EXTENSIONS = {".fxp", ".serumpreset"}
USER_FOLDER = "Serum 2 Presets/Presets/User"
_PREFIX_CATEGORIES = {
    "808": "Bass",
    "ARP": "Arp",
    "BASS": "Bass",
    "BS": "Bass",
    "CH": "Chord",
    "CHORD": "Chord",
    "DRUM": "Drums",
    "DRUMS": "Drums",
    "FX": "FX",
    "SFX": "FX",
    "INSTRUMENT": "Instrument",
    "KEY": "Keys",
    "KEYS": "Keys",
    "KEYBOARD": "Keys",
    "PIANO": "Keys",
    "LD": "Lead",
    "LEAD": "Lead",
    "PAD": "Pad",
    "PD": "Pad",
    "PL": "Pluck",
    "PLUCK": "Pluck",
    "SEQ": "Sequence",
    "SEQUENCE": "Sequence",
    "SEQUENCES": "Sequence",
    "SYN": "Synth",
    "SYNTH": "Synth",
    "NEUROBASS": "Bass",
    "SUBBASS": "Bass",
    "REESE": "Bass",
    "WUB": "Bass",
    "WUBS": "Bass",
    "LEADS": "Lead",
    "PADS": "Pad",
    "PLUCKED": "Pluck",
    "PLUCKS": "Pluck",
    "CHORDS": "Chord",
}
_CONTAINER_FOLDERS = {
    "user", "presets", "serum presets", "serum 2 presets", "synth presets",
    "incoming", "input", "library", "user library", "unsorted", "loose presets",
}
_MAX_METADATA_BYTES = 1024 * 1024


def _types(labels: Iterable[str]) -> set[str]:
    return {_PREFIX_CATEGORIES[label.strip().upper()] for label in labels
            if label.strip().upper() in _PREFIX_CATEGORIES}


def category(filename: str, *, tags: Iterable[str] = (), folders: Iterable[str] = ()) -> str:
    for labels in (tags, folders):
        matches = _types(labels)
        if matches:
            return next(iter(matches)) if len(matches) == 1 else "Unsorted"
    match = re.match(r"^([A-Za-z0-9]+)(?:[\s_-]+)", Path(filename).stem)
    if match and match[1].upper() in _PREFIX_CATEGORIES:
        return _PREFIX_CATEGORIES[match[1].upper()]
    matches = _types(re.findall(r"[A-Za-z0-9]+", Path(filename).stem))
    return next(iter(matches)) if len(matches) == 1 else "Unsorted"


def preset_tags(source: str) -> list[str]:
    if Path(source).suffix.lower() != ".serumpreset":
        return []
    with open(source, "rb") as handle:
        prefix = handle.read(17)
        if not prefix.startswith(b"XferJson\0"):
            return []
        if len(prefix) != 17:
            raise ValueError(f"Incomplete Serum metadata header: {source}")
        size = struct.unpack_from("<I", prefix, 9)[0]
        if not 0 < size <= _MAX_METADATA_BYTES:
            raise ValueError(f"Invalid Serum metadata length: {source}")
        contents = handle.read(size)
    if len(contents) != size:
        raise ValueError(f"Incomplete Serum metadata: {source}")
    try:
        metadata = json.loads(contents)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Invalid Serum metadata: {source}") from error
    if not isinstance(metadata, dict) or not isinstance(metadata.get("tags", []), list):
        raise ValueError(f"Invalid Serum metadata tags: {source}")
    tags = metadata.get("tags", [])
    if any(not isinstance(tag, str) for tag in tags):
        raise ValueError(f"Invalid Serum metadata tags: {source}")
    return tags


def user_relative_path(source: str) -> Path | None:
    path = Path(os.path.abspath(source))
    parts = path.parts
    for index in range(len(parts) - 3):
        if tuple(part.casefold() for part in parts[index:index + 3]) == (
            "serum 2 presets", "presets", "user",
        ):
            return Path(*parts[index + 3:])
    return None


def _folders(source: str | None, source_root: str | None) -> list[str]:
    if source is None:
        return []
    relative = user_relative_path(source)
    if relative is not None:
        return list(relative.parent.parts)
    if source_root is None:
        return []
    root = Path(os.path.abspath(source_root))
    relative = Path(os.path.abspath(source)).relative_to(root)
    return [root.name, *relative.parent.parts]


def _pack(filename: str, folders: Iterable[str]) -> list[str]:
    parts = [folder for folder in folders if folder.casefold() not in _CONTAINER_FOLDERS
             and not _types((folder,))]
    if parts:
        return parts
    match = re.match(r"^([A-Z][A-Z0-9]{2,15})(?:[\s_-]+)", Path(filename).stem)
    if match and not _types((match[1],)):
        return [match[1]]
    return ["Loose Presets"]


def is_user_folder(folder: str) -> bool:
    return folder.replace("\\", "/").strip("/").casefold() == USER_FOLDER.casefold()


def destination(filename: str, configured_folder: str, *, source: str | None = None,
                source_root: str | None = None) -> str:
    if Path(filename).suffix.lower() in PRESET_EXTENSIONS and is_user_folder(configured_folder):
        folders = _folders(source, source_root)
        tags = preset_tags(source) if source is not None else []
        return "/".join((USER_FOLDER, category(filename, tags=tags, folders=folders),
                         *_pack(filename, folders)))
    return configured_folder


def is_resource_path(path: str) -> bool:
    return any(part.casefold() == "serum 2 presets" for part in Path(os.path.abspath(path)).parts)


def is_resource_root(path: str) -> bool:
    root = Path(path)
    return root.name.casefold() == "serum 2 presets" or all(
        (root / name).is_dir() for name in ("Presets", "Tables", "Samples")
    )

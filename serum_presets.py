"""Conservative Serum preset routing; never infer a category from sound-name words."""

import os
import re
from pathlib import Path


PRESET_EXTENSIONS = {".fxp", ".serumpreset"}
USER_FOLDER = "Serum 2 Presets/Presets/User"
_PREFIX_CATEGORIES = {
    "808": "Bass/808",
    "ARP": "Arp",
    "BASS": "Bass",
    "BS": "Bass",
    "CH": "Chord",
    "CHORD": "Chord",
    "DRUM": "Drum",
    "FX": "SFX",
    "INSTRUMENT": "Instrument",
    "KEYS": "Keyboard",
    "LD": "Lead",
    "LEAD": "Lead",
    "PAD": "Pad",
    "PD": "Pad",
    "PL": "Pluck",
    "PLUCK": "Pluck",
    "SEQ": "Seq",
    "SYN": "Synth",
}


def category(filename: str) -> str:
    match = re.match(r"^([A-Za-z0-9]+)(?:[\s_-]+)", Path(filename).stem)
    return _PREFIX_CATEGORIES.get(match[1].upper(), "Unsorted") if match else "Unsorted"


def is_user_folder(folder: str) -> bool:
    return folder.replace("\\", "/").strip("/").casefold() == USER_FOLDER.casefold()


def destination(filename: str, configured_folder: str) -> str:
    if Path(filename).suffix.lower() in PRESET_EXTENSIONS and is_user_folder(configured_folder):
        return USER_FOLDER + "/" + category(filename)
    return configured_folder


def is_resource_path(path: str) -> bool:
    return any(part.casefold() == "serum 2 presets" for part in Path(os.path.abspath(path)).parts)


def is_resource_root(path: str) -> bool:
    root = Path(path)
    return root.name.casefold() == "serum 2 presets" or all(
        (root / name).is_dir() for name in ("Presets", "Tables", "Samples")
    )

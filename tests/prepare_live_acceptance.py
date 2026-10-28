"""Prepare and verify disposable Live acceptance content; never launch Live."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import struct
import sys
import tempfile
import wave


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ("release_kick.wav", "untouched_neighbor.wav")
TAGS = {
    "baseline": [],
    "add": ["Genres|ALM Release Test"],
    "rename": ["Character|ALM Round Trip"],
    "remove": [],
}


def prepare(parent):
    parent = Path(parent).resolve(strict=True)
    fixture = Path(tempfile.mkdtemp(prefix="alm-live-acceptance-", dir=parent))
    library = fixture / "Test Library"
    library.mkdir()
    hashes = {}
    for name, frequency in zip(SAMPLES, (110, 220)):
        sample = library / name
        frames = b"".join(
            struct.pack("<h", round(3000 * math.sin(2 * math.pi * frequency * i / 44100)))
            for i in range(11025)
        )
        with wave.open(str(sample), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(frames)
        hashes[name] = hashlib.sha256(sample.read_bytes()).hexdigest()
    (fixture / "fixture.json").write_text(
        json.dumps({"fixture": "alm-live-acceptance-v1", "audio_sha256": hashes}, indent=2),
        encoding="utf-8",
    )
    (fixture / "runtime").mkdir()
    return fixture


def load_fixture(path):
    fixture = Path(path).resolve(strict=True)
    data = json.loads((fixture / "fixture.json").read_text(encoding="utf-8"))
    if data.get("fixture") != "alm-live-acceptance-v1" or set(data.get("audio_sha256", {})) != set(SAMPLES):
        raise ValueError("Not a recognized disposable acceptance fixture.")
    for name in SAMPLES:
        sample = fixture / "Test Library" / name
        if sample.is_symlink() or hashlib.sha256(sample.read_bytes()).hexdigest() != data["audio_sha256"][name]:
            raise ValueError(f"Audio bytes changed or linked sample found: {sample}")
    return fixture


def verify(path, stage):
    fixture = load_fixture(path)
    sys.path.insert(0, str(ROOT))
    import ableton_tags
    assignments = {
        name: ableton_tags.sample_tags(str(fixture / "Test Library" / name))
        for name in SAMPLES
    }
    expected = {SAMPLES[0]: TAGS[stage], SAMPLES[1]: []}
    if assignments != expected:
        raise ValueError(f"Assignments differ: expected {expected}; found {assignments}")
    return {"stage": stage, "audio_bytes": "unchanged", "assignments": assignments}


def launch(path):
    fixture = load_fixture(path)
    sys.path.insert(0, str(ROOT))
    os.chdir(fixture / "runtime")
    import gui_theme
    library = str(fixture / "Test Library")
    gui_theme.USER_LIBRARY_PATH = library
    gui_theme.resolve_user_library_path = lambda: library
    gui_theme.OPTIONS_PATH = str(fixture / "runtime" / "Options.txt")
    import live_catalog
    live_catalog.available_databases = lambda: ()
    import sorter_engine
    sorter_engine.CONFIG_FILE = str(fixture / "runtime" / "library_config.json")
    sorter_engine.ASSET_INDEX_FILE = str(fixture / "runtime" / "library_assets.db")
    runpy.run_path(str(ROOT / "AbletonLibraryManager.pyw"), run_name="__main__")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("prepare")
    create.add_argument("parent", type=Path)
    check = commands.add_parser("verify")
    check.add_argument("fixture", type=Path)
    check.add_argument("stage", choices=TAGS)
    start = commands.add_parser("launch")
    start.add_argument("fixture", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.parent))
    elif args.command == "verify":
        print(json.dumps(verify(args.fixture, args.stage), indent=2))
    else:
        launch(args.fixture)


if __name__ == "__main__":
    main()

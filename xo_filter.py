"""Builds an XO-friendly folder of sounds grouped by sound type, using hard links.

XO can filter its sample pool by folder name. This module classifies each audio
file into a sound type (Kicks, Nature, Vocals, ...) from its filename, its
folders and any personal tags, then mirrors the files into one folder per type.
Hard links mean no extra disk space; originals are never modified or moved.
"""
import hashlib
import json
import os
import re
import shutil

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


def load_custom_types():
    """Returns the user's {folder name: [keywords]} from the config file."""
    try:
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle).get("XO_CUSTOM_TYPES", {})
    except (OSError, ValueError):
        return {}
    return {str(name): [str(w) for w in words] for name, words in raw.items() if isinstance(words, list)}


@sorter_engine.serialized_config
def save_custom_types(custom):
    """Persists custom types; a built-in name adds keywords to it, a new name creates a folder."""
    data = {}
    if os.path.exists(sorter_engine.CONFIG_FILE):
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    data["XO_CUSTOM_TYPES"] = custom
    sorter_engine._write_config(data)
    apply_custom_types()


def parse_keywords(text):
    return sorted({w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 2})


def all_types():
    """Built-in types merged with custom keywords; custom-only types come first so they win ties."""
    custom = load_custom_types()
    merged = {name: set(words) for name, words in custom.items() if name not in SOUND_TYPES}
    for name, words in SOUND_TYPES.items():
        merged[name] = set(words) | set(custom.get(name, ()))
    return merged


def apply_custom_types():
    """Rebuilds the token lookup tables from built-in and custom types."""
    types = all_types()
    _TOKEN_TYPE.clear()
    for type_name, words in types.items():
        for word in words:
            _TOKEN_TYPE.setdefault(word, []).append(type_name)
    _TYPE_ORDER.clear()
    _TYPE_ORDER.update({name: i for i, name in enumerate(types)})


apply_custom_types()

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
    for dirpath, dirnames, filenames in os.walk(library_root):
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


def classify(path, library_root, personal_tags=()):
    """Returns (sound_type or None, is_loop) for one file."""
    rel = os.path.relpath(path, library_root)
    parts = rel.split(os.sep)
    stem = os.path.splitext(parts[-1])[0]
    file_tokens = _tokens(stem)
    folder_tokens = []
    for part in parts[:-1]:
        folder_tokens.extend(_tokens(part))
    tag_tokens = []
    for tag in personal_tags:
        if tag.startswith(("ableton:", "category:", "name:")):
            continue
        tag_tokens.extend(_tokens(tag.split(":")[-1]))

    scores = {}
    _score_tokens(file_tokens, 2.0, scores)
    _score_tokens(tag_tokens, 3.0, scores)
    _score_tokens(folder_tokens, 1.0, scores)
    is_loop = bool(LOOP_TOKENS & set(file_tokens + folder_tokens))
    if not scores:
        return None, is_loop
    best = max(scores, key=lambda name: (scores[name], -_TYPE_ORDER[name]))
    return best, is_loop


def _personal_tags_by_path(library_root):
    """Loads user-added tags from the index so custom tags can steer the folders."""
    tags = {}
    index_file = sorter_engine.ASSET_INDEX_FILE
    if not os.path.exists(index_file):
        return tags
    import sqlite3
    root = os.path.normpath(library_root).lower() + os.sep
    connection = sqlite3.connect(index_file)
    try:
        rows = connection.execute(
            "SELECT asset_path, tag FROM asset_tags WHERE enabled != 0 "
            "AND tag NOT LIKE 'category:%' AND tag NOT LIKE 'name:%'"
        ).fetchall()
    finally:
        connection.close()
    for path, tag in rows:
        if os.path.normpath(path).lower().startswith(root):
            tags.setdefault(os.path.normpath(path), []).append(tag)
    return tags


def build_plan(library_root, include_loops=False, selected_types=None, should_cancel=None, *, use_live_tags=False):
    """Walks the library and returns {sound_type: [source paths]} plus summary counts."""
    apply_custom_types()
    personal = _personal_tags_by_path(library_root)
    plan = {}
    stats: XoPlanStats = {"scanned": 0, "unclassified": 0, "loops_skipped": 0}
    paths = []
    for dirpath, dirnames, filenames in os.walk(library_root):
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
        sound_type, is_loop = classify(path, library_root, personal.get(path, ()))
        if use_live_tags:
            evidence = tag_evidence.interpret_manual_tags(manual.get(os.path.normcase(os.path.abspath(path)), ()))
            is_loop = is_loop or evidence.is_loop
            routing_type, routing_folder = sorter_engine.resolve_routing_tags(personal.get(path, ()))
            if routing_type == "one-shot":
                is_loop = False
            elif routing_type == "loop":
                is_loop = True
            if evidence.assignments or evidence.is_loop:
                if routing_type or routing_folder:
                    status = "local routing override present; Live type not adopted"
                elif not evidence.one_shot_eligible:
                    status = "manual kit, multisample or impulse-response role; excluded from build"
                    sound_type = None
                elif not evidence.alternatives:
                    status = "manual role only; keyword grouping retained"
                elif not evidence.sound_type:
                    stats["manual_conflicts"] += 1
                    status = "conflicting manual sound types; excluded from build"
                    sound_type = None
                else:
                    status = "manual Live type" + (
                        f" overrides keyword type {sound_type}" if sound_type and sound_type != evidence.sound_type else ""
                    )
                    sound_type = evidence.sound_type
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


def build_folder(plan, dest_root, library_root, progress=None, should_cancel=None):
    """Hard-links (or copies, across drives) each planned file into dest_root/<type>/."""
    dest_root = os.path.normpath(dest_root)
    if os.path.normpath(library_root).lower() in (dest_root.lower(), ):
        raise ValueError("The XO folder cannot be the library itself.")
    result = {"linked": 0, "copied": 0, "existing": 0, "failed": 0, "cancelled": False}
    total = sum(len(files) for files in plan.values())
    done = 0
    for sound_type, files in plan.items():
        dest_dir = os.path.join(dest_root, sound_type)
        os.makedirs(dest_dir, exist_ok=True)
        for source in files:
            if should_cancel and should_cancel():
                result["cancelled"] = True
                return result
            done += 1
            if progress and done % 200 == 0:
                progress(done, total)
            target, exists = _unique_name(dest_dir, source)
            if exists:
                result["existing"] += 1
                continue
            while True:
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
                    except OSError:
                        result["failed"] += 1
                        break
    if progress:
        progress(total, total)
    return result

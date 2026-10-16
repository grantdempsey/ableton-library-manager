"""Suggests new sorting rules by mining files the current rules left in the catch-all folder.

For each filename word that reliably points to one sound type (as judged by the shared
xo_filter vocabulary), a pending rule candidate is created. Candidates go through the
normal review list on the Rules tab; nothing changes until the user approves one.
"""
import json
import os
import re
from collections import Counter, defaultdict

import sorter_engine
import xo_filter

CATCH_ALL_FOLDER = "other one-shots"

# Sound type -> folder name. Existing folders are reused; the rest are proposed as new folders.
TYPE_TO_FOLDER = {
    "Kicks": "Kicks",
    "Snares": "Snares",
    "Claps": "Claps",
    "Hi-Hats": "Hi-Hats",
    "Cymbals": "Cymbals & Crashes",
    "Toms": "Toms",
    "Percussion": "Percussion",
    "808 & Sub Bass": "808 Sub Bass",
    "Bass": "Synth Bass One-Shots",
    "Leads": "Melodic & Synth One-Shots",
    "Pads": "Melodic & Synth One-Shots",
    "Plucks & Synths": "Melodic & Synth One-Shots",
    "Vocals": "Vocals & Chants",
    "FX & Transitions": "Sound FX",
    "Ambience & Textures": "Cinematic & Ambience",
    "Nature": "Nature",
    "Foley": "Foley",
    "Keys & Piano": "Keys & Piano",
    "Guitar & Bass Guitar": "Guitar",
    "Strings & Orchestral": "Strings & Orchestral",
    "Brass & Winds": "Brass & Winds",
    "Bells & Mallets": "Bells & Mallets",
}

# Words that appear in many unrelated names, so they make poor rules.
SKIP_TOKENS = xo_filter.WEAK_TOKENS | {"one", "shot", "oneshot", "dry", "wet", "short", "long", "high", "low"}


def _in_catch_all(path):
    return CATCH_ALL_FOLDER in {part.lower() for part in path.split(os.sep)}


def suggest_rules(library_root, min_files=5, min_share=0.9, should_cancel=None):
    """Returns suggestions sorted by evidence: [{token, target, count, examples, is_new_folder}]."""
    stem_tokens = []
    for dirpath, dirnames, filenames in os.walk(library_root):
        if should_cancel and should_cancel():
            break
        dirnames[:] = [d for d in dirnames if d not in sorter_engine.IGNORED_DIRECTORIES]
        for filename in filenames:
            if os.path.splitext(filename)[1].lower() not in xo_filter.AUDIO_EXTS:
                continue
            path = os.path.join(dirpath, filename)
            if not _in_catch_all(os.path.relpath(path, library_root)):
                continue
            stem = os.path.splitext(filename)[0]
            if sorter_engine.explain_filename(filename)["winner"]:
                continue
            sound_type, _ = xo_filter.classify(os.path.join(library_root, filename), library_root)
            if sound_type is None:
                continue
            words = {w for w in re.findall(r"[a-z]+", re.sub(r"[_#\-]", " ", stem.lower())) if len(w) >= 3}
            stem_tokens.append((filename, sound_type, words))

    word_files = defaultdict(int)
    word_types = defaultdict(Counter)
    examples = defaultdict(list)
    for filename, sound_type, words in stem_tokens:
        for word in words:
            word_files[word] += 1
            word_types[word][sound_type] += 1
            if len(examples[word]) < 3:
                examples[word].append(filename)

    existing_patterns = set(sorter_engine.DRUM_KEYWORDS)
    existing_folders = set(sorter_engine.DRUM_KEYWORDS.values())
    suggestions = []
    for word, total in word_files.items():
        if total < min_files or word in SKIP_TOKENS or word not in xo_filter._TOKEN_TYPE:
            continue
        sound_type, hits = word_types[word].most_common(1)[0]
        if hits / total < min_share or sound_type not in xo_filter._TOKEN_TYPE.get(word, ()):
            continue
        target = TYPE_TO_FOLDER.get(sound_type)
        if not target:
            continue
        pattern = sorter_engine.build_learned_rule_pattern(word)
        if pattern in existing_patterns or any(re.search(p, word) for p in existing_patterns):
            continue
        suggestions.append({
            "token": word, "target": target, "count": hits, "pattern": pattern,
            "examples": examples[word], "is_new_folder": target not in existing_folders,
        })
    suggestions.sort(key=lambda s: -s["count"])
    return suggestions


def add_suggestions_as_candidates(suggestions):
    """Stores suggestions as pending candidates, skipping anything already reviewed or pending."""
    data = {}
    if os.path.exists(sorter_engine.CONFIG_FILE):
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    candidates = data.setdefault("LEARNED_RULE_CANDIDATES", [])
    # Approved candidates whose rule was later deleted can be suggested again.
    live_rules = set(data.get("DRUM_KEYWORDS", sorter_engine.DRUM_KEYWORDS))
    before = len(candidates)
    candidates[:] = [
        c for c in candidates
        if not (c.get("status") == "approved" and c.get("pattern") not in live_rules)
    ]
    removed_stale = len(candidates) != before
    known = {(c.get("token"), c.get("target")) for c in candidates}
    added = 0
    for suggestion in suggestions:
        key = (suggestion["token"], suggestion["target"])
        if key in known:
            continue
        candidates.append({
            "token": suggestion["token"], "target": suggestion["target"],
            "count": suggestion["count"], "pattern": suggestion["pattern"],
            "status": "pending",
        })
        known.add(key)
        added += 1
    if added or removed_stale:
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
    return added

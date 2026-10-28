"""Suggests new sorting rules by mining files the current rules left in the catch-all folder.

For each filename word that reliably points to one sound type (from manual Live tags
or the shared XO vocabulary), a pending rule candidate is created. Candidates go through the
normal review list on the Rules tab; nothing changes until the user approves one.
"""
import json
import os
import re
from collections import Counter, defaultdict

import sorter_engine
import xo_filter
import ableton_tags
import tag_evidence

CATCH_ALL_FOLDER = "other one-shots"

# Sound type -> folder name. Existing folders are reused; the rest are proposed as new folders.
TYPE_TO_FOLDER = tag_evidence.TYPE_TO_FOLDER

# Words that appear in many unrelated names, so they make poor rules.
SKIP_TOKENS = xo_filter.WEAK_TOKENS | {"one", "shot", "oneshot", "dry", "wet", "short", "long", "high", "low"}


def _in_catch_all(path):
    return CATCH_ALL_FOLDER in {part.lower() for part in path.split(os.sep)}


def suggest_rules(library_root, min_files=sorter_engine.MIN_RULE_EVIDENCE, min_share=0.9, should_cancel=None):
    """Returns suggestions sorted by evidence: [{token, target, count, examples, is_new_folder}]."""
    if not os.path.isdir(library_root):
        raise ValueError("The Library is unavailable; saved suggestions were not changed.")
    def scan_error(error):
        raise error
    stem_tokens = []
    manual_samples = []
    for dirpath, dirnames, filenames in os.walk(library_root, onerror=scan_error):
        if should_cancel and should_cancel():
            return []
        dirnames[:] = [d for d in dirnames if d not in sorter_engine.IGNORED_DIRECTORIES]
        for filename in filenames:
            if ableton_tags.is_metadata_stub(filename):
                continue
            if os.path.splitext(filename)[1].lower() not in xo_filter.AUDIO_EXTS:
                continue
            path = os.path.join(dirpath, filename)
            if not _in_catch_all(os.path.relpath(path, library_root)):
                continue
            stem = os.path.splitext(filename)[0]
            if sorter_engine.explain_filename(filename)["winner"]:
                continue
            manual_samples.append(path)
            sound_type, _ = xo_filter.classify(os.path.join(library_root, filename), library_root)
            if sound_type is None:
                continue
            words = {w for w in re.findall(r"[a-z]+", re.sub(r"[_#\-]", " ", stem.lower())) if len(w) >= 3}
            stem_tokens.append((path, sound_type, words))

    manual = ableton_tags.read_sample_assignments(manual_samples)
    indexed = sorter_engine.get_all_indexed_asset_tags()
    word_files = defaultdict(int)
    word_types = defaultdict(Counter)
    examples = defaultdict(list)
    for path, sound_type, words in stem_tokens:
        evidence = tag_evidence.interpret_manual_tags(manual.get(os.path.normcase(os.path.abspath(path)), ()))
        if evidence.assignments or sorter_engine.resolve_routing_tags(indexed.get(os.path.normpath(path), [])) != (None, None):
            continue
        filename = os.path.basename(path)
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
        if hits < min_files or hits / total < min_share or sound_type not in xo_filter._TOKEN_TYPE.get(word, ()):
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
    evidence_by_word = defaultdict(list)
    for path in manual_samples:
        if should_cancel and should_cancel():
            return []
        evidence = tag_evidence.interpret_manual_tags(manual.get(os.path.normcase(os.path.abspath(path)), ()))
        # Contradictory or unmapped sound assignments are not labels for learning.
        filename = os.path.basename(path)
        if sorter_engine.resolve_routing_tags(indexed.get(os.path.normpath(path), [])) != (None, None):
            continue
        if evidence.is_loop or not evidence.one_shot_eligible or re.search(r"\b(loop|loops)\b", filename.replace("_", " "), re.IGNORECASE):
            continue
        words = set(re.findall(r"[a-z]{3,}", os.path.splitext(filename)[0].lower()))
        for word in words - SKIP_TOKENS - {"pack", "sample", "audio", "sound"}:
            evidence_by_word[word].append((path, evidence))
    for word, observations in evidence_by_word.items():
        if any(evidence.assignments for _path, evidence in observations):
            suggestions = [suggestion for suggestion in suggestions if suggestion["token"] != word]
        totals = Counter(evidence.sound_type for _path, evidence in observations)
        sound_type, hits = totals.most_common(1)[0]
        if not sound_type or hits < min_files or hits / len(observations) < min_share:
            continue
        pattern = sorter_engine.build_learned_rule_pattern(word)
        if pattern in existing_patterns or any(re.search(p, word) for p in existing_patterns):
            continue
        target = TYPE_TO_FOLDER[sound_type]
        # Independent manual evidence takes precedence over a name-derived suggestion for this token.
        suggestions = [suggestion for suggestion in suggestions if suggestion["token"] != word]
        examples = [os.path.basename(path) for path, evidence in observations if evidence.sound_type == sound_type][:3]
        assignments = sorted({
            tag for _path, evidence in observations if evidence.sound_type == sound_type
            for tag in evidence.assignments
        })
        suggestions.append({
            "token": word, "target": target, "count": hits, "pattern": pattern,
            "examples": examples, "is_new_folder": target not in existing_folders,
            "evidence_source": "live_manual", "evidence_tags": assignments,
            "evidence_total": len(observations),
        })
    for suggestion in suggestions:
        suggestion.update({
            "library_root": os.path.abspath(library_root),
            "min_files": min_files, "min_share": min_share,
        })
    suggestions.sort(key=lambda s: -s["count"])
    return suggestions


def revalidate_candidates(candidates):
    """Re-scan each candidate scope once; never approve using saved counts alone."""
    scans = {}
    refreshed = []
    for candidate in candidates:
        if candidate.get("evidence_source") not in {"live_manual", "filename_vocabulary"}:
            raise ValueError(
                f"Suggestion '{candidate.get('token')}' contains historical observations, "
                "not verified current files. Refresh suggestions from the current Library "
                "before approving; unsupported historical suggestions will be retired."
            )
        root = candidate.get("library_root")
        minimum = candidate.get("min_files")
        share = candidate.get("min_share")
        if (
            not isinstance(root, str) or not os.path.isabs(root) or not os.path.isdir(root)
            or not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1
            or not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 < share <= 1
        ):
            raise ValueError(
                f"Suggestion '{candidate.get('token')}' has no usable scan scope or thresholds. "
                "Refresh suggestions from the current Library before approving."
            )
        minimum = max(minimum, sorter_engine.MIN_RULE_EVIDENCE)
        share = max(share, 0.9)
        key = (os.path.normcase(os.path.abspath(root)), minimum, share)
        if key not in scans:
            scans[key] = suggest_rules(root, min_files=minimum, min_share=share)
        current = next((
            item for item in scans[key]
            if item["token"] == candidate.get("token") and item["target"] == candidate.get("target")
            and item["pattern"] == candidate.get("pattern")
            and item.get("evidence_source", "filename_vocabulary") == candidate.get("evidence_source")
        ), None)
        if current is None:
            raise ValueError(
                f"Suggestion '{candidate.get('token')}' is no longer supported by current files, tags and rules. "
                "No selected suggestions were approved. Refresh suggestions and review the evidence."
            )
        refreshed.append({**candidate, **current})
    return refreshed


@sorter_engine.serialized_config
def add_suggestions_as_candidates(suggestions, *, library_root=None):
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
    known = {(c.get("token"), c.get("target")): c for c in candidates}
    scope = os.path.normcase(os.path.abspath(library_root)) if library_root else None
    returned = {(item["token"], item["target"]) for item in suggestions}
    added = 0
    updated = False
    if scope is not None:
        for candidate in candidates:
            if candidate.get("status", "pending") != "pending":
                continue
            root = candidate.get("library_root")
            historical = not root and candidate.get("evidence_source") not in {
                "live_manual", "filename_vocabulary"
            }
            in_scope = isinstance(root, str) and os.path.normcase(os.path.abspath(root)) == scope
            if (in_scope or historical) and (candidate.get("token"), candidate.get("target")) not in returned:
                candidate.update(
                    status="stale",
                    stale_reason="Not supported by the latest completed Library scan.",
                    library_root=os.path.abspath(library_root),
                )
                updated = True
    for suggestion in suggestions:
        key = (suggestion["token"], suggestion["target"])
        existing = known.get(key)
        if existing is not None and existing.get("status", "pending") not in {"pending", "stale"}:
            continue
        if existing is not None and scope is not None:
            root = existing.get("library_root")
            if isinstance(root, str) and os.path.normcase(os.path.abspath(root)) != scope:
                continue
        minimum = suggestion.get("min_files", sorter_engine.MIN_RULE_EVIDENCE)
        share = suggestion.get("min_share", 0.9)
        if existing is not None and scope is not None:
            previous_minimum = existing.get("min_files")
            previous_share = existing.get("min_share")
            if isinstance(previous_minimum, int) and not isinstance(previous_minimum, bool):
                minimum = max(minimum, previous_minimum, sorter_engine.MIN_RULE_EVIDENCE)
            if isinstance(previous_share, (int, float)) and not isinstance(previous_share, bool):
                share = max(share, previous_share, 0.9)
            total = suggestion.get("evidence_total", suggestion["count"])
            if suggestion["count"] < minimum or not total or suggestion["count"] / total < share:
                existing.update(
                    status="stale",
                    stale_reason="Current scan does not meet this suggestion's stricter saved thresholds.",
                )
                updated = True
                continue
        candidate = {
            "token": suggestion["token"], "target": suggestion["target"],
            "count": suggestion["count"], "pattern": suggestion["pattern"],
            "status": "pending",
            "evidence_source": suggestion.get("evidence_source", "filename_vocabulary"),
            "evidence_tags": suggestion.get("evidence_tags", []),
            "examples": suggestion.get("examples", []),
            "evidence_total": suggestion.get("evidence_total", suggestion["count"]),
            **{name: suggestion[name] for name in ("library_root", "min_files", "min_share") if name in suggestion},
        }
        if scope is not None:
            candidate.update(library_root=os.path.abspath(library_root), min_files=minimum, min_share=share)
        if existing is not None:
            if existing != candidate:
                existing.clear()
                existing.update(candidate)
                updated = True
        else:
            candidates.append(candidate)
            known[key] = candidate
            added += 1
    if added or updated or removed_stale:
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
    return added

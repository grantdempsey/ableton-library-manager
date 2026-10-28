"""Conservative, exact manual Live sound-type evidence; never a routing command."""
from dataclasses import dataclass
import os
import re


TYPE_TO_FOLDER = {
    "Kicks": "Kicks", "Snares": "Snares", "Claps": "Claps", "Hi-Hats": "Hi-Hats",
    "Cymbals": "Cymbals & Crashes", "Toms": "Toms", "Percussion": "Percussion",
    "808 & Sub Bass": "808 Sub Bass", "Bass": "Bass",
    "Leads": "Melodic & Synth One-Shots", "Pads": "Melodic & Synth One-Shots",
    "Plucks & Synths": "Melodic & Synth One-Shots", "Vocals": "Vocals & Chants",
    "FX & Transitions": "Sound FX", "Ambience & Textures": "Cinematic & Ambience",
    "Nature": "Nature", "Foley": "Foley", "Keys & Piano": "Keys & Piano",
    "Guitar & Bass Guitar": "Guitar", "Strings & Orchestral": "Strings & Orchestral",
    "Brass & Winds": "Brass & Winds", "Bells & Mallets": "Bells & Mallets",
}
_LABELS = {
    "kick": "Kicks", "snare": "Snares", "clap": "Claps", "hi-hat": "Hi-Hats",
    "cymbal": "Cymbals", "tom": "Toms", "percussion": "Percussion",
    "808": "808 & Sub Bass", "sub bass": "808 & Sub Bass", "synth bass": "Bass",
    "bass": "Bass", "lead": "Leads", "pad": "Pads", "pluck": "Plucks & Synths",
    "synth": "Plucks & Synths", "vocal": "Vocals", "sound fx": "FX & Transitions",
    "ambience": "Ambience & Textures", "texture": "Ambience & Textures",
    "nature": "Nature", "foley": "Foley", "piano": "Keys & Piano",
    "guitar": "Guitar & Bass Guitar", "strings": "Strings & Orchestral",
    "brass": "Brass & Winds", "bell": "Bells & Mallets",
    **{name.casefold(): name for name in TYPE_TO_FOLDER},
}
_DRUM_TYPES = {
    "kick": "Kicks", "snare": "Snares", "clap": "Claps", "hihat": "Hi-Hats",
    "cymbal": "Cymbals", "tom": "Toms", "percussion": "Percussion",
}
_SOUND_TYPES = {
    "bass": "Bass", "lead": "Leads", "pad": "Pads",
    "piano & keys": "Keys & Piano", "guitar & plucked": "Guitar & Bass Guitar",
    "strings": "Strings & Orchestral", "brass": "Brass & Winds", "woodwind": "Brass & Winds",
    "mallets": "Bells & Mallets", "voice": "Vocals",
}
_SOUND_SUBTYPES = {
    ("bass", "808 bass"): "808 & Sub Bass",
    ("bass", "electric bass"): "Guitar & Bass Guitar",
    ("bass", "acoustic bass"): "Guitar & Bass Guitar",
    ("bass", "upright bass"): "Guitar & Bass Guitar",
    ("guitar & plucked", "synth plucked"): "Plucks & Synths",
    ("ambience & fx", "atmosphere"): "Ambience & Textures",
    ("ambience & fx", "field & foley"): "Foley",
    ("ambience & fx", "impact"): "FX & Transitions",
    ("ambience & fx", "noise"): "FX & Transitions",
    ("ambience & fx", "sound fx"): "FX & Transitions",
    ("ambience & fx", "sweep"): "FX & Transitions",
}


@dataclass(frozen=True)
class ManualTagEvidence:
    sound_type: str | None
    assignments: tuple[str, ...]
    alternatives: tuple[str, ...]
    is_loop: bool
    one_shot_eligible: bool = True


@dataclass(frozen=True)
class ManualKeyEvidence:
    key: str | None
    assignments: tuple[str, ...]
    ambiguous: bool


_PITCHES = {
    "c": "C", "c#": "C#", "db": "C#", "d": "D", "d#": "D#", "eb": "D#",
    "e": "E", "fb": "E", "e#": "F", "f": "F", "f#": "F#", "gb": "F#",
    "g": "G", "g#": "G#", "ab": "G#", "a": "A", "a#": "A#", "bb": "A#",
    "b": "B", "cb": "B", "b#": "C",
}


def key_identity(value):
    """Canonical comparison key; never derives a mode from a bare note."""
    value = value.strip().casefold().replace("\u266f", "#").replace("\u266d", "b")
    match = re.fullmatch(r"([a-g][#b]?)\s*(major|minor|maj|min|m)?", value)
    if not match:
        return None
    root, mode = match.groups()
    if root not in _PITCHES or mode is None:
        return None
    return _PITCHES[root] + ("MIN" if mode in {"minor", "min", "m"} else "MAJ")


def interpret_manual_key(tags):
    """Live's Key root and mode are separate tags; both must be unambiguous."""
    roots, modes, assignments = set(), set(), []
    for tag in sorted(set(tags)):
        parts = tag.split("|")
        if len(parts) != 2 or parts[0].casefold() != "key":
            continue
        value = parts[1].casefold().replace("\u266f", "#").replace("\u266d", "b")
        if value in _PITCHES:
            roots.add(_PITCHES[value])
        elif value in {"major", "minor"}:
            modes.add("MAJ" if value == "major" else "MIN")
        else:
            continue
        assignments.append(tag)
    ambiguous = len(roots) > 1 or len(modes) > 1
    key = next(iter(roots)) + next(iter(modes)) if len(roots) == len(modes) == 1 else None
    return ManualKeyEvidence(key, tuple(assignments), ambiguous)


def describe_loop_tag_audit(audit):
    return (
        f"Manual tag audit: {audit['manual_loops']:,} tagged loops "
        f"({audit['tag_only_loops']:,} without filename hints); "
        f"{audit['role_conflicts']:,} role conflicts.\n"
        f"Loop keys: {audit['complete_keys']:,} complete, "
        f"{audit['ambiguous_keys']:,} ambiguous, {audit['incomplete_keys']:,} incomplete; "
        f"{audit['key_conflicts']:,} filename disagreements, "
        f"{audit['keys_missing_from_filenames']:,} missing filename keys.\n"
        "Tag evidence is review-only. Layout coverage below uses executable filename routing, "
        "not tag-only loop/key assignments. No routing, filenames or tags are changed."
    )


def interpret_manual_tags(tags):
    """Interpret manual hierarchy semantics without flattening unrelated tag groups."""
    mapped = {}
    roles = []
    is_loop = False
    one_shot_eligible = True
    tags = sorted(set(tags))
    # A specific child refines its parent, rather than creating a second vote.
    most_specific = [tag for tag in tags if not any(other.startswith(tag + "|") for other in tags)]
    for tag in most_specific:
        parts = tag.split("|")
        if len(parts) < 2:
            continue
        group, category = (part.casefold() for part in parts[:2])
        sound_type = None
        if (group == "type" and category == "loop") or (
            group == "drums" and category == "drum loop"
        ) or (group == "sounds" and parts[-1].casefold() in {"loop", "loops"}):
            is_loop = True
            roles.append(tag)
        elif group == "type" and category == "one shot":
            roles.append(tag)
        elif (group == "type" and category in {"impulse response", "multisampled", "construction kit"}) or (
            group == "drums" and category == "drum kit"
        ):
            one_shot_eligible = False
            roles.append(tag)
        if group == "drums":
            sound_type = _DRUM_TYPES.get(category)
        elif group == "sounds":
            subtype = parts[2].casefold() if len(parts) > 2 else ""
            sound_type = _SOUND_SUBTYPES.get((category, subtype), _SOUND_TYPES.get(category))
            if not sound_type:
                sound_type = _LABELS.get(parts[-1].casefold())
        if sound_type:
            mapped.setdefault(sound_type, []).append(tag)
    alternatives = tuple(sorted(mapped))
    assignments = tuple(sorted(
        [tag for tags in mapped.values() for tag in tags] + roles
    ))
    return ManualTagEvidence(
        alternatives[0] if len(alternatives) == 1 else None, assignments, alternatives, is_loop, one_shot_eligible
    )


def suggested_folder(sound_type):
    folder = TYPE_TO_FOLDER[sound_type]
    return ("Percussion", "Shakers") if folder == "Percussion" else ("Samples", "One-Shots", folder)


def describe_preview_evidence(record):
    proposal = record.get("tag_suggestion")
    if not proposal:
        return ""
    destination = proposal.get("destination")
    return (
        f"Manual Live tag suggestion: {destination or 'no single destination'}; "
        f"{proposal['status']}. Evidence: {', '.join(proposal['assignments'])}. "
        "Review only; the normal routing plan is unchanged."
    )


def describe_library_evidence(path, library_root, tags, routing_type, routing_folder):
    evidence = interpret_manual_tags(tags)
    if not evidence.assignments:
        return (
            "No folder advice available for this sound.\n\n"
            "Its saved manual Live tags do not identify a supported sound type. "
            "This is normal for sounds without manual tags. Genres, Character and "
            "the manager's generated search tags do not determine a destination.\n\n"
            "Your existing sorting rules still apply. No files, tags or rules are changed."
        )
    lines = ["Evidence: " + ", ".join(evidence.assignments)]
    if routing_type or routing_folder:
        lines.append("Explicit local routing retained: " + str(routing_folder or routing_type))
    from sorter_engine import AUDIO_EXTS
    if os.path.splitext(path)[1].lower() not in AUDIO_EXTS:
        lines.append("Non-audio item: no audio one-shot destination recommended.")
    elif not evidence.one_shot_eligible:
        lines.append("Manual kit, multisample or impulse-response role: no one-shot destination recommended.")
    elif not evidence.alternatives:
        lines.append("Manual role only: no sound type inferred.")
    elif not evidence.sound_type:
        lines.append("Conflicting sound types: " + ", ".join(evidence.alternatives))
    elif evidence.is_loop:
        lines.append("Manual loop assignment: no one-shot destination recommended.")
    else:
        destination = os.path.normpath(os.path.join(library_root, *suggested_folder(evidence.sound_type)))
        lines.append("Suggested folder: " + os.path.relpath(destination, library_root))
        lines.append(
            "Already in the suggested folder." if os.path.normcase(os.path.dirname(path)) == os.path.normcase(destination)
            else "Folder differs; review in Organize. Existing rules and protected folders still apply."
        )
    lines.append("Review only: no files, tags, or rules are changed.")
    return "\n\n".join(lines)

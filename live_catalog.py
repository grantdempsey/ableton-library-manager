"""Read-only adapter for the verified Live 12 browser catalog schema."""
from dataclasses import dataclass, replace
import os
from pathlib import Path
import sqlite3

KEYWORD_METADATA_KEY = int.from_bytes(b"Keyw", "big")
HIERARCHY_KEYS = {int.from_bytes(name.encode(), "big"): name for name in ("Keyw", "CKey", "IKey", "HKey", "UKey")}
FIELD_KEYS = {
    int.from_bytes(b"DvTy", "big"): (
        "Function", {"Instrument": "Instrument", "Audio Effect": "Audio Effect", "Midi Effect": "MIDI Effect"}
    ),
    int.from_bytes(b"MxTy", "big"): (
        "MIDI Tools", {"Max Note Generator": "Generator", "Max Note Transformation": "Transformation"}
    ),
}
DEVICE_CLASS_KEY = int.from_bytes(b"DvCI", "big")
MAX_DEVICE_CLASSES = {
    "device:ableton:instr:MxDeviceInstrument",
    "device:ableton:audiofx:MxDeviceAudioEffect",
    "device:ableton:midifx:MxDeviceMidiEffect",
}
CATALOG_TYPES = {
    "alc-": "Clip", "adg-": "Rack", "adv-": "Device preset", "midi": "MIDI",
    "vstp": "Plug-in preset", "agr-": "Groove", "ams-": "Audio",
    "amp-": "Max device", "als-": "Live Set", "scl-": "Tuning",
}

@dataclass(frozen=True)
class CatalogSample:
    path: str
    non_auto: tuple[str, ...]
    automatic: tuple[str, ...]
    factory: tuple[str, ...]
    item_type: str = "Audio"
    additional: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()
    metadata_details: tuple[str, ...] = ()
    manual: tuple[str, ...] = ()

    @property
    def tags(self):
        return tuple(sorted(set(self.non_auto + self.automatic + self.factory + self.additional + self.fields + self.manual)))


def available_databases():
    if os.name == "nt":
        folder = Path(os.environ.get("LOCALAPPDATA", "")) / "Ableton" / "Live Database"
    else:
        folder = Path.home() / "Library" / "Application Support" / "Ableton" / "Live Database"
    return tuple(sorted(folder.glob("Live-files-*.db"))) if folder.is_dir() else ()


def read_user_sidecars(samples, library_root):
    """Overlay exact-path User Library sidecars, never relabel factory metadata as manual."""
    import ableton_tags
    if not library_root or not os.path.isabs(library_root):
        raise ValueError("An absolute User Library root is required for catalog sidecar reads.")
    if not os.path.isdir(library_root):
        raise OSError("The configured User Library is unavailable; catalog sidecars could not be refreshed.")
    samples = tuple(samples)
    lexical_root = os.path.normcase(os.path.abspath(library_root))
    root = os.path.normcase(os.path.realpath(library_root))
    paths = []
    for sample in samples:
        lexical_path = os.path.normcase(os.path.abspath(sample.path))
        if os.path.splitdrive(lexical_path)[0] != os.path.splitdrive(lexical_root)[0]:
            continue
        if os.path.commonpath((lexical_root, lexical_path)) != lexical_root:
            continue
        path = os.path.normcase(os.path.realpath(sample.path))
        # A different drive or a link outside the root is not part of this source.
        if os.path.splitdrive(path)[0] != os.path.splitdrive(root)[0]:
            continue
        if os.path.commonpath((root, path)) == root and path != root:
            paths.append(sample.path)
    assignments = ableton_tags.read_sample_assignments(paths)
    return tuple(
        replace(sample, manual=tuple(assignments.get(os.path.normcase(os.path.abspath(sample.path)), ())))
        for sample in samples
    )


def read_catalog(database, *, include_other_items=False):
    """Returns filesystem catalog items and source-separated hierarchies, without touching either index."""
    from sorter_engine import AUDIO_EXTS
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        nodes = {
            file_id: (parent, name, file_type)
            for file_id, parent, name, file_type in connection.execute("SELECT file_id, parent_id, name, file_type FROM files")
        }
        resolved = {}
        def parts_for(file_id):
            chain = []
            seen = set()
            current = file_id
            while current in nodes and current not in resolved:
                if current in seen:
                    raise ValueError("Cycle in Live catalog path hierarchy.")
                seen.add(current)
                chain.append(current)
                current = nodes[current][0]
            if current not in resolved and current not in (0, None):
                raise ValueError("Incomplete Live catalog path hierarchy.")
            parts = resolved.get(current, ())
            for node in reversed(chain):
                name = nodes[node][1]
                if not isinstance(name, str) or not name:
                    raise ValueError("Invalid name in Live catalog path hierarchy.")
                parts = (*parts, name)
                resolved[node] = parts
            return parts
        samples = {}
        for file_id, (_parent, name, file_type) in nodes.items():
            if not isinstance(name, str):
                raise ValueError("Invalid name in Live catalog.")
            is_audio = os.path.splitext(name)[1].lower() in AUDIO_EXTS
            if not isinstance(file_type, int) or not 0 <= file_type <= 0xFFFFFFFF:
                raise ValueError("Unsupported Live catalog file type.")
            type_code = file_type.to_bytes(4, "big").decode("ascii", errors="replace")
            if not is_audio and (not include_other_items or type_code not in CATALOG_TYPES):
                continue
            parts = parts_for(file_id)
            # Virtual keyword/pack trees must never be treated as filesystem paths.
            if not parts or not os.path.isabs(parts[0]):
                continue
            path = os.path.normpath(os.path.join(*parts))
            extension = os.path.splitext(name)[1].lstrip(".").upper()
            fields = {f"File extension|{extension}"} if extension else set()
            if type_code == "amp-":
                fields.add("Format|Max for Live")
            samples[file_id] = (
                path, set(), set(), set(), "Audio" if is_audio else CATALOG_TYPES[type_code],
                set(), fields, set()
            )
        for file_id, keyword_id, is_auto in connection.execute("SELECT file_id, keyw_id, is_auto FROM keywords"):
            if file_id not in samples:
                continue
            parts = parts_for(keyword_id)
            if len(parts) < 3 or parts[0] != "<keywords>" or is_auto not in (0, 1):
                raise ValueError("Unsupported Live catalog keyword hierarchy or provenance.")
            samples[file_id][2 if is_auto else 1].add("|".join(parts[1:]))
        metadata_keys = (*HIERARCHY_KEYS, *FIELD_KEYS, DEVICE_CLASS_KEY)
        placeholders = ",".join("?" for _key in metadata_keys)
        for file_id, key, value in connection.execute(
            "SELECT m.file_id, m.key, v.value FROM metadata m "
            f"JOIN metadata_values v ON v.id = m.value_id WHERE m.key IN ({placeholders})",
            metadata_keys
        ):
            if file_id not in samples:
                continue
            if key == DEVICE_CLASS_KEY:
                if not isinstance(value, str) or not value.strip():
                    raise ValueError("Unsupported Live catalog device class.")
                samples[file_id][7].add(f"DvCI: {value}")
                if samples[file_id][4] in ("Device preset", "Rack"):
                    if value.startswith("device:m4l:") or value in MAX_DEVICE_CLASSES:
                        samples[file_id][6].add("Format|Max for Live")
                    elif value.startswith(("device:ableton:instr:", "device:ableton:audiofx:", "device:ableton:midifx:")):
                        samples[file_id][6].add("Format|Ableton")
                continue
            if key in FIELD_KEYS:
                group, labels = FIELD_KEYS[key]
                if not isinstance(value, str) or value not in labels:
                    raise ValueError("Unsupported Live catalog browser field.")
                samples[file_id][6].add(f"{group}|{labels[value]}")
                samples[file_id][7].add(f"{key.to_bytes(4, 'big').decode('ascii')}: {value}")
                continue
            if not isinstance(value, str) or "|" not in value or any(not part.strip() for part in value.split("|")):
                raise ValueError("Unsupported Live catalog metadata hierarchy.")
            if key == KEYWORD_METADATA_KEY:
                samples[file_id][3].add(value)
            else:
                samples[file_id][5].add(value)
                samples[file_id][7].add(f"{HIERARCHY_KEYS[key]}: {value}")
        return tuple(sorted((
            CatalogSample(
                path, tuple(sorted(manual)), tuple(sorted(auto)), tuple(sorted(factory)), item_type,
                tuple(sorted(additional)), tuple(sorted(fields)), tuple(sorted(metadata_details))
            )
            for path, manual, auto, factory, item_type, additional, fields, metadata_details in samples.values()
        ), key=lambda sample: sample.path.casefold()))
    finally:
        connection.close()


def read_vocabulary(database):
    """Reads the stored keyword hierarchy, including unused values; not a fabricated global taxonomy."""
    connection = sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        nodes = {file_id: (parent, name) for file_id, parent, name in connection.execute(
            "SELECT file_id, parent_id, name FROM files"
        )}
        roots = {file_id for file_id, (_parent, name) in nodes.items() if name == "<keywords>"}
        if not roots:
            raise ValueError("Live catalog has no supported keyword vocabulary root.")
        values = set()
        for file_id in nodes:
            parts = []
            seen = set()
            current = file_id
            while current in nodes and current not in roots:
                if current in seen:
                    raise ValueError("Cycle in Live catalog vocabulary.")
                seen.add(current)
                current, name = nodes[current]
                parts.append(name)
            if current in roots and parts:
                if any(not isinstance(part, str) or not part.strip() for part in parts):
                    raise ValueError("Invalid Live catalog vocabulary value.")
                values.add("|".join(reversed(parts)))
        placeholders = ",".join("?" for _key in HIERARCHY_KEYS)
        for (value,) in connection.execute(
            "SELECT DISTINCT v.value FROM metadata m "
            f"JOIN metadata_values v ON v.id = m.value_id WHERE m.key IN ({placeholders})",
            tuple(HIERARCHY_KEYS)
        ):
            if not isinstance(value, str) or "|" not in value or any(not part.strip() for part in value.split("|")):
                raise ValueError("Unsupported Live catalog metadata hierarchy.")
            values.add(value)
        return tuple(sorted(values, key=str.casefold))
    finally:
        connection.close()


def filter_catalog(samples, search="", group="", tag="", source="All sources", *, item_type="All item types", tags=()):
    """Combine alternatives within a group and require every selected group.

    Facet counts apply the other groups' selections, allowing alternatives in the
    displayed group to remain discoverable. Parent tags include their descendants.
    """
    source_field = {
        "All sources": "tags", "Non-auto (catalog)": "non_auto",
        "Automatic": "automatic", "Factory / catalog metadata": "factory",
        "Additional hierarchy metadata": "additional", "Browser fields (read only)": "fields",
        "User Library sidecars": "manual",
    }
    if source not in source_field:
        raise ValueError("Choose a supported Live catalog source.")
    selected = {}
    for value in (*tags, *((tag,) if tag else ())):
        if not isinstance(value, str) or not value.strip() or any(not part.strip() for part in value.split("|")):
            raise ValueError("Choose a valid Live catalog tag hierarchy.")
        selected.setdefault(value.split("|")[0], set()).add(value)
    selected_groups = set(selected)
    terms = search.casefold().split()
    matches = []
    counts = {}
    for sample in samples:
        if item_type != "All item types" and sample.item_type != item_type:
            continue
        assignments = getattr(sample, source_field[source])
        haystack = (sample.path + " " + " ".join(assignments)).casefold()
        if any(term not in haystack for term in terms):
            continue
        scoped = [value for value in assignments if not group or value.split("|")[0] == group]
        if (group or source != "All sources") and not scoped:
            continue
        ancestors = {
            "|".join(parts[:depth])
            for value in assignments
            for parts in (value.split("|"),)
            for depth in range(1, len(parts) + 1)
        }
        matched_groups = {name for name, alternatives in selected.items() if alternatives & ancestors}
        missing_groups = selected_groups - matched_groups
        for value in ancestors:
            name = value.split("|")[0]
            if (not group or name == group) and missing_groups <= {name}:
                counts[value] = counts.get(value, 0) + 1
        if not missing_groups:
            matches.append(sample)
    return matches, counts

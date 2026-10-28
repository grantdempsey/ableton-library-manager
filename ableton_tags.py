import os
import filecmp
import shutil
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


NAMESPACES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "ablFR": "https://ns.ableton.com/xmp/fs-resources/1.0/",
}
CACHE_PREFIX = "ableton:"
TAG_GROUPS = (
    "Character", "Clips", "Creator", "Devices", "Drums", "Genres",
    "Grooves", "Key", "Sounds", "Tunings", "Type",
)
_WRITE_LOCK = threading.RLock()
for _prefix, _namespace in {
    **NAMESPACES, "x": "adobe:ns:meta/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xmp": "http://ns.adobe.com/xap/1.0/",
}.items():
    ET.register_namespace(_prefix, _namespace)


def is_metadata_stub(name):
    return os.path.basename(name).startswith("._")


def read_folder_tags(folder):
    """Reads Live 12 folder sidecars without changing metadata or audio."""
    metadata_folder = os.path.join(folder, "Ableton Folder Info")
    try:
        entries = os.scandir(metadata_folder)
    except FileNotFoundError:
        return {}
    assignments = {}
    with entries:
        for entry in entries:
            if is_metadata_stub(entry.name) or not entry.name.lower().endswith(".xmp"):
                continue
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise ValueError(f"Unsupported Ableton sidecar location: {entry.path}")
            try:
                root = ET.parse(entry.path).getroot()
            except ET.ParseError as error:
                raise ValueError(f"Invalid Ableton tag sidecar {entry.path}: {error}") from error
            if root.find(".//ablFR:items/rdf:Bag", NAMESPACES) is None:
                raise ValueError(f"Unsupported Ableton tag sidecar: {entry.path}")
            for item in root.findall(".//ablFR:items/rdf:Bag/rdf:li", NAMESPACES):
                relative = item.findtext("ablFR:filePath", namespaces=NAMESPACES)
                if not relative:
                    raise ValueError(f"Missing sample path in Ableton sidecar: {entry.path}")
                relative = relative.replace("\\", os.sep).replace("/", os.sep)
                path = os.path.normpath(os.path.join(os.path.abspath(folder), relative))
                root_path = os.path.realpath(folder)
                resolved = os.path.realpath(path)
                if (
                    os.path.isabs(relative)
                    or os.path.commonpath([root_path, resolved]) != root_path
                    or resolved == root_path
                ):
                    raise ValueError(f"Sample path escapes its Ableton sidecar folder: {entry.path}")
                tags = assignments.setdefault(os.path.normcase(path), set())
                keywords = item.find("ablFR:keywords", NAMESPACES)
                if keywords is not None and keywords.find("rdf:Bag", NAMESPACES) is None:
                    raise ValueError(f"Unsupported Ableton keyword structure: {entry.path}")
                for keyword in item.findall("ablFR:keywords/rdf:Bag/rdf:li", NAMESPACES):
                    tag = keyword.text
                    if not tag or any(not part.strip() for part in tag.split("|")):
                        raise ValueError(f"Invalid Ableton tag hierarchy in {entry.path}")
                    tags.add(tag)
    return {path: sorted(tags) for path, tags in assignments.items()}


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _documents(sample):
    folder = Path(os.path.abspath(sample)).parent
    documents = {}
    for ancestor in (folder, *folder.parents):
        # Validate all sidecars before planning any writes.
        read_folder_tags(str(ancestor))
        info = ancestor / "Ableton Folder Info"
        if info.is_symlink():
            raise ValueError(f"Linked metadata folders cannot be edited: {info}")
        if info.is_dir():
            for path in info.iterdir():
                if is_metadata_stub(path.name) or path.suffix.lower() != ".xmp":
                    continue
                original = path.read_bytes()
                parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
                documents[path] = (original, ET.fromstring(original, parser=parser))
    return documents


def sample_tags(sample):
    """Reads manual tags from adjacent and ancestor folder sidecars."""
    return _tags_from_documents(sample, _documents(sample))


def read_sample_assignments(samples):
    """Reads each relevant metadata folder once, keyed by exact normalized sample path."""
    samples = tuple(dict.fromkeys(os.path.abspath(sample) for sample in samples))
    sample_keys = {os.path.normcase(sample) for sample in samples}
    folders = set()
    for sample in samples:
        folder = Path(sample).parent
        folders.update((folder, *folder.parents))
    assignments = {}
    for folder in sorted(folders):
        for path, tags in read_folder_tags(str(folder)).items():
            if path in sample_keys:
                assignments.setdefault(path, set()).update(tags)
    return {os.path.normcase(sample): sorted(assignments.get(os.path.normcase(sample), ())) for sample in samples}


def _tags_from_documents(sample, documents):
    tags = set()
    for path, (_original, root) in documents.items():
        for item in _matching_items(root, path, sample):
            tags.update(
                node.text for node in item.findall("ablFR:keywords/rdf:Bag/rdf:li", NAMESPACES)
                if node.text
            )
    return sorted(tags)


def _matching_items(root, sidecar, sample):
    for item in root.findall(".//ablFR:items/rdf:Bag/rdf:li", NAMESPACES):
        relative = item.findtext("ablFR:filePath", namespaces=NAMESPACES)
        if relative and _key(os.path.join(
            sidecar.parent.parent, relative.replace("\\", os.sep).replace("/", os.sep)
        )) == _key(sample):
            yield item


def _keyword_bag(item):
    keywords = item.find("ablFR:keywords", NAMESPACES)
    if keywords is None:
        keywords = ET.SubElement(item, f"{{{NAMESPACES['ablFR']}}}keywords")
    bag = keywords.find("rdf:Bag", NAMESPACES)
    if bag is None:
        bag = ET.SubElement(keywords, f"{{{NAMESPACES['rdf']}}}Bag")
    return bag


def _new_document():
    root = ET.Element("{adobe:ns:meta/}xmpmeta")
    description = ET.SubElement(
        ET.SubElement(root, f"{{{NAMESPACES['rdf']}}}RDF"),
        f"{{{NAMESPACES['rdf']}}}Description",
        {f"{{{NAMESPACES['rdf']}}}about": ""}
    )
    ET.SubElement(description, "{http://purl.org/dc/elements/1.1/}format").text = (
        "application/vnd.ableton.folder"
    )
    ET.SubElement(description, f"{{{NAMESPACES['ablFR']}}}resource").text = "folder"
    ET.SubElement(description, f"{{{NAMESPACES['ablFR']}}}platform").text = (
        "win" if os.name == "nt" else "mac"
    )
    ET.SubElement(
        ET.SubElement(description, f"{{{NAMESPACES['ablFR']}}}items"),
        f"{{{NAMESPACES['rdf']}}}Bag"
    )
    return root


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class TagEdit:
    """A reviewed set of sidecar changes with optimistic conflict detection."""

    def __init__(self, assignments, documents=None):
        self.changes = {}
        self.backups = []
        self.sample_fingerprints = {}
        self.sample_changes = ()
        self.unchanged_count = 0
        if documents is None:
            documents = {}
            for sample in assignments:
                documents.update(_documents(sample))
        self.originals = {path: original for path, (original, _root) in documents.items()}
        self.inventories = {}
        for sample in assignments:
            folder = Path(os.path.abspath(sample)).parent
            for ancestor in (folder, *folder.parents):
                info = ancestor / "Ableton Folder Info"
                if info not in self.inventories:
                    self.inventories[info] = {
                        path for path in self.originals if path.parent == info
                    }
        for sample, tags in assignments.items():
            matches = [
                (path, item) for path, (_original, root) in documents.items()
                for item in _matching_items(root, path, sample)
            ]
            if not matches and tags:
                path = Path(sample).absolute().parent / "Ableton Folder Info" / f"{uuid.uuid4()}.xmp"
                root = _new_document()
                documents[path] = (None, root)
                self.originals[path] = None
                bag = root.find(".//ablFR:items/rdf:Bag", NAMESPACES)
                if bag is None:
                    raise ValueError("Could not initialize Ableton metadata.")
                item = ET.SubElement(
                    bag, f"{{{NAMESPACES['rdf']}}}li",
                    {f"{{{NAMESPACES['rdf']}}}parseType": "Resource"}
                )
                ET.SubElement(item, f"{{{NAMESPACES['ablFR']}}}filePath").text = Path(sample).name
                matches = [(path, item)]
            current = {
                node.text for _path, item in matches
                for node in item.findall("ablFR:keywords/rdf:Bag/rdf:li", NAMESPACES)
            }
            if current == set(tags):
                continue
            for index, (path, item) in enumerate(matches):
                bag = _keyword_bag(item)
                for child in list(bag):
                    if child.tag == f"{{{NAMESPACES['rdf']}}}li":
                        bag.remove(child)
                if index == 0:
                    for tag in sorted(set(tags)):
                        ET.SubElement(bag, f"{{{NAMESPACES['rdf']}}}li").text = tag
                self.changes[path] = b""
        for path in self.changes:
            self.changes[path] = ET.tostring(documents[path][1], encoding="utf-8", xml_declaration=True)

    def commit(self):
        with _WRITE_LOCK:
            for sample, expected in self.sample_fingerprints.items():
                if os.path.islink(sample) or _sample_fingerprint(sample) != expected:
                    raise ValueError(f"Selected sample changed during review. Review again: {sample}")
            for folder, expected in self.inventories.items():
                actual = {
                    path for path in folder.iterdir()
                    if path.suffix.lower() == ".xmp" and not is_metadata_stub(path.name)
                } if folder.is_dir() else set()
                if actual != expected:
                    raise ValueError(f"Live added or removed sidecars during review. Retry: {folder}")
            for path, original in self.originals.items():
                actual = path.read_bytes() if path.exists() else None
                if actual != original:
                    raise ValueError(f"Live metadata changed during review. Retry: {path}")
            written = []
            try:
                for path, data in self.changes.items():
                    original = self.originals[path]
                    if original is not None:
                        backup = path.with_name(path.name + f".{uuid.uuid4()}.bak")
                        with backup.open("xb") as handle:
                            handle.write(original)
                        self.backups.append(str(backup))
                    actual = path.read_bytes() if path.exists() else None
                    if actual != original:
                        raise ValueError(f"Live metadata changed before save. Retry: {path}")
                    _atomic_write(path, data)
                    written.append(path)
            except (OSError, ValueError) as error:
                rollback_errors = []
                for path in reversed(written):
                    try:
                        if path.read_bytes() != self.changes[path]:
                            raise ValueError(f"Concurrent edits prevent rollback of {path}")
                        original = self.originals[path]
                        if original is None:
                            path.unlink()
                        else:
                            _atomic_write(path, original)
                    except (OSError, ValueError) as rollback_error:
                        rollback_errors.append(f"{path}: {rollback_error}")
                if rollback_errors:
                    raise OSError(
                        f"Tag edit failed ({error}); rollback incomplete: "
                        f"{'; '.join(rollback_errors)}. Backups: {self.backups}"
                    ) from error
                raise
        return list(self.backups)


def qualify_tag(tag, group):
    """Qualifies a plain label; explicit hierarchies always retain their own group."""
    if "|" in tag:
        return normalize_tag(tag)
    group = group.strip()
    if not group or "|" in group or any(ord(char) < 32 for char in group):
        raise ValueError("Choose or enter one Live tag group, not a hierarchy.")
    return normalize_tag(group + "|" + tag.strip())


def normalize_tag(tag):
    tag = tag.strip()
    if tag.lower().startswith(("ableton:", "name:", "category:")):
        raise ValueError("Enter a Live hierarchy, not an app cache or generated tag.")
    if "|" not in tag:
        tag = "Sounds|" + tag
    if (
        len(tag) > 240 or any(not part.strip() for part in tag.split("|"))
        or any(ord(character) < 32 for character in tag)
        or tag.lower().startswith(("ableton:", "name:", "category:"))
    ):
        raise ValueError("Enter a Live tag such as Sounds|Bass|Synth Bass (maximum 240 characters).")
    return tag


def prepare_edit(samples, tag, remove=False, replacement=None):
    """Plans a manual assignment or a per-selection rename, never a global taxonomy edit."""
    tag = normalize_tag(tag)
    if replacement is not None:
        replacement = normalize_tag(replacement)
    assignments = {}
    documents = {}
    samples = list(samples)
    fingerprints = {}
    for sample in samples:
        if not os.path.isfile(sample) or os.path.islink(sample):
            raise ValueError(f"Select an existing, unlinked sample: {sample}")
        fingerprints[os.path.abspath(sample)] = _sample_fingerprint(sample)
        documents.update(_documents(sample))
    for sample in samples:
        if not os.path.isfile(sample) or os.path.islink(sample):
            raise ValueError(f"Select an existing, unlinked sample: {sample}")
        tags = set(_tags_from_documents(sample, documents))
        if replacement is not None:
            if tag in tags:
                tags.remove(tag)
                tags.add(replacement)
        elif remove:
            tags.discard(tag)
        else:
            tags.add(tag)
        assignments[os.path.abspath(sample)] = sorted(tags)
    if not assignments:
        raise ValueError("Select at least one sample.")
    edit = TagEdit(assignments, documents)
    edit.sample_fingerprints = fingerprints
    return edit


def restore_duplicate(source, destination, recovery, source_tags, destination_tags, merged_tags):
    """Restore a retained duplicate without consuming or changing the surviving audio."""
    with _WRITE_LOCK:
        if os.path.lexists(source):
            raise FileExistsError(f"Original source already exists: {source}")
        if any(os.path.islink(path) for path in (destination, recovery)):
            raise ValueError("Linked files cannot be used for duplicate recovery.")
        if not filecmp.cmp(destination, recovery, shallow=False):
            raise ValueError("Duplicate destination audio changed; recovery was retained.")
        documents = _documents(destination)
        documents.update(_documents(source))
        if set(_tags_from_documents(destination, documents)) != set(merged_tags):
            raise ValueError("Duplicate destination tags changed; recovery was retained.")
        os.makedirs(os.path.dirname(source), exist_ok=True)
        created = False
        try:
            with open(recovery, "rb") as original, open(source, "xb") as restored:
                created = True
                shutil.copyfileobj(original, restored)
            plan = TagEdit(
                {os.path.abspath(source): source_tags, os.path.abspath(destination): destination_tags},
                documents,
            )
            plan.commit()
        except (OSError, ValueError) as error:
            if created:
                try:
                    os.remove(source)
                except OSError as cleanup_error:
                    raise OSError(
                        f"Duplicate recovery failed ({error}); remove incomplete source "
                        f"{source} before retrying ({cleanup_error}). Recovery retained: {recovery}"
                    ) from error
            raise


@dataclass(frozen=True)
class TagOperation:
    action: str
    tag: str
    replacement: str | None = None


def _sample_fingerprint(sample):
    info = os.stat(sample)
    if not os.path.isfile(sample):
        raise ValueError(f"Select an existing sample: {sample}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def prepare_batch(samples, operations):
    """Combines ordered operations against one snapshot without writing anything."""
    normalized = []
    for operation in operations:
        if operation.action not in {"add", "remove", "rename"}:
            raise ValueError(f"Unsupported Live tag action: {operation.action}")
        if operation.action == "rename" and operation.replacement is None:
            raise ValueError("A rename requires a replacement tag.")
        if operation.action != "rename" and operation.replacement is not None:
            raise ValueError("Only renames accept a replacement tag.")
        normalized.append(TagOperation(
            operation.action, normalize_tag(operation.tag),
            normalize_tag(operation.replacement) if operation.replacement is not None else None
        ))
    if not normalized:
        raise ValueError("Queue at least one Live tag change.")
    samples = tuple(dict.fromkeys(os.path.abspath(sample) for sample in samples))
    if not samples:
        raise ValueError("Select at least one sample.")
    fingerprints = {}
    documents = {}
    folders = set()
    for sample in samples:
        if os.path.islink(sample):
            raise ValueError(f"Linked samples cannot be edited: {sample}")
        fingerprints[sample] = _sample_fingerprint(sample)
        folder = os.path.dirname(sample)
        if folder not in folders:
            documents.update(_documents(sample))
            folders.add(folder)
    assignments = {}
    changes = []
    for sample in samples:
        before = set(_tags_from_documents(sample, documents))
        after = set(before)
        for operation in normalized:
            if operation.action == "add":
                after.add(operation.tag)
            elif operation.action == "remove":
                after.discard(operation.tag)
            elif operation.tag in after:
                if operation.replacement is None:
                    raise ValueError("A rename requires a replacement tag.")
                after.remove(operation.tag)
                after.add(operation.replacement)
        assignments[sample] = sorted(after)
        if before != after:
            changes.append((sample, tuple(sorted(after - before)), tuple(sorted(before - after))))
    plan = TagEdit(assignments, documents)
    plan.sample_fingerprints = fingerprints
    plan.sample_changes = tuple(changes)
    plan.unchanged_count = len(samples) - len(changes)
    return plan


def transfer_sample(source, destination, copy=False, duplicate=False):
    """Transfers audio and its manual tags; rolls audio back if metadata saving fails."""
    with _WRITE_LOCK:
        if _key(source) == _key(destination):
            raise ValueError("Source and destination must be different files.")
        if not os.path.isfile(source) or os.path.islink(source):
            raise ValueError(f"Source must be an existing, unlinked file: {source}")
        if os.path.islink(destination):
            raise ValueError(f"Linked destinations cannot be edited: {destination}")
        if duplicate and not os.path.isfile(destination):
            raise ValueError(f"Duplicate destination must be an existing file: {destination}")
        if os.path.exists(destination) and os.path.samefile(source, destination):
            raise ValueError("Source and destination refer to the same file.")
        documents = _documents(source)
        documents.update(_documents(destination))
        source_tags = _tags_from_documents(source, documents)
        destination_tags = _tags_from_documents(destination, documents)
        assignments = {}
        if source_tags:
            assignments[os.path.abspath(destination)] = sorted(set(source_tags + destination_tags))
            if not copy:
                assignments[os.path.abspath(source)] = []
        plan = TagEdit(assignments, documents)
        if not duplicate:
            if os.path.exists(destination):
                raise FileExistsError(destination)
            if copy:
                shutil.copy2(source, destination)
            else:
                shutil.move(source, destination)
        elif not copy:
            os.remove(source)
        try:
            plan.commit()
        except (OSError, ValueError) as error:
            try:
                if not duplicate:
                    if copy:
                        os.remove(destination)
                    else:
                        shutil.move(destination, source)
                elif not copy:
                    shutil.copy2(destination, source)
            except OSError as rollback_error:
                raise OSError(
                    f"Tag save failed ({error}); audio rollback failed from {destination} "
                    f"to {source}: {rollback_error}. Sidecar backups: {plan.backups}"
                ) from error
            raise
        return source_tags

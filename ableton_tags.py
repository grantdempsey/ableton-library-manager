import os
import errno
import base64
import hashlib
import json
import stat
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
                    if getattr(self, "_transfer_edit", False):
                        _transfer_checkpoint("sidecar_written")
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


def transfer_sample(source, destination, copy=False, duplicate=False, *, application=None, reconcile=None):
    """Stage audio/tags, then reconcile application state before removing the journal."""
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
        if duplicate and not _same_sample_content(source, destination):
            raise ValueError("Duplicate files must have identical contents; no audio or tags were changed.")
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
        if not duplicate and os.path.lexists(destination):
            raise FileExistsError(destination)
        if application is not None and reconcile is None:
            raise ValueError("Application transfers require an index/undo reconciliation handler.")
        journal_path, journal = _prepare_transfer(source, destination, copy, duplicate, plan, application)
        try:
            if reconcile is not None:
                reconcile(journal, "validate")
            _transfer_checkpoint("prepared")
            stage = journal["stage"]
            _copy_sample(source, stage)
            journal["stage_identity"] = _transfer_identity(stage)
            _save_transfer(journal_path, journal, "staged")
            if not duplicate:
                _publish_sample(stage, destination)
            _save_transfer(journal_path, journal, "published")
            if not _same_sample_content(source, destination):
                raise ValueError(f"Audio changed during staged transfer: {source}")
            plan._transfer_edit = True
            plan.commit()
            _save_transfer(journal_path, journal, "tagged")
            if _transfer_identity(source) != journal["source_identity"]:
                raise ValueError(f"Source changed before final removal: {source}")
            if not _same_sample_content(stage if os.path.exists(stage) else source, destination):
                raise ValueError(f"Destination changed before final removal: {destination}")
            if not copy:
                _remove_transfer_file(source)
            _save_transfer(journal_path, journal, "source_removed")
            _save_transfer(journal_path, journal, "committed")
        except (OSError, ValueError) as error:
            try:
                _recover_transfer(journal_path, reconcile=reconcile)
            except (OSError, ValueError) as rollback_error:
                raise OSError(
                    f"Transfer failed ({error}); audio rollback failed or metadata recovery needs review: "
                    f"{rollback_error}. Recovery journal: {journal_path}. Sidecar backups: {plan.backups}"
                ) from error
            raise
        if reconcile is not None:
            reconcile(journal, "committed")
            _transfer_checkpoint("application_reconciled")
        _clean_transfer(journal_path, journal)
        return source_tags


_RECOVERY_FOLDER = "ALM Transfer Recovery"


def _transfer_checkpoint(_phase):
    """Fault-injection boundary used by process-interruption regression fixtures."""


def _check_transfer_path(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        junction = (
            os.name == "nt" and os.path.lexists(part)
            and part.lstat().st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT
        )
        if part.is_symlink() or junction:
            raise ValueError(f"Linked transfer/recovery path is not supported: {part}")


def _transfer_identity(path):
    _check_transfer_path(path)
    with open(path, "rb") as handle:
        before = os.fstat(handle.fileno())
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
        after = os.fstat(handle.fileno())
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"File changed while checking transfer identity: {path}")
    return {
        "size": after.st_size, "sha256": digest, "modified_ns": after.st_mtime_ns,
        "device": after.st_dev, "inode": after.st_ino,
    }


def _same_transfer_audio(path, identity):
    actual = _transfer_identity(path)
    return (actual["size"], actual["sha256"]) == (identity["size"], identity["sha256"])


def _save_transfer(path, journal, phase):
    journal["phase"] = phase
    _atomic_write(Path(path), json.dumps(journal).encode("utf-8"))
    _transfer_checkpoint(phase)


def _prepare_transfer(source, destination, copy, duplicate, plan, application=None):
    source, destination = os.path.abspath(source), os.path.abspath(destination)
    _check_transfer_path(source)
    _check_transfer_path(destination)
    folder = Path(destination).parent / "Ableton Folder Info" / _RECOVERY_FOLDER
    _check_transfer_path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    source_folder = Path(source).parent / "Ableton Folder Info" / _RECOVERY_FOLDER
    _check_transfer_path(source_folder)
    pending = list(folder.glob("*.json")) + list(source_folder.glob("*.json"))
    if pending:
        raise ValueError(f"Interrupted transfers need recovery before writing this folder: {pending[0]}")
    token = uuid.uuid4().hex
    path = folder / f"{token}.json"
    journal = {
        "version": 1, "source": source, "destination": destination,
        "copy": copy, "duplicate": duplicate,
        "source_identity": _transfer_identity(source),
        "destination_identity": _transfer_identity(destination) if duplicate else None,
        "stage": str(folder / f"{token}.audio"), "stage_identity": None,
        "phase": "prepared",
        "application": application,
        "sidecars": [{
            "path": str(path),
            "original": base64.b64encode(plan.originals[path]).decode("ascii")
            if plan.originals[path] is not None else None,
            "intended": base64.b64encode(data).decode("ascii"),
        } for path, data in plan.changes.items()],
    }
    _atomic_write(path, json.dumps(journal).encode("utf-8"))
    return str(path), journal


def _publish_sample(stage, destination):
    try:
        os.link(stage, destination)
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP}:
            raise
        if os.name != "nt":
            raise OSError("This filesystem cannot publish staged files without replacing existing paths.") from error
        os.rename(stage, destination)


def _remove_transfer_file(path):
    _check_transfer_path(path)
    mode = os.stat(path).st_mode
    readonly = os.name == "nt" and not mode & stat.S_IWRITE
    if readonly:
        os.chmod(path, stat.S_IWRITE)
    try:
        os.unlink(path)
    except OSError:
        if readonly and os.path.exists(path):
            os.chmod(path, mode)
        raise


def _clean_transfer(path, journal):
    stage = journal["stage"]
    if os.path.lexists(stage):
        if journal["stage_identity"] is not None:
            identity = _transfer_identity(stage)
            expected = journal["stage_identity"]
            if (identity["size"], identity["sha256"], identity["device"], identity["inode"]) != (
                    expected["size"], expected["sha256"], expected["device"], expected["inode"]):
                raise ValueError(f"Staged recovery audio changed; journal retained: {stage}")
        mode = os.stat(stage).st_mode
        _remove_transfer_file(stage)
        if journal["phase"] == "committed" and os.path.exists(journal["destination"]):
            os.chmod(journal["destination"], mode)
        _transfer_checkpoint("cleanup_stage_removed")
    os.unlink(path)


def _recover_transfer(path, *, reconcile=None):
    _check_transfer_path(path)
    with open(path, encoding="utf-8") as handle:
        journal = json.load(handle)
    required = {"source", "destination", "stage", "sidecars", "source_identity",
                "destination_identity", "stage_identity", "copy", "duplicate", "phase", "version"}
    if not isinstance(journal, dict) or not required.issubset(journal) or journal["version"] != 1:
        raise ValueError(f"Unsupported transfer recovery journal: {path}")
    if (journal["phase"] not in {"prepared", "staged", "published", "tagged", "source_removed", "committed"}
            or type(journal["copy"]) is not bool or type(journal["duplicate"]) is not bool):
        raise ValueError(f"Invalid transfer recovery state: {path}")
    source, destination, stage = (journal[key] for key in ("source", "destination", "stage"))
    expected_folder = Path(destination).parent / "Ableton Folder Info" / _RECOVERY_FOLDER
    if (Path(path).parent != expected_folder or Path(stage) != Path(path).with_suffix(".audio")):
        raise ValueError(f"Recovery journal location does not match its transfer: {path}")
    for target in (source, destination, stage):
        _check_transfer_path(target)
    if _key(source) == _key(destination):
        raise ValueError(f"Recovery source and destination must differ: {path}")
    if journal.get("application") is not None and reconcile is None:
        raise ValueError("Recover this application transfer through Organize to reconcile its index and undo log.")
    if reconcile is not None:
        reconcile(journal, "validate")
    if os.path.isfile(stage) and journal["stage_identity"] is not None:
        identity = _transfer_identity(stage)
        expected = journal["stage_identity"]
        if (identity["size"], identity["sha256"], identity["device"], identity["inode"]) != (
                expected["size"], expected["sha256"], expected["device"], expected["inode"]):
            raise ValueError(f"Staged recovery audio changed; journal retained: {stage}")
    sidecars = []
    for record in journal["sidecars"]:
        sidecar = Path(record["path"])
        if (sidecar.suffix.lower() != ".xmp" or sidecar.parent.name != "Ableton Folder Info"
                or not any(sidecar.parent.parent in (Path(sample).parent, *Path(sample).parent.parents)
                           for sample in (source, destination))):
            raise ValueError(f"Invalid recovery sidecar path: {sidecar}")
        _check_transfer_path(sidecar)
        original = base64.b64decode(record["original"], validate=True) if record["original"] is not None else None
        intended = base64.b64decode(record["intended"], validate=True)
        actual = sidecar.read_bytes() if sidecar.exists() else None
        if actual not in (original, intended):
            raise ValueError(f"Metadata changed after interruption; recovery left in place: {sidecar}")
        sidecars.append((sidecar, original, intended, actual))
    if journal["phase"] == "committed":
        if not _same_transfer_audio(destination, journal["source_identity"]):
            raise ValueError(f"Committed destination changed; recovery retained: {destination}")
        if not journal["copy"] and os.path.lexists(source):
            raise ValueError(f"Committed move source path is occupied again; recovery retained: {source}")
        if reconcile is not None:
            reconcile(journal, "committed")
            _transfer_checkpoint("application_reconciled")
        _clean_transfer(path, journal)
        return
    source_exists = os.path.lexists(source)
    if source_exists and not _same_transfer_audio(source, journal["source_identity"]):
        raise ValueError(f"Original source path changed; recovery retained: {source}")
    destination_exists = os.path.lexists(destination)
    if destination_exists:
        identity = journal["destination_identity"] if journal["duplicate"] else journal["stage_identity"]
        actual = _transfer_identity(destination)
        if (identity is None or not _same_transfer_audio(destination, identity)
                or (actual["device"], actual["inode"]) != (identity["device"], identity["inode"])):
            raise ValueError(f"Destination changed or ownership is uncertain; recovery retained: {destination}")
    if not source_exists:
        if journal["copy"]:
            raise ValueError(f"Copy source is missing; recovery retained: {source}")
        recovery_audio = stage if os.path.isfile(stage) else destination
        if not os.path.isfile(recovery_audio) or not _same_transfer_audio(recovery_audio, journal["source_identity"]):
            raise ValueError(f"Original audio cannot be verified; recovery retained: {path}")
        os.makedirs(os.path.dirname(source), exist_ok=True)
        _copy_sample(recovery_audio, source)
        _transfer_checkpoint("recovery_audio_restored")
    for sidecar, original, intended, actual in reversed(sidecars):
        current = sidecar.read_bytes() if sidecar.exists() else None
        if current != actual:
            raise ValueError(f"Metadata changed during recovery; journal retained: {sidecar}")
        if current == intended:
            if original is None:
                sidecar.unlink()
            else:
                _atomic_write(sidecar, original)
            _transfer_checkpoint("recovery_sidecar_restored")
    if destination_exists and not journal["duplicate"]:
        _remove_transfer_file(destination)
        _transfer_checkpoint("recovery_destination_removed")
    if reconcile is not None:
        reconcile(journal, "rolled_back")
        _transfer_checkpoint("application_reconciled")
    _clean_transfer(path, journal)


def find_transfer_recovery(root):
    """Find journals without changing audio, sidecars, or the library index."""
    root = os.path.abspath(root)
    _check_transfer_path(root)
    if not os.path.isdir(root):
        raise ValueError(f"Choose an existing recovery library: {root}")
    journals = []
    def scan_error(error):
        raise error
    for directory, folders, _files in os.walk(root, onerror=scan_error):
        for folder in folders[:]:
            _check_transfer_path(os.path.join(directory, folder))
        if Path(directory).name == _RECOVERY_FOLDER and Path(directory).parent.name == "Ableton Folder Info":
            journals.extend(str(path) for path in sorted(Path(directory).glob("*.json")))
            folders[:] = []
    return sorted(journals)


def recover_transfers(paths, *, reconcile=None):
    """Roll interrupted transfers back, retaining changed/conflicting entries."""
    result = {"recovered": 0, "errors": []}
    with _WRITE_LOCK:
        for path in paths:
            try:
                _recover_transfer(path, reconcile=reconcile)
            except (OSError, ValueError, KeyError, TypeError) as error:
                result["errors"].append(f"{path}: {error}")
            else:
                result["recovered"] += 1
    return result


def _copy_sample(source, destination):
    """Only remove output created by this copy if writing or verification fails."""
    before = _sample_fingerprint(source)
    with open(destination, "xb") as output:
        try:
            with open(source, "rb") as input_file:
                shutil.copyfileobj(input_file, output)
            output.flush()
            os.fsync(output.fileno())
            if (_sample_fingerprint(source) != before
                    or not _same_sample_content(source, destination)):
                raise ValueError(f"Source changed or copied audio failed verification: {source}")
        except (OSError, ValueError):
            output.close()
            os.unlink(destination)
            raise
    try:
        shutil.copystat(source, destination)
    except OSError:
        os.unlink(destination)
        raise


def _same_sample_content(source, destination):
    with open(source, "rb") as first, open(destination, "rb") as second:
        if os.fstat(first.fileno()).st_size != os.fstat(second.fileno()).st_size:
            return False
        while chunk := first.read(1024 * 1024):
            if chunk != second.read(len(chunk)):
                return False
        return not second.read(1)


def _move_sample(source, destination):
    """Move without replacing a path created after destination planning."""
    if os.name == "nt":
        try:
            os.rename(source, destination)
            return
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise
        _copy_sample(source, destination)
    else:
        try:
            os.link(source, destination)
        except OSError as error:
            if error.errno not in {errno.EXDEV, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP}:
                raise
            _copy_sample(source, destination)
    try:
        os.unlink(source)
    except OSError:
        os.unlink(destination)
        raise

"""Build identity embedded in packaged apps; source runs are clearly marked."""
from datetime import datetime, timezone
import hashlib
import json
import platform
from pathlib import Path
import re
import subprocess
import sys

VERSION = "2.2.0-rc.7"


def source_paths(root):
    root = Path(root)
    return sorted(
        [p for p in root.iterdir() if p.is_file() and p.suffix in {".py", ".pyw"}]
        + [root / "requirements-build.txt", root / "README.md"],
        key=lambda p: p.name,
    )


def source_hash(root):
    digest = hashlib.sha256()
    for path in source_paths(root):
        contents = path.read_bytes()
        name = path.name.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big") + name)
        digest.update(len(contents).to_bytes(8, "big") + contents)
    return digest.hexdigest()


def create_metadata(root):
    root = Path(root)
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=root, check=True,
            capture_output=True, text=True,
        ).stdout)
    except (OSError, subprocess.SubprocessError):
        revision, dirty = None, None
    return {
        "schema": 1, "kind": "packaged", "version": VERSION, "source_sha256": source_hash(root),
        "source_manifest": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in source_paths(root)},
        "git_revision": revision, "git_dirty": dirty,
        "git_dirty_scope": "repository tracked and untracked non-ignored files",
        "built_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
    }


def metadata():
    if not getattr(sys, "frozen", False):
        return {"schema": 1, "kind": "development", "description": "Development source run"}
    path = Path(sys._MEIPASS) / "build_info.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != 1
            or data.get("kind") != "packaged"
            or ("version" in data and (
                not isinstance(data["version"], str)
                or not re.fullmatch(r"\d+\.\d+\.\d+(?:-rc\.\d+)?", data["version"])))
            or not {"git_revision", "git_dirty"} <= data.keys()
            or not isinstance(data.get("source_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", data["source_sha256"])
            or (data["git_dirty"] is not None and type(data["git_dirty"]) is not bool)
            or any(not isinstance(data.get(key), str) or not data[key]
                   for key in ("built_at_utc", "python", "platform"))
            or (data.get("git_revision") is not None
                and (not isinstance(data["git_revision"], str)
                     or not re.fullmatch(r"[0-9a-f]{40,64}", data["git_revision"])))):
        raise ValueError(f"Invalid packaged build identity: {path}")
    return data


def display_version():
    data = metadata()
    if data["kind"] == "development":
        return "Development source"
    revision = data.get("git_revision")
    version = f"v{data['version']} · " if data.get("version") else ""
    suffix = " (dirty)" if data.get("git_dirty") else (" (git status unknown)" if data.get("git_dirty") is None else "")
    return version + f"Build {data['source_sha256'][:12]}" + (f" · git {revision[:12]}" if revision else "") + suffix

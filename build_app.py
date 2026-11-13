"""Build a fresh isolated artifact without touching running apps or used output."""
from pathlib import Path
import json
import os
import subprocess
import sys
import uuid

import build_info
import housekeeping


def run_production_compiler_pipeline():
    root = Path(__file__).resolve().parent
    output_root = root / "release_builds"
    output_root.mkdir(exist_ok=True)
    _, cleanup_errors = housekeeping.clean_candidates(output_root)
    for error in cleanup_errors:
        print(f"Candidate cleanup skipped: {error}", file=sys.stderr)
    candidate_id = uuid.uuid4().hex
    candidate = output_root / ("candidate-" + candidate_id)
    lock = output_root / ".candidate-locks" / (candidate_id + ".lock")
    with housekeeping.exclusive_lock(lock, blocking=True) as acquired:
        if not acquired:
            raise OSError("Could not lock build candidate")
        candidate.mkdir()
        marker = candidate / ".alm-candidate.json"
        compiler_pid = None
        def mark(state):
            marker.write_text(json.dumps({
                "version": 2, "id": candidate_id, "state": state,
                "pid": os.getpid(), "compiler_pid": compiler_pid,
            }), encoding="utf-8")
        mark("building")
        try:
            identity = build_info.create_metadata(root)
            metadata_file = candidate / "build_info.json"
            metadata_file.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
            command = [
                sys.executable, "-m", "PyInstaller", "--onedir", "--windowed",
                "--name=AbletonLibraryManager",
                "--distpath", str(candidate / "dist"),
                "--workpath", str(candidate / "work"),
                "--specpath", str(candidate),
                "--add-data", f"{root / 'README.md'}{os.pathsep}.",
                "--add-data", f"{metadata_file}{os.pathsep}.",
                str(root / "AbletonLibraryManager.pyw"),
            ]
            print(f"Building isolated candidate at {candidate}", flush=True)
            compiler = subprocess.Popen(command, cwd=root)
            compiler_pid = compiler.pid
            mark("building")
            returncode = compiler.wait()
            if returncode:
                raise subprocess.CalledProcessError(returncode, command)
            if build_info.source_hash(root) != identity["source_sha256"]:
                raise RuntimeError("Source changed during build; candidate is not valid")
            mark("complete")
        except BaseException:
            mark("failed")
            raise
    artifact = "AbletonLibraryManager.app" if sys.platform == "darwin" else "AbletonLibraryManager"
    print(f"Build complete: {candidate / 'dist' / artifact}")
    print("Smoke-test a copy. Inspect the final archive for private/runtime data before publication.")
    return candidate


if __name__ == "__main__":
    try:
        run_production_compiler_pipeline()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        sys.exit(1)

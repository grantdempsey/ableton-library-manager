"""Native macOS startup/quit smoke in disposable homes, not Live acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("This smoke must run on native macOS.")
    application = args.application.resolve(strict=True)
    executable = application / "Contents" / "MacOS" / "AbletonLibraryManager"
    if not executable.is_file():
        parser.error("Expected an AbletonLibraryManager.app bundle.")
    forbidden = {"library_config.json", "library_assets.db", "saved_searches.json", "Options.txt"}
    for path in application.rglob("*"):
        if path.name in forbidden or path.suffix in {".bak", ".xmp"}:
            raise RuntimeError(f"Runtime/private state in app: {path}")
    results = []
    with tempfile.TemporaryDirectory(prefix="alm-macos-smoke-") as directory:
        root = Path(directory)
        for scenario in ("fresh", "upgrade"):
            fixture = root / scenario
            home = fixture / "home"
            library = home / "Music" / "Ableton" / "User Library"
            library.mkdir(parents=True)
            support = home / "Library" / "Application Support" / "AbletonLibraryManager"
            support.mkdir(parents=True)
            profile = support / "library_config.json"
            if scenario == "upgrade":
                profile.write_text(json.dumps({
                    "DRUM_KEYWORDS": {}, "RULE_METADATA": {},
                    "XO_CUSTOM_TYPES": {"Preserved": ["keep"]},
                }), encoding="utf-8")
            copy = fixture / "AbletonLibraryManager.app"
            shutil.copytree(application, copy, symlinks=True)
            environment = dict(os.environ, HOME=str(home))
            for name in ("OneDrive", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PYTHONHOME", "PYTHONPATH"):
                environment.pop(name, None)
            owned_executable = copy / "Contents" / "MacOS" / executable.name
            log = fixture / "startup.log"
            with log.open("wb") as output:
                process = subprocess.Popen(
                    [str(owned_executable)], cwd="/", env=environment,
                    stdout=output, stderr=subprocess.STDOUT,
                )
                try:
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline and process.poll() is None:
                        if profile.is_file() and (support / "library_assets.db").is_file():
                            break
                        time.sleep(0.1)
                    time.sleep(2)
                    if process.poll() is not None or not profile.is_file() or not (support / "library_assets.db").is_file():
                        raise RuntimeError(f"{scenario} startup failed: {log.read_text(errors='replace')}")
                    data = json.loads(profile.read_text(encoding="utf-8"))
                    if scenario == "upgrade" and data.get("XO_CUSTOM_TYPES") != {"Preserved": ["keep"]}:
                        raise RuntimeError("Legacy profile settings were not preserved.")
                    subprocess.run(
                        [
                            "osascript", "-l", "JavaScript", "-e",
                            "ObjC.import('AppKit'); "
                            f"var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier({process.pid}); "
                            "if (!app.terminate) { throw new Error('Owned app refused native Quit'); }",
                        ],
                        check=True, timeout=15, env=environment,
                    )
                    code = process.wait(timeout=20)
                    if code != 0:
                        raise RuntimeError(f"{scenario} exit code {code}: {log.read_text(errors='replace')}")
                    text = log.read_text(errors="replace")
                    if any(marker in text for marker in ("Traceback (most recent call last)", "Exception in thread", "Fatal Python error")):
                        raise RuntimeError(f"{scenario} runtime exception: {text}")
                    results.append({"scenario": scenario, "startup": "passed", "native_quit_exit": code})
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
    print(json.dumps({
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "scenarios": results,
        "limits": "Native process startup, writable per-user state and Quit only; no native input, Live writes, signing or notarization certification.",
    }, indent=2))


if __name__ == "__main__":
    main()

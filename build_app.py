"""Build a fresh isolated artifact without touching running apps or used output."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def run_production_compiler_pipeline():
    root = Path(__file__).resolve().parent
    output_root = root / "release_builds"
    output_root.mkdir(exist_ok=True)
    candidate = Path(tempfile.mkdtemp(prefix="candidate-", dir=output_root))
    command = [
        sys.executable, "-m", "PyInstaller", "--onedir", "--windowed",
        "--name=AbletonLibraryManager",
        "--distpath", str(candidate / "dist"),
        "--workpath", str(candidate / "work"),
        "--specpath", str(candidate),
        "--add-data", f"{root / 'README.md'}{os.pathsep}.",
        str(root / "AbletonLibraryManager.pyw"),
    ]
    print(f"Building isolated candidate at {candidate}", flush=True)
    subprocess.run(command, cwd=root, check=True)
    artifact = "AbletonLibraryManager.app" if sys.platform == "darwin" else "AbletonLibraryManager"
    print(f"Build complete: {candidate / 'dist' / artifact}")
    print("Smoke-test a copy. Inspect the final archive for private/runtime data before publication.")
    return candidate


if __name__ == "__main__":
    try:
        run_production_compiler_pipeline()
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Build failed: {error}", file=sys.stderr)
        sys.exit(1)

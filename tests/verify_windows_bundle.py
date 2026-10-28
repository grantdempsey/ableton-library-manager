"""Run disposable workflow fixtures against a native executable's bundled code.

This complements native executable startup smoke; it is not mouse/keyboard
automation of the running executable or Live-side acceptance.
"""
import argparse
import importlib.abc
import importlib.machinery
import importlib.util
import marshal
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

from PyInstaller.archive.readers import CArchiveReader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    args = parser.parse_args()
    package = args.package.resolve(strict=True)
    if package.suffix == ".app":
        executable = package / "Contents" / "MacOS" / "AbletonLibraryManager"
        internal = package / "Contents" / "Resources"
    else:
        executable = package / "AbletonLibraryManager.exe"
        internal = package / "_internal"
    archive = CArchiveReader(str(executable))
    bundled = archive.open_embedded_archive("PYZ.pyz")
    root = Path(__file__).resolve().parents[1]
    local_names = {path.stem for path in root.glob("*.py")}
    loaded = set()

    class BundleLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path=None, target=None):
            if fullname not in local_names:
                return None
            if fullname not in bundled.toc:
                raise ModuleNotFoundError(f"Local production module missing from bundle: {fullname}")
            return importlib.util.spec_from_loader(fullname, self)

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            module.__file__ = str(internal / (module.__name__ + ".py"))
            loaded.add(module.__name__)
            exec(bundled.extract(module.__name__), module.__dict__)

    class EntryLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            if fullname == "release_acceptance_app":
                loaded.add("AbletonLibraryManager")
                return marshal.loads(archive.extract("AbletonLibraryManager"))
            return super().get_code(fullname)

    finder = BundleLoader()
    sys.meta_path.insert(0, finder)
    sys.path.insert(0, str(root / "tests"))
    for variable, folder in (("TCL_LIBRARY", "_tcl_data"), ("TK_LIBRARY", "_tk_data")):
        data = internal / folder
        if data.is_dir():
            os.environ[variable] = str(data)
        else:
            print(f"No external {folder}; using host Tcl/Tk for fixtures. "
                  "Native smoke must verify embedded Tcl 9 or macOS frameworks.")
    suites = (
        "test_release_acceptance",
        "test_release_blockers",
        "test_backup_and_undo",
        "test_rules_transactions",
        "test_live_tag_sync",
        "test_integration_workflow",
        "test_ableton_tags",
        "test_advanced_safety",
        "test_library_inspector",
        "test_rule_suggester",
        "test_tag_evidence",
    )
    try:
        with mock.patch.object(importlib.machinery, "SourceFileLoader", EntryLoader):
            suite = unittest.defaultTestLoader.loadTestsFromNames(suites)
            result = unittest.TextTestRunner(verbosity=1).run(suite)
        required = {
            "AbletonLibraryManager", "ableton_tags", "sorter_engine", "tab_tags",
            "live_tag_batch", "tab_experimental", "rule_suggester", "tag_evidence",
        }
        missing = required - loaded
        if missing:
            raise RuntimeError(f"Required bundled modules were not exercised: {sorted(missing)}")
        print(f"Exercised {len(loaded)} production modules from the executable: {', '.join(sorted(loaded))}")
        return 0 if result.wasSuccessful() else 1
    finally:
        sys.meta_path.remove(finder)


if __name__ == "__main__":
    sys.exit(main())

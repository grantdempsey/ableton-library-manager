import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import build_app
import build_info


class BuildInfoTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="identity-test-", dir=Path(__file__).parent)
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)
        for name in ("README.md", "requirements-build.txt", "app.py"):
            (self.root / name).write_text(name, encoding="utf-8")

    def test_hash_captures_source_bytes_and_filenames(self):
        original = build_info.source_hash(self.root)
        (self.root / "app.py").write_text("different", encoding="utf-8")
        self.assertNotEqual(original, build_info.source_hash(self.root))
        after = build_info.source_hash(self.root)
        (self.root / "app.py").rename(self.root / "renamed.py")
        self.assertNotEqual(after, build_info.source_hash(self.root))

    def test_build_identity_captures_hash_and_metadata(self):
        data = build_info.create_metadata(self.root)
        self.assertEqual(build_info.source_hash(self.root), data["source_sha256"])
        self.assertEqual("packaged", data["kind"])
        for key in ("built_at_utc", "python", "platform"):
            self.assertTrue(data[key])
        self.assertEqual({"app.py", "README.md", "requirements-build.txt"}, set(data["source_manifest"]))
        self.assertIn("untracked", data["git_dirty_scope"])

    def test_source_run_is_identified_as_development(self):
        with mock.patch.object(build_info.sys, "frozen", False, create=True):
            self.assertEqual("development", build_info.metadata()["kind"])
            self.assertIn("Development", build_info.display_version())

    def test_packaged_identity_and_missing_or_invalid_metadata(self):
        data = {"schema": 1, "kind": "packaged", "source_sha256": "a" * 64,
                "git_revision": "b" * 40, "git_dirty": True,
                "built_at_utc": "2026-01-01T00:00:00+00:00",
                "python": "3.14", "platform": "Windows"}
        path = self.root / "build_info.json"
        path.write_text(json.dumps(data))
        with mock.patch.object(build_info.sys, "frozen", True, create=True), \
             mock.patch.object(build_info.sys, "_MEIPASS", str(self.root), create=True):
            self.assertEqual(data, build_info.metadata())
            self.assertIn("dirty", build_info.display_version())
            data["version"] = build_info.VERSION
            path.write_text(json.dumps(data))
            self.assertIn(f"v{build_info.VERSION}", build_info.display_version())
            data["version"] = "not a version"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                build_info.metadata()
            path.write_text("{}")
            with self.assertRaises(ValueError):
                build_info.metadata()
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                build_info.metadata()

    def test_build_marks_candidate_and_embeds_identity_without_compiling(self):
        identity = {"source_sha256": "a" * 64}
        with mock.patch.object(build_app, "__file__", str(self.root / "build_app.py")), \
             mock.patch.object(build_info, "create_metadata", return_value=identity), \
             mock.patch.object(build_info, "source_hash", return_value=identity["source_sha256"]), \
             mock.patch.object(build_app.subprocess, "Popen") as compiler:
            compiler.return_value.pid = 123456
            compiler.return_value.wait.return_value = 0
            candidate = build_app.run_production_compiler_pipeline()
        marker = json.loads((candidate / ".alm-candidate.json").read_text())
        self.assertEqual("complete", marker["state"])
        self.assertEqual(identity, json.loads((candidate / "build_info.json").read_text()))
        command = compiler.call_args.args[0]
        self.assertIn(f"{candidate / 'build_info.json'}{build_app.os.pathsep}.", command)

    def test_changed_source_marks_build_failed(self):
        with mock.patch.object(build_app, "__file__", str(self.root / "build_app.py")), \
             mock.patch.object(build_info, "create_metadata", return_value={"source_sha256": "before"}), \
             mock.patch.object(build_info, "source_hash", return_value="after"), \
             mock.patch.object(build_app.subprocess, "Popen") as compiler:
            compiler.return_value.pid = 123456
            compiler.return_value.wait.return_value = 0
            with self.assertRaisesRegex(RuntimeError, "Source changed"):
                build_app.run_production_compiler_pipeline()
        candidate = next((self.root / "release_builds").glob("candidate-*"))
        self.assertEqual("failed", json.loads((candidate / ".alm-candidate.json").read_text())["state"])


if __name__ == "__main__":
    unittest.main()

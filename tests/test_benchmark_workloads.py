import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ableton_tags
import sorter_engine
from tests import benchmark_workloads


class LibraryBenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.library.mkdir()
        self.index = self.root / "assets.db"
        with patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.index)):
            for number in range(3):
                sample = self.library / f"kick {number}.wav"
                sample.write_bytes(b"audio")
                sorter_engine.index_asset(str(sample), str(self.library), "test", 1.0, [])
            ableton_tags.prepare_edit(
                [str(self.library / "kick 0.wav")], "Drums|Kick",
            ).commit()

    def test_real_library_benchmark_saves_report_without_mutating_inputs(self):
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        original_index = sorter_engine.ASSET_INDEX_FILE
        with patch.object(ableton_tags.TagEdit, "commit", side_effect=AssertionError("tag write")), patch.object(
            sorter_engine, "refresh_live_tag_cache", side_effect=AssertionError("cache write")
        ):
            report = benchmark_workloads.benchmark_library(
                self.library, self.index, "kick", repeats=2,
            )
        self.assertEqual(original_index, sorter_engine.ASSET_INDEX_FILE)
        self.assertEqual(before, {
            path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()
        })
        self.assertEqual(3, report["fixture"]["indexed_sounds"])
        self.assertEqual(3, report["measurements"]["warm_search_query"]["rows_fetched"])
        self.assertEqual(2, len(report["measurements"]["unchanged_sidecar_poll"]["samples_seconds"]))
        text = json.dumps(report)
        self.assertNotIn(str(self.library), text)
        self.assertNotIn("kick 0.wav", text)
        self.assertNotIn("Drums|Kick", text)
        output = self.root / "report.json"
        benchmark_workloads.save_report(report, output, self.library)
        self.assertEqual(report, json.loads(output.read_text()))

    def test_report_cannot_overwrite_existing_files_or_be_saved_inside_library(self):
        existing = self.root / "existing.json"
        existing.write_text("preserved")
        with self.assertRaises(FileExistsError):
            benchmark_workloads.save_report({}, existing, self.library)
        self.assertEqual("preserved", existing.read_text())
        with self.assertRaisesRegex(ValueError, "outside"):
            benchmark_workloads.save_report({}, self.library / "report.json", self.library)
        self.assertFalse((self.library / "report.json").exists())

    def test_missing_index_is_not_created(self):
        missing = self.root / "missing.db"
        with self.assertRaises(FileNotFoundError):
            benchmark_workloads.benchmark_library(self.library, missing)
        self.assertFalse(missing.exists())

    def test_cli_persists_read_only_report_and_requires_output(self):
        output = self.root / "performance.json"
        command = [
            sys.executable, str(Path(benchmark_workloads.__file__)),
            "--library", str(self.library), "--index", str(self.index), "--repeats", "2",
        ]
        missing_output = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(0, missing_output.returncode)
        self.assertIn("--library requires --report", missing_output.stderr)
        completed = subprocess.run(
            command + ["--report", str(output)], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual("read_only_library", json.loads(output.read_text())["mode"])
        self.assertEqual(json.loads(completed.stdout), json.loads(output.read_text()))

    def test_changed_metadata_aborts_without_refreshing_cache(self):
        with patch.object(
            benchmark_workloads.live_tag_sync, "poll_live_metadata",
            return_value=("pending", None),
        ), patch.object(sorter_engine, "_cache_ableton_tags") as cache:
            with self.assertRaisesRegex(ValueError, "metadata changed"):
                benchmark_workloads.benchmark_library(self.library, self.index)
        cache.assert_not_called()


if __name__ == "__main__":
    unittest.main()

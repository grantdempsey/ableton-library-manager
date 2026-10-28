import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import sorter_engine
import ableton_tags


class ImmediateWindow:
    """Minimal Tk-compatible scheduler for worker integration tests."""

    def after(self, _delay, callback):
        callback()


class LibraryWorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_file = sorter_engine.CONFIG_FILE
        self.original_index_file = sorter_engine.ASSET_INDEX_FILE
        self.original_drum_keywords = sorter_engine.DRUM_KEYWORDS
        self.original_rule_metadata = sorter_engine.RULE_METADATA
        sorter_engine.CONFIG_FILE = os.path.join(self.temp_dir.name, "library_config.json")
        sorter_engine.ASSET_INDEX_FILE = os.path.join(self.temp_dir.name, "library_assets.db")
        sorter_engine.DRUM_KEYWORDS = {r"\bkick(s)?\b": "Kicks"}
        sorter_engine.RULE_METADATA = {}
        with open(sorter_engine.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump({}, config_file)

    def tearDown(self):
        sorter_engine.CONFIG_FILE = self.original_config_file
        sorter_engine.ASSET_INDEX_FILE = self.original_index_file
        sorter_engine.DRUM_KEYWORDS = self.original_drum_keywords
        sorter_engine.RULE_METADATA = self.original_rule_metadata
        self.temp_dir.cleanup()

    def _run_sorter(self, source, destination, *, copy_mode, preview_only=False):
        completed = threading.Event()
        callbacks = []
        sorter = sorter_engine.ParallelLibrarySorter(
            source,
            destination,
            ImmediateWindow(),
            lambda _message: None,
            lambda stats, mode: (callbacks.append((stats, mode)), completed.set()),
            copy_mode=copy_mode,
            preview_only=preview_only,
        )
        sorter.start_parallel_sort()
        self.assertTrue(completed.wait(5), "sorter did not complete within the test timeout")
        self.assertEqual(1, len(callbacks))
        return sorter, callbacks[0]

    def test_preview_then_copy_indexes_source_and_destination(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        sample_path = os.path.join(source, "heavy_kick.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        preview, (preview_stats, preview_mode) = self._run_sorter(
            source, destination, copy_mode=True, preview_only=True
        )
        self.assertEqual(0, preview_stats["Errors/Skipped Files"])
        self.assertTrue(preview_mode)
        self.assertEqual(1, len(preview.preview_records))
        self.assertTrue(os.path.exists(sample_path))

        copy_sorter, (copy_stats, copy_mode) = self._run_sorter(
            source, destination, copy_mode=True
        )
        self.assertEqual(0, copy_stats["Errors/Skipped Files"])
        self.assertTrue(copy_mode)
        destination_path = os.path.join(
            destination, "Samples", "One-Shots", "Kicks", "heavy_kick.wav"
        )
        self.assertTrue(os.path.exists(sample_path))
        self.assertTrue(os.path.exists(destination_path))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(sample_path))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(destination_path))
        self.assertEqual([], copy_sorter.operation_errors)

    def test_preview_then_move_migrates_index_and_removes_source(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        sample_path = os.path.join(source, "heavy_kick.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        self._run_sorter(source, destination, copy_mode=True, preview_only=True)
        sorter, (stats, copy_mode) = self._run_sorter(
            source, destination, copy_mode=False
        )

        destination_path = os.path.join(
            destination, "Samples", "One-Shots", "Kicks", "heavy_kick.wav"
        )
        self.assertEqual(0, stats["Errors/Skipped Files"])
        self.assertFalse(copy_mode)
        self.assertFalse(os.path.exists(sample_path))
        self.assertTrue(os.path.exists(destination_path))
        self.assertIsNone(sorter_engine.get_indexed_asset(sample_path))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(destination_path))
        self.assertEqual([], sorter.operation_errors)

    def test_organize_removes_externally_deleted_index_records(self):
        library = os.path.join(self.temp_dir.name, "library")
        os.makedirs(library)
        path = os.path.join(library, "deleted.wav")
        with open(path, "wb") as handle:
            handle.write(b"sample")
        sorter_engine.index_asset(path, library, "test", 1.0, ["favorite"])
        os.remove(path)

        sorter, (stats, _mode) = self._run_sorter(
            library, library, copy_mode=False
        )

        self.assertEqual(0, stats["Errors/Skipped Files"])
        self.assertEqual([], sorter.operation_errors)
        self.assertEqual(0, sorter_engine.count_indexed_assets(library))
        self.assertEqual([], sorter_engine.get_asset_tags(path))

    def test_move_then_undo_preserves_live_tags_and_cache(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        path = os.path.join(source, "heavy_kick.wav")
        with open(path, "wb") as handle:
            handle.write(b"sample")
        ableton_tags.prepare_edit([path], "Sounds|Kick|Shared").commit()
        sorter_engine.index_existing_library(source)

        sorter, (stats, _mode) = self._run_sorter(source, destination, copy_mode=False)
        moved = os.path.join(destination, "Samples", "One-Shots", "Kicks", "heavy_kick.wav")
        self.assertEqual(0, stats["Errors/Skipped Files"])
        self.assertEqual([], sorter.operation_errors)
        self.assertEqual(["Sounds|Kick|Shared"], ableton_tags.sample_tags(moved))
        self.assertEqual([], ableton_tags.sample_tags(path))
        self.assertEqual(
            ["Sounds|Kick|Shared"], sorter_engine.get_indexed_asset(moved)["ableton_tags"]
        )
        result = sorter_engine.undo_move_log(sorter.move_log_path)
        self.assertEqual(1, result["restored"])
        self.assertEqual([], result["errors"])
        self.assertEqual(["Sounds|Kick|Shared"], ableton_tags.sample_tags(path))
        self.assertEqual([], ableton_tags.sample_tags(moved))
        self.assertEqual(
            ["Sounds|Kick|Shared"], sorter_engine.get_indexed_asset(path)["ableton_tags"]
        )
        record = sorter_engine.get_indexed_asset(path)
        self.assertEqual(os.path.basename(path), record["filename"])
        self.assertEqual(os.path.dirname(path), record["destination"])

    def test_undo_reports_cache_failure_without_partial_index_update(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        path = os.path.join(source, "heavy_kick.wav")
        with open(path, "wb") as handle:
            handle.write(b"sample")
        ableton_tags.prepare_edit([path], "Sounds|Shared").commit()
        sorter, (_stats, _mode) = self._run_sorter(source, destination, copy_mode=False)
        moved = os.path.join(destination, "Samples", "One-Shots", "Kicks", "heavy_kick.wav")
        with mock.patch.object(sorter_engine, "_cache_ableton_tags", side_effect=ValueError("bad metadata")):
            result = sorter_engine.undo_move_log(sorter.move_log_path)
        self.assertEqual(1, result["restored"])
        self.assertIn("File restored but index update failed", result["errors"][0])
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(["Sounds|Shared"], ableton_tags.sample_tags(path))
        self.assertIsNone(sorter_engine.get_indexed_asset(path))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(moved))
        self.assertTrue(os.path.isfile(sorter.move_log_path))

    def test_copy_and_duplicate_merge_preserve_live_tags(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        path = os.path.join(source, "heavy_kick.wav")
        with open(path, "wb") as handle:
            handle.write(b"sample")
        ableton_tags.prepare_edit([path], "Sounds|Source").commit()
        _sorter, (stats, _mode) = self._run_sorter(source, destination, copy_mode=True)
        copied = os.path.join(destination, "Samples", "One-Shots", "Kicks", "heavy_kick.wav")
        self.assertEqual(0, stats["Errors/Skipped Files"])
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(path))
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(copied))
        ableton_tags.prepare_edit([copied], "Character|Destination").commit()
        sorter, (stats, _mode) = self._run_sorter(source, destination, copy_mode=False)
        self.assertEqual(0, stats["Errors/Skipped Files"])
        self.assertFalse(os.path.exists(path))
        self.assertEqual(
            ["Character|Destination", "Sounds|Source"], ableton_tags.sample_tags(copied)
        )
        self.assertEqual(
            ["Character|Destination", "Sounds|Source"],
            sorter_engine.get_indexed_asset(copied)["ableton_tags"]
        )
        self.assertEqual([], sorter.operation_errors)

    def test_repair_preserves_live_tags_and_index(self):
        source = os.path.join(self.temp_dir.name, "library", "Samples", "Samples")
        destination = os.path.join(self.temp_dir.name, "library", "Samples")
        os.makedirs(source)
        path = os.path.join(source, "heavy_kick.wav")
        target = os.path.join(destination, "heavy_kick.wav")
        with open(path, "wb") as handle:
            handle.write(b"sample")
        ableton_tags.prepare_edit([path], "Sounds|Kick").commit()
        sorter_engine.index_existing_library(source)
        result = sorter_engine.repair_nested_folder_files([
            {"source": path, "destination": target}
        ])
        self.assertEqual({"moved": 1, "skipped": 0, "errors": []}, result)
        self.assertEqual(["Sounds|Kick"], ableton_tags.sample_tags(target))
        self.assertEqual(["Sounds|Kick"], sorter_engine.get_indexed_asset(target)["ableton_tags"])
        self.assertIsNone(sorter_engine.get_indexed_asset(path))


if __name__ == "__main__":
    unittest.main()

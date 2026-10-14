import json
import os
import tempfile
import threading
import unittest

import sorter_engine


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


if __name__ == "__main__":
    unittest.main()

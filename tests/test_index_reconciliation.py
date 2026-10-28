import os
import tempfile
import unittest
from unittest import mock

import sorter_engine


class IndexReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = mock.patch.object(
            sorter_engine, "ASSET_INDEX_FILE",
            os.path.join(self.temp_dir.name, "assets.db")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.library = os.path.join(self.temp_dir.name, "Library_100%")
        os.makedirs(self.library)

    def index_file(self, directory, filename, tags):
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, filename)
        with open(path, "wb") as handle:
            handle.write(b"sound")
        sorter_engine.index_asset(path, directory, "test", 1.0, tags)
        return path

    def test_rescan_removes_deleted_records_and_tags_only_inside_library(self):
        kept = self.index_file(self.library, "kept.wav", ["favorite", "keep"])
        deleted = self.index_file(self.library, "deleted.wav", ["deleted-tag"])
        outside = self.index_file(self.library + "-other", "outside.wav", ["outside"])
        os.remove(deleted)
        os.remove(outside)

        self.assertEqual(1, sorter_engine.index_existing_library(self.library))
        self.assertEqual(1, sorter_engine.count_indexed_assets(self.library))
        self.assertEqual([kept], [
            item["path"] for item in
            sorter_engine.list_indexed_assets(library_root=self.library)
        ])
        self.assertIsNone(sorter_engine.get_indexed_asset(deleted))
        self.assertEqual([], sorter_engine.get_asset_tags(deleted))
        self.assertEqual(["favorite"], sorter_engine.get_asset_tags(kept))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(outside))
        self.assertEqual(
            [("favorite", 1)],
            sorter_engine.list_indexed_tags(self.library)
        )

    def test_unavailable_root_does_not_remove_records(self):
        path = self.index_file(self.library, "kept.wav", ["favorite"])
        os.rename(self.library, self.library + "-offline")
        with self.assertRaises(OSError):
            sorter_engine.index_existing_library(self.library)
        self.assertIsNotNone(sorter_engine.get_indexed_asset(path))

    def test_rescan_keeps_existing_files_in_skipped_directories(self):
        directory = os.path.join(self.library, "Skipped")
        path = self.index_file(directory, "kept.wav", ["favorite"])
        with mock.patch.object(sorter_engine, "IGNORED_DIRECTORIES", ["Skipped"]):
            self.assertEqual(0, sorter_engine.index_existing_library(self.library))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(path))
        self.assertEqual(["favorite"], sorter_engine.get_asset_tags(path))

    def test_inaccessible_file_reports_error_and_preserves_records(self):
        path = self.index_file(self.library, "kept.wav", ["favorite"])
        real_stat = os.stat

        def guarded_stat(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError("File is inaccessible")
            return real_stat(candidate, *args, **kwargs)

        with mock.patch.object(sorter_engine.os, "stat", side_effect=guarded_stat):
            with self.assertRaises(PermissionError):
                sorter_engine.index_existing_library(self.library)
        self.assertIsNotNone(sorter_engine.get_indexed_asset(path))


if __name__ == "__main__":
    unittest.main()

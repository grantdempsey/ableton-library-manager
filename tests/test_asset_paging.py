import os
import unittest
from unittest import mock

import sorter_engine


class AssetPagingTests(unittest.TestCase):
    def setUp(self):
        self.original_db = sorter_engine.ASSET_INDEX_FILE
        self.temp_dir = self._make_temp_dir()
        sorter_engine.ASSET_INDEX_FILE = os.path.join(self.temp_dir, "assets.db")

    def tearDown(self):
        sorter_engine.ASSET_INDEX_FILE = self.original_db
        self._cleanup_temp_dir()

    def _make_temp_dir(self):
        import tempfile
        return tempfile.mkdtemp()

    def _cleanup_temp_dir(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_asset_results_can_be_paged_without_the_old_cap(self):
        for index in range(3):
            path = os.path.join(self.temp_dir, f"sound_{index}.wav")
            with open(path, "wb") as sound_file:
                sound_file.write(b"audio")
            sorter_engine.index_asset(path, "Sounds", "test", 1.0, [])

        first = sorter_engine.list_indexed_assets(limit=2, offset=0)
        second = sorter_engine.list_indexed_assets(limit=2, offset=2)
        self.assertEqual(2, len(first))
        self.assertEqual(1, len(second))

    def test_path_capture_matches_all_browser_query_branches(self):
        library = os.path.join(self.temp_dir, "library")
        fixtures = (
            ("Loops", "kick_loop.wav", ["favorite", "shared", "bpm:120"]),
            ("One-Shots", "kick.wav", ["shared"]),
            ("MIDI", "notes.mid", ["shared"]),
            ("", "ignore.txt", ["shared"]),
        )
        for folder, filename, tags in fixtures:
            path = os.path.join(library, folder, filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"audio")
            sorter_engine.index_asset(path, os.path.dirname(path), "test", 1.0, tags)
        outside = os.path.join(self.temp_dir, "outside.wav")
        with open(outside, "wb") as handle:
            handle.write(b"audio")
        sorter_engine.index_asset(outside, self.temp_dir, "test", 1.0, [])
        for search, tag, favorites in (
            ("", "", False), ("type:loop", "", False), ("type:midi", "", False),
            ("type:one-shot", "shared", False), ("", "shared", False),
            ("", "", True), ("kick -loop", "shared", False),
            ("bpm:120", "shared", True),
        ):
            with self.subTest(search=search, tag=tag, favorites=favorites):
                kwargs = dict(
                    search_text=search, tag_filter=tag, favorites_only=favorites,
                    library_root=library, limit=-1
                )
                records = sorter_engine.list_indexed_assets(**kwargs)
                paths = sorter_engine.list_indexed_assets(**kwargs, paths_only=True)
                self.assertEqual(list(dict.fromkeys(row["path"] for row in records)), paths)
                self.assertFalse(any(path.endswith(".txt") for path in paths))
                self.assertNotIn(outside, paths)
        with mock.patch.object(sorter_engine, "_asset_rows_with_tags", wraps=sorter_engine._asset_rows_with_tags) as rows:
            paths = sorter_engine.list_indexed_assets(limit=-1, paths_only=True)
            self.assertTrue(paths)
            self.assertTrue(rows.call_args.args[2])

    def test_selection_summary_chunks_and_rejects_missing_paths(self):
        connection = sorter_engine._asset_index_connection()
        paths = [os.path.join(self.temp_dir, f"sample_{index}.wav") for index in range(1101)]
        with connection:
            connection.executemany(
                "INSERT INTO assets VALUES (?, ?, 1, 0, ?, 'test', 1, '')",
                [(path, os.path.basename(path), self.temp_dir) for path in paths]
            )
            connection.executemany(
                "INSERT INTO asset_tags VALUES (?, ?, 1, ?)",
                [(path, "ableton:Sounds|Shared", "ableton") for path in paths]
                + [(path, "shared-local", "personal") for path in paths]
                + [(paths[0], "ableton:Character|Some", "ableton")]
            )
        connection.close()
        summary = sorter_engine.summarize_asset_selection(paths + paths[:1])
        self.assertEqual({"Sounds|Shared": 1101, "Character|Some": 1}, summary["live_counts"])
        self.assertEqual(["shared-local"], summary["shared_personal_tags"])
        with self.assertRaisesRegex(ValueError, "no longer indexed"):
            sorter_engine.summarize_asset_selection(paths + ["missing.wav"])
        connect = sorter_engine._asset_index_connection
        def limited_connection():
            connection = connect()
            connection.setlimit(sorter_engine.sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 600)
            return connection
        with mock.patch.object(sorter_engine, "_asset_index_connection", side_effect=limited_connection):
            sorter_engine.bulk_update_asset_tags(paths, "batch")
            self.assertEqual(["batch", "shared-local"], sorter_engine.summarize_asset_selection(paths)["shared_personal_tags"])
            sorter_engine.bulk_update_asset_tags(paths, "batch", remove=True)
            self.assertEqual(["shared-local"], sorter_engine.summarize_asset_selection(paths)["shared_personal_tags"])
            for remove in (False, True):
                with self.assertRaisesRegex(ValueError, "no longer indexed"):
                    sorter_engine.bulk_update_asset_tags(
                        paths + [os.path.join(self.temp_dir, "zzz-missing.wav")],
                        "shared-local" if remove else "never-committed", remove=remove
                    )
            self.assertEqual(["shared-local"], sorter_engine.summarize_asset_selection(paths)["shared_personal_tags"])


if __name__ == "__main__":
    unittest.main()

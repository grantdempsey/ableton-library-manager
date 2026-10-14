import unittest
import os
import tempfile

import sorter_engine


class IndexableExtensionTests(unittest.TestCase):
    def test_audio_extensions_include_common_library_formats(self):
        for extension in (".wav", ".aiff", ".flac", ".mp3", ".ogg", ".m4a",
                          ".aac", ".wma", ".opus", ".caf"):
            self.assertIn(extension, sorter_engine.AUDIO_EXTS)

    def test_documents_are_not_indexable_audio(self):
        self.assertNotIn(".txt", sorter_engine.AUDIO_EXTS)
        self.assertNotIn(".pdf", sorter_engine.AUDIO_EXTS)

    def test_asset_browser_excludes_non_sound_index_records(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            for filename in ("kick.wav", "notes.txt", "metadata.json"):
                path = os.path.join(temp_dir, filename)
                with open(path, "wb") as asset_file:
                    asset_file.write(b"data")
                sorter_engine.index_asset(path, "Samples", "test", 1.0, ["test-tag"])

            results = sorter_engine.list_indexed_assets()
            self.assertEqual(["kick.wav"], [result["filename"] for result in results])
            self.assertEqual(1, sorter_engine.count_indexed_assets())
            self.assertEqual([("test-tag", 1)], sorter_engine.list_indexed_tags())
        sorter_engine.ASSET_INDEX_FILE = original_index

    def test_asset_browser_stays_inside_user_library_root(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            library_dir = os.path.join(temp_dir, "User Library")
            project_dir = os.path.join(temp_dir, "ableton-library-manager")
            os.makedirs(library_dir)
            os.makedirs(project_dir)
            for directory, filename in (
                (library_dir, "library-kick.wav"),
                (project_dir, "project-kick.wav"),
            ):
                path = os.path.join(directory, filename)
                with open(path, "wb") as asset_file:
                    asset_file.write(b"data")
                sorter_engine.index_asset(path, "Samples", "test", 1.0, ["test-tag"])

            results = sorter_engine.list_indexed_assets(library_root=library_dir)
            self.assertEqual(["library-kick.wav"], [item["filename"] for item in results])
            self.assertEqual(1, sorter_engine.count_indexed_assets(library_dir))
            self.assertEqual(
                [("test-tag", 1)],
                sorter_engine.list_indexed_tags(library_dir)
            )
        sorter_engine.ASSET_INDEX_FILE = original_index

    def test_tag_counts_follow_collection_filter(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            library_dir = os.path.join(temp_dir, "User Library")
            loop_dir = os.path.join(library_dir, "Loops")
            one_shot_dir = os.path.join(library_dir, "One-Shots")
            os.makedirs(loop_dir)
            os.makedirs(one_shot_dir)
            for directory, filename, tags in (
                (loop_dir, "loop.wav", ["category:Loops", "tempo"]),
                (one_shot_dir, "hit.wav", ["category:One-Shots", "impact"]),
            ):
                path = os.path.join(directory, filename)
                with open(path, "wb") as asset_file:
                    asset_file.write(b"data")
                sorter_engine.index_asset(path, directory, "test", 1.0, tags)

            self.assertEqual(
                [("category:Loops", 1), ("tempo", 1)],
                sorter_engine.list_indexed_tags(
                    library_dir, search_text="type:loop"
                )
            )
        sorter_engine.ASSET_INDEX_FILE = original_index

    def test_collection_tag_filter_returns_only_matching_assets(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            library_dir = os.path.join(temp_dir, "User Library")
            loop_dir = os.path.join(library_dir, "Loops")
            one_shot_dir = os.path.join(library_dir, "One-Shots")
            os.makedirs(loop_dir)
            os.makedirs(one_shot_dir)
            for directory, filename, tags in (
                (loop_dir, "loop.wav", ["tempo"]),
                (one_shot_dir, "hit.wav", ["tempo"]),
            ):
                path = os.path.join(directory, filename)
                with open(path, "wb") as asset_file:
                    asset_file.write(b"data")
                sorter_engine.index_asset(path, directory, "test", 1.0, tags)

            results = sorter_engine.list_indexed_assets(
                "type:loop", "tempo", library_root=library_dir
            )
            self.assertEqual(["loop.wav"], [item["filename"] for item in results])
            self.assertEqual(
                1,
                sorter_engine.count_indexed_assets(
                    library_dir, search_text="type:loop", tag_filter="tempo"
                )
            )
        sorter_engine.ASSET_INDEX_FILE = original_index

    def test_tag_counts_follow_filename_search(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            library_dir = os.path.join(temp_dir, "User Library")
            os.makedirs(library_dir)
            for filename, tags in (
                ("bright-kick.wav", ["kick", "bright"]),
                ("dark-snare.wav", ["snare", "dark"]),
            ):
                path = os.path.join(library_dir, filename)
                with open(path, "wb") as asset_file:
                    asset_file.write(b"data")
                sorter_engine.index_asset(path, library_dir, "test", 1.0, tags)

            self.assertEqual(
                [("bright", 1), ("kick", 1)],
                sorter_engine.list_indexed_tags(
                    library_dir, search_text="bright"
                )
            )
        sorter_engine.ASSET_INDEX_FILE = original_index

    def test_asset_tag_count_index_is_created(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            sorter_engine.list_indexed_tags()
            connection = sorter_engine.sqlite3.connect(sorter_engine.ASSET_INDEX_FILE)
            indexes = {
                row[1] for row in connection.execute("PRAGMA index_list(asset_tags)")
            }
            connection.close()
            self.assertIn("idx_asset_tags_enabled_tag_path", indexes)
        sorter_engine.ASSET_INDEX_FILE = original_index

    def test_refresh_indexer_discovers_existing_library_sounds(self):
        original_index = sorter_engine.ASSET_INDEX_FILE
        with tempfile.TemporaryDirectory() as temp_dir:
            sorter_engine.ASSET_INDEX_FILE = os.path.join(temp_dir, "assets.db")
            library_dir = os.path.join(temp_dir, "User Library")
            os.makedirs(os.path.join(library_dir, "Samples", "Loops"))
            for filename in ("one.wav", "two.mid", "ignore.txt"):
                path = os.path.join(library_dir, "Samples", "Loops", filename)
                with open(path, "wb") as asset_file:
                    asset_file.write(b"data")

            discovered = sorter_engine.index_existing_library(library_dir)

            self.assertEqual(2, discovered)
            self.assertEqual(2, sorter_engine.count_indexed_assets(library_dir))
            self.assertEqual(
                {"one.wav", "two.mid"},
                {item["filename"] for item in sorter_engine.list_indexed_assets(
                    library_root=library_dir
                )}
            )
            self.assertEqual(2, sorter_engine.index_existing_library(library_dir))
        sorter_engine.ASSET_INDEX_FILE = original_index

if __name__ == "__main__":
    unittest.main()

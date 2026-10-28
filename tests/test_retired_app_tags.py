import os
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import ableton_tags
import sorter_engine
import xo_filter


class RetiredAppTagsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = temporary.name
        patcher = mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.root, "index.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sample = os.path.join(self.root, "kick.wav")
        with open(self.sample, "wb") as handle:
            handle.write(b"unchanged audio")
        sorter_engine.index_asset(self.sample, self.root, "test", 1, ["category:Kicks", "name:kick"])
        connection = sorter_engine._asset_index_connection()
        with connection:
            connection.executemany(
                "INSERT INTO asset_tags VALUES (?, ?, ?, 'personal')",
                [(self.sample, tag, enabled) for tag, enabled in (
                    ("legacy-label", 1), ("type:loop", 1), ("drum:snare", 1), ("disabled-label", 0)
                )]
            )
        connection.close()

    def test_legacy_rows_are_dormant_in_all_read_paths_but_retained_on_disk(self):
        ableton_tags.prepare_edit([self.sample], "Genres|Live").commit()
        sorter_engine.refresh_live_tag_cache([self.sample])
        sorter_engine.add_asset_tag(self.sample, "favorite")
        visible = ["ableton:Genres|Live", "category:Kicks", "favorite", "name:kick"]
        self.assertEqual(visible, sorter_engine.get_asset_tags(self.sample))
        record = sorter_engine.get_indexed_asset(self.sample)
        self.assertEqual(visible, record["tags"])
        self.assertEqual([], record["disabled_tags"])
        self.assertNotIn("personal_tags", record)
        self.assertEqual(visible, sorter_engine.get_all_indexed_asset_tags()[self.sample])
        self.assertEqual(visible, sorter_engine.list_indexed_assets(library_root=self.root)[0]["tags"])
        self.assertEqual(visible, [tag for tag, _count in sorter_engine.list_indexed_tags(self.root)])
        self.assertEqual(
            {"live_counts": {"Genres|Live": 1}, "generated_counts": {"category:Kicks": 1, "name:kick": 1}},
            sorter_engine.summarize_asset_selection([self.sample])
        )
        for search in ("legacy-label", "tag:legacy-label", "anytag:legacy-label", "type:loop"):
            with self.subTest(search=search):
                self.assertEqual([], sorter_engine.list_indexed_assets(search_text=search, library_root=self.root))
                self.assertEqual([], sorter_engine.list_indexed_tags(self.root, search_text=search))
        self.assertEqual(0, sorter_engine.count_indexed_assets(self.root, tag_filter="legacy-label"))
        for search in ("-legacy-label", "-tag:legacy-label"):
            self.assertEqual(1, sorter_engine.count_indexed_assets(self.root, search_text=search))
        self.assertEqual(1, sorter_engine.count_indexed_assets(self.root, favorites_only=True))
        connection = sorter_engine._asset_index_connection()
        try:
            retained = connection.execute(
                "SELECT tag, enabled FROM asset_tags WHERE asset_path = ? AND tag != 'favorite' "
                "AND source = 'personal' ORDER BY tag", (self.sample,)
            ).fetchall()
        finally:
            connection.close()
        self.assertEqual(
            [("disabled-label", 0), ("drum:snare", 1), ("legacy-label", 1), ("type:loop", 1)], retained
        )

    def test_app_only_mutations_are_rejected_and_indexing_cannot_create_them(self):
        for mutate in (
            lambda: sorter_engine.add_asset_tag(self.sample, "new-label"),
            lambda: sorter_engine.remove_asset_tag(self.sample, "legacy-label"),
            lambda: sorter_engine.bulk_update_asset_tags([self.sample], "legacy-label"),
            lambda: sorter_engine.bulk_update_asset_tags([self.sample], "legacy-label", remove=True),
            lambda: sorter_engine.set_asset_tag_enabled(self.sample, "legacy-label", False),
        ):
            with self.assertRaisesRegex(ValueError, "App-only tags have been removed"):
                mutate()
        sorter_engine.index_asset(self.sample, self.root, "test", 1, ["new-label", "category:Kicks"])
        connection = sorter_engine._asset_index_connection()
        try:
            self.assertEqual(0, connection.execute(
                "SELECT COUNT(*) FROM asset_tags WHERE tag = 'new-label'"
            ).fetchone()[0])
            self.assertEqual(4, connection.execute(
                "SELECT COUNT(*) FROM asset_tags WHERE source = 'personal'"
            ).fetchone()[0])
        finally:
            connection.close()

    def test_xo_does_not_consult_legacy_type_or_instrument_overrides(self):
        with mock.patch.object(xo_filter, "apply_custom_types"):
            plan, stats = xo_filter.build_plan(self.root)
        self.assertEqual({"Kicks": [self.sample]}, plan)
        self.assertEqual(0, stats["loops_skipped"])
        with open(self.sample, "rb") as handle:
            self.assertEqual(b"unchanged audio", handle.read())

    def test_sorter_preview_ignores_stored_legacy_overrides(self):
        destination = os.path.join(self.root, "output")
        window = SimpleNamespace(after=lambda _delay, callback: callback())
        with mock.patch.object(sorter_engine, "DRUM_KEYWORDS", {r"\bkick\b": "Kicks"}), mock.patch.object(
            sorter_engine, "RULE_METADATA", {}
        ):
            sorter = sorter_engine.ParallelLibrarySorter(
                self.root, destination, window, lambda _text: None, lambda *_args: None,
                copy_mode=True, preview_only=True,
            )
            sorter.process_single_file(self.root, "kick.wav")
        self.assertEqual([], sorter.operation_errors)
        self.assertEqual(
            os.path.join(destination, "Samples", "One-Shots", "Kicks"),
            sorter.preview_records[0]["destination"]
        )
        self.assertEqual("filename_rule", sorter.preview_records[0]["reason"])

    def test_file_move_keeps_dormant_rows_without_exposing_them(self):
        moved = os.path.join(self.root, "moved.wav")
        os.replace(self.sample, moved)
        sorter_engine.index_asset(
            moved, self.root, "test", 1, sorter_engine.get_asset_tags(self.sample),
            previous_path=self.sample
        )
        self.assertNotIn("legacy-label", sorter_engine.get_asset_tags(moved))
        snapshot = sorter_engine._snapshot_indexed_asset(moved)
        self.assertIn(("legacy-label", 1, "personal"), snapshot["stored_tags"])
        self.assertIn(("disabled-label", 0, "personal"), snapshot["stored_tags"])
        self.assertIsNone(sorter_engine.get_indexed_asset(self.sample))

    def test_pre_removal_sidebar_cache_is_not_reused(self):
        fingerprint = sorter_engine._index_fingerprint()
        with open(sorter_engine._sidebar_cache_path(), "w", encoding="utf-8") as handle:
            json.dump({
                "version": 1, "fingerprint": fingerprint, "library_root": self.root,
                "static_counts": {}, "favorites": 0, "tags": [["legacy-label", 1]],
            }, handle)
        self.assertIsNone(sorter_engine.load_sidebar_snapshot(self.root))

    def test_generated_tag_enable_state_and_favorites_remain_supported(self):
        sorter_engine.set_asset_tag_enabled(self.sample, "name:kick", False)
        sorter_engine.add_asset_tag(self.sample, "favorite")
        self.assertEqual(["category:Kicks", "favorite"], sorter_engine.get_asset_tags(self.sample))
        sorter_engine.set_asset_tag_enabled(self.sample, "name:kick", True)
        sorter_engine.remove_asset_tag(self.sample, "favorite")
        self.assertEqual(["category:Kicks", "name:kick"], sorter_engine.get_asset_tags(self.sample))

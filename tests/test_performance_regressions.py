import os
import tempfile
import unittest
from unittest import mock

import sorter_engine
from tab_tags import TagsTab


class BrowserCountRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = mock.patch.object(
            sorter_engine,
            "ASSET_INDEX_FILE",
            os.path.join(self.temp_dir.name, "assets.db"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def _tab(**overrides):
        tab = object.__new__(TagsTab)
        tab._sidebar_loaded = True
        tab._cached_total_count = 82_215
        tab._active_collection = "All sounds"
        tab.favorites_only = False
        tab.active_tag_filter = ""
        for key, value in overrides.items():
            setattr(tab, key, value)
        return tab

    def test_unfiltered_all_sounds_reuses_loaded_sidebar_count(self):
        tab = self._tab()
        with mock.patch(
            "tab_tags.sorter_engine.count_indexed_assets"
        ) as count_assets:
            count = tab._count_browser_results(self.temp_dir.name, "")

        self.assertEqual(82_215, count)
        count_assets.assert_not_called()
        self.assertFalse(os.path.exists(sorter_engine.ASSET_INDEX_FILE))

    def test_filtered_or_unloaded_counts_still_query_the_index(self):
        cases = (
            ({"_sidebar_loaded": False}, "", "", False),
            ({}, " ", "", False),
            ({}, "kick", "", False),
            ({}, "", "category:kick", False),
            ({"favorites_only": True}, "", "", True),
            ({"_active_collection": "Loops"}, "type:loop", "", False),
        )
        for overrides, search_text, tag_filter, favorites_only in cases:
            with self.subTest(overrides=overrides, search_text=search_text):
                tab = self._tab(**overrides)
                tab.active_tag_filter = tag_filter
                with mock.patch(
                    "tab_tags.sorter_engine.count_indexed_assets",
                    return_value=17,
                ) as count_assets:
                    count = tab._count_browser_results(
                        self.temp_dir.name, search_text
                    )

                self.assertEqual(17, count)
                count_assets.assert_called_once_with(
                    self.temp_dir.name,
                    search_text,
                    tag_filter,
                    favorites_only,
                )

    def test_successful_rescan_invalidates_loaded_sidebar_count(self):
        tab = object.__new__(TagsTab)
        tab._refresh_running = True
        tab.rescan_button = mock.Mock()
        tab.filter_button = mock.Mock()
        tab._set_freshness = mock.Mock()
        tab._set_status = mock.Mock()
        tab._static_counts = {"All sounds": 82_215}
        tab._sidebar_loaded = True
        tab._page_index = 4
        tab._render_results = mock.Mock()

        tab._finish_refresh(1, None)

        self.assertFalse(tab._sidebar_loaded)
        tab._render_results.assert_called_once_with(refresh_sidebar=True)


if __name__ == "__main__":
    unittest.main()

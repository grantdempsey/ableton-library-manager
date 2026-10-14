import unittest
from unittest import mock

from tab_tags import TagsTab


class TagsBrowserStateTests(unittest.TestCase):
    def test_programmatic_filter_selection_is_guarded(self):
        tab = object.__new__(TagsTab)
        tab._updating_browser_filters = True
        tab.refresh = mock.Mock()
        tab.collection_list = mock.Mock()
        tab.tag_list = mock.Mock()

        tab._collection_selected(None)
        tab._tag_selected(None)

        tab.refresh.assert_not_called()

    def test_empty_tag_cache_does_not_mean_sidebar_is_unloaded(self):
        tab = object.__new__(TagsTab)
        tab._sidebar_loaded = True
        tab._sidebar_generation = 0
        tab._sidebar_loading = False
        tab._cached_tags = []
        tab._cached_tag_scope = ("", False, "")
        tab._active_collection = "All sounds"
        tab.favorites_only = False
        tab._updating_browser_filters = False
        tab._cached_total_count = 0
        tab._collection_counts = {}
        tab._asset_paths = {}
        tab._page_index = 0
        tab._page_size = 250
        tab.active_tag_filter = ""
        tab.search_var = mock.Mock()
        tab.search_var.get.return_value = ""
        tab.asset_tree = mock.Mock()
        tab.asset_tree.selection.return_value = []
        tab.asset_tree.get_children.return_value = []
        tab.page_label = mock.Mock()
        tab.total_label = mock.Mock()
        tab.previous_page_button = mock.Mock()
        tab.next_page_button = mock.Mock()
        tab.collection_list = mock.Mock()
        tab.tag_list = mock.Mock()
        tab._refresh_collections = mock.Mock()
        tab._show_selected_asset = mock.Mock()

        with mock.patch("tab_tags.sorter_engine.list_indexed_tags") as list_tags:
            with mock.patch.object(tab, "_load_sidebar_data") as load_sidebar:
                with mock.patch(
                    "tab_tags.sorter_engine.list_indexed_assets", return_value=[]
                ):
                    with mock.patch(
                        "tab_tags.sorter_engine.count_indexed_assets", return_value=0
                    ):
                        tab._render_results()

        load_sidebar.assert_not_called()
        list_tags.assert_not_called()

    def test_sidebar_data_counts_library_independently_of_cached_total(self):
        tab = object.__new__(TagsTab)
        tab._active_collection = "Loops"
        tab.favorites_only = True
        with mock.patch(
            "tab_tags.sorter_engine.count_indexed_assets", return_value=44099
        ) as count_assets, mock.patch(
            "tab_tags.sorter_engine.list_indexed_tags", return_value=[("kick", 3)]
        ) as list_tags, mock.patch(
            "tab_tags.sorter_engine.load_sidebar_snapshot", return_value=None
        ), mock.patch("tab_tags.sorter_engine.save_sidebar_snapshot"):
            data = tab._load_sidebar_data("library", "All sounds", False)

        self.assertEqual(data["total_count"], 44099)
        self.assertEqual(
            data["collection_counts"],
            {
                "All sounds": 44099,
                "Favorites": 44099,
                "Loops": 44099,
                "One-shots": 44099,
                "MIDI": 44099,
            },
        )
        self.assertEqual(data["tag_scope"], ("", False, ""))
        self.assertEqual(count_assets.call_count, 5)
        list_tags.assert_called_once_with(
            "library", search_text="", favorites_only=False
        )

    def test_stale_sidebar_result_is_not_rendered(self):
        tab = object.__new__(TagsTab)
        tab._sidebar_generation = 2
        tab._sidebar_loading = True
        tab._request_sidebar_load = mock.Mock()
        tab._finish_sidebar_load({"total_count": 1}, None, 1)

        tab._request_sidebar_load.assert_called_once()

    def test_tag_selection_does_not_mutate_collection_callback_state(self):
        tab = object.__new__(TagsTab)
        tab._updating_browser_filters = False
        tab.tag_list = mock.Mock()
        tab.collection_list = mock.Mock()
        tab.collection_list.curselection.return_value = []
        tab.tag_list.curselection.return_value = [0]
        tab.tag_list.get.return_value = "category:kick  (12)"
        tab._page_index = 3
        tab.favorites_only = True
        tab.active_tag_filter = ""
        tab._active_collection = "Loops"
        tab._safe_render_results = mock.Mock()

        tab._tag_selected(None)

        self.assertEqual(tab.active_tag_filter, "category:kick")
        self.assertFalse(tab.favorites_only)
        self.assertEqual(tab._active_collection, "Loops")
        self.assertEqual(tab._page_index, 0)
        tab.collection_list.selection_clear.assert_not_called()
        tab._safe_render_results.assert_called_once_with()
        self.assertFalse(tab._updating_browser_filters)

    def test_collection_selection_helper_keeps_callback_guard_active(self):
        tab = object.__new__(TagsTab)
        tab._updating_browser_filters = False
        tab._active_collection = ""
        tab.collection_list = mock.Mock()

        tab._set_collection_selection()

        tab.collection_list.selection_clear.assert_called_once_with(0, "end")
        tab.collection_list.selection_set.assert_not_called()
        self.assertFalse(tab._updating_browser_filters)

    def test_tag_release_selects_clicked_row_explicitly(self):
        tab = object.__new__(TagsTab)
        tab._updating_browser_filters = False
        tab.tag_list = mock.Mock()
        tab.tag_list.nearest.return_value = 4
        tab.tag_list.size.return_value = 10
        tab.tag_list.get.return_value = "category:kick  (12)"
        tab._apply_tag_filter = mock.Mock()

        tab._tag_released(mock.Mock(y=25))

        tab.tag_list.selection_clear.assert_called_once_with(0, "end")
        tab.tag_list.selection_set.assert_called_once_with(4)
        tab._apply_tag_filter.assert_called_once_with("category:kick  (12)")
        self.assertFalse(tab._updating_browser_filters)


if __name__ == "__main__":
    unittest.main()

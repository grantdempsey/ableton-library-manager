import gc
import os
import tempfile
import tkinter as tk
import unittest
from unittest import mock

import gui_theme
import sorter_engine
from tab_tags import TagsTab


class LibraryInspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for target, attribute, value in (
            (sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.temp_dir.name, "assets.db")),
            (gui_theme, "USER_LIBRARY_PATH", self.temp_dir.name),
        ):
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk display is unavailable: {error}")
        self.addCleanup(self.close_root)
        self.root.geometry("1020x620")
        self.tab = TagsTab(self.root)
        self.tab.pack(fill="both", expand=True)
        self.root.update()
        for method in ("_request_sidebar_load", "_draw_waveform"):
            patcher = mock.patch.object(self.tab, method)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.error_patcher = mock.patch("tab_tags.messagebox.showerror")
        self.show_error = self.error_patcher.start()
        self.addCleanup(self.error_patcher.stop)
        self.paths = []
        for filename, tags in (
            ("first.wav", ["shared", "only-first", "category:Kicks", "name:first"]),
            ("second.wav", ["shared", "category:Snares", "name:second"]),
        ):
            path = os.path.join(self.temp_dir.name, filename)
            with open(path, "wb") as handle:
                handle.write(b"unchanged sound")
            sorter_engine.index_asset(path, self.temp_dir.name, "test", 1.0, tags)
            self.paths.append(path)
        self.tab._render_results(load_sidebar=False)
        self.root.update()

    def close_root(self):
        self.root.destroy()
        gc.collect()

    def select(self, paths):
        items = [item for item, path in self.tab._asset_paths.items() if path in paths]
        self.tab.asset_tree.selection_set(items)
        self.root.update()

    def test_panes_resize_and_inspector_collapses_without_losing_selection(self):
        self.select(self.paths[:1])
        self.assertEqual(3, len(self.tab.browser_panes.panes()))
        before = self.tab.browser_panes.sash_coord(0)[0]
        self.tab.browser_panes.sash_place(0, before + 30, 0)
        self.root.update()
        self.assertGreater(self.tab.browser_panes.sash_coord(0)[0], before)
        self.assertEqual("normal", self.tab.add_tag_button.cget("state"))
        self.assertIs(self.tab.favorite_button.master, self.tab.unfavorite_button.master)
        self.assertTrue(self.tab.favorite_button.winfo_ismapped())
        self.assertGreater(self.tab.personal_tag_list.winfo_height(), 20)
        self.assertLess(
            self.tab.remove_tag_button.winfo_rootx() + self.tab.remove_tag_button.winfo_width(),
            self.root.winfo_rootx() + self.root.winfo_width()
        )
        self.tab.inspector_toggle.invoke()
        self.root.update()
        self.assertEqual(2, len(self.tab.browser_panes.panes()))
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        self.tab.inspector_toggle.invoke()
        self.root.update()
        self.assertEqual(3, len(self.tab.browser_panes.panes()))
        self.assertEqual(self.paths[:1], self.tab._selected_paths())

    def test_empty_selection_disables_editing_and_clears_waveform(self):
        self.select(self.paths[:1])
        self.tab.waveform_canvas.create_line(0, 0, 20, 20)
        self.select([])
        self.assertEqual("No sounds selected", self.tab.selection_count_var.get())
        for control in (
            self.tab.play_button, self.tab.favorite_button, self.tab.unfavorite_button,
            self.tab.add_tag_button, self.tab.remove_tag_button, self.tab.personal_tag_entry
        ):
            self.assertEqual("disabled", control.cget("state"))
        self.assertEqual((), self.tab.waveform_canvas.find_all())
        self.assertEqual(0, self.tab.personal_tag_list.size())

    def test_single_selection_inline_tagging_and_removal(self):
        self.select(self.paths[:1])
        self.assertEqual("1 sound selected", self.tab.selection_count_var.get())
        self.assertEqual(
            ("only-first", "shared"), self.tab.personal_tag_list.get(0, "end")
        )
        self.tab.new_tag_var.set("  Dark  ")
        self.tab.add_tag_button.invoke()
        self.root.update()
        self.assertIn("dark", sorter_engine.get_asset_tags(self.paths[0]))
        self.assertNotIn("dark", sorter_engine.get_asset_tags(self.paths[1]))
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        index = self.tab.personal_tag_list.get(0, "end").index("dark")
        self.tab.personal_tag_list.selection_set(index)
        self.tab._personal_tag_selected()
        self.assertEqual("dark", self.tab.new_tag_var.get())
        self.tab.remove_tag_button.invoke()
        self.root.update()
        self.assertNotIn("dark", sorter_engine.get_asset_tags(self.paths[0]))
        self.tab._request_sidebar_load.assert_called()
        self.show_error.assert_not_called()

    def test_bulk_tags_and_favorites_preserve_entire_selection(self):
        self.select(self.paths)
        self.assertEqual("2 sounds selected", self.tab.selection_count_var.get())
        self.assertEqual(("shared",), self.tab.personal_tag_list.get(0, "end"))
        self.assertEqual("disabled", self.tab.play_button.cget("state"))
        self.tab.new_tag_var.set("gritty")
        self.tab.add_tag_button.invoke()
        self.root.update()
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        for path in self.paths:
            self.assertIn("gritty", sorter_engine.get_asset_tags(path))
        self.tab.favorite_button.invoke()
        self.root.update()
        for path in self.paths:
            self.assertIn("favorite", sorter_engine.get_asset_tags(path))
        self.tab.unfavorite_button.invoke()
        self.tab.new_tag_var.set("only-first")
        self.tab.remove_tag_button.invoke()
        self.root.update()
        self.assertNotIn("only-first", sorter_engine.get_asset_tags(self.paths[0]))
        for path in self.paths:
            self.assertNotIn("favorite", sorter_engine.get_asset_tags(path))
            with open(path, "rb") as handle:
                self.assertEqual(b"unchanged sound", handle.read())
        self.show_error.assert_not_called()

    def test_single_favorite_toggle_and_disabled_tag_reenable(self):
        sorter_engine.set_asset_tag_enabled(self.paths[0], "shared", False)
        self.select(self.paths[:1])
        self.assertNotIn("shared", self.tab.personal_tag_list.get(0, "end"))
        self.tab.new_tag_var.set("shared")
        self.tab.add_tag_button.invoke()
        self.root.update()
        self.assertIn("shared", self.tab.personal_tag_list.get(0, "end"))
        self.tab.favorite_button.invoke()
        self.root.update()
        self.assertIn("favorite", sorter_engine.get_asset_tags(self.paths[0]))
        self.tab.favorite_button.invoke()
        self.root.update()
        self.assertNotIn("favorite", sorter_engine.get_asset_tags(self.paths[0]))
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        self.show_error.assert_not_called()

    def test_invalid_and_generated_tags_report_errors_without_changes(self):
        self.select(self.paths)
        before = [sorter_engine.get_asset_tags(path) for path in self.paths]
        for tag in ("", "name:generated", "category:Kicks", "a" * 81):
            self.tab.new_tag_var.set(tag)
            self.tab.add_tag_button.invoke()
        self.assertEqual(4, self.show_error.call_count)
        self.assertEqual(before, [sorter_engine.get_asset_tags(path) for path in self.paths])

    def test_bulk_changes_do_not_affect_unselected_filtered_results(self):
        self.tab.search_var.set("first")
        self.tab._render_results(load_sidebar=False)
        self.select(self.paths)
        self.tab.new_tag_var.set("reviewed")
        self.tab.add_tag_button.invoke()
        self.root.update()
        self.assertIn("reviewed", sorter_engine.get_asset_tags(self.paths[0]))
        self.assertNotIn("reviewed", sorter_engine.get_asset_tags(self.paths[1]))

    def test_removing_active_tag_filter_updates_results_and_selection(self):
        self.tab.active_tag_filter = "shared"
        self.tab._render_results(load_sidebar=False)
        self.select(self.paths)
        self.tab.new_tag_var.set("shared")
        self.tab.remove_tag_button.invoke()
        self.root.update()
        self.assertEqual({}, self.tab._asset_paths)
        self.assertEqual("No sounds selected", self.tab.selection_count_var.get())
        self.assertEqual("disabled", self.tab.add_tag_button.cget("state"))


class BulkTagValidationTests(unittest.TestCase):
    def test_bulk_changes_reject_stale_paths_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                sorter_engine, "ASSET_INDEX_FILE", os.path.join(directory, "assets.db")
            ):
                path = os.path.join(directory, "sound.wav")
                with open(path, "wb") as handle:
                    handle.write(b"sound")
                sorter_engine.index_asset(path, directory, "test", 1.0, ["favorite"])
                stale_path = os.path.join(directory, "not-indexed.wav")
                for remove in (False, True):
                    with self.assertRaisesRegex(ValueError, "no longer indexed"):
                        sorter_engine.bulk_update_asset_tags(
                            [path, stale_path], "favorite", remove=remove
                        )
                    self.assertEqual(["favorite"], sorter_engine.get_asset_tags(path))
                    self.assertEqual([], sorter_engine.get_asset_tags(stale_path))


if __name__ == "__main__":
    unittest.main()

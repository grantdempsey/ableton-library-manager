import gc
import json
import queue
import os
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

import gui_theme
import sorter_engine
import ableton_tags
import live_catalog
from tab_tags import TagsTab


class LibraryInspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for target, attribute, value in (
            (sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.temp_dir.name, "assets.db")),
            (sorter_engine, "CONFIG_FILE", os.path.join(self.temp_dir.name, "config.json")),
            (gui_theme, "USER_LIBRARY_PATH", self.temp_dir.name),
        ):
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        databases = mock.patch("live_catalog.available_databases", return_value=())
        databases.start()
        self.addCleanup(databases.stop)
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
        for callback in self.root.tk.splitlist(self.root.tk.call("after", "info")):
            self.root.tk.call("after", "cancel", callback)
        self.root.destroy()
        gc.collect()

    def select(self, paths):
        items = [item for item, path in self.tab._asset_paths.items() if path in paths]
        self.tab.asset_tree.selection_set(items)
        self.root.update()

    def wait_for_vocabulary(self):
        deadline = time.monotonic() + 3
        while (self.tab._live_vocabulary_queue is not None or self.tab._tag_suggestions_queue is not None) and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.tab._live_vocabulary_queue)
        self.assertIsNone(self.tab._tag_suggestions_queue)

    def test_inspector_separates_assignments_and_suggestions_from_tag_editing(self):
        self.assertIsNone(self.tab._live_batch_dialog)
        self.assertFalse(hasattr(self.tab, "tag_editor"))
        self.assertFalse(hasattr(self.tab, "personal_tag_entry"))
        self.assertFalse(hasattr(self.tab, "edit_local_tags_button"))
        self.select(self.paths)
        text = self.tab.assigned_tags_text.get("1.0", "end")
        self.assertIn("Manual Live (shared with Ableton)", text)
        self.assertNotIn("App-only", text)
        self.assertNotIn("only-first", text)
        self.assertIn("Generated (search / classification)", text)
        self.assertIn("category:Kicks (1/2)", text)
        self.assertEqual("disabled", self.tab.assigned_tags_text.cget("state"))
        self.assertFalse(hasattr(self.tab, "selection_notebook"))
        for control in (self.tab.edit_live_tags_button,):
            self.assertTrue(control.winfo_ismapped(), str(control))
            self.assertEqual("normal", control.cget("state"))
        self.select([])
        self.assertIn("Select sounds", self.tab.assigned_tags_text.get("1.0", "end"))
        for control in (self.tab.edit_live_tags_button,):
            self.assertEqual("disabled", control.cget("state"))

    def test_one_live_editor_captures_selection_and_close_discards_without_writing(self):
        self.select(self.paths[:1])
        self.tab.edit_live_tags_button.invoke()
        self.root.update()
        dialog = self.tab._live_batch_dialog
        self.wait_for_batch(dialog)
        self.assertTrue(dialog.winfo_ismapped())
        self.assertEqual((self.paths[0],), dialog.paths)
        self.assertFalse(hasattr(self.tab, "tag_editor"))
        dialog.group_var.set("Genres")
        dialog.tag_var.set("Unsaved")
        dialog.review_button.invoke()
        self.wait_for_batch(dialog)
        self.select(self.paths)
        self.assertEqual((self.paths[0],), dialog.paths)
        self.assertIn(self.paths[0], dialog.preview.get("1.0", "end"))
        self.assertNotIn(self.paths[1], dialog.preview.get("1.0", "end"))
        with mock.patch("live_tag_batch.ask_confirm", return_value=False):
            dialog.close()
        self.assertTrue(dialog.winfo_exists())
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            dialog.close()
        self.assertIsNone(self.tab._live_batch_dialog)
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))

    def test_consolidated_assignments_reload_select_remove_and_rename(self):
        ableton_tags.prepare_edit(self.paths, "Genres|Shared").commit()
        ableton_tags.prepare_edit(self.paths[:1], "Character|Partial").commit()
        dialog = self.open_batch()
        self.assertEqual(
            [("Character|Partial", "1/2"), ("Genres|Shared", "2/2")],
            self.assigned_rows(dialog)
        )
        dialog.assigned_tree.selection_set(dialog.assigned_tree.get_children()[0])
        self.root.update()
        self.assertEqual("remove", dialog.action_var.get())
        self.assertEqual("Character|Partial", dialog.tag_var.get())
        dialog.action_var.set("rename")
        dialog.replacement_var.set("Genres|Renamed")
        dialog.review()
        self.wait_for_batch(dialog)
        self.assertIn("- Character|Partial", dialog.preview.get("1.0", "end"))
        self.assertIn("+ Genres|Renamed", dialog.preview.get("1.0", "end"))
        dialog.save()
        self.wait_for_batch(dialog)
        self.assertIn("Changes saved", dialog.status_var.get())
        self.assertEqual(
            [("Genres|Renamed", "1/2"), ("Genres|Shared", "2/2")],
            self.assigned_rows(dialog)
        )
        ableton_tags.prepare_edit(self.paths, "Genres|Shared", "remove").commit()
        dialog.refresh_button.invoke()
        self.wait_for_batch(dialog)
        self.assertEqual([("Genres|Renamed", "1/2")], self.assigned_rows(dialog))
        self.assertIsNone(dialog.plan)
        self.assertEqual("disabled", str(dialog.save_button.cget("state")))

    def test_assignment_read_failure_is_explicit_and_never_enables_save(self):
        dialog = self.open_batch()
        with mock.patch.object(
            sorter_engine, "refresh_live_tag_cache", side_effect=ValueError("Invalid sidecar")
        ), mock.patch("live_tag_batch.messagebox.showerror") as error:
            dialog.refresh_button.invoke()
            self.wait_for_batch(dialog)
        self.assertIn("Invalid sidecar", error.call_args.args[1])
        self.assertIn("Could not read", dialog.status_var.get())
        self.assertIsNone(dialog.plan)
        self.assertEqual("disabled", str(dialog.save_button.cget("state")))
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))

    def test_assignment_read_is_background_and_single_flight(self):
        dialog = self.open_batch()
        release = threading.Event()
        started = threading.Event()
        original = sorter_engine.refresh_live_tag_cache
        threads = []
        def delayed(paths):
            threads.append(threading.current_thread())
            started.set()
            if not release.wait(3):
                raise ValueError("Test reader timed out")
            return original(paths)
        with mock.patch.object(sorter_engine, "refresh_live_tag_cache", side_effect=delayed) as read:
            try:
                dialog.refresh_assignments()
                self.assertTrue(started.wait(1))
                dialog.refresh_assignments()
                heartbeat = []
                self.root.after_idle(lambda: heartbeat.append(True))
                self.root.update()
                self.assertEqual([True], heartbeat)
                self.assertEqual("disabled", str(dialog.save_button.cget("state")))
                self.assertTrue(dialog.busy)
            finally:
                release.set()
            self.wait_for_batch(dialog)
        self.assertEqual(1, read.call_count)
        self.assertTrue(all(thread is not threading.main_thread() for thread in threads))

    def test_favorites_still_target_captured_selection_without_app_tags(self):
        self.tab._page_size = 1
        self.tab._render_results(load_sidebar=False)
        self.tab._select_all_matching()
        self.wait_for_select_all()
        with mock.patch("tab_tags.ask_confirm", return_value=False):
            self.tab.bulk_remove_favorite()
        with mock.patch("tab_tags.ask_confirm", return_value=True):
            self.tab._update_selected_tag("favorite")
        for path in self.paths:
            self.assertIn("favorite", sorter_engine.get_asset_tags(path))
            self.assertNotIn("shared", sorter_engine.get_asset_tags(path))
        with mock.patch("tab_tags.ask_confirm", return_value=True):
            self.tab.bulk_remove_favorite()
        for path in self.paths:
            self.assertNotIn("favorite", sorter_engine.get_asset_tags(path))
        with self.assertRaisesRegex(ValueError, "App-only tags have been removed"):
            self.tab._update_selected_tag("custom")
        for attribute in ("personal_tag_entry", "personal_tag_list", "add_tag_button", "bulk_add_tag"):
            self.assertFalse(hasattr(self.tab, attribute))

    def test_pagination_view_and_metadata_controls_are_grouped_by_scope(self):
        self.assertEqual("Previous page", self.tab.previous_page_button.cget("text"))
        self.assertEqual("Next page", self.tab.next_page_button.cget("text"))
        self.assertIn("Page 1", self.tab.page_label.cget("text"))
        self.assertIs(self.tab.previous_page_button.master, self.tab.next_page_button.master)
        self.assertIs(self.tab.page_label.master, self.tab.next_page_button.master)
        self.assertIs(self.tab.page_label.master.master, self.tab.asset_tree.master)
        self.assertIsNot(self.tab.inspector_toggle.master, self.tab.page_label.master)
        self.assertIs(self.tab.monitor_live_check.master, self.tab.freshness_label.master)
        self.assertIn("right", self.tab.inspector_toggle.cget("text"))
        self.assertFalse(hasattr(self.tab, "selection_notebook"))
        self.select(self.paths[:1])
        self.assertIn("category:Kicks", self.tab.assigned_tags_text.get("1.0", "end"))
        self.tab._open_asset_details()
        advice = self.tab.sound_details_text.get("1.0", "end")
        self.assertIn("Folder advice (review only)", advice)
        self.assertIn("No folder advice available", advice)
        self.assertNotIn("No mapped manual", advice)
        for control in (self.tab.previous_page_button, self.tab.next_page_button, self.tab.page_label):
            self.assertTrue(control.winfo_ismapped())
            self.assertGreaterEqual(control.winfo_rootx(), self.tab.asset_tree.winfo_rootx())
            self.assertLessEqual(
                control.winfo_rootx() + control.winfo_width(),
                self.tab.asset_tree.master.winfo_rootx() + self.tab.asset_tree.master.winfo_width()
            )
        self.assertGreater(
            self.tab.monitor_live_check.winfo_rooty(),
            self.tab.browser_panes.winfo_rooty() + self.tab.browser_panes.winfo_height()
        )

    def test_summary_separates_sources_and_omits_disabled_tags_without_writing(self):
        connection = sorter_engine._asset_index_connection()
        try:
            connection.executemany(
                "INSERT INTO asset_tags(asset_path, tag, enabled, source) VALUES (?, ?, ?, ?)",
                [
                    (self.paths[0], "ableton:Genres|Ambient", 1, "ableton"),
                    (self.paths[0], "category:Disabled", 0, "generated"),
                    (self.paths[0], "hidden-personal", 0, "personal"),
                ]
            )
            connection.commit()
        finally:
            connection.close()
        with mock.patch.object(ableton_tags.TagEdit, "commit") as write:
            self.select(self.paths)
            text = self.tab.assigned_tags_text.get("1.0", "end")
            self.assertIn("Genres > Ambient (1/2)", text)
            self.assertIn("category:Kicks (1/2)", text)
            self.assertNotIn("only-first", text)
            self.assertNotIn("category:Disabled", text)
            self.assertNotIn("hidden-personal", text)
            self.assertNotIn("\nshared\n", text)
            self.select(self.paths[:1])
            self.tab._open_asset_details()
            self.root.update()
            self.assertTrue(self.tab.sound_details_text.winfo_ismapped())
            self.assertEqual("disabled", self.tab.sound_details_text.cget("state"))
            self.assertTrue(self.tab.sound_details_text.cget("yscrollcommand"))
            self.assertIn("Folder advice (review only)", self.tab.sound_details_text.get("1.0", "end"))
            write.assert_not_called()


    def test_live_vocabulary_augments_cached_custom_suggestions_without_assigning_tags(self):
        vocabulary = ("Genres", "Genres|Ambient", "My Group|Subgroup|Custom", "Drums|Snare|Rim")
        self.tab.live_group_var.set("My Group")
        self.tab.live_tag_var.set("Keep typed value")
        before = sorter_engine.list_indexed_tags(library_root=self.temp_dir.name)
        batch = self.open_batch()
        batch.tag_var.set("Keep typed value")
        with mock.patch("live_catalog.available_databases", return_value=("chosen.db",)), mock.patch(
            "live_catalog.read_vocabulary", return_value=vocabulary
        ) as read, mock.patch.object(ableton_tags.TagEdit, "commit") as write:
            self.tab._load_live_tag_suggestions()
            self.wait_for_vocabulary()
            self.assertEqual(
                ("Drums|Snare|Rim", "Genres|Ambient", "My Group|Subgroup|Custom"),
                batch.tag_entry.cget("values")
            )
            self.assertIn("My Group", batch.group_entry.cget("values"))
            self.assertNotIn("Format", batch.group_entry.cget("values"))
            self.assertEqual("Keep typed value", batch.tag_var.get())
            self.assertEqual("My Group", batch.group_var.get())
            self.tab._load_live_tag_suggestions()
            read.assert_called_once_with("chosen.db")
            batch.load_suggestions()
            self.assertIn("My Group", batch.group_entry.cget("values"))
            write.assert_not_called()
        self.assertEqual(before, sorter_engine.list_indexed_tags(library_root=self.temp_dir.name))

    def test_vocabulary_requires_database_choice_and_surfaces_read_errors(self):
        self.tab._live_vocabulary = ("Genres|Keep",)
        with mock.patch("live_catalog.available_databases", return_value=("one.db", "two.db")), mock.patch(
            "live_catalog.read_vocabulary"
        ) as read:
            self.tab._load_live_tag_suggestions()
            read.assert_not_called()
        with mock.patch("live_catalog.available_databases", return_value=("one.db",)), mock.patch(
            "live_catalog.read_vocabulary", side_effect=ValueError("Invalid vocabulary")
        ):
            self.tab._load_live_tag_suggestions()
            self.wait_for_vocabulary()
        self.assertEqual(("Genres|Keep",), self.tab._live_vocabulary)
        self.assertIn("Invalid vocabulary", self.show_error.call_args.args[1])
        self.assertIsNone(self.tab._live_vocabulary_database)

    def test_library_has_one_editable_browser_and_keeps_vocabulary_choice(self):
        self.assertFalse(hasattr(self.tab, "library_source_picker"))
        self.assertFalse(hasattr(self.tab, "_catalog_panel"))
        self.select(self.paths)
        self.tab._open_tag_editor()
        with mock.patch("tab_tags.filedialog.askopenfilename", return_value="selected.db"), mock.patch(
            "live_catalog.read_vocabulary", return_value=("Genres|Ambient", "Custom|Sub|Tag")
        ) as read, mock.patch.object(ableton_tags.TagEdit, "commit") as write:
            self.tab._choose_live_vocabulary_database()
            self.wait_for_vocabulary()
        read.assert_called_once_with("selected.db")
        write.assert_not_called()
        self.assertIn("Custom|Sub|Tag", self.tab._live_batch_dialog.tag_entry.cget("values"))
        self.assertEqual("selected.db", self.tab._selected_vocabulary_database)

    def test_library_help_does_not_direct_users_to_removed_catalog(self):
        with mock.patch("tab_tags.show_notice") as notice:
            self.tab._explain_tag_sources()
        help_text = notice.call_args.args[2]
        self.assertIn("Tag suggestions source...", help_text)
        self.assertNotIn("Ableton catalog", help_text)
        self.tab._render_tag_browser([])
        self.assertIn("No manual Live assignments", self.tab.tag_browser_status.cget("text"))
        self.assertNotIn("catalog", self.tab.tag_browser_status.cget("text"))

    def test_panes_resize_and_inspector_collapses_without_losing_selection(self):
        self.select(self.paths[:1])
        self.assertEqual(3, len(self.tab.browser_panes.panes()))
        before = self.tab.browser_panes.sash_coord(0)[0]
        self.tab.browser_panes.sash_place(0, before + 30, 0)
        self.root.update()
        self.assertGreater(self.tab.browser_panes.sash_coord(0)[0], before)
        self.assertEqual("normal", self.tab.edit_live_tags_button.cget("state"))
        self.assertIs(self.tab.favorite_button.master, self.tab.unfavorite_button.master)
        self.assertTrue(self.tab.favorite_button.winfo_ismapped())
        self.assertIsNone(self.tab._live_batch_dialog)
        self.assertGreater(self.tab.assigned_tags_text.winfo_height(), 20)
        self.assertLess(
            self.tab.edit_live_tags_button.winfo_rootx() + self.tab.edit_live_tags_button.winfo_width(),
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
            self.tab.edit_live_tags_button
        ):
            self.assertEqual("disabled", control.cget("state"))
        self.assertEqual((), self.tab.waveform_canvas.find_all())
        self.assertIsNone(self.tab._live_batch_dialog)

    def test_library_hints_are_cached_explainable_and_clear_on_multiselection(self):
        ableton_tags.prepare_edit(self.paths[:1], "Sounds|Snare").commit()
        sorter_engine.refresh_live_tag_cache(self.paths[:1])
        self.select(self.paths[:1])
        self.tab._open_asset_details()
        text = self.tab.sound_details_text.get("1.0", "end")
        self.assertIn("Sounds|Snare", text)
        self.assertIn("Snares", text)
        self.assertIn("Review only", text)
        self.assertIn("Folder differs", text)
        self.assertEqual("disabled", self.tab.sound_details_text.cget("state"))
        self.tab._close_details_dialog(self.tab._details_dialog)
        ableton_tags.prepare_edit(self.paths[:1], "Sounds|Kick").commit()
        sorter_engine.refresh_live_tag_cache(self.paths[:1])
        self.tab._show_selected_asset()
        self.tab._open_asset_details()
        self.assertIn("Conflicting sound types", self.tab.sound_details_text.get("1.0", "end"))
        self.tab._close_details_dialog(self.tab._details_dialog)
        self.select(self.paths)
        self.assertFalse(hasattr(self.tab, "recommendation_text"))
        self.assertTrue(os.path.isfile(self.paths[0]))


    def test_inline_preview_survives_initial_idle_assignment_read(self):
        self.select(self.paths[:1])
        self.tab._edit_live_tags(self.paths[:1], "Sounds|Custom label", "add")
        dialog = self.tab._live_batch_dialog
        deadline = time.monotonic() + 4
        while dialog.results.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(dialog.results.empty())
        dialog.finish()
        self.assertIsNotNone(dialog.plan)
        self.root.update_idletasks()
        self.assertFalse(dialog.busy)
        self.assertIsNotNone(dialog.plan)
        self.assertEqual("normal", str(dialog.save_button.cget("state")))
        self.finish_inline_change()
        self.assertIn("Sounds|Custom label", ableton_tags.sample_tags(self.paths[0]))

    def test_inline_custom_tags_round_trip_in_every_verified_group(self):
        self.select(self.paths[:1])
        for group in ableton_tags.TAG_GROUPS:
            with self.subTest(group=group), mock.patch("tab_tags.ask_confirm", return_value=True):
                self.tab.live_group_var.set(group)
                self.tab.live_tag_var.set("Custom label")
                self.preview_inline("add")
                self.finish_inline_change()
                self.assertIn(f"{group}|Custom label", ableton_tags.sample_tags(self.paths[0]))
                self.assertIn(f"{group}|Custom label", sorter_engine.get_indexed_asset(self.paths[0])["ableton_tags"])
                self.preview_inline("remove")
                self.finish_inline_change()
                self.assertNotIn(f"{group}|Custom label", ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual([], ableton_tags.sample_tags(self.paths[1]))

    def test_group_qualification_preserves_explicit_hierarchies_and_rejects_bad_groups(self):
        self.assertEqual("Genres|Custom|Deep", ableton_tags.qualify_tag("Genres|Custom|Deep", "Sounds"))
        self.assertEqual("My Group|Custom", ableton_tags.qualify_tag("Custom", "My Group"))
        for group in ("", "Sounds|Bass", "Bad\nGroup"):
            with self.assertRaises(ValueError):
                ableton_tags.qualify_tag("Custom", group)

    def test_batch_group_choice_rename_and_review_invalidation(self):
        dialog = self.open_batch()
        dialog.group_var.set("Genres")
        dialog.tag_var.set("Custom genre")
        dialog.enqueue()
        dialog.review()
        self.wait_for_batch(dialog)
        self.assertIsNotNone(dialog.plan)
        dialog.group_var.set("Character")
        self.assertIsNone(dialog.plan)
        self.assertEqual("normal", str(dialog.save_button.cget("state")))
        # A plain rename target uses the chosen group; explicit source keeps its own.
        dialog.action_var.set("rename")
        dialog.tag_var.set("Genres|Custom genre")
        dialog.replacement_var.set("Custom character")
        dialog.enqueue()
        self.assertEqual("Genres|Custom genre", dialog.operations[-1].tag)
        self.assertEqual("Character|Custom character", dialog.operations[-1].replacement)
        dialog.review()
        self.wait_for_batch(dialog)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            dialog.save()
            self.wait_for_batch(dialog)
        for path in self.paths:
            self.assertEqual(["Character|Custom character"], ableton_tags.sample_tags(path))


    def live_rows(self):
        text = self.tab.assigned_tags_text.get("1.0", "end")
        if "Manual Live (shared with Ableton)" not in text:
            return []
        section = text.split("Manual Live (shared with Ableton)\n", 1)[1]
        import re
        rows = []
        for line in section.strip().splitlines():
            if line == "None":
                continue
            match = re.fullmatch(r"(.*) \(([\d,]+)/([\d,]+)\)", line)
            if match:
                tag, count, total = match.groups()
                count, total = count.replace(",", ""), total.replace(",", "")
                rows.append((tag.replace(" > ", "|"), f"{count}/{total} {'all' if count == total else 'some'}"))
            else:
                rows.append((line.replace(" > ", "|"), "1/1 all"))
        return rows

    def preview_inline(self, action="add"):
        try:
            tag = ableton_tags.qualify_tag(self.tab.live_tag_var.get(), self.tab.live_group_var.get())
        except ValueError as error:
            self.show_error("Live tags", str(error))
            return
        self.tab._edit_live_tags(self.tab._selected_paths(), tag, action)

    def suggestion_editor(self):
        if self.tab._live_batch_dialog is None:
            self.select(self.paths)
            self.tab._open_live_batch()
            self.root.update()
            self.wait_for_batch(self.tab._live_batch_dialog)
        return self.tab._live_batch_dialog

    def assigned_rows(self, dialog):
        return [
            dialog.assigned_tree.item(item, "values")
            for item in dialog.assigned_tree.get_children()
        ]

    def set_browser_tags_from_index(self):
        self.tab._cached_tags = sorter_engine.list_indexed_tags(self.temp_dir.name)
        self.tab._render_tag_browser(self.tab._cached_tags)
        self.root.update()

    def test_tag_browser_prioritizes_live_and_navigates_sources_groups_and_find(self):
        for tag in ("Sounds|Bass|Deep", "Character|Warm", "Instrument|Synth"):
            ableton_tags.prepare_edit(self.paths[:1], tag).commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.set_browser_tags_from_index()
        self.assertEqual(
            ("All groups", "Character", "Instrument", "Sounds"),
            self.tab.tag_group_picker.cget("values")
        )
        self.assertEqual(
            ["ableton:Character|Warm", "ableton:Instrument|Synth", "ableton:Sounds|Bass|Deep"],
            [row[0] for row in self.tab._tag_browser_rows[:3]]
        )
        self.tab.tag_source_var.set("Live manual tags")
        self.tab.tag_group_var.set("Sounds")
        self.tab._tag_navigation_changed()
        self.assertEqual(["ableton:Sounds|Bass|Deep"], [row[0] for row in self.tab._tag_browser_rows])
        self.tab.tag_search_var.set("DEEP")
        self.tab._tag_navigation_changed()
        self.assertEqual(1, len(self.tab._tag_browser_rows))
        self.tab.tag_source_var.set("Generated tags")
        self.tab.tag_search_var.set("category:")
        self.tab._tag_navigation_changed()
        self.assertEqual("disabled", str(self.tab.tag_group_picker.cget("state")))
        self.assertEqual({"category:Kicks", "category:Snares"}, {row[0] for row in self.tab._tag_browser_rows})
        self.tab.tag_source_var.set("Local tags")
        self.tab.tag_search_var.set("shared")
        self.tab._tag_navigation_changed()
        self.assertEqual([], self.tab._tag_browser_rows)
        self.assertNotIn("Local tags", self.tab.tag_source_picker.cget("values"))
        self.show_error.assert_not_called()

    def test_discovery_builder_filters_and_saved_collection_round_trip(self):
        ableton_tags.prepare_edit(self.paths[:1], "Sounds|Bass").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.select(self.paths)
        self.assertTrue(self.tab._add_discovery_filters(
            ["ableton:Sounds|Bass", "category:Snares"], "Match any",
            "Any manual Live tags", "Character"
        ))
        self.root.update()
        self.assertEqual(set(self.paths), set(self.tab._asset_paths.values()))
        self.assertEqual(set(), self.tab._selection_paths)
        search = self.tab.search_var.get()
        self.assertIn('"anytag:ableton:Sounds|Bass"', search)
        with mock.patch("tab_tags.ask_fields", return_value=["Needs character"]):
            self.tab._save_current_search()
        saved = self.tab._load_saved_searches()[0]
        self.assertEqual(search, saved["text"])
        self.tab._clear_all_filters()
        self.tab._apply_saved_search(saved)
        self.assertEqual(search, self.tab.search_var.get())
        self.tab._select_all_matching()
        self.wait_for_select_all()
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        self.show_error.assert_not_called()

    def test_discovery_builder_untagged_and_excluded_tag_modes(self):
        ableton_tags.prepare_edit(self.paths[:1], "Character|Warm").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.assertTrue(self.tab._add_discovery_filters([], "Match all", "No manual Live tags", ""))
        self.assertEqual(self.paths[1:], list(self.tab._asset_paths.values()))
        self.tab._clear_all_filters()
        self.assertTrue(self.tab._add_discovery_filters(
            ["ableton:Character|Warm"], "Exclude selected", "Any manual Live tags", ""
        ))
        self.assertEqual(self.paths[1:], list(self.tab._asset_paths.values()))
        self.show_error.assert_not_called()

    def test_discovery_invalid_inputs_preserve_search_and_selection(self):
        self.select(self.paths)
        before = self.tab.search_var.get()
        for tags, group in (([], ""), ([], "Sounds|Bass"), (['Bad"Tag'], ""), ([], 'Bad"Group')):
            self.assertFalse(self.tab._add_discovery_filters(tags, "Match all", "Any manual Live tags", group))
        self.assertEqual(4, self.show_error.call_count)
        self.assertEqual(before, self.tab.search_var.get())
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))

    def test_discovery_dialog_controls_fit_minimum_size(self):
        self.tab._open_discovery_filters()
        self.root.update()
        dialog = next(child for child in self.tab.winfo_children() if isinstance(child, tk.Toplevel))
        dialog.geometry("580x490")
        self.root.update()
        for control in dialog.winfo_children():
            self.assertTrue(control.winfo_ismapped())
            self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), dialog.winfo_rootx() + dialog.winfo_width())
            self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())
        listing = next(widget for child in dialog.winfo_children() for widget in child.winfo_children()
                       if isinstance(widget, tk.Listbox))
        for option, color in (
            ("background", "bg_field"), ("foreground", "fg_light"),
            ("selectbackground", "tag_enabled"), ("selectforeground", "fg_light"),
            ("highlightbackground", "border"), ("highlightcolor", "accent_neon")
        ):
            self.assertEqual(gui_theme.THEME[color], listing.cget(option))
        listing.selection_set(0)
        self.assertEqual((0,), listing.curselection())
        dialog.destroy()

    def test_tag_navigation_does_not_change_sound_filter_or_captured_selection(self):
        self.select(self.paths)
        self.set_browser_tags_from_index()
        self.tab.tag_source_var.set("Live manual tags")
        self.tab.tag_search_var.set("missing")
        self.tab._tag_navigation_changed()
        self.assertEqual((), tuple(self.tab._tag_browser_rows))
        self.assertEqual("None", self.tab.tag_list.get(0))
        self.assertEqual("", self.tab.active_tag_filter)
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        with mock.patch("tab_tags.show_notice") as help_notice:
            self.tab._explain_tag_sources()
        self.assertIn("automatic/factory tags", help_notice.call_args.args[2])
        self.assertIn("configured User Library", help_notice.call_args.args[2])

    def test_tag_browser_click_uses_exact_raw_hierarchy_not_display_text(self):
        tag = "Sounds|Bass  (Subtag)"
        ableton_tags.prepare_edit(self.paths[:1], tag).commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.set_browser_tags_from_index()
        index = next(i for i, row in enumerate(self.tab._tag_browser_rows) if row[0] == "ableton:" + tag)
        self.tab.tag_list.selection_set(index)
        self.tab._tag_selected(None)
        self.root.update()
        self.assertEqual("ableton:" + tag, self.tab.active_tag_filter)
        self.assertEqual(self.paths[:1], list(self.tab._asset_paths.values()))

    def test_clicking_first_tag_batch_does_not_truncate_remaining_tags(self):
        tags = [(f"name:generated-{index:04}", 1) for index in range(1200)]
        tags.append(("ableton:Sounds|Visible first", 1))
        self.tab._cached_tags = tags
        self.tab._render_tag_browser(tags)
        self.assertEqual(250, self.tab.tag_list.size())
        with mock.patch.object(self.tab, "_apply_tag_filter") as apply:
            self.tab._tag_released(mock.Mock(y=1))
            deadline = time.monotonic() + 2
            while self.tab._tag_render_after_id is not None and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.005)
        self.assertEqual(1201, self.tab.tag_list.size())
        apply.assert_called_once_with("ableton:Sounds|Visible first", exact=True)
        self.assertTrue(self.tab.tag_list.get(0).startswith("Live: Sounds|"))

    def test_tag_browser_refresh_replaces_renamed_removed_groups_and_counts(self):
        ableton_tags.prepare_edit(self.paths, "Sounds|Old").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.set_browser_tags_from_index()
        self.tab.tag_source_var.set("Live manual tags")
        self.tab.tag_group_var.set("Sounds")
        self.tab._tag_navigation_changed()
        self.assertEqual([("ableton:Sounds|Old", 2, "Live: Sounds|Old")], self.tab._tag_browser_rows)
        ableton_tags.prepare_edit(self.paths[:1], "Sounds|Old", replacement="Character|New").commit()
        ableton_tags.prepare_edit(self.paths[1:], "Sounds|Old", remove=True).commit()
        self.select(self.paths)
        self.tab._refresh_selected_live_tags()
        self.wait_for_live_refresh()
        self.set_browser_tags_from_index()
        self.assertEqual("All groups", self.tab.tag_group_var.get())
        self.assertEqual(("All groups", "Character"), self.tab.tag_group_picker.cget("values"))
        self.assertEqual([("ableton:Character|New", 1, "Live: Character|New")], self.tab._tag_browser_rows)
        self.show_error.assert_not_called()

    def test_sidebar_updates_from_real_cache_after_writes_refresh_and_rescan(self):
        def load_sidebar_now(library_root):
            self.tab._sidebar_generation += 1
            data = self.tab._load_sidebar_data(library_root, "All sounds", False)
            self.tab._finish_sidebar_load(data, None, self.tab._sidebar_generation)
        self.tab._request_sidebar_load.side_effect = load_sidebar_now
        self.tab.tag_source_var.set("Live manual tags")
        self.select(self.paths)
        with mock.patch("tab_tags.ask_confirm", return_value=True):
            self.tab.live_tag_var.set("Character|First")
            self.preview_inline()
        self.finish_inline_change()
        self.root.update()
        self.assertEqual([("ableton:Character|First", 2, "Live: Character|First")], self.tab._tag_browser_rows)
        ableton_tags.prepare_edit(self.paths, "Character|First", replacement="Sounds|External").commit()
        self.tab._refresh_selected_live_tags()
        self.wait_for_live_refresh()
        self.assertEqual([("ableton:Sounds|External", 2, "Live: Sounds|External")], self.tab._tag_browser_rows)
        ableton_tags.prepare_edit(self.paths, "Sounds|External", remove=True).commit()
        sorter_engine.index_existing_library(self.temp_dir.name)
        self.tab._finish_refresh(2, None)
        self.root.update()
        self.assertEqual([], self.tab._tag_browser_rows)
        self.assertEqual(("All groups",), self.tab.tag_group_picker.cget("values"))
        self.show_error.assert_not_called()

    def test_tag_browser_remains_usable_at_minimum_window(self):
        self.select(self.paths)
        self.tab._cached_tags = [(f"ableton:Sounds|Tag {index}", 1) for index in range(20)]
        self.tab._render_tag_browser(self.tab._cached_tags)
        self.root.update()
        self.assertGreaterEqual(self.tab.tag_list.winfo_height(), 70)
        self.assertGreaterEqual(self.tab.tag_list.winfo_width(), 100)
        for control in (self.tab.tag_source_picker, self.tab.tag_group_picker, self.tab.tag_search_entry):
            self.assertTrue(control.winfo_ismapped())
            self.assertLessEqual(
                control.winfo_rootx() + control.winfo_width(),
                self.tab.collection_list.master.master.winfo_rootx()
                + self.tab.collection_list.master.master.winfo_width()
            )

    def wait_for_live_refresh(self):
        deadline = time.monotonic() + 3
        while self.tab._live_refresh_queue is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.tab._live_refresh_queue)

    def run_metadata_probe(self):
        if self.tab._metadata_after_id is not None:
            self.tab.after_cancel(self.tab._metadata_after_id)
        self.tab._poll_live_metadata()
        deadline = time.monotonic() + 4
        while self.tab._metadata_queue is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.tab._metadata_queue)

    def test_metadata_monitor_updates_external_tags_without_changing_captured_selection(self):
        self.select(self.paths)
        ableton_tags.prepare_edit(self.paths[:1], "Character|External").commit()
        self.run_metadata_probe()
        self.assertIn("stable second probe", self.tab.freshness_var.get())
        self.assertEqual([], self.live_rows())
        self.run_metadata_probe()
        self.assertEqual([("Character|External", "1/2 some")], self.live_rows())
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        self.assertIn("Library Live-tag sync:", self.tab.freshness_var.get())
        self.assertIsNotNone(self.tab._last_metadata_sync)
        self.tab._request_sidebar_load.assert_called()
        self.show_error.assert_not_called()

    def test_metadata_monitor_skips_hidden_disabled_and_batch_editor(self):
        with mock.patch("tab_tags.live_tag_sync.poll_live_metadata") as poll:
            self.tab.monitor_live_var.set(False)
            self.run_metadata_probe()
            self.tab.monitor_live_var.set(True)
            with mock.patch.object(self.tab, "_tab_is_visible", return_value=False):
                self.run_metadata_probe()
            self.select(self.paths)
            self.tab._open_live_batch()
            self.run_metadata_probe()
            poll.assert_not_called()
        self.assertIn("paused during", self.tab.freshness_var.get())

    def test_monitor_error_retains_cache_displays_failure_and_can_retry(self):
        ableton_tags.prepare_edit(self.paths, "Sounds|Keep").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.select(self.paths)
        with mock.patch("tab_tags.live_tag_sync.poll_live_metadata", side_effect=ValueError("Invalid metadata")):
            self.run_metadata_probe()
        self.assertIn("cached assignments retained: Invalid metadata", self.tab.freshness_var.get())
        self.assertEqual([("Sounds|Keep", "2/2 all")], self.live_rows())
        self.assertEqual("normal", self.tab.edit_live_tags_button.cget("state"))
        self.run_metadata_probe()
        self.run_metadata_probe()
        self.assertIn("metadata checked", self.tab.freshness_var.get())

    def test_monitor_can_hide_selected_matches_without_retargeting_batch_selection(self):
        self.tab.search_var.set("live:none")
        self.tab._apply_filter()
        self.select(self.paths)
        ableton_tags.prepare_edit(self.paths, "Sounds|External").commit()
        self.run_metadata_probe()
        self.run_metadata_probe()
        self.root.update()
        self.assertEqual({}, self.tab._asset_paths)
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        self.assertEqual("2 sounds selected (2 off page)", self.tab.selection_count_var.get())

    def test_freshness_records_successful_scan_and_does_not_claim_success_on_failure(self):
        self.tab._finish_refresh(2, None)
        self.assertIsNotNone(self.tab._last_full_scan)
        last_scan = self.tab._last_full_scan
        self.tab._finish_refresh(0, ValueError("Invalid sidecar"))
        self.assertEqual(last_scan, self.tab._last_full_scan)
        self.assertIn("Scan failed", self.tab.freshness_var.get())
        self.assertIn(last_scan, self.tab.freshness_var.get())
        self.show_error.assert_called_once()


    def test_monitor_probe_blocks_rescan_and_already_open_dialog_write(self):
        self.tab._metadata_queue = mock.Mock()
        try:
            with mock.patch("tab_tags.show_notice") as notice, mock.patch.object(
                ableton_tags, "prepare_edit"
            ) as write:
                self.assertFalse(self.tab._edit_live_tags(self.paths, "Sounds|No", "add"))
                self.tab.rescan_library()
            self.assertEqual(2, notice.call_count)
            write.assert_not_called()
        finally:
            self.tab._metadata_queue = None

    def open_batch(self):
        self.select(self.paths)
        self.tab._open_live_batch()
        self.root.update()
        self.wait_for_batch(self.tab._live_batch_dialog)
        return self.tab._live_batch_dialog

    def wait_for_batch(self, dialog):
        deadline = time.monotonic() + 4
        while dialog.busy and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(dialog.busy)
        self.root.update()

    def finish_inline_change(self, save=True):
        dialog = self.tab._live_batch_dialog
        self.wait_for_batch(dialog)
        if save:
            dialog.save()
        self.wait_for_batch(dialog)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            dialog.close()

    def test_batch_surfaces_stay_dark_when_empty_reviewed_and_invalidated(self):
        dialog = self.open_batch()
        def check_surfaces():
            for widget in (dialog.listing, dialog.preview):
                for option, color in (
                    ("background", "bg_field"), ("foreground", "fg_light"),
                    ("selectbackground", "tag_enabled"), ("selectforeground", "fg_light"),
                    ("highlightbackground", "border"), ("highlightcolor", "accent_neon")
                ):
                    expected = gui_theme.THEME[color]
                    if widget is dialog.preview:
                        expected = {"background": dialog.field, "highlightbackground": dialog.edge}.get(option, expected)
                    self.assertEqual(expected, widget.cget(option))
            self.assertEqual("disabled", dialog.preview.cget("state"))
        check_surfaces()
        dialog.tag_var.set("Sounds|Snare")
        dialog.queue_button.invoke()
        dialog.review_button.invoke()
        self.wait_for_batch(dialog)
        check_surfaces()
        self.assertIn("Snare", dialog.preview.get("1.0", "end"))
        dialog.tag_var.set("Sounds|Kick")
        check_surfaces()
        self.assertIn("Preview changes", dialog.preview.get("1.0", "end"))
        self.assertNotIn("+ Sounds|Snare", dialog.preview.get("1.0", "end"))

    def test_live_editor_contrast_and_styles_do_not_change_other_pages(self):
        style = ttk.Style(self.root)
        default_entry = style.lookup("TCombobox", "fieldbackground")
        dialog = self.open_batch()
        def luminance(color):
            channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        def contrast(first, second):
            light, dark = sorted((luminance(first), luminance(second)), reverse=True)
            return (light + 0.05) / (dark + 0.05)
        self.assertGreaterEqual(contrast(gui_theme.THEME["fg_light"], dialog.surface), 4.5)
        self.assertGreaterEqual(contrast(gui_theme.THEME["fg_light"], dialog.field), 4.5)
        self.assertGreaterEqual(contrast(dialog.edge, dialog.surface), 3)
        self.assertGreaterEqual(contrast(dialog.edge, dialog.field), 3)
        self.assertGreaterEqual(
            contrast(dialog.save_button.cget("foreground"), dialog.save_button.cget("background")), 4.5
        )
        self.assertEqual("LiveEditor.TCombobox", dialog.tag_entry.cget("style"))
        self.assertEqual(default_entry, style.lookup("TCombobox", "fieldbackground"))
        self.assertNotEqual(dialog.review_button.cget("background"), gui_theme.THEME["bg_dark"])

    def test_batch_captures_selection_reviews_and_saves_combined_changes_once(self):
        dialog = self.open_batch()
        self.select(self.paths[:1])
        dialog.tag_var.set("Sounds|First")
        dialog.queue_button.invoke()
        dialog.tag_var.set("Character|Warm")
        dialog.queue_button.invoke()
        dialog.review_button.invoke()
        self.wait_for_batch(dialog)
        self.assertEqual(tuple(self.paths), dialog.paths)
        self.assertEqual(2, len(dialog.plan.sample_changes))
        self.assertEqual("normal", str(dialog.save_button.cget("state")))
        for path in self.paths:
            self.assertEqual([], ableton_tags.sample_tags(path))
        with mock.patch("live_tag_batch.ask_confirm", return_value=True) as confirm:
            dialog.save_button.invoke()
            self.wait_for_batch(dialog)
        confirm.assert_not_called()
        self.assertEqual([], dialog.operations)
        self.assertIsNone(dialog.plan)
        self.assertEqual("disabled", str(dialog.save_button.cget("state")))
        for path in self.paths:
            self.assertEqual(["Character|Warm", "Sounds|First"], ableton_tags.sample_tags(path))
            self.assertEqual(["Character|Warm", "Sounds|First"], sorter_engine.get_indexed_asset(path)["ableton_tags"])
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        dialog.close()
        self.assertIsNone(self.tab._live_batch_dialog)

    def test_batch_cancel_and_queue_mutation_invalidate_review(self):
        dialog = self.open_batch()
        dialog.tag_var.set("Sounds|First")
        dialog.enqueue()
        dialog.review()
        self.wait_for_batch(dialog)
        with mock.patch("live_tag_batch.ask_confirm", return_value=False):
            dialog.close()
        self.assertIsNotNone(dialog.plan)
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))
        dialog.tag_var.set("Character|Changed")
        self.assertIsNone(dialog.plan)
        self.assertEqual("normal", str(dialog.save_button.cget("state")))
        dialog.enqueue()
        dialog.listing.selection_set(0)
        dialog.remove()
        self.assertEqual([ableton_tags.TagOperation("add", "Character|Changed")], dialog.operations)
        with mock.patch("live_tag_batch.ask_confirm", return_value=False):
            dialog.close()
        self.assertTrue(dialog.winfo_exists())
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            dialog.close()
        self.assertIsNone(self.tab._live_batch_dialog)

    def test_batch_noop_disables_save_and_busy_dialog_blocks_other_live_writes(self):
        dialog = self.open_batch()
        dialog.tag_var.set("Sounds|Cancel")
        dialog.enqueue()
        dialog.action_var.set("remove")
        dialog.tag_var.set("Sounds|Cancel")
        dialog.enqueue()
        dialog.review()
        with mock.patch("live_tag_batch.show_notice") as notice:
            dialog.close()
            notice.assert_called_once()
        self.wait_for_batch(dialog)
        self.assertEqual("disabled", str(dialog.save_button.cget("state")))
        self.assertEqual(2, dialog.plan.unchanged_count)
        with mock.patch("tab_tags.show_notice"), mock.patch.object(ableton_tags, "prepare_edit") as write:
            self.assertFalse(self.tab._edit_live_tags(self.paths, "Sounds|No", "add"))
            write.assert_not_called()
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))

    def test_batch_conflict_requires_new_review_and_preserves_concurrent_tags(self):
        dialog = self.open_batch()
        dialog.tag_var.set("Sounds|Planned")
        dialog.enqueue()
        dialog.review()
        self.wait_for_batch(dialog)
        ableton_tags.prepare_edit(self.paths[:1], "Sounds|Concurrent").commit()
        with mock.patch("live_tag_batch.ask_confirm", return_value=True), mock.patch(
            "live_tag_batch.messagebox.showerror"
        ) as error:
            dialog.save()
            self.wait_for_batch(dialog)
        self.assertIn("sidecars", error.call_args.args[1])
        self.assertIsNone(dialog.plan)
        self.assertEqual(1, len(dialog.operations))
        self.assertEqual(["Sounds|Concurrent"], ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual([], ableton_tags.sample_tags(self.paths[1]))

    def test_batch_cache_failure_reports_saved_and_clears_queue_to_prevent_repeat(self):
        dialog = self.open_batch()
        dialog.tag_var.set("Sounds|Saved")
        dialog.enqueue()
        dialog.review()
        self.wait_for_batch(dialog)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True), mock.patch.object(
            sorter_engine, "refresh_live_tag_cache", side_effect=ValueError("Stale index")
        ), mock.patch("live_tag_batch.messagebox.showerror") as error:
            dialog.save()
            self.wait_for_batch(dialog)
        self.assertIn("sidecars were saved", error.call_args.args[1])
        self.assertEqual([], dialog.operations)
        self.assertIsNone(dialog.plan)
        self.assertEqual(["Sounds|Saved"], ableton_tags.sample_tags(self.paths[0]))

    def test_batch_review_failure_reports_error_and_reenables_queue(self):
        dialog = self.open_batch()
        dialog.tag_var.set("Sounds|Planned")
        dialog.enqueue()
        with mock.patch.object(ableton_tags, "prepare_batch", side_effect=ValueError("Invalid metadata")), mock.patch(
            "live_tag_batch.messagebox.showerror"
        ) as error:
            dialog.review()
            self.wait_for_batch(dialog)
        self.assertIn("Invalid metadata", error.call_args.args[1])
        self.assertEqual("normal", str(dialog.queue_button.cget("state")))
        self.assertEqual("normal", str(dialog.save_button.cget("state")))

    def test_batch_rename_and_remove_share_one_review_and_preserve_unselected_sound(self):
        ableton_tags.prepare_edit(self.paths, "Sounds|Old").commit()
        ableton_tags.prepare_edit(self.paths, "Character|Remove").commit()
        self.select(self.paths[:1])
        self.tab._open_live_batch()
        dialog = self.tab._live_batch_dialog
        dialog.action_var.set("rename")
        dialog.tag_var.set("Sounds|Old")
        dialog.replacement_var.set("Instrument|Renamed")
        dialog.enqueue()
        dialog.action_var.set("remove")
        dialog.tag_var.set("Character|Remove")
        dialog.enqueue()
        dialog.review()
        self.wait_for_batch(dialog)
        self.assertIn("+ Instrument|Renamed", dialog.preview.get("1.0", "end"))
        self.assertIn("- Sounds|Old", dialog.preview.get("1.0", "end"))
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            dialog.save()
            self.wait_for_batch(dialog)
        self.assertEqual(["Instrument|Renamed"], ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual(["Character|Remove", "Sounds|Old"], ableton_tags.sample_tags(self.paths[1]))

    def test_batch_invalid_action_is_not_queued_and_empty_review_writes_nothing(self):
        dialog = self.open_batch()
        with mock.patch("live_tag_batch.show_notice") as notice:
            dialog.review()
        notice.assert_called_once()
        for action, tag, replacement in (
            ("rename", "Sounds|Valid", ""),
            ("add", "Sounds||Invalid", ""),
            ("unknown", "Sounds|Valid", ""),
        ):
            dialog.action_var.set(action)
            dialog.tag_var.set(tag)
            dialog.replacement_var.set(replacement)
            with mock.patch("live_tag_batch.messagebox.showerror") as error:
                dialog.enqueue()
            error.assert_called_once()
        self.assertEqual([], dialog.operations)
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))

    def test_batch_dialog_controls_fit_at_minimum_size(self):
        dialog = self.open_batch()
        self.assertFalse(dialog.replacement_entry.winfo_ismapped())
        self.assertFalse(dialog.listing.winfo_ismapped())
        dialog.tag_var.set("Sounds|First")
        dialog.enqueue()
        dialog.action_var.set("rename")
        dialog.geometry("680x620")
        self.root.update()
        self.assertGreaterEqual(dialog.preview.winfo_height(), 50)
        for control in (
            dialog.action_entry, dialog.tag_entry, dialog.replacement_entry, dialog.queue_button,
            dialog.remove_button, dialog.review_button, dialog.preview, dialog.close_button, dialog.save_button,
            dialog.assigned_tree, dialog.refresh_button, dialog.group_entry, dialog.vocabulary_button
        ):
            self.assertTrue(control.winfo_ismapped())
            self.assertGreater(control.winfo_height(), 10)
            self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), dialog.winfo_rootx() + dialog.winfo_width())
            self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), dialog.winfo_rooty() + dialog.winfo_height())

    def test_direct_preview_and_save_needs_no_queue_or_confirmation(self):
        self.select(self.paths[:1])
        self.tab._open_live_batch()
        dialog = self.tab._live_batch_dialog
        dialog.group_var.set("Genres")
        dialog.tag_var.set("Release test")
        dialog.review_button.invoke()
        self.wait_for_batch(dialog)
        self.assertEqual([], dialog.operations)
        self.assertIn(self.paths[0], dialog.preview.get("1.0", "end"))
        self.assertIn("+ Genres|Release test", dialog.preview.get("1.0", "end"))
        self.assertEqual([], ableton_tags.sample_tags(self.paths[0]))
        with mock.patch("live_tag_batch.ask_confirm") as confirm:
            dialog.save_button.invoke()
            self.wait_for_batch(dialog)
        confirm.assert_not_called()
        self.assertEqual(["Genres|Release test"], ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual([], ableton_tags.sample_tags(self.paths[1]))
        self.assertEqual("", dialog.tag_var.get())
        self.assertEqual("disabled", str(dialog.save_button.cget("state")))

    def test_save_without_preview_reviews_then_confirms_and_removes_assignment(self):
        ableton_tags.prepare_edit(self.paths[:1], "Genres|Release test").commit()
        sorter_engine.refresh_live_tag_cache(self.paths[:1])
        dialog = self.open_batch()
        dialog.assigned_tree.selection_set(dialog.assigned_tree.get_children()[0])
        self.root.update()
        self.assertEqual("remove", dialog.action_var.get())
        self.assertEqual("normal", str(dialog.save_button.cget("state")))
        with mock.patch("live_tag_batch.ask_confirm", return_value=True) as confirm:
            dialog.save_button.invoke()
            self.wait_for_batch(dialog)
        confirm.assert_called_once()
        self.assertIn("Remove: Genres|Release test", confirm.call_args.args[2])
        self.assertEqual([], ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual([], ableton_tags.sample_tags(self.paths[1]))
        self.assertIn("Changes saved.", dialog.status_var.get())

    def test_canceling_direct_save_confirmation_leaves_assignments_unchanged(self):
        ableton_tags.prepare_edit(self.paths[:1], "Genres|Keep").commit()
        sorter_engine.refresh_live_tag_cache(self.paths[:1])
        dialog = self.open_batch()
        dialog.assigned_tree.selection_set(dialog.assigned_tree.get_children()[0])
        self.root.update()
        with mock.patch("live_tag_batch.ask_confirm", return_value=False) as confirm:
            dialog.save_button.invoke()
            self.wait_for_batch(dialog)
        confirm.assert_called_once()
        self.assertEqual(["Genres|Keep"], ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual([], ableton_tags.sample_tags(self.paths[1]))
        self.assertIsNotNone(dialog.plan)
        self.assertIn("Nothing saved", dialog.status_var.get())

    def test_preview_includes_extra_change_and_current_edit_without_duplicate(self):
        dialog = self.open_batch()
        dialog.tag_var.set("Sounds|First")
        dialog.enqueue()
        self.assertEqual("", dialog.tag_var.get())
        dialog.tag_var.set("Character|Warm")
        dialog.review()
        self.wait_for_batch(dialog)
        first_preview = dialog.preview.get("1.0", "end")
        self.assertIn("+ Sounds|First", first_preview)
        self.assertIn("+ Character|Warm", first_preview)
        dialog.review()
        self.wait_for_batch(dialog)
        self.assertEqual(first_preview, dialog.preview.get("1.0", "end"))
        self.assertEqual(1, len(dialog.operations))
        dialog.tag_var.set("Character|Changed")
        self.assertIsNone(dialog.plan)
        self.assertEqual("normal", str(dialog.save_button.cget("state")))

    def test_inline_live_summary_counts_mixed_tags_and_keeps_exact_hierarchies(self):
        ableton_tags.prepare_edit(self.paths, "Sounds|Shared").commit()
        ableton_tags.prepare_edit(self.paths[:1], "Character|Only first").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.select(self.paths)
        self.assertEqual([
            ("Character|Only first", "1/2 some"), ("Sounds|Shared", "2/2 all")
        ], self.live_rows())
        dialog = self.suggestion_editor()
        first = dialog.assigned_tree.get_children()[0]
        dialog.assigned_tree.selection_set(first)
        self.root.update()
        self.assertEqual("Character|Only first", dialog.tag_var.get())
        self.tab._load_live_tag_suggestions()
        self.wait_for_vocabulary()
        self.assertEqual(
            ("Character|Only first", "Sounds|Shared"), dialog.tag_entry.cget("values")
        )
        self.show_error.assert_not_called()

    def wait_for_select_all(self):
        deadline = time.monotonic() + 3
        while self.tab._select_all_queue is not None and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertIsNone(self.tab._select_all_queue)

    def test_select_all_large_empty_search_does_not_summarize_on_ui_thread_or_repeat_on_select_page(self):
        import threading
        paths = [os.path.join(self.temp_dir.name, f"large-{index}.wav") for index in range(1200)]
        ui_thread = threading.get_ident()
        calls = []
        release = threading.Event()
        def summarize(selected):
            calls.append(threading.get_ident())
            if threading.get_ident() != ui_thread:
                release.wait(3)
            return {"live_counts": {}, "personal_counts": {}, "generated_counts": {}, "shared_personal_tags": []}
        try:
            with mock.patch.object(sorter_engine, "list_indexed_assets", return_value=self.paths + paths), mock.patch.object(
                sorter_engine, "summarize_asset_selection", side_effect=summarize
            ):
                self.tab._select_all_matching()
                self.wait_for_select_all()
                self.tab._select_page()
                self.root.update()
                self.assertNotIn(ui_thread, calls, "Large summaries must not block Tk")
                self.assertEqual(1, len(calls))
                self.assertEqual(set(self.paths + paths), self.tab._selection_paths)
                self.tab._clear_selection()
                release.set()
                deadline = time.monotonic() + 3
                while getattr(self.tab, "_selection_summary_queue", None) is not None and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(0.01)
                self.assertEqual("No sound selected", self.tab.selected_asset_var.get())
        finally:
            release.set()

    def test_large_selection_summary_finishes_and_reports_errors_without_stale_tags(self):
        paths = {os.path.join(self.temp_dir.name, f"large-{index}.wav") for index in range(1200)}
        for error in (None, ValueError("Selection changed externally")):
            with self.subTest(error=error):
                self.tab._selection_paths = paths
                self.tab._selection_revision += 1
                with mock.patch.object(
                    sorter_engine, "summarize_asset_selection",
                    side_effect=error,
                    return_value={"live_counts": {"Sounds|Snare": 1200}, "personal_counts": {"shared": 1200},
                                  "generated_counts": {"category:Snares": 1200}, "shared_personal_tags": ["shared"]}
                ):
                    self.tab._show_selected_asset()
                    self.assertEqual("disabled", self.tab.edit_live_tags_button.cget("state"))
                    self.assertEqual("disabled", self.tab.favorite_button.cget("state"))
                    deadline = time.monotonic() + 3
                    while self.tab._selection_summary_queue is not None and time.monotonic() < deadline:
                        self.root.update()
                        time.sleep(0.01)
                    self.assertIsNone(self.tab._selection_summary_queue)
                if error is None:
                    self.assertEqual([("Sounds|Snare", "1200/1200 all")], self.live_rows())
                    self.assertEqual("normal", self.tab.favorite_button.cget("state"))
                    self.assertNotIn("\nshared", self.tab.assigned_tags_text.get("1.0", "end"))
                else:
                    self.assertEqual("Selection is out of date", self.tab.selected_asset_var.get())
                    self.assertEqual([], self.live_rows())
                    self.assertEqual("disabled", self.tab.favorite_button.cget("state"))

    def test_select_page_accumulates_across_pages_and_clear_removes_everything(self):
        self.tab._page_size = 1
        self.tab._render_results(load_sidebar=False)
        self.tab._select_page()
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        self.tab._next_page()
        self.root.update()
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        self.assertEqual("1 sound selected (1 off page)", self.tab.selection_count_var.get())
        self.tab._select_page()
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        self.tab._previous_page()
        self.root.update()
        self.assertEqual(1, len(self.tab.asset_tree.selection()))
        self.assertEqual("2 sounds selected (1 off page)", self.tab.selection_count_var.get())
        self.tab.asset_tree.selection_remove(self.tab.asset_tree.selection())
        self.root.update()
        self.assertEqual(self.paths[1:], self.tab._selected_paths())
        self.tab._clear_selection()
        self.root.update()
        self.assertEqual("No sounds selected", self.tab.selection_count_var.get())
        self.assertEqual(set(), self.tab._selection_paths)

    def test_all_matching_is_captured_and_live_actions_include_off_page_sounds(self):
        self.tab._page_size = 1
        self.tab._render_results(load_sidebar=False)
        self.tab._select_all_matching()
        self.wait_for_select_all()
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        self.assertEqual("2 sounds selected (1 off page)", self.tab.selection_count_var.get())
        self.tab.live_tag_var.set("Character|Batch")
        self.preview_inline()
        batch = self.tab._live_batch_dialog
        self.wait_for_batch(batch)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True) as confirm:
            batch.save()
        self.wait_for_batch(batch)
        self.assertIn("1 off page", batch.selection_label.cget("text"))
        batch.close()
        self.assertEqual([("Character|Batch", "2/2 all")], self.live_rows())
        for path in self.paths:
            self.assertEqual(["Character|Batch"], ableton_tags.sample_tags(path))
        new_path = os.path.join(self.temp_dir.name, "third.wav")
        with open(new_path, "wb") as handle:
            handle.write(b"audio")
        sorter_engine.index_asset(new_path, self.temp_dir.name, "test", 1.0, [])
        self.tab._render_results(load_sidebar=False)
        self.assertEqual(set(self.paths), set(self.tab._selected_paths()))
        self.assertEqual([], ableton_tags.sample_tags(new_path))

    def test_filter_changes_clear_captured_selection_instead_of_hiding_targets(self):
        self.tab._select_all_matching()
        self.wait_for_select_all()
        self.tab.search_var.set("first")
        self.tab._apply_filter()
        self.root.update()
        self.assertEqual(set(), self.tab._selection_paths)
        self.assertEqual("No sounds selected", self.tab.selection_count_var.get())
        self.tab._select_all_matching()
        self.wait_for_select_all()
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        self.assertEqual("1 sound selected", self.tab.selection_count_var.get())

    def test_delayed_select_all_does_not_replace_changed_selection_or_filters(self):
        for change in ("selection", "filter"):
            with self.subTest(change=change):
                self.tab._clear_selection()
                scope = self.tab._current_selection_scope()
                revision = self.tab._selection_revision
                with mock.patch("tab_tags.threading.Thread"), mock.patch.object(self.tab, "after"):
                    self.tab._select_all_matching()
                if change == "selection":
                    self.select(self.paths[:1])
                else:
                    self.tab.search_var.set("second")
                self.tab._select_all_queue.put((self.paths, None))
                self.tab._finish_select_all(scope, revision)
                self.assertEqual(
                    set(self.paths[:1]) if change == "selection" else set(),
                    self.tab._selection_paths
                )
                self.assertIsNone(self.tab._select_all_queue)

    def test_failed_select_all_preserves_existing_selection_and_reports_error(self):
        self.select(self.paths[:1])
        with mock.patch.object(sorter_engine, "list_indexed_assets", side_effect=ValueError("Unavailable")):
            self.tab._select_all_matching()
            self.wait_for_select_all()
        self.assertEqual(self.paths[:1], self.tab._selected_paths())
        self.assertIn("Unavailable", self.show_error.call_args.args[1])


    def test_stale_off_page_index_disables_writes_and_library_change_clears_selection(self):
        self.tab._page_size = 1
        self.tab._render_results(load_sidebar=False)
        self.tab._select_all_matching()
        self.wait_for_select_all()
        connection = sorter_engine._asset_index_connection()
        with connection:
            connection.execute("DELETE FROM assets WHERE path = ?", (self.paths[1],))
        connection.close()
        self.tab._show_selected_asset()
        self.assertEqual("disabled", self.tab.edit_live_tags_button.cget("state"))
        self.assertEqual("disabled", self.tab.favorite_button.cget("state"))
        self.tab.invalidate_library()
        self.root.update()
        self.assertEqual(set(), self.tab._selection_paths)

    def test_multiple_selected_sounds_cannot_use_single_sound_playback(self):
        self.select(self.paths)
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.tab._selected_path()

    def test_inline_apply_and_remove_only_change_frozen_selected_paths(self):
        ableton_tags.prepare_edit(self.paths[:1], "Sounds|Partial").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.select(self.paths)
        self.tab.live_tag_var.set("Sounds|Partial")
        with mock.patch("tab_tags.ask_confirm", return_value=True):
            self.preview_inline()
        self.finish_inline_change()
        self.assertEqual([("Sounds|Partial", "2/2 all")], self.live_rows())
        self.select(self.paths[:1])
        with mock.patch("tab_tags.ask_confirm", return_value=True):
            self.preview_inline("remove")
        self.finish_inline_change()
        self.assertEqual([], ableton_tags.sample_tags(self.paths[0]))
        self.assertEqual(["Sounds|Partial"], ableton_tags.sample_tags(self.paths[1]))
        self.assertNotIn("only-first", sorter_engine.get_asset_tags(self.paths[0]))
        self.show_error.assert_not_called()

    def test_inline_cancel_and_invalid_tag_never_write_sidecars(self):
        self.select(self.paths)
        self.tab.live_tag_var.set("Sounds|Cancelled")
        with mock.patch("tab_tags.ask_confirm", return_value=False):
            self.preview_inline()
        self.finish_inline_change(save=False)
        self.tab.live_tag_var.set("Sounds||Invalid")
        self.preview_inline()
        self.show_error.assert_called_once()
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))

    def test_existing_dialog_cannot_write_during_selected_refresh(self):
        self.tab._live_refresh_queue = mock.Mock()
        try:
            with mock.patch("tab_tags.show_notice") as notice, mock.patch.object(
                ableton_tags, "prepare_edit"
            ) as prepare:
                self.assertFalse(self.tab._edit_live_tags(self.paths, "Sounds|No", "add"))
            notice.assert_called_once()
            prepare.assert_not_called()
        finally:
            self.tab._live_refresh_queue = None

    def test_suggestion_failure_reports_error_and_retains_old_choices(self):
        dialog = self.suggestion_editor()
        dialog.tag_entry.configure(values=("Sounds|Stale",))
        with mock.patch.object(sorter_engine, "list_indexed_tags", side_effect=ValueError("Unavailable index")):
            self.tab._load_live_tag_suggestions()
            self.wait_for_vocabulary()
        self.assertEqual(("Sounds|Stale",), dialog.tag_entry.cget("values"))
        self.assertIn("Unavailable index", self.show_error.call_args.args[1])

    def test_slow_dropdown_query_is_background_single_flight_and_cached(self):
        dialog = self.suggestion_editor()
        release = threading.Event()
        threads = []
        def read(**_kwargs):
            threads.append(threading.current_thread())
            if not release.wait(3):
                raise ValueError("Test reader timed out")
            return [("ableton:Genres|Ambient", 5)]
        with mock.patch.object(sorter_engine, "list_indexed_tags", side_effect=read) as scan:
            try:
                start = time.perf_counter()
                for _ in range(10):
                    self.tab._load_live_tag_suggestions()
                self.assertLess(time.perf_counter() - start, 0.1)
                self.assertEqual(1, scan.call_count)
                heartbeat = []
                self.root.after(0, lambda: heartbeat.append(True))
                self.root.update()
                self.assertEqual([True], heartbeat)
            finally:
                release.set()
            self.wait_for_vocabulary()
            self.assertTrue(all(thread is not threading.main_thread() for thread in threads))
            self.assertIn("Genres|Ambient", dialog.tag_entry.cget("values"))
            self.tab.live_group_var.set("Keep custom group")
            self.tab.live_tag_var.set("Keep typed tag")
            for _ in range(10):
                self.tab._load_live_tag_suggestions()
            self.assertEqual(1, scan.call_count)
            self.assertEqual("Keep typed tag", self.tab.live_tag_var.get())
            self.assertEqual("Keep custom group", self.tab.live_group_var.get())
            self.tab._tag_suggestions_revision += 1
            self.tab._load_live_tag_suggestions()
            self.wait_for_vocabulary()
            self.assertEqual(2, scan.call_count)


    def test_suggestion_invalidation_discards_stale_read_and_updates_open_editors(self):
        release = threading.Event()
        started = threading.Event()
        calls = []
        def read(**_kwargs):
            calls.append(True)
            if len(calls) == 1:
                started.set()
                if not release.wait(3):
                    raise ValueError("Test reader timed out")
                return [("ableton:Workflow|Old", 1)]
            return [("ableton:Workflow|Current", 1)]
        self.select(self.paths)
        with mock.patch.object(sorter_engine, "list_indexed_tags", side_effect=read):
            try:
                self.tab._load_live_tag_suggestions()
                self.assertTrue(started.wait(1))
                self.tab._tag_suggestions_revision += 1
                self.tab._open_live_batch()
                batch = self.tab._live_batch_dialog
                self.tab._load_live_tag_suggestions()
            finally:
                release.set()
            self.wait_for_vocabulary()
            self.assertEqual(2, len(calls))
            self.assertNotIn("Workflow|Old", batch.tag_entry.cget("values"))
            self.assertIn("Workflow|Current", batch.tag_entry.cget("values"))
            tag_entry, group_entry = batch.tag_entry, batch.group_entry
            self.tab._live_vocabulary = ("Genres|Ambient",)
            self.tab._update_tag_suggestion_choices()
            self.assertIn("Genres|Ambient", tag_entry.cget("values"))
            self.assertIn("Genres", group_entry.cget("values"))

    def test_watcher_refresh_invalidates_dropdown_cache(self):
        self.tab._metadata_queue = queue.Queue()
        self.tab._metadata_queue.put(("refreshed", {}, None))
        before = self.tab._tag_suggestions_revision
        self.tab._finish_metadata_poll(gui_theme.USER_LIBRARY_PATH)
        self.assertGreater(self.tab._tag_suggestions_revision, before)

    def test_selection_edit_planning_does_not_block_tk(self):
        release = threading.Event()
        started = threading.Event()
        original = ableton_tags.prepare_batch
        def delayed(*args, **kwargs):
            started.set()
            if not release.wait(3):
                raise ValueError("Timed out waiting for test release")
            return original(*args, **kwargs)
        with mock.patch.object(ableton_tags, "prepare_batch", side_effect=delayed):
            try:
                before = time.monotonic()
                self.assertTrue(self.tab._edit_live_tags(self.paths, "Drums|Kick", "add"))
                self.assertLess(time.monotonic() - before, 0.5)
                self.assertTrue(started.wait(1))
                heartbeat = []
                self.root.after(0, lambda: heartbeat.append(True))
                self.root.update()
                self.assertEqual([True], heartbeat)
                self.assertTrue(self.tab._live_batch_dialog.busy)
            finally:
                release.set()
            self.wait_for_batch(self.tab._live_batch_dialog)
        self.assertEqual([], ableton_tags.sample_tags(self.paths[0]))

    def test_selected_live_refresh_reads_external_changes_without_writing(self):
        ableton_tags.prepare_edit(self.paths, "Sounds|External").commit()
        self.select(self.paths[:1])
        with mock.patch.object(ableton_tags.TagEdit, "commit") as write:
            self.tab._refresh_selected_live_tags()
            self.assertEqual("disabled", self.tab.edit_live_tags_button.cget("state"))
            self.select(self.paths[1:])
            self.wait_for_live_refresh()
            write.assert_not_called()
        self.assertEqual(["Sounds|External"], sorter_engine.get_indexed_asset(self.paths[0])["ableton_tags"])
        self.assertEqual([], sorter_engine.get_indexed_asset(self.paths[1])["ableton_tags"])
        self.assertEqual(self.paths[1:], self.tab._selected_paths())
        self.assertEqual([], self.live_rows())
        self.show_error.assert_not_called()

    def test_selected_live_refresh_error_reenables_controls_and_keeps_cache(self):
        ableton_tags.prepare_edit(self.paths, "Sounds|Keep").commit()
        sorter_engine.refresh_live_tag_cache(self.paths)
        self.select(self.paths)
        with mock.patch.object(sorter_engine, "refresh_live_tag_cache", side_effect=ValueError("Invalid XMP")):
            self.tab._refresh_selected_live_tags()
            self.wait_for_live_refresh()
        self.assertEqual("normal", self.tab.edit_live_tags_button.cget("state"))
        self.assertEqual([("Sounds|Keep", "2/2 all")], self.live_rows())
        self.assertIn("Invalid XMP", self.show_error.call_args.args[1])


    def test_explicit_live_edit_confirms_writes_and_refreshes(self):
        self.select(self.paths)
        self.assertTrue(self.tab._edit_live_tags(self.paths, "Sounds|Shared", "add"))
        batch = self.tab._live_batch_dialog
        self.wait_for_batch(batch)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True) as confirm:
            batch.save()
        self.wait_for_batch(batch)
        self.assertIn("2 selected sounds", batch.selection_label.cget("text"))
        for path in self.paths:
            self.assertEqual(["Sounds|Shared"], ableton_tags.sample_tags(path))
            self.assertEqual(["Sounds|Shared"], sorter_engine.get_indexed_asset(path)["ableton_tags"])
        batch.close()
        self.assertTrue(self.tab._edit_live_tags(
            self.paths, "Sounds|Shared", "rename", "Character|Renamed"
        ))
        batch = self.tab._live_batch_dialog
        self.wait_for_batch(batch)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            batch.save()
        self.wait_for_batch(batch)
        for path in self.paths:
            self.assertEqual(["Character|Renamed"], ableton_tags.sample_tags(path))
        self.show_error.assert_not_called()

    def test_cancelled_live_edit_does_not_create_sidecars(self):
        self.assertTrue(self.tab._edit_live_tags(self.paths, "Sounds|No", "add"))
        batch = self.tab._live_batch_dialog
        self.wait_for_batch(batch)
        with mock.patch("live_tag_batch.ask_confirm", return_value=False):
            batch.close()
        self.assertFalse(os.path.isdir(os.path.join(self.temp_dir.name, "Ableton Folder Info")))
        self.show_error.assert_not_called()

    def test_live_cache_error_explicitly_reports_that_sidecars_were_saved(self):
        self.assertTrue(self.tab._edit_live_tags(self.paths, "Sounds|Saved", "add"))
        batch = self.tab._live_batch_dialog
        self.wait_for_batch(batch)
        with mock.patch("live_tag_batch.ask_confirm", return_value=True), mock.patch(
            "tab_tags.sorter_engine.refresh_live_tag_cache", side_effect=ValueError("Stale index")
        ):
            batch.save()
            self.wait_for_batch(batch)
        self.assertIn("sidecars were saved", self.show_error.call_args.args[1])
        self.assertEqual(["Sounds|Saved"], ableton_tags.sample_tags(self.paths[0]))


    def test_saved_collection_round_trip_updates_sidebar_and_results(self):
        self.tab.search_var.set("first")
        self.tab.active_tag_filter = "category:Kicks"
        with mock.patch("tab_tags.ask_fields", return_value=["First sounds"]):
            self.tab.save_collection_button.invoke()
        self.assertEqual(("First sounds",), self.tab.saved_collection_list.get(0, "end"))
        with open(self.tab._saved_searches_file(), encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual("first", saved[0]["text"])
        self.tab._clear_all_filters()
        self.root.update()
        self.assertEqual(2, len(self.tab._asset_paths))
        self.tab.collection_tabs.select(1)
        self.root.update()
        self.tab.saved_collection_list.selection_set(0)
        self.tab.saved_collection_list.event_generate("<<ListboxSelect>>")
        self.root.update()
        self.assertEqual("first", self.tab.search_var.get())
        self.assertEqual("category:Kicks", self.tab.active_tag_filter)
        self.assertEqual([self.paths[0]], list(self.tab._asset_paths.values()))
        self.assertEqual((0,), self.tab.saved_collection_list.curselection())
        self.show_error.assert_not_called()

    def test_clear_chips_independently_and_clear_all(self):
        self.tab.search_var.set("first")
        self.tab._active_collection = "Favorites"
        self.tab.favorites_only = True
        self.tab.active_tag_filter = "shared"
        self.tab._page_index = 5
        self.tab._render_results(load_sidebar=False)
        chips = self.tab.filter_chips.winfo_children()
        self.assertEqual(4, len(chips))
        chips[0].invoke()
        self.assertEqual("", self.tab.search_var.get())
        self.assertEqual("Favorites", self.tab._active_collection)
        self.assertEqual("shared", self.tab.active_tag_filter)
        self.assertEqual(0, self.tab._page_index)
        self.tab._clear_filter("collection")
        self.assertEqual("All sounds", self.tab._active_collection)
        self.assertFalse(self.tab.favorites_only)
        self.assertEqual("shared", self.tab.active_tag_filter)
        self.tab._clear_filter("tag")
        self.root.update()
        self.assertEqual(2, len(self.tab._asset_paths))
        self.assertEqual([], self.tab.filter_chips.winfo_children())
        self.tab.search_var.set("first")
        self.tab._render_results(load_sidebar=False)
        clear_all = self.tab.filter_chips.winfo_children()[-1]
        self.assertEqual("Clear all", clear_all.cget("text"))
        clear_all.invoke()
        self.assertEqual(2, len(self.tab._asset_paths))
        self.show_error.assert_not_called()

    def test_long_filter_chips_fit_at_minimum_width(self):
        self.tab.search_var.set("a long search " * 20)
        self.tab._active_collection = "One-shots"
        self.tab.active_tag_filter = "a-long-personal-tag-" * 4
        self.tab._refresh_filter_chips()
        self.root.update()
        right_edge = self.root.winfo_rootx() + self.root.winfo_width()
        for chip in self.tab.filter_chips.winfo_children():
            self.assertLess(chip.winfo_rootx() + chip.winfo_width(), right_edge)
        self.assertGreater(self.tab.assigned_tags_text.winfo_height(), 20)

    def test_saved_collection_replacement_delete_and_restart(self):
        self.tab.search_var.set("first")
        with mock.patch("tab_tags.ask_fields", return_value=["My sounds"]):
            self.tab._save_current_search()
        self.tab.search_var.set("second")
        with mock.patch("tab_tags.ask_fields", return_value=["my sounds"]):
            self.tab._save_current_search()
        self.assertEqual(1, len(self.tab._saved_collections))
        self.assertEqual("second", self.tab._saved_collections[0]["text"])
        other = TagsTab(self.root)
        self.assertEqual(("my sounds",), other.saved_collection_list.get(0, "end"))
        self.tab.saved_collection_list.selection_set(0)
        with mock.patch("tab_tags.ask_confirm", return_value=False):
            self.tab.delete_collection_button.invoke()
        self.assertEqual(1, len(self.tab._saved_collections))
        with mock.patch("tab_tags.ask_confirm", return_value=True):
            self.tab.delete_collection_button.invoke()
        self.assertEqual([], self.tab._saved_collections)
        self.assertEqual([], self.tab._load_saved_searches())
        for path in self.paths:
            self.assertTrue(os.path.isfile(path))
            self.assertTrue(any(tag.startswith("category:") for tag in sorter_engine.get_asset_tags(path)))
        self.show_error.assert_not_called()

    def test_corrupt_saved_views_are_reported_and_not_overwritten(self):
        path = self.tab._saved_searches_file()
        for contents in ("{broken", '{"unexpected": true}', '[{"name": "Bad", "text": 1}]'):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(contents)
            self.tab._refresh_saved_collections()
            self.assertEqual([], self.tab._saved_collections)
            self.tab.search_var.set("first")
            with mock.patch("tab_tags.ask_fields", return_value=["New"]):
                self.tab._save_current_search()
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(contents, handle.read())
        self.assertEqual(6, self.show_error.call_count)

    def test_failed_collection_write_preserves_existing_file(self):
        items = [{"name": "Existing", "text": "first"}]
        self.assertTrue(self.tab._write_saved_searches(items))
        with mock.patch("tab_tags.os.replace", side_effect=PermissionError("Locked")):
            self.assertFalse(self.tab._write_saved_searches([{"name": "New"}]))
        self.assertEqual(items, self.tab._load_saved_searches())
        self.assertEqual([], [
            name for name in os.listdir(self.temp_dir.name) if name.endswith(".tmp")
        ])
        self.show_error.assert_called_once()


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

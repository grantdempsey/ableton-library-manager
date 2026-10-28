import gc
import hashlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest import mock

import gui_theme
import ableton_tags
import live_catalog
from live_catalog_dialog import LiveCatalogDialog
import sorter_engine


class LiveCatalogTests(unittest.TestCase):
    def test_destroy_cancels_pending_catalog_callbacks(self):
        root = tk.Tk()
        try:
            with mock.patch.object(live_catalog, "available_databases", return_value=()):
                dialog = LiveCatalogDialog(root)
            called = []
            dialog._schedule(10000, lambda: called.append(True))
            identifiers = set(dialog._pending_callbacks)
            self.assertTrue(identifiers)
            dialog.destroy()
            remaining = set(root.tk.splitlist(root.tk.call("after", "info")))
            self.assertTrue(identifiers.isdisjoint(remaining))
            root.update()
            self.assertEqual([], called)
        finally:
            root.destroy()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "Live-files-test.db"
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                "CREATE TABLE files(file_id INTEGER, parent_id INTEGER, name TEXT, file_type INTEGER DEFAULT 0);"
                "CREATE TABLE keywords(file_id INTEGER, keyw_id INTEGER, is_auto INTEGER);"
                "CREATE TABLE metadata(file_id INTEGER, key INTEGER, value_id INTEGER);"
                "CREATE TABLE metadata_values(id INTEGER, value TEXT);"
            )
            root = os.path.abspath(os.sep)
            connection.executemany("INSERT INTO files(file_id,parent_id,name) VALUES (?, ?, ?)", [
                (1, 0, root), (2, 1, "Core Library"), (3, 2, "same.wav"),
                (4, 1, "Packs"), (5, 4, "same.wav"), (6, 0, "<keywords>"),
                (7, 6, "Sounds"), (8, 7, "Bass"), (9, 8, "Synth Bass"),
                (10, 4, "plain.wav"),
                (11, 6, "Genres"), (12, 11, "Hip Hop"), (13, 11, "Unused"),
            ])
            connection.executemany("INSERT INTO keywords VALUES (?, ?, ?)", [
                (3, 9, 1), (5, 8, 0)
            ])
            connection.execute("INSERT INTO metadata_values VALUES (1, 'Genres|Hip Hop')")
            connection.execute("INSERT INTO metadata VALUES (3, 1264941431, 1)")
            connection.commit()
        finally:
            connection.close()

    def create_browser(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        def cleanup():
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                root.tk.call("after", "cancel", callback)
            root.destroy()
            gc.collect()
        self.addCleanup(cleanup)
        with mock.patch("live_catalog.available_databases", return_value=()):
            browser = LiveCatalogDialog(root)
        return root, browser

    def wait_for_query(self, root, browser):
        deadline = time.monotonic() + 3
        while browser._query_results is not None and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        self.assertIsNone(browser._query_results)

    def test_slow_catalog_load_shows_animated_banner_until_success_or_failure(self):
        root, browser = self.create_browser()
        browser.database.set("test.db")
        for outcome in ((live_catalog.CatalogSample("one.wav", (), (), ()),), ValueError("Read failed")):
            with self.subTest(outcome=outcome):
                release = threading.Event()
                def read(*_args, **_kwargs):
                    if not release.wait(3):
                        raise ValueError("Test reader timed out")
                    if isinstance(outcome, Exception):
                        raise outcome
                    return outcome
                with mock.patch("live_catalog.read_catalog", side_effect=read), mock.patch(
                    "live_catalog.read_vocabulary", return_value=()
                ), mock.patch("live_catalog.read_user_sidecars", side_effect=lambda samples, _root: samples):
                    try:
                        browser.load()
                        root.update()
                        self.assertTrue(browser.loading_banner.winfo_ismapped())
                        self.assertEqual("Loading Ableton catalog", browser.loading_heading.cget("text"))
                        self.assertEqual("place", browser.loading_banner.winfo_manager())
                        self.assertEqual(
                            browser.loading_banner.master.winfo_width(),
                            browser.loading_banner.winfo_width()
                        )
                        self.assertEqual(
                            browser.loading_banner.master.winfo_height(),
                            browser.loading_banner.winfo_height()
                        )
                        self.assertGreater(browser.loading_banner.winfo_height(), 150)
                        self.assertGreaterEqual(
                            int(browser.loading_heading.cget("font").split()[2]), 20
                        )
                        self.assertFalse(browser.detail_frame.winfo_ismapped())
                        self.assertIn("tens of seconds", browser.loading_message.get())
                        self.assertEqual("indeterminate", str(browser.loading_progress.cget("mode")))
                        start = float(browser.loading_progress.cget("value"))
                        deadline = time.monotonic() + 0.15
                        while time.monotonic() < deadline:
                            root.update()
                            time.sleep(0.01)
                        self.assertNotEqual(start, float(browser.loading_progress.cget("value")))
                        self.assertTrue(browser.reload_button.instate(["disabled"]))
                    finally:
                        release.set()
                    deadline = time.monotonic() + 3
                    while browser.results is not None and time.monotonic() < deadline:
                        root.update()
                        time.sleep(0.01)
                self.assertIsNone(browser.results)
                self.assertFalse(browser.loading_banner.winfo_ismapped())
                root.update()
                self.assertTrue(browser.detail_frame.winfo_ismapped())
                self.assertEqual(0, float(browser.loading_progress.cget("value")))
                self.assertFalse(browser.reload_button.instate(["disabled"]))
                if isinstance(outcome, Exception):
                    self.assertIn("Read failed", browser.status.get())
                    self.assertEqual("one.wav", browser.samples[0].path)

    def test_tag_clicks_replace_control_toggle_and_shift_extend_after_filter_refresh(self):
        self.check_tag_modifier_clicks(3)

    def test_tag_modifier_clicks_survive_background_filter_refresh(self):
        self.check_tag_modifier_clicks(600)

    def check_tag_modifier_clicks(self, sample_count):
        root, browser = self.create_browser()
        tags = ("Character|Acoustic", "Character|Bright", "Character|Warm")
        browser.samples = tuple(
            live_catalog.CatalogSample(f"item{index}.wav", (tags[index % len(tags)],), (), ())
            for index in range(sample_count)
        )
        browser.apply()
        self.wait_for_query(root, browser)
        root.update()
        def click(tag, state=0):
            index = browser.tag_rows.index(tag)
            browser.tags.see(index)
            root.update()
            x, y, width, height = browser.tags.bbox(index)
            browser.tags.event_generate("<ButtonPress-1>", x=x + 5, y=y + height // 2, state=state)
            browser.tags.event_generate("<ButtonRelease-1>", x=x + 5, y=y + height // 2, state=state)
            root.update()
            self.wait_for_query(root, browser)
        click("Character|Acoustic")
        self.assertEqual({"Character|Acoustic"}, browser.active_tags)
        click("Character|Bright")
        self.assertEqual({"Character|Bright"}, browser.active_tags)
        click("Character|Acoustic", state=4)
        self.assertEqual({"Character|Acoustic", "Character|Bright"}, browser.active_tags)
        click("Character|Bright", state=4)
        self.assertEqual({"Character|Acoustic"}, browser.active_tags)
        click("Character|Acoustic")
        click("Character|Warm", state=1)
        self.assertEqual({"Character|Acoustic", "Character|Bright", "Character|Warm"}, browser.active_tags)
        click("Character|Bright")
        self.assertEqual({"Character|Bright"}, browser.active_tags)
        browser.clear_tag()
        self.assertEqual(set(), browser.active_tags)
        self.assertIn("Shift-click", browser.selected_filters.get())

    def test_catalog_actual_theme_contrast_filter_explanations_and_scrollable_details(self):
        root, browser = self.create_browser()
        loader = importlib.machinery.SourceFileLoader(
            "catalog_theme_test", str(Path(__file__).resolve().parent.parent / "AbletonLibraryManager.pyw")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        module.ProductionStudioManagerApp.set_application_styling_theme(root)
        # Construct after the application theme, as happens in the real Library.
        browser.destroy()
        with mock.patch("live_catalog.available_databases", return_value=()):
            browser = LiveCatalogDialog(root)
        browser.samples = (
            live_catalog.CatalogSample(
                "bright.adv", ("Character|Bright",), (), ("Genres|Ambient",), "Device preset",
                metadata_details=tuple(f"Field {index}: value" for index in range(30))
            ),
            live_catalog.CatalogSample("acoustic.adv", ("Character|Acoustic",), (), (), "Device preset"),
        )
        browser.active_tags = {"Character|Bright", "Character|Acoustic"}
        browser.apply()
        root.update()
        self.assertIn(" OR ", browser.selected_filters.get())
        self.assertEqual(2, len(browser.rows))
        children = browser.sounds.get_children()
        browser.sounds.selection_set(children[0])
        root.update()
        browser.show_details()
        text = browser.details.get("1.0", "end")
        self.assertIn("Matched filters: Character|Bright", text)
        self.assertIn("need not match every alternative", text)
        self.assertTrue(browser.details.cget("yscrollcommand"))
        self.assertTrue(browser.sounds.cget("xscrollcommand"))
        browser.details.yview_moveto(1)
        root.update()
        self.assertGreater(browser.details.yview()[0], 0)
        style = ttk.Style(root)
        def luminance(color):
            channels = [part / 65535 for part in root.winfo_rgb(color)]
            linear = [part / 12.92 if part <= 0.04045 else ((part + 0.055) / 1.055) ** 2.4 for part in channels]
            return sum(part * weight for part, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        def contrast(foreground, background):
            values = sorted((luminance(foreground), luminance(background)))
            return (values[1] + 0.05) / (values[0] + 0.05)
        for foreground, background in (
            (browser.tags.cget("foreground"), browser.tags.cget("background")),
            (browser.tags.cget("selectforeground"), browser.tags.cget("selectbackground")),
            (browser.details.cget("foreground"), browser.details.cget("background")),
            (style.lookup("Catalog.Treeview", "foreground", ("selected",)),
             style.lookup("Catalog.Treeview", "background", ("selected",))),
        ):
            self.assertGreaterEqual(contrast(foreground, background), 4.5)
        self.assertNotEqual(style.lookup("Catalog.Treeview", "background"), gui_theme.THEME["bg_dark"])
        self.assertEqual(gui_theme.THEME["tag_enabled"], browser.tags.cget("selectbackground"))
        self.assertEqual(gui_theme.THEME["tag_enabled"],
                         style.lookup("Catalog.Treeview", "background", ("selected",)))
        self.assertEqual(gui_theme.THEME["btn_secondary_hover"],
                         style.lookup("Catalog.Treeview.Heading", "background", ("active",)))
        self.assertEqual(gui_theme.THEME["fg_light"],
                         style.lookup("Catalog.Treeview.Heading", "foreground", ("active",)))
        self.assertEqual(("alternate",), browser.sounds.item(children[1], "tags"))
        self.assertIn("Character", browser.tags.get(0))
        self.assertNotIn("|", browser.tags.get(1))

    def test_user_sidecars_include_non_audio_exact_paths_without_changing_provenance(self):
        root = Path(self.temporary.name, "User Library")
        root.mkdir()
        samples = []
        for folder, name, item_type in (
            ("Racks", "same.adg", "Rack"), ("Other", "same.adg", "Rack"),
            ("Clips", "clip.alc", "Clip"), ("MIDI", "notes.mid", "MIDI"),
            ("Presets", "preset.adv", "Device preset"), ("Grooves", "swing.agr", "Groove"),
            ("Tunings", "scale.ascl", "Tuning"), ("Devices", "device.amxd", "Max device"),
            ("Sets", "set.als", "Live Set"),
        ):
            path = root / folder / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"unchanged content")
            samples.append(live_catalog.CatalogSample(
                str(path), ("Genres|Factory",), ("Sounds|Bass",), ("Character|Bright",), item_type
            ))
        outside = Path(self.temporary.name, "User Library-other", "same.adg")
        outside.parent.mkdir()
        outside.write_bytes(b"protected")
        samples.append(live_catalog.CatalogSample(str(outside), (), (), (), "Rack"))
        for sample in samples:
            if Path(sample.path).parent.name != "Other":
                ableton_tags.prepare_edit([sample.path], "My Group|Workflow|Favorite").commit()
        ableton_tags.prepare_edit([samples[0].path], "Genres|Ambient").commit()
        before = {
            path: hashlib.sha256(path.read_bytes()).digest()
            for path in Path(self.temporary.name).rglob("*") if path.is_file()
        }
        with mock.patch.object(sorter_engine, "_asset_index_connection", side_effect=AssertionError("No index access")), mock.patch.object(
            ableton_tags.TagEdit, "commit", side_effect=AssertionError("No sidecar writes")
        ):
            refreshed = live_catalog.read_user_sidecars(samples, str(root))
        self.assertIn("Genres|Ambient", refreshed[0].manual)
        self.assertEqual((), refreshed[1].manual)
        self.assertEqual((), refreshed[-1].manual)
        for original, sample in zip(samples, refreshed):
            self.assertEqual(original.non_auto, sample.non_auto)
            self.assertEqual(original.automatic, sample.automatic)
            self.assertEqual(original.factory, sample.factory)
            self.assertEqual((), original.manual)
        found, counts = live_catalog.filter_catalog(refreshed, source="User Library sidecars", tag="My Group")
        self.assertEqual(8, len(found))
        self.assertEqual(8, counts["My Group"])
        self.assertEqual([], live_catalog.filter_catalog(refreshed, source="Non-auto (catalog)", tag="My Group")[0])
        after = {
            path: hashlib.sha256(path.read_bytes()).digest()
            for path in Path(self.temporary.name).rglob("*") if path.is_file()
        }
        self.assertEqual(before, after)
        ableton_tags.prepare_edit([samples[0].path], "Genres|Ambient", remove=True).commit()
        reread = live_catalog.read_user_sidecars(refreshed, str(root))
        self.assertNotIn("Genres|Ambient", reread[0].manual)
        with self.assertRaisesRegex(ValueError, "absolute User Library"):
            live_catalog.read_user_sidecars(samples, "")
        with self.assertRaisesRegex(OSError, "User Library is unavailable"):
            live_catalog.read_user_sidecars(samples, str(root / "missing"))

    def test_sidecar_catalog_scope_rejects_resolved_links_outside_user_library(self):
        root = Path(self.temporary.name, "User Library")
        root.mkdir()
        inside = str(root / "rack.adg")
        escaped = str(root / "linked" / "rack.adg")
        outside = str(Path(self.temporary.name, "Packs", "rack.adg"))
        samples = (
            live_catalog.CatalogSample(inside, (), (), (), "Rack"),
            live_catalog.CatalogSample(escaped, (), (), (), "Rack", manual=("Workflow|Stale",)),
        )
        original = os.path.realpath
        def resolve(path):
            return outside if path == escaped else original(path)
        with mock.patch("live_catalog.os.path.realpath", side_effect=resolve), mock.patch.object(
            ableton_tags, "read_sample_assignments", return_value={}
        ) as read:
            result = live_catalog.read_user_sidecars(samples, str(root))
        read.assert_called_once_with([inside])
        self.assertEqual((), result[1].manual)

    def test_sidecar_catalog_read_failure_retains_previous_browser_snapshot(self):
        root, browser = self.create_browser()
        previous = (live_catalog.CatalogSample("previous.wav", (), (), ()),)
        browser.samples = previous
        browser.vocabulary = ("Sounds|Previous",)
        browser.database.set(str(self.database))
        with mock.patch("live_catalog.read_user_sidecars", side_effect=ValueError("Invalid non-audio sidecar")):
            browser.load()
            deadline = time.monotonic() + 3
            while browser.results is not None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
        self.assertIsNone(browser.results)
        self.assertIs(previous, browser.samples)
        self.assertEqual(("Sounds|Previous",), browser.vocabulary)
        self.assertIn("Invalid non-audio sidecar", browser.status.get())

    def test_sidecar_catalog_refresh_exposes_fresh_custom_vocabulary_and_source(self):
        root, browser = self.create_browser()
        path = Path(self.temporary.name, "rack.adg")
        path.write_bytes(b"rack")
        ableton_tags.prepare_edit([str(path)], "Workflow|Custom|Favorite").commit()
        sample = live_catalog.CatalogSample(str(path), (), (), ("Genres|Ambient",), "Rack")
        browser.database.set(str(self.database))
        with mock.patch.object(gui_theme, "USER_LIBRARY_PATH", self.temporary.name), mock.patch(
            "live_catalog.read_catalog", return_value=(sample,)
        ):
            browser.load()
            deadline = time.monotonic() + 3
            while browser.results is not None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
        self.assertIsNone(browser.results)
        self.assertIn("Workflow|Custom|Favorite", browser.vocabulary)
        self.assertIn("Workflow", browser.group_picker.cget("values"))
        browser.source.set("User Library sidecars")
        browser.group.set("Workflow")
        browser.apply()
        self.assertEqual(1, len(browser.rows))
        browser.sounds.selection_set(browser.sounds.get_children()[0])
        browser.show_details()
        self.assertIn("Workflow|Custom|Favorite", browser.details.get("1.0", "end"))
        self.assertIn("User Library sidecars", browser.details.get("1.0", "end"))

    def test_reads_sources_exact_paths_and_genres_without_writing(self):
        before = hashlib.sha256(self.database.read_bytes()).digest()
        with mock.patch.object(sorter_engine, "_asset_index_connection", side_effect=AssertionError("Must not use manager index")):
            samples = live_catalog.read_catalog(self.database)
        self.assertEqual(3, len(samples))
        genres, counts = live_catalog.filter_catalog(samples, group="Genres")
        self.assertEqual(1, len(genres))
        self.assertEqual({"Genres": 1, "Genres|Hip Hop": 1}, counts)
        self.assertEqual(("Sounds|Bass|Synth Bass",), genres[0].automatic)
        self.assertEqual((), genres[0].non_auto)
        non_auto, _ = live_catalog.filter_catalog(samples, source="Non-auto (catalog)")
        self.assertEqual(1, len(non_auto))
        self.assertNotEqual(genres[0].path, non_auto[0].path)
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).digest())

    def test_search_tag_source_and_unknown_filters(self):
        samples = live_catalog.read_catalog(self.database)
        matching, _ = live_catalog.filter_catalog(samples, search="Core Hip Hop", tag="Genres|Hip Hop")
        self.assertEqual(1, len(matching))
        self.assertEqual([], live_catalog.filter_catalog(samples, group="Genres", source="Automatic")[0])
        self.assertEqual([], live_catalog.filter_catalog(samples, search="does-not-exist")[0])
        with self.assertRaises(ValueError):
            live_catalog.filter_catalog(samples, source="unknown")

    def test_parent_filters_include_descendants_and_count_each_item_once(self):
        samples = (
            live_catalog.CatalogSample(
                "one.wav", ("Drums|Snare|Rim", "Drums|Snare|Hit"), (), ()
            ),
            live_catalog.CatalogSample("two.wav", ("Drums|Snare",), (), ()),
            live_catalog.CatalogSample("three.wav", ("Drums|Snare-ish",), (), ()),
        )
        matches, counts = live_catalog.filter_catalog(samples, tag="Drums|Snare")
        self.assertEqual(["one.wav", "two.wav"], [sample.path for sample in matches])
        self.assertEqual(2, counts["Drums|Snare"])
        self.assertEqual(3, counts["Drums"])
        self.assertEqual(1, counts["Drums|Snare|Rim"])
        self.assertEqual([], live_catalog.filter_catalog(samples, tag="Drums|Snare", source="Automatic")[0])

    def test_multiple_tags_use_alternatives_within_groups_and_intersection_across_groups(self):
        samples = (
            live_catalog.CatalogSample("kick.wav", ("Drums|Kick", "Type|One Shot"), (), ("Genres|Ambient",)),
            live_catalog.CatalogSample("snare.wav", ("Drums|Snare|Rim", "Type|One Shot"), (), ("Genres|Ambient",)),
            live_catalog.CatalogSample("loop.wav", ("Drums|Snare", "Type|Loop"), (), ("Genres|Ambient",)),
            live_catalog.CatalogSample("bass.wav", ("Sounds|Bass", "Type|One Shot"), (), ("Genres|Ambient",)),
            live_catalog.CatalogSample("other.wav", ("Drums|Kick", "Type|One Shot"), (), ("Genres|House",)),
        )
        selected = ("Drums|Kick", "Drums|Snare", "Type|One Shot", "Genres|Ambient")
        matches, counts = live_catalog.filter_catalog(samples, tags=selected)
        self.assertEqual(["kick.wav", "snare.wav"], [sample.path for sample in matches])
        self.assertEqual(1, counts["Drums|Kick"])
        self.assertEqual(1, counts["Drums|Snare"])
        self.assertEqual(1, counts["Type|Loop"])
        self.assertEqual(1, counts["Genres|House"])
        self.assertEqual([], live_catalog.filter_catalog(samples, tags=selected, source="Non-auto (catalog)")[0])
        scoped, _ = live_catalog.filter_catalog(samples, group="Drums", tags=selected)
        self.assertEqual(matches, scoped)
        for invalid in ("", "Drums||Kick", None):
            with self.assertRaises(ValueError):
                live_catalog.filter_catalog(samples, tags=(invalid,))

    def test_catalog_multiple_selection_survives_group_search_and_source_changes(self):
        root, browser = self.create_browser()
        browser.samples = (
            live_catalog.CatalogSample("kick.wav", ("Drums|Kick", "Type|One Shot"), (), ()),
            live_catalog.CatalogSample("snare.wav", ("Drums|Snare", "Type|One Shot"), (), ()),
            live_catalog.CatalogSample("loop.wav", ("Drums|Snare", "Type|Loop"), (), ()),
        )
        browser.vocabulary = ("Drums|Kick", "Drums|Snare", "Type|Loop", "Type|One Shot")
        browser.group.set("Drums")
        browser.apply()
        for tag in ("Drums|Kick", "Drums|Snare"):
            browser.tags.selection_set(browser.tag_rows.index(tag))
        browser.pick_tag()
        self.assertEqual(3, len(browser.rows))
        browser.group.set("Type")
        browser.apply()
        browser.tags.selection_set(browser.tag_rows.index("Type|One Shot"))
        browser.pick_tag()
        root.update()
        self.assertEqual({"Drums|Kick", "Drums|Snare", "Type|One Shot"}, browser.active_tags)
        self.assertEqual({"kick.wav", "snare.wav"}, {sample.path for sample in browser.rows.values()})
        browser.search.set("snare")
        browser.apply()
        self.assertEqual(["snare.wav"], [sample.path for sample in browser.rows.values()])
        browser.source.set("Automatic")
        browser.apply()
        self.assertEqual({}, browser.rows)
        self.assertEqual(3, len(browser.active_tags))
        browser.source.set("All sources")
        browser.search.set("")
        browser.group.set("Drums")
        browser.apply()
        self.assertEqual(2, len(browser.tags.curselection()))
        browser.clear_tag()
        self.assertEqual(set(), browser.active_tags)
        self.assertEqual(3, len(browser.rows))

    def test_all_catalog_pages_are_reachable_without_refiltering_and_queries_reset_page(self):
        root, browser = self.create_browser()
        browser.samples = tuple(
            live_catalog.CatalogSample(f"item-{index:04}.wav", (), (), ()) for index in range(501)
        )
        with mock.patch("live_catalog.filter_catalog", wraps=live_catalog.filter_catalog) as query:
            browser.apply()
            self.wait_for_query(root, browser)
            self.assertEqual("Page 1 of 3", browser.page_label.get())
            self.assertTrue(browser.previous_button.instate(["disabled"]))
            seen = set(sample.path for sample in browser.rows.values())
            browser.next_button.invoke()
            seen.update(sample.path for sample in browser.rows.values())
            browser.next_button.invoke()
            seen.update(sample.path for sample in browser.rows.values())
            self.assertEqual(501, len(seen))
            self.assertEqual(1, len(browser.rows))
            self.assertTrue(browser.next_button.instate(["disabled"]))
            browser.previous_button.invoke()
            self.assertEqual("Page 2 of 3", browser.page_label.get())
            self.assertEqual(1, query.call_count)
            browser.search.set("item-0500")
            browser.apply()
            self.wait_for_query(root, browser)
            self.assertEqual("Page 1 of 1", browser.page_label.get())
            self.assertEqual(["item-0500.wav"], [sample.path for sample in browser.rows.values()])
            browser.search.set("missing")
            browser.apply()
            self.wait_for_query(root, browser)
            self.assertEqual("Page 0 of 0", browser.page_label.get())
            self.assertEqual({}, browser.rows)
            self.assertTrue(browser.next_button.instate(["disabled"]))
            self.assertTrue(browser.previous_button.instate(["disabled"]))

    def test_large_query_keeps_tk_responsive_and_discards_stale_results(self):
        root, browser = self.create_browser()
        browser.samples = tuple(
            live_catalog.CatalogSample(f"item-{index:04}.wav", (), (), ()) for index in range(501)
        )
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        original = live_catalog.filter_catalog
        def slow_query(*args, **kwargs):
            if not started.is_set():
                started.set()
                if not release.wait(3):
                    raise ValueError("Test query timed out")
            return original(*args, **kwargs)
        with mock.patch("live_catalog.filter_catalog", side_effect=slow_query) as query:
            browser.apply()
            self.assertTrue(started.wait(1))
            ticks = []
            root.after(0, lambda: ticks.append(True))
            root.update()
            self.assertEqual([True], ticks)
            browser.search.set("item-0001")
            browser.apply()
            browser.search.set("item-0500")
            browser.apply()
            release.set()
            self.wait_for_query(root, browser)
            self.assertEqual(["item-0500.wav"], [sample.path for sample in browser.rows.values()])
            self.assertEqual(2, query.call_count)
        with mock.patch("live_catalog.filter_catalog", side_effect=ValueError("Invalid source")):
            browser.apply()
            self.wait_for_query(root, browser)
        self.assertIn("Catalog filtering failed: Invalid source", browser.status.get())
        self.assertEqual({}, browser.rows)
        browser.apply()
        self.wait_for_query(root, browser)
        self.assertEqual(1, len(browser.rows))

    def test_vocabulary_includes_unused_tags_and_catalog_includes_non_audio_items(self):
        connection = sqlite3.connect(self.database)
        try:
            for file_id, name, code in (
                (20, "rack.adg", "adg-"), (21, "clip.alc", "alc-"),
                (22, "notes.mid", "midi"), (23, "swing.agr", "agr-"),
                (24, "scale.ascl", "scl-"), (25, "device.amxd", "amp-")
            ):
                connection.execute(
                    "INSERT INTO files VALUES (?, 4, ?, ?)", (file_id, name, int.from_bytes(code.encode(), "big"))
                )
                connection.execute("INSERT INTO keywords VALUES (?, 12, 0)", (file_id,))
            connection.commit()
        finally:
            connection.close()
        self.assertIn("Genres|Unused", live_catalog.read_vocabulary(self.database))
        self.assertEqual(3, len(live_catalog.read_catalog(self.database)))
        items = live_catalog.read_catalog(self.database, include_other_items=True)
        self.assertEqual(9, len(items))
        self.assertEqual(
            {"Audio", "Rack", "Clip", "MIDI", "Groove", "Tuning", "Max device"},
            {item.item_type for item in items}
        )
        racks, _ = live_catalog.filter_catalog(items, item_type="Rack", tag="Genres|Hip Hop")
        self.assertEqual(1, len(racks))
        self.assertTrue(racks[0].path.endswith("rack.adg"))

    def test_additional_hierarchy_and_browser_fields_preserve_provenance(self):
        connection = sqlite3.connect(self.database)
        try:
            for index, (key, value) in enumerate((
                ("CKey", "Sounds|Bass"), ("IKey", "Devices|Generative"),
                ("HKey", "Character|Bright"), ("DvTy", "Instrument"),
                ("MxTy", "Max Note Generator"),
                ("UKey", "My Group|User label"),
            ), start=10):
                connection.execute("INSERT INTO metadata_values VALUES (?, ?)", (index, value))
                connection.execute(
                    "INSERT INTO metadata VALUES (3, ?, ?)", (int.from_bytes(key.encode(), "big"), index)
                )
            connection.commit()
        finally:
            connection.close()
        items = live_catalog.read_catalog(self.database)
        item = next(item for item in items if item.path.endswith(os.path.join("Core Library", "same.wav")))
        self.assertIn("Devices|Generative", item.additional)
        self.assertIn("IKey: Devices|Generative", item.metadata_details)
        vocabulary = live_catalog.read_vocabulary(self.database)
        self.assertIn("Devices|Generative", vocabulary)
        self.assertIn("Character|Bright", vocabulary)
        self.assertIn("My Group|User label", vocabulary)
        self.assertIn("UKey: My Group|User label", item.metadata_details)
        self.assertNotIn("File extension|WAV", vocabulary)
        self.assertNotIn("Function|Instrument", vocabulary)
        self.assertNotIn("MIDI Tools|Generator", vocabulary)
        self.assertEqual((), item.non_auto)
        self.assertIn("File extension|WAV", item.fields)
        self.assertIn("Function|Instrument", item.fields)
        self.assertIn("MIDI Tools|Generator", item.fields)
        self.assertIn("DvTy: Instrument", item.metadata_details)
        self.assertIn("MxTy: Max Note Generator", item.metadata_details)
        self.assertNotIn("File extension|WAV", item.factory)
        self.assertFalse(any(tag.startswith("Format|") for tag in item.fields))
        self.assertEqual([item], live_catalog.filter_catalog(
            items, group="MIDI Tools", source="Browser fields (read only)"
        )[0])
        self.assertEqual([item], live_catalog.filter_catalog(
            items, group="Devices", source="Additional hierarchy metadata"
        )[0])
        self.assertEqual([], live_catalog.filter_catalog(items, group="MIDI Tools", source="Non-auto (catalog)")[0])

    def test_device_fields_match_live_labels_without_guessing_format_from_preset_extension(self):
        examples = (
            ("native.adv", "adv-", "Instrument", "device:ableton:instr:Operator", None, "Ableton"),
            ("rack.adg", "adg-", "Audio Effect", "device:ableton:audiofx:AudioEffectGroupDevice", None, "Ableton"),
            ("max-preset.adv", "adv-", "Midi Effect", "device:ableton:midifx:MxDeviceMidiEffect", None, "Max for Live"),
            ("max-instrument.adv", "adv-", "Instrument", "device:ableton:instr:MxDeviceInstrument", None, "Max for Live"),
            ("max-audio.adv", "adv-", "Audio Effect", "device:ableton:audiofx:MxDeviceAudioEffect", None, "Max for Live"),
            ("max-ref.adv", "adv-", "Instrument", "device:m4l:instr:pack@example", None, "Max for Live"),
            ("generator.amxd", "amp-", None, None, "Max Note Generator", "Max for Live"),
            ("transform.amxd", "amp-", None, None, "Max Note Transformation", "Max for Live"),
            ("unknown.adv", "adv-", None, None, None, None),
            ("external.adv", "adv-", "Instrument", "device:vst3:example", None, None),
            ("clip.alc", "alc-", None, "device:ableton:instr:Operator", None, None),
        )
        connection = sqlite3.connect(self.database)
        try:
            for file_id, (name, code, function, device_class, midi_tool, _format) in enumerate(examples, 20):
                connection.execute(
                    "INSERT INTO files VALUES (?, 4, ?, ?)", (file_id, name, int.from_bytes(code.encode(), "big"))
                )
                for offset, (key, value) in enumerate((("DvTy", function), ("DvCI", device_class), ("MxTy", midi_tool))):
                    if value is not None:
                        value_id = file_id * 10 + offset
                        connection.execute("INSERT INTO metadata_values VALUES (?, ?)", (value_id, value))
                        connection.execute("INSERT INTO metadata VALUES (?, ?, ?)", (
                            file_id, int.from_bytes(key.encode(), "big"), value_id
                        ))
            connection.commit()
        finally:
            connection.close()
        before = hashlib.sha256(self.database.read_bytes()).digest()
        items = live_catalog.read_catalog(self.database, include_other_items=True)
        by_name = {os.path.basename(item.path): item for item in items}
        for name, _code, function, device_class, midi_tool, device_format in examples:
            with self.subTest(name=name):
                item = by_name[name]
                formats = tuple(tag for tag in item.fields if tag.startswith("Format|"))
                self.assertEqual((f"Format|{device_format}",) if device_format else (), formats)
                self.assertIn(f"File extension|{name.split('.')[-1].upper()}", item.fields)
                if function:
                    self.assertIn(f"Function|{'MIDI Effect' if function == 'Midi Effect' else function}", item.fields)
                    self.assertIn(f"DvTy: {function}", item.metadata_details)
                if device_class:
                    self.assertIn(f"DvCI: {device_class}", item.metadata_details)
                if midi_tool:
                    self.assertIn(f"MIDI Tools|{'Generator' if midi_tool == 'Max Note Generator' else 'Transformation'}", item.fields)
                self.assertFalse(any(tag.startswith("Device type|") for tag in item.tags))
        combined, _ = live_catalog.filter_catalog(
            items, tags=("Function|MIDI Effect", "Format|Max for Live"), source="Browser fields (read only)"
        )
        self.assertEqual(["max-preset.adv"], [os.path.basename(item.path) for item in combined])
        self.assertEqual(before, hashlib.sha256(self.database.read_bytes()).digest())

    def test_unknown_device_field_values_report_unsupported_schema(self):
        for key in ("DvTy", "MxTy"):
            with self.subTest(key=key):
                connection = sqlite3.connect(self.database)
                try:
                    connection.execute("DELETE FROM metadata WHERE file_id=3 AND key<>1264941431")
                    connection.execute("INSERT OR REPLACE INTO metadata_values VALUES (30, 'Future unknown value')")
                    connection.execute("INSERT INTO metadata VALUES (3, ?, 30)", (int.from_bytes(key.encode(), "big"),))
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaisesRegex(ValueError, "Unsupported Live catalog browser field"):
                    live_catalog.read_catalog(self.database)

    def test_unknown_schema_and_bad_hierarchy_are_errors_not_empty_success(self):
        connection = sqlite3.connect(self.database)
        try:
            connection.execute("UPDATE files SET parent_id=3 WHERE file_id=2")
            connection.commit()
        finally:
            connection.close()
        with self.assertRaisesRegex(ValueError, "Cycle"):
            live_catalog.read_catalog(self.database)
        missing = Path(self.temporary.name) / "missing.db"
        with self.assertRaises(sqlite3.Error):
            live_catalog.read_catalog(missing)
        self.assertFalse(missing.exists())

    def test_catalog_dialog_loads_genres_and_exposes_only_read_operations(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        def cleanup():
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                root.tk.call("after", "cancel", callback)
            root.destroy()
            gc.collect()
        self.addCleanup(cleanup)
        with mock.patch("live_catalog.available_databases", return_value=(self.database,)), mock.patch.object(
            sorter_engine, "_asset_index_connection", side_effect=AssertionError("Must not write manager index")
        ):
            dialog = LiveCatalogDialog(root)
            deadline = time.monotonic() + 3
            while dialog.results is not None and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertIsNone(dialog.results)
            self.assertEqual(3, len(dialog.samples))
            dialog.group.set("Genres")
            dialog.apply()
            self.assertEqual(["Genres", "Genres|Hip Hop", "Genres|Unused"], dialog.tag_rows)
            self.assertEqual(1, len(dialog.sounds.get_children()))
            dialog.sounds.selection_set(dialog.sounds.get_children()[0])
            dialog.show_details()
            self.assertIn("Genres|Hip Hop", dialog.details.get("1.0", "end"))
            self.assertIn("Factory / catalog metadata", dialog.details.get("1.0", "end"))
            self.assertEqual("#181b20", dialog.details.cget("background"))
            self.assertEqual("#181b20", dialog.tags.cget("background"))
            dialog.geometry("760x560")
            root.update()
            for child in dialog.winfo_children():
                if child is dialog.loading_banner:
                    self.assertFalse(child.winfo_ismapped())
                    continue
                self.assertTrue(child.winfo_ismapped(),
                                f"{child}: {child.winfo_class()} {child.winfo_geometry()} "
                                f"requested={child.winfo_reqwidth()}x{child.winfo_reqheight()} "
                                f"dialog={dialog.winfo_geometry()}")
                self.assertLessEqual(child.winfo_y() + child.winfo_height(), dialog.winfo_height())
            widgets = [dialog]
            labels = []
            while widgets:
                widget = widgets.pop()
                widgets.extend(widget.winfo_children())
                if widget.winfo_class() in ("TButton", "Button"):
                    labels.append(widget.cget("text"))
            self.assertEqual({"Close", "Load / refresh", "Search", "Clear tag filters", "Previous", "Next"}, set(labels))
            with mock.patch("live_catalog.read_catalog", side_effect=ValueError("Invalid catalog")):
                dialog.load()
                deadline = time.monotonic() + 3
                while dialog.results is not None and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.01)
            self.assertIn("refresh failed", dialog.status.get())
            self.assertEqual(3, len(dialog.samples))

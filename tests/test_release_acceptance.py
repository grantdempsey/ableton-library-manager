import gc
import importlib.machinery
import importlib.util
import json
import hashlib
import os
from pathlib import Path
import tempfile
import time
import threading
import tkinter as tk
import unittest
from unittest import mock
import wave

import ableton_tags
import gui_theme
import live_catalog
import sorter_engine


class WindowsReleaseAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.library.mkdir()
        for name, value in (
            ("CONFIG_FILE", str(self.root / "profile.json")),
            ("ASSET_INDEX_FILE", str(self.root / "assets.db")),
            ("CONFIG_BACKUP_DIR", str(self.root / "backups")),
            ("MOVE_LOG_DIR", str(self.root / "move_logs")),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        resolver = mock.patch.object(gui_theme, "resolve_user_library_path", return_value=str(self.library))
        resolver.start()
        self.addCleanup(resolver.stop)
        for name in (
            "BPM_RANGES", "DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS",
            "IGNORED_DIRECTORIES", "RULE_METADATA", "SMART_LEARNING_ENABLED",
            "LEARNING_COUNTS", "LEARNED_RULE_CANDIDATES", "LOOP_LAYOUT",
        ):
            original = getattr(sorter_engine, name)
            self.addCleanup(setattr, sorter_engine, name, original)
        for name, value in (
            ("USER_LIBRARY_PATH", str(self.library)),
            ("OPTIONS_PATH", str(self.root / "preferences" / "Options.txt")),
        ):
            patcher = mock.patch.object(gui_theme, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sorter_engine._write_config(sorter_engine._default_config(), create_backup=False)
        sorter_engine.load_external_config()
        self.sample = self.library / "acceptance_kick.wav"
        with wave.open(str(self.sample), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(44100)
            handle.writeframes(b"\0\0" * 4410)
        sorter_engine.index_existing_library(str(self.library))
        loader = importlib.machinery.SourceFileLoader(
            "release_acceptance_app", str(Path(__file__).resolve().parents[1] / "AbletonLibraryManager.pyw")
        )
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        discovery = mock.patch.object(live_catalog, "available_databases", return_value=())
        discovery.start()
        self.addCleanup(discovery.stop)
        self.app = module.ProductionStudioManagerApp()
        self.callbacks = []
        worker_errors = mock.patch.object(threading, "excepthook", side_effect=lambda error: self.callbacks.append(error))
        worker_errors.start()
        self.addCleanup(worker_errors.stop)
        self.app.report_callback_exception = lambda *error: self.callbacks.append(error)
        self.addCleanup(self.close_app)

    def close_app(self):
        worker = self.app.organize_panel._volume_thread
        if worker is not None:
            worker.join(timeout=5)
        for identifier in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.tk.call("after", "cancel", identifier)
        self.app.destroy()
        gc.collect()

    def wait(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(0.01)
        self.assertTrue(predicate(), "UI worker did not finish")
        self.app.update()
        self.assertEqual([], self.callbacks)

    def assert_inside(self, widget, container):
        self.assertTrue(widget.winfo_ismapped(), str(widget))
        self.assertGreater(widget.winfo_height(), 5)
        self.assertGreater(widget.winfo_width(), 5)
        self.assertGreaterEqual(widget.winfo_rootx(), container.winfo_rootx())
        self.assertGreaterEqual(widget.winfo_rooty(), container.winfo_rooty())
        self.assertLessEqual(
            widget.winfo_rootx() + widget.winfo_width(),
            container.winfo_rootx() + container.winfo_width(),
        )
        self.assertLessEqual(
            widget.winfo_rooty() + widget.winfo_height(),
            container.winfo_rooty() + container.winfo_height(),
        )

    def test_all_pages_and_latest_dialogs_at_supported_window_sizes(self):
        for geometry in ("1020x700", "1180x760"):
            self.app.geometry(geometry)
            for tab in self.app.tab_notebook.tabs():
                self.app.tab_notebook.select(tab)
                self.app.update()
                self.assert_inside(self.app.tab_notebook, self.app)
                self.assertEqual([], self.callbacks)
            browser = self.app.tags_panel
            self.app.tab_notebook.select(browser)
            self.wait(lambda: not browser.has_pending_library_work())
            browser._render_results(load_sidebar=False)
            self.app.update()
            item = next(item for item, path in browser._asset_paths.items() if path == str(self.sample))
            browser.asset_tree.selection_set(item)
            self.app.update()
            self.assert_inside(browser.asset_tree, self.app)
            browser._open_tag_editor()
            self.app.update()
            editor = browser._live_batch_dialog
            self.wait(lambda: not editor.busy)
            for widget in (editor.tag_entry, editor.group_entry, editor.assigned_tree, editor.review_button):
                self.assert_inside(widget, editor)
            self.wait(lambda: browser._tag_suggestions_queue is None and browser._live_vocabulary_queue is None)
            editor.close()
            self.assertTrue(browser._edit_live_tags([str(self.sample)], "Drums|Kick", "add"))
            batch = browser._live_batch_dialog
            self.wait(lambda: not batch.busy)
            self.assert_inside(batch.save_button, batch)
            self.assert_inside(batch.preview, batch)
            self.assertFalse((self.library / "Ableton Folder Info").exists())
            with mock.patch("live_tag_batch.ask_confirm", return_value=True):
                batch.close()
            browser._open_discovery_filters()
            self.app.update()
            dialog = next(
                child for child in browser.winfo_children()
                if isinstance(child, tk.Toplevel) and child.title() == "Add discovery filters"
            )
            dialog.destroy()
            self.assertFalse(hasattr(browser, "library_source_picker"))
            self.assertFalse(hasattr(browser, "_catalog_panel"))
            self.app.update()
        self.assertEqual([], self.callbacks)
        self.assertFalse(Path(gui_theme.OPTIONS_PATH).exists())
        self.assertEqual(1, sorter_engine.count_indexed_assets(str(self.library)))

    def test_old_profile_survives_startup_and_rules_refresh_is_required(self):
        data = sorter_engine.load_external_config()
        data["XO_CUSTOM_TYPES"] = {"Keep my folder": ["preserved"]}
        data["LEARNED_RULE_CANDIDATES"] = [
            {"token": "old", "target": "Snares", "count": 7, "status": "pending"},
            {"token": "historical", "target": "Snares", "count": 81, "status": "pending"},
        ]
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
        with self.assertRaisesRegex(ValueError, "historical observations"):
            sorter_engine.review_learning_candidate("historical", "Snares", "approved")
        import rule_suggester
        found = rule_suggester.suggest_rules(str(self.library))
        rule_suggester.add_suggestions_as_candidates(found, library_root=str(self.library))
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual({"Keep my folder": ["preserved"]}, saved["XO_CUSTOM_TYPES"])
        self.assertEqual(["stale", "stale"], [item["status"] for item in saved["LEARNED_RULE_CANDIDATES"]])
        self.assertEqual(0, sorter_engine.library_status_summary()["suggestions"])

    def test_reviewed_ui_writes_round_trip_without_changing_audio_or_neighbors(self):
        neighbor = self.library / "untouched_snare.wav"
        neighbor.write_bytes(self.sample.read_bytes())
        ableton_tags.prepare_edit([str(neighbor)], "Character|Keep").commit()
        sorter_engine.index_existing_library(str(self.library))
        audio_hashes = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (self.sample, neighbor)
        }
        browser = self.app.tags_panel
        self.app.tab_notebook.select(browser)
        self.wait(lambda: not browser.has_pending_library_work())
        browser._render_results(load_sidebar=False)
        item = next(item for item, path in browser._asset_paths.items() if path == str(self.sample))
        browser.asset_tree.selection_set(item)
        self.app.update()
        browser._open_tag_editor()
        self.wait(lambda: browser._tag_suggestions_queue is None and browser._live_vocabulary_queue is None)
        batch = browser._live_batch_dialog
        self.wait(lambda: not batch.busy)
        batch.group_var.set("Genres")
        batch.tag_var.set("Release fixture")
        batch.review_button.invoke()
        self.wait(lambda: not batch.busy)
        self.assertEqual([], ableton_tags.sample_tags(str(self.sample)))
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            batch.close()
        self.assertEqual([], ableton_tags.sample_tags(str(self.sample)))

        for action, old_tag, new_tag, expected in (
            ("add", "Genres|Release fixture", None, ["Genres|Release fixture"]),
            ("rename", "Genres|Release fixture", "Character|Round trip", ["Character|Round trip"]),
            ("remove", "Character|Round trip", None, []),
        ):
            self.assertTrue(browser._edit_live_tags([str(self.sample)], old_tag, action, new_tag))
            batch = browser._live_batch_dialog
            self.wait(lambda: not batch.busy)
            self.assert_inside(batch.save_button, batch)
            existing_sidecars = {
                path: batch.plan.originals[path]
                for path in batch.plan.changes
                if batch.plan.originals.get(path) is not None
            }
            prior_backups = set(self.library.rglob("*.bak"))
            with mock.patch("live_tag_batch.ask_confirm", return_value=True):
                batch.save_button.invoke()
                self.wait(lambda: not batch.busy)
            self.assertIn("Changes saved.", batch.status_var.get())
            new_backups = set(self.library.rglob("*.bak")) - prior_backups
            self.assertEqual(len(existing_sidecars), len(new_backups))
            for path, original in existing_sidecars.items():
                backup = next(backup for backup in new_backups if backup.name.startswith(path.name + "."))
                self.assertEqual(original, backup.read_bytes())
            self.assertEqual(expected, ableton_tags.sample_tags(str(self.sample)))
            self.assertEqual(expected, sorter_engine.get_indexed_asset(str(self.sample))["ableton_tags"])
            self.assertEqual(["Character|Keep"], ableton_tags.sample_tags(str(neighbor)))
            self.assertEqual(["Character|Keep"], sorter_engine.get_indexed_asset(str(neighbor))["ableton_tags"])
            for path, digest in audio_hashes.items():
                self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            batch.close()
            self.wait(lambda: not browser.has_pending_library_work())
        self.assertEqual(2, len(list(self.library.rglob("*.bak"))))
        self.assertEqual([], self.callbacks)

    def test_ui_rescan_reconciles_external_deletion_and_new_audio(self):
        browser = self.app.tags_panel
        self.app.tab_notebook.select(browser)
        self.wait(lambda: not browser.has_pending_library_work())
        replacement = self.library / "new_snare.wav"
        replacement.write_bytes(self.sample.read_bytes())
        self.sample.unlink()
        browser.rescan_button.invoke()
        self.wait(lambda: not browser.has_pending_library_work())
        self.assertIsNone(sorter_engine.get_indexed_asset(str(self.sample)))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(str(replacement)))
        self.assertEqual(1, sorter_engine.count_indexed_assets(str(self.library)))
        self.assertEqual({str(replacement)}, set(browser._asset_paths.values()))
        self.assertEqual(1, sorter_engine.library_status_summary()["sounds"])
        self.assertEqual("normal", browser.rescan_button.cget("state"))

    def test_ui_save_refuses_external_sidecar_changes_after_review(self):
        browser = self.app.tags_panel
        self.app.tab_notebook.select(browser)
        self.wait(lambda: not browser.has_pending_library_work())
        self.assertTrue(browser._edit_live_tags([str(self.sample)], "Drums|Kick", "add"))
        batch = browser._live_batch_dialog
        self.wait(lambda: not batch.busy)
        ableton_tags.prepare_edit([str(self.sample)], "Character|External").commit()
        before = {path: path.read_bytes() for path in self.library.rglob("*.xmp")}
        with mock.patch("live_tag_batch.ask_confirm", return_value=True), mock.patch(
            "live_tag_batch.messagebox.showerror"
        ) as error:
            batch.save_button.invoke()
            self.wait(lambda: not batch.busy)
        error.assert_called_once()
        self.assertEqual("Live Tag Edit Failed", error.call_args.args[0])
        self.assertIn("Tag edit failed.", batch.status_var.get())
        self.assertEqual(["Character|External"], ableton_tags.sample_tags(str(self.sample)))
        self.assertEqual(before, {path: path.read_bytes() for path in self.library.rglob("*.xmp")})
        self.assertEqual([], list(self.library.rglob("*.bak")))
        with mock.patch("live_tag_batch.ask_confirm", return_value=True):
            batch.close()


if __name__ == "__main__":
    unittest.main()

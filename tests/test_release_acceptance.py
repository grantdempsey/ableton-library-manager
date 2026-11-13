import gc
from contextlib import contextmanager, ExitStack
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
from tkinter import ttk
import unittest
from unittest import mock
import wave
import zipfile

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
        config = sorter_engine._default_config()
        config["ACTIVE_LIBRARY_PATH"] = str(self.library)
        sorter_engine._write_config(config, create_backup=False)
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
        for thread, _cancel in list(getattr(self.app, "_background_jobs", [])):
            thread.join(timeout=5)
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

    def run_workflow_until(self, predicate, action=lambda: None):
        complete = []
        def poll():
            nonlocal polling
            if predicate():
                complete.append(True)
                self.app.quit()
            else:
                polling = self.app.after(10, poll)
        timeout = self.app.after(15000, self.app.quit)
        polling = self.app.after(10, poll)
        try:
            action()
            self.app.mainloop()
        finally:
            self.app.after_cancel(timeout)
            self.app.after_cancel(polling)
        self.assertTrue(complete, "Workflow did not complete before timeout")
        self.assertEqual([], self.callbacks)

    @contextmanager
    def workflow_dialogs(self):
        # Approve only fixture dialogs; workers, transfers and reconciliation stay real.
        with ExitStack() as stack:
            notices = {}
            for name in ("showinfo", "showwarning", "showerror"):
                notices[name] = stack.enter_context(mock.patch(f"tab_matrix.messagebox.{name}"))
            stack.enter_context(mock.patch("tab_matrix.messagebox.askyesno", return_value=True))
            stack.enter_context(mock.patch("tab_organize.ask_confirm", return_value=True))
            stack.enter_context(mock.patch("tab_organize.themed_dialog", return_value=False))
            stack.enter_context(mock.patch("tab_organize.show_notice"))
            yield notices

    def prepare_workflow(self, page):
        self.run_workflow_until(lambda: not self.app._startup_recovery_pending)
        # Finish startup's scheduled rescan before taking preview snapshots.
        self.run_workflow_until(
            lambda: not self.app.tags_panel.has_pending_library_work(),
            self.app._rescan_after_startup_recovery,
        )
        self.app.after_cancel(self.app._startup_rescan_after_id)
        self.app.tab_notebook.select(page)
        self.app.update()
        self.assert_inside(page, self.app)

    @staticmethod
    def file_snapshot(folder):
        return {
            path.relative_to(folder).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in folder.rglob("*") if path.is_file()
        }

    @staticmethod
    def button_named(parent, text):
        for child in parent.winfo_children():
            if isinstance(child, (tk.Button, ttk.Button)) and child.cget("text") == text:
                return child
            found = WindowsReleaseAcceptanceTests.button_named(child, text)
            if found is not None:
                return found
        return None

    def finish_import(self, page, button):
        previous_worker = page.active_sorter
        self.run_workflow_until(
            lambda: page.active_sorter is not None
            and page.active_sorter is not previous_worker
            and not page.active_sorter.is_running()
            and page.preview_btn.cget("state") == "normal",
            lambda: self.click_button(button),
        )
        self.assertEqual([], page.active_sorter.operation_errors)
        self.assertEqual("disabled", page.cancel_btn.cget("state"))

    def click_button(self, button):
        self.assert_inside(button, self.app)
        self.assertNotEqual("disabled", button.cget("state"))
        x, y = button.winfo_width() // 2, button.winfo_height() // 2
        button.event_generate("<Enter>", x=x, y=y)
        button.event_generate("<ButtonPress-1>", x=x, y=y)
        button.event_generate("<ButtonRelease-1>", x=x, y=y)

    def undo_history_item(self, log_path):
        self.button_named(self.app, "History / Recovery").invoke()
        self.app.update()
        tree = self.app._history_tree
        selected = next(item for item, path in self.app._history_paths.items() if path == log_path)
        tree.selection_set(selected)
        self.run_workflow_until(
            lambda: not self.app.import_dashboard._undo_pending,
            self.button_named(self.app._history_window, "Undo selected…").invoke,
        )
        self.assertFalse(Path(log_path).exists())
        self.assertTrue(Path(log_path + ".undone").is_file())
        self.assertNotIn(log_path, self.app._history_paths.values())

    def test_import_copy_move_buttons_preview_export_apply_and_history_undo(self):
        page = self.app.import_dashboard
        self.prepare_workflow(page)
        with self.workflow_dialogs() as notices:
            for copy_mode in (True, False):
                with self.subTest(copy_mode=copy_mode):
                    incoming = self.root / ("incoming-copy" if copy_mode else "incoming-move")
                    incoming.mkdir()
                    source = incoming / ("copy_kick.wav" if copy_mode else "move_snare.wav")
                    source.write_bytes(self.sample.read_bytes())
                    excluded = incoming / "leave.mid"
                    excluded.write_bytes(b"untouched MIDI fixture")
                    ableton_tags.prepare_edit([str(source)], "Character|Workflow").commit()
                    source_snapshot = self.file_snapshot(incoming)
                    library_snapshot = self.file_snapshot(self.library)
                    profile = Path(sorter_engine.CONFIG_FILE).read_bytes()
                    page.src_dir_var.set(str(incoming))
                    page.dest_dir_var.set(str(self.library))
                    (page.copy_radio if copy_mode else page.move_radio).invoke()
                    page.audio_only_check.invoke()
                    self.finish_import(page, page.preview_btn)
                    self.assertIsNotNone(page.reviewed_plan)
                    self.assertEqual(source_snapshot, self.file_snapshot(incoming))
                    self.assertEqual(library_snapshot, self.file_snapshot(self.library))
                    self.assertEqual(profile, Path(sorter_engine.CONFIG_FILE).read_bytes())
                    self.assertEqual("normal", page.apply_btn.cget("state"))
                    records = page.active_sorter.preview_records
                    self.assertEqual([str(source)], [r["source"] for r in records])
                    destination = Path(records[0]["destination_path"])
                    self.assertFalse(destination.exists())
                    exported = self.root / f"import-{copy_mode}.json"
                    with mock.patch("tab_import.filedialog.asksaveasfilename", return_value=str(exported)):
                        page.export_btn.invoke()
                    self.assertEqual(page.reviewed_plan, json.loads(exported.read_text()))
                    self.finish_import(page, page.apply_btn)
                    self.assertEqual(source_snapshot[source.name][0], destination.read_bytes())
                    self.assertEqual(["Character|Workflow"], ableton_tags.sample_tags(str(destination)))
                    self.assertIsNotNone(sorter_engine.get_indexed_asset(str(destination)))
                    self.assertEqual(b"untouched MIDI fixture", excluded.read_bytes())
                    if copy_mode:
                        self.assertEqual(source_snapshot, self.file_snapshot(incoming))
                        self.assertIsNone(page.active_sorter.move_log_path)
                    else:
                        self.assertFalse(source.exists())
                        self.undo_history_item(page.active_sorter.move_log_path)
                        self.assertEqual(source_snapshot[source.name][0], source.read_bytes())
                        self.assertEqual(["Character|Workflow"], ableton_tags.sample_tags(str(source)))
                        self.assertFalse(destination.exists())
                        self.assertIsNone(sorter_engine.get_indexed_asset(str(destination)))
                    self.assertEqual("disabled", page.apply_btn.cget("state"))
            notices["showerror"].assert_not_called()
            notices["showwarning"].assert_not_called()

    def test_organize_buttons_backup_export_apply_and_history_undo(self):
        page = self.app.organize_panel
        self.prepare_workflow(page)
        ableton_tags.prepare_edit([str(self.sample)], "Character|Keep").commit()
        original = self.file_snapshot(self.library)
        profile = Path(sorter_engine.CONFIG_FILE).read_bytes()
        with self.workflow_dialogs() as notices:
            self.run_workflow_until(lambda: not page.has_pending_job(), lambda: self.click_button(page.btn_preview))
            self.assertIsNotNone(page.reviewed_plan)
            self.assertEqual([], page.preview_sorter.operation_errors)
            self.assertEqual(original, self.file_snapshot(self.library))
            self.assertEqual(profile, Path(sorter_engine.CONFIG_FILE).read_bytes())
            destination = Path(next(
                r["destination_path"] for r in page.preview_sorter.preview_records
                if r["source"] == str(self.sample)
            ))
            exported = self.root / "organize-plan.json"
            with mock.patch("tab_organize.filedialog.asksaveasfilename", return_value=str(exported)):
                page.tools_menu.invoke(0)
            self.assertEqual(page.reviewed_plan, json.loads(exported.read_text()))
            self.run_workflow_until(lambda: not page.has_pending_job(), lambda: self.click_button(page.btn_execute))
            self.assertEqual([], page.active_sorter.operation_errors)
            self.assertFalse(self.sample.exists())
            self.assertEqual(original[self.sample.name][0], destination.read_bytes())
            self.assertEqual(["Character|Keep"], ableton_tags.sample_tags(str(destination)))
            backups = list(Path(page.get_backup_directory(str(self.library))).glob("*.zip"))
            self.assertEqual(1, len(backups))
            with zipfile.ZipFile(backups[0]) as backup:
                self.assertIsNone(backup.testzip())
                self.assertEqual(set(original), set(backup.namelist()))
                for name, (contents, _mtime) in original.items():
                    self.assertEqual(contents, backup.read(name))
            self.undo_history_item(page.active_sorter.move_log_path)
            self.assertEqual(original[self.sample.name][0], self.sample.read_bytes())
            self.assertEqual(["Character|Keep"], ableton_tags.sample_tags(str(self.sample)))
            self.assertFalse(destination.exists())
            self.assertIsNotNone(sorter_engine.get_indexed_asset(str(self.sample)))
            notices["showerror"].assert_not_called()
            notices["showwarning"].assert_not_called()

    def test_move_collision_review_and_history_restore_both_duplicate_sources(self):
        page = self.app.import_dashboard
        self.prepare_workflow(page)
        incoming = self.root / "collisions"
        sources = []
        for folder in ("first", "second"):
            directory = incoming / folder
            directory.mkdir(parents=True)
            source = directory / "collision_kick.wav"
            source.write_bytes(self.sample.read_bytes())
            sources.append(source)
        page.src_dir_var.set(str(incoming))
        page.move_radio.invoke()
        with self.workflow_dialogs() as notices:
            self.finish_import(page, page.preview_btn)
            blocked_destination = Path(page.active_sorter.preview_records[0]["destination_path"])
            blocked_destination.parent.mkdir(parents=True)
            blocked_destination.write_bytes(b"existing file must not be overwritten")
            source_snapshot = self.file_snapshot(incoming)
            library_snapshot = self.file_snapshot(self.library)
            self.finish_import(page, page.preview_btn)
            records = page.active_sorter.preview_records
            self.assertEqual(["duplicate", "move"], sorted(r["action"] for r in records))
            self.assertTrue(any(r["collision"] == "rename" for r in records))
            self.assertEqual(1, len({r["destination_path"] for r in records}))
            self.assertEqual(source_snapshot, self.file_snapshot(incoming))
            self.assertEqual(library_snapshot, self.file_snapshot(self.library))
            destination = Path(records[0]["destination_path"])
            self.finish_import(page, page.apply_btn)
            self.assertTrue(all(not source.exists() for source in sources))
            self.assertEqual(source_snapshot["first/collision_kick.wav"][0], destination.read_bytes())
            self.assertEqual(b"existing file must not be overwritten", blocked_destination.read_bytes())
            self.assertEqual(2, sorter_engine.describe_move_log(page.active_sorter.move_log_path)[0])
            self.undo_history_item(page.active_sorter.move_log_path)
            for source in sources:
                self.assertEqual(source_snapshot[source.relative_to(incoming).as_posix()][0], source.read_bytes())
            self.assertFalse(destination.exists())
            self.assertEqual(b"existing file must not be overwritten", blocked_destination.read_bytes())
            notices["showerror"].assert_not_called()
            notices["showwarning"].assert_not_called()

    def test_apply_buttons_refuse_files_changed_after_preview_without_transferring(self):
        importing = self.app.import_dashboard
        self.prepare_workflow(importing)
        incoming = self.root / "changed-input"
        incoming.mkdir()
        source = incoming / "changed_kick.wav"
        source.write_bytes(self.sample.read_bytes())
        importing.src_dir_var.set(str(incoming))
        with self.workflow_dialogs() as notices:
            self.finish_import(importing, importing.preview_btn)
            source.write_bytes(source.read_bytes() + b"external change")
            source_snapshot = self.file_snapshot(incoming)
            library_snapshot = self.file_snapshot(self.library)
            self.run_workflow_until(
                lambda: not importing.active_sorter.is_running()
                and importing.preview_btn.cget("state") == "normal",
                lambda: self.click_button(importing.apply_btn),
            )
            self.assertTrue(importing.active_sorter.operation_errors)
            self.assertEqual(source_snapshot, self.file_snapshot(incoming))
            self.assertEqual(library_snapshot, self.file_snapshot(self.library))
            self.assertIsNone(importing.reviewed_plan)
            self.assertEqual("disabled", importing.apply_btn.cget("state"))

            organizing = self.app.organize_panel
            self.app.tab_notebook.select(organizing)
            self.app.update()
            organizing.cb_backup.invoke()
            self.run_workflow_until(
                lambda: not organizing.has_pending_job(), lambda: self.click_button(organizing.btn_preview),
            )
            self.assertIsNotNone(organizing.reviewed_plan)
            self.sample.write_bytes(self.sample.read_bytes() + b"external change")
            library_snapshot = self.file_snapshot(self.library)
            self.run_workflow_until(
                lambda: not organizing.has_pending_job(), lambda: self.click_button(organizing.btn_execute),
            )
            self.assertTrue(organizing.active_sorter.operation_errors)
            self.assertEqual(library_snapshot, self.file_snapshot(self.library))
            self.assertIsNone(organizing.reviewed_plan)
            self.assertEqual("disabled", organizing.btn_execute.cget("state"))
            self.assertEqual(2, notices["showwarning"].call_count)
            notices["showerror"].assert_not_called()

    def cancel_after_first_transfer(self, page, apply_button, cancel_button, finished):
        transferred, release = threading.Event(), threading.Event()
        serial = threading.Lock()
        execute = sorter_engine.ParallelLibrarySorter._execute_record
        def held_transfer(worker, record):
            with serial:
                execute(worker, record)
                if not transferred.is_set():
                    transferred.set()
                    if not release.wait(10):
                        raise TimeoutError("Fixture did not release first completed transfer")
        def cancel_when_ready():
            if transferred.is_set():
                self.click_button(cancel_button)
                release.set()
            else:
                self.app.after(10, cancel_when_ready)
        with mock.patch.object(sorter_engine.ParallelLibrarySorter, "_execute_record", held_transfer):
            self.app.after(10, cancel_when_ready)
            try:
                self.run_workflow_until(finished, lambda: self.click_button(apply_button))
            finally:
                release.set()
        self.assertTrue(page.active_sorter.cancel_event.is_set())
        self.assertEqual([], page.active_sorter.operation_errors)

    def test_import_cancel_buttons_keep_completed_files_and_move_history_is_undoable(self):
        page = self.app.import_dashboard
        self.prepare_workflow(page)
        with self.workflow_dialogs() as notices:
            for copy_mode in (True, False):
                with self.subTest(copy_mode=copy_mode):
                    incoming = self.root / f"cancel-{copy_mode}"
                    incoming.mkdir()
                    originals = {}
                    for number in range(8):
                        source = incoming / f"cancel_{copy_mode}_{number}_kick.wav"
                        source.write_bytes(self.sample.read_bytes())
                        originals[source] = source.read_bytes()
                    page.src_dir_var.set(str(incoming))
                    (page.copy_radio if copy_mode else page.move_radio).invoke()
                    self.finish_import(page, page.preview_btn)
                    records = list(page.active_sorter.preview_records)
                    self.cancel_after_first_transfer(
                        page, page.apply_btn, page.cancel_btn,
                        lambda: not page.active_sorter.is_running()
                        and page.preview_btn.cget("state") == "normal",
                    )
                    completed = [r for r in records if Path(r["destination_path"]).exists()]
                    self.assertEqual(1, len(completed))
                    for record in records:
                        source, destination = Path(record["source"]), Path(record["destination_path"])
                        if destination.exists():
                            self.assertEqual(originals[source], destination.read_bytes())
                            self.assertEqual(copy_mode, source.exists())
                        else:
                            self.assertEqual(originals[source], source.read_bytes())
                    self.assertIn("cancelled", page.import_status_var.get().lower())
                    self.assertEqual("disabled", page.apply_btn.cget("state"))
                    if not copy_mode:
                        self.undo_history_item(page.active_sorter.move_log_path)
                        for source, contents in originals.items():
                            self.assertEqual(contents, source.read_bytes())
            notices["showerror"].assert_not_called()

    def test_organize_cancel_button_keeps_completed_move_and_history_restores_it(self):
        page = self.app.organize_panel
        self.prepare_workflow(page)
        for number in range(7):
            (self.library / f"cancel_{number}_snare.wav").write_bytes(self.sample.read_bytes())
        originals = {p: p.read_bytes() for p in self.library.glob("*.wav")}
        page.cb_backup.invoke()
        with self.workflow_dialogs() as notices:
            self.run_workflow_until(lambda: not page.has_pending_job(), lambda: self.click_button(page.btn_preview))
            records = list(page.preview_sorter.preview_records)
            self.cancel_after_first_transfer(
                page, page.btn_execute, page.btn_cancel, lambda: not page.has_pending_job(),
            )
            completed = [r for r in records if Path(r["destination_path"]).exists()]
            self.assertEqual(1, len(completed))
            self.assertIn("stopped early", page.plan_summary_var.get())
            self.assertEqual("disabled", page.btn_execute.cget("state"))
            self.undo_history_item(page.active_sorter.move_log_path)
            for source, contents in originals.items():
                self.assertEqual(contents, source.read_bytes())
            for record in records:
                self.assertFalse(Path(record["destination_path"]).exists())
            notices["showerror"].assert_not_called()

    def test_global_status_is_visible_below_notebook_at_default_and_resized_heights(self):
        self.app.status_lbl.config(text="Options.txt inspected; not validated by Live.")
        for geometry in ("1180x760", "1020x700", "1180x950"):
            self.app.geometry(geometry)
            self.app.tab_notebook.select(self.app.organize_panel)
            self.app.update()
            self.assert_inside(self.app.status_lbl, self.app)
            self.assertGreaterEqual(
                self.app.status_lbl.winfo_rooty(),
                self.app.tab_notebook.winfo_rooty() + self.app.tab_notebook.winfo_height(),
            )
        self.assertEqual([], self.callbacks)

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
            self.assertIn("Live acceptance is not verified.", batch.status_var.get())
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

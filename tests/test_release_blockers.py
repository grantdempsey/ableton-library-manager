import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

import ableton_tags
import gui_theme
import live_tag_sync
import sorter_engine
from tab_organize import OrganizeTab
import xo_filter
import test_release_acceptance as app_fixture


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / "library"
        self.library.mkdir()
        for name, value in (
            ("CONFIG_FILE", str(self.root / "profile.json")),
            ("ASSET_INDEX_FILE", str(self.root / "index.db")),
            ("MOVE_LOG_DIR", str(self.root / "moves")),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def backup_page(self):
        return SimpleNamespace(
            get_backup_directory=lambda path: str(self.root / "backups"),
            write_console_message=lambda message: None,
        )

    def test_backup_restores_unicode_audio_and_live_sidecar_assignments(self):
        sample = self.library / "café kick.wav"
        sample.write_bytes(b"audio")
        ableton_tags.prepare_edit([str(sample)], "Genres|Ambient").commit()
        apple_double = self.library / "._café kick.wav"
        apple_double.write_bytes(b"resource-fork")
        _target, archive_path = OrganizeTab.run_safeguard_archiver_thread(self.backup_page(), str(self.library))
        restored = self.root / "restored"
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(restored)
        for original in self.library.rglob("*"):
            if original.is_file():
                self.assertEqual(original.read_bytes(), (restored / original.relative_to(self.library)).read_bytes())
        self.assertEqual(["Genres|Ambient"], ableton_tags.sample_tags(str(restored / sample.name)))

    def test_appledouble_files_are_not_sounds_or_xmp_documents(self):
        sample = self.library / "kick.wav"
        sample.write_bytes(b"audio")
        (self.library / "._kick.wav").write_bytes(b"not audio")
        sorter_engine.index_asset(str(self.library / "._kick.wav"), str(self.library), "old_scan", 1, [])
        ableton_tags.prepare_edit([str(sample)], "Drums|Kick").commit()
        info = self.library / "Ableton Folder Info"
        (info / "._metadata.xmp").write_bytes(b"not XML")
        self.assertEqual(1, sorter_engine.index_existing_library(str(self.library)))
        self.assertEqual(1, sorter_engine.count_indexed_assets(str(self.library)))
        self.assertEqual(["Drums|Kick"], ableton_tags.sample_tags(str(sample)))
        ableton_tags.prepare_edit([str(sample)], "Character|Warm").commit()
        state, snapshot = live_tag_sync.poll_live_metadata(str(self.library))
        self.assertEqual("pending", state)
        self.assertEqual("refreshed", live_tag_sync.poll_live_metadata(str(self.library), candidate=snapshot)[0])
        plan, stats = xo_filter.build_plan(str(self.library), use_live_tags=True)
        self.assertEqual(1, stats["scanned"])
        self.assertEqual([str(sample)], [path for paths in plan.values() for path in paths])

    def test_backup_write_or_scan_failure_leaves_no_success_archive(self):
        (self.library / "kick.wav").write_bytes(b"audio")
        for target in ("tab_organize.zipfile.ZipFile.write", "tab_organize.os.scandir"):
            with self.subTest(target=target), mock.patch(target, side_effect=OSError("disk or scan denied")):
                with self.assertRaisesRegex(OSError, "Backup incomplete"):
                    OrganizeTab.run_safeguard_archiver_thread(self.backup_page(), str(self.library))
            self.assertEqual([], list((self.root / "backups").glob("*.zip")))

    def test_backup_rejects_silently_missing_archive_entries(self):
        (self.library / "kick.wav").write_bytes(b"audio")
        with mock.patch("tab_organize.zipfile.ZipFile.write"):
            with self.assertRaisesRegex(OSError, "every selected file"):
                OrganizeTab.run_safeguard_archiver_thread(self.backup_page(), str(self.library))
        self.assertEqual([], list((self.root / "backups").glob("*.zip")))

    def test_backups_are_unique_even_with_identical_start_times(self):
        (self.library / "kick.wav").write_bytes(b"audio")
        paths = [
            OrganizeTab.run_safeguard_archiver_thread(self.backup_page(), str(self.library))[1]
            for _ in range(2)
        ]
        self.assertNotEqual(*paths)
        self.assertTrue(all(Path(path).is_file() for path in paths))

    def test_move_pipeline_does_not_run_shell_repairs_or_remove_nested_content(self):
        nested = self.library / "Presets" / "Instruments" / "Presets" / "Instruments"
        nested.mkdir(parents=True)
        deep = nested / "keep" / "precious.adg"
        deep.parent.mkdir()
        deep.write_bytes(b"precious")
        done = threading.Event()
        messages = []
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.library), str(self.library),
            SimpleNamespace(after=lambda delay, callback: callback()),
            messages.append, lambda *args: done.set(), copy_mode=False,
            smart_learning_enabled=False,
        )
        with mock.patch.object(sorter_engine.subprocess, "run") as shell:
            sorter.start_parallel_sort()
            self.assertTrue(done.wait(5))
            sorter.worker_thread.join(5)
        shell.assert_not_called()
        remaining = list(self.library.rglob("precious.adg"))
        self.assertEqual(1, len(remaining))
        self.assertEqual(b"precious", remaining[0].read_bytes())
        if remaining[0] != deep:
            self.assertIsNotNone(sorter.move_log_path)
            records = [json.loads(line) for line in Path(sorter.move_log_path).read_text().splitlines()]
            self.assertTrue(any(record["source"] == str(deep) for record in records))
        self.assertFalse(hasattr(sorter, "nuclear_powershell_flatten"))

    @unittest.skipIf(os.name == "nt", "POSIX mode bits require a native POSIX filesystem")
    def test_move_preserves_posix_read_permissions(self):
        source = self.library / "kick.wav"
        source.write_bytes(b"audio")
        source.chmod(0o640)
        destination = self.root / "output"
        done = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.library), str(destination),
            SimpleNamespace(after=lambda delay, callback: callback()),
            lambda message: None, lambda *args: done.set(), copy_mode=False,
            smart_learning_enabled=False,
        )
        sorter.start_parallel_sort()
        self.assertTrue(done.wait(5))
        sorter.worker_thread.join(5)
        self.assertEqual([], sorter.operation_errors)
        output = next(destination.rglob("kick.wav"))
        self.assertEqual(b"audio", output.read_bytes())
        self.assertEqual(0o640, output.stat().st_mode & 0o777)

    def test_pipeline_scan_failure_reports_error_and_moves_nothing(self):
        sample = self.library / "kick.wav"
        sample.write_bytes(b"audio")
        scheduled, messages, completed = [], [], []
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.library), str(self.root / "output"),
            SimpleNamespace(after=lambda delay, callback: scheduled.append(callback)),
            messages.append, lambda *args: completed.append(args), copy_mode=False,
            smart_learning_enabled=False,
        )
        with mock.patch.object(sorter_engine.os, "scandir", side_effect=OSError("permission denied")):
            sorter.start_parallel_sort()
            sorter.worker_thread.join(5)
        self.assertFalse(sorter.is_running())
        for callback in scheduled:
            callback()
        self.assertEqual(1, len(completed))
        self.assertEqual(1, sorter.stats["Errors/Skipped Files"])
        self.assertTrue(any("permission denied" in text for text in messages))
        self.assertEqual(b"audio", sample.read_bytes())
        self.assertFalse((self.root / "output").exists())

    def test_macos_default_library_and_preferences_use_native_locations(self):
        preferences = self.root / "Library" / "Preferences" / "Ableton"
        (preferences / "Live 12.9").mkdir(parents=True)
        (preferences / "Live 12.10").mkdir()
        with mock.patch.object(gui_theme, "CURRENT_OS", "Darwin"), mock.patch.object(
            gui_theme, "USER_HOME", str(self.root)
        ):
            self.assertEqual(
                os.path.normpath(str(self.root / "Music" / "Ableton" / "User Library")),
                gui_theme.resolve_user_library_path(),
            )
            options, log = gui_theme.resolve_live_telemetry_coordinates()
        self.assertEqual(str(preferences / "Live 12.10" / "Options.txt"), options)
        self.assertEqual(str(preferences / "Live 12.10" / "Log.txt"), log)

    def test_ordinary_undo_refuses_changed_content_and_legacy_logs(self):
        source = self.root / "original.wav"
        destination = self.library / "moved.wav"
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                destination.write_bytes(b"original")
                record = {"source": str(source), "destination": str(destination)}
                if not legacy:
                    record["destination_identity"] = sorter_engine._file_identity(destination)
                    destination.write_bytes(b"modified")
                log = self.root / "move.jsonl"
                log.write_text(json.dumps(record) + "\n")
                result = sorter_engine.undo_move_log(str(log))
                self.assertEqual(0, result["restored"])
                self.assertEqual(1, result["skipped"])
                self.assertTrue(result["errors"])
                self.assertFalse(source.exists())
                self.assertTrue(destination.exists())
                self.assertTrue(log.exists())

    def test_reviewed_nested_repair_is_logged_and_can_be_undone(self):
        nested = self.library / "Samples" / "Samples"
        nested.mkdir(parents=True)
        source = nested / "kick.wav"
        source.write_bytes(b"audio")
        destination = nested.parent / source.name
        ableton_tags.prepare_edit([str(source)], "Drums|Kick").commit()
        sorter_engine.index_existing_library(str(self.library))
        result = sorter_engine.repair_nested_folder_files([{
            "source": str(source), "destination": str(destination),
        }])
        self.assertEqual(1, result["moved"])
        log = sorter_engine.latest_move_log()
        self.assertIsNotNone(log)
        result = sorter_engine.undo_move_log(log)
        self.assertEqual([], result["errors"])
        self.assertEqual(1, result["restored"])
        self.assertEqual(["Drums|Kick"], ableton_tags.sample_tags(str(source)))
        self.assertEqual(b"audio", source.read_bytes())

    def test_xo_collision_never_overwrites_existing_hardlinked_output(self):
        source = self.library / "kick.wav"
        source.write_bytes(b"new")
        dest = self.root / "xo" / "Kicks"
        dest.mkdir(parents=True)
        (dest / source.name).write_bytes(b"base")
        digest = hashlib.sha1(str(source).encode("utf-8", "ignore")).hexdigest()[:6]
        occupied = dest / f"kick_{digest}.wav"
        other = self.root / "other.wav"
        other.write_bytes(b"keep")
        os.link(other, occupied)
        with mock.patch("xo_filter.os.link", side_effect=OSError("cross-device")):
            result = xo_filter.build_folder({"Kicks": [str(source)]}, str(dest.parent), str(self.library))
        self.assertEqual(1, result["copied"])
        self.assertEqual(b"keep", occupied.read_bytes())
        self.assertEqual(b"keep", other.read_bytes())
        self.assertEqual(b"base", (dest / source.name).read_bytes())
        self.assertEqual(b"new", (dest / f"kick_{digest}_1.wav").read_bytes())

    def test_xo_copy_fallback_handles_destination_created_after_allocation(self):
        source = self.library / "kick.wav"
        source.write_bytes(b"new")
        dest = self.root / "xo"
        raced = dest / "Kicks" / source.name
        def race(*args):
            if not raced.exists():
                raced.write_bytes(b"raced")
            raise OSError("cross-device")
        with mock.patch("xo_filter.os.link", side_effect=race):
            result = xo_filter.build_folder({"Kicks": [str(source)]}, str(dest), str(self.library))
        self.assertEqual(1, result["copied"])
        self.assertEqual(b"raced", raced.read_bytes())
        self.assertEqual(2, len(list((dest / "Kicks").iterdir())))

    def test_xo_exclusive_copy_retains_audio_and_modification_time(self):
        source = self.library / "kick.wav"
        source.write_bytes(b"sample")
        os.utime(source, (1000000000, 1000000000))
        destination = self.root / "XO"
        with mock.patch.object(xo_filter.os, "link", side_effect=OSError("different volume")):
            result = xo_filter.build_folder({"Kicks": [str(source)]}, str(destination), str(self.library))
        output = destination / "Kicks" / source.name
        self.assertEqual(1, result["copied"])
        self.assertEqual(b"sample", output.read_bytes())
        self.assertEqual(source.stat().st_mtime_ns, output.stat().st_mtime_ns)

    def test_frozen_macos_state_is_outside_bundle_and_independent_of_cwd(self):
        support = self.root / "Library" / "Application Support" / "AbletonLibraryManager"
        with mock.patch.object(sorter_engine.sys, "platform", "darwin"), mock.patch.object(
            sorter_engine.sys, "frozen", True, create=True
        ), mock.patch.object(sorter_engine.os.path, "expanduser", return_value=str(support)):
            self.assertEqual(str(support / "library_config.json"), sorter_engine._runtime_file("library_config.json"))
            self.assertEqual(str(support / "library_assets.db"), sorter_engine._runtime_file("library_assets.db"))
        self.assertTrue(support.is_dir())


class RecoveryUiTests(unittest.TestCase):
    setUp = app_fixture.WindowsReleaseAcceptanceTests.setUp
    close_app = app_fixture.WindowsReleaseAcceptanceTests.close_app
    wait = app_fixture.WindowsReleaseAcceptanceTests.wait

    def test_cleanup_button_keeps_requested_size_with_long_backup_path_on_resize(self):
        page = self.app.organize_panel
        self.app.tab_notebook.select(page)
        page.backup_location_var.set("Backup folder: " + str(self.library / ("long-folder-name-" * 12)))
        for width, height in ((1180, 760), (1020, 700), (1400, 800), (1020, 700)):
            self.app.geometry(f"{width}x{height}")
            self.app.update()
            button = page.btn_execute
            with self.subTest(width=width, height=height):
                self.assertTrue(button.winfo_ismapped())
                self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
                self.assertLessEqual(
                    button.winfo_rootx() + button.winfo_width(),
                    button.master.winfo_rootx() + button.master.winfo_width(),
                )
                self.assertGreaterEqual(
                    page.lbl_backup_location.winfo_rooty(),
                    button.winfo_rooty() + button.winfo_height(),
                )

    def test_shutdown_waits_for_blocked_undo_and_does_not_interrupt_recovery(self):
        entered, release = threading.Event(), threading.Event()
        def undo():
            entered.set()
            if not release.wait(5):
                raise OSError("fixture timeout")
            return {"restored": 1, "skipped": 0, "errors": []}
        page = self.app.organize_panel
        try:
            self.assertTrue(page._start_job("undo", undo))
            self.assertTrue(entered.wait(1))
            with mock.patch.object(self.app, "destroy") as destroy:
                self.app.request_graceful_shutdown()
                self.app.update()
                destroy.assert_not_called()
                release.set()
                deadline = time.monotonic() + 5
                while not destroy.called and time.monotonic() < deadline:
                    self.app.update()
                    time.sleep(0.01)
                destroy.assert_called_once()
            self.assertFalse(page.has_pending_job())
            self.assertEqual([], self.callbacks)
        finally:
            release.set()
            for thread, _cancel in getattr(self.app, "_background_jobs", []):
                thread.join(5)

    def test_backup_failure_requires_explicit_bypass_on_main_thread(self):
        page = self.app.organize_panel
        page.library_dir_var.set(str(self.library))
        with mock.patch.object(page, "run_safeguard_archiver_thread", side_effect=OSError("disk full")), mock.patch(
            "tab_organize.messagebox.askyesno", return_value=False
        ) as question, mock.patch.object(page, "kickoff_sorting_engine") as sort:
            page.execute_library_restructure()
            self.wait(lambda: not page.has_pending_job())
        question.assert_called_once()
        self.assertIn("disk full", question.call_args.args[1])
        sort.assert_not_called()
        self.assertEqual("normal", page.btn_execute.cget("state"))

    def test_organize_operations_cannot_overlap_a_sort_or_preview(self):
        page = self.app.organize_panel
        with mock.patch.object(page, "_start_job") as job, mock.patch(
            "tab_organize.messagebox.askyesno"
        ) as question, mock.patch.object(sorter_engine, "ParallelLibrarySorter") as sorter:
            for flag in ("_sort_pending", "preview_running"):
                setattr(page, flag, True)
                try:
                    self.assertTrue(page.has_pending_job())
                    page.scan_nested_folders()
                    page.repair_nested_folders()
                    page.undo_last_cleanup()
                    page.preview_cleanup()
                    page.execute_library_restructure()
                finally:
                    setattr(page, flag, False)
            job.assert_not_called()
            question.assert_not_called()
            sorter.assert_not_called()

    def test_failed_job_does_not_open_a_modal_dialog_while_closing(self):
        page = self.app.organize_panel
        page._job_pending = True
        page._job_results.put(("undo", None, OSError("fixture failure")))
        self.app._closing = True
        try:
            with mock.patch("tab_organize.messagebox.showerror") as dialog:
                page._poll_job_results()
            dialog.assert_not_called()
            self.assertFalse(page.has_pending_job())
        finally:
            self.app._closing = False

    def test_toplevel_worker_registers_on_application_root(self):
        dialog = tk.Toplevel(self.app)
        release = threading.Event()
        cancelled = []
        thread = gui_theme.start_background_job(dialog, lambda: release.wait(5), cancel=lambda: cancelled.append(True))
        try:
            self.assertIn(thread, [job for job, _cancel in self.app._background_jobs])
            self.assertFalse(thread.daemon)
            with mock.patch.object(self.app, "destroy"):
                self.app.request_graceful_shutdown()
            self.assertEqual([True], cancelled)
        finally:
            release.set()
            thread.join(5)
            dialog.destroy()

    def test_native_macos_quit_uses_the_same_graceful_shutdown_handler(self):
        self.app.tk.eval("namespace eval ::tk::mac {}")
        with mock.patch("platform.system", return_value="Darwin"), mock.patch.object(
            self.app, "request_graceful_shutdown"
        ) as shutdown:
            self.app.install_shutdown_handlers()
            self.app.tk.call("tk::mac::Quit")
        shutdown.assert_called_once_with()

    def test_discovery_hides_personal_tags_without_removing_stored_data(self):
        browser = self.app.tags_panel
        connection = sorter_engine._asset_index_connection()
        with connection:
            connection.execute(
                "INSERT INTO asset_tags VALUES (?, 'legacy-label', 1, 'personal')", (str(self.sample),)
            )
        connection.close()
        browser._open_discovery_filters()
        dialog = next(
            child for child in browser.winfo_children()
            if isinstance(child, tk.Toplevel) and child.title() == "Add discovery filters"
        )
        def find_list(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Listbox):
                    return child
                result = find_list(child)
                if result is not None:
                    return result
            return None
        choices = find_list(dialog).get(0, "end")
        self.assertFalse(any("legacy-label" in choice for choice in choices))
        self.assertNotIn("legacy-label", sorter_engine.get_asset_tags(str(self.sample)))
        dialog.destroy()

    def test_startup_rescan_defers_without_modal_during_metadata_edit(self):
        browser = self.app.tags_panel
        browser._live_batch_dialog = object()
        try:
            with mock.patch("tab_tags.show_notice") as notice, mock.patch.object(browser, "after") as schedule:
                browser.rescan_library(notify_busy=False)
            notice.assert_not_called()
            schedule.assert_called_once()
            self.assertEqual(500, schedule.call_args.args[0])
            self.assertFalse(browser._refresh_running)
        finally:
            browser._live_batch_dialog = None


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import library_state
import ableton_tags
import sorter_engine
from tab_import import ImportTab


class ImportRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / "stable"
        self.profile.mkdir()
        for name, value in (
            ("CONFIG_FILE", str(self.profile / "library_config.json")),
            ("ASSET_INDEX_FILE", str(self.profile / "library_assets.db")),
            ("CONFIG_LOAD_ERROR", None), ("XO_CONFIG_LOAD_ERROR", None),
            ("IGNORED_DIRECTORIES", list(sorter_engine.IGNORED_DIRECTORIES)),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.current = sorter_engine._default_config()
        self.current["IGNORED_DIRECTORIES"] = ["Keep current"]
        sorter_engine._write_config(self.current, create_backup=False)
        self.legacy = self.root / "old-build"
        self.legacy.mkdir()
        self.old = self.legacy / "library_config.json"
        self.old.write_text(json.dumps({"IGNORED_DIRECTORIES": ["MIDI STUFF"]}))

    def test_conflicting_legacy_skip_settings_block_sort_until_explicit_merge(self):
        library_state.migrate_legacy_state([self.legacy], self.profile)
        pending = sorter_engine.pending_legacy_exclusions()
        self.assertEqual(["MIDI STUFF"], pending[0]["missing"])
        worker = sorter_engine.ParallelLibrarySorter(
            str(self.root / "incoming"), str(self.root / "library"),
            SimpleNamespace(after=lambda _delay, callback: callback()),
            mock.Mock(), mock.Mock(),
        )
        self.assertIsNone(worker._claim_job("Import"))
        self.assertIn("MIDI STUFF", worker.operation_errors[0]["error"])
        sorter_engine.merge_legacy_exclusions(
            self.old, expected_digest=pending[0]["digest"],
        )
        saved = json.loads(Path(sorter_engine.CONFIG_FILE).read_text())
        self.assertEqual(["Keep current", "MIDI STUFF", "No Key Info"], saved["IGNORED_DIRECTORIES"])
        self.assertEqual(self.current["DRUM_KEYWORDS"], saved["DRUM_KEYWORDS"])
        self.assertEqual([], sorter_engine.pending_legacy_exclusions())
        sorter_engine.load_external_config()
        self.assertIn("MIDI STUFF", sorter_engine.IGNORED_DIRECTORIES)
        sorter_engine.save_ignored_directories(["Keep current"])
        self.assertEqual([], sorter_engine.pending_legacy_exclusions())

    def test_changed_legacy_profile_requires_new_review(self):
        library_state.migrate_legacy_state([self.legacy], self.profile)
        digest = sorter_engine.pending_legacy_exclusions()[0]["digest"]
        self.old.write_text(json.dumps({"IGNORED_DIRECTORIES": ["changed"]}))
        original = Path(sorter_engine.CONFIG_FILE).read_bytes()
        with self.assertRaisesRegex(ValueError, "changed during review"):
            sorter_engine.merge_legacy_exclusions(self.old, expected_digest=digest)
        self.assertEqual(original, Path(sorter_engine.CONFIG_FILE).read_bytes())

    def test_registry_remembers_old_profile_when_next_build_has_no_local_state(self):
        library_state.migrate_legacy_state([self.legacy], self.profile)
        new_build = self.root / "new-build"
        new_build.mkdir()
        library_state.migrate_legacy_state([new_build], self.profile)
        self.assertEqual(str(self.old), sorter_engine.pending_legacy_exclusions()[0]["path"])

    def test_invalid_folder_entries_are_rejected_before_merging(self):
        self.old.write_text(json.dumps({"IGNORED_DIRECTORIES": [123]}))
        original = Path(sorter_engine.CONFIG_FILE).read_bytes()
        with self.assertRaisesRegex(ValueError, "folder names"):
            sorter_engine.merge_legacy_exclusions(self.old)
        self.assertEqual(original, Path(sorter_engine.CONFIG_FILE).read_bytes())

    def test_cancel_requests_safe_stop_without_enabling_another_import(self):
        worker = mock.Mock()
        worker.is_running.return_value = True
        panel = SimpleNamespace(
            active_sorter=worker, cancel_btn=mock.Mock(), write_console_message=mock.Mock(),
        )
        ImportTab.cancel_import(panel)
        worker.cancel.assert_called_once()
        panel.cancel_btn.config.assert_called_once_with(state="disabled")
        self.assertIn("Completed moves remain", panel.write_console_message.call_args.args[0])

    def test_audio_only_preview_and_copy_exclude_resources_and_preserve_originals(self):
        incoming = self.root / "MDrummer"
        incoming.mkdir()
        original = {}
        for suffix in sorter_engine.AUDIO_EXTS | {".mdDrumset", ".fxp", ".mid", ".json", ".txt"}:
            path = incoming / ("kick" + suffix.upper())
            path.write_bytes(("fixture " + suffix).encode())
            original[path] = path.read_bytes()
        sample = next(path for path in original if path.suffix.lower() == ".wav")
        ableton_tags.prepare_edit([str(sample)], "Drums|Kick").commit()
        source_snapshot = {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in incoming.rglob("*") if path.is_file()
        }
        destination = self.root / "library"
        workers = []
        for preview in (True, False):
            completed = threading.Event()
            worker = sorter_engine.ParallelLibrarySorter(
                str(incoming), str(destination),
                SimpleNamespace(after=lambda _delay, callback: callback()),
                lambda _: None, lambda *_: completed.set(),
                copy_mode=True, audio_only=True, preview_only=preview,
                smart_learning_enabled=False,
            )
            worker.start_parallel_sort()
            self.assertTrue(completed.wait(30))
            worker.worker_thread.join()
            self.assertEqual([], worker.operation_errors)
            self.assertEqual(5, worker.stats["Non-audio Files Excluded"])
            self.assertEqual(len(sorter_engine.AUDIO_EXTS), worker.total_files)
            self.assertEqual(
                sorter_engine.AUDIO_EXTS,
                {Path(record["source"]).suffix.lower() for record in worker.operation_plan},
            )
            if preview:
                self.assertFalse(destination.exists())
            workers.append(worker)
        self.assertEqual(
            {r["source"]: r["destination_path"] for r in workers[0].preview_records},
            {r["source"]: r["destination_path"] for r in workers[1].operation_plan},
        )
        for path, contents in original.items():
            self.assertEqual(contents, path.read_bytes())
        self.assertEqual(source_snapshot, {
            path: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in incoming.rglob("*") if path.is_file()
        })
        for record in workers[1].operation_plan:
            self.assertEqual(original[Path(record["source"])], Path(record["destination_path"]).read_bytes())
        self.assertFalse(any(
            path.suffix.lower() in {".mddrumset", ".fxp", ".mid", ".json", ".txt"}
            for path in destination.rglob("*") if path.is_file()
            and "Ableton Folder Info" not in path.parts
        ))

    def test_audio_only_single_file_caller_cannot_route_a_drumset(self):
        source = self.root / "kick.mdDrumset"
        source.write_bytes(b"resource")
        worker = sorter_engine.ParallelLibrarySorter(
            str(self.root), str(self.root.parent / "other-library"),
            SimpleNamespace(after=lambda _delay, callback: callback()),
            mock.Mock(), mock.Mock(), audio_only=True, copy_mode=True,
        )
        worker.process_single_file(str(self.root), source.name)
        self.assertEqual([], worker.operation_plan)
        self.assertEqual(1, worker.stats["Non-audio Files Excluded"])
        self.assertTrue(source.exists())

    def test_audio_only_rejects_overlapping_targets_before_work(self):
        for copy, destination in (
            (False, self.root / "nested"),
            (True, self.root),
            (True, self.root / "nested"),
        ):
            with self.subTest(copy=copy, destination=destination):
                done = mock.Mock()
                worker = sorter_engine.ParallelLibrarySorter(
                    str(self.root), str(destination),
                    SimpleNamespace(after=lambda _delay, callback: callback()),
                    mock.Mock(), done, audio_only=True, copy_mode=copy,
                )
                worker.start_parallel_sort()
                done.assert_called_once()
                self.assertIsNone(worker.worker_thread)
                self.assertEqual(1, len(worker.operation_errors))
                self.assertEqual([], worker.operation_plan)

    def test_audio_only_ui_passes_filter_independently_of_copy_mode(self):
        panel = mock.MagicMock()
        panel.active_sorter = None
        panel.audio_only_var.get.return_value = True
        panel._selected_scope.return_value = (True, False)
        panel.winfo_toplevel.return_value._closing = False
        panel.src_dir_var.get.return_value = str(self.root)
        panel.dest_dir_var.get.return_value = str(self.root / "library")
        panel.copy_mode_var.get.return_value = False
        with mock.patch("tab_import.gui_theme.library_job_available", return_value=True), \
                mock.patch("tab_import.ParallelLibrarySorter") as worker:
            ImportTab._start_import(panel, preview=True)
        self.assertTrue(worker.call_args.kwargs["audio_only"])
        self.assertFalse(worker.call_args.kwargs["copy_mode"])
        self.assertTrue(worker.call_args.kwargs["preview_only"])

    def test_audio_only_move_preserves_resources_and_can_be_undone(self):
        incoming = self.root / "MDrummer"
        incoming.mkdir()
        audio = incoming / "kick.wav"
        resource = incoming / "kick.mdDrumset"
        audio.write_bytes(b"audio")
        resource.write_bytes(b"resource")
        done = threading.Event()
        worker = sorter_engine.ParallelLibrarySorter(
            str(incoming), str(self.root / "library"),
            SimpleNamespace(after=lambda _delay, callback: callback()),
            lambda _: None, lambda *_: done.set(), audio_only=True, copy_mode=False,
            smart_learning_enabled=False,
        )
        worker.start_parallel_sort()
        self.assertTrue(done.wait(30))
        worker.worker_thread.join()
        self.assertEqual([], worker.operation_errors)
        self.assertFalse(audio.exists())
        self.assertEqual(b"resource", resource.read_bytes())
        self.assertEqual(1, len(worker.operation_plan))
        self.assertEqual(
            {"restored": 1, "skipped": 0, "errors": []},
            sorter_engine.undo_move_log(worker.move_log_path),
        )
        self.assertEqual(b"audio", audio.read_bytes())
        self.assertEqual(b"resource", resource.read_bytes())

    def test_audio_only_move_apply_warning_can_abort_without_creating_destination(self):
        panel = mock.MagicMock()
        panel.active_sorter = None
        panel._undo_pending = False
        panel.winfo_toplevel.return_value._closing = False
        panel.audio_only_var.get.return_value = True
        panel._selected_scope.return_value = (True, False)
        panel.copy_mode_var.get.return_value = False
        panel.src_dir_var.get.return_value = str(self.root)
        panel.dest_dir_var.get.return_value = str(self.root / "destination")
        with mock.patch("tab_import.gui_theme.library_job_available", return_value=True), \
                mock.patch("tab_import.messagebox.askyesno", return_value=False) as confirm, \
                mock.patch("tab_import.ParallelLibrarySorter") as worker:
            ImportTab._start_import(panel, preview=False, approved_plan={"kind": "ordinary"})
        confirm.assert_called_once()
        worker.assert_not_called()
        self.assertFalse((self.root / "destination").exists())

    def test_audio_only_does_not_override_complete_serum_resource_workflow(self):
        panel = mock.MagicMock()
        panel.active_sorter = None
        panel.audio_only_var.get.return_value = True
        panel._selected_scope.return_value = (True, False)
        panel.copy_mode_var.get.return_value = True
        panel.src_dir_var.get.return_value = str(self.root)
        panel.dest_dir_var.get.return_value = str(self.root / "library")
        panel.winfo_toplevel.return_value._closing = False
        with mock.patch("tab_import.gui_theme.library_job_available", return_value=True), \
                mock.patch("tab_import.serum_presets.is_resource_root", return_value=True), \
                mock.patch("tab_import.messagebox.showwarning") as notice, \
                mock.patch("tab_import.SerumResourceImporter") as worker:
            ImportTab._start_import(panel, preview=True)
        notice.assert_called_once()
        worker.assert_not_called()
        self.assertFalse((self.root / "library").exists())

    def test_undo_confirms_specific_log_and_uses_shared_background_job(self):
        log = self.root / "moves_1.jsonl"
        log.write_text(json.dumps({
            "source": str(self.root / "incoming" / "kick.wav"),
            "destination": str(self.root / "library" / "kick.wav"),
            "job_kind": "import", "record_id": "1", "copy_mode": False,
        }) + "\n")
        panel = SimpleNamespace(
            _undo_pending=False, _undo_results=queue.Queue(),
            winfo_toplevel=lambda: SimpleNamespace(_closing=False),
            run_btn=mock.Mock(), undo_btn=mock.Mock(),
            preview_btn=mock.Mock(), apply_btn=mock.Mock(), export_btn=mock.Mock(),
        )
        def start(_owner, work, **kwargs):
            self.assertEqual("Undo Move import", kwargs["library_job"])
            work()
            return mock.Mock()
        result = {"restored": 1, "skipped": 0, "errors": []}
        with mock.patch("tab_import.gui_theme.library_job_available", return_value=True), \
                mock.patch("tab_import.filedialog.askopenfilename", return_value=str(log)), \
                mock.patch("tab_import.messagebox.askyesno", return_value=True) as confirm, \
                mock.patch("tab_import.gui_theme.start_background_job", side_effect=start), \
                mock.patch.object(sorter_engine, "undo_move_log", return_value=result) as undo:
            ImportTab.undo_move_import(panel)
        undo.assert_called_once_with(str(log))
        self.assertIn(str(log), confirm.call_args.args[1])
        self.assertIn("Undo this history item", confirm.call_args.args[0])
        self.assertIn("Copy imports cannot be undone", confirm.call_args.args[1])
        self.assertEqual((result, None), panel._undo_results.get_nowait())

    def test_selected_copy_history_cannot_be_confirmed_or_undone(self):
        log = self.root / "copy_1.jsonl"
        log.write_text(json.dumps({
            "source": str(self.root / "incoming" / "kick.wav"),
            "destination": str(self.root / "library" / "kick.wav"),
            "job_kind": "import", "record_id": "1", "copy_mode": True,
        }) + "\n")
        panel = SimpleNamespace(
            _undo_pending=False, _undo_results=queue.Queue(),
            winfo_toplevel=lambda: SimpleNamespace(_closing=False),
        )
        with mock.patch("tab_import.gui_theme.library_job_available", return_value=True), \
                mock.patch("tab_import.messagebox.askyesno") as confirm, \
                mock.patch("tab_import.messagebox.showerror") as error, \
                mock.patch.object(sorter_engine, "undo_move_log") as undo:
            ImportTab.undo_move_import(panel, str(log))
        confirm.assert_not_called()
        undo.assert_not_called()
        error.assert_called_once()
        self.assertIn("Copy imports cannot be undone", error.call_args.args[1])


if __name__ == "__main__":
    unittest.main()

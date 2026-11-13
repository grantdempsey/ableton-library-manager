import os
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import serum_presets
import performance_log
import sorter_engine
from tab_import import ImportTab


class ImmediateWindow:
    def after(self, _delay, callback):
        callback()


class SerumResourceImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        patcher = mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.root / "assets.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.source = self.root / "Xfer" / "Serum 2 Presets"
        self.library = self.root / "User Library"
        self.target = self.library / "Serum 2 Presets"
        for folder in ("Presets", "Tables", "Samples", "Curves", "LFO Shapes"):
            (self.source / folder / "User").mkdir(parents=True)
        self.contents = {
            "Presets/Factory/Bass/BS Factory.SerumPreset": b"factory-preset",
            "Presets/User/Custom Pack/BS Mine.fxp": b"user-preset",
            "Tables/User/kick.wav": b"wavetable-not-a-drum",
            "Samples/User/pad.wav": b"sample-not-a-pad-preset",
            "LFO Shapes/User/shape.lfo": b"lfo",
            "System/settings.json": b'{"setting": true}',
            "Arp Patterns/Factory/a/b/c/d/e/f/g/h/pattern.arp": b"deep-resource",
            ".hidden-resource": b"hidden",
            "ReadMe.txt": b"resource-instructions",
        }
        for relative, content in self.contents.items():
            path = self.source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.original = self.snapshot(self.source)

    @staticmethod
    def snapshot(root):
        return {
            str(path.relative_to(root)): (
                path.read_bytes(), path.stat().st_mtime_ns
            ) for path in root.rglob("*") if path.is_file()
        }

    def run_import(self, *, preview=False, copy_mode=True, source=None, library=None):
        completed = threading.Event()
        callbacks = []
        worker = sorter_engine.SerumResourceImporter(
            str(source or self.source), str(library or self.library),
            ImmediateWindow(), lambda _message: None,
            lambda stats, mode: (callbacks.append((stats, mode)), completed.set()),
            preview_only=preview, copy_mode=copy_mode,
        )
        worker.start_parallel_sort()
        self.assertTrue(completed.wait(10), "resource import did not finish")
        worker.worker_thread.join(5)
        self.assertEqual(1, len(callbacks))
        return worker

    def assert_source_unchanged(self):
        self.assertEqual(self.original, self.snapshot(self.source))
        self.assertTrue((self.source / "Curves" / "User").is_dir())

    def test_preview_then_copy_preserves_every_resource_and_empty_folder(self):
        with mock.patch.object(sorter_engine, "index_asset") as index:
            preview = self.run_import(preview=True)
            self.assertEqual([], preview.operation_errors)
            self.assertEqual(len(self.contents), len(preview.preview_records))
            self.assertEqual(
                len(self.contents), preview.stats["Serum 2 Resource Files Planned"]
            )
            self.assertFalse(self.library.exists())
            copied = self.run_import()
            index.assert_not_called()
        self.assertEqual([], copied.operation_errors)
        self.assertEqual(len(self.contents), copied.stats["Serum 2 Resource Files Copied"])
        self.assertEqual(self.original, self.snapshot(self.target))
        self.assertTrue((self.target / "Curves" / "User").is_dir())
        self.assertFalse((self.target / "Serum 2 Presets").exists())
        self.assertFalse((self.library / "Samples").exists())
        self.assert_source_unchanged()

    def test_repeat_copy_skips_identical_files_without_touching_destination(self):
        self.assertEqual([], self.run_import().operation_errors)
        previous = self.snapshot(self.target)
        (self.target / "Presets" / "User" / "Only In Library.fxp").write_bytes(b"keep")
        repeat = self.run_import()
        self.assertEqual([], repeat.operation_errors)
        self.assertEqual(0, repeat.stats["Serum 2 Resource Files Copied"])
        self.assertEqual(len(self.contents), repeat.stats["Skipped Duplicate Items"])
        for relative, identity in previous.items():
            path = self.target / relative
            self.assertEqual(identity, (path.read_bytes(), path.stat().st_mtime_ns))
        self.assertEqual(b"keep", (self.target / "Presets" / "User" / "Only In Library.fxp").read_bytes())
        self.assert_source_unchanged()

    def test_resource_copy_logs_real_counts_and_bytes_without_content(self):
        self.run_import()
        self.run_import()
        self.run_import(preview=True)
        with next(performance_log.log_directory().glob("*.jsonl")).open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle]
        self.assertEqual(3, len(records))
        self.assertEqual("serum_resource_import", records[0]["operation"])
        self.assertEqual(len(self.contents), records[0]["completed_files"])
        self.assertEqual(len(self.contents), records[0]["planned_files"])
        self.assertEqual(sum(map(len, self.contents.values())), records[0]["transferred_bytes"])
        self.assertEqual(len(self.contents), records[1]["completed_files"])
        self.assertEqual(0, records[1]["transferred_bytes"])
        self.assertTrue(records[2]["preview"])
        self.assertEqual(0, records[2]["completed_files"])
        self.assertEqual(0, records[2]["transferred_bytes"])
        self.assertEqual(len(self.contents), records[2]["processed_files"])
        self.assertNotIn("BS Mine", json.dumps(records))

    def test_conflict_aborts_entire_import_before_writing_any_resource(self):
        conflict = self.target / "Tables" / "User" / "kick.wav"
        conflict.parent.mkdir(parents=True)
        conflict.write_bytes(b"existing-different-table")
        for preview in (True, False):
            with self.subTest(preview=preview):
                worker = self.run_import(preview=preview)
                self.assertEqual(1, len(worker.operation_errors))
                self.assertIn("Different resource file", worker.operation_errors[0]["error"])
                self.assertEqual(0, worker.stats["Serum 2 Resource Files Copied"])
                self.assertEqual([], worker.preview_records)
                self.assertEqual(
                    [conflict], [p for p in self.target.rglob("*") if p.is_file()]
                )
                self.assertEqual(b"existing-different-table", conflict.read_bytes())
        self.assert_source_unchanged()

    def test_resource_directory_conflicting_with_file_aborts_before_copy(self):
        self.target.mkdir(parents=True)
        (self.target / "Presets").write_bytes(b"not-a-directory")
        worker = self.run_import()
        self.assertEqual(1, len(worker.operation_errors))
        self.assertEqual(0, worker.stats["Serum 2 Resource Files Copied"])
        self.assert_source_unchanged()

    def test_move_mode_is_rejected_without_changing_originals(self):
        worker = self.run_import(copy_mode=False)
        self.assertIn("copy-only", worker.operation_errors[0]["error"])
        self.assertFalse(self.library.exists())
        self.assert_source_unchanged()

    def test_incomplete_resource_root_is_rejected_explicitly(self):
        (self.source / "Tables" / "User" / "kick.wav").unlink()
        (self.source / "Tables" / "User").rmdir()
        (self.source / "Tables").rmdir()
        worker = self.run_import()
        self.assertIn("complete Serum 2 resource folder", worker.operation_errors[0]["error"])
        self.assertFalse(self.library.exists())

    def test_overlapping_paths_are_rejected(self):
        for source, library in (
            (self.source, self.source.parent),
            (self.source, self.source / "nested-library"),
        ):
            with self.subTest(library=library):
                worker = self.run_import(source=source, library=library)
                self.assertIn("overlap", worker.operation_errors[0]["error"])
        self.assert_source_unchanged()

    def test_copy_failure_removes_partial_output_and_reports_error(self):
        def partial_copy(source, destination):
            destination.write(source.read(2))
            raise OSError("disk full fixture")
        with mock.patch.object(sorter_engine.shutil, "copyfileobj", side_effect=partial_copy):
            worker = self.run_import()
        self.assertIn("disk full fixture", worker.operation_errors[0]["error"])
        self.assertEqual(0, worker.stats["Serum 2 Resource Files Copied"])
        self.assertEqual([], [p for p in self.target.rglob("*") if p.is_file()])
        self.assert_source_unchanged()

    def test_changed_source_is_rejected_before_copy(self):
        worker = sorter_engine.SerumResourceImporter(
            str(self.source), str(self.library), ImmediateWindow(), lambda _: None, lambda *_: None
        )
        source = self.source / "ReadMe.txt"
        identity = sorter_engine._file_identity(source)
        source.write_bytes(b"changed")
        destination = self.root / "not-created.txt"
        with self.assertRaisesRegex(ValueError, "Source changed"):
            worker._copy_resource(source, destination, identity)
        self.assertFalse(destination.exists())

    def test_file_appearing_after_plan_is_not_overwritten(self):
        worker = sorter_engine.SerumResourceImporter(
            str(self.source), str(self.library), ImmediateWindow(), lambda _: None, lambda *_: None
        )
        source = self.source / "ReadMe.txt"
        destination = self.root / "created-by-another-import.txt"
        destination.write_bytes(b"keep-concurrent-file")
        with self.assertRaises(FileExistsError):
            worker._copy_resource(source, destination, sorter_engine._file_identity(source))
        self.assertEqual(b"keep-concurrent-file", destination.read_bytes())
        self.assert_source_unchanged()

    def test_successful_copy_can_fill_an_existing_resource_tree(self):
        duplicate = self.target / "Tables" / "User" / "kick.wav"
        duplicate.parent.mkdir(parents=True)
        duplicate.write_bytes(self.contents["Tables/User/kick.wav"])
        worker = self.run_import()
        self.assertEqual([], worker.operation_errors)
        self.assertEqual(1, worker.stats["Skipped Duplicate Items"])
        self.assertEqual(len(self.contents) - 1, worker.stats["Serum 2 Resource Files Copied"])
        self.assertEqual(
            self.contents, {str(p.relative_to(self.target)).replace(os.sep, "/"): p.read_bytes()
                            for p in self.target.rglob("*") if p.is_file()}
        )
        self.assert_source_unchanged()

    def test_source_links_report_an_explicit_error_even_without_symlink_privilege(self):
        original = Path.is_symlink
        linked_path = self.source / "ReadMe.txt"
        with mock.patch.object(
            Path, "is_symlink", lambda path: path == linked_path or original(path)
        ):
            worker = self.run_import()
        self.assertEqual(1, len(worker.operation_errors))
        self.assertIn("Linked paths are not supported", worker.operation_errors[0]["error"])
        self.assertFalse(self.library.exists())

    def test_cancel_before_start_writes_nothing(self):
        completed = threading.Event()
        worker = sorter_engine.SerumResourceImporter(
            str(self.source), str(self.library), ImmediateWindow(), lambda _: None,
            lambda *_: completed.set(),
        )
        worker.cancel()
        worker.start_parallel_sort()
        self.assertTrue(completed.wait(5))
        worker.worker_thread.join(5)
        self.assertEqual([], worker.operation_errors)
        self.assertFalse(self.library.exists())
        self.assert_source_unchanged()

    def test_resource_detection_is_not_triggered_by_loose_presets(self):
        self.assertTrue(serum_presets.is_resource_root(str(self.source)))
        self.assertFalse(serum_presets.is_resource_root(str(self.source / "Presets" / "User")))
        renamed = self.source.with_name("Custom Xfer Folder")
        self.source.rename(renamed)
        self.assertTrue(serum_presets.is_resource_root(str(renamed)))

    def test_linked_source_entry_is_rejected_without_following_it(self):
        link = self.source / "linked-resource"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Creating a symlink is unavailable: {error}")
        worker = self.run_import()
        self.assertIn("Linked paths are not supported", worker.operation_errors[0]["error"])
        self.assertIn(str(link), worker.operation_errors[0]["error"])
        self.assertFalse(self.library.exists())

    def test_import_ui_auto_selects_resource_copy_worker(self):
        panel = mock.MagicMock()
        panel.active_sorter = None
        panel.src_dir_var.get.return_value = str(self.source)
        panel.dest_dir_var.get.return_value = str(self.library)
        panel.copy_mode_var.get.return_value = True
        panel._selected_scope.return_value = (False, True)
        with mock.patch("tab_import.SerumResourceImporter") as resources, mock.patch(
            "tab_import.ParallelLibrarySorter"
        ) as sounds:
            ImportTab._start_import(panel, preview=True)
        resources.return_value.start_parallel_sort.assert_called_once()
        self.assertTrue(resources.call_args.kwargs["preview_only"])
        sounds.assert_not_called()
        self.assertFalse(self.library.exists())

    def test_import_ui_move_selection_warns_instead_of_removing_source(self):
        panel = mock.MagicMock()
        panel.active_sorter = None
        panel.src_dir_var.get.return_value = str(self.source)
        panel.dest_dir_var.get.return_value = str(self.library)
        panel.copy_mode_var.get.return_value = False
        panel._selected_scope.return_value = (False, True)
        with mock.patch("tab_import.SerumResourceImporter") as resources, mock.patch(
            "tab_import.messagebox.showwarning"
        ) as warning:
            ImportTab._start_import(panel, preview=True)
        warning.assert_called_once()
        resources.assert_not_called()
        self.assertFalse(self.library.exists())
        self.assert_source_unchanged()

    def test_import_ui_audio_only_selection_requires_supported_resource_mode(self):
        panel = mock.MagicMock()
        panel.active_sorter = None
        panel.src_dir_var.get.return_value = str(self.source)
        panel.dest_dir_var.get.return_value = str(self.library)
        panel.copy_mode_var.get.return_value = True
        panel._selected_scope.return_value = (True, False)
        with mock.patch("tab_import.SerumResourceImporter") as resources, mock.patch(
            "tab_import.ParallelLibrarySorter"
        ) as sounds, mock.patch("tab_import.messagebox.showwarning") as warning:
            ImportTab._start_import(panel, preview=True)
        warning.assert_called_once()
        self.assertIn("Audio + supported presets", warning.call_args.args[1])
        resources.assert_not_called()
        sounds.assert_not_called()
        self.assertFalse(self.library.exists())
        self.assert_source_unchanged()

    def test_completion_reports_conflicts_as_warning_not_success(self):
        panel = mock.MagicMock()
        panel.active_sorter.preview_only = False
        panel.active_sorter.cancel_event.is_set.return_value = False
        panel.active_sorter.operation_errors = [{
            "operation": "Serum 2 resource import", "source": str(self.source),
            "destination": str(self.target), "error": "Conflicting resource file",
        }]
        with mock.patch("tab_import.tab_matrix.rescan_suggestions"), mock.patch(
            "tab_import.messagebox.showwarning"
        ) as warning, mock.patch("tab_import.messagebox.showinfo") as success:
            ImportTab.handle_pipeline_completion(panel, {"Errors/Skipped Files": 1}, True)
        warning.assert_called_once()
        self.assertIn("Import needs review", warning.call_args.args[1])
        success.assert_not_called()

    def test_completion_alerts_user_to_actual_destination_and_manual_setup(self):
        worker = self.run_import()
        panel = mock.MagicMock()
        panel.active_sorter = worker
        panel.dest_dir_var.get.return_value = str(self.root / "different-ui-value")
        with mock.patch("tab_import.tab_matrix.rescan_suggestions"), mock.patch(
            "tab_import.messagebox.showinfo"
        ) as notice:
            ImportTab.handle_pipeline_completion(panel, worker.stats, True)
        text = notice.call_args.args[1]
        self.assertIn(str(self.target), text)
        self.assertIn("NEXT STEP: In Serum 2", text)
        self.assertIn("not its Presets/User subfolder", text)
        self.assertIn("Places", text)
        self.assertIn("preferences were not changed automatically", text)
        self.assertIn("does not verify that Serum 2 resolves", text)
        self.assertIn("check that its dependencies load", text)
        self.assertTrue(any(str(self.target) in call.args[0]
                            for call in panel.write_console_message.call_args_list))

    def test_preview_alert_shows_destination_without_claiming_setup_is_ready(self):
        worker = self.run_import(preview=True)
        panel = mock.MagicMock()
        panel.active_sorter = worker
        with mock.patch("tab_import.tab_matrix.rescan_suggestions"), mock.patch(
            "tab_import.messagebox.showinfo"
        ) as notice:
            ImportTab.handle_pipeline_completion(panel, worker.stats, True)
        text = notice.call_args.args[1]
        self.assertIn(str(self.target), text)
        self.assertIn("Preview complete; no files were changed", text)
        self.assertNotIn("NEXT STEP", text)


if __name__ == "__main__":
    unittest.main()

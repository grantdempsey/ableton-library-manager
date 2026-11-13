import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import ableton_tags
import sorter_engine
from tab_organize import OrganizeTab


class ImmediateWindow:
    def after(self, _delay, callback):
        callback()


class SafetyStabilizationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for name, value in (
            ("CONFIG_FILE", str(self.root / "profile.json")),
            ("ASSET_INDEX_FILE", str(self.root / "assets.db")),
            ("CONFIG_BACKUP_DIR", str(self.root / "backups")),
            ("MOVE_LOG_DIR", str(self.root / "logs")),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("DRUM_KEYWORDS", "RULE_METADATA", "SYNTH_EXTS", "NATIVE_EXTS"):
            patcher = mock.patch.object(
                sorter_engine, name, copy.deepcopy(getattr(sorter_engine, name))
            )
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_config_rejects_escaping_routes_for_all_routing_maps(self):
        for key in ("DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS"):
            for folder in ("../outside", r"..\outside", "/absolute", r"C:\outside",
                           r"C:outside", r"\\server\share", "safe/../outside",
                           r".. \outside", "folder./outside", "", 42):
                with self.subTest(key=key, folder=folder):
                    with self.assertRaises(ValueError):
                        sorter_engine._validate_config({key: {"rule": folder}})
        sorter_engine._validate_config({
            "DRUM_KEYWORDS": {"shaker": r"Percussion\Shakers"},
            "SYNTH_EXTS": {".serumpreset": "Serum 2 Presets/Presets/User"},
        })

    def test_runtime_rejects_escape_even_when_rules_bypass_config_validation(self):
        incoming = self.root / "incoming"
        library = self.root / "library"
        incoming.mkdir()
        source = incoming / "lead.fxp"
        source.write_bytes(b"preset")
        sorter_engine.SYNTH_EXTS = {".fxp": "../outside"}
        for preview in (True, False):
            with self.subTest(preview=preview):
                sorter = sorter_engine.ParallelLibrarySorter(
                    str(incoming), str(library), ImmediateWindow(), lambda _: None, lambda *_: None,
                    copy_mode=False, preview_only=preview,
                )
                sorter.process_single_file(str(incoming), source.name)
                self.assertEqual(1, len(sorter.operation_errors))
                self.assertIn("destination", sorter.operation_errors[0]["error"].lower())
                self.assertEqual([], sorter.preview_records)
                self.assertTrue(source.exists())
                self.assertFalse((self.root / "outside").exists())

    def test_resolved_destination_rejects_linked_escape(self):
        library = self.root / "library"
        library.mkdir()
        outside = self.root / "outside"
        outside.mkdir()
        route = library / "Presets"
        try:
            route.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"Creating a symlink is unavailable: {error}")
            import _winapi
            _winapi.CreateJunction(str(outside), str(route))
        source = self.root / "lead.fxp"
        source.write_bytes(b"preset")
        sorter_engine.SYNTH_EXTS = {".fxp": "Presets"}
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.root), str(library), ImmediateWindow(), lambda _: None, lambda *_: None,
            copy_mode=True,
        )
        sorter.process_single_file(str(self.root), source.name)
        self.assertEqual(1, len(sorter.operation_errors))
        self.assertFalse((outside / source.name).exists())

    @unittest.skipUnless(os.name == "nt", "Windows extended paths")
    def test_equivalent_windows_extended_paths_are_not_false_escapes(self):
        library = self.root / "library"
        library.mkdir()
        destination = library / "Presets" / "sample.fxp"
        realpath = os.path.realpath
        def prefixed_target(path):
            resolved = realpath(path)
            return "\\\\?\\" + resolved if os.fspath(path) == str(destination) else resolved
        with mock.patch.object(sorter_engine.os.path, "realpath", side_effect=prefixed_target):
            self.assertEqual(str(destination), sorter_engine._validate_destination(
                str(library), str(destination)
            ))

    def test_copy_failure_removes_partial_output_without_changing_original(self):
        source = self.root / "sample.wav"
        destination = self.root / "copy.wav"
        source.write_bytes(b"original audio")
        def partial_copy(input_file, output_file, *args, **kwargs):
            output_file.write(input_file.read(3))
            raise OSError("disk full fixture")
        with mock.patch.object(ableton_tags.shutil, "copyfileobj", side_effect=partial_copy):
            with self.assertRaisesRegex(OSError, "disk full fixture"):
                ableton_tags.transfer_sample(str(source), str(destination), copy=True)
        self.assertEqual(b"original audio", source.read_bytes())
        self.assertFalse(destination.exists())

    def test_existing_copy_destination_is_never_overwritten_or_removed(self):
        source = self.root / "sample.wav"
        destination = self.root / "copy.wav"
        source.write_bytes(b"source")
        destination.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            ableton_tags.transfer_sample(str(source), str(destination), copy=True)
        self.assertEqual(b"source", source.read_bytes())
        self.assertEqual(b"existing", destination.read_bytes())

    def test_failed_copy_metadata_preservation_removes_output(self):
        source = self.root / "sample.wav"
        destination = self.root / "copy.wav"
        source.write_bytes(b"source")
        with mock.patch.object(ableton_tags.shutil, "copystat", side_effect=OSError("metadata failure")):
            with self.assertRaisesRegex(OSError, "metadata failure"):
                ableton_tags.transfer_sample(str(source), str(destination), copy=True)
        self.assertFalse(destination.exists())
        self.assertEqual(b"source", source.read_bytes())

    def test_nested_routes_support_both_separators_and_preview_counts_once(self):
        source = self.root / "lead.fxp"
        source.write_bytes(b"preset")
        sorter_engine.SYNTH_EXTS = {".fxp": r"My Synth\Presets"}
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.root), str(self.root / "library"), ImmediateWindow(), lambda _: None,
            lambda *_: None, preview_only=True,
        )
        sorter.process_single_file(str(self.root), source.name)
        self.assertEqual([], sorter.operation_errors)
        self.assertEqual(1, sorter.processed_files)
        self.assertEqual(
            str(self.root / "library" / "My Synth" / "Presets"),
            sorter.preview_records[0]["destination"],
        )

    def test_cancel_during_scan_completes_exactly_once(self):
        incoming = self.root / "incoming"
        incoming.mkdir()
        (incoming / "kick.wav").write_bytes(b"sample")
        callbacks = []
        completed = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            str(incoming), str(self.root / "library"), ImmediateWindow(), lambda _: None,
            lambda stats, mode: (callbacks.append((stats, mode)), completed.set()),
            copy_mode=True,
        )
        scandir = os.scandir
        def cancel_on_scan(path):
            sorter.cancel()
            return scandir(path)
        with mock.patch.object(sorter_engine, "harvest_ableton_metadata", return_value={}), mock.patch.object(
            sorter_engine, "get_all_indexed_asset_tags", return_value={}
        ), mock.patch.object(sorter_engine.os, "scandir", side_effect=cancel_on_scan):
            # Add a directory so the scanner observes cancellation on its next iteration.
            (incoming / "nested").mkdir()
            sorter.start_parallel_sort()
            sorter.worker_thread.join(5)
        self.assertFalse(sorter.is_running())
        self.assertTrue(completed.is_set())
        self.assertEqual(1, len(callbacks))
        self.assertFalse((self.root / "library").exists())

    def test_preview_never_calls_index_writer(self):
        source = self.root / "lead.fxp"
        source.write_bytes(b"preset")
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.root), str(self.root / "library"), ImmediateWindow(), lambda _: None,
            lambda *_: None, preview_only=True,
        )
        with mock.patch.object(sorter_engine, "index_asset", side_effect=OSError("index unavailable")) as writer:
            sorter.process_single_file(str(self.root), source.name)
        writer.assert_not_called()
        self.assertEqual(0, sorter.stats["Errors/Skipped Files"])
        self.assertEqual([], sorter.operation_errors)
        self.assertTrue(source.exists())

    def test_skipped_undo_can_be_retried_without_archiving_log(self):
        source = self.root / "incoming" / "sample.wav"
        source.parent.mkdir()
        source.write_bytes(b"obstruction")
        destination = self.root / "library" / "sample.wav"
        destination.parent.mkdir()
        destination.write_bytes(b"original")
        log = sorter_engine._new_move_log_path()
        sorter_engine._append_move_record(
            log, str(source), str(destination),
            destination_identity=sorter_engine._file_identity(destination),
        )
        result = sorter_engine.undo_move_log(log)
        self.assertEqual(1, result["skipped"])
        self.assertTrue(Path(log).exists())
        self.assertFalse(Path(log + ".undone").exists())
        source.unlink()
        result = sorter_engine.undo_move_log(log)
        self.assertEqual(1, result["restored"])
        self.assertEqual([], result["errors"])
        self.assertEqual(b"original", source.read_bytes())
        self.assertTrue(Path(log + ".undone").exists())

    def test_completed_duplicate_undo_is_not_repeated_on_retry(self):
        incoming = self.root / "incoming"
        incoming.mkdir()
        library = self.root / "library"
        target = library / "Samples" / "One-Shots" / "Kicks"
        target.mkdir(parents=True)
        sorter_engine.DRUM_KEYWORDS = {r"\bkick\b": "Kicks"}
        sorter = sorter_engine.ParallelLibrarySorter(
            str(incoming), str(library), ImmediateWindow(), lambda _: None, lambda *_: None,
        )
        duplicate = incoming / "kick_a.wav"
        duplicate.write_bytes(b"same audio")
        (target / duplicate.name).write_bytes(b"same audio")
        blocked = incoming / "kick_b.wav"
        blocked.write_bytes(b"other audio")
        for source in (duplicate, blocked):
            sorter.process_single_file(str(incoming), source.name)
        self.assertEqual([], sorter.operation_errors)
        blocked.write_bytes(b"obstruction")
        first = sorter_engine.undo_move_log(sorter.move_log_path)
        self.assertEqual([], first["errors"])
        self.assertEqual((1, 1), (first["restored"], first["skipped"]))
        checkpoint = [json.loads(line) for line in Path(sorter.move_log_path).read_text().splitlines()]
        self.assertEqual(1, sum(bool(record.get("undo_complete")) for record in checkpoint))
        duplicate.write_bytes(b"edited after restored duplicate")
        blocked.unlink()
        second = sorter_engine.undo_move_log(sorter.move_log_path)
        self.assertEqual({"restored": 1, "skipped": 0, "errors": []}, second)
        self.assertEqual(b"edited after restored duplicate", duplicate.read_bytes())

    def test_undo_retries_index_reconciliation_after_files_were_restored(self):
        source = self.root / "incoming" / "sample.wav"
        destination = self.root / "library" / "sample.wav"
        destination.parent.mkdir()
        destination.write_bytes(b"audio")
        sorter_engine.index_asset(str(destination), str(destination.parent), "fixture", 1, [])
        log = sorter_engine._new_move_log_path()
        sorter_engine._append_move_record(
            log, str(source), str(destination),
            destination_identity=sorter_engine._file_identity(destination),
        )
        with mock.patch.object(sorter_engine, "_cache_ableton_tags", side_effect=OSError("index fixture")):
            first = sorter_engine.undo_move_log(log)
        self.assertEqual(1, first["restored"])
        self.assertTrue(first["errors"])
        self.assertTrue(source.exists())
        second = sorter_engine.undo_move_log(log)
        self.assertEqual({"restored": 0, "skipped": 0, "errors": []}, second)
        connection = sorter_engine._asset_index_connection()
        try:
            self.assertIsNotNone(connection.execute(
                "SELECT path FROM assets WHERE path = ?", (str(source),)
            ).fetchone())
            self.assertIsNone(connection.execute(
                "SELECT path FROM assets WHERE path = ?", (str(destination),)
            ).fetchone())
        finally:
            connection.close()

    def test_partial_undo_retry_recognizes_already_restored_entries(self):
        log = sorter_engine._new_move_log_path()
        sources = []
        for name in ("first.wav", "second.wav"):
            source = self.root / "incoming" / name
            source.parent.mkdir(exist_ok=True)
            destination = self.root / "library" / name
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(name.encode("ascii"))
            sources.append(source)
            sorter_engine._append_move_record(
                log, str(source), str(destination),
                destination_identity=sorter_engine._file_identity(destination),
            )
        sources[0].write_bytes(b"obstruction")
        first = sorter_engine.undo_move_log(log)
        self.assertEqual((1, 1), (first["restored"], first["skipped"]))
        self.assertEqual(1, sorter_engine.describe_move_log(log)[0])
        # A completed undo must stay completed even if that restored source changes.
        sources[1].write_bytes(b"edited after successful undo")
        sources[0].unlink()
        second = sorter_engine.undo_move_log(log)
        self.assertEqual(1, second["restored"])
        self.assertEqual(0, second["skipped"])
        self.assertEqual([], second["errors"])
        self.assertTrue(Path(log + ".undone").exists())

    def test_failed_or_cancelled_organize_preview_cannot_report_clean_plan(self):
        for cancelled in (False, True):
            panel = mock.MagicMock()
            panel.preview_sorter.preview_records = []
            panel.preview_sorter.cancel_event.is_set.return_value = cancelled
            panel.preview_sorter.operation_errors = [] if cancelled else [{
                "source": "library", "destination": "", "operation": "pipeline", "error": "access denied",
            }]
            with self.subTest(cancelled=cancelled), mock.patch(
                "tab_organize.show_notice"
            ) as notice, mock.patch("tab_organize.themed_dialog") as start:
                OrganizeTab.show_preview_results(panel, {"Errors/Skipped Files": int(not cancelled)}, False)
            self.assertNotEqual("No planned moves", notice.call_args.kwargs["heading"])
            self.assertIn("incomplete", notice.call_args.args[2].lower())
            start.assert_not_called()
            panel.execute_library_restructure.assert_not_called()
            self.assertEqual(0, panel.progress_bar.__setitem__.call_args.args[1])

    def test_failed_cleanup_warns_instead_of_reporting_success(self):
        panel = mock.MagicMock()
        panel.active_sorter.cancel_event.is_set.return_value = False
        panel.active_sorter.operation_errors = [{
            "source": "source.wav", "destination": "dest.wav",
            "operation": "move", "error": "access denied",
        }]
        with mock.patch("tab_organize.tab_matrix.rescan_suggestions"), mock.patch(
            "tab_organize.messagebox.showwarning"
        ) as warning, mock.patch("tab_organize.messagebox.showinfo") as success:
            OrganizeTab.handle_execution_complete(panel, {"Errors/Skipped Files": 1}, False)
        warning.assert_called_once()
        success.assert_not_called()
        self.assertIn("review", warning.call_args.args[1].lower())
        self.assertNotIn("verified clean", panel.status_lbl.config.call_args.kwargs["text"])

    def test_successful_and_cancelled_cleanup_have_distinct_outcomes(self):
        for cancelled in (False, True):
            panel = mock.MagicMock()
            panel.active_sorter.cancel_event.is_set.return_value = cancelled
            panel.active_sorter.operation_errors = []
            with self.subTest(cancelled=cancelled), mock.patch(
                "tab_organize.tab_matrix.rescan_suggestions"
            ), mock.patch("tab_organize.messagebox.showwarning") as warning, mock.patch(
                "tab_organize.messagebox.showinfo"
            ) as success:
                OrganizeTab.handle_execution_complete(panel, {}, False)
            self.assertEqual(int(cancelled), warning.call_count)
            self.assertEqual(int(not cancelled), success.call_count)
            self.assertEqual(0 if cancelled else 100, panel.progress_bar.__setitem__.call_args.args[1])
            panel.winfo_toplevel().event_generate.assert_called_once_with(
                "<<LibraryChanged>>", when="tail"
            )


if __name__ == "__main__":
    unittest.main()

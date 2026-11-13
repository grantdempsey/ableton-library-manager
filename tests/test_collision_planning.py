import errno
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import ableton_tags
import sorter_engine
from tab_import import ImportTab
from tab_organize import OrganizeTab


class ImmediateWindow:
    def after(self, _delay, callback):
        callback()


class CollisionPlanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.incoming = self.root / "incoming"
        self.library = self.root / "library"
        self.incoming.mkdir()
        self.target = self.library / "Samples" / "One-Shots" / "Kicks"
        for name, value in (
            ("CONFIG_FILE", str(self.root / "config.json")),
            ("ASSET_INDEX_FILE", str(self.root / "assets.db")),
            ("MOVE_LOG_DIR", str(self.root / "logs")),
            ("CONFIG_BACKUP_DIR", str(self.root / "backups")),
            ("DRUM_KEYWORDS", {r"\bkick\b": "Kicks"}),
            ("RULE_METADATA", {}),
            ("SMART_LEARNING_ENABLED", False),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sample(self, relative, contents):
        path = self.incoming / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def worker(self, *, preview=False, copy_mode=False):
        return sorter_engine.ParallelLibrarySorter(
            str(self.incoming), str(self.library), ImmediateWindow(), lambda _: None,
            lambda *_: None, preview_only=preview, copy_mode=copy_mode,
            smart_learning_enabled=False,
        )

    def run_worker(self, *, timeout=10, **kwargs):
        worker = self.worker(**kwargs)
        worker.start_parallel_sort()
        worker.worker_thread.join(timeout)
        finished = not worker.is_running()
        if not finished:
            worker.cancel()
            worker.worker_thread.join(10)
        self.assertTrue(finished, f"sorter did not finish within {timeout}s")
        return worker

    def test_preview_and_move_reserve_exact_names_in_stable_source_order(self):
        sources = {
            self.sample("z/kick.wav", b"third"): "kick_2.wav",
            self.sample("a/kick.wav", b"first"): "kick.wav",
            self.sample("m/kick.wav", b"second"): "kick_1.wav",
        }
        for _ in range(2):
            preview = self.run_worker(preview=True)
            self.assertEqual([], preview.operation_errors)
            self.assertEqual(
                {str(source): str(self.target / name) for source, name in sources.items()},
                {record["source"]: record["destination_path"] for record in preview.preview_records},
            )
            self.assertEqual(["none", "rename", "rename"],
                             [record["collision"] for record in preview.preview_records])
        self.assertFalse(self.library.exists())
        moved = self.run_worker()
        self.assertEqual([], moved.operation_errors)
        for source, name in sources.items():
            self.assertFalse(source.exists())
            self.assertTrue((self.target / name).is_file())
        self.assertEqual(b"first", (self.target / "kick.wav").read_bytes())
        self.assertEqual(b"second", (self.target / "kick_1.wav").read_bytes())
        self.assertEqual(b"third", (self.target / "kick_2.wav").read_bytes())
        result = sorter_engine.undo_move_log(moved.move_log_path)
        self.assertEqual({"restored": 3, "skipped": 0, "errors": []}, result)
        self.assertTrue(all(source.exists() for source in sources))

    def test_identical_planned_files_merge_tags_and_undo_both_sources(self):
        first = self.sample("a/kick.wav", b"same")
        second = self.sample("b/kick.wav", b"same")
        ableton_tags.prepare_edit([str(first)], "Character|Warm").commit()
        ableton_tags.prepare_edit([str(second)], "Drums|Kick").commit()
        preview = self.run_worker(preview=True)
        self.assertEqual(["move", "duplicate"], [r["action"] for r in preview.preview_records])
        self.assertEqual(1, preview.stats["Skipped Duplicate Items"])
        self.assertEqual({str(self.target / "kick.wav")},
                         {r["destination_path"] for r in preview.preview_records})
        moved = self.run_worker()
        self.assertEqual([], moved.operation_errors)
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())
        self.assertEqual(["Character|Warm", "Drums|Kick"],
                         ableton_tags.sample_tags(str(self.target / "kick.wav")))
        result = sorter_engine.undo_move_log(moved.move_log_path)
        self.assertEqual({"restored": 2, "skipped": 0, "errors": []}, result)
        self.assertEqual(["Character|Warm"], ableton_tags.sample_tags(str(first)))
        self.assertEqual(["Drums|Kick"], ableton_tags.sample_tags(str(second)))

    def test_existing_files_folders_and_suffix_duplicates_have_exact_plan(self):
        self.target.mkdir(parents=True)
        (self.target / "kick.wav").mkdir()
        (self.target / "kick_1.wav").write_bytes(b"other")
        (self.target / "kick_2.wav").write_bytes(b"same")
        source = self.sample("kick.wav", b"same")
        preview = self.run_worker(preview=True, copy_mode=True)
        record = preview.preview_records[0]
        self.assertEqual("duplicate", record["action"])
        self.assertEqual(str(self.target / "kick_2.wav"), record["destination_path"])
        copied = self.run_worker(copy_mode=True)
        self.assertEqual([], copied.operation_errors)
        self.assertEqual(1, copied.stats["Skipped Duplicate Items"])
        self.assertTrue(source.exists())
        self.assertFalse((self.target / "kick_3.wav").exists())

    def test_crc_collision_never_deletes_different_source_audio(self):
        source = self.sample("kick.wav", b"different")
        self.target.mkdir(parents=True)
        destination = self.target / "kick.wav"
        destination.write_bytes(b"original")
        with mock.patch.object(sorter_engine, "calculate_crc32", return_value="same-crc"):
            moved = self.run_worker()
        self.assertEqual([], moved.operation_errors)
        self.assertEqual(0, moved.stats["Skipped Duplicate Items"])
        self.assertEqual(b"original", destination.read_bytes())
        self.assertEqual(b"different", (self.target / "kick_1.wav").read_bytes())
        self.assertFalse(source.exists())

    def test_literal_suffix_names_cannot_share_a_reserved_destination(self):
        for name, contents in (
            ("a/kick.wav", b"one"), ("b/kick.wav", b"two"), ("c/kick_1.wav", b"three"),
        ):
            self.sample(name, contents)
        preview = self.run_worker(preview=True)
        destinations = [r["destination_path"] for r in preview.preview_records]
        self.assertEqual(3, len(set(destinations)))
        moved = self.run_worker()
        self.assertEqual([], moved.operation_errors)
        self.assertEqual({b"one", b"two", b"three"},
                         {path.read_bytes() for path in self.target.glob("*.wav")})

    def test_planned_parent_folders_are_reserved_against_new_files(self):
        source = self.sample("a/kick.wav", b"audio")
        preset = self.sample("b/lead.fxp", b"preset")
        with mock.patch.object(sorter_engine, "DRUM_KEYWORDS", {
            r"\bkick\b": "Samples/One-Shots/Kicks/lead.fxp",
        }), mock.patch.object(sorter_engine, "SYNTH_EXTS", {
            ".fxp": "Samples/One-Shots/Kicks",
        }):
            preview = self.run_worker(preview=True)
            self.assertEqual([], preview.operation_errors)
            records = {r["source"]: r for r in preview.preview_records}
            self.assertEqual(str(self.target / "lead_1.fxp"), records[str(preset)]["destination_path"])
            worker = self.run_worker()
        self.assertEqual([], worker.operation_errors)
        self.assertEqual(b"audio", (self.target / "lead.fxp" / "kick.wav").read_bytes())
        self.assertEqual(b"preset", (self.target / "lead_1.fxp").read_bytes())
        self.assertFalse(source.exists())

    def test_existing_hard_link_is_reported_as_conflict_before_transfer(self):
        source = self.sample("kick.wav", b"source")
        self.target.mkdir(parents=True)
        destination = self.target / "kick.wav"
        try:
            os.link(source, destination)
        except OSError as error:
            self.skipTest(f"Hard links unavailable: {error}")
        preview = self.run_worker(preview=True)
        self.assertEqual([], preview.preview_records)
        self.assertEqual(1, len(preview.operation_errors))
        self.assertIn("same file", preview.operation_errors[0]["error"])
        self.assertTrue(source.exists())
        self.assertEqual(b"source", destination.read_bytes())

    def test_failed_provider_cannot_turn_dependent_duplicate_into_a_move(self):
        first = self.sample("a/kick.wav", b"same")
        second = self.sample("b/kick.wav", b"same")
        transfer = ableton_tags.transfer_sample
        def fail_first(source, destination, **kwargs):
            if source == str(first):
                raise OSError("fixture: provider failed")
            return transfer(source, destination, **kwargs)
        with mock.patch.object(ableton_tags, "transfer_sample", side_effect=fail_first):
            worker = self.run_worker()
        self.assertEqual(2, len(worker.operation_errors))
        self.assertTrue(first.exists())
        self.assertTrue(second.exists())
        self.assertFalse((self.target / "kick.wav").exists())
        self.assertEqual(0, worker.stats["Skipped Duplicate Items"])

    def test_changed_source_between_planning_and_execution_is_left_untouched(self):
        self.library.mkdir()
        source = self.sample("kick.wav", b"original")
        worker = self.worker()
        execute = worker._execute_record
        def changed(record):
            source.write_bytes(b"external edit")
            return execute(record)
        with mock.patch.object(worker, "_execute_record", side_effect=changed):
            worker.start_parallel_sort()
            worker.worker_thread.join(10)
        self.assertEqual(1, len(worker.operation_errors))
        self.assertIn("changed", worker.operation_errors[0]["error"].lower())
        self.assertEqual(b"external edit", source.read_bytes())
        self.assertFalse((self.target / "kick.wav").exists())

    def test_new_destination_after_planning_is_not_overwritten_or_renamed(self):
        source = self.sample("kick.wav", b"source")
        worker = self.worker()
        execute = worker._execute_record
        def occupied(record):
            self.target.mkdir(parents=True, exist_ok=True)
            (self.target / "kick.wav").write_bytes(b"external")
            return execute(record)
        with mock.patch.object(worker, "_execute_record", side_effect=occupied):
            worker.start_parallel_sort()
            worker.worker_thread.join(10)
        self.assertEqual(1, len(worker.operation_errors))
        self.assertEqual(b"source", source.read_bytes())
        self.assertEqual(b"external", (self.target / "kick.wav").read_bytes())
        self.assertFalse((self.target / "kick_1.wav").exists())
        self.assertIsNone(worker.move_log_path)

    def test_copy_preview_uses_copy_action_and_keeps_source_after_execution(self):
        source = self.sample("kick.wav", b"source")
        preview = self.run_worker(preview=True, copy_mode=True)
        self.assertEqual("copy", preview.preview_records[0]["action"])
        worker = self.run_worker(copy_mode=True)
        self.assertEqual([], worker.operation_errors)
        self.assertTrue(source.exists())
        self.assertEqual(b"source", (self.target / "kick.wav").read_bytes())

    def test_many_different_same_name_files_keep_exact_preview_names(self):
        contents = {}
        for index in reversed(range(40)):
            path = self.sample(f"{index:03d}/kick.wav", f"audio-{index}".encode("ascii"))
            contents[str(path)] = path.read_bytes()
        preview = self.run_worker(preview=True, copy_mode=True)
        planned = {r["source"]: r["destination_path"] for r in preview.preview_records}
        self.assertEqual(40, len(set(planned.values())))
        copied = self.run_worker(copy_mode=True, timeout=30)
        self.assertEqual([], copied.operation_errors)
        self.assertEqual(40, copied.stats["One-Shots Grouped by Drum Type"])
        for source, destination in planned.items():
            self.assertEqual(contents[source], Path(destination).read_bytes())
            self.assertTrue(Path(source).exists())

    def test_rule_changes_during_planning_abort_before_any_transfer(self):
        sources = [self.sample(f"{letter}/kick.wav", b"sample") for letter in ("a", "b")]
        worker = self.worker()
        plan = worker.process_single_file
        def changed(root, filename):
            plan(root, filename)
            sorter_engine.DRUM_KEYWORDS = {r"\bkick\b": "Changed Folder"}
        with mock.patch.object(worker, "process_single_file", side_effect=changed):
            worker.start_parallel_sort()
            worker.worker_thread.join(10)
        self.assertEqual(1, len(worker.operation_errors))
        self.assertIn("settings changed", worker.operation_errors[0]["error"])
        self.assertTrue(all(source.exists() for source in sources))
        self.assertFalse(self.library.exists())

    def test_duplicate_transfer_rechecks_content_even_if_caller_is_wrong(self):
        first = self.sample("a.wav", b"one")
        second = self.sample("b.wav", b"two")
        with self.assertRaisesRegex(ValueError, "identical"):
            ableton_tags.transfer_sample(str(first), str(second), duplicate=True)
        self.assertEqual(b"one", first.read_bytes())
        self.assertEqual(b"two", second.read_bytes())

    def test_file_blocking_destination_folder_is_a_preview_error(self):
        source = self.sample("kick.wav", b"source")
        self.library.mkdir()
        (self.library / "Samples").write_bytes(b"not a folder")
        preview = self.run_worker(preview=True)
        self.assertEqual([], preview.preview_records)
        self.assertEqual(1, len(preview.operation_errors))
        self.assertIn("blocks", preview.operation_errors[0]["error"])
        self.assertEqual(b"source", source.read_bytes())

    def test_move_never_overwrites_a_file_created_during_transfer(self):
        source = self.sample("kick.wav", b"source")
        destination = self.root / "other.wav"
        publish = ableton_tags._publish_sample
        def create_then_publish(first, second):
            Path(second).write_bytes(b"external")
            return publish(first, second)
        with mock.patch.object(ableton_tags, "_publish_sample", side_effect=create_then_publish):
            with self.assertRaises(OSError):
                ableton_tags.transfer_sample(str(source), str(destination))
        self.assertEqual(b"source", source.read_bytes())
        self.assertEqual(b"external", destination.read_bytes())

    def test_cross_volume_move_copy_does_not_overwrite_new_destination(self):
        source = self.sample("kick.wav", b"source")
        destination = self.root / "other.wav"
        copy_sample = ableton_tags._copy_sample
        def create_then_copy(first, second):
            self.assertNotEqual(destination, Path(second))
            destination.write_bytes(b"external")
            return copy_sample(first, second)
        with mock.patch.object(ableton_tags, "_copy_sample", side_effect=create_then_copy):
            with self.assertRaises(OSError):
                ableton_tags.transfer_sample(str(source), str(destination))
        self.assertEqual(b"source", source.read_bytes())
        self.assertEqual(b"external", destination.read_bytes())

    def test_move_rollback_cannot_overwrite_a_recreated_original_path(self):
        source = self.sample("kick.wav", b"source")
        destination = self.root / "other.wav"
        def fail_metadata():
            source.write_bytes(b"external replacement")
            raise OSError("fixture: metadata failure")
        with mock.patch.object(ableton_tags.TagEdit, "commit", side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError, "audio rollback failed"):
                ableton_tags.transfer_sample(str(source), str(destination))
        self.assertEqual(b"external replacement", source.read_bytes())
        self.assertEqual(b"source", destination.read_bytes())

    def test_duplicate_rollback_cannot_overwrite_a_recreated_original_path(self):
        source = self.sample("kick.wav", b"source")
        destination = self.root / "other.wav"
        destination.write_bytes(b"source")
        def fail_metadata():
            source.write_bytes(b"external replacement")
            raise OSError("fixture: metadata failure")
        with mock.patch.object(ableton_tags.TagEdit, "commit", side_effect=fail_metadata):
            with self.assertRaisesRegex(OSError, "audio rollback failed"):
                ableton_tags.transfer_sample(str(source), str(destination), duplicate=True)
        self.assertEqual(b"external replacement", source.read_bytes())
        self.assertEqual(b"source", destination.read_bytes())

    def test_posix_no_replace_move_and_cross_volume_fallback(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback):
                source = self.sample(f"{fallback}/kick.wav", b"source")
                destination = self.root / f"other-{fallback}.wav"
                link = os.link
                with mock.patch.object(ableton_tags.os, "name", "posix"), mock.patch.object(
                    ableton_tags.os, "link",
                    side_effect=OSError(errno.EXDEV, "cross-device") if fallback else link,
                ):
                    ableton_tags._move_sample(str(source), str(destination))
                self.assertFalse(source.exists())
                self.assertEqual(b"source", destination.read_bytes())

    def test_changed_duplicate_destination_does_not_consume_original(self):
        source = self.sample("kick.wav", b"same")
        self.target.mkdir(parents=True)
        destination = self.target / "kick.wav"
        destination.write_bytes(b"same")
        worker = self.worker()
        execute = worker._execute_record
        def changed(record):
            destination.write_bytes(b"external edit")
            return execute(record)
        with mock.patch.object(worker, "_execute_record", side_effect=changed):
            worker.start_parallel_sort()
            worker.worker_thread.join(10)
        self.assertEqual(1, len(worker.operation_errors))
        self.assertIn("changed", worker.operation_errors[0]["error"])
        self.assertTrue(source.exists())
        self.assertEqual(b"external edit", destination.read_bytes())
        self.assertIsNone(worker.move_log_path)

    def test_multiple_planned_duplicates_merge_in_order_and_undo_every_source(self):
        sources = [self.sample(f"{letter}/kick.wav", b"same") for letter in ("c", "a", "b")]
        for index, source in enumerate(sources):
            ableton_tags.prepare_edit([str(source)], f"Character|Fixture{index}").commit()
        worker = self.run_worker()
        self.assertEqual([], worker.operation_errors)
        self.assertEqual(2, worker.stats["Skipped Duplicate Items"])
        self.assertEqual(3, len(ableton_tags.sample_tags(str(self.target / "kick.wav"))))
        self.assertTrue(all(not source.exists() for source in sources))
        result = sorter_engine.undo_move_log(worker.move_log_path)
        self.assertEqual({"restored": 3, "skipped": 0, "errors": []}, result)
        for index, source in enumerate(sources):
            self.assertEqual(["Character|Fixture" + str(index)], ableton_tags.sample_tags(str(source)))

    def test_import_preview_logs_full_destination_and_duplicate_decision(self):
        panel = mock.MagicMock()
        panel.active_sorter.preview_only = True
        panel.active_sorter.operation_errors = []
        panel.active_sorter.cancel_event.is_set.return_value = False
        panel.active_sorter.preview_records = [{
            "filename": "kick.wav", "source": "incoming/kick.wav",
            "destination": "library/Kicks", "destination_path": "library/Kicks/kick_1.wav",
            "action": "duplicate", "collision": "identical",
            "reason": "filename_rule", "confidence": 0.95, "tags": [],
        }]
        with mock.patch("tab_import.tab_matrix.rescan_suggestions"), mock.patch(
            "tab_import.messagebox.showinfo"
        ):
            ImportTab.handle_pipeline_completion(panel, {}, True)
        messages = "\n".join(call.args[0] for call in panel.write_console_message.call_args_list)
        self.assertIn("library/Kicks/kick_1.wav", messages)
        self.assertIn("duplicate", messages.lower())

    def test_organize_preview_exposes_rename_and_duplicate_counts(self):
        panel = mock.MagicMock()
        panel.winfo_toplevel.return_value = SimpleNamespace(_closing=False)
        settings = (str(self.library), False)
        panel._settings_snapshot.return_value = settings
        panel._preview_settings = settings
        panel.preview_sorter.operation_errors = []
        panel.preview_sorter.cancel_event.is_set.return_value = False
        panel.preview_sorter.reviewed_plan = {"kind": "ordinary"}
        panel.btn_cancel = mock.Mock()
        panel.btn_preview = mock.Mock()
        panel.btn_undo = mock.Mock()
        panel.btn_execute = mock.Mock()
        panel.btn_export_plan = mock.Mock()
        panel.progress_bar = mock.MagicMock()
        panel.progress_text_var = mock.Mock()
        panel.library_dir_var.get.return_value = str(self.library)
        panel.preview_sorter.preview_records = [
            {"source": str(self.incoming / "kick.wav"), "filename": "kick.wav",
             "destination": str(self.target), "destination_path": str(self.target / "kick_1.wav"),
             "action": "move", "collision": "rename"},
            {"source": str(self.incoming / "second/kick.wav"), "filename": "kick.wav",
             "destination": str(self.target), "destination_path": str(self.target / "kick_1.wav"),
             "action": "duplicate", "collision": "identical"},
        ]
        with mock.patch("tab_organize.themed_dialog", return_value=False) as dialog:
            OrganizeTab.show_preview_results(panel, {}, False)
        message = dialog.call_args.args[2].lower()
        self.assertIn("1", message)
        self.assertIn("duplicate", message)
        self.assertIn("rename", message)
        messages = "\n".join(call.args[0] for call in panel.write_console_message.call_args_list)
        self.assertIn(str(self.target / "kick_1.wav"), messages)


if __name__ == "__main__":
    unittest.main()

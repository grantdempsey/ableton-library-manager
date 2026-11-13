import copy
import json
import sqlite3
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import ableton_tags
import library_jobs
import sorter_engine


class ReviewedPlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.incoming = self.root / "incoming"
        self.incoming.mkdir()
        self.library = self.root / "library"
        self.profile = self.root / "profile"
        self.profile.mkdir()
        for name, value in (
            ("CONFIG_FILE", str(self.profile / "config.json")),
            ("ASSET_INDEX_FILE", str(self.profile / "assets.db")),
            ("MOVE_LOG_DIR", str(self.profile / "moves")),
            ("CONFIG_LOAD_ERROR", None), ("XO_CONFIG_LOAD_ERROR", None),
            ("DRUM_KEYWORDS", {r"\bkick\b": "Kicks"}),
            ("SYNTH_EXTS", {".fxp": "Presets"}),
            ("NATIVE_EXTS", {".adg": "Instrument Racks"}),
            ("RULE_METADATA", {}), ("IGNORED_DIRECTORIES", ["protected"]),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        jobs = mock.patch.object(library_jobs, "coordinator", library_jobs.LibraryJobCoordinator(self.root / "lock"))
        jobs.start()
        self.addCleanup(jobs.stop)
        sorter_engine._write_config(sorter_engine._default_config(), create_backup=False)

    def run_worker(self, *, preview=True, approved=None, copy_mode=True):
        done = threading.Event()
        worker = sorter_engine.ParallelLibrarySorter(
            str(self.incoming), str(self.library),
            SimpleNamespace(after=lambda _delay, callback: callback()),
            lambda _: None, lambda *_: done.set(), preview_only=preview,
            copy_mode=copy_mode, smart_learning_enabled=False,
            supported_only=True, approved_plan=approved,
        )
        worker.start_parallel_sort()
        self.assertTrue(done.wait(30))
        if worker.worker_thread:
            worker.worker_thread.join()
        return worker

    def snapshot(self, root):
        return {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
                for path in root.rglob("*") if path.is_file()
                and "performance_logs" not in path.parts}

    def test_preview_leaves_existing_index_profile_and_source_bytes_unchanged(self):
        sample = self.incoming / "kick.wav"
        sample.write_bytes(b"audio")
        ableton_tags.prepare_edit([str(sample)], "Drums|Kick").commit()
        sorter_engine.index_asset(str(sample), str(self.incoming), "fixture", 1, ["favorite"])
        before = self.snapshot(self.root)
        preview = self.run_worker()
        self.assertEqual([], preview.operation_errors)
        self.assertIsNotNone(preview.reviewed_plan)
        after = self.snapshot(self.root)
        after.pop(str(self.root / "lock"), None)
        self.assertEqual(before, after)
        self.assertFalse(self.library.exists())

    def test_preview_does_not_create_missing_index(self):
        (self.incoming / "kick.wav").write_bytes(b"audio")
        preview = self.run_worker()
        self.assertEqual([], preview.operation_errors)
        self.assertFalse(Path(sorter_engine.ASSET_INDEX_FILE).exists())

    def test_successful_import_measures_planning_validation_and_transfer_separately(self):
        (self.incoming / "kick.wav").write_bytes(b"audio")
        worker = self.run_worker(preview=False)
        self.assertEqual([], worker.operation_errors)
        records = [
            json.loads(line)
            for path in sorter_engine.performance_log.log_directory().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        metrics = next(record for record in records if record["operation"] == "import")
        for name in ("planning_seconds", "approval_validation_seconds", "transfer_seconds"):
            self.assertIsInstance(metrics[name], float)
            self.assertGreaterEqual(metrics[name], 0)

    def test_destination_tag_changes_invalidate_approval_before_any_transfer(self):
        source = self.incoming / "kick.wav"
        source.write_bytes(b"audio")
        target = self.library / "Samples" / "One-Shots" / "Kicks" / "kick.wav"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"audio")
        ableton_tags.prepare_edit([str(target)], "Character|Old").commit()
        preview = self.run_worker(copy_mode=False)
        ableton_tags.prepare_edit([str(target)], "Character|New").commit()
        before = self.snapshot(self.library)
        executed = self.run_worker(preview=False, copy_mode=False, approved=preview.reviewed_plan)
        self.assertTrue(executed.operation_errors)
        self.assertEqual(set(), executed._completed_plan_sources)
        self.assertEqual(b"audio", source.read_bytes())
        self.assertEqual(before, self.snapshot(self.library))

    def test_unreadable_routing_index_rejects_preview_without_writes(self):
        (self.incoming / "kick.wav").write_bytes(b"audio")
        index = Path(sorter_engine.ASSET_INDEX_FILE)
        with sqlite3.connect(index) as connection:
            connection.execute("CREATE TABLE invalid_schema(value TEXT)")
        connection.close()
        before = index.read_bytes()
        preview = self.run_worker()
        self.assertTrue(preview.operation_errors)
        self.assertIsNone(preview.reviewed_plan)
        self.assertEqual(before, index.read_bytes())
        self.assertFalse(self.library.exists())

    def test_preview_preserves_closed_wal_index_without_creating_bookkeeping(self):
        (self.incoming / "kick.wav").write_bytes(b"audio")
        sorter_engine.index_asset(
            str(self.incoming / "kick.wav"), str(self.incoming), "fixture", 1, ["favorite"],
        )
        with sqlite3.connect(sorter_engine.ASSET_INDEX_FILE) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
        connection.close()
        before = self.snapshot(self.profile)
        preview = self.run_worker()
        self.assertEqual([], preview.operation_errors)
        self.assertEqual(before, self.snapshot(self.profile))

    def test_preview_reads_committed_live_wal_tags_without_mutating_original(self):
        sample = self.incoming / "kick.wav"
        sample.write_bytes(b"audio")
        sorter_engine.index_asset(str(sample), str(self.incoming), "fixture", 1, [])
        connection = sqlite3.connect(sorter_engine.ASSET_INDEX_FILE)
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "INSERT INTO asset_tags(asset_path,tag,enabled,source) VALUES (?,?,1,'personal')",
            (str(sample), "favorite"),
        )
        connection.commit()
        before = self.snapshot(self.profile)
        preview = self.run_worker()
        self.assertEqual([], preview.operation_errors)
        self.assertEqual(before, self.snapshot(self.profile))
        self.assertIn("favorite", preview.operation_plan[0]["tags"])

    def test_audio_plus_presets_uses_explicit_allowlist_not_unknown_filename_matches(self):
        for name in ("kick.wav", "kick.fxp", "kick.mdDrumset", "kick.mid", "kick.txt"):
            (self.incoming / name).write_bytes(name.encode())
        with mock.patch.dict(sorter_engine.SYNTH_EXTS, {".txt": "Presets"}, clear=False):
            preview = self.run_worker()
        self.assertEqual([], preview.operation_errors)
        self.assertEqual(
            {".wav", ".fxp"}, {Path(row["source"]).suffix for row in preview.operation_plan},
        )

    def test_complete_export_includes_all_records_and_skips_not_first_hundred(self):
        for index in range(105):
            (self.incoming / f"kick-{index}.wav").write_bytes(str(index).encode())
        (self.incoming / "kick.mdDrumset").write_bytes(b"resource")
        protected = self.incoming / "protected"
        protected.mkdir()
        (protected / "kick.wav").write_bytes(b"protected")
        preview = self.run_worker()
        report = self.root / "plan.json"
        preview.export_plan(report)
        plan = json.loads(report.read_text())
        self.assertEqual(105, len(plan["records"]))
        self.assertEqual({"file_type_excluded", "skip_folder"}, {row["reason"] for row in plan["skipped"]})
        self.assertFalse((self.library / "kick.mdDrumset").exists())
        with self.assertRaises(FileExistsError):
            preview.export_plan(report)
        with self.assertRaisesRegex(ValueError, "outside"):
            preview.export_plan(self.incoming / "plan.json")

    def test_approved_move_uses_preview_destinations_and_can_be_undone(self):
        sample = self.incoming / "kick.wav"
        sample.write_bytes(b"audio")
        preview = self.run_worker(copy_mode=False)
        worker = self.run_worker(preview=False, copy_mode=False, approved=preview.reviewed_plan)
        self.assertEqual([], worker.operation_errors)
        self.assertFalse(sample.exists())
        self.assertTrue(Path(preview.operation_plan[0]["destination_path"]).exists())
        self.assertEqual(1, sorter_engine.undo_move_log(worker.move_log_path)["restored"])
        self.assertTrue(sample.exists())

    def test_stale_changes_abort_every_transfer_not_just_changed_file(self):
        for change in ("bytes", "new_file", "destination", "settings", "sidecar", "index_tags", "mode"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as scratch:
                original_source, original_library = self.incoming, self.library
                self.incoming = Path(scratch) / "incoming"
                self.library = Path(scratch) / "library"
                self.incoming.mkdir()
                first = self.incoming / "kick.wav"
                second = self.incoming / "kick2.wav"
                first.write_bytes(b"first")
                second.write_bytes(b"second")
                preview = self.run_worker()
                plan = copy.deepcopy(preview.reviewed_plan)
                if change == "bytes":
                    second.write_bytes(b"changed")
                elif change == "new_file":
                    (self.incoming / "snare.wav").write_bytes(b"new")
                elif change == "destination":
                    destination = Path(preview.operation_plan[0]["destination_path"])
                    destination.parent.mkdir(parents=True)
                    destination.write_bytes(b"existing")
                elif change == "settings":
                    with open(sorter_engine.CONFIG_FILE, "a") as handle:
                        handle.write(" ")
                elif change == "sidecar":
                    ableton_tags.prepare_edit([str(second)], "Drums|Snare").commit()
                elif change == "index_tags":
                    sorter_engine.index_asset(str(second), str(self.incoming), "fixture", 1, ["favorite"])
                elif change == "mode":
                    plan["audio_only"] = True
                worker = self.run_worker(preview=False, approved=plan)
                self.assertTrue(worker.operation_errors)
                self.assertEqual(set(), worker._completed_plan_sources)
                self.assertTrue(first.exists())
                self.incoming, self.library = original_source, original_library

    def test_inputs_changed_during_replanning_abort_every_transfer(self):
        first = self.incoming / "kick-a.wav"
        first.write_bytes(b"first")
        second = self.incoming / "kick-b.wav"
        second.write_bytes(b"second")
        original = sorter_engine.ParallelLibrarySorter.process_single_file
        for mutation in ("content", "inventory", "destination"):
            with self.subTest(mutation=mutation):
                preview = self.run_worker()
                target = Path(preview.operation_plan[0]["destination_path"])
                def changed(worker, root, filename):
                    original(worker, root, filename)
                    if filename == second.name:
                        if mutation == "content":
                            first.write_bytes(b"edited")
                        elif mutation == "inventory":
                            (self.incoming / "kick-new.wav").write_bytes(b"new")
                        else:
                            target.parent.mkdir(parents=True)
                            target.write_bytes(b"external")
                with mock.patch.object(
                    sorter_engine.ParallelLibrarySorter, "process_single_file", new=changed,
                ):
                    executed = self.run_worker(preview=False, approved=preview.reviewed_plan)
                self.assertTrue(executed.operation_errors)
                self.assertEqual([], list(self.library.rglob("kick-b.wav")))
                self.assertEqual(b"second", second.read_bytes())
                self.assertEqual(set(), executed._completed_plan_sources)
                if mutation == "content":
                    first.write_bytes(b"first")
                elif mutation == "inventory":
                    (self.incoming / "kick-new.wav").unlink()
                else:
                    target.unlink()

    def test_serum_preview_is_read_only_and_approved_resource_change_aborts_copy(self):
        source = self.incoming / "Serum 2 Presets"
        for name in ("Presets", "Tables", "Samples", "Curves", "LFO Shapes"):
            (source / name / "User").mkdir(parents=True)
        preset = source / "Presets" / "User" / "preset.fxp"
        preset.write_bytes(b"preset")
        table = source / "Tables" / "User" / "table.wav"
        table.write_bytes(b"table")
        def run(preview, approved=None):
            done = threading.Event()
            worker = sorter_engine.SerumResourceImporter(
                str(source), str(self.library),
                SimpleNamespace(after=lambda _delay, callback: callback()),
                lambda _: None, lambda *_: done.set(),
                preview_only=preview, approved_plan=approved,
            )
            worker.start_parallel_sort()
            self.assertTrue(done.wait(30))
            worker.worker_thread.join()
            return worker
        before = self.snapshot(source)
        preview = run(True)
        self.assertEqual([], preview.operation_errors)
        self.assertFalse(self.library.exists())
        self.assertEqual(before, self.snapshot(source))
        table.write_bytes(b"modified")
        executed = run(False, preview.reviewed_plan)
        self.assertTrue(executed.operation_errors)
        self.assertFalse(self.library.exists())
        self.assertEqual(b"preset", preset.read_bytes())
        preview = run(True)
        original = sorter_engine.SerumResourceImporter._resource_plan
        calls = 0
        def changed(worker):
            nonlocal calls
            result = original(worker)
            calls += 1
            if calls == 1:
                preset.write_bytes(b"changed during planning")
            return result
        with mock.patch.object(sorter_engine.SerumResourceImporter, "_resource_plan", new=changed):
            executed = run(False, preview.reviewed_plan)
        self.assertTrue(executed.operation_errors)
        self.assertFalse(self.library.exists())


if __name__ == "__main__":
    unittest.main()

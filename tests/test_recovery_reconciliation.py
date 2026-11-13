import json
import marshal
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import ableton_tags
import library_jobs
import library_state
import performance_log
import housekeeping
import serum_presets
import sorter_engine
import tag_evidence


class ImmediateWindow:
    def after(self, _delay, callback):
        callback()


class RecoveryReconciliationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.sequence = 0
        for name in ("ASSET_INDEX_FILE", "MOVE_LOG_DIR", "DRUM_KEYWORDS", "SMART_LEARNING_ENABLED"):
            patcher = mock.patch.object(sorter_engine, name, getattr(sorter_engine, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.fixture()

    def fixture(self):
        self.sequence += 1
        self.root = self.base / str(self.sequence)
        self.source = self.root / "incoming" / "kick.wav"
        self.library = self.root / "library"
        self.destination = self.library / "Samples" / "One-Shots" / "Kicks" / "kick.wav"
        self.source.parent.mkdir(parents=True)
        self.destination.parent.mkdir(parents=True)
        self.source.write_bytes(b"fixture-audio" * 100)
        ableton_tags.prepare_edit([str(self.source)], "Sounds|Source").commit()
        sorter_engine.ASSET_INDEX_FILE = str(self.root / "assets.db")
        sorter_engine.MOVE_LOG_DIR = str(self.root / "move_logs")
        sorter_engine.DRUM_KEYWORDS = {r"\bkick\b": "Kicks"}
        sorter_engine.SMART_LEARNING_ENABLED = False
        sorter_engine.index_asset(str(self.source), str(self.source.parent), "fixture", 1.0, ["favorite"])
        connection = sorter_engine._asset_index_connection()
        try:
            connection.execute(
                "INSERT INTO asset_tags VALUES (?, 'dormant-tag', 0, 'personal')", (str(self.source),)
            )
            connection.commit()
        finally:
            connection.close()

    def worker(self, *, copy=False):
        return sorter_engine.ParallelLibrarySorter(
            str(self.source.parent), str(self.library), ImmediateWindow(), lambda _: None,
            lambda *_: None, copy_mode=copy, smart_learning_enabled=False,
        )

    def logs(self):
        return list(Path(sorter_engine.MOVE_LOG_DIR).glob("*.jsonl"))

    def journals(self):
        return ableton_tags.find_transfer_recovery(str(self.root))

    def crash(self, phase, *, operation="move"):
        codes = {}
        for module in (
            ableton_tags, library_state, library_jobs, serum_presets, tag_evidence,
            housekeeping, performance_log, sorter_engine,
        ):
            codes[module.__name__] = module.__loader__.get_code(module.__name__)
        code_path = self.root / "production.bin"
        with code_path.open("wb") as handle:
            marshal.dump(codes, handle)
        script = r"""
import marshal, os, sys, types
root, phase, operation, code_path = sys.argv[1:]
with open(code_path, 'rb') as handle:
    codes = marshal.load(handle)
for name, code in codes.items():
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(code, module.__dict__)
import ableton_tags, sorter_engine
sorter_engine.ASSET_INDEX_FILE = os.path.join(root, 'assets.db')
sorter_engine.MOVE_LOG_DIR = os.path.join(root, 'move_logs')
sorter_engine.DRUM_KEYWORDS = {r'\bkick\b': 'Kicks'}
sorter_engine.SMART_LEARNING_ENABLED = False
def checkpoint(name):
    if name == phase:
        os._exit(79)
ableton_tags._transfer_checkpoint = checkpoint
if operation == 'recover':
    sorter_engine.recover_library_transfers(ableton_tags.find_transfer_recovery(root))
elif operation == 'undo':
    sorter_engine.undo_move_log(sorter_engine.latest_move_log())
else:
    class Window:
        def after(self, _delay, callback):
            callback()
    incoming = os.path.join(root, 'incoming')
    worker = sorter_engine.ParallelLibrarySorter(
        incoming, os.path.join(root, 'library'), Window(), lambda _: None,
        lambda *_: None, copy_mode=operation == 'copy', smart_learning_enabled=False)
    worker.process_single_file(incoming, 'kick.wav')
    if worker.operation_errors:
        raise RuntimeError(worker.operation_errors)
"""
        child = subprocess.run(
            [sys.executable, "-c", script, str(self.root), phase, operation, str(code_path)],
            cwd=self.root, capture_output=True, text=True, timeout=20,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(79, child.returncode, child.stderr)

    def recover(self):
        self.assertEqual({"recovered": 1, "errors": []},
                         sorter_engine.recover_library_transfers(self.journals()))
        self.assertEqual([], self.journals())

    def test_selected_undo_preserves_unselected_import_and_log_entries(self):
        second = self.source.with_name("kick second.wav")
        second.write_bytes(b"second audio")
        worker = self.worker()
        worker.process_single_file(str(self.source.parent), self.source.name)
        worker.process_single_file(str(second.parent), second.name)
        self.assertEqual([], worker.operation_errors)
        log = self.logs()[0]
        records = [json.loads(line) for line in log.read_text().splitlines()]
        selected = next(record for record in records if record["source"] == str(self.source))
        other = next(record for record in records if record["source"] == str(second))

        result = sorter_engine.undo_move_log(str(log), record_ids={selected["record_id"]})

        self.assertEqual({"restored": 1, "skipped": 0, "errors": []}, result)
        self.assertTrue(self.source.is_file())
        self.assertFalse(second.exists())
        self.assertTrue(Path(other["destination"]).is_file())
        remaining = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertTrue(next(r for r in remaining if r["source"] == str(self.source))["undo_complete"])
        self.assertEqual(other, next(r for r in remaining if r["source"] == str(second)))

    def test_startup_recovery_finds_and_reconciles_active_library_transfer(self):
        self.crash("committed")

        result = sorter_engine.recover_startup_transfers(str(self.library))

        self.assertEqual({"journals_found": 1, "recovered": 1, "errors": []}, result)
        self.assertEqual([], self.journals())
        self.assertIsNone(sorter_engine.get_indexed_asset(str(self.source)))
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.destination)))

    def test_startup_recovery_finds_interrupted_undo_outside_active_library(self):
        worker = self.worker()
        worker.process_single_file(str(self.source.parent), self.source.name)
        self.assertEqual([], worker.operation_errors)
        self.crash("committed", operation="undo")
        journal = self.journals()[0]
        self.assertFalse(Path(journal).is_relative_to(self.library))

        result = sorter_engine.recover_startup_transfers(str(self.library))

        self.assertEqual({"journals_found": 1, "recovered": 1, "errors": []}, result)
        self.assertEqual([], self.journals())
        self.assertTrue(self.source.is_file())
        self.assertFalse(self.destination.exists())
        self.assertEqual(0, sorter_engine.describe_move_log(str(self.logs()[0]))[0])

    def test_startup_recovery_retains_changed_transfer_and_reports_error(self):
        self.crash("committed")
        self.destination.write_bytes(b"externally changed")

        result = sorter_engine.recover_startup_transfers(str(self.library))

        self.assertEqual(1, result["journals_found"])
        self.assertEqual(0, result["recovered"])
        self.assertTrue(result["errors"])
        self.assertEqual(b"externally changed", self.destination.read_bytes())
        self.assertEqual(1, len(self.journals()))

    def test_move_process_exit_reconciles_every_application_boundary(self):
        for phase in ("prepared", "source_removed", "committed", "application_index_committed",
                      "application_undo_committed", "application_reconciled", "cleanup_stage_removed"):
            with self.subTest(phase=phase):
                self.fixture()
                self.crash(phase)
                self.recover()
                log = str(self.logs()[0])
                if phase in ("prepared", "source_removed"):
                    self.assertTrue(self.source.exists())
                    self.assertFalse(self.destination.exists())
                    self.assertIsNotNone(sorter_engine.get_indexed_asset(str(self.source)))
                    self.assertIsNone(sorter_engine.get_indexed_asset(str(self.destination)))
                    self.assertEqual(0, sorter_engine.describe_move_log(log)[0])
                else:
                    self.assertFalse(self.source.exists())
                    self.assertIsNone(sorter_engine.get_indexed_asset(str(self.source)))
                    asset = sorter_engine._snapshot_indexed_asset(str(self.destination))
                    self.assertIn("favorite", asset["tags"])
                    self.assertIn(("dormant-tag", 0, "personal"), asset["stored_tags"])
                    self.assertEqual(["Sounds|Source"], asset["ableton_tags"])
                    self.assertEqual(1, sorter_engine.describe_move_log(log)[0])
                    result = sorter_engine.undo_move_log(log)
                    self.assertEqual({"restored": 1, "skipped": 0, "errors": []}, result)
                    self.assertTrue(self.source.exists())

    def test_copy_reconciliation_keeps_both_paths_and_original_favorite(self):
        self.crash("committed", operation="copy")
        self.recover()
        self.assertTrue(self.source.exists())
        self.assertTrue(self.destination.exists())
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.source)))
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.destination)))
        self.assertEqual([], self.logs())

    def test_duplicate_reconciliation_preserves_merged_tags_and_undo(self):
        self.destination.write_bytes(self.source.read_bytes())
        ableton_tags.prepare_edit([str(self.destination)], "Character|Destination").commit()
        sorter_engine.index_asset(str(self.destination), str(self.destination.parent), "fixture", 1.0, [])
        self.crash("application_index_committed")
        self.recover()
        self.assertEqual(["Character|Destination", "Sounds|Source"],
                         sorter_engine.get_indexed_asset(str(self.destination))["ableton_tags"])
        self.assertEqual({"restored": 1, "skipped": 0, "errors": []},
                         sorter_engine.undo_move_log(str(self.logs()[0])))
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(str(self.source)))
        self.assertEqual(["Character|Destination"], ableton_tags.sample_tags(str(self.destination)))

    def test_ordinary_undo_interruption_reconciles_without_repeating_restoration(self):
        for phase in ("source_removed", "committed", "application_index_committed",
                      "application_undo_committed", "application_reconciled"):
            with self.subTest(phase=phase):
                self.fixture()
                worker = self.worker()
                worker.process_single_file(str(self.source.parent), self.source.name)
                self.assertEqual([], worker.operation_errors)
                self.crash(phase, operation="undo")
                self.recover()
                committed = phase != "source_removed"
                self.assertEqual(committed, self.source.exists())
                self.assertEqual(not committed, self.destination.exists())
                self.assertEqual(int(not committed), sorter_engine.describe_move_log(worker.move_log_path)[0])
                result = sorter_engine.undo_move_log(worker.move_log_path)
                self.assertEqual([], result["errors"])
                self.assertEqual(int(not committed), result["restored"])
                self.assertTrue(self.source.exists())

    def test_recovery_can_exit_after_index_or_log_and_be_retried(self):
        for phase in ("application_index_committed", "application_undo_committed"):
            with self.subTest(phase=phase):
                self.fixture()
                self.crash("committed")
                self.crash(phase, operation="recover")
                self.recover()
                self.assertEqual(1, sorter_engine.describe_move_log(str(self.logs()[0]))[0])

    def test_index_failure_retains_committed_audio_and_retryable_journal(self):
        worker = self.worker()
        with mock.patch.object(sorter_engine, "_cache_ableton_tags", side_effect=OSError("index fixture")):
            worker.process_single_file(str(self.source.parent), self.source.name)
        self.assertTrue(worker.operation_errors)
        self.assertFalse(self.source.exists())
        self.assertTrue(self.destination.exists())
        self.assertEqual(1, len(self.journals()))
        self.assertIsNotNone(sorter_engine.get_indexed_asset(str(self.source)))
        self.recover()
        self.assertIsNone(sorter_engine.get_indexed_asset(str(self.source)))
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.destination)))

    def test_undo_automatically_reconciles_pending_committed_transfer(self):
        self.crash("committed")
        result = sorter_engine.undo_move_log(str(self.logs()[0]))
        self.assertEqual({"restored": 1, "skipped": 0, "errors": []}, result)
        self.assertTrue(self.source.exists())
        self.assertEqual([], self.journals())

    def test_profile_or_undo_conflict_is_retained_before_audio_rollback(self):
        for conflict in ("profile", "record"):
            with self.subTest(conflict=conflict):
                self.fixture()
                self.crash("source_removed")
                if conflict == "profile":
                    sorter_engine.ASSET_INDEX_FILE = str(self.root / "different.db")
                else:
                    log = self.logs()[0]
                    record = json.loads(log.read_text())
                    record["destination"] = str(self.root / "different.wav")
                    log.write_text(json.dumps(record) + "\n")
                result = sorter_engine.recover_library_transfers(self.journals())
                self.assertEqual(0, result["recovered"])
                self.assertTrue(result["errors"])
                self.assertFalse(self.source.exists())
                self.assertTrue(self.destination.exists())
                self.assertEqual(1, len(self.journals()))

    def test_committed_move_does_not_delete_reappeared_source_index(self):
        self.crash("committed")
        self.source.write_bytes(b"new external file")
        result = sorter_engine.recover_library_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertIn("occupied again", result["errors"][0])
        self.assertEqual(b"new external file", self.source.read_bytes())
        self.assertIsNotNone(sorter_engine.get_indexed_asset(str(self.source)))

    def test_low_level_recovery_cannot_drop_application_intent(self):
        self.crash("committed")
        result = ableton_tags.recover_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertIn("through Organize", result["errors"][0])
        self.assertEqual(1, len(self.journals()))

    def test_completed_rollback_log_does_not_hide_older_undo_history(self):
        older = sorter_engine._new_move_log_path()
        sorter_engine._append_move_record(
            older, str(self.root / "old.wav"), str(self.root / "old-moved.wav"),
            destination_identity={"size": 1, "sha256": "fixture", "modified_ns": 0},
        )
        self.crash("prepared")
        cancelled = next(path for path in self.logs() if str(path) != older)
        os.utime(cancelled, None)
        self.recover()
        self.assertEqual(0, sorter_engine.describe_move_log(str(cancelled))[0])
        self.assertEqual(older, sorter_engine.latest_move_log())

    def test_undo_log_save_failure_keeps_journal_after_index_commit(self):
        worker = self.worker()
        worker.process_single_file(str(self.source.parent), self.source.name)
        self.assertEqual([], worker.operation_errors)
        self.crash("committed", operation="undo")
        with mock.patch.object(sorter_engine, "_save_move_records", side_effect=OSError("log fixture")):
            result = sorter_engine.recover_library_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertIn("log fixture", result["errors"][0])
        self.assertIsNotNone(sorter_engine.get_indexed_asset(str(self.source)))
        self.assertEqual(1, len(self.journals()))
        self.recover()
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.source)))

    def test_nested_repair_keeps_reconciliation_intent_after_index_failure(self):
        with mock.patch.object(sorter_engine, "_cache_ableton_tags", side_effect=OSError("index fixture")):
            result = sorter_engine.repair_nested_folder_files([{
                "source": str(self.source), "destination": str(self.destination),
            }])
        self.assertTrue(result["errors"])
        self.assertEqual(1, len(self.journals()))
        self.recover()
        self.assertIsNone(sorter_engine.get_indexed_asset(str(self.source)))
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.destination)))

    def test_duplicate_rollback_cancels_undo_without_changing_original_index(self):
        self.destination.write_bytes(self.source.read_bytes())
        ableton_tags.prepare_edit([str(self.destination)], "Character|Destination").commit()
        sorter_engine.index_asset(str(self.destination), str(self.destination.parent), "fixture", 1.0, [])
        self.crash("source_removed")
        self.recover()
        self.assertTrue(self.source.exists())
        self.assertTrue(self.destination.exists())
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(self.source)))
        self.assertNotIn("favorite", sorter_engine.get_asset_tags(str(self.destination)))
        self.assertEqual(["Character|Destination"], ableton_tags.sample_tags(str(self.destination)))
        self.assertEqual(0, sorter_engine.describe_move_log(str(self.logs()[0]))[0])

    def test_sqlite_failure_is_an_actionable_retained_recovery_error(self):
        self.crash("committed")
        with mock.patch.object(
            sorter_engine, "_asset_index_connection", side_effect=sorter_engine.sqlite3.OperationalError("locked fixture")
        ):
            result = sorter_engine.recover_library_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertIn("index reconciliation failed", result["errors"][0])
        self.assertEqual(1, len(self.journals()))
        self.recover()


if __name__ == "__main__":
    unittest.main()

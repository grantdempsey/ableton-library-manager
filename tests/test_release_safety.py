import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

import ableton_tags
import build_app
import rule_suggester
import sorter_engine
import tab_exclusions
import tag_evidence
from tab_import import ImportTab


class ReleaseSafetyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "profile.json"
        for name, value in (
            ("CONFIG_FILE", str(self.config)),
            ("ASSET_INDEX_FILE", str(self.root / "assets.db")),
            ("CONFIG_BACKUP_DIR", str(self.root / "backups")),
            ("MOVE_LOG_DIR", str(self.root / "logs")),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in (
            "BPM_RANGES", "DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS",
            "IGNORED_DIRECTORIES", "RULE_METADATA", "SMART_LEARNING_ENABLED",
            "LEARNING_COUNTS", "LEARNED_RULE_CANDIDATES", "LOOP_LAYOUT",
        ):
            original = getattr(sorter_engine, name)
            self.addCleanup(setattr, sorter_engine, name, original)
        self.config.write_text(json.dumps({"keep": "unchanged"}), encoding="utf-8")

    def test_interrupted_profile_write_preserves_original_and_cleans_temporary(self):
        before = self.config.read_bytes()
        def partial_write(data, handle, **kwargs):
            handle.write('{"partial":')
            raise OSError("disk full")
        with mock.patch.object(sorter_engine.json, "dump", side_effect=partial_write):
            with self.assertRaisesRegex(OSError, "disk full"):
                sorter_engine._write_config({"keep": "new"})
        self.assertEqual(before, self.config.read_bytes())
        self.assertEqual([], list(self.root.glob(".library-config-*.tmp")))

    def test_profile_conflict_does_not_replace_newer_content(self):
        before = self.config.read_bytes()
        self.config.write_text('{"keep":"external"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "profile changed"):
            sorter_engine._write_config({"keep": "mine"}, expected_content=before)
        self.assertEqual({"keep": "external"}, json.loads(self.config.read_text()))

    def test_exclusions_initialization_does_not_write_profile(self):
        before = self.config.read_bytes()
        page = SimpleNamespace(active_exclusions_set=set())
        tab_exclusions.ExclusionsTab.synchronize_backend_variables(page)
        self.assertEqual(before, self.config.read_bytes())
        self.assertIn("No Key Info", page.active_exclusions_set)

    def test_failed_exclusions_save_keeps_memory_and_reports_error(self):
        sorter_engine.IGNORED_DIRECTORIES = ["keep"]
        page = SimpleNamespace(active_exclusions_set={"new"})
        before = self.config.read_bytes()
        with mock.patch.object(sorter_engine.os, "replace", side_effect=OSError("locked")), mock.patch.object(
            tab_exclusions.messagebox, "showerror"
        ) as show_error:
            self.assertFalse(tab_exclusions.ExclusionsTab.flush_changes_to_backend_memory(page))
        self.assertEqual(["keep"], sorter_engine.IGNORED_DIRECTORIES)
        self.assertEqual({"keep", "No Key Info"}, page.active_exclusions_set)
        self.assertEqual(before, self.config.read_bytes())
        show_error.assert_called_once()

    def test_exclusions_save_preserves_other_settings(self):
        sorter_engine.save_ignored_directories(["Vendor"])
        data = json.loads(self.config.read_text())
        self.assertEqual("unchanged", data["keep"])
        self.assertEqual(["No Key Info", "Vendor"], data["IGNORED_DIRECTORIES"])
        self.assertEqual(data["IGNORED_DIRECTORIES"], sorter_engine.IGNORED_DIRECTORIES)

    def test_serialized_transactions_retain_independent_updates(self):
        barrier = threading.Barrier(2)
        errors = []
        @sorter_engine.serialized_config
        def update(key):
            data = json.loads(self.config.read_text())
            data[key] = True
            sorter_engine._write_config(data)
        def worker(key):
            try:
                barrier.wait(timeout=5)
                update(key)
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=worker, args=(key,)) for key in ("first", "second")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assertEqual({"keep": "unchanged", "first": True, "second": True}, json.loads(self.config.read_text()))

    def test_direct_edit_rejects_replaced_sample_before_writing_sidecars(self):
        sample = self.root / "sample.wav"
        sample.write_bytes(b"original")
        edit = ableton_tags.prepare_edit([str(sample)], "Drums|Kick")
        sample.write_bytes(b"replacement with different bytes")
        with self.assertRaisesRegex(ValueError, "sample changed"):
            edit.commit()
        self.assertEqual([], list(self.root.rglob("*.xmp")))

    def test_refresh_retires_absent_candidates_only_in_scope_and_can_revive(self):
        other_root = str(self.root / "other")
        candidate = {
            "token": "quasar", "target": "Snares", "count": 81,
            "pattern": sorter_engine.build_learned_rule_pattern("quasar"),
            "status": "pending", "evidence_source": "live_manual",
            "library_root": str(self.root), "min_files": 20, "min_share": 0.9,
        }
        unrelated = {**candidate, "token": "nebula", "library_root": other_root}
        data = {"LEARNED_RULE_CANDIDATES": [candidate, unrelated]}
        sorter_engine._write_config(data)
        rule_suggester.add_suggestions_as_candidates([], library_root=str(self.root))
        saved = json.loads(self.config.read_text())["LEARNED_RULE_CANDIDATES"]
        self.assertEqual(["stale", "pending"], [item["status"] for item in saved])
        self.assertFalse(sorter_engine.is_reviewable_learning_candidate(saved[0]))
        rule_suggester.add_suggestions_as_candidates([candidate], library_root=str(self.root))
        saved = json.loads(self.config.read_text())["LEARNED_RULE_CANDIDATES"]
        self.assertEqual(["pending", "pending"], [item["status"] for item in saved])

    def test_historical_counts_cannot_bypass_current_evidence_validation(self):
        candidate = {"token": "old", "count": 81}
        with self.assertRaisesRegex(ValueError, "historical observations"):
            rule_suggester.revalidate_candidates([candidate])

    def test_refresh_preserves_stricter_candidate_thresholds(self):
        suggestion = {
            "token": "quasar", "target": "Snares", "count": 20,
            "pattern": sorter_engine.build_learned_rule_pattern("quasar"),
            "library_root": str(self.root), "min_files": 20, "min_share": 0.9,
        }
        sorter_engine._write_config({"LEARNED_RULE_CANDIDATES": [{
            **suggestion, "status": "pending", "min_files": 50,
        }]})
        rule_suggester.add_suggestions_as_candidates([suggestion], library_root=str(self.root))
        saved = json.loads(self.config.read_text())["LEARNED_RULE_CANDIDATES"][0]
        self.assertEqual("stale", saved["status"])
        self.assertEqual(50, saved["min_files"])

    def test_unavailable_rule_scan_does_not_retire_saved_candidates(self):
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ValueError, "Library is unavailable"):
            rule_suggester.suggest_rules(str(self.root / "missing"))
        self.assertEqual(before, self.config.read_bytes())

    def test_home_counts_only_reviewable_candidates(self):
        sorter_engine.LEARNED_RULE_CANDIDATES = [
            {"count": 7, "status": "pending"},
            {"count": 20, "status": "pending"},
            {"count": 81, "status": "stale"},
        ]
        self.assertEqual(1, sorter_engine.library_status_summary()["suggestions"])

    def test_broad_bass_advice_is_neutral(self):
        evidence = tag_evidence.interpret_manual_tags(["Sounds|Bass"])
        self.assertEqual(("Samples", "One-Shots", "Bass"), tag_evidence.suggested_folder(evidence.sound_type))

    def test_move_regenerates_category_tags_and_duplicate_undo_preserves_both_files(self):
        self._assert_duplicate_undo_preserves_data()

    def test_historical_duplicate_snapshot_restores_dormant_enabled_and_disabled_rows(self):
        original = sorter_engine.ParallelLibrarySorter.log_move
        def historical_log(sorter, source, destination, **details):
            for name in ("source_index", "destination_index"):
                snapshot = details.get(name)
                if snapshot is not None:
                    rows = snapshot.pop("stored_tags")
                    snapshot["tags"] = [tag for tag, enabled, _source in rows if enabled]
                    snapshot["disabled_tags"] = [tag for tag, enabled, _source in rows if not enabled]
            return original(sorter, source, destination, **details)
        with mock.patch.object(sorter_engine.ParallelLibrarySorter, "log_move", historical_log):
            self._assert_duplicate_undo_preserves_data()

    def _assert_duplicate_undo_preserves_data(self):
        source_dir = self.root / "incoming"
        target_root = self.root / "library"
        target_dir = target_root / "Samples" / "One-Shots" / "Kicks"
        source_dir.mkdir()
        target_dir.mkdir(parents=True)
        source = source_dir / "heavy_kick.wav"
        destination = target_dir / source.name
        source.write_bytes(b"identical audio")
        destination.write_bytes(source.read_bytes())
        sorter_engine.DRUM_KEYWORDS = {r"\bkick\b": "Kicks"}
        sorter_engine.RULE_METADATA = {}
        sorter_engine.index_asset(str(source), str(source_dir), "test", 1, ["favorite", "category:Incoming"])
        sorter_engine.index_asset(str(destination), str(target_dir), "test", 1, [])
        connection = sorter_engine._asset_index_connection()
        with connection:
            connection.executemany(
                "INSERT INTO asset_tags VALUES (?, ?, ?, 'personal')",
                [(str(destination), "keep-destination", 1), (str(source), "disabled-legacy", 0)]
            )
        connection.close()
        ableton_tags.prepare_edit([str(source)], "Drums|Kick").commit()
        ableton_tags.prepare_edit([str(destination)], "Character|Warm").commit()
        window = SimpleNamespace(after=lambda _delay, callback: callback())
        sorter = sorter_engine.ParallelLibrarySorter(
            str(source_dir), str(target_root), window, lambda _text: None,
            lambda *_args: None, copy_mode=False,
        )
        sorter.process_single_file(str(source_dir), source.name)
        self.assertEqual([], sorter.operation_errors)
        self.assertFalse(source.exists())
        self.assertIsNotNone(sorter.move_log_path)
        tags = sorter_engine.get_asset_tags(str(destination))
        self.assertNotIn("category:Incoming", tags)
        self.assertIn("category:Kicks", tags)
        self.assertEqual(["Character|Warm", "Drums|Kick"], ableton_tags.sample_tags(str(destination)))
        sorter_engine.remove_asset_tag(str(destination), "favorite")
        refused = sorter_engine.undo_move_log(sorter.move_log_path)
        self.assertIn("app tags changed", refused["errors"][0])
        self.assertFalse(source.exists())
        sorter_engine.add_asset_tag(str(destination), "favorite")
        result = sorter_engine.undo_move_log(sorter.move_log_path)
        self.assertEqual([], result["errors"])
        self.assertEqual(1, result["restored"])
        self.assertEqual(b"identical audio", source.read_bytes())
        self.assertEqual(b"identical audio", destination.read_bytes())
        self.assertEqual(["Drums|Kick"], ableton_tags.sample_tags(str(source)))
        self.assertEqual(["Character|Warm"], ableton_tags.sample_tags(str(destination)))
        self.assertIn("favorite", sorter_engine.get_asset_tags(str(source)))
        self.assertNotIn("keep-destination", sorter_engine.get_asset_tags(str(destination)))
        connection = sorter_engine._asset_index_connection()
        try:
            self.assertEqual([(1,)], connection.execute(
                "SELECT enabled FROM asset_tags WHERE asset_path = ? AND tag = 'keep-destination'",
                (str(destination),)
            ).fetchall())
            self.assertEqual([(0,)], connection.execute(
                "SELECT enabled FROM asset_tags WHERE asset_path = ? AND tag = 'disabled-legacy'",
                (str(source),)
            ).fetchall())
        finally:
            connection.close()
        self.assertNotIn("favorite", sorter_engine.get_asset_tags(str(destination)))

    def test_duplicate_recovery_refuses_changed_destination(self):
        source = self.root / "source.wav"
        destination = self.root / "destination.wav"
        recovery = self.root / "recovery.audio"
        destination.write_bytes(b"changed")
        recovery.write_bytes(b"original")
        with self.assertRaisesRegex(ValueError, "audio changed"):
            ableton_tags.restore_duplicate(str(source), str(destination), str(recovery), [], [], [])
        self.assertFalse(source.exists())
        self.assertTrue(recovery.exists())

    def test_import_ui_preview_does_not_create_destination(self):
        destination = self.root / "not-created"
        panel = mock.MagicMock()
        panel.src_dir_var.get.return_value = str(self.root)
        panel.dest_dir_var.get.return_value = str(destination)
        panel.preview_only_var.get.return_value = True
        panel.copy_mode_var.get.return_value = True
        with mock.patch("tab_import.ParallelLibrarySorter") as sorter:
            ImportTab.kickoff_pipeline_sorting(panel)
        sorter.return_value.start_parallel_sort.assert_called_once()
        self.assertTrue(sorter.call_args.kwargs["preview_only"])
        self.assertFalse(destination.exists())

    def test_build_uses_new_output_without_killing_apps_or_removing_existing_data(self):
        used = self.root / "dist"
        used.mkdir()
        private = used / "profile.json"
        private.write_text("must not touch")
        with mock.patch.object(build_app, "__file__", str(self.root / "build_app.py")), mock.patch.object(
            build_app.subprocess, "run"
        ) as run:
            first = build_app.run_production_compiler_pipeline()
            second = build_app.run_production_compiler_pipeline()
        self.assertNotEqual(first, second)
        self.assertEqual("must not touch", private.read_text())
        self.assertEqual(2, run.call_count)
        command = run.call_args.args[0]
        self.assertNotIn("--noconfirm", command)
        self.assertEqual(str(second / "dist"), command[command.index("--distpath") + 1])


if __name__ == "__main__":
    unittest.main()

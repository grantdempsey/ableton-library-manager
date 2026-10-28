import json
import os
import tempfile
import unittest

import sorter_engine


class LearningFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_config_file = sorter_engine.CONFIG_FILE
        self.original_enabled = sorter_engine.SMART_LEARNING_ENABLED
        self.original_bpm_ranges = sorter_engine.BPM_RANGES
        self.original_drum_keywords = sorter_engine.DRUM_KEYWORDS
        self.original_rule_metadata = sorter_engine.RULE_METADATA
        self.original_asset_index_file = sorter_engine.ASSET_INDEX_FILE
        sorter_engine.CONFIG_FILE = os.path.join(self.temp_dir.name, "library_config.json")
        sorter_engine.ASSET_INDEX_FILE = os.path.join(self.temp_dir.name, "library_assets.db")
        sorter_engine.SMART_LEARNING_ENABLED = True
        sorter_engine.DRUM_KEYWORDS = {r"\bkick(s)?\b": "Kicks"}
        sorter_engine.RULE_METADATA = {}
        with open(sorter_engine.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump({}, config_file)

    def tearDown(self):
        sorter_engine.CONFIG_FILE = self.original_config_file
        sorter_engine.SMART_LEARNING_ENABLED = self.original_enabled
        sorter_engine.BPM_RANGES = self.original_bpm_ranges
        sorter_engine.DRUM_KEYWORDS = self.original_drum_keywords
        sorter_engine.RULE_METADATA = self.original_rule_metadata
        sorter_engine.ASSET_INDEX_FILE = self.original_asset_index_file
        self.temp_dir.cleanup()

    def test_generated_pattern_is_safe_and_matches_token_prefix(self):
        pattern = sorter_engine.build_learned_rule_pattern("rim.shot")

        self.assertRegex("rim.shot_v2", pattern)
        self.assertNotRegex("rimXshot_v2", pattern)

    def test_invalid_config_is_recovered_from_backup(self):
        valid_config = {
            "BPM_RANGES": [[0, 200, "All tempos"]],
            "DRUM_KEYWORDS": {r"\bkick\b": "Kicks"},
            "SYNTH_EXTS": {},
            "NATIVE_EXTS": {},
            "IGNORED_DIRECTORIES": [],
            "SMART_LEARNING_ENABLED": True,
            "LEARNING_COUNTS": {},
            "LEARNED_RULE_CANDIDATES": [],
            "RULE_METADATA": {}
        }
        with open(f"{sorter_engine.CONFIG_FILE}.bak", "w", encoding="utf-8") as backup:
            json.dump(valid_config, backup)
        with open(sorter_engine.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            config_file.write("{not valid json")

        loaded = sorter_engine.load_external_config()

        self.assertEqual("Kicks", loaded["DRUM_KEYWORDS"][r"\bkick\b"])
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as config_file:
            self.assertEqual(valid_config, json.load(config_file))

    def test_invalid_config_shape_is_rejected(self):
        with open(sorter_engine.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump({"DRUM_KEYWORDS": []}, config_file)

        with self.assertRaises(ValueError):
            sorter_engine.load_external_config()

    def test_config_writes_keep_a_valid_backup(self):
        original = {"DRUM_KEYWORDS": {}, "BPM_RANGES": []}
        sorter_engine._write_config(original)
        sorter_engine._write_config({"DRUM_KEYWORDS": {r"\bsnare\b": "Snares"}, "BPM_RANGES": []})

        with open(f"{sorter_engine.CONFIG_FILE}.bak", "r", encoding="utf-8") as backup:
            self.assertEqual(original, json.load(backup))

    def test_evidence_accumulates_and_creates_pending_candidate(self):
        evidence = [("rimshot", "Snares")] * 19
        self.assertEqual([], sorter_engine.record_learning_evidence(evidence))
        candidates = sorter_engine.record_learning_evidence([("rimshot", "Snares")])

        self.assertEqual(1, len(candidates))
        self.assertEqual("pending", candidates[0]["status"])
        self.assertEqual(20, candidates[0]["count"])

        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as config_file:
            saved = json.load(config_file)
        self.assertEqual(20, saved["LEARNING_COUNTS"]["rimshot|Snares"]["count"])
        self.assertEqual({}, saved.get("DRUM_KEYWORDS", {}))
        self.assertEqual(1, len(saved["LEARNED_RULE_CANDIDATES"]))

    def test_existing_pending_candidate_is_not_duplicated(self):
        evidence = [("rimshot", "Snares")] * 20
        self.assertEqual(1, len(sorter_engine.record_learning_evidence(evidence)))
        self.assertEqual([], sorter_engine.record_learning_evidence(evidence))

    def test_historical_pending_support_floor_and_accumulation(self):
        sorter_engine.record_learning_evidence([("rimshot", "Snares")] * 5, minimum_count=5)
        candidate = sorter_engine.LEARNED_RULE_CANDIDATES[0]
        self.assertFalse(sorter_engine.is_reviewable_learning_candidate(candidate))
        with open(sorter_engine.CONFIG_FILE, "rb") as handle:
            before = handle.read()
        with self.assertRaisesRegex(ValueError, "at least 20"):
            sorter_engine.review_learning_candidate("rimshot", "Snares", "approved")
        with open(sorter_engine.CONFIG_FILE, "rb") as handle:
            self.assertEqual(before, handle.read())
        sorter_engine.record_learning_evidence([("rimshot", "Snares")] * 14)
        self.assertEqual(19, sorter_engine.LEARNED_RULE_CANDIDATES[0]["count"])
        self.assertFalse(sorter_engine.is_reviewable_learning_candidate(sorter_engine.LEARNED_RULE_CANDIDATES[0]))
        sorter_engine.record_learning_evidence([("rimshot", "Snares")])
        self.assertEqual(1, len(sorter_engine.LEARNED_RULE_CANDIDATES))
        self.assertTrue(sorter_engine.is_reviewable_learning_candidate(sorter_engine.LEARNED_RULE_CANDIDATES[0]))
        with self.assertRaisesRegex(ValueError, "historical observations"):
            sorter_engine.review_learning_candidate("rimshot", "Snares", "approved")
        self.assertNotIn(r"\brimshot\w*\b", sorter_engine.DRUM_KEYWORDS)

    def test_bulk_cannot_bypass_historical_floor_but_rejection_is_allowed(self):
        sorter_engine.record_learning_evidence([("rimshot", "Snares")] * 20)
        sorter_engine.record_learning_evidence([("quasar", "Snares")] * 7, minimum_count=5)
        with self.assertRaisesRegex(ValueError, "at least 20"):
            sorter_engine.review_learning_candidates((("rimshot", "Snares"), ("quasar", "Snares")), "approved")
        self.assertNotIn(r"\brimshot\w*\b", sorter_engine.DRUM_KEYWORDS)
        self.assertTrue(all(c["status"] == "pending" for c in sorter_engine.LEARNED_RULE_CANDIDATES))
        sorter_engine.review_learning_candidate("quasar", "Snares", "rejected")
        self.assertEqual("rejected", sorter_engine.LEARNED_RULE_CANDIDATES[1]["status"])

    def test_approving_candidate_activates_only_that_rule(self):
        sorter_engine.record_learning_evidence([("rimshot", "Snares")] * 20)
        # The wrapper persists only candidates whose current evidence was verified.
        from unittest import mock
        with mock.patch("rule_suggester.revalidate_candidates", side_effect=lambda candidates: candidates):
            sorter_engine.review_learning_candidate("rimshot", "Snares", "approved")

        self.assertIn(r"\brimshot\w*\b", sorter_engine.DRUM_KEYWORDS)
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as config_file:
            saved = json.load(config_file)
        self.assertEqual("approved", saved["LEARNED_RULE_CANDIDATES"][0]["status"])

    def test_rejecting_candidate_does_not_activate_rule(self):
        sorter_engine.record_learning_evidence([("rimshot", "Snares")] * 20)

        sorter_engine.review_learning_candidate("rimshot", "Snares", "rejected")

        self.assertNotIn(r"\brimshot\w*\b", sorter_engine.DRUM_KEYWORDS)

    def test_disabled_learning_does_not_persist_evidence(self):
        sorter_engine.SMART_LEARNING_ENABLED = False

        self.assertEqual([], sorter_engine.record_learning_evidence([("kick", "Kicks")] * 10))
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as config_file:
            saved = json.load(config_file)
        self.assertNotIn("LEARNING_COUNTS", saved)

    def test_preview_classifies_without_changing_source_or_destination(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        sample_path = os.path.join(source, "heavy_kick.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        class ImmediateWindow:
            def after(self, _delay, callback):
                callback()

        sorter = sorter_engine.ParallelLibrarySorter(
            source, destination, ImmediateWindow(), lambda _message: None,
            lambda _stats, _copy_mode: None, copy_mode=True, preview_only=True
        )
        sorter.harvested_metadata = {}
        sorter.process_single_file(source, "heavy_kick.wav")

        self.assertTrue(os.path.exists(sample_path))
        self.assertFalse(os.path.exists(os.path.join(destination, "Samples")))
        self.assertEqual(1, len(sorter.preview_records))
        self.assertEqual("filename_rule", sorter.preview_records[0]["reason"])
        self.assertEqual(0.95, sorter.preview_records[0]["confidence"])
        self.assertIn("category:Kicks", sorter.preview_records[0]["tags"])

        indexed = sorter_engine.get_indexed_asset(sample_path)
        self.assertEqual("filename_rule", indexed["reason"])
        self.assertIn("category:Kicks", indexed["tags"])

    def test_cancelled_sorter_leaves_file_untouched(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        sample_path = os.path.join(source, "heavy_kick.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        class ImmediateWindow:
            def after(self, _delay, callback):
                callback()

        sorter = sorter_engine.ParallelLibrarySorter(
            source, destination, ImmediateWindow(), lambda _message: None,
            lambda _stats, _copy_mode: None, copy_mode=False
        )
        sorter.cancel()
        sorter.process_single_file(source, "heavy_kick.wav")

        self.assertTrue(os.path.exists(sample_path))
        self.assertFalse(os.path.exists(os.path.join(destination, "Samples")))

    def test_file_operation_failure_is_recorded_with_context(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library")
        os.makedirs(source)
        sorter = sorter_engine.ParallelLibrarySorter(
            source, destination, type("Window", (), {"after": lambda *_args: None})(),
            lambda _message: None, lambda _stats, _copy_mode: None,
            copy_mode=False
        )

        sorter.process_single_file(source, "missing_kick.wav")

        self.assertEqual(1, len(sorter.operation_errors))
        failure = sorter.operation_errors[0]
        self.assertEqual("move", failure["operation"])
        self.assertIn("missing_kick.wav", failure["source"])
        self.assertTrue(failure["error"])
        self.assertEqual(1, sorter.stats["Errors/Skipped Files"])

    def test_asset_index_updates_tags_without_duplicate_rows(self):
        asset_path = os.path.join(self.temp_dir.name, "sample.wav")
        with open(asset_path, "wb") as asset_file:
            asset_file.write(b"abc")

        sorter_engine.index_asset(asset_path, "Kicks", "filename_rule", 0.95, ["kick", "category:Kicks"])
        sorter_engine.add_asset_tag(asset_path, "favorite")
        sorter_engine.index_asset(asset_path, "Snares", "ableton_metadata", 0.85, ["category:Snares"])

        indexed = sorter_engine.get_indexed_asset(asset_path)
        self.assertEqual("Snares", indexed["destination"])
        self.assertIn("favorite", indexed["tags"])
        self.assertIn("category:Snares", indexed["tags"])
        self.assertNotIn("category:Kicks", indexed["tags"])

    def test_move_migrates_preview_index_record_to_destination(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        destination = os.path.join(self.temp_dir.name, "library", "Samples", "One-Shots", "Kicks")
        os.makedirs(source)
        os.makedirs(destination)
        source_path = os.path.join(source, "heavy_kick.wav")
        destination_path = os.path.join(destination, "heavy_kick.wav")
        with open(source_path, "wb") as asset_file:
            asset_file.write(b"sample")

        sorter_engine.index_asset(
            source_path, destination, "filename_rule", 0.95,
            ["name:heavy", "category:Kicks"]
        )
        sorter_engine.add_asset_tag(source_path, "favorite")
        os.replace(source_path, destination_path)

        sorter_engine.index_asset(
            destination_path, destination, "filename_rule", 0.95,
            ["name:heavy", "category:Kicks"], previous_path=source_path
        )

        self.assertIsNone(sorter_engine.get_indexed_asset(source_path))
        migrated = sorter_engine.get_indexed_asset(destination_path)
        self.assertIsNotNone(migrated)
        self.assertIn("favorite", migrated["tags"])
        self.assertEqual(
            1,
            len(sorter_engine.list_indexed_assets())
        )

    def test_asset_tag_browser_queries_and_user_tags(self):
        asset_path = os.path.join(self.temp_dir.name, "dark_kick.wav")
        with open(asset_path, "wb") as asset_file:
            asset_file.write(b"abc")
        sorter_engine.index_asset(
            asset_path, "Kicks", "filename_rule", 0.95,
            ["name:kick", "category:Kicks"]
        )

        sorter_engine.add_asset_tag(asset_path, "favorite")

        records = sorter_engine.list_indexed_assets(tag_filter="favorite")
        self.assertEqual(1, len(records))
        self.assertEqual(
            1, len(sorter_engine.list_indexed_assets(tag_filter="  FAVORITE  "))
        )
        self.assertIn("favorite", records[0]["tags"])
        self.assertIn(("favorite", 1), sorter_engine.list_indexed_tags())
        sorter_engine.remove_asset_tag(asset_path, "favorite")
        self.assertNotIn("favorite", sorter_engine.get_indexed_asset(asset_path)["tags"])

    def test_disabling_tag_preserves_assignment_and_excludes_it_from_search(self):
        asset_path = os.path.join(self.temp_dir.name, "tagged.wav")
        with open(asset_path, "wb") as asset_file:
            asset_file.write(b"abc")

        sorter_engine.index_asset(asset_path, "Kicks", "filename_rule", 0.95, ["name:kick"])
        sorter_engine.set_asset_tag_enabled(asset_path, "name:kick", False)

        indexed = sorter_engine.get_indexed_asset(asset_path)
        self.assertNotIn("name:kick", indexed["tags"])
        self.assertEqual(["name:kick"], indexed["disabled_tags"])
        self.assertEqual([], sorter_engine.list_indexed_assets(tag_filter="name:kick"))

        sorter_engine.index_asset(asset_path, "Kicks", "filename_rule", 0.95, ["name:kick"])
        indexed = sorter_engine.get_indexed_asset(asset_path)
        self.assertEqual(["name:kick"], indexed["disabled_tags"])
        self.assertEqual([], indexed["tags"])
        sorter_engine.set_asset_tag_enabled(asset_path, "name:kick", True)
        self.assertIn("name:kick", sorter_engine.get_indexed_asset(asset_path)["tags"])

    def test_bulk_tag_update_applies_and_removes_tag(self):
        paths = []
        for filename in ("one.wav", "two.wav"):
            path = os.path.join(self.temp_dir.name, filename)
            with open(path, "wb") as asset_file:
                asset_file.write(b"abc")
            sorter_engine.index_asset(path, "Kicks", "filename_rule", 0.95, [])
            paths.append(path)

        sorter_engine.bulk_update_asset_tags(paths, "favorite")
        self.assertEqual(2, len(sorter_engine.list_indexed_assets(tag_filter="favorite")))
        sorter_engine.bulk_update_asset_tags(paths, "favorite", remove=True)
        self.assertEqual(0, len(sorter_engine.list_indexed_assets(tag_filter="favorite")))

    def test_advanced_asset_search_supports_filters_and_exclusions(self):
        assets = [
            ("dark_loop_120bpm.wav", ["favorite", "type:loop", "bpm:120", "key:Am"]),
            ("bright_loop_120bpm.wav", ["type:loop", "bpm:120", "key:C"]),
            ("dark_kick.wav", ["favorite", "role:kick"]),
        ]
        for filename, tags in assets:
            path = os.path.join(self.temp_dir.name, filename)
            with open(path, "wb") as asset_file:
                asset_file.write(b"abc")
            sorter_engine.index_asset(path, "Samples/Loops", "filename_rule", 0.95, tags)

        results = sorter_engine.list_indexed_assets(
            'tag:favorite type:loop bpm:120 key:Am -bright'
        )
        self.assertEqual(["dark_loop_120bpm.wav"], [row["filename"] for row in results])

    def test_asset_search_matches_multiple_words_across_asset_details(self):
        asset_path = os.path.join(self.temp_dir.name, "Dark_Kick_Reference.wav")
        with open(asset_path, "wb") as asset_file:
            asset_file.write(b"abc")

        sorter_engine.index_asset(
            asset_path, "Kicks", "filename_rule", 0.95,
            ["name:dark", "name:kick", "favorite"]
        )

        records = sorter_engine.list_indexed_assets("dark favorite")
        self.assertEqual([asset_path], [record["path"] for record in records])

    def test_filename_tags_are_searchable_but_not_routing_rules(self):
        self.assertEqual(
            ["name:dark", "name:kick"],
            sorter_engine.derive_filename_tags("dark_kick_v2.wav")
        )

    def test_personal_tags_do_not_change_classification(self):
        self.assertFalse(hasattr(sorter_engine, "resolve_routing_tags"))

    def test_retired_routing_role_does_not_override_classification(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        os.makedirs(source)
        sample_path = os.path.join(source, "mystery.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")
        sorter_engine.index_asset(
            sample_path, "Snares", "filename_rule", 0.95, ["role:snare"]
        )

        class ImmediateWindow:
            def after(self, _delay, callback):
                callback()

        sorter = sorter_engine.ParallelLibrarySorter(
            source, os.path.join(self.temp_dir.name, "library"),
            ImmediateWindow(), lambda _message: None,
            lambda _stats, _copy_mode: None, copy_mode=True, preview_only=True
        )
        sorter.process_single_file(source, "mystery.wav")

        self.assertEqual(
            os.path.join(self.temp_dir.name, "library", "Samples", "One-Shots", "Other One-Shots"),
            sorter.preview_records[0]["destination"]
        )
        self.assertEqual("audio_fallback", sorter.preview_records[0]["reason"])

    def test_retired_loop_tag_does_not_force_loop_routing(self):
        source = os.path.join(self.temp_dir.name, "incoming")
        os.makedirs(source)
        sample_path = os.path.join(source, "mystery_120bpm_Am.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")
        sorter_engine.index_asset(
            sample_path, "Other One-Shots", "audio_fallback", 0.35, ["type:loop"]
        )
        sorter_engine.BPM_RANGES = [(115, 129, "115-129 BPM")]

        class ImmediateWindow:
            def after(self, _delay, callback):
                callback()

        sorter = sorter_engine.ParallelLibrarySorter(
            source, os.path.join(self.temp_dir.name, "library"),
            ImmediateWindow(), lambda _message: None,
            lambda _stats, _copy_mode: None, copy_mode=True, preview_only=True
        )
        sorter.process_single_file(source, "mystery_120bpm_Am.wav")

        self.assertNotEqual("routing_tag", sorter.preview_records[0]["reason"])

    def test_reorganizing_already_sorted_file_is_a_no_op(self):
        library = os.path.join(self.temp_dir.name, "library")
        sorted_dir = os.path.join(library, "Samples", "One-Shots", "Kicks")
        os.makedirs(sorted_dir)
        sample_path = os.path.join(sorted_dir, "heavy_kick.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        class ImmediateWindow:
            def after(self, _delay, callback):
                callback()

        sorter = sorter_engine.ParallelLibrarySorter(
            library, library, ImmediateWindow(), lambda _message: None,
            lambda _stats, _copy_mode: None, copy_mode=False, preview_only=False
        )
        sorter.process_single_file(sorted_dir, "heavy_kick.wav")

        self.assertTrue(os.path.exists(sample_path))
        self.assertFalse(
            os.path.exists(os.path.join(library, "Samples", "One-Shots", "Other One-Shots", "heavy_kick.wav"))
        )

    def test_nested_organized_path_is_never_deleted_in_move_mode(self):
        library = os.path.join(self.temp_dir.name, "library")
        nested_dir = os.path.join(library, "Samples", "Loops", "Nested", "Loops")
        os.makedirs(nested_dir)
        sample_path = os.path.join(nested_dir, "loop.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        class ImmediateWindow:
            def after(self, _delay, callback):
                callback()

        sorter = sorter_engine.ParallelLibrarySorter(
            library, library, ImmediateWindow(), lambda _message: None,
            lambda _stats, _copy_mode: None, copy_mode=False, preview_only=False
        )
        sorter.process_single_file(nested_dir, "loop.wav")

        self.assertTrue(os.path.exists(sample_path))

    def test_nested_folder_scan_proposes_flattened_destination(self):
        library = os.path.join(self.temp_dir.name, "library")
        nested_dir = os.path.join(library, "Samples", "Samples", "One-Shots", "Kicks")
        os.makedirs(nested_dir)
        sample_path = os.path.join(nested_dir, "kick.wav")
        with open(sample_path, "wb") as sample_file:
            sample_file.write(b"sample")

        suggestions = sorter_engine.find_nested_folder_repairs(library)

        self.assertEqual(1, len(suggestions))
        self.assertEqual(
            os.path.join(library, "Samples", "One-Shots", "Kicks", "kick.wav"),
            suggestions[0]["destination"]
        )

    def test_nested_repair_skips_collisions_and_never_overwrites(self):
        library = os.path.join(self.temp_dir.name, "library")
        source_dir = os.path.join(library, "Samples", "Samples", "One-Shots")
        destination_dir = os.path.join(library, "Samples", "One-Shots")
        os.makedirs(source_dir)
        os.makedirs(destination_dir)
        source = os.path.join(source_dir, "kick.wav")
        destination = os.path.join(destination_dir, "kick.wav")
        with open(source, "wb") as source_file:
            source_file.write(b"source")
        with open(destination, "wb") as destination_file:
            destination_file.write(b"original")

        result = sorter_engine.repair_nested_folder_files([{
            "source": source, "destination": destination, "reason": "test"
        }])

        self.assertEqual(0, result["moved"])
        self.assertEqual(1, result["skipped"])
        with open(destination, "rb") as destination_file:
            self.assertEqual(b"original", destination_file.read())
        self.assertTrue(os.path.exists(source))

    def test_disabled_rule_is_not_used_for_classification(self):
        sorter_engine.RULE_METADATA = {r"\bkick(s)?\b": {
            "priority": 100, "enabled": False, "exclude": []
        }}
        self.assertEqual([], sorter_engine.iter_active_drum_rules())

    def test_priority_controls_rule_order_and_exclusions(self):
        sorter_engine.DRUM_KEYWORDS = {
            r"\bkick(s)?\b": "Kicks",
            r"\bdrum\b": "Other One-Shots"
        }
        sorter_engine.RULE_METADATA = {
            r"\bkick(s)?\b": {"priority": 1, "enabled": True, "exclude": [r"\bdrum\b"]},
            r"\bdrum\b": {"priority": 100, "enabled": True, "exclude": []}
        }
        rules = sorter_engine.iter_active_drum_rules()
        self.assertEqual(r"\bdrum\b", rules[0][0])
        self.assertEqual(r"\bkick(s)?\b", rules[1][0])

    def test_rule_metadata_update_persists_without_dropping_rule(self):
        sorter_engine.set_rule_metadata(
            r"\bkick(s)?\b", enabled=False, priority=120, exclude=[r"\bloop\b"]
        )

        self.assertEqual([], sorter_engine.iter_active_drum_rules())
        with open(sorter_engine.CONFIG_FILE, "r", encoding="utf-8") as config_file:
            saved = json.load(config_file)
        self.assertIn(r"\bkick(s)?\b", saved["DRUM_KEYWORDS"])
        self.assertEqual(120, saved["RULE_METADATA"][r"\bkick(s)?\b"]["priority"])

    def test_toggling_rule_keeps_implicit_priority(self):
        sorter_engine.DRUM_KEYWORDS = {r"\bkick\b": "Kicks", r"\bsnare\b": "Snares"}
        sorter_engine.RULE_METADATA = {r"\bsnare\b": {"priority": 1, "enabled": True, "exclude": []}}
        sorter_engine.set_rule_metadata(r"\bsnare\b", enabled=False)
        sorter_engine.set_rule_metadata(r"\bsnare\b", enabled=True)
        self.assertEqual(1, sorter_engine.RULE_METADATA[r"\bsnare\b"]["priority"])

    def test_specific_new_rule_is_placed_above_broader_rule(self):
        sorter_engine.DRUM_KEYWORDS = {
            r"\bkick\b": "Kicks", r"\bsnare(s)?\b": "Snares", r"\bhat\b": "Hi-Hats"
        }
        sorter_engine.RULE_METADATA = {}
        with open(sorter_engine.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump({"DRUM_KEYWORDS": sorter_engine.DRUM_KEYWORDS}, config_file)

        placement = sorter_engine.add_rule_with_smart_priority(
            r"\bsnare\s*roll\b", "Snare Rolls"
        )

        order = [r[0] for r in sorter_engine.iter_active_drum_rules()]
        self.assertLess(order.index(r"\bsnare\s*roll\b"), order.index(r"\bsnare(s)?\b"))
        self.assertEqual([r"\bsnare(s)?\b"], placement["above"])
        priorities = [m["priority"] for m in sorter_engine.RULE_METADATA.values()]
        self.assertEqual(len(priorities), len(set(priorities)))

    def test_unrelated_new_rule_goes_last_and_move_rule_reorders(self):
        sorter_engine.DRUM_KEYWORDS = {r"\bkick\b": "Kicks", r"\bsnare\b": "Snares"}
        sorter_engine.RULE_METADATA = {}
        with open(sorter_engine.CONFIG_FILE, "w", encoding="utf-8") as config_file:
            json.dump({"DRUM_KEYWORDS": sorter_engine.DRUM_KEYWORDS}, config_file)

        sorter_engine.add_rule_with_smart_priority(r"\bweird\b", "Weird")
        order = [r[0] for r in sorter_engine.iter_active_drum_rules()]
        self.assertEqual(r"\bweird\b", order[-1])

        self.assertTrue(sorter_engine.move_rule(r"\bweird\b", -1))
        order = [r[0] for r in sorter_engine.iter_active_drum_rules()]
        self.assertEqual(r"\bweird\b", order[1])
        self.assertFalse(sorter_engine.move_rule(r"\bkick\b", -1))

    def test_competing_rules_report_shared_filename(self):
        sorter_engine.DRUM_KEYWORDS = {
            r"\b(synth|pad)\b": "Synths", r"\b(pad|drone)\b": "Ambience"
        }
        sorter_engine.RULE_METADATA = {}
        competitions = sorter_engine.find_rule_competitions()
        self.assertEqual(1, len(competitions))
        self.assertEqual("pad", competitions[0][4])


if __name__ == "__main__":
    unittest.main()

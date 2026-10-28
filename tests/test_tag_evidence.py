import json
import os
import tempfile
import threading
import unittest
from contextlib import closing
from unittest import mock

import ableton_tags
import rule_suggester
import sorter_engine
import tag_evidence
import xo_filter


class TagEvidenceTests(unittest.TestCase):
    def test_manual_keys_require_one_root_and_mode_and_preserve_exact_labels(self):
        examples = (
            (["Key|C", "Key|Major"], "CMAJ"),
            (["Key|C\u266f", "Key|Minor"], "C#MIN"),
            (["Key|D\u266d", "Key|C#", "Key|Minor"], "C#MIN"),
            (["Key|B\u266d", "Key|Major"], "A#MAJ"),
        )
        for tags, expected in examples:
            with self.subTest(tags=tags):
                evidence = tag_evidence.interpret_manual_key(tags)
                self.assertEqual(expected, evidence.key)
                self.assertEqual(tuple(sorted(tags)), evidence.assignments)
                self.assertFalse(evidence.ambiguous)
        for tags in (["Key|C"], ["Key|Minor"], ["Genres|C", "Character|Minor"], ["Key|Custom|C"]):
            self.assertIsNone(tag_evidence.interpret_manual_key(tags).key)
        for tags in (["Key|C", "Key|D", "Key|Minor"], ["Key|C", "Key|Major", "Key|Minor"]):
            self.assertTrue(tag_evidence.interpret_manual_key(tags).ambiguous)
            self.assertIsNone(tag_evidence.interpret_manual_key(tags).key)
        self.assertEqual("C#MIN", tag_evidence.key_identity("Dbmin"))
        self.assertEqual("A#MAJ", tag_evidence.key_identity("B\u266d Major"))
        self.assertIsNone(tag_evidence.key_identity("C"))
        self.assertIsNone(tag_evidence.key_identity("8A"))

    def test_verified_live_hierarchies_use_group_and_parent_semantics(self):
        examples = {
            "Drums|Kick": "Kicks", "Drums|Snare|Rim": "Snares",
            "Drums|Snare|Snare Hit": "Snares", "Drums|Hihat|Closed Hihat": "Hi-Hats",
            "Drums|Cymbal|Ride": "Cymbals", "Drums|Tom|Low Tom": "Toms",
            "Drums|Percussion|Bell": "Percussion", "Drums|Percussion|Snap": "Percussion",
            "Sounds|Bass|808 Bass": "808 & Sub Bass",
            "Sounds|Bass|Acoustic Bass": "Guitar & Bass Guitar",
            "Sounds|Piano & Keys|Synth Keys": "Keys & Piano",
            "Sounds|Strings|String Ensemble": "Strings & Orchestral",
            "Sounds|Voice|Vocal FX": "Vocals", "Sounds|Woodwind|Flute": "Brass & Winds",
            "Sounds|Guitar & Plucked|Synth Plucked": "Plucks & Synths",
            "Sounds|Mallets|Bell Chromatic": "Bells & Mallets",
            "Sounds|Ambience & FX|Field & Foley": "Foley",
            "Sounds|Ambience & FX|Atmosphere": "Ambience & Textures",
        }
        for tag, expected in examples.items():
            with self.subTest(tag=tag):
                evidence = tag_evidence.interpret_manual_tags([tag])
                self.assertEqual(expected, evidence.sound_type)
                self.assertEqual((tag,), evidence.assignments)
        evidence = tag_evidence.interpret_manual_tags(["Sounds|Bass", "Sounds|Bass|808 Bass"])
        self.assertEqual("808 & Sub Bass", evidence.sound_type)
        conflict = tag_evidence.interpret_manual_tags(["Drums|Kick", "Sounds|Voice|Choir"])
        self.assertIsNone(conflict.sound_type)
        self.assertEqual(("Kicks", "Vocals"), conflict.alternatives)
        for group in ("Genres", "Character", "Devices", "Function", "Format", "MIDI Tools", "Creator", "Key"):
            self.assertEqual((), tag_evidence.interpret_manual_tags([f"{group}|Kick"]).assignments)

    def test_manual_roles_are_not_sound_types_and_non_one_shots_are_protected(self):
        for tag in ("Type|Loop", "Drums|Drum Loop|Top Drum Loop", "Sounds|Loop"):
            evidence = tag_evidence.interpret_manual_tags([tag, "Drums|Snare|Rim"])
            self.assertTrue(evidence.is_loop)
            self.assertEqual("Snares", evidence.sound_type)
            self.assertIn(tag, evidence.assignments)
        for tag in ("Type|Impulse Response", "Type|Multisampled", "Type|Construction Kit", "Drums|Drum Kit|Hybrid Kit"):
            evidence = tag_evidence.interpret_manual_tags([tag, "Drums|Snare"])
            self.assertFalse(evidence.one_shot_eligible)
        evidence = tag_evidence.interpret_manual_tags(["Type|One Shot"])
        self.assertIsNone(evidence.sound_type)
        self.assertFalse(evidence.is_loop)
        self.assertEqual(("Type|One Shot",), evidence.assignments)

    def test_exact_leaf_mapping_and_non_sound_groups(self):
        evidence = tag_evidence.interpret_manual_tags(["Sounds|Drums|Snare", "Character|Kick", "Instrument|Bass"])
        self.assertEqual("Snares", evidence.sound_type)
        self.assertEqual(("Sounds|Drums|Snare",), evidence.assignments)
        for tags in (["Character|Kick"], ["Sounds|Snare|Unknown"], ["category:Snares"], ["name:kick"]):
            self.assertIsNone(tag_evidence.interpret_manual_tags(tags).sound_type)

    def test_conflicting_manual_types_do_not_resolve_by_order(self):
        for tags in (["Sounds|Kick", "Sounds|Snare"], ["Sounds|Snare", "Sounds|Kick"]):
            evidence = tag_evidence.interpret_manual_tags(tags)
            self.assertIsNone(evidence.sound_type)
            self.assertEqual(("Kicks", "Snares"), evidence.alternatives)

    def test_xo_does_not_flatten_live_character_or_generated_cache_into_personal_hints(self):
        self.assertIsNone(xo_filter.classify(
            os.path.join("library", "mystery.wav"), "library",
            ["ableton:Character|Kick", "category:Snares", "name:clap"]
        )[0])
        self.assertEqual("Kicks", xo_filter.classify(
            os.path.join("library", "mystery.wav"), "library", ["kick"]
        )[0])


class TagEvidenceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        self.source = os.path.join(self.root, "incoming")
        self.destination = os.path.join(self.root, "library")
        os.makedirs(self.source)
        for name, value in (
            ("ASSET_INDEX_FILE", os.path.join(self.root, "assets.db")),
            ("CONFIG_FILE", os.path.join(self.root, "config.json")),
            ("DRUM_KEYWORDS", {r"\bkick\b": "Kicks"}),
            ("RULE_METADATA", {}), ("LEARNED_RULE_CANDIDATES", []),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def sample(self, name, tags=(), folder=None):
        path = os.path.join(folder or self.source, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"audio")
        for tag in tags:
            ableton_tags.prepare_edit([path], tag).commit()
        return path

    def run_sorter(self, preview=True, copy_mode=True):
        class Window:
            def after(self, _delay, callback):
                callback()
        completed = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            self.source, self.destination, Window(), lambda _text: None,
            lambda *_args: completed.set(), copy_mode=copy_mode, preview_only=preview
        )
        sorter.start_parallel_sort()
        self.assertTrue(completed.wait(5))
        sorter.worker_thread.join(5)
        self.assertFalse(sorter.worker_thread.is_alive())
        return sorter

    def pending_manual_candidate(self, token="Quasar", count=20, **thresholds):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        paths = [
            self.sample(f"{token} {index}.wav", ["Drums|Snare|Rim", "Type|One Shot"], catch_all)
            for index in range(count)
        ]
        thresholds.setdefault("min_files", 20)
        suggestions = rule_suggester.suggest_rules(self.source, **thresholds)
        candidate = next(item for item in suggestions if item["token"] == token.lower())
        with mock.patch.object(sorter_engine, "load_external_config"):
            rule_suggester.add_suggestions_as_candidates([candidate])
        return paths, candidate

    def test_loop_layout_audits_fresh_roles_and_keys_without_changing_filename_plan(self):
        from pathlib import Path
        tagged = self.sample("mystery.wav", ["Type|Loop", "Key|C", "Key|Minor"])
        conflict = self.sample("groove 100 bpm Cmaj.wav", ["Type|One Shot", "Key|D", "Key|Minor"])
        self.sample("rhythm loop.wav", ["Key|C", "Key|D", "Key|Minor"])
        self.sample("incomplete loop.wav", ["Key|C"])
        self.sample("unknown loop.wav", ["Key|F", "Key|Major"])
        self.sample("same loop 110 bpm Dbmin.wav", ["Key|C\u266f", "Key|Minor"])
        self.sample("ignored.adg", ["Type|Loop", "Key|A", "Key|Minor"])
        before = {
            path: Path(path).read_bytes() for path in (tagged, conflict)
        }
        result = sorter_engine.recommend_loop_layout(self.source)
        self.assertEqual(5, result["loops"])
        audit = result["tag_evidence"]
        self.assertEqual(1, audit["manual_loops"])
        self.assertEqual(1, audit["tag_only_loops"])
        self.assertEqual(1, audit["role_conflicts"])
        self.assertEqual(4, audit["complete_keys"])
        self.assertEqual(1, audit["key_conflicts"])
        self.assertEqual(2, audit["keys_missing_from_filenames"])
        self.assertEqual(1, audit["ambiguous_keys"])
        self.assertEqual(1, audit["incomplete_keys"])
        self.assertTrue(any("Key|C" in item["assignments"] for item in audit["examples"]))
        self.assertIn("review-only", tag_evidence.describe_loop_tag_audit(audit))
        with mock.patch.object(ableton_tags, "read_sample_assignments", return_value={}):
            filename_only = sorter_engine.recommend_loop_layout(self.source)
        self.assertEqual(result["layout"], filename_only["layout"])
        self.assertEqual(result["stats"], filename_only["stats"])
        ableton_tags.prepare_edit([tagged], "Key|Minor", replacement="Key|Major").commit()
        updated = sorter_engine.recommend_loop_layout(self.source)
        item = next(item for item in updated["tag_evidence"]["examples"] if item["path"] == tagged)
        self.assertEqual("CMAJ", item["manual_key"])
        for path, data in before.items():
            with open(path, "rb") as handle:
                self.assertEqual(data, handle.read())

    def test_loop_layout_failure_and_cancellation_are_not_partial_successes(self):
        self.sample("loop.wav", ["Type|Loop"])
        with self.assertRaisesRegex(ValueError, "cancelled"):
            sorter_engine.recommend_loop_layout(self.source, should_cancel=lambda: True)
        from pathlib import Path
        next(Path(self.source, "Ableton Folder Info").glob("*.xmp")).write_bytes(b"<broken")
        with self.assertRaisesRegex(ValueError, "Invalid Ableton"):
            sorter_engine.recommend_loop_layout(self.source)

    def test_candidate_approval_blocks_changed_manual_tags_without_writing_config(self):
        paths, candidate = self.pending_manual_candidate()
        with open(sorter_engine.CONFIG_FILE, "rb") as handle:
            before = handle.read()
        ableton_tags.prepare_edit([paths[0]], "Drums|Snare|Rim", replacement="Drums|Kick").commit()
        with mock.patch.object(sorter_engine, "_write_config") as write:
            with self.assertRaisesRegex(ValueError, "no longer supported"):
                sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
            write.assert_not_called()
        with open(sorter_engine.CONFIG_FILE, "rb") as handle:
            self.assertEqual(before, handle.read())
        self.assertNotIn(candidate["pattern"], sorter_engine.DRUM_KEYWORDS)

    def test_deleted_support_and_unreadable_metadata_block_approval(self):
        paths, candidate = self.pending_manual_candidate()
        os.remove(paths[0])
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        self.sample(os.path.basename(paths[0]), ["Drums|Snare|Rim"], os.path.dirname(paths[0]))
        from pathlib import Path
        next(Path(os.path.dirname(paths[0]), "Ableton Folder Info").glob("*.xmp")).write_bytes(b"<broken")
        with self.assertRaisesRegex(ValueError, "Invalid Ableton"):
            sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            self.assertEqual("pending", json.load(handle)["LEARNED_RULE_CANDIDATES"][0]["status"])

    def test_bulk_approval_is_all_or_nothing_and_scans_each_scope_once(self):
        _paths, first = self.pending_manual_candidate()
        paths, second = self.pending_manual_candidate("Nebula")
        selections = ((first["token"], first["target"]), (second["token"], second["target"]))
        ableton_tags.prepare_edit([paths[0]], "Drums|Snare|Rim", replacement="Drums|Kick").commit()
        with mock.patch.object(rule_suggester, "suggest_rules", wraps=rule_suggester.suggest_rules) as scan:
            with self.assertRaisesRegex(ValueError, "no longer supported"):
                sorter_engine.review_learning_candidates(selections, "approved")
            self.assertEqual(1, scan.call_count)
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(["pending", "pending"], [item["status"] for item in saved["LEARNED_RULE_CANDIDATES"]])
        self.assertEqual({}, saved.get("DRUM_KEYWORDS", {}))
        ableton_tags.prepare_edit([paths[0]], "Drums|Kick", replacement="Drums|Snare|Rim").commit()
        with mock.patch.object(rule_suggester, "suggest_rules", wraps=rule_suggester.suggest_rules) as scan, mock.patch.object(
            sorter_engine, "load_external_config"
        ):
            sorter_engine.review_learning_candidates(selections, "approved")
            self.assertEqual(1, scan.call_count)
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(["approved", "approved"], [item["status"] for item in saved["LEARNED_RULE_CANDIDATES"]])
        self.assertEqual("Snares", saved["DRUM_KEYWORDS"][first["pattern"]])
        self.assertEqual("Snares", saved["DRUM_KEYWORDS"][second["pattern"]])

    def test_approval_preserves_scan_thresholds_and_refreshes_evidence_counts(self):
        paths, candidate = self.pending_manual_candidate(count=20, min_files=3, min_share=0.75)
        self.sample("Quasar extra.wav", ["Drums|Snare|Rim"], os.path.dirname(paths[0]))
        with mock.patch.object(sorter_engine, "load_external_config"):
            sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)["LEARNED_RULE_CANDIDATES"][0]
        self.assertEqual(21, saved["count"])
        self.assertEqual(21, saved["evidence_total"])
        self.assertEqual(20, saved["min_files"])
        self.assertEqual(0.9, saved["min_share"])
        self.assertEqual(os.path.abspath(self.source), saved["library_root"])

    def test_legacy_manual_suggestions_require_refresh_but_can_be_dismissed(self):
        _paths, candidate = self.pending_manual_candidate()
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        for field in ("library_root", "min_files", "min_share"):
            data["LEARNED_RULE_CANDIDATES"][0].pop(field)
        sorter_engine._write_config(data)
        with self.assertRaisesRegex(ValueError, "Refresh suggestions"):
            sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        suggestions = rule_suggester.suggest_rules(self.source, min_files=5)
        with mock.patch.object(sorter_engine, "load_external_config"):
            self.assertEqual(0, rule_suggester.add_suggestions_as_candidates(suggestions))
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            refreshed = json.load(handle)["LEARNED_RULE_CANDIDATES"]
        self.assertEqual(1, len(refreshed))
        self.assertEqual(os.path.abspath(self.source), refreshed[0]["library_root"])
        with mock.patch.object(rule_suggester, "revalidate_candidates") as validate, mock.patch.object(
            sorter_engine, "load_external_config"
        ):
            sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "rejected")
            validate.assert_not_called()

    @mock.patch.object(sorter_engine, "load_external_config")
    def test_completed_refresh_retires_stale_evidence_then_revives_after_repair(self, _load):
        paths, candidate = self.pending_manual_candidate(count=20)
        ableton_tags.prepare_edit([paths[0]], "Drums|Snare|Rim", replacement="Drums|Kick").commit()
        found = rule_suggester.suggest_rules(self.source)
        rule_suggester.add_suggestions_as_candidates(found, library_root=self.source)
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)["LEARNED_RULE_CANDIDATES"][0]
        self.assertEqual("stale", saved["status"])
        self.assertFalse(sorter_engine.is_reviewable_learning_candidate(saved))
        with self.assertRaisesRegex(ValueError, "Pending learning candidate was not found"):
            sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        ableton_tags.prepare_edit([paths[0]], "Drums|Kick", replacement="Drums|Snare|Rim").commit()
        found = rule_suggester.suggest_rules(self.source)
        rule_suggester.add_suggestions_as_candidates(found, library_root=self.source)
        sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual("approved", saved["LEARNED_RULE_CANDIDATES"][0]["status"])
        self.assertEqual("Snares", saved["DRUM_KEYWORDS"][candidate["pattern"]])

    def test_config_changes_during_revalidation_are_not_overwritten(self):
        _paths, candidate = self.pending_manual_candidate()
        original = rule_suggester.revalidate_candidates
        def revalidate_then_change_profile(candidates):
            current = original(candidates)
            with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
            data["XO_CUSTOM_TYPES"] = {"Keep": ["me"]}
            sorter_engine._write_config(data)
            return current
        with mock.patch.object(rule_suggester, "revalidate_candidates", side_effect=revalidate_then_change_profile):
            with self.assertRaisesRegex(ValueError, "profile changed"):
                sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual({"Keep": ["me"]}, saved["XO_CUSTOM_TYPES"])
        self.assertEqual("pending", saved["LEARNED_RULE_CANDIDATES"][0]["status"])

    def test_verified_drums_tags_flow_through_preview_hints_xo_and_rule_learning(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        paths = [
            self.sample(f"Quasar {index}.wav", ["Drums|Snare|Rim", "Type|One Shot", "Genres|Ambient"], catch_all)
            for index in range(5)
        ]
        candidate = next(item for item in rule_suggester.suggest_rules(self.source, min_files=5) if item["token"] == "quasar")
        self.assertEqual("Snares", candidate["target"])
        self.assertEqual(5, candidate["count"])
        self.assertEqual(["Drums|Snare|Rim", "Type|One Shot"], candidate["evidence_tags"])
        records = {record["source"]: record for record in self.run_sorter().preview_records}
        proposal = records[paths[0]]["tag_suggestion"]
        self.assertEqual("Snares", proposal["sound_type"])
        self.assertTrue(proposal["destination"].endswith("Snares"))
        hints = tag_evidence.describe_library_evidence(paths[0], self.source, candidate["evidence_tags"], None, None)
        self.assertIn("Suggested folder:", hints)
        self.assertIn("Drums|Snare|Rim", hints)
        plan, stats = xo_filter.build_plan(self.source, use_live_tags=True)
        self.assertEqual(set(paths), set(plan["Snares"]))
        self.assertEqual(5, stats["manual_classified"])

    def test_roles_block_one_shot_suggestions_without_changing_normal_sorting(self):
        loop = self.sample("loopless.wav", ["Drums|Snare|Rim", "Type|Loop"])
        impulse = self.sample("impulse.wav", ["Drums|Snare|Rim", "Type|Impulse Response"])
        role = self.sample("kick.wav", ["Type|One Shot"])
        records = {record["source"]: record for record in self.run_sorter().preview_records}
        self.assertIsNone(records[loop]["tag_suggestion"]["destination"])
        self.assertIsNone(records[impulse]["tag_suggestion"]["destination"])
        self.assertIn("impulse-response", records[impulse]["tag_suggestion"]["status"])
        self.assertIn("role only", records[role]["tag_suggestion"]["status"])
        plan, stats = xo_filter.build_plan(self.source, use_live_tags=True)
        self.assertEqual({"Kicks": [role]}, plan)
        self.assertEqual(1, stats["loops_skipped"])
        self.assertEqual(0, stats["manual_conflicts"])
        self.assertIn("Type|Loop", next(item for item in stats["evidence"] if item["path"] == loop)["assignments"])

    def test_filename_rule_fallback_cannot_bypass_manual_loop_or_conflicting_type(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        for index in range(5):
            self.sample(f"snare Quasar {index}.wav", ["Drums|Kick", "Type|Loop"], catch_all)
        self.assertEqual([], rule_suggester.suggest_rules(self.source, min_files=5))

    def test_partial_manual_disagreement_prevents_filename_only_candidate(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        for index in range(5):
            self.sample(f"rain {index}.wav", folder=catch_all)
        self.sample("rain conflicting.wav", ["Drums|Kick", "Drums|Snare"], catch_all)
        self.assertNotIn("rain", {item["token"] for item in rule_suggester.suggest_rules(self.source, min_files=5)})

    def test_non_audio_tags_never_propose_audio_one_shot_destinations(self):
        rack = self.sample("mystery.adg", ["Drums|Snare|Rim"])
        records = {record["source"]: record for record in self.run_sorter().preview_records}
        self.assertIsNone(records[rack]["tag_suggestion"])
        hints = tag_evidence.describe_library_evidence(rack, self.source, ["Drums|Snare|Rim"], None, None)
        self.assertIn("Non-audio item", hints)
        self.assertNotIn("Suggested folder:", hints)

    def test_xo_folder_suggestions_honor_opted_in_manual_types_roles_and_errors(self):
        for index in range(5):
            self.sample(f"Quasar {index}.wav", ["Drums|Snare|Rim"])
            self.sample(f"Nebula {index}.wav", ["Drums|Kick", "Drums|Snare"])
            self.sample(f"Impulse {index}.wav", ["Type|Impulse Response"])
            self.sample(f"Orbit {index}.wav", ["Type|Loop"])
            self.sample(f"Mystery {index}.wav")
        default = {item["word"] for item in xo_filter.suggest_types(self.source, min_files=5)}
        self.assertIn("quasar", default)
        suggestions = xo_filter.suggest_types(
            self.source, min_files=5, use_live_tags=True, include_loops=False
        )
        self.assertFalse({"quasar", "nebula", "impulse", "orbit"} & {item["word"] for item in suggestions})
        from pathlib import Path
        next(Path(self.source, "Ableton Folder Info").glob("*.xmp")).write_bytes(b"<broken")
        with self.assertRaisesRegex(ValueError, "Invalid Ableton"):
            xo_filter.suggest_types(self.source, min_files=5, use_live_tags=True)

    def test_preview_reads_unindexed_sidecars_by_path_and_does_not_change_routing(self):
        first = self.sample("mystery.wav", ["Sounds|Drums|Snare", "Character|Warm"])
        other = self.sample("mystery.wav", ["Sounds|Kick"], os.path.join(self.source, "Other"))
        sorter = self.run_sorter()
        self.assertEqual([], sorter.operation_errors)
        records = {record["source"]: record for record in sorter.preview_records}
        self.assertEqual("Snares", records[first]["tag_suggestion"]["sound_type"])
        self.assertEqual("Kicks", records[other]["tag_suggestion"]["sound_type"])
        self.assertEqual("live_manual", records[first]["tag_suggestion"]["source"])
        self.assertTrue(records[first]["tag_suggestion"]["destination"].endswith("Snares"))
        self.assertTrue(records[first]["destination"].endswith("Other One-Shots"))
        self.assertEqual("audio_fallback", records[first]["reason"])
        self.assertIn("routing plan is unchanged", tag_evidence.describe_preview_evidence(records[first]))
        self.assertTrue(os.path.isfile(first))
        self.assertFalse(os.path.exists(self.destination))

    def test_conflicts_and_explicit_routing_are_explained_without_overriding(self):
        conflict = self.sample("kick.wav", ["Sounds|Snare"])
        ambiguous = self.sample("unknown.wav", ["Sounds|Kick", "Sounds|Snare"])
        routed = self.sample("override.wav", ["Sounds|Snare"])
        sorter_engine.index_asset(routed, self.source, "test", 1, ["type:loop"])
        records = {record["source"]: record for record in self.run_sorter().preview_records}
        self.assertEqual("filename_rule", records[conflict]["reason"])
        self.assertIn("conflicts with existing", records[conflict]["tag_suggestion"]["status"])
        self.assertIsNone(records[ambiguous]["tag_suggestion"]["destination"])
        self.assertIn("conflicting manual sound types", records[ambiguous]["tag_suggestion"]["status"])
        self.assertEqual("routing_tag", records[routed]["reason"])
        self.assertEqual("explicit routing retained", records[routed]["tag_suggestion"]["status"])

    def test_real_copy_keeps_old_classification_until_rule_approved_and_preserves_tags(self):
        source = self.sample("mystery.wav", ["Sounds|Snare"])
        sorter = self.run_sorter(preview=False)
        self.assertEqual([], sorter.operation_errors)
        copied = os.path.join(self.destination, "Samples", "One-Shots", "Other One-Shots", "mystery.wav")
        self.assertTrue(os.path.isfile(copied))
        self.assertEqual(["Sounds|Snare"], ableton_tags.sample_tags(copied))
        self.assertEqual(["Sounds|Snare"], ableton_tags.sample_tags(source))

    def test_malformed_sidecars_report_abort_and_complete_instead_of_guessing(self):
        self.sample("mystery.wav", ["Sounds|Snare"])
        from pathlib import Path
        next(Path(self.source, "Ableton Folder Info").glob("*.xmp")).write_bytes(b"<broken")
        sorter = self.run_sorter()
        self.assertEqual([], sorter.preview_records)
        self.assertEqual("read_manual_live_tags", sorter.operation_errors[0]["operation"])
        self.assertFalse(os.path.exists(self.destination))

    def test_manual_evidence_can_propose_new_filename_word_without_auto_approval(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        for index in range(6):
            self.sample(f"Quasar {index}.wav", ["Sounds|Snare"], catch_all)
        suggestions = rule_suggester.suggest_rules(self.source, min_files=5)
        candidate = next(item for item in suggestions if item["token"] == "quasar")
        self.assertEqual("Snares", candidate["target"])
        self.assertEqual(6, candidate["count"])
        self.assertEqual("live_manual", candidate["evidence_source"])
        self.assertEqual(["Sounds|Snare"], candidate["evidence_tags"])
        with mock.patch.object(sorter_engine, "load_external_config"):
            rule_suggester.add_suggestions_as_candidates([candidate])
        import json
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)["LEARNED_RULE_CANDIDATES"][0]
        self.assertEqual("pending", saved["status"])
        self.assertEqual(["Sounds|Snare"], saved["evidence_tags"])
        self.assertNotIn(candidate["pattern"], sorter_engine.DRUM_KEYWORDS)

    def test_mixed_unknown_character_and_conflicting_assignments_do_not_validate_rule(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        for index in range(6):
            self.sample(f"Quasar {index}.wav", ["Sounds|Snare"], catch_all)
        self.sample("Quasar mixed.wav", ["Sounds|Kick", "Sounds|Snare"], catch_all)
        self.assertFalse(any(item["token"] == "quasar" for item in rule_suggester.suggest_rules(self.source, min_files=5)))
        for index in range(6):
            self.sample(f"Nebula {index}.wav", ["Character|Kick"], catch_all)
        self.assertFalse(any(item["token"] == "nebula" for item in rule_suggester.suggest_rules(self.source, min_files=5)))

    def test_existing_catch_all_no_move_still_exposes_evidence(self):
        self.source = self.destination
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        source = self.sample("mystery.wav", ["Sounds|Snare"], catch_all)
        records = self.run_sorter().preview_records
        self.assertEqual(1, len(records))
        self.assertEqual(os.path.dirname(source), records[0]["destination"])
        self.assertTrue(records[0]["tag_suggestion"]["destination"].endswith("Snares"))

    def test_fresh_sidecars_not_stale_cache_supply_evidence(self):
        path = self.sample("unknown.wav", ["Character|Warm"])
        sorter_engine.index_asset(path, self.source, "test", 1, [])
        with closing(sorter_engine._asset_index_connection()) as connection:
            connection.execute(
                "INSERT INTO asset_tags(asset_path, tag, enabled, source) VALUES (?, ?, 1, 'ableton')",
                (path, "ableton:Sounds|Kick")
            )
            connection.commit()
        self.assertIsNone(self.run_sorter().preview_records[0]["tag_suggestion"])

    def test_exact_thresholds_count_untagged_samples_against_share(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        for index in range(19):
            self.sample(f"Quasar {index}.wav", ["Sounds|Snare"], catch_all)
        self.assertEqual([], rule_suggester.suggest_rules(self.source))
        self.sample("Quasar 19.wav", ["Sounds|Snare"], catch_all)
        self.assertEqual(20, rule_suggester.suggest_rules(self.source)[0]["count"])
        for index in range(20, 27):
            self.sample(f"Quasar {index}.wav", ["Sounds|Snare"], catch_all)
        for index in range(27, 30):
            self.sample(f"Quasar {index}.wav", (), catch_all)
        candidate = rule_suggester.suggest_rules(self.source)[0]
        self.assertEqual((27, 30), (candidate["count"], candidate["evidence_total"]))
        self.assertEqual((20, 0.9), (candidate["min_files"], candidate["min_share"]))
        self.sample("Quasar 30.wav", (), catch_all)
        self.assertEqual([], rule_suggester.suggest_rules(self.source))

    def test_manual_learning_excludes_filename_loops_and_explicit_overrides(self):
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        for index in range(6):
            self.sample(f"Quasar Loop {index}.wav", ["Sounds|Snare"], catch_all)
            path = self.sample(f"Nebula {index}.wav", ["Sounds|Snare"], catch_all)
            sorter_engine.index_asset(path, catch_all, "test", 1, ["type:loop"])
            self.sample(f"Supernova {index}.wav", ["Sounds|Snare", "Sounds|Loop"], catch_all)
        self.assertEqual([], rule_suggester.suggest_rules(self.source, min_files=5))

    def test_manual_loop_role_does_not_propose_one_shot_destination(self):
        source = self.sample("mystery.wav", ["Sounds|Snare", "Sounds|Loop"])
        record = self.run_sorter().preview_records[0]
        self.assertEqual(source, record["source"])
        self.assertEqual("audio_fallback", record["reason"])
        self.assertIsNone(record["tag_suggestion"]["destination"])
        self.assertIn("manual loop assignment conflicts", record["tag_suggestion"]["status"])
        self.assertEqual(["Sounds|Loop", "Sounds|Snare"], record["tag_suggestion"]["assignments"])

    def test_xo_manual_mode_is_opt_in_exact_path_and_conflict_aware(self):
        tagged = self.sample("kick.wav", ["Sounds|Snare"])
        neighbor = self.sample("kick.wav", ["Character|Warm"], os.path.join(self.source, "Other"))
        conflict = self.sample("ambiguous.wav", ["Sounds|Kick", "Sounds|Snare"])
        before, _ = xo_filter.build_plan(self.source)
        self.assertIn(tagged, before["Kicks"])
        self.assertNotIn("Snares", before)
        plan, stats = xo_filter.build_plan(self.source, use_live_tags=True)
        self.assertEqual([tagged], plan["Snares"])
        self.assertEqual([neighbor], plan["Kicks"])
        self.assertNotIn(conflict, [path for paths in plan.values() for path in paths])
        self.assertEqual(1, stats["manual_conflicts"])
        evidence = next(item for item in stats["evidence"] if item["path"] == tagged)
        self.assertEqual(["Sounds|Snare"], evidence["assignments"])
        self.assertIn("overrides keyword type Kicks", evidence["status"])
        self.assertEqual([], sorter_engine.LEARNED_RULE_CANDIDATES)
        output = os.path.join(self.root, "xo-output")
        result = xo_filter.build_folder(plan, output, self.source)
        self.assertEqual(0, result["failed"])
        self.assertTrue(os.path.isfile(os.path.join(output, "Snares", "kick.wav")))
        self.assertEqual(["Sounds|Snare"], ableton_tags.sample_tags(tagged))

    def test_xo_manual_loop_filter_local_override_and_selected_types(self):
        loop = self.sample("unknown.wav", ["Sounds|Snare", "Sounds|Loop"])
        override = self.sample("kick.wav", ["Sounds|Snare"])
        sorter_engine.index_asset(override, self.source, "test", 1, ["type:one-shot"])
        plan, stats = xo_filter.build_plan(self.source, use_live_tags=True)
        self.assertEqual(1, stats["loops_skipped"])
        self.assertEqual([override], plan["Kicks"])
        included, _ = xo_filter.build_plan(
            self.source, use_live_tags=True, include_loops=True, selected_types={"Snares"}
        )
        self.assertEqual({"Snares": [loop]}, included)

    def test_xo_loop_role_only_is_explained_without_ambiguity_or_type_invention(self):
        source = self.sample("kick.wav", ["Sounds|Loop", "Character|Warm"])
        plan, stats = xo_filter.build_plan(self.source, use_live_tags=True)
        self.assertEqual({}, plan)
        self.assertEqual(1, stats["loops_skipped"])
        self.assertEqual(0, stats["manual_conflicts"])
        self.assertEqual(["Sounds|Loop"], stats["evidence"][0]["assignments"])
        included, _ = xo_filter.build_plan(self.source, use_live_tags=True, include_loops=True)
        self.assertEqual({"Kicks": [source]}, included)

    def test_xo_rereads_external_metadata_and_surfaces_invalid_sidecars(self):
        source = self.sample("unknown.wav", ["Sounds|Snare"])
        self.assertEqual([source], xo_filter.build_plan(self.source, use_live_tags=True)[0]["Snares"])
        ableton_tags.prepare_edit([source], "Sounds|Snare", replacement="Sounds|Kick").commit()
        self.assertEqual([source], xo_filter.build_plan(self.source, use_live_tags=True)[0]["Kicks"])
        from pathlib import Path
        next(Path(self.source, "Ableton Folder Info").glob("*.xmp")).write_bytes(b"<broken")
        with self.assertRaisesRegex(ValueError, "Invalid Ableton"):
            xo_filter.build_plan(self.source, use_live_tags=True)
        # Existing keyword-only behavior does not depend on sidecar readability.
        self.assertEqual({}, xo_filter.build_plan(self.source)[0])

    def test_approved_manual_rule_preview_move_and_undo_preserve_assignments(self):
        self.source = self.destination
        catch_all = os.path.join(self.source, "Samples", "One-Shots", "Other One-Shots")
        paths = [self.sample(f"Quasar {index}.wav", ["Sounds|Snare"], catch_all) for index in range(20)]
        candidate = rule_suggester.suggest_rules(self.source, min_files=5)[0]

        def reload_test_rules():
            with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
                data = json.load(handle)
            sorter_engine.DRUM_KEYWORDS = data.get("DRUM_KEYWORDS", sorter_engine.DRUM_KEYWORDS)
            sorter_engine.RULE_METADATA = data.get("RULE_METADATA", sorter_engine.RULE_METADATA)
            sorter_engine.LEARNED_RULE_CANDIDATES = data["LEARNED_RULE_CANDIDATES"]

        with mock.patch.object(sorter_engine, "load_external_config", side_effect=reload_test_rules):
            rule_suggester.add_suggestions_as_candidates([candidate])
            self.assertEqual("pending", sorter_engine.LEARNED_RULE_CANDIDATES[0]["status"])
            sorter_engine.review_learning_candidate("quasar", "Snares", "approved")
            self.assertEqual(["Sounds|Snare"], sorter_engine.LEARNED_RULE_CANDIDATES[0]["evidence_tags"])
        preview = self.run_sorter()
        self.assertEqual(20, len(preview.preview_records))
        self.assertTrue(all(record["reason"] == "filename_rule" for record in preview.preview_records))
        self.assertTrue(all(record["tag_suggestion"]["status"] == "supports existing classification"
                            for record in preview.preview_records))
        moved = self.run_sorter(preview=False, copy_mode=False)
        self.assertEqual([], moved.operation_errors)
        for record in preview.preview_records:
            destination = os.path.join(record["destination"], record["filename"])
            self.assertTrue(os.path.isfile(destination))
            self.assertEqual(["Sounds|Snare"], ableton_tags.sample_tags(destination))
        result = sorter_engine.undo_move_log(moved.move_log_path)
        self.assertEqual(20, result["restored"])
        for path in paths:
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(["Sounds|Snare"], ableton_tags.sample_tags(path))

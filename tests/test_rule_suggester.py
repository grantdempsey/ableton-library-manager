import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import rule_suggester
import sorter_engine


class _Window:
    def after(self, _delay, callback):
        callback()


class RuleSuggesterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._config = sorter_engine.CONFIG_FILE
        self._index = sorter_engine.ASSET_INDEX_FILE
        sorter_engine.CONFIG_FILE = os.path.join(self.tmp, "cfg.json")
        sorter_engine.ASSET_INDEX_FILE = os.path.join(self.tmp, "idx.db")
        sorter_engine.load_external_config()
        self.addCleanup(self._restore)
        self.lib = os.path.join(self.tmp, "lib")
        self.catch_all = os.path.join(self.lib, "Samples", "One-Shots", "Other One-Shots")
        os.makedirs(self.catch_all)

    def _restore(self):
        sorter_engine.CONFIG_FILE = self._config
        sorter_engine.ASSET_INDEX_FILE = self._index
        sorter_engine.load_external_config()

    def _files(self, names, folder=None):
        for name in names:
            with open(os.path.join(folder or self.catch_all, name), "wb") as handle:
                handle.write(b"x")

    def test_suggests_reliable_word_with_new_folder(self):
        self._files([f"Pack - Rain {i}.wav" for i in range(20)])
        suggestions = rule_suggester.suggest_rules(self.lib)
        rain = [s for s in suggestions if s["token"] == "rain"]
        self.assertEqual(len(rain), 1)
        self.assertEqual(rain[0]["target"], "Nature")
        self.assertTrue(rain[0]["is_new_folder"])
        self.assertEqual(20, rain[0]["count"])
        self.assertEqual(20, rain[0]["min_files"])
        self.assertEqual(0.9, rain[0]["min_share"])

    def test_default_requires_twenty_files_and_explicit_lower_threshold_is_preserved(self):
        self._files([f"Pack - Rain {i}.wav" for i in range(19)])
        self.assertEqual([], rule_suggester.suggest_rules(self.lib))
        suggestions = rule_suggester.suggest_rules(self.lib, min_files=5)
        self.assertEqual(19, suggestions[0]["count"])
        self.assertEqual(5, suggestions[0]["min_files"])
        with self.assertRaisesRegex(ValueError, "no longer supported"):
            rule_suggester.revalidate_candidates([
                dict(suggestions[0], evidence_source="filename_vocabulary")
            ])
        self._files(["Pack - Rain 19.wav"])
        refreshed = rule_suggester.revalidate_candidates([
            dict(suggestions[0], evidence_source="filename_vocabulary")
        ])
        self.assertEqual(20, refreshed[0]["min_files"])

    def test_filename_evidence_requires_twenty_supporters_not_just_observations(self):
        self._files([f"Rain {index}.wav" for index in range(19)])
        self._files([f"Rain conflict {index}.wav" for index in range(2)])
        def classify(path, _root):
            return ("Snares" if "conflict" in path else "Nature", None)
        with mock.patch("xo_filter.classify", side_effect=classify):
            self.assertEqual([], rule_suggester.suggest_rules(self.lib))
            self._files(["Rain 19.wav"])
            suggestions = rule_suggester.suggest_rules(self.lib)
            self.assertEqual(20, suggestions[0]["count"])
            self._files(["Rain conflict 2.wav"])
            self.assertEqual([], rule_suggester.suggest_rules(self.lib))

    def test_ignores_rare_words_and_words_existing_rules_cover(self):
        self._files(["Pack - Rain 1.wav", "Pack - Rain 2.wav"] + [f"Kick {i}.wav" for i in range(8)])
        tokens = {s["token"] for s in rule_suggester.suggest_rules(self.lib)}
        self.assertNotIn("rain", tokens)
        self.assertNotIn("kick", tokens)

    def test_priority_preview_matches_actual_placement(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(20)])
        rule_suggester.add_suggestions_as_candidates(rule_suggester.suggest_rules(self.lib))
        preview = sorter_engine.suggest_rule_priority(r"\bdjembe\w*\b", "Percussion")
        sorter_engine.review_learning_candidate("djembe", "Percussion", "approved")
        ordered = sorter_engine._ordered_rule_patterns(
            {"DRUM_KEYWORDS": sorter_engine.DRUM_KEYWORDS, "RULE_METADATA": sorter_engine.RULE_METADATA})
        self.assertEqual(ordered.index(r"\bdjembe\w*\b") + 1, preview["position"])

    def test_custom_xo_type_and_learned_suggestions(self):
        import xo_filter
        self.addCleanup(xo_filter.apply_custom_types)
        xo_filter.save_custom_types({"Melodies": ["melody"], "Kicks": ["thump"]})
        self.assertEqual(xo_filter.classify(os.path.join(self.lib, "Pack - Melody 1.wav"), self.lib)[0], "Melodies")
        self.assertEqual(xo_filter.classify(os.path.join(self.lib, "Big Thump.wav"), self.lib)[0], "Kicks")
        xo_filter.save_custom_types({})
        self.assertIsNone(xo_filter.classify(os.path.join(self.lib, "Pack - Melody 1.wav"), self.lib)[0])
        self._files([f"Zzyx Pack - Quasar {i}.wav" for i in range(30)] + [f"Other Thing {i}.wav" for i in range(40)])
        words = [s["word"] for s in xo_filter.suggest_types(self.lib)]
        self.assertIn("quasar", words)

    def test_deleted_rule_can_be_suggested_again(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(20)])
        rule_suggester.add_suggestions_as_candidates(rule_suggester.suggest_rules(self.lib))
        sorter_engine.review_learning_candidate("djembe", "Percussion", "approved")
        self.assertEqual(rule_suggester.suggest_rules(self.lib), [])
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        data["DRUM_KEYWORDS"].pop(r"\bdjembe\w*\b")
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
        again = rule_suggester.suggest_rules(self.lib)
        self.assertEqual(rule_suggester.add_suggestions_as_candidates(again), 1)

    def test_candidates_are_stored_once_as_pending(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(20)])
        suggestions = rule_suggester.suggest_rules(self.lib)
        self.assertEqual(rule_suggester.add_suggestions_as_candidates(suggestions), 1)
        self.assertEqual(rule_suggester.add_suggestions_as_candidates(suggestions), 0)
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(saved["LEARNED_RULE_CANDIDATES"][0]["status"], "pending")

    def test_approved_rule_moves_catch_all_files_on_organize(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(20)])
        suggestions = rule_suggester.suggest_rules(self.lib)
        rule_suggester.add_suggestions_as_candidates(suggestions)
        sorter_engine.review_learning_candidate("djembe", "Percussion", "approved")
        done = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            self.lib, self.lib, _Window(), lambda _m: None,
            lambda *_: done.set(), copy_mode=False)
        sorter.start_parallel_sort()
        self.assertTrue(done.wait(10))
        moved = os.path.join(self.lib, "Percussion", "Shakers")
        self.assertTrue(os.path.isdir(moved) and len(os.listdir(moved)) == 20)
    def test_loop_layout_applies_to_new_and_existing_loops(self):
        loops = os.path.join(self.lib, "Samples", "Loops", "100-114 BPM", "AMIN")
        custom = os.path.join(self.lib, "Samples", "Loops", "My Favorites")
        os.makedirs(loops)
        os.makedirs(custom)
        self._files(["Dark Loop 105 BPM Amin.wav"], folder=loops)
        self._files(["Keeper Loop 105 BPM Amin.wav"], folder=custom)
        self._files(["Fresh Loop 120 BPM Cmaj.wav"], folder=self.catch_all)
        sorter_engine.LOOP_LAYOUT = ["key", "bpm"]
        self.addCleanup(lambda: setattr(sorter_engine, "LOOP_LAYOUT", ["bpm", "key"]))
        done = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            self.lib, self.lib, _Window(), lambda _m: None,
            lambda *_: done.set(), copy_mode=False)
        sorter.start_parallel_sort()
        self.assertTrue(done.wait(10))
        base = os.path.join(self.lib, "Samples", "Loops")
        self.assertTrue(os.path.exists(os.path.join(base, "AMIN", "100-114 BPM", "Dark Loop 105 BPM Amin.wav")))
        self.assertTrue(os.path.exists(os.path.join(base, "CMAJ", "115-129 BPM", "Fresh Loop 120 BPM Cmaj.wav")))
        self.assertTrue(os.path.exists(os.path.join(custom, "Keeper Loop 105 BPM Amin.wav")))

    def test_recommended_layout_puts_fewest_folders_first_and_skips_sparse_levels(self):
        self._files([f"Loop {90 + i} BPM {k}.wav" for i, k in enumerate(["A Min", "C Maj", "D Min", "F Maj"] * 3)])
        result = sorter_engine.recommend_loop_layout(self.lib)
        self.assertEqual(result["layout"], ["bpm", "key"])
        self._files([f"Groove {i} loop {95 + i} bpm.wav" for i in range(30)], folder=self.catch_all)
        result = sorter_engine.recommend_loop_layout(self.lib)
        self.assertEqual(result["layout"], ["bpm"])

    def test_invalid_loop_layout_is_rejected(self):
        with self.assertRaises(ValueError):
            sorter_engine._validate_config({"LOOP_LAYOUT": ["bpm", "bpm"]})
        with self.assertRaises(ValueError):
            sorter_engine._validate_config({"LOOP_LAYOUT": ["pack"]})


if __name__ == "__main__":
    unittest.main()

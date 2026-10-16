import json
import os
import tempfile
import threading
import unittest

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
        self._files([f"Pack - Rain {i}.wav" for i in range(6)])
        suggestions = rule_suggester.suggest_rules(self.lib)
        rain = [s for s in suggestions if s["token"] == "rain"]
        self.assertEqual(len(rain), 1)
        self.assertEqual(rain[0]["target"], "Nature")
        self.assertTrue(rain[0]["is_new_folder"])

    def test_ignores_rare_words_and_words_existing_rules_cover(self):
        self._files(["Pack - Rain 1.wav", "Pack - Rain 2.wav"] + [f"Kick {i}.wav" for i in range(8)])
        tokens = {s["token"] for s in rule_suggester.suggest_rules(self.lib)}
        self.assertNotIn("rain", tokens)
        self.assertNotIn("kick", tokens)

    def test_priority_preview_matches_actual_placement(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(6)])
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

    def test_candidates_are_stored_once_as_pending(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(6)])
        suggestions = rule_suggester.suggest_rules(self.lib)
        self.assertEqual(rule_suggester.add_suggestions_as_candidates(suggestions), 1)
        self.assertEqual(rule_suggester.add_suggestions_as_candidates(suggestions), 0)
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(saved["LEARNED_RULE_CANDIDATES"][0]["status"], "pending")

    def test_approved_rule_moves_catch_all_files_on_organize(self):
        self._files([f"Pack - Djembe {i}.wav" for i in range(6)])
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
        self.assertTrue(os.path.isdir(moved) and len(os.listdir(moved)) == 6)


if __name__ == "__main__":
    unittest.main()

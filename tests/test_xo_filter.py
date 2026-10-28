import os
import tempfile
import unittest

import xo_filter


class XoFilterTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()

    def _make(self, rel, data=b"x"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def test_classifies_by_filename_and_folder(self):
        cases = {
            "Samples/Pack - Rain Medium 3.wav": "Nature",
            "Samples/Pack - Ad Lib Down.wav": "Vocals",
            "Samples/Pack - Hi Hat 02.wav": "Hi-Hats",
            "Samples/Kicks/Heavy 01.wav": "Kicks",
            "Samples/Pack - Foley Scissors.wav": "Foley",
            "Samples/Pack - Cabasa 4.wav": "Percussion",
        }
        for rel, expected in cases.items():
            kind, _ = xo_filter.classify(os.path.join(self.root, rel), self.root)
            self.assertEqual(kind, expected, rel)

    def test_unknown_sample_has_no_app_tag_override_input(self):
        path = os.path.join(self.root, "Samples", "mystery 1.wav")
        kind, _ = xo_filter.classify(path, self.root)
        self.assertIsNone(kind)

    def test_loops_and_unknown_are_skipped_by_default(self):
        self._make("Loops/Drum Loop 1.wav")
        self._make("Samples/zzzz 1.wav")
        plan, stats = xo_filter.build_plan(self.root)
        self.assertEqual(plan, {})
        self.assertEqual(stats["loops_skipped"], 1)
        self.assertEqual(stats["unclassified"], 1)

    def test_build_folder_links_and_is_rerunnable(self):
        kick = self._make("Samples/Pack - Kick 1.wav", b"kickdata")
        self._make("Other/Pack - Kick 1.wav", b"different")
        plan, _ = xo_filter.build_plan(self.root)
        dest = tempfile.mkdtemp()
        first = xo_filter.build_folder(plan, dest, self.root)
        self.assertEqual(first["failed"], 0)
        self.assertEqual(first["linked"] + first["copied"], 2)
        self.assertEqual(len(os.listdir(os.path.join(dest, "Kicks"))), 2)
        second = xo_filter.build_folder(plan, dest, self.root)
        self.assertEqual(second["existing"], 2)
        self.assertTrue(os.path.exists(kick))

    def test_refuses_library_as_destination(self):
        with self.assertRaises(ValueError):
            xo_filter.build_folder({}, self.root, self.root)


if __name__ == "__main__":
    unittest.main()

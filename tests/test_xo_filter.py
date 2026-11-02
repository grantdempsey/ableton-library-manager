import os
import tempfile
import unittest
from unittest import mock

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

    def test_refuses_destinations_that_overlap_the_library(self):
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            xo_filter.build_folder({}, os.path.join(self.root, "XO"), self.root)
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            xo_filter.build_folder({}, os.path.dirname(self.root), self.root)

    def test_custom_folder_names_cannot_escape_destination(self):
        source = self._make("Samples/Kick.wav")
        destination = tempfile.mkdtemp()
        with self.assertRaisesRegex(ValueError, "Invalid XO filter folder name"):
            xo_filter.build_folder({"../outside": [source]}, destination, self.root)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(destination), "outside")))

    def test_custom_folder_configuration_requires_valid_shape(self):
        for custom_types in (
            [],
            {"Custom": "kick"},
            {"Custom": ["kick", 1]},
        ):
            with self.subTest(custom_types=custom_types):
                with self.assertRaisesRegex(ValueError, "XO_CUSTOM_TYPES"):
                    xo_filter.sorter_engine._validate_config({"XO_CUSTOM_TYPES": custom_types})

    def test_custom_folder_names_reject_platform_collisions_before_saving(self):
        config = os.path.join(self.root, "profile.json")
        with mock.patch.object(xo_filter.sorter_engine, "CONFIG_FILE", config):
            with self.assertRaisesRegex(ValueError, "letter case"):
                xo_filter.save_custom_types({"Kicks": ["kick"], "kicks": ["thump"]})
            with self.assertRaisesRegex(ValueError, "Invalid XO filter folder name"):
                xo_filter.save_custom_types({"CONIN$": ["kick"]})
        self.assertFalse(os.path.exists(config))

    def test_custom_keywords_are_case_insensitive(self):
        with mock.patch.object(xo_filter, "load_custom_types", return_value={"My Kicks": ["HeavyKick"]}):
            xo_filter.apply_custom_types()
            self.assertEqual(
                "My Kicks",
                xo_filter.classify(os.path.join(self.root, "HeavyKick.wav"), self.root)[0],
            )
        xo_filter.apply_custom_types()

    def test_library_scan_errors_are_not_silently_ignored(self):
        def fail_walk(_root, *, onerror):
            onerror(PermissionError("folder access denied"))
            return iter(())

        with mock.patch.object(xo_filter.os, "walk", side_effect=fail_walk):
            with self.assertRaisesRegex(PermissionError, "folder access denied"):
                xo_filter.build_plan(self.root)
            with self.assertRaisesRegex(PermissionError, "folder access denied"):
                xo_filter.suggest_types(self.root)


if __name__ == "__main__":
    unittest.main()

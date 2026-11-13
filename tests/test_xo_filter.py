import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

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

    def test_rebuild_replaces_categories_and_keeps_library_bytes(self):
        source = self._make("Samples/kick.wav", b"original")
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            first = xo_filter.rebuild_folder({"Old Kicks": [source]}, output, self.root)
            self.assertTrue(first["published"])
            second = xo_filter.rebuild_folder({"Kicks": [source]}, output, self.root)
            self.assertTrue(second["published"])
            self.assertFalse((output / "Old Kicks").exists())
            self.assertEqual(b"original", (output / "Kicks" / "kick.wav").read_bytes())
            self.assertEqual(b"original", Path(source).read_bytes())
            self.assertEqual(["XO"], os.listdir(parent))

    def test_rebuild_failure_and_cancellation_preserve_previous_output(self):
        source = self._make("Samples/kick.wav", b"original")
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            xo_filter.rebuild_folder({"Old": [source]}, output, self.root)
            original = xo_filter._output_snapshot(output)
            for outcome in (
                {"linked": 0, "copied": 0, "existing": 0, "failed": 1,
                 "cancelled": False, "errors": [{"error": "denied"}]},
                {"linked": 0, "copied": 0, "existing": 0, "failed": 0,
                 "cancelled": True, "errors": []},
            ):
                with self.subTest(outcome=outcome), mock.patch.object(
                    xo_filter, "build_folder", return_value=outcome,
                ):
                    result = xo_filter.rebuild_folder({"New": [source]}, output, self.root)
                    self.assertFalse(result["published"])
                self.assertEqual(original, xo_filter._output_snapshot(output))
                self.assertEqual(["XO"], os.listdir(parent))

    def test_rebuild_adoption_requires_confirmation_and_retains_every_old_file(self):
        source = self._make("Samples/kick.wav")
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            output.mkdir()
            (output / "personal.txt").write_bytes(b"keep this")
            with self.assertRaisesRegex(ValueError, "Confirm adoption"):
                xo_filter.rebuild_folder({"Kicks": [source]}, output, self.root)
            reviewed = xo_filter.review_output_destination(output, self.root)
            result = xo_filter.rebuild_folder(
                {"Kicks": [source]}, output, self.root,
                reviewed_destination=reviewed, adopt_existing=True,
            )
            self.assertEqual(b"keep this", (Path(result["retained_backup"]) / "personal.txt").read_bytes())
            self.assertFalse((output / "personal.txt").exists())
            (output / "manual.txt").write_bytes(b"added later")
            with self.assertRaisesRegex(ValueError, "changed outside"):
                xo_filter.rebuild_folder({"Snares": [source]}, output, self.root)
            self.assertEqual(b"added later", (output / "manual.txt").read_bytes())

    def test_rebuild_refuses_destination_change_after_review(self):
        source = self._make("Samples/kick.wav")
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            output.mkdir()
            reviewed = xo_filter.review_output_destination(output, self.root)
            (output / "added.txt").write_bytes(b"external")
            with self.assertRaisesRegex(ValueError, "changed after confirmation"):
                xo_filter.rebuild_folder(
                    {"Kicks": [source]}, output, self.root,
                    reviewed_destination=reviewed, adopt_existing=True,
                )
            self.assertEqual(b"external", (output / "added.txt").read_bytes())

    def test_rebuild_refuses_overlap_standard_folders_and_linked_output(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            xo_filter.review_output_destination(Path(self.root) / "XO", self.root)
        with self.assertRaisesRegex(ValueError, "dedicated"):
            xo_filter.review_output_destination(Path.home(), self.root)
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            output.mkdir()
            link = output / "linked"
            try:
                link.symlink_to(self.root, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"Symlink creation unavailable: {error}")
            with self.assertRaisesRegex(ValueError, "Linked paths"):
                xo_filter.review_output_destination(output, self.root)

    def test_rebuild_publish_failure_rolls_back_previous_output(self):
        source = self._make("Samples/kick.wav")
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            xo_filter.rebuild_folder({"Old": [source]}, output, self.root)
            original = xo_filter._output_snapshot(output)
            rename = Path.rename
            def fail_publish(path, target):
                if path.name.startswith(".alm-xo-build-"):
                    raise OSError("publish denied")
                return rename(path, target)
            with mock.patch.object(Path, "rename", fail_publish):
                with self.assertRaisesRegex(OSError, "publish denied"):
                    xo_filter.rebuild_folder({"New": [source]}, output, self.root)
            self.assertEqual(original, xo_filter._output_snapshot(output))
            self.assertEqual(["XO"], os.listdir(parent))

    def test_rebuild_reports_phases_and_does_not_reread_unchanged_audio_for_each_check(self):
        source = self._make("Samples/kick.wav", b"audio" * 1000)
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            xo_filter.rebuild_folder({"Old": [source]}, output, self.root)
            if not os.path.samefile(source, output / "Old" / "kick.wav"):
                self.skipTest("Hard links unavailable on this filesystem")
            reads, messages = [], []
            original_open = Path.open
            def tracked_open(path, *args, **kwargs):
                if path.suffix == ".wav" and args and args[0] == "rb":
                    reads.append(str(path))
                return original_open(path, *args, **kwargs)
            with mock.patch.object(Path, "open", tracked_open):
                result = xo_filter.rebuild_folder({"New": [source]}, output, self.root, status=messages.append)
            self.assertTrue(result["published"])
            self.assertLessEqual(len(reads), 2)
            for phase in ("Checking previous output", "Creating replacement", "Verifying replacement",
                          "Switching", "Removing previous output"):
                self.assertTrue(any(phase in message for message in messages), phase)

    def test_snapshot_cache_rechecks_modified_file_and_hashing_is_cancellable(self):
        source = Path(self._make("Samples/kick.wav", b"a" * (3 * 1024 * 1024)))
        cache = {}
        first = xo_filter._output_snapshot(Path(self.root), digest_cache=cache)
        original = source.stat()
        source.write_bytes(b"b" * (3 * 1024 * 1024))
        os.utime(source, ns=(original.st_atime_ns, original.st_mtime_ns))
        second = xo_filter._output_snapshot(Path(self.root), digest_cache=cache)
        self.assertNotEqual(first["files"], second["files"])
        messages = []
        with self.assertRaises(xo_filter.BuildCancelled):
            xo_filter._output_snapshot(
                Path(self.root), should_cancel=lambda: any(" MB)" in message for message in messages),
                status=messages.append,
            )
        self.assertEqual(b"b" * (3 * 1024 * 1024), source.read_bytes())

    def test_cancelled_staging_is_discarded_without_hashing_audio_again(self):
        source = self._make("Samples/kick.wav", b"audio")
        with tempfile.TemporaryDirectory() as parent:
            output = Path(parent) / "XO"
            def cancelled_build(plan, staging, *args):
                (staging / "partial.wav").write_bytes(b"a" * (3 * 1024 * 1024))
                return {"linked": 0, "copied": 1, "existing": 0, "failed": 0,
                        "cancelled": True, "errors": []}
            with mock.patch.object(xo_filter, "build_folder", side_effect=cancelled_build), \
                    mock.patch.object(xo_filter, "_output_digest") as digest:
                result = xo_filter.rebuild_folder({"Kicks": [source]}, output, self.root)
            self.assertTrue(result["cancelled"])
            digest.assert_not_called()
            self.assertEqual([], os.listdir(parent))
            self.assertEqual(b"audio", Path(source).read_bytes())

    def test_classifies_by_filename_and_folder(self):
        cases = {
            "Samples/Pack - Rain Medium 3.wav": "Nature",
            "Samples/Pack - Ad Lib Down.wav": "Vocals & Chants",
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

    def test_existing_library_categories_override_filename_keywords(self):
        cases = {
            ("Samples", "One-Shots", "Cymbals & Crashes", "snare kick.wav"): "Cymbals & Crashes",
            ("Samples", "One-Shots", "Vocals & Chants", "bass piano.wav"): "Vocals & Chants",
            ("Samples", "One-Shots", "My Custom Sounds", "mystery.wav"): "My Custom Sounds",
            ("Samples", "One-Shots", "Percussion", "Shakers", "kick.wav"): "Percussion",
            ("samples", "one-shots", "Cinematic & Ambience", "bell.wav"): "Cinematic & Ambience",
        }
        for parts, expected in cases.items():
            with self.subTest(parts=parts):
                path = os.path.join(self.root, *parts)
                self.assertEqual((expected, False), xo_filter.classify(path, self.root))

    def test_uncategorized_audio_still_uses_keywords(self):
        cases = {
            ("Samples", "One-Shots", "Other One-Shots", "kick.wav"): "Kicks",
            ("Samples", "One-Shots", "Other One-Shots", "mystery.wav"): None,
            ("Samples", "One-Shots", "snare.wav"): "Snares",
            ("Incoming", "Samples", "One-Shots", "Foley", "kick.wav"): "Kicks",
        }
        for parts, expected in cases.items():
            with self.subTest(parts=parts):
                self.assertEqual(
                    (expected, False),
                    xo_filter.classify(os.path.join(self.root, *parts), self.root),
                )

    def test_keyword_fallback_uses_library_category_names(self):
        examples = {
            "808.wav": "808 Sub Bass",
            "cymbal.wav": "Cymbals & Crashes",
            "vocal.wav": "Vocals & Chants",
            "guitar.wav": "Guitar",
            "ambience.wav": "Cinematic & Ambience",
            "riser.wav": "Sound FX",
            "lead.wav": "Melodic & Synth One-Shots",
            "pad.wav": "Melodic & Synth One-Shots",
            "pluck.wav": "Melodic & Synth One-Shots",
        }
        expected = {}
        for filename, category in examples.items():
            organized = self._make(os.path.join("Samples", "One-Shots", category, filename))
            fallback = self._make(os.path.join("Samples", "One-Shots", "Other One-Shots", filename))
            expected.setdefault(category, set()).update((organized, fallback))
        plan, _ = xo_filter.build_plan(self.root)
        self.assertEqual(expected, {category: set(files) for category, files in plan.items()})
        selected, _ = xo_filter.build_plan(self.root, selected_types={"808 Sub Bass", "Cymbals & Crashes"})
        self.assertEqual(
            {category: files for category, files in expected.items()
             if category in {"808 Sub Bass", "Cymbals & Crashes"}},
            {category: set(files) for category, files in selected.items()},
        )
        with tempfile.TemporaryDirectory() as output:
            result = xo_filter.build_folder(plan, output, self.root)
            self.assertEqual(0, result["failed"])
            self.assertEqual(set(expected), set(os.listdir(output)))
            for category, sources in expected.items():
                self.assertEqual(len(sources), len(os.listdir(os.path.join(output, category))))

    def test_internal_manual_types_use_the_same_output_categories(self):
        examples = {
            "808.wav": ("Sounds|808", "808 Sub Bass"),
            "cymbal.wav": ("Sounds|Cymbal", "Cymbals & Crashes"),
        }
        expected = {}
        assignments = {}
        for filename, (tag, category) in examples.items():
            source = self._make(os.path.join("Incoming", filename))
            expected[category] = [source]
            assignments[os.path.normcase(os.path.abspath(source))] = [tag]
        with mock.patch.object(xo_filter.ableton_tags, "read_sample_assignments", return_value=assignments):
            plan, stats = xo_filter.build_plan(self.root, use_live_tags=True)
        self.assertEqual(expected, plan)
        self.assertEqual(set(expected), {item["sound_type"] for item in stats["evidence"]})

    def test_preserved_categories_honor_loops_selection_and_build_names(self):
        cymbal = self._make(os.path.join("Samples", "One-Shots", "Cymbals & Crashes", "kick.wav"))
        loop = self._make(os.path.join("Samples", "One-Shots", "Vocals & Chants", "loop.wav"))
        self._make(os.path.join("Samples", "One-Shots", "My Custom Sounds", "unknown.wav"))
        plan, stats = xo_filter.build_plan(self.root, selected_types={"Cymbals & Crashes"})
        self.assertEqual({"Cymbals & Crashes": [cymbal]}, plan)
        self.assertEqual(1, stats["loops_skipped"])
        included, _ = xo_filter.build_plan(
            self.root, include_loops=True, selected_types={"Vocals & Chants"}
        )
        self.assertEqual({"Vocals & Chants": [loop]}, included)
        with tempfile.TemporaryDirectory() as output:
            result = xo_filter.build_folder(plan, output, self.root)
            self.assertEqual(0, result["failed"])
            self.assertEqual(["Cymbals & Crashes"], os.listdir(output))
            self.assertTrue(os.path.isfile(os.path.join(output, "Cymbals & Crashes", "kick.wav")))
        self.assertTrue(os.path.isfile(cymbal))

    def test_preserved_categories_are_not_mined_for_keyword_suggestions(self):
        for index in range(3):
            self._make(os.path.join("Samples", "One-Shots", "My Sounds", f"quasar {index}.wav"))
            self._make(os.path.join("Incoming", f"mystery {index}.wav"))
        suggestions = xo_filter.suggest_types(self.root, min_files=3)
        self.assertNotIn("quasar", {item["word"] for item in suggestions})

    def test_saved_custom_keywords_cannot_override_an_existing_category(self):
        source = self._make(os.path.join("Samples", "One-Shots", "Nature", "quasar.wav"))
        self.addCleanup(xo_filter.apply_custom_types)
        with mock.patch.object(xo_filter, "load_custom_types", return_value={"My FX": ["quasar"]}):
            plan, _ = xo_filter.build_plan(self.root)
            self.assertEqual({"Nature": [source]}, plan)

    def test_scan_preserves_sources_and_does_not_read_live_tags_by_default(self):
        source = self._make(os.path.join("Samples", "One-Shots", "Guitar", "kick.wav"), b"original")
        before = os.stat(source)
        with mock.patch.object(xo_filter.ableton_tags, "read_sample_assignments") as read_tags:
            plan, _ = xo_filter.build_plan(self.root)
        read_tags.assert_not_called()
        self.assertEqual({"Guitar": [source]}, plan)
        self.assertEqual(before.st_mtime_ns, os.stat(source).st_mtime_ns)
        with open(source, "rb") as handle:
            self.assertEqual(b"original", handle.read())

    def test_internal_manual_override_still_explains_preserved_category(self):
        source = self._make(os.path.join("Samples", "One-Shots", "Nature", "kick.wav"))
        assignments = {os.path.normcase(os.path.abspath(source)): ["Sounds|Snare"]}
        with mock.patch.object(xo_filter.ableton_tags, "read_sample_assignments", return_value=assignments):
            plan, stats = xo_filter.build_plan(self.root, use_live_tags=True)
        self.assertEqual({"Snares": [source]}, plan)
        self.assertIn("overrides library category Nature", stats["evidence"][0]["status"])

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

    def test_same_filesystem_uses_device_identity_and_existing_destination_parent(self):
        destination = os.path.join(self.root, "not-created", "XO")
        existing_parent = os.path.join(self.root, "not-created")
        os.makedirs(existing_parent)
        self.assertEqual(os.stat(existing_parent).st_dev, xo_filter._filesystem_device(destination))
        with mock.patch.object(xo_filter, "_filesystem_device", side_effect=[10, 20]):
            self.assertFalse(xo_filter.same_filesystem(self.root, destination))

    def test_filesystem_check_propagates_access_errors(self):
        with mock.patch.object(xo_filter.os, "stat", side_effect=PermissionError("access denied")):
            with self.assertRaisesRegex(PermissionError, "access denied"):
                xo_filter.same_filesystem(self.root, os.path.join(self.root, "XO"))

    def test_cross_filesystem_build_copies_without_attempting_hard_link(self):
        source = self._make("Samples/Pack - Kick 1.wav", b"kickdata")
        destination = tempfile.mkdtemp()
        with mock.patch.object(xo_filter, "same_filesystem", return_value=False), mock.patch.object(
            xo_filter.os, "link"
        ) as link:
            result = xo_filter.build_folder({"Kicks": [source]}, destination, self.root)
        link.assert_not_called()
        self.assertEqual(1, result["copied"])
        self.assertEqual(0, result["linked"])
        target = os.path.join(destination, "Kicks", os.path.basename(source))
        with open(target, "rb") as handle:
            self.assertEqual(b"kickdata", handle.read())

    def test_build_folder_reports_failed_source_destination_and_cause(self):
        source = self._make("Samples/Pack - Kick 1.wav")
        dest = tempfile.mkdtemp()
        with mock.patch("xo_filter.os.link", side_effect=OSError("link denied")), mock.patch(
            "builtins.open", side_effect=PermissionError("write denied")
        ):
            result = xo_filter.build_folder({"Kicks": [source]}, dest, self.root)

        self.assertEqual(1, result["failed"])
        self.assertEqual([{
            "source": source,
            "destination": os.path.join(dest, "Kicks", os.path.basename(source)),
            "error": "write denied",
        }], result["errors"])

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

    def test_unreadable_custom_folder_config_is_reported_without_replacing_active_types(self):
        config = os.path.join(self.root, "profile.json")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write('{"XO_CUSTOM_TYPES":')
        original_error = xo_filter.sorter_engine.XO_CONFIG_LOAD_ERROR
        self.addCleanup(setattr, xo_filter.sorter_engine, "XO_CONFIG_LOAD_ERROR", original_error)
        original_tokens = {key: list(value) for key, value in xo_filter._TOKEN_TYPE.items()}
        with mock.patch.object(xo_filter.sorter_engine, "CONFIG_FILE", config):
            with self.assertRaisesRegex(ValueError, "could not be loaded"):
                xo_filter.apply_custom_types()
            self.assertIn("kick", xo_filter._TOKEN_TYPE)
            self.assertEqual(original_tokens, xo_filter._TOKEN_TYPE)
            self.assertIn(config, xo_filter.sorter_engine.XO_CONFIG_LOAD_ERROR)

    def test_invalid_xo_folder_name_is_not_silently_discarded(self):
        config = os.path.join(self.root, "profile.json")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write('{"XO_CUSTOM_TYPES":{"../Outside":["kick"]}}')
        original_error = xo_filter.sorter_engine.XO_CONFIG_LOAD_ERROR
        self.addCleanup(setattr, xo_filter.sorter_engine, "XO_CONFIG_LOAD_ERROR", original_error)
        with mock.patch.object(xo_filter.sorter_engine, "CONFIG_FILE", config):
            with self.assertRaisesRegex(ValueError, "Invalid XO filter folder name"):
                xo_filter.load_custom_types()
            self.assertIn("is invalid", xo_filter.sorter_engine.XO_CONFIG_LOAD_ERROR)

    def test_build_plan_reports_malformed_xo_configuration(self):
        config = os.path.join(self.root, "profile.json")
        with open(config, "w", encoding="utf-8") as handle:
            handle.write('{"XO_CUSTOM_TYPES":{"../Outside":["kick"]}}')
        with mock.patch.object(xo_filter.sorter_engine, "CONFIG_FILE", config):
            with self.assertRaisesRegex(ValueError, "Invalid XO filter folder name"):
                xo_filter.build_plan(self.root)

    def test_startup_keeps_other_settings_when_xo_configuration_is_malformed(self):
        config = os.path.join(self.root, "profile.json")
        data = xo_filter.sorter_engine._default_config()
        data["XO_CUSTOM_TYPES"] = {"Custom": "not a keyword list"}
        with open(config, "w", encoding="utf-8") as handle:
            xo_filter.json.dump(data, handle)
        with open(config, "rb") as handle:
            original_profile = handle.read()
        for name in (
            "BPM_RANGES", "DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS",
            "IGNORED_DIRECTORIES", "RULE_METADATA", "SMART_LEARNING_ENABLED",
            "LEARNING_COUNTS", "LEARNED_RULE_CANDIDATES", "LOOP_LAYOUT",
            "ACTIVE_LIBRARY_PATH", "CONFIG_LOAD_ERROR", "XO_CONFIG_LOAD_ERROR",
        ):
            self.addCleanup(setattr, xo_filter.sorter_engine, name,
                            getattr(xo_filter.sorter_engine, name))
        with mock.patch.object(xo_filter.sorter_engine, "CONFIG_FILE", config):
            loaded = xo_filter.sorter_engine.load_external_config()
            self.assertNotIn("XO_CUSTOM_TYPES", loaded)
            self.assertEqual(
                xo_filter.sorter_engine._default_config()["ACTIVE_LIBRARY_PATH"],
                loaded["ACTIVE_LIBRARY_PATH"],
            )
            self.assertTrue(xo_filter.sorter_engine.XO_CONFIG_LOAD_ERROR)
            with self.assertRaisesRegex(ValueError, "XO_CUSTOM_TYPES"):
                xo_filter.apply_custom_types()
        with open(config, "rb") as handle:
            self.assertEqual(original_profile, handle.read())

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

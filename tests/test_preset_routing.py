import copy
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

import sorter_engine
import serum_presets


class ImmediateWindow:
    def after(self, _delay, callback):
        callback()


class PresetRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = temporary.name
        self.user_folder = os.path.join("Serum 2 Presets", "Presets", "User")
        for name in (
            "BPM_RANGES", "DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS",
            "IGNORED_DIRECTORIES", "SMART_LEARNING_ENABLED", "LEARNING_COUNTS",
            "LEARNED_RULE_CANDIDATES", "RULE_METADATA", "LOOP_LAYOUT",
        ):
            patcher = mock.patch.object(
                sorter_engine, name, copy.deepcopy(getattr(sorter_engine, name))
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (
            ("CONFIG_FILE", os.path.join(self.root, "config.json")),
            ("ASSET_INDEX_FILE", os.path.join(self.root, "assets.db")),
            ("CONFIG_BACKUP_DIR", os.path.join(self.root, "backups")),
            ("MOVE_LOG_DIR", os.path.join(self.root, "logs")),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        sorter_engine.load_external_config()

    def run_sorter(self, source, destination, *, preview_only=False, copy_mode=False):
        completed = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            source, destination, ImmediateWindow(), lambda _message: None,
            lambda _stats, _mode: completed.set(),
            preview_only=preview_only, copy_mode=copy_mode,
            smart_learning_enabled=False,
        )
        sorter.start_parallel_sort()
        self.assertTrue(completed.wait(5), "sorter did not complete")
        self.assertEqual([], sorter.operation_errors)
        self.assertEqual(0, sorter.stats["Errors/Skipped Files"])
        return sorter

    def test_serum_presets_preview_copy_and_move_to_serum_folder(self):
        source = os.path.join(self.root, "incoming", "Synth Presets")
        destination = os.path.join(self.root, "library")
        os.makedirs(source)
        filenames = (
            "ATYYA_Bousy Flutter.SerumPreset",
            "ATYYA_Burrow.serumpreset",
            "ATYYA_Choppah.SERUMPRESET",
        )
        for filename in filenames:
            with open(os.path.join(source, filename), "wb") as handle:
                handle.write(filename.encode("ascii"))

        preview = self.run_sorter(source, destination, preview_only=True)
        self.assertEqual(len(filenames), len(preview.preview_records))
        for record in preview.preview_records:
            self.assertEqual(os.path.join(destination, self.user_folder, "Unsorted"), record["destination"])
            self.assertEqual("file_extension", record["reason"])
            self.assertEqual(0.90, record["confidence"])
        self.assertFalse(os.path.exists(destination))

        for copy_mode in (True, False):
            with self.subTest(copy_mode=copy_mode):
                target = os.path.join(destination, "copy" if copy_mode else "move")
                sorter = self.run_sorter(source, target, copy_mode=copy_mode)
                self.assertEqual(
                    len(filenames), sorter.stats["Synth Presets & Wavetables (.fxp, .vital)"]
                )
                self.assertEqual(0, sorter.stats["Native Live Racks (.adg, .amxd, .alc, .adv)"])
                for filename in filenames:
                    with open(os.path.join(target, self.user_folder, "Unsorted", filename), "rb") as handle:
                        self.assertEqual(filename.encode("ascii"), handle.read())
                    self.assertEqual(copy_mode, os.path.exists(os.path.join(source, filename)))

    def test_extension_routing_wins_over_flat_and_nested_sound_rules(self):
        source = os.path.join(self.root, "incoming")
        destination = os.path.join(self.root, "library")
        os.makedirs(source)
        cases = {
            "kick.SerumPreset": os.path.join(self.user_folder, "Unsorted"),
            "shaker.SerumPreset": os.path.join(self.user_folder, "Unsorted"),
            "shaker.fxp": os.path.join(self.user_folder, "Unsorted"),
            "shaker.fxb": "Serum Banks",
            "shaker.adg": "Live Instrument Racks",
            "shaker.amxd": "Max For Live Devices",
            "shaker.mid": "Midi",
            "shaker.wav": os.path.join("Samples", "One-Shots", "Percussion", "Shakers"),
        }
        for filename in cases:
            with open(os.path.join(source, filename), "wb") as handle:
                handle.write(b"preset")
        preview = self.run_sorter(source, destination, preview_only=True)
        records = {record["filename"]: record for record in preview.preview_records}
        self.assertEqual(set(cases), set(records))
        for filename, folder in cases.items():
            with self.subTest(filename=filename):
                self.assertEqual(os.path.join(destination, folder), records[filename]["destination"])
                self.assertEqual(
                    "filename_rule" if filename.endswith(".wav") else "file_extension",
                    records[filename]["reason"],
                )
                self.assertEqual(
                    folder.replace(os.sep, "/"),
                    sorter_engine.explain_filename(filename)["destination"],
                )

    def test_missing_serum_default_can_be_restored_without_overwriting_custom_rules(self):
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        data["SYNTH_EXTS"].pop(".serumpreset", None)
        data["SYNTH_EXTS"][".fxp"] = "Custom FXP"
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
        missing = sorter_engine.missing_default_rules()
        self.assertEqual(serum_presets.USER_FOLDER, missing["SYNTH_EXTS"][".serumpreset"])
        self.assertNotIn(".fxp", missing["SYNTH_EXTS"])
        data["SYNTH_EXTS"].update(missing["SYNTH_EXTS"])
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
        self.assertEqual("Custom FXP", sorter_engine.SYNTH_EXTS[".fxp"])
        self.assertEqual(
            serum_presets.USER_FOLDER + "/Unsorted",
            sorter_engine.explain_filename("ATYYA_Currents.SerumPreset")["destination"],
        )

    def test_organize_recovers_misplaced_serum_presets_and_can_undo(self):
        library = os.path.join(self.root, "library")
        misplaced = os.path.join(library, "Live Instrument Racks", "ATYYA_Currents.SerumPreset")
        for folder, filename in (
            ("Live Instrument Racks", "ATYYA_Currents.SerumPreset"),
            ("Live Instrument Racks", "Serum Rack.adg"),
            ("Live Instrument Racks", "Other.fxp"),
            (os.path.join(self.user_folder, "Unsorted"), "Already Sorted.SerumPreset"),
        ):
            directory = os.path.join(library, folder)
            os.makedirs(directory, exist_ok=True)
            with open(os.path.join(directory, filename), "wb") as handle:
                handle.write(filename.encode("ascii"))
        preview = self.run_sorter(library, library, preview_only=True)
        target = os.path.join(library, self.user_folder, "Unsorted")
        self.assertEqual(1, len(preview.preview_records))
        self.assertEqual(misplaced, preview.preview_records[0]["source"])
        self.assertEqual(target, preview.preview_records[0]["destination"])
        self.assertTrue(os.path.exists(misplaced))

        moved = self.run_sorter(library, library)
        destination = os.path.join(target, os.path.basename(misplaced))
        self.assertFalse(os.path.exists(misplaced))
        with open(destination, "rb") as handle:
            self.assertEqual(b"ATYYA_Currents.SerumPreset", handle.read())
        self.assertTrue(os.path.exists(os.path.join(library, "Live Instrument Racks", "Serum Rack.adg")))
        self.assertTrue(os.path.exists(os.path.join(library, "Live Instrument Racks", "Other.fxp")))
        self.assertEqual([], self.run_sorter(library, library, preview_only=True).preview_records)
        undo = sorter_engine.undo_move_log(moved.move_log_path)
        self.assertEqual(1, undo["restored"])
        self.assertEqual([], undo["errors"])
        self.assertTrue(os.path.exists(misplaced))

    def test_recovery_honors_custom_serum_destination(self):
        library = os.path.join(self.root, "library")
        directory = os.path.join(library, "Live Instrument Racks", "Nested")
        os.makedirs(directory)
        filename = "shaker.SERUMPRESET"
        with open(os.path.join(directory, filename), "wb") as handle:
            handle.write(b"preset")
        sorter_engine.SYNTH_EXTS[".serumpreset"] = "Custom Serum"
        preview = self.run_sorter(library, library, preview_only=True)
        self.assertEqual(1, len(preview.preview_records))
        self.assertEqual(
            os.path.join(library, "Custom Serum"), preview.preview_records[0]["destination"]
        )
        self.assertEqual("file_extension", preview.preview_records[0]["reason"])

    def test_loose_presets_migrate_by_prefix_without_touching_serum_resources(self):
        library = os.path.join(self.root, "library")
        loose = os.path.join(library, "Serum Presets")
        os.makedirs(loose)
        resources = os.path.join(library, "Serum 2 Presets")
        protected = (
            os.path.join("Presets", "Factory", "Bass", "BS Factory.SerumPreset"),
            os.path.join("Presets", "User", "Bass", "BS Existing.fxp"),
            os.path.join("Tables", "User", "wavetable.wav"),
            os.path.join("Samples", "User", "kick.wav"),
            os.path.join("LFO Shapes", "User", "shape.lfo"),
        )
        for relative in protected:
            path = os.path.join(resources, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"unchanged")
        empty_resource = os.path.join(resources, "Curves", "User")
        os.makedirs(empty_resource)
        cases = {
            "808 - Alien.fxp": "Bass/808",
            "ARP - Arcade.fxp": "Arp",
            "BS Growl.fxp": "Bass",
            "CH - Chord.fxp": "Chord",
            "FX_Impact.fxp": "SFX",
            "KEYS Piano.fxp": "Keyboard",
            "LD Lead.fxp": "Lead",
            "PD Soft.fxp": "Pad",
            "PL Bright.fxp": "Pluck",
            "SEQ - Pattern.fxp": "Seq",
            "SYN_Saw.fxp": "Synth",
            "ATYYA_Bossy Flutter.SerumPreset": "Unsorted",
            "SAVEJ - BASS PLUCK.SerumPreset": "Unsorted",
            "Plucky Bass.fxp": "Unsorted",
        }
        for filename in cases:
            with open(os.path.join(loose, filename), "wb") as handle:
                handle.write(filename.encode("ascii"))

        preview = self.run_sorter(library, library, preview_only=True)
        records = {record["filename"]: record for record in preview.preview_records}
        self.assertEqual(set(cases), set(records))
        for filename, category in cases.items():
            self.assertEqual(
                os.path.normpath(os.path.join(library, self.user_folder, category)),
                records[filename]["destination"],
            )
        moved = self.run_sorter(library, library)
        for filename, category in cases.items():
            path = os.path.normpath(os.path.join(library, self.user_folder, category, filename))
            with open(path, "rb") as handle:
                self.assertEqual(filename.encode("ascii"), handle.read())
            self.assertFalse(os.path.exists(os.path.join(loose, filename)))
        for relative in protected:
            with open(os.path.join(resources, relative), "rb") as handle:
                self.assertEqual(b"unchanged", handle.read())
        self.assertTrue(os.path.isdir(empty_resource))
        self.assertEqual([], self.run_sorter(library, library, preview_only=True).preview_records)
        undo = sorter_engine.undo_move_log(moved.move_log_path)
        self.assertEqual(len(cases), undo["restored"])
        self.assertEqual([], undo["errors"])

    def test_profile_upgrade_persists_only_legacy_serum_destinations(self):
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        data["SYNTH_EXTS"].update({
            ".fxp": "Custom FXP", ".serumpreset": "Serum Presets", ".vital": "Vital Presets",
        })
        data["custom_setting"] = "preserved"
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            saved = json.load(handle)
        self.assertEqual(serum_presets.USER_FOLDER, saved["SYNTH_EXTS"][".serumpreset"])
        self.assertEqual("Custom FXP", saved["SYNTH_EXTS"][".fxp"])
        self.assertEqual("Serum Banks", saved["SYNTH_EXTS"][".fxb"])
        self.assertEqual("Vital Presets", saved["SYNTH_EXTS"][".vital"])
        self.assertEqual("preserved", saved["custom_setting"])
        self.assertEqual("Custom FXP", sorter_engine.explain_filename("BS Growl.fxp")["destination"])
        with mock.patch.object(sorter_engine, "_write_config") as writer:
            sorter_engine.load_external_config()
        writer.assert_not_called()

    def test_profile_upgrade_failure_does_not_publish_or_change_disk(self):
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        data["SYNTH_EXTS"][".fxp"] = "Serum Presets"
        sorter_engine._write_config(data)
        with open(sorter_engine.CONFIG_FILE, "rb") as handle:
            before = handle.read()
        memory = dict(sorter_engine.SYNTH_EXTS)
        with mock.patch.object(sorter_engine, "_write_config", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                sorter_engine.load_external_config()
        self.assertEqual(memory, sorter_engine.SYNTH_EXTS)
        with open(sorter_engine.CONFIG_FILE, "rb") as handle:
            self.assertEqual(before, handle.read())

    def test_serum_resource_root_is_protected_when_selected_directly(self):
        resources = os.path.join(self.root, "Serum 2 Presets")
        os.makedirs(os.path.join(resources, "Tables", "User"))
        with open(os.path.join(resources, "Tables", "User", "kick.wav"), "wb") as handle:
            handle.write(b"wavetable")
        self.assertEqual(
            [], self.run_sorter(resources, resources, preview_only=True).preview_records
        )

    def test_previously_nested_profile_upgrades_to_flat_resource_root(self):
        with open(sorter_engine.CONFIG_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        data["SYNTH_EXTS"][".serumpreset"] = "Serum Presets/Serum 2 Presets/Presets/User"
        sorter_engine._write_config(data)
        sorter_engine.load_external_config()
        self.assertEqual(
            serum_presets.USER_FOLDER, sorter_engine.SYNTH_EXTS[".serumpreset"]
        )

    def test_nested_resource_root_requires_review_before_any_files_move(self):
        library = os.path.join(self.root, "library")
        os.makedirs(os.path.join(library, "Serum Presets", "Serum 2 Presets"))
        preset = os.path.join(library, "Serum Presets", "BS Growl.fxp")
        with open(preset, "wb") as handle:
            handle.write(b"preset")
        completed = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            library, library, ImmediateWindow(), lambda _message: None,
            lambda _stats, _mode: completed.set(),
        )
        sorter.start_parallel_sort()
        self.assertTrue(completed.wait(5))
        self.assertEqual(1, len(sorter.operation_errors))
        self.assertIn("reviewed relocation", sorter.operation_errors[0]["error"])
        self.assertTrue(os.path.exists(preset))
        self.assertFalse(os.path.exists(os.path.join(library, "Serum 2 Presets")))


if __name__ == "__main__":
    unittest.main()

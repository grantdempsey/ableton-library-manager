import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import sorter_engine
import tab_matrix


class RulesTransactionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / "profile.json"
        for name in (
            "BPM_RANGES", "DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS",
            "IGNORED_DIRECTORIES", "SMART_LEARNING_ENABLED", "LEARNING_COUNTS",
            "LEARNED_RULE_CANDIDATES", "RULE_METADATA", "LOOP_LAYOUT",
        ):
            patcher = mock.patch.object(sorter_engine, name, copy.deepcopy(getattr(sorter_engine, name)))
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in (
            ("CONFIG_FILE", str(self.config)),
            ("CONFIG_BACKUP_DIR", str(self.root / "backups")),
        ):
            patcher = mock.patch.object(sorter_engine, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        data = sorter_engine._default_config()
        data["DRUM_KEYWORDS"] = {"kick": "Kicks"}
        data["XO_CUSTOM_TYPES"] = {"Keep": ["preserved"]}
        data["RULE_METADATA"] = {"kick": {"enabled": True, "priority": 7, "exclude": ["test"]}}
        sorter_engine._write_config(data, create_backup=False)
        sorter_engine.load_external_config()
        self.before = self.config.read_bytes()
        self.memory = self.snapshot()
        self.errors = self.patch(tab_matrix.messagebox, "showerror")
        self.success = self.patch(tab_matrix.messagebox, "showinfo")
        self.refresh = self.patch(tab_matrix, "refresh_matrix_data")
        self.patch(tab_matrix, "_status_label_ref", None)

    def patch(self, owner, name, *args, **kwargs):
        patcher = mock.patch.object(owner, name, *args, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def snapshot(self):
        return copy.deepcopy({
            key: getattr(sorter_engine, key) for key in (
                "DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS",
                "IGNORED_DIRECTORIES", "LOOP_LAYOUT", "RULE_METADATA",
            )
        })

    def import_profile(self, data):
        profile = self.root / "import.json"
        profile.write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.object(tab_matrix.filedialog, "askopenfilename", return_value=str(profile)), mock.patch.object(
            tab_matrix.messagebox, "askyesno", return_value=True
        ):
            tab_matrix.execute_profile_json_import(None)

    def test_import_write_failure_preserves_memory_disk_and_never_reports_success(self):
        with mock.patch.object(sorter_engine.os, "replace", side_effect=OSError("disk full")):
            self.import_profile({
                "DRUM_KEYWORDS": {"new": "New"},
                "SYNTH_EXTS": {".new": "New Presets"},
                "NATIVE_EXTS": {".test": "New Racks"},
                "IGNORED_DIRECTORIES": ["New Skip"],
            })
        self.assertEqual(self.before, self.config.read_bytes())
        self.assertEqual(self.memory, self.snapshot())
        self.errors.assert_called_once()
        self.success.assert_not_called()
        self.refresh.assert_not_called()
        self.assertEqual([], list(self.root.glob(".library-config-*.tmp")))

    def test_import_success_persists_before_publishing_and_preserves_unrelated_data(self):
        writer = sorter_engine._write_config
        def verify_before_publish(data, **kwargs):
            self.assertEqual(self.memory, self.snapshot())
            writer(data, **kwargs)
        with mock.patch.object(sorter_engine, "_write_config", side_effect=verify_before_publish):
            self.import_profile({"DRUM_KEYWORDS": {"new": "New"}, "IGNORED_DIRECTORIES": ["New Skip"]})
        saved = json.loads(self.config.read_text(encoding="utf-8"))
        self.assertEqual({"kick": "Kicks", "new": "New"}, sorter_engine.DRUM_KEYWORDS)
        self.assertEqual(saved["DRUM_KEYWORDS"], sorter_engine.DRUM_KEYWORDS)
        self.assertEqual({"Keep": ["preserved"]}, saved["XO_CUSTOM_TYPES"])
        self.assertEqual(7, saved["RULE_METADATA"]["kick"]["priority"])
        self.assertIn("New Skip", sorter_engine.IGNORED_DIRECTORIES)
        self.success.assert_called_once()
        self.errors.assert_not_called()
        self.refresh.assert_called_once()

    def test_other_staged_rule_actions_leave_state_unchanged_on_failure(self):
        edits = (
            lambda data: data["DRUM_KEYWORDS"].pop("kick"),
            lambda data: data["DRUM_KEYWORDS"].update(kick="Changed"),
            lambda data: data["SYNTH_EXTS"].update({".new": "New"}),
            lambda data: data["NATIVE_EXTS"].clear(),
            lambda data: data.update(LOOP_LAYOUT=["key"]),
            lambda data: data["DRUM_KEYWORDS"].update(default="Default"),
        )
        for edit in edits:
            with self.subTest(edit=edit), mock.patch.object(
                sorter_engine, "_write_config", side_effect=OSError("permission denied")
            ):
                self.assertFalse(tab_matrix._sync_config_state("Saved", edit))
                self.assertEqual(self.memory, self.snapshot())
                self.assertEqual(self.before, self.config.read_bytes())
        self.refresh.assert_not_called()

    def test_invalid_import_never_publishes_or_saves(self):
        for data in (
            {"DRUM_KEYWORDS": {"[": "Invalid expression"}},
            {"DRUM_KEYWORDS": {"valid": 42}},
            {"DRUM_KEYWORDS": []},
            {"SYNTH_EXTS": {".test": "Test"}, "IGNORED_DIRECTORIES": [42]},
        ):
            with self.subTest(data=data):
                self.import_profile(data)
                self.assertEqual(self.memory, self.snapshot())
                self.assertEqual(self.before, self.config.read_bytes())
        self.success.assert_not_called()
        self.refresh.assert_not_called()

    def test_external_change_during_staging_is_not_overwritten(self):
        external = self.before + b"\n"
        def edit(data):
            data["DRUM_KEYWORDS"]["new"] = "New"
            self.config.write_bytes(external)
        self.assertFalse(tab_matrix._sync_config_state("Saved", edit))
        self.assertEqual(external, self.config.read_bytes())
        self.assertEqual(self.memory, self.snapshot())
        self.errors.assert_called_once()

    def test_successful_layout_change_preserves_rule_metadata(self):
        self.assertTrue(tab_matrix._sync_config_state("Layout saved", lambda data: data.update(LOOP_LAYOUT=["key"])))
        self.assertEqual(["key"], sorter_engine.LOOP_LAYOUT)
        self.assertEqual(self.memory["RULE_METADATA"], sorter_engine.RULE_METADATA)
        self.assertEqual(["key"], json.loads(self.config.read_text())["LOOP_LAYOUT"])

    def test_successful_add_change_delete_and_default_restore_publish_saved_rules(self):
        edits = (
            lambda data: data["SYNTH_EXTS"].update({".new": "New"}),
            lambda data: data["DRUM_KEYWORDS"].update(kick="Changed"),
            lambda data: data["DRUM_KEYWORDS"].pop("kick"),
            lambda data: data["DRUM_KEYWORDS"].update(kick="Kicks"),
        )
        for edit in edits:
            with self.subTest(edit=edit):
                self.assertTrue(tab_matrix._sync_config_state("Saved", edit))
                saved = json.loads(self.config.read_text(encoding="utf-8"))
                self.assertEqual(saved["DRUM_KEYWORDS"], sorter_engine.DRUM_KEYWORDS)
                self.assertEqual(saved["SYNTH_EXTS"], sorter_engine.SYNTH_EXTS)
                self.assertEqual({"Keep": ["preserved"]}, saved["XO_CUSTOM_TYPES"])
        self.errors.assert_not_called()


if __name__ == "__main__":
    unittest.main()

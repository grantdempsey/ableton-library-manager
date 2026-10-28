import json
import os
import tempfile
import unittest
from unittest import mock

import sorter_engine


class BackupAndUndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.tmp.name
        self.config = os.path.join(root, "library_config.json")
        patches = [
            mock.patch.object(sorter_engine, "CONFIG_FILE", self.config),
            mock.patch.object(sorter_engine, "CONFIG_BACKUP_DIR", os.path.join(root, "backups")),
            mock.patch.object(sorter_engine, "MOVE_LOG_DIR", os.path.join(root, "logs")),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_backup_skips_identical_and_limits_count(self):
        with open(self.config, "w") as f:
            json.dump({"v": 0}, f)
        sorter_engine.backup_config()
        sorter_engine.backup_config()
        self.assertEqual(len(sorter_engine.list_config_backups()), 1)
        for version in range(1, 15):
            with open(self.config, "w") as f:
                json.dump({"v": version}, f)
            sorter_engine.backup_config()
        self.assertLessEqual(len(sorter_engine.list_config_backups()), sorter_engine.CONFIG_BACKUP_LIMIT)

    def test_missing_default_rules_ignores_style_and_finds_removed(self):
        saved = dict(sorter_engine.DRUM_KEYWORDS)
        saved_synth, saved_native = dict(sorter_engine.SYNTH_EXTS), dict(sorter_engine.NATIVE_EXTS)
        try:
            sorter_engine.DRUM_KEYWORDS.clear()
            sorter_engine.DRUM_KEYWORDS.update({r"\bkick(s)?\b": "Kicks", r"\bsnare(s)?\b": "Snares"})
            sorter_engine.SYNTH_EXTS.clear()
            sorter_engine.NATIVE_EXTS.clear()
            missing = sorter_engine.missing_default_rules()
            folders = set(missing["DRUM_KEYWORDS"].values())
            self.assertNotIn("Kicks", folders)
            self.assertNotIn("Snares", [v for k, v in missing["DRUM_KEYWORDS"].items() if "snare" in k])
            self.assertIn("Claps", folders)
            self.assertIn(".fxp", missing["SYNTH_EXTS"])
        finally:
            for target, original in ((sorter_engine.DRUM_KEYWORDS, saved), (sorter_engine.SYNTH_EXTS, saved_synth),
                                     (sorter_engine.NATIVE_EXTS, saved_native)):
                target.clear()
                target.update(original)

    def test_explain_filename_reports_winner_and_file_types(self):
        saved = (dict(sorter_engine.DRUM_KEYWORDS), dict(sorter_engine.RULE_METADATA), dict(sorter_engine.SYNTH_EXTS))
        try:
            sorter_engine.DRUM_KEYWORDS.clear()
            sorter_engine.DRUM_KEYWORDS.update({r"\bkick(s)?\b": "Kicks", r"\bsub\b": "Sub Bass"})
            sorter_engine.RULE_METADATA.clear()
            sorter_engine.RULE_METADATA.update({r"\bkick(s)?\b": {"priority": 5}, r"\bsub\b": {"priority": 1}})
            sorter_engine.SYNTH_EXTS[".fxp"] = "Serum Presets"
            info = sorter_engine.explain_filename("Big_Sub_Kick_01.wav")
            self.assertEqual(info["winner"][1], "Kicks")
            self.assertEqual([f for _p, f in info["others"]], ["Sub Bass"])
            self.assertEqual(sorter_engine.explain_filename("lead.fxp")["destination"], "Serum Presets")
            self.assertIsNone(sorter_engine.explain_filename("vocal.wav")["winner"])
        finally:
            for target, original in ((sorter_engine.DRUM_KEYWORDS, saved[0]),
                                     (sorter_engine.RULE_METADATA, saved[1]),
                                     (sorter_engine.SYNTH_EXTS, saved[2])):
                target.clear()
                target.update(original)

    def test_shadowed_rule_detected(self):
        saved = (dict(sorter_engine.DRUM_KEYWORDS), dict(sorter_engine.RULE_METADATA))
        try:
            sorter_engine.DRUM_KEYWORDS.clear()
            sorter_engine.DRUM_KEYWORDS.update({r"\bkick\w*\b": "Kicks", r"\bkick\b": "Other", r"\bsnare\b": "Snares"})
            sorter_engine.RULE_METADATA.clear()
            sorter_engine.RULE_METADATA.update({
                r"\bkick\w*\b": {"priority": 9}, r"\bkick\b": {"priority": 5}, r"\bsnare\b": {"priority": 1}})
            shadowed = sorter_engine.find_shadowed_rules()
            self.assertIn(r"\bkick\b", shadowed)
            self.assertNotIn(r"\bsnare\b", shadowed)
            self.assertNotIn(r"\bkick\w*\b", shadowed)
        finally:
            for target, original in ((sorter_engine.DRUM_KEYWORDS, saved[0]), (sorter_engine.RULE_METADATA, saved[1])):
                target.clear()
                target.update(original)

    def test_undo_moves_files_back_without_overwriting(self):
        root = self.tmp.name
        src = os.path.join(root, "a.wav")
        dst_dir = os.path.join(root, "Kicks")
        os.makedirs(dst_dir)
        dst = os.path.join(dst_dir, "a.wav")
        with open(dst, "w") as f:
            f.write("x")
        log = sorter_engine._new_move_log_path()
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "source": src, "destination": dst,
                "destination_identity": sorter_engine._file_identity(dst),
            }) + "\n")
        with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", os.path.join(root, "none.db"), create=True):
            result = sorter_engine.undo_move_log(log)
        self.assertEqual(result["restored"], 1)
        self.assertTrue(os.path.exists(src))
        self.assertFalse(os.path.exists(dst))


if __name__ == "__main__":
    unittest.main()

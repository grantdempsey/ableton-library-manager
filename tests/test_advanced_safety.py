import glob
import os
import tempfile
import unittest
from unittest import mock

import gui_theme
from tab_experimental import ExperimentalTab, documented_options


class _Value:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class AdvancedSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.options_path = os.path.join(self.temp_dir.name, "Options.txt")
        self.path_patch = mock.patch.object(gui_theme, "OPTIONS_PATH", self.options_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)

        self.panel = ExperimentalTab.__new__(ExperimentalTab)
        self.panel.options_state = {
            "-EnableArmOnSelection": _Value(False),
            "-DontCombineAPCs": _Value(False),
        }
        self.panel.vst_limit_var = _Value("")
        self.panel.status_lbl = mock.Mock()
        self.panel.after = lambda _delay, callback: callback()

    def write_fixture(self, contents):
        with open(self.options_path, "wb") as target:
            target.write(contents)

    def save_with_dialogs(self):
        with mock.patch("tab_experimental.messagebox.showerror") as error, mock.patch(
            "tab_experimental.messagebox.showinfo"
        ) as success:
            self.panel.write_live_options_file()
        return error, success

    def test_read_failure_blocks_save_and_preserves_original(self):
        original = b"-EnableArmOnSelection\n-UnknownExperimentalOption\n"
        self.write_fixture(original)
        with mock.patch(
            "builtins.open", side_effect=PermissionError("read denied")
        ), mock.patch("tab_experimental.messagebox.showwarning"):
            self.panel.read_live_options_file()

        error, success = self.save_with_dialogs()

        self.assertTrue(error.called)
        success.assert_not_called()
        with open(self.options_path, "rb") as source:
            self.assertEqual(source.read(), original)
        self.assertIn("read denied", error.call_args.args[1])

    def test_save_preserves_unknown_and_unverified_legacy_lines_and_backs_up(self):
        original = (
            b"# keep this comment\r\n"
            b"-_AbsoluteMouseMode\r\n"
            b"-UnknownExperimentalOption=raw value\r\n"
            b"-AdaptiveMacroMappingBounds\r\n"
            b"-PluginAutoPopulateThreshold=-1\r\n"
            b"-EnableArmOnSelection\r\n"
            b"-MaxCpuAudioThreads=4\r\n"
        )
        self.write_fixture(original)
        self.panel.read_live_options_file()
        self.panel.options_state["-EnableArmOnSelection"].set(False)
        self.panel.options_state["-DontCombineAPCs"].set(True)
        self.panel.vst_limit_var.set("128")

        error, success = self.save_with_dialogs()

        error.assert_not_called()
        success.assert_called_once()
        with open(self.options_path, "rb") as source:
            saved = source.read()
        self.assertIn(b"# keep this comment\r\n", saved)
        self.assertIn(b"-_AbsoluteMouseMode\r\n", saved)
        self.assertIn(b"-UnknownExperimentalOption=raw value\r\n", saved)
        self.assertNotIn(b"-EnableArmOnSelection\n", saved)
        self.assertIn(b"-AdaptiveMacroMappingBounds\r\n", saved)
        self.assertIn(b"-DontCombineAPCs\n", saved)
        self.assertIn(b"-MaxCpuAudioThreads=4\r\n", saved)
        self.assertIn(b"-PluginAutoPopulateThreshold=-1\r\n", saved)
        self.assertIn(b"-_PluginAutoPopulateThreshold=128\n", saved)

        backups = glob.glob(os.path.join(self.temp_dir.name, ".Options.txt.*.bak"))
        self.assertEqual(len(backups), 1)
        with open(backups[0], "rb") as backup:
            self.assertEqual(backup.read(), original)

    def test_conflict_detected_without_replacing_newer_contents(self):
        original = b"-Unknown=before\n"
        changed = b"-Unknown=external edit\n"
        self.write_fixture(original)
        self.panel.read_live_options_file()
        self.write_fixture(changed)

        error, success = self.save_with_dialogs()

        error.assert_called_once()
        success.assert_not_called()
        with open(self.options_path, "rb") as source:
            self.assertEqual(source.read(), changed)
        self.assertIn("changed since it was loaded", error.call_args.args[1])

    def test_change_during_save_is_detected_before_atomic_replace(self):
            original = b"-Unknown=before\n"
            changed = b"-Unknown=external edit during save\n"
            self.write_fixture(original)
            self.panel.read_live_options_file()

            read_count = 0

            def detect_racing_change(_path):
                nonlocal read_count
                read_count += 1
                if read_count == 2:
                    self.write_fixture(changed)
                    return changed
                return original

            with mock.patch.object(
                self.panel,
                "_read_bytes_or_missing",
                side_effect=detect_racing_change,
            ):
                error, success = self.save_with_dialogs()

            error.assert_called_once()
            success.assert_not_called()
            with open(self.options_path, "rb") as source:
                self.assertEqual(source.read(), changed)

    def test_interrupted_atomic_replacement_keeps_original_and_reports_failure(self):
        original = b"-Unknown=preserve\n"
        self.write_fixture(original)
        self.panel.read_live_options_file()
        self.panel.options_state["-EnableArmOnSelection"].set(True)

        with mock.patch("tab_experimental.os.replace", side_effect=OSError("replace failed")):
            error, success = self.save_with_dialogs()

        error.assert_called_once()
        success.assert_not_called()
        with open(self.options_path, "rb") as source:
            self.assertEqual(source.read(), original)
        self.assertEqual(
            glob.glob(os.path.join(self.temp_dir.name, ".Options.txt.*.tmp")), []
        )
        self.assertEqual(
            len(glob.glob(os.path.join(self.temp_dir.name, ".Options.txt.*.bak"))), 1
        )

    def test_invalid_numeric_values_are_rejected_without_writing(self):
        original = b"-Unknown=preserve\n"
        invalid_values = ("0", "129", "2.5", "-1", "many")
        for plugin_limit in invalid_values:
            with self.subTest(plugin_limit=plugin_limit):
                self.write_fixture(original)
                self.panel.read_live_options_file()
                self.panel.vst_limit_var.set(plugin_limit)

                error, success = self.save_with_dialogs()

                error.assert_called_once()
                success.assert_not_called()
                with open(self.options_path, "rb") as source:
                    self.assertEqual(source.read(), original)
                self.assertEqual(
                    glob.glob(os.path.join(self.temp_dir.name, ".Options.txt.*.bak")),
                    [],
                )

    def test_inspection_reports_only_syntax_and_not_live_verification(self):
        self.write_fixture(b"-MaxCpuAudioThreads=8\n-_PluginAutoPopulateThreshold=64\n")

        self.panel.automated_background_verify_sweep()

        status_text = self.panel.status_lbl.config.call_args.kwargs["text"]
        self.assertIn("inspected", status_text)
        self.assertIn("not validated by Live", status_text)
        self.assertNotIn("Auto-Verified", status_text)
        self.assertNotIn("Auto-disabling", status_text)

    def test_underscored_absolute_mouse_flag_is_not_exposed_as_a_toggle(self):
        self.assertNotIn("-_AbsoluteMouseMode", self.panel.options_state)

    def test_only_documented_exact_platform_options_are_exposed(self):
        windows = documented_options("Windows")
        mac = documented_options("Darwin")
        self.assertEqual({
            "-EnableArmOnSelection", "-DontCombineAPCs", "-_EnsureKeyMessagesForPlugins",
        }, set(windows))
        self.assertIn("Push 2 or Push 3", windows["-EnableArmOnSelection"][1])
        self.assertNotIn("-_EnsureKeyMessagesForPlugins", mac)
        self.assertIn("-DisableGraphicsHardwareAcceleration", mac)
        self.assertIn("-DisableAppleSiliconBurstWorkaround", mac)

    def test_exact_documented_parameter_flag_round_trips_boundaries(self):
        for limit in ("1", "64", "128"):
            self.write_fixture(b"-_PluginAutoPopulateThreshold=" + limit.encode() + b"\n")
            self.panel.read_live_options_file()
            self.assertEqual(limit, self.panel.vst_limit_var.get())
            error, success = self.save_with_dialogs()
            error.assert_not_called()
            success.assert_called_once()
            with open(self.options_path, "rb") as handle:
                self.assertIn(b"-_PluginAutoPopulateThreshold=" + limit.encode(), handle.read())


if __name__ == "__main__":
    unittest.main()

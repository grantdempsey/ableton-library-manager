import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import ableton_tags
import gui_theme
import live_catalog
import sorter_engine


SPEC = importlib.util.spec_from_file_location(
    "acceptance_fixture", Path(__file__).with_name("prepare_live_acceptance.py")
)
fixture_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixture_tool)


class LiveAcceptanceFixtureTests(unittest.TestCase):
    def test_generated_fixture_and_assignment_stages_preserve_audio_and_neighbor(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = fixture_tool.prepare(parent)
            self.assertEqual("unchanged", fixture_tool.verify(fixture, "baseline")["audio_bytes"])
            sample = str(fixture / "Test Library" / fixture_tool.SAMPLES[0])
            ableton_tags.prepare_edit([sample], "Genres|ALM Release Test").commit()
            fixture_tool.verify(fixture, "add")
            ableton_tags.prepare_edit(
                [sample], "Genres|ALM Release Test", replacement="Character|ALM Round Trip"
            ).commit()
            fixture_tool.verify(fixture, "rename")
            ableton_tags.prepare_edit([sample], "Character|ALM Round Trip", remove=True).commit()
            fixture_tool.verify(fixture, "remove")

    def test_changed_audio_and_unrecognized_fixture_are_refused(self):
        with tempfile.TemporaryDirectory() as parent:
            with self.assertRaises(FileNotFoundError):
                fixture_tool.load_fixture(parent)
            fixture = fixture_tool.prepare(parent)
            (fixture / "Test Library" / fixture_tool.SAMPLES[0]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "Audio bytes changed"):
                fixture_tool.verify(fixture, "baseline")

    def test_neighbor_assignment_changes_are_detected(self):
        with tempfile.TemporaryDirectory() as parent:
            fixture = fixture_tool.prepare(parent)
            neighbor = str(fixture / "Test Library" / fixture_tool.SAMPLES[1])
            ableton_tags.prepare_edit([neighbor], "Character|Unexpected").commit()
            with self.assertRaisesRegex(ValueError, "Assignments differ"):
                fixture_tool.verify(fixture, "baseline")

    def test_launcher_routes_profile_library_and_discovery_to_fixture(self):
        cwd = Path.cwd()
        search_path = list(sys.path)
        try:
            with tempfile.TemporaryDirectory() as parent:
                fixture = fixture_tool.prepare(parent)
                with mock.patch.object(gui_theme, "USER_LIBRARY_PATH"), mock.patch.object(
                    gui_theme, "resolve_user_library_path"
                ), mock.patch.object(gui_theme, "OPTIONS_PATH"), mock.patch.object(
                    live_catalog, "available_databases"
                ), mock.patch.object(sorter_engine, "CONFIG_FILE"), mock.patch.object(
                    sorter_engine, "ASSET_INDEX_FILE"
                ), mock.patch.object(fixture_tool.runpy, "run_path") as entry:
                    fixture_tool.launch(fixture)
                    self.assertEqual(fixture / "runtime", Path.cwd())
                    self.assertEqual(str(fixture / "Test Library"), gui_theme.resolve_user_library_path())
                    self.assertEqual((), live_catalog.available_databases())
                    self.assertEqual(fixture / "runtime", Path(sorter_engine.CONFIG_FILE).parent)
                    self.assertEqual(fixture / "runtime", Path(sorter_engine.ASSET_INDEX_FILE).parent)
                    self.assertEqual(fixture / "runtime", Path(gui_theme.OPTIONS_PATH).parent)
                    entry.assert_called_once_with(
                        str(fixture_tool.ROOT / "AbletonLibraryManager.pyw"), run_name="__main__"
                    )
                os.chdir(cwd)
        finally:
            os.chdir(cwd)
            sys.path[:] = search_path

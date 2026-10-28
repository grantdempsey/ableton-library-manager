import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import ableton_tags
import live_tag_sync
import sorter_engine


class LiveTagSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        patcher = mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.root, "assets.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.sample = os.path.join(self.root, "library", "sample.wav")
        os.makedirs(os.path.dirname(self.sample))
        with open(self.sample, "wb") as handle:
            handle.write(b"audio")
        self.library = os.path.dirname(self.sample)
        sorter_engine.index_asset(self.sample, self.library, "test", 1, ["favorite"])

    def settle(self, baseline=None):
        state, snapshot = live_tag_sync.poll_live_metadata(self.library, baseline)
        self.assertEqual("pending", state)
        state, refreshed = live_tag_sync.poll_live_metadata(self.library, baseline, snapshot)
        self.assertEqual("refreshed", state)
        self.assertEqual(snapshot, refreshed)
        return refreshed

    def test_initial_sync_then_external_rename_removal_and_deleted_sidecars(self):
        ableton_tags.prepare_edit([self.sample], "Character|Old").commit()
        baseline = self.settle()
        self.assertEqual(["Character|Old"], sorter_engine.get_indexed_asset(self.sample)["ableton_tags"])
        self.assertEqual(("checked", baseline), live_tag_sync.poll_live_metadata(self.library, baseline))
        ableton_tags.prepare_edit([self.sample], "Character|Old", replacement="Sounds|New").commit()
        baseline = self.settle(baseline)
        self.assertEqual(["Sounds|New"], sorter_engine.get_indexed_asset(self.sample)["ableton_tags"])
        for sidecar in Path(self.library, "Ableton Folder Info").glob("*.xmp"):
            sidecar.unlink()
        self.settle(baseline)
        self.assertEqual([], sorter_engine.get_indexed_asset(self.sample)["ableton_tags"])
        self.assertIn("favorite", sorter_engine.get_asset_tags(self.sample))

    def test_malformed_metadata_keeps_existing_cache_and_recovers(self):
        ableton_tags.prepare_edit([self.sample], "Sounds|Keep").commit()
        baseline = self.settle()
        sidecar = next(Path(self.library, "Ableton Folder Info").glob("*.xmp"))
        original = sidecar.read_bytes()
        sidecar.write_bytes(b"<broken")
        state, candidate = live_tag_sync.poll_live_metadata(self.library, baseline)
        self.assertEqual("pending", state)
        with self.assertRaisesRegex(ValueError, "Invalid"):
            live_tag_sync.poll_live_metadata(self.library, baseline, candidate)
        self.assertEqual(["Sounds|Keep"], sorter_engine.get_indexed_asset(self.sample)["ableton_tags"])
        sidecar.write_bytes(original)
        self.assertEqual(("checked", baseline), live_tag_sync.poll_live_metadata(self.library, baseline))

    def test_read_only_probe_does_not_change_audio_or_sidecars(self):
        ableton_tags.prepare_edit([self.sample], "Sounds|Keep").commit()
        sidecar = next(Path(self.library, "Ableton Folder Info").glob("*.xmp"))
        before = sidecar.read_bytes()
        with mock.patch.object(ableton_tags.TagEdit, "commit") as writer:
            self.settle()
        writer.assert_not_called()
        self.assertEqual(before, sidecar.read_bytes())
        self.assertEqual(b"audio", Path(self.sample).read_bytes())

    def test_continuing_changes_reset_candidate_and_commit_conflicts_roll_back(self):
        ableton_tags.prepare_edit([self.sample], "Sounds|Original").commit()
        baseline = self.settle()
        ableton_tags.prepare_edit([self.sample], "Sounds|Later").commit()
        _state, first = live_tag_sync.poll_live_metadata(self.library, baseline)
        ableton_tags.prepare_edit([self.sample], "Character|Newest").commit()
        state, candidate = live_tag_sync.poll_live_metadata(self.library, baseline, first)
        self.assertEqual("pending", state)
        self.assertNotEqual(first, candidate)
        fingerprint = live_tag_sync._fingerprint
        calls = 0
        def changed_before_commit(paths, folders):
            nonlocal calls
            calls += 1
            if calls == 3:
                return ("concurrent change",)
            return fingerprint(paths, folders)
        with mock.patch.object(live_tag_sync, "_fingerprint", side_effect=changed_before_commit):
            with self.assertRaisesRegex(ValueError, "before cache commit"):
                live_tag_sync.poll_live_metadata(self.library, baseline, candidate)
        self.assertEqual(["Sounds|Original"], sorter_engine.get_indexed_asset(self.sample)["ableton_tags"])
        self.settle(baseline)
        self.assertEqual(
            ["Character|Newest", "Sounds|Later", "Sounds|Original"],
            sorter_engine.get_indexed_asset(self.sample)["ableton_tags"]
        )

    def test_unavailable_library_fails_instead_of_clearing_cached_rows(self):
        with self.assertRaises(NotADirectoryError):
            live_tag_sync.poll_live_metadata(os.path.join(self.root, "missing"))
        self.assertIn("favorite", sorter_engine.get_asset_tags(self.sample))

    def test_root_scope_and_ancestor_sidecars_are_read_without_touching_outside_cache(self):
        outside = os.path.join(self.root, "outside.wav")
        with open(outside, "wb") as handle:
            handle.write(b"audio")
        sorter_engine.index_asset(outside, self.root, "test", 1, [])
        plan = ableton_tags.TagEdit({
            self.sample: ["Character|Inside"], outside: ["Sounds|Outside"]
        })
        plan.commit()
        inside_sidecar = next(Path(self.library, "Ableton Folder Info").glob("*.xmp"))
        tree = ableton_tags.ET.parse(inside_sidecar)
        node = tree.getroot().find(".//ablFR:filePath", ableton_tags.NAMESPACES)
        node.text = "library/sample.wav"
        tree.write(Path(self.root, "Ableton Folder Info", inside_sidecar.name), encoding="utf-8")
        inside_sidecar.unlink()
        sorter_engine.refresh_live_tag_cache([outside])
        ableton_tags.prepare_edit([outside], "Sounds|New external").commit()
        self.settle()
        self.assertEqual(["Character|Inside"], sorter_engine.get_indexed_asset(self.sample)["ableton_tags"])
        self.assertEqual(["Sounds|Outside"], sorter_engine.get_indexed_asset(outside)["ableton_tags"])
        self.assertEqual([], ableton_tags.sample_tags(os.path.join(self.library, "not-indexed.wav")))

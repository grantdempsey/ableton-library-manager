import errno
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

import ableton_tags
import sorter_engine


RDF = ableton_tags.NAMESPACES["rdf"]
LIVE = ableton_tags.NAMESPACES["ablFR"]


class AbletonTagTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        patcher = mock.patch.object(
            sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.root, "assets.db")
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def sample(self, relative):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"unchanged audio")
        return path

    def sidecar(self, assignments, folder=None, name="test.xmp"):
        folder = folder or self.root
        info = os.path.join(folder, "Ableton Folder Info")
        os.makedirs(info, exist_ok=True)
        root = ET.Element("{adobe:ns:meta/}xmpmeta")
        description = ET.SubElement(ET.SubElement(root, f"{{{RDF}}}RDF"), f"{{{RDF}}}Description")
        bag = ET.SubElement(ET.SubElement(description, f"{{{LIVE}}}items"), f"{{{RDF}}}Bag")
        for filename, tags in assignments:
            item = ET.SubElement(bag, f"{{{RDF}}}li", {f"{{{RDF}}}parseType": "Resource"})
            ET.SubElement(item, f"{{{LIVE}}}filePath").text = filename
            keywords = ET.SubElement(ET.SubElement(item, f"{{{LIVE}}}keywords"), f"{{{RDF}}}Bag")
            for tag in tags:
                ET.SubElement(keywords, f"{{{RDF}}}li").text = tag
        ET.SubElement(description, "{http://ns.adobe.com/xap/1.0/}CreatorTool").text = "Ableton Index 12.4.7"
        path = os.path.join(info, name)
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
        return path

    def test_exact_paths_hierarchy_case_and_unicode_are_preserved(self):
        first = self.sample(os.path.join("A", "Same C#.wav"))
        second = self.sample(os.path.join("B", "Same C#.wav"))
        tags = ["Sounds|Bass|Synth Bass", "Character|Énergie & Warm"]
        sidecar = self.sidecar([("A/Same C#.wav", tags), ("B/Same C#.wav", ["Sounds|Other"])])
        with open(sidecar, "rb") as handle:
            original = handle.read()
        sorter_engine.index_existing_library(self.root)
        self.assertEqual(sorted(tags), sorter_engine.get_indexed_asset(first)["ableton_tags"])
        self.assertEqual(["Sounds|Other"], sorter_engine.get_indexed_asset(second)["ableton_tags"])
        self.assertNotIn("personal_tags", sorter_engine.get_indexed_asset(first))
        self.assertEqual(1, sorter_engine.count_indexed_assets(
            self.root, tag_filter="ableton:Sounds|Bass|Synth Bass"
        ))
        with open(sidecar, "rb") as handle:
            self.assertEqual(original, handle.read())
        with open(first, "rb") as handle:
            self.assertEqual(b"unchanged audio", handle.read())

    def test_rename_removal_and_deleted_sidecars_do_not_resurrect_tags(self):
        sample = self.sample("test.wav")
        sidecar = self.sidecar([("test.wav", ["Sounds|Old", "Character|Keep"])])
        sorter_engine.index_existing_library(self.root)
        sorter_engine.add_asset_tag(sample, "favorite")
        self.sidecar([("test.wav", ["Sounds|Renamed", "Character|Keep"])])
        sorter_engine.index_existing_library(self.root)
        self.assertEqual(
            ["Character|Keep", "Sounds|Renamed"],
            sorter_engine.get_indexed_asset(sample)["ableton_tags"]
        )
        self.sidecar([("test.wav", [])])
        sorter_engine.index_existing_library(self.root)
        self.assertEqual([], sorter_engine.get_indexed_asset(sample)["ableton_tags"])
        self.assertIn("favorite", sorter_engine.get_asset_tags(sample))
        self.sidecar([("test.wav", ["Sounds|Again"])])
        sorter_engine.index_existing_library(self.root)
        os.remove(sidecar)
        sorter_engine.index_existing_library(self.root)
        self.assertEqual([], sorter_engine.get_indexed_asset(sample)["ableton_tags"])
        self.assertIn("favorite", sorter_engine.get_asset_tags(sample))

    def test_scan_subroot_reads_and_reconciles_ancestor_sidecar_assignments(self):
        sample = self.sample(os.path.join("library", "sample.wav"))
        self.sidecar([("library/sample.wav", ["Character|Ancestor"])])
        sorter_engine.index_existing_library(os.path.dirname(sample))
        self.assertEqual(["Character|Ancestor"], sorter_engine.get_indexed_asset(sample)["ableton_tags"])
        self.sidecar([("library/sample.wav", ["Sounds|Renamed"])])
        sorter_engine.index_existing_library(os.path.dirname(sample))
        self.assertEqual(["Sounds|Renamed"], sorter_engine.get_indexed_asset(sample)["ableton_tags"])
        self.sidecar([("library/sample.wav", [])])
        sorter_engine.index_existing_library(os.path.dirname(sample))
        self.assertEqual([], sorter_engine.get_indexed_asset(sample)["ableton_tags"])

    def test_bad_sidecar_rolls_back_cache_and_reports_path(self):
        sample = self.sample("test.wav")
        sidecar = self.sidecar([("test.wav", ["Sounds|Keep"])])
        sorter_engine.index_existing_library(self.root)
        with open(sidecar, "w", encoding="utf-8") as handle:
            handle.write("<broken")
        with self.assertRaisesRegex(ValueError, "test.xmp"):
            sorter_engine.index_existing_library(self.root)
        self.assertEqual(["Sounds|Keep"], sorter_engine.get_indexed_asset(sample)["ableton_tags"])

    def test_sidecar_path_escape_is_rejected(self):
        for path in ("../outside.wav", r"..\outside.wav", os.path.abspath("outside.wav")):
            with self.subTest(path=path):
                self.sidecar([(path, ["Sounds|No"])])
                with self.assertRaises(ValueError):
                    ableton_tags.read_folder_tags(self.root)

    def test_cache_cannot_be_modified_with_local_tag_actions(self):
        sample = self.sample("test.wav")
        self.sidecar([("test.wav", ["Sounds|Keep"])])
        sorter_engine.index_existing_library(self.root)
        tag = "ableton:Sounds|Keep"
        for action in (
            lambda: sorter_engine.add_asset_tag(sample, tag),
            lambda: sorter_engine.remove_asset_tag(sample, tag),
            lambda: sorter_engine.bulk_update_asset_tags([sample], tag),
            lambda: sorter_engine.bulk_update_asset_tags([sample], tag, remove=True),
            lambda: sorter_engine.set_asset_tag_enabled(sample, tag, False),
        ):
            with self.assertRaisesRegex(ValueError, "read-only|App-only tags have been removed"):
                action()
        self.assertEqual(["Sounds|Keep"], sorter_engine.get_indexed_asset(sample)["ableton_tags"])

    def test_move_does_not_promote_live_cache_to_personal_tags(self):
        sample = self.sample("test.wav")
        self.sidecar([("test.wav", ["Sounds|Keep"])])
        sorter_engine.index_existing_library(self.root)
        sorter_engine.add_asset_tag(sample, "favorite")
        sorter_engine.set_asset_tag_enabled(sample, "favorite", False)
        tags = sorter_engine.get_asset_tags(sample)
        moved = os.path.join(self.root, "moved.wav")
        os.replace(sample, moved)
        sorter_engine.index_asset(moved, self.root, "test", 1.0, tags, previous_path=sample)
        record = sorter_engine.get_indexed_asset(moved)
        self.assertEqual([], record["ableton_tags"])
        self.assertNotIn("personal_tags", record)
        self.assertIn("favorite", record["disabled_tags"])
        self.assertIsNone(sorter_engine.get_indexed_asset(sample))

    def test_reindex_ignores_cache_as_input_personal_tags(self):
        sample = self.sample("test.wav")
        self.sidecar([("test.wav", ["Sounds|Keep"])])
        sorter_engine.index_existing_library(self.root)
        sorter_engine.index_asset(
            sample, self.root, "test", 1.0, sorter_engine.get_asset_tags(sample)
        )
        self.sidecar([("test.wav", [])])
        sorter_engine.index_existing_library(self.root)
        self.assertFalse(any(tag.startswith("ableton:") for tag in sorter_engine.get_asset_tags(sample)))

    def test_edit_preserves_neighbor_metadata_and_creates_exact_backup(self):
        first = self.sample("first.wav")
        self.sample("neighbor.wav")
        path = self.sidecar([
            ("first.wav", ["Sounds|Original"]), ("neighbor.wav", ["Sounds|Neighbor"])
        ])
        tree = ET.parse(path)
        ET.SubElement(tree.getroot(), "{urn:test}untouched", {"id": "42"}).text = "keep"
        tree.write(path, encoding="utf-8")
        with open(path, "rb") as handle:
            original = handle.read()
        plan = ableton_tags.prepare_edit([first], "Character|Énergie & Warm")
        backups = plan.commit()
        self.assertEqual(1, len(backups))
        with open(backups[0], "rb") as handle:
            self.assertEqual(original, handle.read())
        self.assertEqual(
            ["Character|Énergie & Warm", "Sounds|Original"], ableton_tags.sample_tags(first)
        )
        self.assertEqual(
            ["Sounds|Neighbor"], ableton_tags.sample_tags(os.path.join(self.root, "neighbor.wav"))
        )
        self.assertEqual("keep", ET.parse(path).getroot().findtext("{urn:test}untouched"))

    def test_plain_tags_new_sidecars_rename_and_remove(self):
        sample = self.sample("new C#.wav")
        ableton_tags.prepare_edit([sample], "New Tag").commit()
        self.assertEqual(["Sounds|New Tag"], ableton_tags.sample_tags(sample))
        ableton_tags.prepare_edit(
            [sample], "New Tag", replacement="Character|Renamed"
        ).commit()
        self.assertEqual(["Character|Renamed"], ableton_tags.sample_tags(sample))
        ableton_tags.prepare_edit([sample], "Character|Renamed", remove=True).commit()
        self.assertEqual([], ableton_tags.sample_tags(sample))
        self.assertEqual({}, ableton_tags.prepare_edit([sample], "Missing", remove=True).changes)

    def test_batch_combines_ordered_actions_and_reports_net_changes_without_writing(self):
        first = self.sample("first.wav")
        second = self.sample("second.wav")
        sidecar = self.sidecar([
            ("first.wav", ["Sounds|Old", "Character|Keep"]),
            ("second.wav", ["Character|Keep"]),
        ])
        with open(sidecar, "rb") as handle:
            original = handle.read()
        plan = ableton_tags.prepare_batch([first, second, first], [
            ableton_tags.TagOperation("add", "Temporary"),
            ableton_tags.TagOperation("remove", "Temporary"),
            ableton_tags.TagOperation("rename", "Sounds|Old", "Sounds|Renamed"),
            ableton_tags.TagOperation("add", "Character|Keep"),
        ])
        self.assertEqual(((first, ("Sounds|Renamed",), ("Sounds|Old",)),), plan.sample_changes)
        self.assertEqual(1, plan.unchanged_count)
        self.assertEqual(1, len(plan.changes))
        with open(sidecar, "rb") as handle:
            self.assertEqual(original, handle.read())
        self.assertEqual(1, len(plan.commit()))
        self.assertEqual(["Character|Keep", "Sounds|Renamed"], ableton_tags.sample_tags(first))
        self.assertEqual(["Character|Keep"], ableton_tags.sample_tags(second))

    def test_batch_no_net_changes_creates_no_files(self):
        sample = self.sample("sample.wav")
        plan = ableton_tags.prepare_batch([sample], [
            ableton_tags.TagOperation("add", "Cancel"),
            ableton_tags.TagOperation("remove", "Cancel"),
        ])
        self.assertEqual({}, plan.changes)
        self.assertEqual((), plan.sample_changes)
        self.assertEqual(1, plan.unchanged_count)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "Ableton Folder Info")))

    def test_batch_invalid_queue_or_samples_cannot_write(self):
        sample = self.sample("sample.wav")
        for operations in (
            [], [ableton_tags.TagOperation("unknown", "Tag")],
            [ableton_tags.TagOperation("rename", "Tag")],
            [ableton_tags.TagOperation("add", "Tag", "Other")],
            [ableton_tags.TagOperation("add", "Sounds||Invalid")],
        ):
            with self.subTest(operations=operations):
                with self.assertRaises(ValueError):
                    ableton_tags.prepare_batch([sample], operations)
        with self.assertRaises(ValueError):
            ableton_tags.prepare_batch([], [ableton_tags.TagOperation("add", "Tag")])
        self.assertFalse(os.path.isdir(os.path.join(self.root, "Ableton Folder Info")))

    def test_batch_rejects_audio_or_sidecar_changes_after_review(self):
        sample = self.sample("sample.wav")
        self.sidecar([("sample.wav", ["Sounds|Original"])])
        plan = ableton_tags.prepare_batch([sample], [ableton_tags.TagOperation("add", "Planned")])
        self.sidecar([("sample.wav", ["Sounds|Concurrent"])])
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            plan.commit()
        plan = ableton_tags.prepare_batch([sample], [ableton_tags.TagOperation("add", "Planned")])
        with open(sample, "ab") as handle:
            handle.write(b"external audio change")
        with self.assertRaisesRegex(ValueError, "sample changed"):
            plan.commit()
        self.assertEqual(["Sounds|Concurrent"], ableton_tags.sample_tags(sample))

    def test_conflicting_changes_and_added_sidecars_abort_before_writing(self):
        sample = self.sample("sample.wav")
        path = self.sidecar([("sample.wav", ["Sounds|Original"])])
        plan = ableton_tags.prepare_edit([sample], "Planned")
        self.sidecar([("sample.wav", ["Sounds|Concurrent"])])
        with self.assertRaisesRegex(ValueError, "changed"):
            plan.commit()
        self.assertEqual(["Sounds|Concurrent"], ableton_tags.sample_tags(sample))
        plan = ableton_tags.prepare_edit([sample], "Planned")
        self.sidecar([("sample.wav", ["Sounds|New file"])], name="another.xmp")
        with self.assertRaisesRegex(ValueError, "added or removed"):
            plan.commit()
        with open(path, "rb") as handle:
            self.assertNotIn(b"Planned", handle.read())

    def test_bulk_write_failure_rolls_back_written_sidecars(self):
        first = self.sample(os.path.join("A", "first.wav"))
        second = self.sample(os.path.join("B", "second.wav"))
        self.sidecar([("first.wav", ["Sounds|Original"])], folder=os.path.dirname(first))
        self.sidecar([("second.wav", ["Sounds|Original"])], folder=os.path.dirname(second))
        plan = ableton_tags.prepare_edit([first, second], "Planned")
        write = ableton_tags._atomic_write
        count = 0
        def fail_second(path, data):
            nonlocal count
            count += 1
            if count == 2:
                raise PermissionError("locked")
            return write(path, data)
        with mock.patch.object(ableton_tags, "_atomic_write", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                plan.commit()
        self.assertEqual(["Sounds|Original"], ableton_tags.sample_tags(first))
        self.assertEqual(["Sounds|Original"], ableton_tags.sample_tags(second))

    def test_copy_move_and_undo_preserve_manual_tags(self):
        source = self.sample(os.path.join("incoming", "sample.wav"))
        self.sidecar([("sample.wav", ["Sounds|Bass", "Character|Warm"])], folder=os.path.dirname(source))
        destination = os.path.join(self.root, "library", "renamed.wav")
        os.makedirs(os.path.dirname(destination))
        ableton_tags.transfer_sample(source, destination, copy=True)
        self.assertEqual(ableton_tags.sample_tags(source), ableton_tags.sample_tags(destination))
        moved = os.path.join(self.root, "library", "moved.wav")
        ableton_tags.transfer_sample(source, moved)
        self.assertFalse(os.path.exists(source))
        self.assertEqual([], ableton_tags.sample_tags(source))
        self.assertEqual(["Character|Warm", "Sounds|Bass"], ableton_tags.sample_tags(moved))
        ableton_tags.transfer_sample(moved, source)
        self.assertEqual(["Character|Warm", "Sounds|Bass"], ableton_tags.sample_tags(source))
        self.assertEqual([], ableton_tags.sample_tags(moved))
        with open(source, "rb") as handle:
            self.assertEqual(b"unchanged audio", handle.read())

    def test_metadata_failure_rolls_back_audio_move_and_copy(self):
        source = self.sample("sample.wav")
        self.sidecar([("sample.wav", ["Sounds|Bass"])])
        for copy in (False, True):
            destination = os.path.join(self.root, "destination.wav")
            with mock.patch.object(ableton_tags.TagEdit, "commit", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    ableton_tags.transfer_sample(source, destination, copy=copy)
            self.assertTrue(os.path.isfile(source))
            self.assertFalse(os.path.exists(destination))
            self.assertEqual(["Sounds|Bass"], ableton_tags.sample_tags(source))

    def test_duplicate_merge_keeps_both_assignments_and_clears_source(self):
        source = self.sample("source.wav")
        destination = self.sample("destination.wav")
        self.sidecar([
            ("source.wav", ["Sounds|Source"]), ("destination.wav", ["Sounds|Destination"])
        ])
        ableton_tags.transfer_sample(source, destination, duplicate=True)
        self.assertFalse(os.path.exists(source))
        self.assertEqual([], ableton_tags.sample_tags(source))
        self.assertEqual(
            ["Sounds|Destination", "Sounds|Source"], ableton_tags.sample_tags(destination)
        )

    def test_invalid_manual_tags_cannot_write_sidecars(self):
        sample = self.sample("sample.wav")
        for tag in ("", "Sounds||Empty", "Sounds|", "a" * 241, "Sounds|bad\nline", "ableton:Sounds|No"):
            with self.subTest(tag=tag):
                with self.assertRaises(ValueError):
                    ableton_tags.prepare_edit([sample], tag)
        self.assertFalse(os.path.isdir(os.path.join(self.root, "Ableton Folder Info")))

    def test_unsupported_bags_abort_without_clearing_cached_tags(self):
        sample = self.sample("sample.wav")
        for element in ("items", "keywords"):
            with self.subTest(element=element):
                path = self.sidecar([("sample.wav", ["Sounds|Keep"])])
                sorter_engine.index_existing_library(self.root)
                tree = ET.parse(path)
                node = tree.getroot().find(f".//ablFR:{element}/rdf:Bag", ableton_tags.NAMESPACES)
                node.tag = f"{{{RDF}}}Seq"
                tree.write(path, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unsupported"):
                    sorter_engine.index_existing_library(self.root)
                with self.assertRaisesRegex(ValueError, "Unsupported"):
                    ableton_tags.prepare_edit([sample], "New")
                self.assertEqual(["Sounds|Keep"], sorter_engine.get_indexed_asset(sample)["ableton_tags"])

    def test_same_file_and_missing_duplicate_abort_without_removing_source(self):
        source = self.sample("source.wav")
        for destination, duplicate in (
            (source, False), (source, True),
            (os.path.join(self.root, "missing.wav"), True),
        ):
            with self.subTest(destination=destination, duplicate=duplicate):
                with self.assertRaises(ValueError):
                    ableton_tags.transfer_sample(source, destination, duplicate=duplicate)
                self.assertTrue(os.path.isfile(source))

    def test_cross_volume_move_and_failed_save_restore_audio(self):
        source = self.sample("source.wav")
        self.sidecar([("source.wav", ["Sounds|Source"])])
        destination = os.path.join(self.root, "other-volume", "destination.wav")
        os.makedirs(os.path.dirname(destination))
        with mock.patch.object(ableton_tags.os, "rename", side_effect=OSError(errno.EXDEV, "cross-device")):
            with mock.patch.object(ableton_tags.TagEdit, "commit", side_effect=PermissionError("locked")):
                with self.assertRaises(PermissionError):
                    ableton_tags.transfer_sample(source, destination)
            self.assertTrue(os.path.isfile(source))
            self.assertFalse(os.path.exists(destination))
            ableton_tags.transfer_sample(source, destination)
        self.assertFalse(os.path.exists(source))
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(destination))
        self.assertEqual([], ableton_tags.sample_tags(source))

    def test_duplicate_merge_failure_restores_source_and_both_tag_sets(self):
        source = self.sample("source.wav")
        destination = self.sample("destination.wav")
        self.sidecar([
            ("source.wav", ["Sounds|Source"]), ("destination.wav", ["Sounds|Destination"])
        ])
        with mock.patch.object(ableton_tags.TagEdit, "commit", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                ableton_tags.transfer_sample(source, destination, duplicate=True)
        with open(source, "rb") as handle:
            self.assertEqual(b"unchanged audio", handle.read())
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(source))
        self.assertEqual(["Sounds|Destination"], ableton_tags.sample_tags(destination))

    def test_failed_rollback_reports_backup_and_continues_other_restores(self):
        samples = [self.sample(os.path.join(folder, "sample.wav")) for folder in ("A", "B", "C")]
        for sample in samples:
            self.sidecar([("sample.wav", ["Sounds|Original"])], folder=os.path.dirname(sample))
        plan = ableton_tags.prepare_edit(samples, "Planned")
        write = ableton_tags._atomic_write
        count = 0
        def fail_save_and_first_restore(path, data):
            nonlocal count
            count += 1
            if count in (3, 4):
                raise PermissionError("locked")
            return write(path, data)
        with mock.patch.object(ableton_tags, "_atomic_write", side_effect=fail_save_and_first_restore):
            with self.assertRaisesRegex(OSError, r"rollback incomplete:.*Backups:.*\.bak"):
                plan.commit()
        self.assertEqual(["Sounds|Original"], ableton_tags.sample_tags(samples[0]))
        self.assertEqual(["Sounds|Original", "Sounds|Planned"], ableton_tags.sample_tags(samples[1]))
        self.assertEqual(["Sounds|Original"], ableton_tags.sample_tags(samples[2]))


if __name__ == "__main__":
    unittest.main()

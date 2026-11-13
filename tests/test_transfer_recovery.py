import os
import marshal
import json
import stat
import errno
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import ableton_tags
from tab_organize import OrganizeTab


class TransferRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "incoming" / "sample.wav"
        self.destination = self.root / "library" / "sample.wav"
        self.source.parent.mkdir()
        self.destination.parent.mkdir()
        self.source.write_bytes(b"audio" * 100)
        ableton_tags.prepare_edit([str(self.source)], "Sounds|Source").commit()

    def journals(self):
        return ableton_tags.find_transfer_recovery(str(self.destination.parent))

    def crash(self, phase, *, copy=False, duplicate=False):
        # A child process exits without finally/exception cleanup.
        code = ableton_tags.__loader__.get_code("ableton_tags")
        code_path = self.root / "transfer-code.bin"
        with code_path.open("wb") as handle:
            marshal.dump(code, handle)
        script = """
import os, sys, marshal, types
phase, source, destination, copy, duplicate, code_path, recover = sys.argv[1:]
ableton_tags = types.ModuleType('ableton_tags')
sys.modules['ableton_tags'] = ableton_tags
with open(code_path, 'rb') as handle:
    exec(marshal.load(handle), ableton_tags.__dict__)
def checkpoint(name):
    if name == phase:
        os._exit(79)
ableton_tags._transfer_checkpoint = checkpoint
if phase == 'copying':
    def partial_copy(first, second):
        second.write(first.read(3))
        second.flush()
        os._exit(79)
    ableton_tags.shutil.copyfileobj = partial_copy
if phase == 'publication_gap':
    publish = ableton_tags._publish_sample
    def publish_then_exit(first, second):
        publish(first, second)
        os._exit(79)
    ableton_tags._publish_sample = publish_then_exit
if recover == 'True':
    ableton_tags.recover_transfers(ableton_tags.find_transfer_recovery(os.path.dirname(destination)))
else:
    ableton_tags.transfer_sample(source, destination, copy=copy == 'True', duplicate=duplicate == 'True')
"""
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPATH"] = str(Path(ableton_tags.__file__).parent)
        child = subprocess.run(
            [sys.executable, "-c", script, phase, str(self.source), str(self.destination),
             str(copy), str(duplicate), str(code_path), str(phase.startswith("recovery_"))],
            env=environment, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(79, child.returncode, child.stderr)

    def assert_original(self, *, duplicate=False):
        self.assertEqual(b"audio" * 100, self.source.read_bytes())
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(str(self.source)))
        if duplicate:
            self.assertEqual(b"audio" * 100, self.destination.read_bytes())
            self.assertEqual(["Character|Destination"], ableton_tags.sample_tags(str(self.destination)))
        else:
            self.assertFalse(self.destination.exists())
        self.assertEqual([], self.journals())

    def test_partial_stage_never_appears_at_final_destination(self):
        def partial(source, destination):
            Path(destination).write_bytes(b"partial")
            self.assertFalse(self.destination.exists())
            raise OSError("disk full fixture")
        with mock.patch.object(ableton_tags, "_copy_sample", side_effect=partial):
            with self.assertRaisesRegex(OSError, "disk full"):
                ableton_tags.transfer_sample(str(self.source), str(self.destination), copy=True)
        self.assert_original()

    def test_process_death_at_every_move_boundary_is_recoverable(self):
        for phase in ("prepared", "copying", "staged", "publication_gap", "published",
                      "sidecar_written", "tagged", "source_removed"):
            with self.subTest(phase=phase):
                self.crash(phase)
                if phase in ("prepared", "copying", "staged"):
                    self.assertFalse(self.destination.exists())
                self.assertEqual(1, len(self.journals()))
                result = ableton_tags.recover_transfers(self.journals())
                self.assertEqual({"recovered": 1, "errors": []}, result)
                self.assert_original()

    def test_recovery_itself_can_be_interrupted_and_retried(self):
        for phase in ("recovery_audio_restored", "recovery_sidecar_restored", "recovery_destination_removed"):
            with self.subTest(phase=phase):
                self.crash("source_removed")
                self.crash(phase)
                self.assertEqual({"recovered": 1, "errors": []},
                                 ableton_tags.recover_transfers(self.journals()))
                self.assert_original()

    def test_copy_interruption_keeps_source_and_restores_metadata(self):
        self.crash("sidecar_written", copy=True)
        self.assertTrue(self.source.exists())
        self.assertEqual({"recovered": 1, "errors": []}, ableton_tags.recover_transfers(self.journals()))
        self.assert_original()

    def test_duplicate_interruption_restores_both_original_tag_sets(self):
        self.destination.write_bytes(self.source.read_bytes())
        ableton_tags.prepare_edit([str(self.destination)], "Character|Destination").commit()
        for phase in ("published", "sidecar_written", "source_removed"):
            with self.subTest(phase=phase):
                self.crash(phase, duplicate=True)
                self.assertEqual({"recovered": 1, "errors": []},
                                 ableton_tags.recover_transfers(self.journals()))
                self.assert_original(duplicate=True)

    def test_committed_transfer_is_kept_and_only_recovery_files_are_cleaned(self):
        self.crash("committed")
        self.assertFalse(self.source.exists())
        self.assertTrue(self.destination.exists())
        self.assertEqual({"recovered": 1, "errors": []}, ableton_tags.recover_transfers(self.journals()))
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(str(self.destination)))
        self.assertFalse(self.source.exists())
        self.assertEqual([], self.journals())

    def test_interrupted_committed_cleanup_keeps_destination(self):
        self.crash("cleanup_stage_removed")
        self.assertFalse(self.source.exists())
        self.assertEqual(1, len(self.journals()))
        self.assertEqual({"recovered": 1, "errors": []}, ableton_tags.recover_transfers(self.journals()))
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(str(self.destination)))
        self.assertFalse(self.source.exists())
        self.assertEqual([], self.journals())

    @unittest.skipUnless(os.name == "nt", "Windows no-replace rename publication")
    def test_filesystem_without_hardlinks_uses_verified_same_volume_rename(self):
        with mock.patch.object(ableton_tags.os, "link", side_effect=OSError(errno.EOPNOTSUPP, "no links")):
            ableton_tags.transfer_sample(str(self.source), str(self.destination))
        self.assertFalse(self.source.exists())
        self.assertEqual(b"audio" * 100, self.destination.read_bytes())
        self.assertEqual(["Sounds|Source"], ableton_tags.sample_tags(str(self.destination)))
        self.assertEqual([], self.journals())

    def test_unsupported_publication_does_not_remove_original_or_leave_partial_final(self):
        with mock.patch.object(ableton_tags.os, "link", side_effect=OSError(errno.EXDEV, "unexpected volume")):
            with self.assertRaises(OSError):
                ableton_tags.transfer_sample(str(self.source), str(self.destination))
        self.assert_original()

    def test_changed_destination_blocks_recovery_without_touching_sidecars(self):
        self.crash("source_removed")
        self.destination.write_bytes(b"external edit")
        before = {path: path.read_bytes() for path in self.root.rglob("*.xmp")}
        result = ableton_tags.recover_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertTrue(result["errors"])
        self.assertFalse(self.source.exists())
        self.assertEqual(b"external edit", self.destination.read_bytes())
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*.xmp")})
        self.assertEqual(1, len(self.journals()))

    def test_external_metadata_change_blocks_recovery_without_touching_audio(self):
        self.crash("source_removed")
        ableton_tags.prepare_edit([str(self.destination)], "Character|External").commit()
        result = ableton_tags.recover_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertTrue(result["errors"])
        self.assertFalse(self.source.exists())
        self.assertTrue(self.destination.exists())
        self.assertIn("Character|External", ableton_tags.sample_tags(str(self.destination)))

    def test_pending_journal_blocks_a_new_transfer_into_same_folder(self):
        self.crash("published")
        other = self.source.parent / "other.wav"
        other.write_bytes(b"other")
        with self.assertRaisesRegex(ValueError, "recover"):
            ableton_tags.transfer_sample(str(other), str(self.destination.parent / "other.wav"))
        self.assertTrue(other.exists())
        self.assertFalse((self.destination.parent / "other.wav").exists())

    def test_recovery_is_retryable_after_restoring_changed_destination(self):
        self.crash("published")
        original = self.destination.read_bytes()
        self.destination.write_bytes(b"external")
        self.assertTrue(ableton_tags.recover_transfers(self.journals())["errors"])
        self.destination.write_bytes(original)
        # Explicit recovery compares content/ownership, not the timestamp of a repair.
        self.assertEqual({"recovered": 1, "errors": []}, ableton_tags.recover_transfers(self.journals()))
        self.assert_original()

    def test_recovery_scan_and_confirmation_use_background_jobs(self):
        panel = mock.MagicMock()
        panel.has_pending_job.return_value = False
        panel.winfo_toplevel.return_value._closing = False
        panel.library_dir_var.get.return_value = str(self.destination.parent)
        OrganizeTab.scan_transfer_recovery(panel)
        self.assertEqual("recovery_scan", panel._start_job.call_args.args[0])
        journal = str(self.destination.parent / "fixture.json")
        with mock.patch("tab_organize.ask_confirm", return_value=True):
            OrganizeTab.show_transfer_recovery(panel, [journal])
        self.assertEqual("transfer_recovery", panel._start_job.call_args.args[0])

    def test_completed_copy_preserves_readonly_mode(self):
        os.chmod(self.source, stat.S_IREAD)
        try:
            ableton_tags.transfer_sample(str(self.source), str(self.destination), copy=True)
            self.assertFalse(os.stat(self.destination).st_mode & stat.S_IWRITE)
        finally:
            for path in (self.source, self.destination):
                if path.exists():
                    os.chmod(path, stat.S_IWRITE)
        self.assertEqual([], self.journals())

    def test_completed_move_preserves_readonly_destination_mode(self):
        os.chmod(self.source, stat.S_IREAD)
        try:
            ableton_tags.transfer_sample(str(self.source), str(self.destination))
            self.assertFalse(self.source.exists())
            self.assertFalse(os.stat(self.destination).st_mode & stat.S_IWRITE)
        finally:
            for path in (self.source, self.destination):
                if path.exists():
                    os.chmod(path, stat.S_IWRITE)
        self.assertEqual([], self.journals())

    def test_modified_stage_is_not_deleted_or_used_for_recovery(self):
        self.crash("staged")
        journal_path = Path(self.journals()[0])
        journal = json.loads(journal_path.read_text())
        Path(journal["stage"]).write_bytes(b"external")
        result = ableton_tags.recover_transfers([str(journal_path)])
        self.assertEqual(0, result["recovered"])
        self.assertIn("Staged recovery audio changed", result["errors"][0])
        self.assertEqual(b"external", Path(journal["stage"]).read_bytes())
        self.assertTrue(journal_path.exists())
        self.assertTrue(self.source.exists())
        self.assertFalse(self.destination.exists())

    def test_invalid_journal_is_an_explicit_error_and_is_retained(self):
        folder = self.destination.parent / "Ableton Folder Info" / ableton_tags._RECOVERY_FOLDER
        folder.mkdir(parents=True)
        journal = folder / "broken.json"
        journal.write_text("{broken")
        result = ableton_tags.recover_transfers(self.journals())
        self.assertEqual(0, result["recovered"])
        self.assertTrue(result["errors"])
        self.assertTrue(journal.exists())
        self.assertTrue(self.source.exists())

    def test_recovery_scan_rejects_junctions(self):
        linked = self.destination.parent / "linked"
        try:
            linked.symlink_to(self.source.parent, target_is_directory=True)
        except OSError:
            if os.name != "nt":
                self.skipTest("Symlink creation unavailable")
            import _winapi
            _winapi.CreateJunction(str(self.source.parent), str(linked))
        with self.assertRaisesRegex(ValueError, "Linked"):
            self.journals()

    def test_finish_recovery_reports_conflicts_and_notifies_library(self):
        panel = mock.MagicMock()
        with mock.patch("tab_organize.show_notice") as notice:
            OrganizeTab.finish_transfer_recovery(panel, {
                "recovered": 1, "errors": ["changed file fixture"],
            })
        self.assertEqual("Recovery needs review", notice.call_args.kwargs["heading"])
        panel.write_console_message.assert_called_once()
        panel.winfo_toplevel().event_generate.assert_called_once_with("<<LibraryChanged>>", when="tail")


if __name__ == "__main__":
    unittest.main()

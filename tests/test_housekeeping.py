import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import housekeeping
import performance_log
import sorter_engine


class HousekeepingTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="housekeeping-test-", dir=Path(__file__).parent)
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)

    def log(self, session, age=100, size=4):
        directory = self.root / "performance_logs"
        directory.mkdir(exist_ok=True)
        path = directory / f"performance-{session}.jsonl"
        path.write_bytes(b"x" * size)
        locks = directory / ".locks"
        locks.mkdir(exist_ok=True)
        (locks / (session + ".active")).write_text("1073741824")
        os.utime(path, (time.time() - age, time.time() - age))
        return path

    def test_retention_age_size_and_unrecognized_files(self):
        old = self.log("a" * 32, age=1000)
        recent = self.log("b" * 32, age=100)
        newest = self.log("c" * 32, age=1)
        unknown = old.parent / "undo.jsonl"
        unknown.write_text("protected")
        errors = housekeeping.retain_performance_logs(old.parent, max_age=500, max_bytes=4)
        self.assertEqual([], errors)
        self.assertFalse(old.exists())
        self.assertFalse(recent.exists())
        self.assertTrue(newest.exists())
        self.assertTrue(unknown.exists())

    def test_active_pid_and_locked_session_are_protected(self):
        active = self.log("a" * 32)
        locked = self.log("b" * 32)
        locks = active.parent / ".locks"
        (locks / (("a" * 32) + ".active")).write_text(str(os.getpid()))
        with housekeeping.exclusive_lock(locks / (("b" * 32) + ".lock")) as acquired:
            self.assertTrue(acquired)
            self.assertEqual([], housekeeping.retain_performance_logs(active.parent, max_age=0))
            self.assertTrue(active.exists())
            self.assertTrue(locked.exists())
        housekeeping.retain_performance_logs(active.parent, max_age=0)
        self.assertTrue(active.exists())
        self.assertFalse(locked.exists())

    def test_bad_active_marker_reports_error_and_preserves_log(self):
        path = self.log("a" * 32)
        locks = path.parent / ".locks"
        (locks / (("a" * 32) + ".active")).write_text("bad")
        errors = housekeeping.retain_performance_logs(path.parent, max_age=0)
        self.assertTrue(errors)
        self.assertTrue(path.exists())

    def test_legacy_log_without_marker_is_preserved(self):
        path = self.log("a" * 32)
        (path.parent / ".locks" / (("a" * 32) + ".active")).unlink()
        self.assertEqual([], housekeeping.retain_performance_logs(path.parent, max_age=0))
        self.assertTrue(path.exists())

    def test_log_hook_tracks_redirected_profile_without_pruning_active_log(self):
        with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.root / "test.db")):
            performance_log.record("test", time.perf_counter())
            path = performance_log.log_directory() / f"performance-{performance_log.SESSION_ID}.jsonl"
            self.assertTrue(path.exists())
            housekeeping.retain_performance_logs(max_age=0)
            self.assertTrue(path.exists())

    def candidate(self, output, key, state="failed", pid=1073741824, compiler_pid=None):
        folder = output / ("candidate-" + key * 32)
        folder.mkdir(parents=True)
        marker = folder / ".alm-candidate.json"
        marker.write_text(json.dumps({"version": 2, "id": key * 32, "state": state,
                                      "pid": pid, "compiler_pid": compiler_pid}))
        (folder / "work").mkdir()
        (folder / "work" / "objects.bin").write_bytes(b"work")
        (folder / "work" / "base_library.zip").write_bytes(b"python libraries")
        (folder / "work" / "Analysis-00.toc").write_text("build table")
        (folder / "work" / "warn-AbletonLibraryManager.txt").write_text("build warnings")
        (folder / "dist").mkdir()
        (folder / "dist" / "app.exe").write_bytes(b"binary")
        os.utime(folder, (1, 1))
        return folder

    def test_failed_and_abandoned_candidates_pruned_by_age_and_size(self):
        output = self.root / "release_builds"
        failed = self.candidate(output, "a")
        abandoned = self.candidate(output, "b", "building", compiler_pid=1073741824)
        with mock.patch.object(housekeeping, "_running_under", return_value=False):
            removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=10, max_bytes=0)
        self.assertEqual([], errors)
        self.assertCountEqual([str(failed), str(abandoned)], removed)
        self.assertFalse(failed.exists())
        self.assertFalse(abandoned.exists())

    def test_size_cap_prunes_youngest_only_if_necessary(self):
        output = self.root / "release_builds"
        older = self.candidate(output, "a")
        newer = self.candidate(output, "b")
        os.utime(older, (90, 90))
        os.utime(newer, (95, 95))
        max_bytes = housekeeping._scan_tree(newer)
        with mock.patch.object(housekeeping, "_running_under", return_value=False):
            removed, errors = housekeeping.clean_candidates(output, now=100, max_age=1000, max_bytes=max_bytes)
        self.assertEqual([], errors)
        self.assertEqual([str(older)], removed)
        self.assertTrue(newer.exists())

    def test_candidate_restored_if_process_appears_during_quarantine(self):
        output = self.root / "release_builds"
        candidate = self.candidate(output, "a")
        with mock.patch.object(housekeeping, "_running_under", side_effect=[False, True]):
            removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0)
        self.assertEqual([], removed)
        self.assertTrue(any("running" in error for error in errors))
        self.assertTrue(candidate.exists())
        self.assertFalse(any(output.glob(".cleanup-*")))

    def test_active_locked_and_unknown_candidates_protected(self):
        output = self.root / "release_builds"
        active = self.candidate(output, "a", pid=os.getpid())
        locked = self.candidate(output, "b")
        app = self.candidate(output, "c")
        legacy = self.candidate(output, "d")
        (legacy / ".alm-candidate.json").write_text(json.dumps({"version": 1, "id": "d" * 32, "state": "failed"}))
        missing_compiler = self.candidate(output, "e", "building")
        with housekeeping.exclusive_lock(output / ".candidate-locks" / (("b" * 32) + ".lock")), \
             mock.patch.object(housekeeping, "_running_under", return_value=True):
            removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0, max_bytes=0)
        self.assertEqual([], removed)
        self.assertTrue(all(path.exists() for path in (active, locked, app, legacy, missing_compiler)))
        self.assertTrue(any("active" in error for error in errors))
        self.assertTrue(any("target" in error for error in errors))

    def test_private_and_unknown_contents_block_deletion(self):
        output = self.root / "release_builds"
        backup = self.candidate(output, "a")
        (backup / "work" / "library_config.json").write_text("protected")
        unknown = self.candidate(output, "b")
        (unknown / "my-recording.wav").write_bytes(b"safe")
        unmarked = output / ("candidate-" + "c" * 32)
        unmarked.mkdir()
        (unmarked / "work").mkdir()
        with mock.patch.object(housekeeping, "_running_under", return_value=False):
            removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0)
        self.assertEqual([], removed)
        self.assertTrue(errors)
        self.assertTrue((backup / "work" / "library_config.json").exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(unmarked.exists())

    @unittest.skipUnless(os.name == "nt", "Windows Restart Manager integration")
    def test_running_executable_prevents_real_candidate_cleanup(self):
        output = self.root / "release_builds"
        candidate = self.candidate(output, "a")
        exe = candidate / "dist" / "app.exe"
        shutil.copy2(sys.executable, exe)
        dll = Path(sys.base_prefix) / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        if dll.exists():
            shutil.copy2(dll, candidate / "dist" / dll.name)
        child = subprocess.Popen([str(exe), "-c", "import time; time.sleep(30)"],
                                 env={**os.environ, "PYTHONHOME": sys.base_prefix},
                                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            time.sleep(0.5)
            self.assertIsNone(child.poll(), child.stderr.read().decode(errors="replace") if child.poll() is not None else "")
            self.assertTrue(housekeeping._running_under(candidate))
            removed, errors = housekeeping.clean_candidates(output, now=time.time() + 100, max_age=0)
            self.assertEqual([], removed)
            self.assertTrue(any("running" in error for error in errors))
            self.assertTrue(exe.exists())
        finally:
            child.terminate()
            child.communicate(timeout=10)

    def test_protected_hard_link_blocks_deletion(self):
        output = self.root / "release_builds"
        candidate = self.candidate(output, "a")
        os.link(candidate / "work" / "objects.bin", self.root / "protected-copy")
        removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0)
        self.assertEqual([], removed)
        self.assertTrue(any("hard-linked" in error for error in errors))
        self.assertTrue(candidate.exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction integration")
    def test_junction_descendant_prevents_candidate_cleanup(self):
        output = self.root / "release_builds"
        candidate = self.candidate(output, "a")
        protected = self.root / "protected"
        protected.mkdir()
        (protected / "important.txt").write_text("preserve")
        junction = candidate / "work" / "linked"
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "New-Item -ItemType Junction -Path $env:FIXTURE_LINK -Target $env:FIXTURE_TARGET | Out-Null"],
                       env={**os.environ, "FIXTURE_LINK": str(junction), "FIXTURE_TARGET": str(protected)},
                       check=True, capture_output=True)
        removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0)
        self.assertEqual([], removed)
        self.assertTrue(any("linked" in error for error in errors))
        self.assertTrue((protected / "important.txt").exists())

    def test_validation_retains_distribution_prunes_only_work(self):
        output = self.root / "release_builds"
        candidate = self.candidate(output, "a", "complete")
        removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0)
        self.assertEqual([], removed)
        self.assertTrue(any("validated" in error for error in errors))
        housekeeping.mark_validated(candidate)
        os.utime(candidate, (1, 1))
        removed, errors = housekeeping.clean_candidates(output, now=1000, max_age=0)
        self.assertEqual([str(candidate / "work")], removed)
        self.assertEqual([], errors)
        self.assertTrue((candidate / "dist" / "app.exe").exists())

    def test_mark_validation_rejects_failed_and_locked_candidates(self):
        output = self.root / "release_builds"
        candidate = self.candidate(output, "a")
        with self.assertRaises(ValueError):
            housekeeping.mark_validated(candidate)
        with housekeeping.exclusive_lock(output / ".candidate-locks" / (("a" * 32) + ".lock")):
            with self.assertRaises(OSError):
                housekeeping.mark_validated(candidate)

    def test_storage_is_read_only_and_follows_index_redirect(self):
        (self.root / "move_logs").mkdir()
        (self.root / "move_logs" / "undo.json").write_bytes(b"undo")
        (self.root / "library_config.json.bak").write_bytes(b"backup")
        with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.root / "other.db")):
            summary = housekeeping.storage_summary(build_root=self.root / "builds", library_path=self.root / "library")
        self.assertEqual(str(self.root), summary["profile_directory"])
        self.assertEqual(4, summary["categories"]["Undo and move history"])
        self.assertEqual(6, summary["categories"]["Configuration backups"])
        self.assertEqual([], summary["errors"])
        self.assertTrue((self.root / "move_logs" / "undo.json").exists())

    def test_unreadable_storage_is_reported(self):
        with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.root / "other.db")):
            with mock.patch.object(Path, "lstat", side_effect=PermissionError("denied")):
                summary = housekeeping.storage_summary(build_root=self.root / "builds", library_path=self.root / "library")
        self.assertTrue(summary["errors"])
        self.assertIn("denied", summary["errors"][0])

    def test_summary_builds_and_selected_library_backups(self):
        builds = self.root / "builds"
        builds.mkdir()
        (builds / "binary").write_bytes(b"build")
        backups = self.root / "Ableton Library Backups"
        backups.mkdir()
        (backups / "User_Library_Backup_fixture.zip").write_bytes(b"backup")
        (backups / "other.zip").write_bytes(b"ignored")
        with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.root / "db")):
            summary = housekeeping.storage_summary(build_root=builds, library_path=self.root / "library")
        self.assertEqual(5, summary["categories"]["Build artifacts"])
        self.assertEqual(6, summary["categories"]["Library ZIP backups"])

    def test_summary_unknown_backup_location_is_not_zero(self):
        with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.root / "db")):
            summary = housekeeping.storage_summary(build_root=self.root / "builds", library_path="relative")
        self.assertIsNone(summary["categories"]["Library ZIP backups"])


if __name__ == "__main__":
    unittest.main()

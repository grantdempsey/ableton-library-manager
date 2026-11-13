import os
import queue
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

import gui_theme
import sorter_engine
from tab_import import ImportTab
from tab_organize import OrganizeTab
from tab_tags import TagsTab
from live_tag_batch import LiveTagBatchDialog


class LibraryJobTests(unittest.TestCase):
    def setUp(self):
        import library_jobs
        lock_directory = tempfile.TemporaryDirectory()
        self.addCleanup(lock_directory.cleanup)
        self.lock_path = Path(lock_directory.name) / "library_jobs.lock"
        self.jobs = library_jobs.LibraryJobCoordinator(lock_path=self.lock_path)
        for name, filename in (("ASSET_INDEX_FILE", "assets.db"), ("CONFIG_FILE", "config.json")):
            state = mock.patch.object(sorter_engine, name, str(Path(lock_directory.name) / filename))
            state.start()
            self.addCleanup(state.stop)
        patcher = mock.patch.object(library_jobs, "coordinator", self.jobs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = SimpleNamespace(_closing=False, _background_jobs=[])
        self.owner = SimpleNamespace(_root=lambda: self.root)

    def test_only_one_writer_can_claim_and_release_is_idempotent(self):
        first = self.jobs.claim("Import")
        self.assertIsNotNone(first)
        self.assertIsNone(self.jobs.claim("Undo"))
        self.assertEqual("Import", self.jobs.active_label)
        first.release()
        second = self.jobs.claim("Undo")
        first.release()
        self.assertEqual("Undo", self.jobs.active_label)
        second.release()
        self.assertIsNone(self.jobs.active_label)

    def test_atomic_claim_allows_exactly_one_of_concurrent_callers(self):
        barrier = threading.Barrier(8)
        leases = []
        def claim():
            barrier.wait()
            lease = self.jobs.claim("writer")
            if lease is not None:
                leases.append(lease)
        threads = [threading.Thread(target=claim) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(3)
            self.assertFalse(thread.is_alive())
        self.assertEqual(1, len(leases))
        leases[0].release()

    def test_process_claim_blocks_other_process_until_released(self):
        script = (
            "import sys; from library_jobs import LibraryJobCoordinator; "
            "jobs=LibraryJobCoordinator(lock_path=sys.argv[1]); "
            "lease=jobs.claim('child'); print('blocked' if lease is None else 'acquired'); "
            "lease.release() if lease is not None else None"
        )
        lease = self.jobs.claim("parent")
        self.assertIsNotNone(lease)
        try:
            blocked = subprocess.run(
                [sys.executable, "-c", script, os.fspath(self.lock_path)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(0, blocked.returncode, blocked.stderr)
            self.assertEqual("blocked", blocked.stdout.strip())
        finally:
            lease.release()

        available = subprocess.run(
            [sys.executable, "-c", script, os.fspath(self.lock_path)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, available.returncode, available.stderr)
        self.assertEqual("acquired", available.stdout.strip())

    def test_process_exit_releases_writer_lock_for_startup_recovery(self):
        script = (
            "import os,sys; from library_jobs import LibraryJobCoordinator; "
            "jobs=LibraryJobCoordinator(lock_path=sys.argv[1]); "
            "lease=jobs.claim('crashing writer'); "
            "print('locked' if lease is not None else 'blocked', flush=True); os._exit(79)"
        )
        crashed = subprocess.run(
            [sys.executable, "-c", script, os.fspath(self.lock_path)],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(79, crashed.returncode, crashed.stderr)
        self.assertEqual("locked", crashed.stdout.strip())
        lease = self.jobs.claim("startup recovery")
        self.assertIsNotNone(lease)
        lease.release()

    def test_background_job_holds_ownership_until_actual_work_finishes(self):
        entered, release = threading.Event(), threading.Event()
        def work():
            entered.set()
            release.wait(5)
        worker = gui_theme.start_background_job(
            self.owner, work, library_job="Live tag save", cancel=release.set,
        )
        self.assertTrue(entered.wait(2))
        with mock.patch("gui_theme.messagebox.showwarning") as notice:
            blocked = gui_theme.start_background_job(self.owner, lambda: self.fail("overlap"), library_job="Undo")
        self.assertIsNone(blocked)
        self.assertIn("Live tag save", notice.call_args.args[1])
        self.assertEqual(1, len(self.root._background_jobs))
        release.set()
        worker.join(3)
        self.assertIsNone(self.jobs.active_label)

    def test_worker_failure_and_thread_start_failure_release_ownership(self):
        error_seen = threading.Event()
        with mock.patch("threading.excepthook", side_effect=lambda _: error_seen.set()):
            def failing():
                raise OSError("fixture failure")
            worker = gui_theme.start_background_job(self.owner, failing, library_job="Repair")
            worker.join(3)
            self.assertTrue(error_seen.is_set())
        self.assertIsNone(self.jobs.active_label)
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("cannot start")):
            with self.assertRaises(RuntimeError):
                gui_theme.start_background_job(self.owner, lambda: None, library_job="Repair")
        self.assertIsNone(self.jobs.active_label)

    def test_closing_app_does_not_claim_or_start_work(self):
        self.root._closing = True
        self.assertIsNone(gui_theme.start_background_job(self.owner, lambda: self.fail("closing"), library_job="Import"))
        self.assertIsNone(self.jobs.active_label)

    def test_both_sorters_release_ownership_on_pipeline_or_start_failure(self):
        window = SimpleNamespace(after=lambda _delay, fn: fn())
        with tempfile.TemporaryDirectory() as scratch:
            for engine, planning in (
                (sorter_engine.ParallelLibrarySorter, "_routing_state"),
                (sorter_engine.SerumResourceImporter, "_resource_plan"),
            ):
                for failure in ("pipeline", "start"):
                    with self.subTest(engine=engine.__name__, failure=failure):
                        done = mock.Mock()
                        sorter = engine(scratch, scratch, window, lambda _: None, done)
                        patch = (
                            mock.patch.object(sorter, planning, side_effect=OSError("cannot read"))
                            if failure == "pipeline" else
                            mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("cannot start"))
                        )
                        with patch:
                            sorter.start_parallel_sort()
                            if sorter.worker_thread.ident is not None:
                                sorter.worker_thread.join(3)
                        self.assertIsNone(self.jobs.active_label)
                        self.assertEqual(1, len(sorter.operation_errors))
                        done.assert_called_once()

    def test_completion_callback_failure_cannot_keep_ownership(self):
        with tempfile.TemporaryDirectory() as scratch, mock.patch("threading.excepthook"):
            sorter = sorter_engine.ParallelLibrarySorter(
                scratch, scratch, SimpleNamespace(after=lambda _delay, fn: fn()),
                lambda _: None, mock.Mock(side_effect=RuntimeError("closing UI")),
            )
            sorter.cancel()
            sorter.start_parallel_sort()
            sorter.worker_thread.join(3)
        self.assertIsNone(self.jobs.active_label)

    def test_backup_retains_lease_until_cleanup_handoff(self):
        lease = self.jobs.claim("Backup and cleanup")
        worker = gui_theme.start_background_job(
            self.owner, lambda: None, lease=lease, release_lease=False,
        )
        worker.join(3)
        self.assertTrue(lease.active)
        self.assertIsNone(self.jobs.claim("Import"))
        with tempfile.TemporaryDirectory() as scratch, mock.patch.object(
            sorter_engine, "ASSET_INDEX_FILE", os.path.join(scratch, "assets.db")
        ):
            done = mock.Mock(side_effect=lambda *_: self.assertIsNone(self.jobs.active_label))
            sorter = sorter_engine.ParallelLibrarySorter(
                scratch, scratch, SimpleNamespace(after=lambda _delay, fn: fn()),
                lambda _: None, done,
            )
            sorter.start_parallel_sort(job_lease=lease)
            sorter.worker_thread.join(3)
            self.assertFalse(sorter.is_running())
            done.assert_called_once()
            self.assertEqual([], sorter.operation_errors)
        self.assertFalse(lease.active)

    def test_unexpected_backup_worker_failure_releases_retained_lease(self):
        lease = self.jobs.claim("Backup and cleanup")
        with mock.patch("threading.excepthook"):
            def failing():
                raise RuntimeError("fixture")
            worker = gui_theme.start_background_job(
                self.owner, failing, lease=lease, release_lease=False,
            )
            worker.join(3)
        self.assertFalse(lease.active)

    def test_expired_lease_cannot_authorize_worker(self):
        lease = self.jobs.claim("Old job")
        lease.release()
        with self.jobs.claim("New job"):
            with self.assertRaisesRegex(ValueError, "expired"):
                gui_theme.start_background_job(self.owner, lambda: self.fail("overlap"), lease=lease)
        self.assertIsNone(self.jobs.active_label)

    def test_sync_claim_context_releases_after_exception(self):
        with self.assertRaises(OSError):
            with self.jobs.claim("Favorite"):
                raise OSError("fixture")
        self.assertIsNone(self.jobs.active_label)

    def test_sorters_refuse_other_jobs_and_complete_once_without_writes(self):
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / "incoming"
            source.mkdir()
            (source / "kick.wav").write_bytes(b"audio")
            for worker_type in (sorter_engine.ParallelLibrarySorter, sorter_engine.SerumResourceImporter):
                with self.subTest(worker=worker_type.__name__), self.jobs.claim("Tag save"):
                    done = mock.Mock()
                    worker = worker_type(
                        str(source), str(Path(scratch) / "library"),
                        SimpleNamespace(after=lambda _delay, fn: fn()), lambda _: None, done,
                        copy_mode=True,
                    )
                    worker.start_parallel_sort()
                    self.assertFalse(worker.is_running())
                    done.assert_called_once()
                    self.assertEqual(1, len(worker.operation_errors))
                    self.assertIn("Tag save", worker.operation_errors[0]["error"])
                    self.assertFalse((Path(scratch) / "library").exists())

    def test_scan_cancel_releases_sorter_lease_before_completion(self):
        with tempfile.TemporaryDirectory() as scratch:
            done = mock.Mock(side_effect=lambda *_: self.assertIsNone(self.jobs.active_label))
            worker = sorter_engine.ParallelLibrarySorter(
                scratch, os.path.join(scratch, "library"),
                SimpleNamespace(after=lambda _delay, fn: fn()), lambda _: None, done,
            )
            worker.cancel()
            worker.start_parallel_sort()
            worker.worker_thread.join(3)
            self.assertFalse(worker.worker_thread.is_alive(), "Cancelled worker did not finish")
            done.assert_called_once()
            self.assertIsNone(self.jobs.active_label)

    def test_import_busy_does_not_create_destination_or_disable_controls(self):
        with tempfile.TemporaryDirectory() as scratch, self.jobs.claim("Cleanup"):
            panel = mock.MagicMock()
            panel.winfo_toplevel.return_value._closing = False
            panel.src_dir_var.get.return_value = scratch
            panel.dest_dir_var.get.return_value = os.path.join(scratch, "new")
            panel.active_sorter = None
            panel._undo_pending = False
            panel._selected_scope.return_value = (False, True)
            with mock.patch("gui_theme.messagebox.showwarning") as notice, mock.patch(
                "tab_import.ParallelLibrarySorter"
            ) as worker:
                ImportTab._start_import(panel, preview=True)
            notice.assert_called_once()
            worker.assert_not_called()
            panel.run_btn.config.assert_not_called()
            self.assertFalse(Path(scratch, "new").exists())

    def test_organize_busy_restores_job_controls_and_never_queues_work(self):
        panel = mock.MagicMock()
        panel.has_pending_job.return_value = False
        panel.winfo_toplevel.return_value._closing = False
        panel.library_dir_var.get.return_value = "library"
        with self.jobs.claim("Import"), mock.patch("gui_theme.messagebox.showwarning"), mock.patch(
            "gui_theme.start_background_job", wraps=gui_theme.start_background_job
        ):
            result = OrganizeTab._start_job(panel, "undo", lambda: self.fail("must not run"))
        self.assertFalse(result)
        self.assertFalse(panel._job_pending)
        panel._restore_job_controls.assert_called_once()

    def test_tag_save_busy_keeps_reviewed_plan_and_buttons_usable(self):
        panel = mock.MagicMock()
        panel.busy = False
        plan = panel.plan
        with self.jobs.claim("Cleanup"), mock.patch("gui_theme.messagebox.showwarning"):
            LiveTagBatchDialog.save(panel)
        plan.commit.assert_not_called()
        self.assertIs(panel.plan, plan)
        panel.set_busy.assert_not_called()

    def test_favorite_busy_does_not_change_index(self):
        panel = mock.MagicMock()
        panel._selected_paths.return_value = ["sample.wav"]
        panel._asset_paths = {"row": "sample.wav"}
        with self.jobs.claim("Recovery"), mock.patch("gui_theme.messagebox.showwarning"), mock.patch.object(
            sorter_engine, "bulk_update_asset_tags"
        ) as write:
            self.assertFalse(TagsTab._update_selected_tag(panel, "favorite"))
        write.assert_not_called()

    def test_monitor_defers_silently_while_other_job_owns_library(self):
        panel = mock.MagicMock()
        panel.winfo_toplevel.return_value._closing = False
        panel.monitor_live_var.get.return_value = True
        panel._tab_is_visible.return_value = True
        panel._refresh_running = False
        panel._live_refresh_queue = None
        panel._live_batch_dialog = None
        panel._metadata_root = gui_theme.USER_LIBRARY_PATH
        with self.jobs.claim("Import"), mock.patch("gui_theme.messagebox.showwarning") as notice, mock.patch(
            "tab_tags.live_tag_sync.poll_live_metadata"
        ) as poll:
            TagsTab._poll_live_metadata(panel)
        poll.assert_not_called()
        notice.assert_not_called()
        panel.after.assert_called_with(5000, panel._poll_live_metadata)

    def test_manual_rescan_refuses_and_automatic_rescan_retries_while_busy(self):
        with tempfile.TemporaryDirectory() as scratch, mock.patch.object(
            gui_theme, "USER_LIBRARY_PATH", scratch
        ), self.jobs.claim("Import"):
            panel = mock.MagicMock()
            panel.winfo_toplevel.return_value._closing = False
            panel._refresh_running = False
            panel._metadata_queue = None
            panel._live_refresh_queue = None
            panel._live_batch_dialog = None
            with mock.patch("gui_theme.messagebox.showwarning") as notice:
                TagsTab.rescan_library(panel)
                notice.assert_called_once()
                notice.reset_mock()
                TagsTab.rescan_library(panel, notify_busy=False)
                notice.assert_not_called()
            panel._discover_then_refresh.assert_not_called()
            self.assertFalse(panel._refresh_running)
            self.assertEqual(500, panel.after.call_args.args[0])

    def test_pending_import_object_is_not_replaced_by_second_start(self):
        panel = mock.MagicMock()
        panel.winfo_toplevel.return_value._closing = False
        panel.active_sorter.is_running.return_value = True
        active = panel.active_sorter
        with self.jobs.claim("Import"), mock.patch("gui_theme.messagebox.showwarning") as notice:
            ImportTab._start_import(panel, preview=True)
        self.assertIs(active, panel.active_sorter)
        panel.src_dir_var.get.assert_not_called()
        notice.assert_called_once()

    def test_index_worker_start_failures_surface_errors_and_restore_controls(self):
        with tempfile.TemporaryDirectory() as scratch, mock.patch.object(
            gui_theme, "USER_LIBRARY_PATH", scratch
        ):
            for operation in ("selected", "monitor", "rescan"):
                with self.subTest(operation=operation):
                    panel = mock.MagicMock()
                    panel._root.return_value = self.root
                    panel.winfo_toplevel.return_value._closing = False
                    panel._metadata_queue = None
                    panel._live_refresh_queue = None
                    panel._live_batch_dialog = None
                    panel._refresh_running = False
                    panel._library_work_results = queue.Queue()
                    panel._selected_paths.return_value = ("fixture.wav",)
                    with mock.patch.object(
                        threading.Thread, "start", side_effect=RuntimeError("cannot start")
                    ), mock.patch("tab_tags.messagebox.showerror") as notice:
                        if operation == "selected":
                            TagsTab._refresh_selected_live_tags(panel)
                            TagsTab._finish_selected_live_refresh(panel, 1)
                        elif operation == "monitor":
                            TagsTab._poll_live_metadata(panel)
                            TagsTab._finish_metadata_poll(panel, scratch)
                        else:
                            TagsTab.rescan_library(panel)
                            kind, result, error, _generation = panel._library_work_results.get_nowait()
                            self.assertEqual("scan", kind)
                            TagsTab._finish_refresh(panel, result, error)
                            panel.rescan_button.configure.assert_called_with(state="normal")
                        if operation != "monitor":
                            notice.assert_called_once()
                    self.assertIsNone(self.jobs.active_label)
                    self.assertIsNone(panel._live_refresh_queue)
                    self.assertIsNone(panel._metadata_queue)
                    self.assertFalse(panel._refresh_running)
                    panel._set_freshness.assert_called()

    def test_tag_save_start_failure_is_reported_and_releases_job(self):
        panel = mock.MagicMock()
        panel._root.return_value = self.root
        panel.busy = False
        with mock.patch.object(threading.Thread, "start", side_effect=RuntimeError("cannot start")):
            LiveTagBatchDialog.save(panel)
        self.assertIsNone(self.jobs.active_label)
        panel.results.put.assert_called_once()
        self.assertEqual("save", panel.results.put.call_args.args[0][0])
        self.assertIsInstance(panel.results.put.call_args.args[0][2], RuntimeError)
        panel.after.assert_called_once_with(30, panel.finish)


if __name__ == "__main__":
    unittest.main()

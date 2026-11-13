import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

import live_tag_sync
import performance_log
import sorter_engine
from tab_organize import OrganizeTab


class PerformanceLogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for target, name, value in (
            (sorter_engine, "ASSET_INDEX_FILE", str(self.root / "assets.db")),
            (sorter_engine, "CONFIG_FILE", str(self.root / "config.json")),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def records(self):
        return [
            json.loads(line)
            for path in performance_log.log_directory().glob("*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()
        ]

    def test_records_timings_without_library_content(self):
        performance_log.record(
            "import", time.perf_counter() - 0.01,
            files=3, search="private query", filename="private.wav", tags=["Drums|Kick"],
        )
        record = self.records()[0]
        self.assertGreaterEqual(record["seconds"], 0.01)
        self.assertEqual(3, record["files"])
        self.assertNotIn("search", record)
        self.assertNotIn("filename", record)
        self.assertNotIn("tags", record)

    def test_decorator_preserves_failures_without_recording_error_text(self):
        @performance_log.timed("sidecar_poll")
        def fail():
            raise ValueError("private path and tag")
        with self.assertRaisesRegex(ValueError, "private path"):
            fail()
        record = self.records()[0]
        self.assertEqual("failed", record["outcome"])
        self.assertEqual("ValueError", record["error_type"])
        self.assertNotIn("private", json.dumps(record))

    def test_log_failure_is_reported_without_interrupting_operation(self):
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")), self.assertLogs(
            "performance_log", level="WARNING"
        ):
            performance_log.record("import", time.perf_counter())

    def test_invalid_measurement_is_reported_without_interrupting_operation(self):
        with self.assertLogs("performance_log", level="WARNING"):
            performance_log.record("import", time.perf_counter(), files=float("nan"))

    def test_metrics_collection_failure_preserves_success(self):
        def metrics(_result):
            raise OSError("unavailable measurement")
        measured = performance_log.timed("backup", metrics)(lambda: "success")
        with self.assertLogs("performance_log", level="WARNING"):
            self.assertEqual("success", measured())
        self.assertEqual("measurement_failed", self.records()[0]["outcome"])

    def test_timed_records_aggregate_named_phase_durations(self):
        @performance_log.timed("browser")
        def render():
            with performance_log.measure_phase("query"):
                pass
            with performance_log.measure_phase("query"):
                pass
            return "rendered"

        self.assertEqual("rendered", render())
        record = self.records()[0]
        self.assertGreaterEqual(record["phase_query_seconds"], 0)
        self.assertNotIn("phase_render_seconds", record)

    def test_logging_failure_preserves_original_exception(self):
        measured = performance_log.timed("backup")(lambda: (_ for _ in ()).throw(ValueError("original")))
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("denied")), self.assertLogs(
            "performance_log", level="WARNING"
        ), self.assertRaisesRegex(ValueError, "original"):
            measured()

    def test_concurrent_records_remain_valid_json(self):
        threads = [
            threading.Thread(target=performance_log.record, args=("import", time.perf_counter()), kwargs={"files": n})
            for n in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(set(range(20)), {record["files"] for record in self.records()})

    def test_rotation_keeps_previous_segment(self):
        performance_log.record("first", time.perf_counter())
        with mock.patch.object(performance_log, "MAX_LOG_BYTES", 1):
            performance_log.record("second", time.perf_counter())
        self.assertEqual("second", self.records()[0]["operation"])
        previous = list(performance_log.log_directory().glob("*.previous"))
        self.assertEqual(1, len(previous))
        self.assertEqual("first", json.loads(previous[0].read_text())["operation"])

    def test_real_backup_and_poll_emit_automatic_records(self):
        library = self.root / "library"
        library.mkdir()
        sample = library / "private.wav"
        sample.write_bytes(b"audio")
        sorter_engine.index_asset(str(sample), str(library), "test", 1.0, [])
        live_tag_sync.poll_live_metadata(str(library))
        page = SimpleNamespace(
            get_backup_directory=lambda _: str(self.root / "backups"),
            write_console_message=lambda _: None,
        )
        OrganizeTab.run_safeguard_archiver_thread(page, str(library))
        records = {record["operation"]: record for record in self.records()}
        self.assertEqual(1, records["sidecar_poll"]["indexed_records"])
        self.assertGreaterEqual(records["sidecar_poll"]["phase_scope_seconds"], 0)
        self.assertGreaterEqual(records["sidecar_poll"]["phase_fingerprint_seconds"], 0)
        self.assertEqual(1, records["library_backup"]["files"])
        self.assertEqual(5, records["library_backup"]["source_bytes"])
        self.assertNotIn("private.wav", json.dumps(records))

    def test_sorter_logs_completion_and_cancellation_without_extra_scans(self):
        sorter = sorter_engine.ParallelLibrarySorter(
            str(self.root / "incoming"), str(self.root / "library"),
            SimpleNamespace(after=lambda _delay, callback: callback()),
            lambda _: None, lambda *_: None, copy_mode=True,
        )
        sorter.total_files = sorter.processed_files = 1
        sorter.operation_plan = [{
            "source": "private.wav", "source_identity": {"size": 50}, "action": "copy",
        }]
        sorter._completed_plan_sources.add("private.wav")
        sorter.cancel()
        sorter._record_performance(time.perf_counter() - 1)
        record = self.records()[0]
        self.assertEqual("cancelled", record["outcome"])
        self.assertEqual(1, record["completed_files"])
        self.assertEqual(50, record["transferred_bytes"])
        self.assertGreaterEqual(record["cancellation_seconds"], 0)
        self.assertNotIn("private.wav", json.dumps(record))

    def test_normal_sorter_worker_writes_log_before_done_callback(self):
        import library_jobs
        incoming = self.root / "incoming"
        incoming.mkdir()
        (incoming / "kick.wav").write_bytes(b"audio")
        done = threading.Event()
        sorter = sorter_engine.ParallelLibrarySorter(
            str(incoming), str(self.root / "library"),
            SimpleNamespace(after=lambda _delay, callback: callback()),
            lambda _: None, lambda *_: done.set(), copy_mode=True, smart_learning_enabled=False,
        )
        with mock.patch.object(library_jobs, "coordinator", library_jobs.LibraryJobCoordinator(
            self.root / "jobs.lock"
        )):
            sorter.start_parallel_sort()
            self.assertTrue(done.wait(30))
            sorter.worker_thread.join()
        record = next(record for record in self.records() if record["operation"] == "import")
        self.assertEqual("completed", record["outcome"])
        self.assertEqual(1, record["completed_files"])
        self.assertEqual(5, record["transferred_bytes"])


if __name__ == "__main__":
    unittest.main()

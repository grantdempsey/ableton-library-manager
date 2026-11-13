import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

import library_state


class LibraryStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.legacy = self.root / "legacy"
        self.stable = self.root / "stable"
        self.legacy.mkdir()

    def make_database(self, path):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE state (value TEXT)")
            connection.execute("INSERT INTO state VALUES ('favorite survives')")
            connection.commit()

    def test_platform_storage_paths_are_stable_per_user(self):
        self.assertEqual(
            os.path.join("C:\\Users\\fixture\\AppData\\Local", "AbletonLibraryManager"),
            library_state.user_data_directory(
                system="win32", home="C:\\Users\\fixture",
                environment={"LOCALAPPDATA": "C:\\Users\\fixture\\AppData\\Local"},
            ),
        )
        self.assertEqual(
            os.path.abspath("/Users/fixture/Library/Application Support/AbletonLibraryManager"),
            library_state.user_data_directory(system="darwin", home="/Users/fixture", environment={}),
        )
        self.assertEqual(
            os.path.abspath("/home/fixture/custom/AbletonLibraryManager"),
            library_state.user_data_directory(
                system="linux", home="/home/fixture",
                environment={"XDG_DATA_HOME": "/home/fixture/custom"},
            ),
        )

    def test_migration_copies_settings_database_cache_backups_and_logs(self):
        (self.legacy / "library_config.json").write_text(
            json.dumps({"ACTIVE_LIBRARY_PATH": "C:\\Ableton\\User Library", "XO_CUSTOM_TYPES": {"Keep": ["tag"]}}),
            encoding="utf-8",
        )
        self.make_database(self.legacy / "library_assets.db")
        (self.legacy / "saved_searches.json").write_text('[{"name":"Kicks"}]', encoding="utf-8")
        (self.legacy / "sidebar_cache.json").write_text('{"old":true}', encoding="utf-8")
        backups = self.legacy / "config_backups"
        logs = self.legacy / "move_logs"
        backups.mkdir()
        logs.mkdir()
        (backups / "library_config_1.json").write_text('{"old":"rules"}', encoding="utf-8")
        (logs / "duplicate-1.audio").write_bytes(b"undo audio")
        old_log = logs / "moves_1.jsonl"
        old_log.write_text(json.dumps({"source": "a", "destination": "b",
                                       "recovery": str(logs / "duplicate-1.audio")}) + "\n", encoding="utf-8")

        warnings = library_state.migrate_legacy_state([self.legacy], self.stable)

        self.assertEqual([], warnings)
        for name in ("library_config.json", "library_assets.db", "saved_searches.json", "sidebar_cache.json"):
            self.assertTrue((self.stable / name).is_file())
            self.assertTrue((self.legacy / name).is_file())
        with closing(sqlite3.connect(self.stable / "library_assets.db")) as connection:
            self.assertEqual(("favorite survives",), connection.execute("SELECT value FROM state").fetchone())
            self.assertEqual(("ok",), connection.execute("PRAGMA integrity_check").fetchone())
        migrated_log = self.stable / "move_logs" / old_log.name
        record = json.loads(migrated_log.read_text(encoding="utf-8"))
        self.assertEqual(str(self.stable / "move_logs" / "duplicate-1.audio"), record["recovery"])
        self.assertTrue((self.legacy / "move_logs" / "duplicate-1.audio").is_file())

    def test_repeat_migration_is_idempotent_and_records_legacy_path_aliases(self):
        source = self.legacy / "library_config.json"
        source.write_text('{"setting":1}', encoding="utf-8")
        (self.legacy / "move_logs").mkdir()
        old_log = self.legacy / "move_logs" / "moves_1.jsonl"
        old_log.write_text('{"source":"a","destination":"b"}\n', encoding="utf-8")
        library_state.migrate_legacy_state([self.legacy], self.stable)
        before = (self.stable / "move_logs" / old_log.name).stat().st_mtime_ns
        warnings = library_state.migrate_legacy_state([self.legacy], self.stable)
        self.assertEqual([], warnings)
        self.assertEqual(before, (self.stable / "move_logs" / old_log.name).stat().st_mtime_ns)
        alias_file = self.stable / "legacy_path_aliases.json"
        self.assertEqual(
            str(self.stable / "move_logs" / old_log.name),
            library_state.resolve_legacy_path(str(old_log), alias_file),
        )

    def test_differing_existing_stable_files_are_never_overwritten(self):
        self.stable.mkdir()
        (self.stable / "library_config.json").write_text('{"active":"new"}', encoding="utf-8")
        (self.legacy / "library_config.json").write_text('{"active":"old"}', encoding="utf-8")
        (self.legacy / "move_logs").mkdir()
        (self.legacy / "move_logs" / "moves_old.jsonl").write_text('{"old":true}\n', encoding="utf-8")
        warnings = library_state.migrate_legacy_state([self.legacy], self.stable)
        self.assertEqual('{"active":"new"}', (self.stable / "library_config.json").read_text())
        self.assertEqual('{"active":"old"}', (self.legacy / "library_config.json").read_text())
        self.assertFalse((self.stable / "move_logs" / "moves_old.jsonl").exists())
        self.assertTrue((self.legacy / "move_logs" / "moves_old.jsonl").is_file())
        self.assertTrue(any("conflicting legacy library_config.json" in warning for warning in warnings))

    def test_existing_database_conflict_with_wal_skips_the_legacy_profile(self):
        self.stable.mkdir()
        source = self.legacy / "library_assets.db"
        self.make_database(source)
        with closing(sqlite3.connect(source)) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.commit()
        (self.stable / source.name).write_bytes(source.read_bytes())
        connection = sqlite3.connect(source)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("INSERT INTO state VALUES ('wal-only value')")
            connection.commit()

            (self.legacy / "move_logs").mkdir()
            (self.legacy / "move_logs" / "moves_old.jsonl").write_text('{"old":true}\n', encoding="utf-8")
            warnings = library_state.migrate_legacy_state([self.legacy], self.stable)

            self.assertTrue(any("conflicting legacy library_assets.db" in warning for warning in warnings))
            self.assertFalse((self.stable / "move_logs" / "moves_old.jsonl").exists())
            self.assertEqual(
                ("wal-only value",),
                connection.execute("SELECT value FROM state WHERE value='wal-only value'").fetchone(),
            )
        finally:
            connection.close()

    def test_conflicting_move_log_is_renamed_and_both_logs_are_preserved(self):
        old_logs = self.legacy / "move_logs"
        new_logs = self.stable / "move_logs"
        old_logs.mkdir()
        new_logs.mkdir(parents=True)
        (old_logs / "moves_same.jsonl").write_text('{"old":true}\n', encoding="utf-8")
        (new_logs / "moves_same.jsonl").write_text('{"new":true}\n', encoding="utf-8")
        library_state.migrate_legacy_state([self.legacy], self.stable)
        self.assertEqual('{"new":true}\n', (new_logs / "moves_same.jsonl").read_text())
        self.assertEqual('{"old":true}\n', (old_logs / "moves_same.jsonl").read_text())
        self.assertEqual(2, len(list(new_logs.glob("*.jsonl"))))

    def test_failed_sqlite_copy_leaves_source_and_fails_closed(self):
        broken = self.legacy / "library_assets.db"
        broken.write_bytes(b"not sqlite")
        with self.assertRaises(library_state.StateMigrationError):
            library_state.migrate_legacy_state([self.legacy], self.stable)
        self.assertEqual(b"not sqlite", broken.read_bytes())
        self.assertFalse((self.stable / "library_assets.db").exists())

    def test_linked_legacy_database_is_refused_without_following_it(self):
        source = self.legacy / "outside.db"
        self.make_database(source)
        linked = self.legacy / "library_assets.db"
        try:
            linked.symlink_to(source)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(library_state.StateMigrationError):
            library_state.migrate_legacy_state([self.legacy], self.stable)
        self.assertTrue(source.is_file())
        self.assertTrue(linked.is_symlink())

    def test_changed_legacy_source_after_first_copy_is_preserved_as_conflict(self):
        source = self.legacy / "saved_searches.json"
        source.write_text('{"version":1}', encoding="utf-8")
        library_state.migrate_legacy_state([self.legacy], self.stable)
        source.write_text('{"version":2}', encoding="utf-8")
        warnings = library_state.migrate_legacy_state([self.legacy], self.stable)
        self.assertEqual('{"version":1}', (self.stable / source.name).read_text())
        self.assertEqual('{"version":2}', source.read_text())
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()

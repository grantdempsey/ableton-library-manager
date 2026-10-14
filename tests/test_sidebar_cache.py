import os
import tempfile
import unittest
from unittest import mock

import sorter_engine


class SidebarSnapshotTests(unittest.TestCase):
    def test_snapshot_round_trip_and_invalidation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db = os.path.join(temp_dir, "assets.db")
            with open(db, "wb") as handle:
                handle.write(b"one")
            with mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", db):
                counts = {"All sounds": 5, "Loops": 2, "One-shots": 3, "MIDI": 0}
                fingerprint = sorter_engine._index_fingerprint()
                sorter_engine.save_sidebar_snapshot("root", counts, 1, [("kick", 3)], fingerprint)
                snapshot = sorter_engine.load_sidebar_snapshot("root")
                self.assertEqual(snapshot["static_counts"], counts)
                self.assertEqual(snapshot["favorites"], 1)
                self.assertEqual(snapshot["tags"], [("kick", 3)])
                self.assertIsNone(sorter_engine.load_sidebar_snapshot("other root"))
                with open(db, "wb") as handle:
                    handle.write(b"changed contents")
                self.assertIsNone(sorter_engine.load_sidebar_snapshot("root"))


if __name__ == "__main__":
    unittest.main()

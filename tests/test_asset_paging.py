import os
import unittest

import sorter_engine


class AssetPagingTests(unittest.TestCase):
    def setUp(self):
        self.original_db = sorter_engine.ASSET_INDEX_FILE
        self.temp_dir = self._make_temp_dir()
        sorter_engine.ASSET_INDEX_FILE = os.path.join(self.temp_dir, "assets.db")

    def tearDown(self):
        sorter_engine.ASSET_INDEX_FILE = self.original_db
        self._cleanup_temp_dir()

    def _make_temp_dir(self):
        import tempfile
        return tempfile.mkdtemp()

    def _cleanup_temp_dir(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_asset_results_can_be_paged_without_the_old_cap(self):
        for index in range(3):
            path = os.path.join(self.temp_dir, f"sound_{index}.wav")
            with open(path, "wb") as sound_file:
                sound_file.write(b"audio")
            sorter_engine.index_asset(path, "Sounds", "test", 1.0, [])

        first = sorter_engine.list_indexed_assets(limit=2, offset=0)
        second = sorter_engine.list_indexed_assets(limit=2, offset=2)
        self.assertEqual(2, len(first))
        self.assertEqual(1, len(second))


if __name__ == "__main__":
    unittest.main()

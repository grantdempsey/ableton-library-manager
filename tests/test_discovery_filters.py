import os
import tempfile
import unittest
from unittest import mock

import ableton_tags
import sorter_engine


class DiscoveryFilterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = self.temporary.name
        patcher = mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.root, "assets.db"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.paths = []
        for filename, local, live in (
            ("deep_kick.wav", ["favorite", "category:Review"], ["Sounds|Bass", "Character|Warm"]),
            ("bright_kick.wav", ["category:Review"], ["Sounds|Bass"]),
            ("raw_kick.wav", ["category:Review"], []),
            ("loose_kick.wav", [], ["Character|Bright"]),
        ):
            path = os.path.join(self.root, "One-Shots", filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(b"audio")
            sorter_engine.index_asset(path, os.path.dirname(path), "test", 1, local)
            for tag in live:
                ableton_tags.prepare_edit([path], tag).commit()
            self.paths.append(path)
        sorter_engine.refresh_live_tag_cache(self.paths)

    def assert_query(self, query, expected, **kwargs):
        arguments = dict(search_text=query, library_root=self.root, **kwargs)
        records = sorter_engine.list_indexed_assets(**arguments, limit=-1)
        paths = sorter_engine.list_indexed_assets(**arguments, limit=-1, paths_only=True)
        self.assertEqual(set(expected), {record["path"] for record in records})
        self.assertEqual(set(expected), set(paths))
        self.assertEqual(len(expected), sorter_engine.count_indexed_assets(**arguments))
        paged = [
            row["path"] for offset in range(len(expected))
            for row in sorter_engine.list_indexed_assets(**arguments, limit=1, offset=offset)
        ]
        self.assertEqual(paths, paged)
        facet_kwargs = {key: value for key, value in arguments.items() if key != "tag_filter"}
        if "tag_filter" not in arguments:
            expected_counts = {}
            for record in records:
                for tag in record["tags"]:
                    expected_counts[tag] = expected_counts.get(tag, 0) + 1
            self.assertEqual(expected_counts, dict(sorter_engine.list_indexed_tags(**facet_kwargs)))

    def test_manual_presence_and_missing_group_keep_counts_facets_and_paths_consistent(self):
        self.assert_query("live:none", self.paths[2:3])
        self.assert_query("live:tagged", [self.paths[0], self.paths[1], self.paths[3]])
        self.assert_query("missing-group:Character", self.paths[1:3])
        self.assert_query("missing-group:Sounds", self.paths[2:])
        self.assert_query("type:one-shot missing-group:Character tag:category:review", self.paths[1:3])
        self.assert_query("live:tagged missing-group:Character", self.paths[1:2])
        self.assert_query("live:none live:tagged", [])

    def test_any_all_and_excluded_tags_compose_with_existing_filters(self):
        self.assert_query('"tag:ableton:Sounds|Bass" "tag:ableton:Character|Warm"', self.paths[:1])
        self.assert_query('"anytag:ableton:Sounds|Bass" anytag:favorite', self.paths[:2])
        self.assert_query('"anytag:ableton:Sounds|Bass" "anytag:ableton:Character|Bright"', [self.paths[0], self.paths[1], self.paths[3]])
        self.assert_query('anytag:category:review anytag:favorite -tag:favorite', self.paths[1:3])
        self.assert_query('anytag:category:review missing-group:Character', self.paths[1:3])
        self.assert_query('anytag:category:review', self.paths[:1], favorites_only=True)
        self.assert_query('live:none', self.paths[2:3], tag_filter="category:Review")

    def test_group_matching_is_case_insensitive_literal_and_source_specific(self):
        path = self.paths[2]
        connection = sorter_engine._asset_index_connection()
        with connection:
            connection.execute(
                "INSERT INTO asset_tags VALUES (?, 'Character|Local does not count', 1, 'personal')", (path,)
            )
        connection.close()
        ableton_tags.prepare_edit([path], "Char_acter|Special").commit()
        sorter_engine.refresh_live_tag_cache([path])
        self.assert_query("missing-group:CHARACTER", self.paths[1:3])
        self.assert_query("missing-group:Char_acter", [self.paths[0], self.paths[1], self.paths[3]])
        self.assert_query("missing-group:Char%", self.paths)
        self.assert_query("missing-group:Char", self.paths)

    def test_quoted_full_hierarchies_and_group_names(self):
        ableton_tags.prepare_edit(self.paths[:1], "Custom Group|Multi Word").commit()
        sorter_engine.refresh_live_tag_cache(self.paths[:1])
        self.assert_query('"anytag:ableton:Custom Group|Multi Word"', self.paths[:1])
        self.assert_query('"missing-group:Custom Group"', self.paths[1:])

    def test_external_removal_changes_discovery_after_cache_refresh(self):
        ableton_tags.prepare_edit(self.paths[:1], "Character|Warm", remove=True).commit()
        self.assert_query("missing-group:Character", self.paths[1:3])
        sorter_engine.refresh_live_tag_cache(self.paths[:1])
        self.assert_query("missing-group:Character", self.paths[:3])

    def test_malformed_discovery_filters_fail_explicitly_everywhere(self):
        for query in ("live:unknown", "-live:none", "anytag:", "missing-group:", "missing-group:Sounds|Bass"):
            for function in (
                lambda: sorter_engine.list_indexed_assets(query),
                lambda: sorter_engine.count_indexed_assets(search_text=query),
                lambda: sorter_engine.list_indexed_tags(search_text=query),
            ):
                with self.subTest(query=query), self.assertRaises(ValueError):
                    function()

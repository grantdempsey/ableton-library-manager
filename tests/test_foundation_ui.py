import importlib.machinery
import importlib.util
import gc
import os
import tempfile
import tkinter as tk
import unittest
from tkinter import ttk
from unittest import mock

import gui_theme
import sorter_engine
from tab_import import ImportTab
from tab_organize import OrganizeTab
from tab_integrations import IntegrationsTab
from tab_tags import TagsTab


class CompletionNotificationTests(unittest.TestCase):
    def test_completions_notify_even_with_partial_operation_errors(self):
        for panel_class, method_name, arguments in (
            (ImportTab, "handle_pipeline_completion", ({}, True)),
            (OrganizeTab, "handle_execution_complete", ({}, False)),
            (OrganizeTab, "show_preview_results", ({}, False)),
            (OrganizeTab, "finish_undo", ({"restored": 1, "skipped": 0, "errors": []},)),
        ):
            with self.subTest(method=method_name):
                panel = mock.MagicMock()
                panel.active_sorter = None
                panel.preview_sorter.preview_records = []
                with mock.patch("tab_matrix.rescan_suggestions"), mock.patch(
                    "tab_matrix.messagebox.showinfo"
                ), mock.patch("tab_organize.show_notice"):
                    getattr(panel_class, method_name)(panel, *arguments)
                panel.event_generate.assert_called_once_with(
                    "<<LibraryChanged>>", when="tail"
                )

    def test_nested_repair_notifies_after_approved_operation(self):
        panel = mock.Mock()
        panel.nested_repair_suggestions = [{"source": "old", "destination": "new"}]
        with mock.patch(
            "tab_organize.messagebox.askyesno", return_value=True
        ), mock.patch(
            "tab_organize.sorter_engine.repair_nested_folder_files",
            return_value={"moved": 1, "skipped": 0, "errors": []}
        ):
            OrganizeTab.repair_nested_folders(panel)
        panel.event_generate.assert_called_once_with(
            "<<LibraryChanged>>", when="tail"
        )


class FoundationUiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        for target, attribute, value in (
            (sorter_engine, "ASSET_INDEX_FILE", os.path.join(self.temp_dir.name, "assets.db")),
            (gui_theme, "USER_LIBRARY_PATH", self.temp_dir.name),
        ):
            patcher = mock.patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def create_root(self, factory=tk.Tk):
        try:
            root = factory()
        except tk.TclError as error:
            self.skipTest(f"Tk display is unavailable: {error}")
        def close_root():
            root.destroy()
            gc.collect()

        self.addCleanup(close_root)
        return root

    def test_integrations_opens_existing_builder(self):
        root = self.create_root()
        tab = IntegrationsTab(root)
        tab.pack(fill="both", expand=True)
        root.update()
        with mock.patch("tab_integrations.xo_dialog.open_xo_builder") as builder:
            tab.xo_button.invoke()
        builder.assert_called_once_with(tab)
        browser = TagsTab(root)
        self.assertNotIn("xo_button", browser.__dict__)

    def test_app_mounts_integrations_and_refreshes_browser_after_event(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "AbletonLibraryManager.pyw"
        )
        loader = importlib.machinery.SourceFileLoader("foundation_app", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        with mock.patch.object(module.tab_cover, "build"), mock.patch.object(
            module.tab_matrix, "build"
        ), mock.patch.object(
            module, "ImportTab", side_effect=lambda parent, _status: ttk.Frame(parent)
        ), mock.patch.object(
            module, "OrganizeTab", side_effect=lambda parent, _status: ttk.Frame(parent)
        ), mock.patch.object(
            module, "ExclusionsTab", side_effect=ttk.Frame
        ), mock.patch.object(
            module, "ExperimentalTab", side_effect=lambda parent, _status: ttk.Frame(parent)
        ), mock.patch.object(TagsTab, "rescan_library"), mock.patch.object(
            TagsTab, "_request_sidebar_load"
        ):
            app = self.create_root(module.ProductionStudioManagerApp)
            app.tab_notebook.select(app.tags_panel)
            app.update()
            self.assertIn("Integrations", [
                app.tab_notebook.tab(tab, "text").strip()
                for tab in app.tab_notebook.tabs()
            ])
            self.assertTrue(
                app.tab_notebook.tab(app.tags_panel, "text").strip().endswith("Library")
            )
            app.tags_panel._static_counts["old"] = {"All sounds": 100}
            app.tags_panel._page_index = 5
            with mock.patch.object(
                app.tags_panel, "_request_sidebar_load"
            ) as load_sidebar, mock.patch.object(
                app.tags_panel, "_render_results"
            ) as render:
                app.import_dashboard.event_generate("<<LibraryChanged>>", when="tail")
                app.update()
            self.assertEqual({}, app.tags_panel._static_counts)
            self.assertEqual(0, app.tags_panel._page_index)
            render.assert_called_once_with(load_sidebar=False)
            load_sidebar.assert_called_once_with(self.temp_dir.name)

            def load_sidebar_now(library_root):
                tab = app.tags_panel
                tab._sidebar_generation += 1
                data = tab._load_sidebar_data(
                    library_root, "All sounds", False
                )
                tab._finish_sidebar_load(data, None, tab._sidebar_generation)

            with mock.patch.object(
                app.tags_panel, "_request_sidebar_load", side_effect=load_sidebar_now
            ):
                for count, filename in enumerate(("first.wav", "second.wav"), start=1):
                    asset_path = os.path.join(self.temp_dir.name, filename)
                    with open(asset_path, "wb") as handle:
                        handle.write(b"sound")
                    sorter_engine.index_asset(
                        asset_path, self.temp_dir.name, "test", 1.0, ["favorite"]
                    )
                    app.import_dashboard.event_generate(
                        "<<LibraryChanged>>", when="tail"
                    )
                    app.update()
                    self.assertEqual(count, app.tags_panel._cached_total_count)
                    self.assertEqual(count, len(app.tags_panel._asset_paths))
                    self.assertIn(
                        f"({count})", app.tags_panel.collection_list.get(0)
                    )
                    self.assertIn(
                        f"library total: {count}",
                        app.tags_panel.total_label.cget("text")
                    )


if __name__ == "__main__":
    unittest.main()

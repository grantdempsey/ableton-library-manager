import importlib.machinery
import importlib.util
import ast
import gc
import os
import tempfile
import threading
import time
import tkinter as tk
import unittest
from tkinter import ttk
from unittest import mock

import gui_theme
import sorter_engine
import tab_matrix
import xo_dialog
from tab_import import ImportTab
from tab_organize import OrganizeTab
from tab_integrations import IntegrationsTab
from tab_tags import TagsTab
from tab_experimental import ExperimentalTab


class CompletionNotificationTests(unittest.TestCase):
    def test_classic_content_widgets_explicitly_set_surface_colors(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        checked = 0
        for path in (*root.glob("*.py"), *root.glob("*.pyw")):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                constructor = node.func
                classic = (
                    isinstance(constructor, ast.Attribute)
                    and isinstance(constructor.value, ast.Name)
                    and constructor.value.id == "tk"
                    and constructor.attr in {"Text", "Listbox", "Entry", "Canvas", "Spinbox"}
                ) or (isinstance(constructor, ast.Name) and constructor.id == "ScrolledText")
                if not classic:
                    continue
                checked += 1
                options = {keyword.arg for keyword in node.keywords}
                with self.subTest(file=path.name, line=node.lineno):
                    self.assertTrue(options & {"bg", "background"}, "Missing explicit dark surface")
                    if not (isinstance(constructor, ast.Attribute) and constructor.attr == "Canvas"):
                        self.assertTrue(options & {"fg", "foreground"}, "Missing explicit text color")
        self.assertGreater(checked, 30)

    def test_in_place_organize_preview_exposes_separate_tag_recommendation(self):
        panel = mock.MagicMock()
        panel.preview_sorter.preview_records = [{
            "source": os.path.join("library", "Other One-Shots", "unknown.wav"),
            "filename": "unknown.wav",
            "destination": os.path.join("library", "Other One-Shots"),
            "tag_suggestion": {
                "destination": "Snares", "status": "suggested alternative to catch-all",
                "assignments": ["Sounds|Snare"]
            }
        }]
        with mock.patch("tab_organize.show_notice") as notice:
            OrganizeTab.show_preview_results(panel, {}, False)
        self.assertIn("Sounds|Snare", panel.write_console_message.call_args.args[0])
        self.assertIn("normal routing plan is unchanged", panel.write_console_message.call_args.args[0])
        self.assertEqual("No planned moves", notice.call_args.kwargs["heading"])
        self.assertIn("1 manual Live-tag", notice.call_args.kwargs["cards"][0][0])

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
        panel._job_pending = False
        panel.has_pending_job.return_value = False
        panel.winfo_toplevel.return_value._closing = False
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
            (sorter_engine, "CONFIG_FILE", os.path.join(self.temp_dir.name, "config.json")),
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
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                root.tk.call("after", "cancel", callback)
            root.destroy()
            gc.collect()

        self.addCleanup(close_root)
        return root

    def test_xo_folder_suggestion_error_is_visible_and_live_mode_reaches_scan(self):
        root = self.create_root()
        with mock.patch.object(xo_dialog.xo_filter, "suggest_types", side_effect=ValueError("Invalid manual sidecar")) as scan, mock.patch.object(
            xo_dialog.messagebox, "showerror"
        ) as error:
            xo_dialog.open_type_editor(
                root, root, self.temp_dir.name, lambda: None, use_live_tags=True
            )
            editor = next(child for child in root.winfo_children() if isinstance(child, tk.Toplevel))
            widgets = [editor]
            find_button = None
            listings = []
            while widgets:
                widget = widgets.pop()
                widgets.extend(widget.winfo_children())
                if widget.winfo_class() in ("Button", "TButton") and widget.cget("text") == "Find suggestions":
                    find_button = widget
                if widget.winfo_class() == "Listbox":
                    listings.append(widget)
            self.assertIsNotNone(find_button)
            find_button.invoke()
            deadline = time.monotonic() + 3
            while not error.called and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            scan.assert_called_once_with(self.temp_dir.name, include_loops=False, use_live_tags=True)
            error.assert_called_once()
            self.assertIn("Invalid manual sidecar", error.call_args.args[1])
            self.assertTrue(any("Suggestion scan failed" in widget.get(0) for widget in listings if widget.size()))
            self.assertEqual("normal", find_button.cget("state"))

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

    def test_shared_polish_keeps_controls_visible_at_minimum_size(self):
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "AbletonLibraryManager.pyw")
        loader = importlib.machinery.SourceFileLoader("polish_app", path)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        root = self.create_root()
        module.ProductionStudioManagerApp.set_application_styling_theme(root)
        root.geometry("1020x700")
        style = ttk.Style(root)
        self.assertNotEqual(
            style.lookup("TButton", "foreground", ("disabled",)),
            style.lookup("TButton", "background", ("disabled",))
        )
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)
        library = TagsTab(notebook)
        notebook.add(library, text="Library")
        root.update()
        self.assertGreater(library.search_entry.winfo_width(), 150)
        self.assertGreater(library.tag_list.winfo_height(), 70)
        self.assertIsNone(library._live_batch_dialog)
        self.assertGreater(library.assigned_tags_text.winfo_height(), 20)
        root.geometry("1020x620")
        for content in (library.assigned_tags_text,):
            root.update()
            for control in (content, library.edit_live_tags_button):
                self.assertTrue(control.winfo_ismapped(), str(control))
                self.assertGreater(control.winfo_height(), 20)
                self.assertLessEqual(
                    control.winfo_rooty() + control.winfo_height(),
                    library.inspector.winfo_rooty() + library.inspector.winfo_height()
                )
        root.geometry("1020x700")
        root.update()
        for control in (library.rescan_button, library.discovery_button, library.filter_button):
            self.assertTrue(control.winfo_ismapped())
            self.assertLessEqual(control.winfo_rootx() + control.winfo_width(),
                                 root.winfo_rootx() + root.winfo_width())
        button = tk.Button(root, text="Disabled", state="disabled")
        self.assertEqual(gui_theme.THEME["fg_muted"], button.cget("disabledforeground"))
        entry = tk.Entry(root, state="disabled")
        self.assertEqual(gui_theme.THEME["bg_field"], entry.cget("disabledbackground"))
        for widget_class in (tk.Text, tk.Listbox, tk.Entry):
            widget = widget_class(root)
            for state in ("normal", "disabled"):
                widget.configure(state=state)
                self.assertEqual(gui_theme.THEME["bg_field"], widget.cget("background"))
                self.assertEqual(gui_theme.THEME["fg_light"], widget.cget("foreground"))
                self.assertEqual(gui_theme.THEME["tag_enabled"], widget.cget("selectbackground"))
        with mock.patch.object(ExperimentalTab, "read_live_options_file"), mock.patch.object(
            ExperimentalTab, "automated_background_verify_sweep"
        ):
            advanced = ExperimentalTab(notebook, None)
            notebook.add(advanced, text="Advanced")
            notebook.select(advanced)
            root.update()
        self.assertLessEqual(advanced.lbl_tooltip.winfo_rooty() + advanced.lbl_tooltip.winfo_height(),
                             root.winfo_rooty() + root.winfo_height())
        check = next(child for row in advanced.winfo_children() for panel in row.winfo_children()
                     for holder in panel.winfo_children() for child in holder.winfo_children()
                     if isinstance(child, tk.Checkbutton))
        check.event_generate("<FocusIn>")
        root.update()
        self.assertNotEqual("Hover over an option to see a plain-English explanation.",
                            advanced.lbl_tooltip.cget("text"))

    def test_rules_exposes_manual_candidate_source_and_review_details(self):
        root = self.create_root()
        root.geometry("1020x620")
        status = ttk.Label(root)
        candidate = {
            "token": "quasar", "target": "Snares", "pattern": r"\bquasar\w*\b",
            "count": 27, "evidence_total": 30, "status": "pending",
            "evidence_source": "live_manual", "evidence_tags": ["Sounds|Snare"],
            "examples": ["Quasar 1.wav"],
        }
        with mock.patch.object(sorter_engine, "LEARNED_RULE_CANDIDATES", [candidate]), mock.patch.object(
            tab_matrix, "show_notice"
        ) as notice:
            tab_matrix.build(root, status)
            root.update()
            tree = tab_matrix._candidate_tree
            row = tree.get_children()[0]
            self.assertEqual("live_manual", tree.item(row, "values")[-1])
            tree.selection_set(row)
            widgets = [root]
            while widgets:
                widget = widgets.pop()
                widgets.extend(widget.winfo_children())
                if isinstance(widget, tk.Button) and widget.cget("text") == "View evidence":
                    widget.invoke()
                    break
            else:
                self.fail("Rules did not expose a View evidence button")
            text = notice.call_args.args[2]
            self.assertIn("Sounds|Snare", text)
            self.assertIn("27 / 30", text)
            self.assertIn("Quasar 1.wav", text)
            self.assertIn("Pending only", text)

    def test_rule_approval_rechecks_in_background_and_reports_stale_evidence(self):
        root = self.create_root()
        status = ttk.Label(root)
        candidate = {
            "token": "quasar", "target": "Snares", "pattern": r"\bquasar\w*\b",
            "count": 20, "status": "pending", "evidence_source": "live_manual",
        }
        started = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        def recheck(*_args):
            started.set()
            if not release.wait(3):
                raise ValueError("Recheck timed out")
            raise ValueError("Suggestion is no longer supported")
        with mock.patch.object(sorter_engine, "LEARNED_RULE_CANDIDATES", [candidate]), mock.patch.object(
            sorter_engine, "review_learning_candidates", side_effect=recheck
        ) as review, mock.patch.object(tab_matrix.messagebox, "showerror") as error:
            tab_matrix.build(root, status)
            tree = tab_matrix._candidate_tree
            tree.selection_set(tree.get_children()[0])
            widgets = [root]
            buttons = {}
            while widgets:
                widget = widgets.pop()
                widgets.extend(widget.winfo_children())
                if isinstance(widget, tk.Button):
                    buttons[widget.cget("text")] = widget
            use = buttons["Use this suggestion"]
            use.invoke()
            self.assertTrue(started.wait(1))
            self.assertEqual(1, len(root._background_jobs))
            self.assertTrue(root._background_jobs[0][0].is_alive())
            self.assertFalse(root._background_jobs[0][0].daemon)
            for name in ("Use this suggestion", "Use all suggestions", "Dismiss this suggestion"):
                self.assertEqual("disabled", buttons[name].cget("state"))
            ticks = []
            root.after(0, lambda: ticks.append(True))
            root.update()
            self.assertEqual([True], ticks)
            use.invoke()
            self.assertEqual(1, review.call_count)
            release.set()
            deadline = time.monotonic() + 3
            while not error.called and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            review.assert_called_once_with((("quasar", "Snares"),), "approved")
            self.assertIn("no longer supported", error.call_args.args[1])
            self.assertIn("no selected rules added", status.cget("text"))
            for name in ("Use this suggestion", "Use all suggestions", "Dismiss this suggestion"):
                self.assertEqual("normal", buttons[name].cget("state"))
            root._closing = True
            with mock.patch.object(tab_matrix.rule_suggester, "suggest_rules") as scan:
                use.invoke()
                tab_matrix.rescan_suggestions()
            scan.assert_not_called()
            self.assertEqual(1, review.call_count)

    def test_loop_layout_audit_is_visible_and_failed_scan_cannot_be_applied(self):
        root = self.create_root()
        result = sorter_engine.recommend_loop_layout(self.temp_dir.name)
        result["tag_evidence"].update({
            "manual_loops": 2, "tag_only_loops": 1, "key_conflicts": 1,
            "examples": [{
                "path": os.path.join(self.temp_dir.name, "mystery.wav"),
                "assignments": ["Type|Loop", "Key|C", "Key|Minor"],
                "manual_key": "CMIN", "notes": ["manual key disagrees with the filename key"],
            }],
        })
        def find_widgets(window):
            widgets, pending = [], [window]
            while pending:
                widget = pending.pop()
                widgets.append(widget)
                pending.extend(widget.winfo_children())
            return widgets
        with mock.patch.object(sorter_engine, "recommend_loop_layout", return_value=result):
            win = tab_matrix.open_loop_layout(root, self.temp_dir.name)
            widgets = find_widgets(win)
            evidence = next(widget for widget in widgets if isinstance(widget, tk.Button) and widget.cget("text") == "Evidence")
            use = next(widget for widget in widgets if isinstance(widget, tk.Button) and widget.cget("text") == "Use recommended")
            deadline = time.monotonic() + 3
            while evidence.cget("state") == "disabled" and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertEqual("normal", use.cget("state"))
            self.assertTrue(any("2 tagged loops" in widget.cget("text") and "review-only" in widget.cget("text")
                                for widget in widgets if isinstance(widget, tk.Label)))
            evidence.invoke()
            root.update()
            detail = next(child for child in win.winfo_children() if isinstance(child, tk.Toplevel))
            text = next(child for child in detail.winfo_children() if isinstance(child, tk.Text))
            self.assertIn("Type|Loop", text.get("1.0", "end"))
            self.assertIn("Key|Minor", text.get("1.0", "end"))
            self.assertEqual(gui_theme.THEME["bg_field"], text.cget("background"))
            self.assertEqual("disabled", text.cget("state"))
            for button in (use, evidence):
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(button.winfo_rooty() + button.winfo_height(), win.winfo_rooty() + win.winfo_height())
            win.destroy()
        with mock.patch.object(sorter_engine, "recommend_loop_layout", side_effect=ValueError("Invalid manual sidecar")):
            win = tab_matrix.open_loop_layout(root, self.temp_dir.name)
            widgets = find_widgets(win)
            deadline = time.monotonic() + 3
            while not any("Invalid manual sidecar" in widget.cget("text") for widget in widgets if isinstance(widget, tk.Label)) and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertTrue(any("Invalid manual sidecar" in widget.cget("text") for widget in widgets if isinstance(widget, tk.Label)))
            for button in widgets:
                if isinstance(button, tk.Button) and button.cget("text") in ("Use recommended", "Evidence"):
                    self.assertEqual("disabled", button.cget("state"))

    def test_rules_use_all_submits_one_atomic_review(self):
        root = self.create_root()
        status = ttk.Label(root)
        candidates = [
            {"token": token, "target": "Snares", "pattern": rf"\b{token}\w*\b", "count": 20, "status": "pending"}
            for token in ("quasar", "nebula")
        ]
        candidates.extend(
            {"token": f"legacy{count}", "target": "Nature", "pattern": rf"\blegacy{count}\b",
             "count": count, "status": "pending"}
            for count in (5, 7, 19)
        )
        with mock.patch.object(sorter_engine, "LEARNED_RULE_CANDIDATES", candidates), mock.patch.object(
            sorter_engine, "review_learning_candidates"
        ) as review, mock.patch.object(tab_matrix, "ask_confirm", return_value=True):
            tab_matrix.build(root, status)
            rows = tab_matrix._candidate_tree.get_children()
            self.assertEqual(2, len(rows))
            self.assertTrue(all(int(tab_matrix._candidate_tree.item(row, "values")[3]) >= 20 for row in rows))
            widgets = [root]
            use_all = None
            while widgets:
                widget = widgets.pop()
                widgets.extend(widget.winfo_children())
                if isinstance(widget, tk.Button) and widget.cget("text") == "Use all suggestions":
                    use_all = widget
            self.assertIsNotNone(use_all)
            use_all.invoke()
            deadline = time.monotonic() + 3
            while use_all.cget("state") == "disabled" and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            review.assert_called_once_with((("quasar", "Snares"), ("nebula", "Snares")), "approved")
            self.assertIn("Approved 2 suggestion(s)", status.cget("text"))

    def test_xo_opt_in_scan_evidence_and_failed_rescan_disable_build(self):
        root = self.create_root()
        xo_dialog.open_xo_builder(root)
        win = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
        widgets = []
        pending = [win]
        while pending:
            widget = pending.pop()
            widgets.append(widget)
            pending.extend(widget.winfo_children())
        scan = next(widget for widget in widgets if isinstance(widget, tk.Button) and widget.cget("text") == "Scan")
        build = next(widget for widget in widgets if isinstance(widget, tk.Button) and widget.cget("text") == "Build folder")
        evidence = next(widget for widget in widgets if isinstance(widget, tk.Button) and widget.cget("text") == "Evidence")
        live = next(widget for widget in widgets if isinstance(widget, tk.Checkbutton)
                    and widget.cget("text").startswith("Use manual Live"))
        path = os.path.join(self.temp_dir.name, "unknown.wav")
        stats = {
            "scanned": 1, "unclassified": 0, "loops_skipped": 0,
            "manual_classified": 1, "manual_conflicts": 0,
            "evidence": [{
                "path": path, "assignments": ["Sounds|Snare"], "status": "manual Live type",
                "sound_type": "Snares", "is_loop": False,
            }]
        }

        def finish_scan():
            deadline = time.monotonic() + 3
            while scan.cget("state") == "disabled" and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            self.assertEqual("normal", scan.cget("state"))

        with mock.patch("xo_dialog.xo_filter.build_plan", return_value=({"Snares": [path]}, stats)) as plan:
            live.invoke()
            scan.invoke()
            finish_scan()
            self.assertTrue(plan.call_args.kwargs["use_live_tags"])
        self.assertEqual("normal", build.cget("state"))
        evidence.invoke()
        root.update()
        detail = next(widget for widget in win.winfo_children() if isinstance(widget, tk.Toplevel))
        from tkinter.scrolledtext import ScrolledText
        texts = [widget for child in detail.winfo_children() for widget in child.winfo_children()
                 if isinstance(widget, ScrolledText)]
        self.assertIn("Sounds|Snare", texts[0].get("1.0", "end"))
        detail.destroy()
        with mock.patch("xo_dialog.xo_filter.build_folder", return_value={
            "linked": 1, "copied": 0, "existing": 0, "failed": 0
        }) as build_folder:
            build.invoke()
            finish_scan()
            self.assertEqual({"Snares": [path]}, build_folder.call_args.args[0])
        with mock.patch("xo_dialog.xo_filter.build_plan", side_effect=ValueError("Invalid Ableton sidecar")):
            scan.invoke()
            finish_scan()
        self.assertEqual("disabled", build.cget("state"))
        self.assertEqual("disabled", evidence.cget("state"))
        self.assertTrue(any("Invalid Ableton sidecar" in widget.cget("text")
                            for widget in widgets if isinstance(widget, tk.Label)))
        many_types = {f"Group {index}": [path] for index in range(40)}
        with mock.patch("xo_dialog.xo_filter.build_plan", return_value=(many_types, stats)):
            scan.invoke()
            finish_scan()
        win.geometry("640x580")
        root.update()
        self.assertTrue(build.winfo_ismapped())
        self.assertLessEqual(build.winfo_rooty() + build.winfo_height(), win.winfo_rooty() + win.winfo_height())
        canvas = next(widget for child in win.winfo_children() for widget in child.winfo_children()
                      if isinstance(widget, tk.Canvas))
        self.assertGreater(canvas.bbox("all")[3], canvas.winfo_height())
        canvas.yview_moveto(1)
        root.update()
        self.assertGreater(canvas.yview()[0], 0)

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
            batch = mock.Mock()
            app.tags_panel._live_batch_dialog = batch
            app.request_graceful_shutdown()
            batch.close.assert_called_once_with()
            self.assertFalse(app._closing)
            app.tags_panel._live_batch_dialog = None
            app.tags_panel._refresh_running = True
            app.organize_panel.has_pending_job = lambda: False
            with mock.patch.object(app, "destroy") as destroy, mock.patch.object(app, "after") as schedule:
                app._wait_for_workers_before_close(0)
            destroy.assert_not_called()
            schedule.assert_called_once()
            app.tags_panel._refresh_running = False


if __name__ == "__main__":
    unittest.main()

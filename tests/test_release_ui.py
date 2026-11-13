import os
import importlib.machinery
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

import gui_theme
import sorter_engine
from tab_import import ImportTab
from tab_organize import OrganizeTab
from tab_experimental import ExperimentalTab


class ReleaseUiTests(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory(prefix="alm-release-ui-")
        self.addCleanup(fixture.cleanup)
        self.root_dir = Path(fixture.name)
        self.home = self.root_dir / "home"
        self.home.mkdir()
        self.library = self.home / "User Library"
        self.library.mkdir()
        self.source = self.home / "incoming"
        self.source.mkdir()
        self.config = self.home / "library_config.json"
        self.index = self.home / "library_assets.db"
        self.patchers = [
            mock.patch.object(sorter_engine, "CONFIG_FILE", str(self.config)),
            mock.patch.object(sorter_engine, "ASSET_INDEX_FILE", str(self.index)),
            mock.patch.object(gui_theme, "USER_HOME", str(self.home)),
            mock.patch.object(gui_theme, "USER_LIBRARY_PATH", str(self.library)),
            mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)}),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk is unavailable: {error}")
        self.addCleanup(self._destroy_root)
        self.root.geometry("900x540+0+0")
        self.root.update_idletasks()
        self.screenshot_dir = self.root_dir / "screenshots"
        self.screenshot_dir.mkdir(exist_ok=True)
        self.screenshot_run = uuid.uuid4().hex[:8]

    def _destroy_root(self):
        try:
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            self.root.destroy()
        except tk.TclError:
            pass

    def _destroy_panel(self, panel):
        try:
            for callback in self.root.tk.call("after", "info"):
                self.root.after_cancel(callback)
            panel.destroy()
        except tk.TclError:
            pass

    def _capture(self, filename):
        if os.name == "nt":
            path = self.screenshot_dir / f"{self.screenshot_run}-{filename.replace('.png', '.bmp')}"
            size = self._capture_windows_bitmap(path)
            self.assertGreater(path.stat().st_size, 0)
            return size
        try:
            from PIL import ImageGrab
            x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
            image = ImageGrab.grab(bbox=(x, y, x + self.root.winfo_width(), y + self.root.winfo_height()))
            path = self.screenshot_dir / f"{self.screenshot_run}-{filename}"
            image.save(path)
            size = image.size
        except ImportError:
            self.skipTest("Desktop screenshot capture requires Pillow outside Windows.")
        self.assertGreater(path.stat().st_size, 0)
        return size

    def _capture_windows_bitmap(self, path):
        import ctypes

        width, height = self.root.winfo_width(), self.root.winfo_height()
        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        user32.GetParent.restype = ctypes.c_void_p
        window = user32.GetParent(ctypes.c_void_p(self.root.winfo_id()))
        screen = user32.GetDC(None)
        memory = gdi32.CreateCompatibleDC(screen)
        bitmap = gdi32.CreateCompatibleBitmap(screen, width, height)
        previous = gdi32.SelectObject(memory, bitmap)
        try:
            if not user32.PrintWindow(ctypes.c_void_p(window), memory, 1):
                raise OSError("Windows could not capture the Tk window.")

            class BitmapInfoHeader(ctypes.Structure):
                _fields_ = [
                    ("size", ctypes.c_uint32), ("width", ctypes.c_int32),
                    ("height", ctypes.c_int32), ("planes", ctypes.c_uint16),
                    ("bit_count", ctypes.c_uint16), ("compression", ctypes.c_uint32),
                    ("image_size", ctypes.c_uint32), ("x_pixels", ctypes.c_int32),
                    ("y_pixels", ctypes.c_int32), ("colors_used", ctypes.c_uint32),
                    ("colors_important", ctypes.c_uint32),
                ]

            class BitmapInfo(ctypes.Structure):
                _fields_ = [("header", BitmapInfoHeader), ("colors", ctypes.c_uint32 * 3)]

            info = BitmapInfo()
            info.header = BitmapInfoHeader(
                ctypes.sizeof(BitmapInfoHeader), width, -height, 1, 32, 0,
                width * height * 4, 0, 0, 0, 0,
            )
            pixels = ctypes.create_string_buffer(width * height * 4)
            gdi32.SelectObject(memory, previous)
            if not gdi32.GetDIBits(
                memory, bitmap, 0, height, pixels, ctypes.byref(info), 0,
            ):
                raise OSError("Windows could not read the Tk window screenshot.")
            raw = pixels.raw
            header = struct.pack(
                "<2sIHHI", b"BM", 54 + len(raw), 0, 0, 54,
            ) + struct.pack(
                "<IiiHHIIiiII", 40, width, -height, 1, 32, 0,
                len(raw), 0, 0, 0, 0,
            )
            path.write_bytes(header + raw)
        finally:
            gdi32.SelectObject(memory, previous)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory)
            user32.ReleaseDC(None, screen)
        return width, height

    def test_import_has_distinct_preview_and_apply_and_does_not_create_destination(self):
        panel = ImportTab(self.root)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.update()
        panel.src_dir_var.set(str(self.source))
        destination = self.home / "not-created"
        panel.dest_dir_var.set(str(destination))
        worker = mock.Mock()
        with mock.patch("tab_import.gui_theme.library_job_available", return_value=True), \
                mock.patch("tab_import.ParallelLibrarySorter", return_value=worker) as sorter:
            panel.preview_import()

        sorter.assert_called_once()
        self.assertTrue(sorter.call_args.kwargs["preview_only"])
        self.assertFalse(sorter.call_args.kwargs["audio_only"])
        self.assertTrue(sorter.call_args.kwargs["supported_only"])
        self.assertTrue(panel.copy_mode_var.get())
        self.assertEqual("supported", panel.import_scope_var.get())
        self.assertEqual("Copy (keep originals)", panel.copy_radio.cget("text"))
        self.assertEqual("Move (remove originals)", panel.move_radio.cget("text"))
        self.assertEqual("Audio + supported presets", panel.supported_only_check.cget("text"))
        worker.start_parallel_sort.assert_called_once_with()
        self.assertEqual("disabled", panel.apply_btn.cget("state"))
        self.assertFalse(hasattr(panel, "undo_btn"))
        self.assertIs(panel.audio_only_check.master, panel.supported_only_check.master)
        self.assertIs(panel.copy_radio.master, panel.move_radio.master)
        self.assertLess(
            panel.audio_type_group.winfo_rootx() + panel.audio_type_group.winfo_width(),
            panel.operation_group.winfo_rootx(),
        )
        self.assertLess(
            panel.operation_group.winfo_rootx() + panel.operation_group.winfo_width(),
            panel.review_group.winfo_rootx(),
        )
        self.assertEqual(panel.audio_only_check.grid_info()["column"],
                         panel.supported_only_check.grid_info()["column"])
        self.assertLess(panel.audio_only_check.winfo_rooty(), panel.supported_only_check.winfo_rooty())
        self.assertEqual(gui_theme.THEME["btn_primary"], panel.preview_btn.cget("background"))
        self.assertNotEqual(gui_theme.THEME["accent_neon"], panel.apply_btn.cget("background"))
        self.assertEqual(gui_theme.THEME["fg_muted"], panel.apply_btn.cget("disabledforeground"))
        for control in (
            panel.copy_radio, panel.move_radio, panel.audio_only_check,
            panel.supported_only_check, panel.preview_btn, panel.apply_btn,
            panel.cancel_btn, panel.console_log,
        ):
            self.assertTrue(control.winfo_ismapped(), str(control))
            self.assertGreater(control.winfo_width(), 0, str(control))
            self.assertGreater(control.winfo_height(), 0, str(control))
            self.assertGreaterEqual(control.winfo_rootx(), self.root.winfo_rootx(), str(control))
            self.assertLessEqual(
                control.winfo_rootx() + control.winfo_width(),
                self.root.winfo_rootx() + self.root.winfo_width(), str(control),
            )
        self.assertFalse(destination.exists())
        self.assertFalse(self.config.exists())
        self.assertFalse(self.index.exists())
        screenshot_size = self._capture("import-ui.png")
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), screenshot_size)

    def test_advanced_does_not_expose_internal_diagnostics(self):
        with mock.patch.object(ExperimentalTab, "read_live_options_file"), mock.patch(
            "tab_experimental.gui_theme.reveal_folder_in_explorer",
        ) as reveal:
            panel = ExperimentalTab(self.root, None)
            self.addCleanup(self._destroy_panel, panel)
            panel.pack(fill="both", expand=True)
            self.root.update()
        def widget_texts(widget):
            for child in widget.winfo_children():
                if "text" in child.keys():
                    yield str(child.cget("text")).lower()
                yield from widget_texts(child)
        labels = "\n".join(widget_texts(panel))
        for internal_label in ("performance logs", "storage summary", "log timings"):
            self.assertNotIn(internal_label, labels)
        self.assertIn("reload settings from disk", labels)
        self.assertNotIn("documentation url:", labels)
        pending = [panel]
        actions = {}
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, tk.Button):
                actions[widget.cget("text")] = widget
        self.assertIs(actions["Save changes"].master, actions["Reload settings from disk"].master)
        self.assertGreater(actions["Save changes"].winfo_rooty(), panel.ent_path.winfo_rooty())
        self.assertTrue(actions["Ableton documentation"].winfo_ismapped())
        reveal.assert_not_called()

    def test_completed_import_preview_does_not_trigger_library_rescans(self):
        panel = ImportTab(self.root)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.update()
        panel.active_sorter = SimpleNamespace(
            preview_only=True, operation_errors=[], preview_records=[],
            cancel_event=SimpleNamespace(is_set=lambda: False),
            reviewed_plan={"kind": "ordinary"},
        )
        panel._preview_settings = panel._settings_snapshot()
        with mock.patch("tab_import.tab_matrix.rescan_suggestions") as rescan, \
                mock.patch("tab_import.messagebox.showinfo"), \
                mock.patch.object(self.root, "event_generate") as event_generate:
            panel.handle_pipeline_completion({}, True)
        rescan.assert_not_called()
        event_generate.assert_not_called()
        self.assertEqual("normal", panel.apply_btn.cget("state"))
        self.assertFalse(self.config.exists())
        self.assertFalse(self.index.exists())

    def test_organize_uses_measured_scrollable_geometry_and_collapses_repair_options(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.backup_required_var.set(False)
        panel.pack(fill="both", expand=True)
        self.root.geometry("900x540+0+0")
        self.root.update()
        canvas = panel._organize_canvas
        region = tuple(map(int, canvas.cget("scrollregion").split()))
        viewport_height = canvas.winfo_height()
        self.assertGreater(viewport_height, 0)
        self.assertGreater(region[3] - region[1], 0)
        self.assertFalse(panel.repair_group.winfo_ismapped())
        self.assertEqual("disabled", panel.btn_execute.cget("state"))
        self.assertEqual(gui_theme.THEME["btn_secondary"], panel.btn_execute.cget("background"))
        self.assertNotEqual(gui_theme.THEME["accent_neon"], panel.btn_execute.cget("background"))
        self.assertEqual(gui_theme.THEME["fg_muted"], panel.btn_execute.cget("disabledforeground"))
        self.assertTrue(panel.btn_preview.winfo_ismapped())
        self.assertFalse(hasattr(panel, "btn_history"))
        self.assertFalse(panel.ent_src.winfo_ismapped())
        self.assertFalse(panel.btn_cancel.winfo_ismapped())
        self.assertFalse(panel.progress_bar.winfo_ismapped())
        self.assertEqual(panel.btn_preview.winfo_rooty(), panel.btn_execute.winfo_rooty())
        self.assertLess(panel.btn_preview.winfo_rootx(), panel.btn_execute.winfo_rootx())
        self.assertEqual(gui_theme.THEME["btn_primary"], panel.btn_preview.cget("background"))
        self.assertTrue(panel.btn_tools.winfo_ismapped())
        safety_bottom = panel.safety_group.winfo_rooty() + panel.safety_group.winfo_height()
        viewport_bottom = canvas.winfo_rooty() + viewport_height
        self.assertLessEqual(safety_bottom, viewport_bottom)
        self.assertLessEqual(self.root.winfo_width(), self.root.winfo_screenwidth())
        self.assertLessEqual(self.root.winfo_height(), self.root.winfo_screenheight())
        screenshot_size = self._capture("organize-ui.png")
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), screenshot_size)
        canvas.yview_moveto(1.0)
        self.root.update()
        viewport_top = canvas.winfo_rooty()
        viewport_bottom = viewport_top + canvas.winfo_height()
        self.assertGreaterEqual(panel.console_log.winfo_rooty(), viewport_top)
        self.assertLessEqual(
            panel.console_log.winfo_rooty() + panel.console_log.winfo_height(),
            viewport_bottom,
        )
        canvas.yview_moveto(0.0)
        self.root.update()
        for control in (panel.btn_preview, panel.btn_execute, panel.btn_tools):
            self.assertGreaterEqual(control.winfo_rooty(), canvas.winfo_rooty())
            self.assertLessEqual(
                control.winfo_rooty() + control.winfo_height(),
                canvas.winfo_rooty() + canvas.winfo_height(),
            )

    def test_organize_more_tools_owns_menu_and_opens_repairs(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.update()
        self.assertIs(panel.btn_tools, panel.tools_menu.master)
        panel.tools_menu.invoke(1)
        self.root.update()
        self.assertTrue(panel.repair_group.winfo_ismapped())

    @unittest.skipIf(sys.platform == "darwin", "Native Cocoa menu tracking needs manual input acceptance")
    def test_organize_more_tools_posts_from_button(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.update()
        button = panel.btn_tools
        posted = []
        finished = threading.Event()
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class GuiThreadInfo(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT),
                ]

            user32 = ctypes.windll.user32
            user32.GetParent.restype = wintypes.HWND
            window = user32.GetParent(wintypes.HWND(self.root.winfo_id()))
            thread_id = user32.GetWindowThreadProcessId(wintypes.HWND(window), None)

            def dismiss_native_menu():
                deadline = time.monotonic() + 5
                while not finished.wait(0.02) and time.monotonic() < deadline:
                    info = GuiThreadInfo(cbSize=ctypes.sizeof(GuiThreadInfo))
                    if user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)) and info.flags & 4:
                        posted.append(True)
                        user32.PostMessageW(wintypes.HWND(info.hwndMenuOwner), 0x001F, 0, 0)
                        return
                user32.PostMessageW(wintypes.HWND(window), 0x001F, 0, 0)

            dismiss = threading.Thread(target=dismiss_native_menu)
            dismiss.start()
        else:
            def dismiss_menu():
                posted.append(bool(panel.tools_menu.winfo_ismapped()))
                self.root.tk.call("tk::MenuUnpost", "")
                finished.set()
            self.root.after(100, dismiss_menu)
        try:
            self.root.tk.call("tk::MbPost", str(button))
            if os.name != "nt":
                while not finished.is_set():
                    self.root.update()
            self.assertEqual([True], posted)
            panel.tools_menu.invoke(1)
            self.root.update()
            self.assertTrue(panel.repair_group.winfo_ismapped())
        finally:
            finished.set()
            if os.name == "nt":
                dismiss.join(timeout=6)
            self.root.tk.call("tk::MenuUnpost", "")

    def test_organize_activity_grows_with_window_and_short_content_still_scrolls(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.geometry("1020x700")
        self.root.update()
        initial_height = panel.console_log.winfo_height()
        initial_window_height = self.root.winfo_height()
        self.root.geometry("1020x900")
        self.root.update()
        window_growth = self.root.winfo_height() - initial_window_height
        self.assertGreater(window_growth, 0)
        self.assertGreaterEqual(panel.console_log.winfo_height(), initial_height + window_growth - 10)
        expanded_height = panel.console_log.winfo_height()
        panel.toggle_repair_options()
        self.root.update()
        self.assertLess(panel.console_log.winfo_height(), expanded_height)
        panel.toggle_repair_options()
        self.root.update()
        self.assertEqual(expanded_height, panel.console_log.winfo_height())
        panel.toggle_repair_options()
        self.root.geometry("900x380")
        self.root.update()
        canvas = panel._organize_canvas
        self.assertGreater(panel._organize_content.winfo_height(), canvas.winfo_height())
        canvas.yview_moveto(1)
        self.root.update()
        self.assertLessEqual(
            panel.console_log.winfo_rooty() + panel.console_log.winfo_height(),
            canvas.winfo_rooty() + canvas.winfo_height(),
        )
        panel.toggle_repair_options()
        self.root.geometry("1020x900")
        self.root.update()
        self.assertEqual(expanded_height, panel.console_log.winfo_height())

    def test_organize_preview_cannot_enable_apply_without_a_complete_plan(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.backup_required_var.set(False)
        panel.pack(fill="both", expand=True)
        self.root.update()
        panel.library_dir_var.set(str(self.library))
        incomplete = mock.Mock()
        incomplete.operation_errors = [{"operation": "scan", "source": "fixture", "error": "failed"}]
        incomplete.cancel_event.is_set.return_value = False
        incomplete.reviewed_plan = None
        panel.preview_sorter = incomplete
        with mock.patch("tab_organize.show_notice"):
            panel.show_preview_results({}, False)
        self.assertEqual("disabled", panel.btn_execute.cget("state"))
        self.assertIsNone(panel.reviewed_plan)

    def test_completed_organize_preview_enables_only_the_reviewed_plan(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.backup_required_var.set(False)
        panel.pack(fill="both", expand=True)
        self.root.update()
        panel.library_dir_var.set(str(self.library))
        panel.preview_sorter = SimpleNamespace(
            operation_errors=[], cancel_event=SimpleNamespace(is_set=lambda: False),
            reviewed_plan={"kind": "ordinary"}, preview_records=[],
        )
        panel._preview_settings = panel._settings_snapshot()
        with mock.patch("tab_organize.show_notice"), \
                mock.patch.object(self.root, "event_generate") as event_generate:
            panel.show_preview_results({}, False)
        self.assertEqual("normal", panel.btn_execute.cget("state"))
        self.assertEqual("normal", panel.btn_export_plan.cget("state"))
        self.assertEqual("normal", panel.tools_menu.entrycget(0, "state"))
        self.assertEqual(gui_theme.THEME["btn_primary"], panel.btn_execute.cget("background"))
        self.assertIn("0 planned operations", panel.plan_summary_var.get())
        event_generate.assert_not_called()

    def test_organize_running_controls_and_menu_follow_job_lifetime(self):
        panel = OrganizeTab(self.root, None)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.update()
        panel.preview_running = True
        panel.btn_cancel.config(state="normal")
        panel._sync_workflow_controls()
        self.root.update()
        self.assertTrue(panel.btn_cancel.winfo_ismapped())
        self.assertTrue(panel.progress_bar.winfo_ismapped())
        self.assertEqual("disabled", panel.tools_menu.entrycget(1, "state"))
        panel.preview_running = False
        panel.lbl_alert.config(text="")
        panel._sync_workflow_controls()
        self.root.update()
        self.assertFalse(panel.btn_cancel.winfo_ismapped())
        self.assertFalse(panel.f_alert_box.winfo_ismapped())
        panel.lbl_alert.config(text="Backup needs attention")
        panel._sync_workflow_controls()
        self.root.update()
        self.assertTrue(panel.f_alert_box.winfo_ismapped())
        self.assertEqual("normal", panel.tools_menu.entrycget(1, "state"))
        panel.tools_menu.invoke(1)
        self.root.update()
        self.assertTrue(panel.repair_group.winfo_ismapped())
        panel.tools_menu.invoke(1)
        self.root.update()
        self.assertFalse(panel.repair_group.winfo_ismapped())

    def test_home_instructions_and_scrollable_layout(self):
        import tab_cover
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        with mock.patch.object(sorter_engine, "library_status_summary", return_value={
            "sounds": 0, "rules_enabled": 0, "rules": 0, "suggestions": 0,
            "last_cleanup": None, "backups": 0,
        }):
            tab_cover.build(frame)
        self.root.update()
        pending = [frame]
        texts = []
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if "text" in widget.keys():
                texts.append(str(widget.cget("text")))
        self.assertNotIn("Preview only", "\n".join(texts))
        self.assertNotIn("Version 2.1.1", "\n".join(texts))
        self.assertIn("Preview the plan", "\n".join(texts))
        self.assertTrue(any(isinstance(widget, tk.Canvas) for widget in frame.winfo_children()))

    def test_skip_removal_is_list_scoped_and_selection_dependent(self):
        from tab_exclusions import ExclusionsTab
        with mock.patch.object(sorter_engine, "pending_legacy_exclusions", return_value=[]):
            panel = ExclusionsTab(self.root)
        panel.pack(fill="both", expand=True)
        self.root.update()
        self.assertEqual("disabled", panel.btn_remove.cget("state"))
        item = panel.tree.get_children()[0]
        panel.tree.selection_set(item)
        self.root.update()
        self.assertEqual("normal", panel.btn_remove.cget("state"))
        self.assertGreater(panel.btn_remove.winfo_rooty(), panel.tree.winfo_rooty())
        panel.configuration_read_only = True
        panel._update_remove_state()
        self.assertEqual("disabled", panel.btn_remove.cget("state"))

    def test_library_has_one_saved_search_surface_and_visible_rescan(self):
        from tab_tags import TagsTab
        panel = TagsTab(self.root)
        self.addCleanup(self._destroy_panel, panel)
        panel.pack(fill="both", expand=True)
        self.root.geometry("1020x700+0+0")
        self.root.update()
        self.assertFalse(hasattr(panel, "saved_button"))
        self.assertTrue(panel.saved_collection_list.winfo_exists())
        self.assertTrue(panel.rescan_button.winfo_ismapped())
        self.assertGreater(panel.rescan_button.winfo_width(), 60)
        panel._show_selected_asset()
        self.assertEqual("disabled", panel._selection_buttons["Clear selection"].cget("state"))
        self.assertEqual("disabled", panel._selection_buttons["Select page"].cget("state"))
        self.assertGreater(panel.rescan_button.winfo_rooty(), panel.asset_tree.winfo_rooty())

    def test_application_default_and_minimum_geometry_fit_screen(self):
        path = Path(__file__).resolve().parent.parent / "AbletonLibraryManager.pyw"
        loader = importlib.machinery.SourceFileLoader("release_ui_geometry", str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        dimensions = module.ProductionStudioManagerApp._window_dimensions
        screen = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
        default = dimensions(*screen)
        small_display = dimensions(min(screen[0], 1024), min(screen[1], 768))
        self.assertLessEqual(default[0], screen[0])
        self.assertLessEqual(default[1], screen[1])
        self.assertLessEqual(small_display[0], screen[0])
        self.assertLessEqual(small_display[1], screen[1])
        self.assertEqual((1180, 760), dimensions(1920, 1080))
        self.assertEqual((964, 668), dimensions(1024, 768))


if __name__ == "__main__":
    unittest.main()

# AbletonLibraryManager.pyw - Complete Production Application Orchestrator
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import platform
import queue
import time
import os
import json

# Import Modular Studio Layout Tabs
from tab_import import ImportTab
from tab_organize import OrganizeTab
from tab_exclusions import ExclusionsTab
from tab_experimental import ExperimentalTab
from tab_tags import TagsTab
from tab_integrations import IntegrationsTab
import tab_cover
import tab_matrix
import gui_theme
import sorter_engine
import xo_filter

class ProductionStudioManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        version = self._display_version()
        self.title(f"Ableton Library Manager — {version}")
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width, height = self._window_dimensions(screen_width, screen_height)
        self.geometry(f"{width}x{height}")
        self.minsize(min(1020, width), min(700, height))
        try:
            startup_lease = gui_theme.claim_library_job(
                self, "Startup state recovery", notify=False,
            )
        except OSError as error:
            messagebox.showerror(
                "Could not secure application state",
                f"Startup recovery was not run and no library operation was started:\n\n{error}",
                parent=self,
            )
            self.destroy()
            return
        if startup_lease is None:
            messagebox.showwarning(
                "Another manager operation is active",
                "This manager could not secure library access for startup recovery. "
                "Close the other manager after its operation finishes, then restart this app.",
                parent=self,
            )
            self.destroy()
            return
        startup_lease_transferred = False
        try:
            startup_lease_transferred = self._initialize_with_startup_lease(startup_lease)
        finally:
            if not startup_lease_transferred and startup_lease.active:
                startup_lease.release()

    def _initialize_with_startup_lease(self, startup_lease):
        try:
            migration_warnings = sorter_engine.initialize_runtime_storage()
            sorter_engine.load_external_config()
        except (OSError, ValueError) as error:
            messagebox.showerror(
                "Application data migration failed",
                "Your existing state files were preserved. The application cannot continue "
                f"until migration succeeds:\n\n{error}",
                parent=self,
            )
            self.destroy()
            return False
        try:
            xo_filter.apply_custom_types()
        except (OSError, ValueError) as error:
            messagebox.showwarning(
                "XO folder configuration could not be loaded",
                "Built-in XO folder matching remains available, but custom XO folders "
                "could not be loaded. Repair the profile before editing Skip Folders.\n\n"
                f"{error}",
                parent=self,
            )
        gui_theme.set_active_library_path(sorter_engine.ACTIVE_LIBRARY_PATH)
        self._startup_recovery_pending = True
        self._startup_recovery_results = queue.Queue()
        self._startup_rescan_after_id = None
        self.set_application_styling_theme()
        self.build_notebook_tabs()
        self._closing = False

        # 🌟 THE ABSOLUTE TERMINATOR PROTOCOL BINDING:
        # Explicitly monitors the OS window close (X) button action to intercept zombie worker threads
        self.install_shutdown_handlers()
        if migration_warnings:
            self.after(500, lambda: messagebox.showwarning(
                "Some older state was preserved",
                "A newer stable profile was kept where state files conflicted. "
                "The older files were not changed and remain available for manual recovery.\n\n"
                + "\n".join(migration_warnings[:12]),
                parent=self,
            ))
        self._start_startup_recovery(startup_lease)
        self._startup_rescan_after_id = self.after(1500, self._rescan_after_startup_recovery)
        return True

    @staticmethod
    def _display_version():
        try:
            import build_info
            return build_info.display_version()
        except Exception:
            return "Development source"

    @staticmethod
    def _window_dimensions(screen_width, screen_height):
        return (
            min(1180, max(320, screen_width - 60)),
            min(760, max(320, screen_height - 100)),
        )

    def show_about(self):
        try:
            import build_info
            identity = build_info.metadata()
            version = build_info.display_version()
        except Exception as error:
            messagebox.showwarning(
                "Build identity unavailable",
                f"Build metadata could not be verified:\n\n{error}",
                parent=self,
            )
            version = "Development source"
            identity = {"kind": "development"}
        details = "\n".join(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in identity.items()
        )
        messagebox.showinfo(
            "About Ableton Library Manager",
            f"Ableton Library Manager\n{version}\n\n{details}",
            parent=self,
        )

    def open_history_recovery(self):
        existing = getattr(self, "_history_window", None)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            self._refresh_history_list()
            return

        window = tk.Toplevel(self)
        self._history_window = window
        window.title("History / Recovery")
        window.transient(self)
        window.geometry("760x420")
        window.minsize(620, 320)
        ttk.Label(
            window,
            text="Review completed Move and cleanup logs. Changed or occupied files are never overwritten.",
            wraplength=700, justify="left",
        ).pack(fill="x", padx=12, pady=(12, 6))
        wrapper = ttk.Frame(window)
        wrapper.pack(fill="both", expand=True, padx=12, pady=6)
        columns = ("action", "created", "remaining", "path")
        self._history_tree = ttk.Treeview(wrapper, columns=columns, show="headings", selectmode="browse")
        for column, heading, width in (
            ("action", "Operation", 130), ("created", "Created", 140),
            ("remaining", "Moves to undo", 100), ("path", "History log", 330),
        ):
            self._history_tree.heading(column, text=heading)
            self._history_tree.column(column, width=width, anchor="w")
        scroll = ttk.Scrollbar(wrapper, orient="vertical", command=self._history_tree.yview)
        self._history_tree.configure(yscrollcommand=scroll.set)
        self._history_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._history_paths = {}
        actions = ttk.Frame(window)
        actions.pack(fill="x", padx=12, pady=(4, 12))
        ttk.Button(actions, text="Refresh", command=self._refresh_history_list).pack(side="left")
        ttk.Button(actions, text="Undo selected…", command=self._undo_selected_history).pack(side="left", padx=6)
        ttk.Button(
            actions, text="Scan interrupted transfers",
            command=self.organize_panel.scan_transfer_recovery,
        ).pack(side="left")
        ttk.Button(actions, text="Close", command=window.destroy).pack(side="right")
        self._refresh_history_list()

    def _refresh_history_list(self):
        tree = getattr(self, "_history_tree", None)
        if tree is None or not tree.winfo_exists():
            return
        for item in tree.get_children():
            tree.delete(item)
        self._history_paths.clear()
        directory = sorter_engine._move_log_dir()
        try:
            paths = [
                os.path.join(directory, name)
                for name in os.listdir(directory) if name.lower().endswith(".jsonl")
            ]
        except OSError:
            paths = []
        paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        for path in paths:
            try:
                remaining, created = sorter_engine.describe_move_log(path)
                with open(path, "r", encoding="utf-8") as handle:
                    first_record = next((json.loads(line) for line in handle if line.strip()), {})
                kind = first_record.get("job_kind", "move")
                operation = "Organize" if kind == "organize" else "Import / Move"
                item = tree.insert(
                    "", "end", values=(operation, created, f"{remaining:,}", path),
                )
                self._history_paths[item] = path
            except (OSError, ValueError, TypeError):
                item = tree.insert("", "end", values=("Review required", "—", "—", path))
                self._history_paths[item] = path

    def _undo_selected_history(self):
        selected = self._history_tree.selection()
        if not selected:
            messagebox.showinfo("Select a history log", "Choose a history item to undo.", parent=self._history_window)
            return
        path = self._history_paths.get(selected[0])
        if path:
            self.import_dashboard.undo_move_import(path)

    def _start_startup_recovery(self, lease=None):
        if self._closing:
            self._startup_recovery_pending = False
            if lease is not None:
                lease.release()
            return
        if lease is None:
            lease = gui_theme.claim_library_job(
                self, "Startup transfer recovery", notify=False,
            )
            if lease is None:
                self.after(100, self._start_startup_recovery)
                return

        self.status_lbl.config(text="Checking for interrupted transfers...")

        def recover():
            try:
                result = sorter_engine.recover_startup_transfers(gui_theme.USER_LIBRARY_PATH)
            except (OSError, ValueError, TypeError) as error:
                result = {"journals_found": 0, "recovered": 0, "errors": [str(error)]}
            self._startup_recovery_results.put(result)

        try:
            self._startup_recovery_thread = gui_theme.start_background_job(
                self, recover, library_job="Startup transfer recovery",
                lease=lease, notify_busy=False,
            )
        except RuntimeError as error:
            self._startup_recovery_pending = False
            self.status_lbl.config(text="Startup recovery could not be started.")
            messagebox.showwarning(
                "Startup recovery could not start",
                f"Interrupted transfers were not changed. Use Organize > Scan transfer recovery to retry.\n\n{error}",
                parent=self,
            )
            return
        self.after(30, self._poll_startup_recovery)

    def _poll_startup_recovery(self):
        try:
            result = self._startup_recovery_results.get_nowait()
        except queue.Empty:
            if not self._closing:
                self.after(30, self._poll_startup_recovery)
            return
        self._startup_recovery_pending = False
        if self._closing:
            return
        errors = result["errors"]
        recovered = result["recovered"]
        if errors:
            self.status_lbl.config(
                text=f"Startup recovery: {recovered:,} recovered; {len(errors):,} need review."
            )
            details = "\n".join(errors[:12])
            if len(errors) > 12:
                details += f"\n...and {len(errors) - 12:,} more."
            messagebox.showwarning(
                "Some interrupted transfers need review",
                f"{recovered:,} transfer records recovered. {len(errors):,} were retained because "
                "their files or recorded state need review. Use Organize > Scan transfer recovery "
                "to retry after resolving the reported issue.\n\n"
                + details,
                parent=self,
            )
        elif recovered:
            self.status_lbl.config(text=f"Startup recovery completed: {recovered:,} transfer records recovered.")
            messagebox.showinfo(
                "Interrupted transfers recovered",
                f"{recovered:,} interrupted transfer records were recovered. "
                "Unfinished transfers were rolled back and committed audio was retained. "
                "The Library index will now be rescanned.",
                parent=self,
            )
        else:
            self.status_lbl.config(text="Ready | Preview changes before importing or organizing.")

    def _rescan_after_startup_recovery(self):
        if self._closing:
            return
        if self._startup_recovery_pending:
            self._startup_rescan_after_id = self.after(100, self._rescan_after_startup_recovery)
            return
        self.tags_panel.rescan_library(notify_busy=False)

    def install_shutdown_handlers(self):
        self.protocol("WM_DELETE_WINDOW", self.request_graceful_shutdown)
        if platform.system() == "Darwin":
            self.tk.createcommand("tk::mac::Quit", self.request_graceful_shutdown)

    def set_application_styling_theme(self):
        """Builds custom application styles mapped to our decoupled central theme file."""
        style = ttk.Style()
        t = gui_theme.THEME
        
        # 🌟 FIXED CROSS-PLATFORM GRAPHICS THEME: Use 'aqua' on macOS, 'clam' on Windows/Linux
        current_sys = platform.system()
        if current_sys == "Darwin":
            style.theme_use("aqua")
        else:
            style.theme_use("clam")

        # 🌟 FIXED CROSS-PLATFORM TYPOGRAPHY STACK: Ensures text metrics scale perfectly on Mac Retina panels
        font_family = "Helvetica" if current_sys == "Darwin" else "Segoe UI"
        self.configure(bg=t["bg_dark"])
        for pattern, value in (
            ("*Font", (font_family, 9)),
            ("*Button.Font", (font_family, 9)),
            ("*Button.padX", 10), ("*Button.padY", 4),
            ("*Button.relief", "flat"), ("*Button.overRelief", "flat"),
            ("*Button.disabledForeground", t["fg_muted"]),
            ("*Button.highlightBackground", t["bg_dark"]),
            ("*Button.highlightColor", t["accent_neon"]),
            ("*Button.highlightThickness", 1),
            ("*Entry.highlightBackground", t["border"]),
            ("*Entry.background", t["bg_field"]),
            ("*Entry.foreground", t["fg_light"]),
            ("*Entry.insertBackground", t["fg_light"]),
            ("*Entry.highlightColor", t["accent_neon"]),
            ("*Entry.disabledBackground", t["bg_field"]),
            ("*Entry.disabledForeground", t["fg_muted"]),
            ("*Entry.readonlyBackground", t["bg_field"]),
            ("*Entry.selectBackground", t["tag_enabled"]),
            ("*Entry.selectForeground", "#ffffff"),
            ("*Listbox.selectBackground", t["tag_enabled"]),
            ("*Listbox.selectForeground", "#ffffff"),
            ("*Listbox.background", t["bg_field"]),
            ("*Listbox.foreground", t["fg_light"]),
            ("*Listbox.highlightBackground", t["border"]),
            ("*Listbox.highlightColor", t["accent_neon"]),
            ("*Text.background", t["bg_field"]),
            ("*Text.foreground", t["fg_light"]),
            ("*Text.insertBackground", t["fg_light"]),
            ("*Text.selectBackground", t["tag_enabled"]),
            ("*Text.selectForeground", t["fg_light"]),
            ("*Text.highlightBackground", t["border"]),
            ("*Text.highlightColor", t["accent_neon"]),
            ("*Scrollbar.background", t["bg_panel"]),
            ("*Scrollbar.activeBackground", t["hover_dark"]),
            ("*Scrollbar.troughColor", t["bg_dark"]),
            ("*Scrollbar.borderWidth", 0),
            ("*Scrollbar.width", 12),
        ):
            self.option_add(pattern, value)

        # Window Frame Backgrounds and Layout Typographies
        style.configure(".", background=t["bg_dark"], foreground=t["fg_light"], font=(font_family, 9))
        style.configure("TLabel", background=t["bg_dark"], foreground=t["fg_light"])
        style.configure("TFrame", background=t["bg_dark"])
        style.configure("TLabelframe", background=t["bg_dark"], foreground=t["accent_neon"])
        style.configure("TLabelframe.Label", background=t["bg_dark"], foreground=t["accent_neon"], font=(font_family, 10, "bold"))

        # Entry Boxes and Input Fields Properties
        style.configure("TEntry", fieldbackground=t["bg_field"], foreground=t["fg_light"], bordercolor=t["border"], insertcolor=t["fg_light"], padding=5)
        style.map("TEntry", fieldbackground=[("disabled", t["bg_panel"]), ("focus", t["bg_field"])],
                  foreground=[("disabled", t["fg_muted"])], bordercolor=[("focus", t["accent_neon"])])

        # Dropdown Combobox Layout Arrays
        style.configure("TCombobox", fieldbackground=t["bg_field"], background=t["bg_panel"], foreground=t["fg_light"], bordercolor="#555555", arrowcolor=t["fg_light"])
        style.map("TCombobox", fieldbackground=[("disabled", t["bg_field"]), ("readonly", t["bg_field"])],
                  foreground=[("disabled", t["fg_muted"]), ("readonly", t["fg_light"])])
        style.configure("TScrollbar", background=t["bg_panel"], troughcolor=t["bg_dark"],
                        bordercolor=t["bg_dark"], arrowcolor=t["fg_muted"])
        style.map("TScrollbar", background=[("active", t["hover_dark"])])
        
        self.option_add("*TCombobox*Listbox.background", t["bg_field"])
        self.option_add("*TCombobox*Listbox.foreground", t["fg_light"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["bg_panel"])
        self.option_add("*TCombobox*Listbox.selectForeground", t["accent_neon"])

        # Control Buttons Highlight Mapping
        style.configure("TButton", background=t["bg_panel"], foreground=t["fg_light"], bordercolor=t["border"], padding=(10, 5), font=(font_family, 9, "bold"))
        style.map("TButton", 
            background=[("disabled", t["bg_field"]), ("active", t["hover_dark"])],
            foreground=[("disabled", t["fg_muted"]), ("active", t["accent_neon"])]
        )

        # Tabbed Notebook Structure Settings
        style.configure("TNotebook", background=t["bg_dark"], borderwidth=0)
        style.configure("TNotebook.Tab", background=t["bg_panel"], foreground=t["fg_muted"], padding=(12, 6), font=(font_family, 9, "bold"))
        style.map("TNotebook.Tab", 
            background=[("selected", t["bg_dark"]), ("active", t["hover_dark"])], 
            foreground=[("selected", t["accent_neon"]), ("active", t["fg_light"])]
        )
        style.configure(
            "Treeview",
            background=t["bg_field"],
            fieldbackground=t["bg_field"],
            foreground=t["fg_light"],
            bordercolor=t["border"],
            lightcolor=t["border"],
            darkcolor=t["border"],
            rowheight=27
        )
        style.map(
            "Treeview",
            background=[("selected", t["tag_enabled"])],
            foreground=[("selected", "white")]
        )
        style.configure(
            "Treeview.Heading",
            background=t["bg_panel"],
            foreground=t["fg_light"],
            bordercolor=t["border"],
            lightcolor=t["border"],
            darkcolor=t["border"],
            font=(font_family, 9, "bold")
        )

        style.configure("TRadiobutton", background=t["bg_dark"], foreground=t["fg_light"])
        style.map("TRadiobutton", foreground=[("active", t["accent_neon"])])
        style.configure("TCheckbutton", background=t["bg_dark"], foreground=t["fg_light"])
        style.map("TCheckbutton", foreground=[("active", t["accent_neon"])])

    def build_notebook_tabs(self):
        """Injects modular workspace panel segments into the core window display layer."""
        library_bar = ttk.Frame(self)
        library_bar.pack(fill="x", padx=10, pady=(7, 0))
        ttk.Label(library_bar, text="Active User Library:").pack(side="left")
        self.active_library_var = tk.StringVar(value=gui_theme.USER_LIBRARY_PATH)
        ttk.Entry(
            library_bar, textvariable=self.active_library_var, state="readonly",
        ).pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(library_bar, text="Choose…", command=self.choose_active_library).pack(side="right")
        ttk.Button(library_bar, text="About", command=self.show_about).pack(side="right", padx=(0, 6))
        ttk.Button(
            library_bar, text="History / Recovery", command=self.open_history_recovery,
        ).pack(side="right", padx=(0, 6))

        # Master Notebook Controller Definition
        self.tab_notebook = ttk.Notebook(self)

        # System Status Footnote Strip Bar
        status_bar = ttk.Frame(self, height=26)
        status_bar.pack(fill="x", side="bottom", padx=5, pady=(2, 5))
        
        # 🌟 FIXED TYPOGRAPHY CALL: Refactored system footnote text style properties safely
        current_sys = platform.system()
        font_family = "Helvetica" if current_sys == "Darwin" else "Segoe UI"
        
        self.status_lbl = tk.Label(
            status_bar, 
            text="Ready | Preview changes before importing or organizing.",
            font=(font_family, 9),
            bg=gui_theme.THEME["bg_dark"],
            fg=gui_theme.THEME["fg_muted"],
            anchor="w"
        )
        self.status_lbl.pack(side="left", fill="x", expand=True, padx=8, pady=2)
        self.tab_notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # WORKSPACE TAB MOUNT SEQUENCING:
        # 1. Home Welcome View Panel
        tab1_frame = ttk.Frame(self.tab_notebook)
        self.tab_notebook.add(tab1_frame, text=" 🚀  Home ")
        tab_cover.build(tab1_frame)

        # 2. Import Dashboard
        self.import_dashboard = ImportTab(self.tab_notebook, self.status_lbl)
        self.tab_notebook.add(self.import_dashboard, text=" 📥  Import ")

        # 3. Organize Library Panel
        self.organize_panel = OrganizeTab(self.tab_notebook, self.status_lbl)
        self.tab_notebook.add(self.organize_panel, text=" 🗃️  Organize ")

        # 4. Searchable sound index
        self.tags_panel = TagsTab(self.tab_notebook, self.status_lbl)
        self.tab_notebook.add(self.tags_panel, text=" 🏷️  Library ")
        self.bind("<<LibraryChanged>>", self.tags_panel.invalidate_library, add="+")

        self.integrations_panel = IntegrationsTab(self.tab_notebook)
        self.tab_notebook.add(self.integrations_panel, text=" Integrations ")

        # 5. Rule Matrix Configuration Dashboard
        tab3_frame = ttk.Frame(self.tab_notebook)
        self.tab_notebook.add(tab3_frame, text=" 📊  Rules ")
        tab_matrix.build(tab3_frame, self.status_lbl)

        # 6. Global Storage Ignore Rules Panel
        self.exclusion_panel = ExclusionsTab(self.tab_notebook)
        self.tab_notebook.add(self.exclusion_panel, text=" 🚫  Skip Folders ")

        # 7. Experimental Options Engine Panel
        self.experimental_panel = ExperimentalTab(self.tab_notebook, self.status_lbl)
        self.tab_notebook.add(self.experimental_panel, text=" ⚙️  Advanced ")

        # 🌟 THE BULLETPROOF TAB WATCHDOG TRACKER:
        # Monitors master notebook tab focus changes directly on the main UI execution loop thread
        self.tab_notebook.bind("<<NotebookTabChanged>>", self.intercept_tab_focus_swap_events)

    def choose_active_library(self):
        selected = filedialog.askdirectory(
            title="Choose the shared Ableton User Library",
            initialdir=gui_theme.USER_LIBRARY_PATH or None,
        )
        if selected:
            self.set_active_library(selected)

    def set_active_library(self, path):
        lease = gui_theme.claim_library_job(self, "Change active User Library")
        if lease is None:
            return False
        try:
            selected = sorter_engine.set_active_library_path(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not change User Library", str(error), parent=self)
            return False
        finally:
            lease.release()
        gui_theme.set_active_library_path(selected)
        self.active_library_var.set(selected)
        self.import_dashboard.set_active_library_path(selected)
        self.organize_panel.set_active_library_path(selected)
        self.event_generate("<<LibraryChanged>>", when="tail")
        self.tags_panel.rescan_library(notify_busy=False)
        return True

    def intercept_tab_focus_swap_events(self, event):
        """Intercepts layout tab navigation actions instantly and safely triggers targeted script safeguards."""
        try:
            active_tab_widget = self.nametowidget(self.tab_notebook.select())
        except Exception:
            return

        if active_tab_widget == self.tags_panel:
            self.tags_panel.ensure_loaded()
        elif active_tab_widget == self.organize_panel:
            self.organize_panel.trigger_instant_volume_safeguard_check()

    def request_graceful_shutdown(self):
        """Request worker cancellation, then close normally after workers finish."""
        if self._closing:
            return
        batch = self.tags_panel._live_batch_dialog
        if batch is not None:
            batch.close()
            if self.tags_panel._live_batch_dialog is not None:
                return
        self._closing = True
        self.tags_panel.stop_sound()
        self.status_lbl.config(
            text=" Application Status: Finishing current file safely before closing...",
            fg=gui_theme.THEME["accent_gold"]
        )
        for panel in (self.import_dashboard, self.organize_panel):
            sorter = getattr(panel, "active_sorter", None)
            if sorter:
                sorter.cancel()
        preview = getattr(self.organize_panel, "preview_sorter", None)
        if preview is not None:
            preview.cancel()
        for thread, cancel in getattr(self, "_background_jobs", []):
            if thread.is_alive() and cancel is not None:
                cancel()
        self._wait_for_workers_before_close(time.monotonic() + 5.0)

    def _wait_for_workers_before_close(self, deadline):
        active = [
            getattr(panel, "active_sorter", None)
            for panel in (self.import_dashboard, self.organize_panel)
        ]
        active.append(getattr(self.organize_panel, "preview_sorter", None))
        if (any(sorter and sorter.is_running() for sorter in active)
                or any(thread.is_alive() for thread, _cancel in getattr(self, "_background_jobs", []))
                or self.organize_panel.has_pending_job()
                or self.tags_panel.has_pending_library_work()):
            self.after(100, self._wait_for_workers_before_close, deadline)
            return
        self.destroy()

if __name__ == "__main__":
    app = ProductionStudioManagerApp()
    app.mainloop()

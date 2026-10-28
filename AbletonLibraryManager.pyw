# AbletonLibraryManager.pyw - Complete Production Application Orchestrator
import tkinter as tk
from tkinter import ttk
import platform
import time

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

class ProductionStudioManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ableton Production Assets & Sample Studio Manager v2.1.0")
        self.geometry("1180x760")
        self.minsize(1020, 700)
        self.set_application_styling_theme()
        self.build_notebook_tabs()
        self._closing = False

        # 🌟 THE ABSOLUTE TERMINATOR PROTOCOL BINDING:
        # Explicitly monitors the OS window close (X) button action to intercept zombie worker threads
        self.install_shutdown_handlers()

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
        # Master Notebook Controller Definition
        self.tab_notebook = ttk.Notebook(self)
        self.tab_notebook.pack(fill="both", expand=True, padx=5, pady=5)

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
        self.after(1500, self.tags_panel.rescan_library)
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

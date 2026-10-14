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
import tab_cover
import tab_matrix
import gui_theme
import sorter_engine

class ProductionStudioManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Ableton Production Assets & Sample Studio Manager v2.0.0")
        self.geometry("1180x760")
        self.minsize(1020, 700)
        self.set_application_styling_theme()
        self.build_notebook_tabs()
        self._closing = False

        # 🌟 THE ABSOLUTE TERMINATOR PROTOCOL BINDING:
        # Explicitly monitors the OS window close (X) button action to intercept zombie worker threads
        self.protocol("WM_DELETE_WINDOW", self.request_graceful_shutdown)

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

        # Window Frame Backgrounds and Layout Typographies
        style.configure(".", background=t["bg_dark"], foreground=t["fg_light"])
        style.configure("TLabel", background=t["bg_dark"], foreground=t["fg_light"])
        style.configure("TFrame", background=t["bg_dark"])
        style.configure("TLabelframe", background=t["bg_dark"], foreground=t["accent_neon"])
        style.configure("TLabelframe.Label", background=t["bg_dark"], foreground=t["accent_neon"], font=(font_family, 10, "bold"))

        # Entry Boxes and Input Fields Properties
        style.configure("TEntry", fieldbackground=t["bg_field"], foreground=t["fg_light"], bordercolor="#555555", insertcolor=t["fg_light"])
        style.map("TEntry", fieldbackground=[("focus", "#3c3c3c")], bordercolor=[("focus", t["accent_neon"])])

        # Dropdown Combobox Layout Arrays
        style.configure("TCombobox", fieldbackground=t["bg_field"], background=t["bg_panel"], foreground=t["fg_light"], bordercolor="#555555", arrowcolor=t["fg_light"])
        style.map("TCombobox", fieldbackground=[("readonly", t["bg_field"])], foreground=[("readonly", t["fg_light"])])
        
        self.option_add("*TCombobox*Listbox.background", t["bg_field"])
        self.option_add("*TCombobox*Listbox.foreground", t["fg_light"])
        self.option_add("*TCombobox*Listbox.selectBackground", t["bg_panel"])
        self.option_add("*TCombobox*Listbox.selectForeground", t["accent_neon"])

        # Control Buttons Highlight Mapping
        style.configure("TButton", background=t["bg_panel"], foreground=t["fg_light"], bordercolor="#555555", font=(font_family, 9, "bold"))
        style.map("TButton", 
            background=[("active", t["hover_dark"]), ("disabled", "#2d2d2d")], 
            foreground=[("active", t["accent_neon"]), ("disabled", "#2d2d2d")]
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
            rowheight=24
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
        status_bar = ttk.Frame(self, height=26, relief="sunken")
        status_bar.pack(fill="x", side="bottom", padx=5, pady=(2, 5))
        
        # 🌟 FIXED TYPOGRAPHY CALL: Refactored system footnote text style properties safely
        current_sys = platform.system()
        font_family = "Helvetica" if current_sys == "Darwin" else "Segoe UI"
        
        self.status_lbl = tk.Label(
            status_bar, 
            text=" Application Status: Engine Online & Ready | Cohort Profile: AFC", 
            font=(font_family, 9),
            bg=gui_theme.THEME["bg_dark"],
            fg=gui_theme.THEME["accent_gold"],
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
        self.tab_notebook.add(self.tags_panel, text=" 🏷️  Sounds & Tags ")

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
            print("🗃️ Switched to Organize tab. Launching cloud-insulated lookahead size evaluation...")
            self.organize_panel.trigger_instant_volume_safeguard_check()

    def request_graceful_shutdown(self):
        """Request worker cancellation, then close normally after workers finish."""
        if self._closing:
            return
        self._closing = True
        self.status_lbl.config(
            text=" Application Status: Finishing current file safely before closing...",
            fg=gui_theme.THEME["accent_gold"]
        )
        for panel in (self.import_dashboard, self.organize_panel):
            sorter = getattr(panel, "active_sorter", None)
            if sorter:
                sorter.cancel()
        self._wait_for_workers_before_close(time.monotonic() + 5.0)

    def _wait_for_workers_before_close(self, deadline):
        active = [
            getattr(panel, "active_sorter", None)
            for panel in (self.import_dashboard, self.organize_panel)
        ]
        if any(sorter and sorter.is_running() for sorter in active):
            if time.monotonic() < deadline:
                self.after(100, self._wait_for_workers_before_close, deadline)
                return
        self.destroy()

if __name__ == "__main__":
    app = ProductionStudioManagerApp()
    app.mainloop()

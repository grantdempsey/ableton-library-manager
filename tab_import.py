# tab_import.py - Core Library Sorting Execution Panel Component
import tkinter as tk
from tkinter import ttk, filedialog
from tab_matrix import messagebox
import tab_matrix
import os
import platform
import gui_theme
import tag_evidence
from sorter_engine import ParallelLibrarySorter

class ImportTab(ttk.Frame):
    def __init__(self, parent, status_label_ref=None):
        """Initializes the multi-threaded sample ingestion control panel layer."""
        super().__init__(parent)
        self.status_lbl = status_label_ref
        self.active_sorter = None
        
        # Track targeted folder directory selection string states
        self.src_dir_var = tk.StringVar(value="")
        self.dest_dir_var = tk.StringVar(value="")
        self.copy_mode_var = tk.BooleanVar(value=True)
        self.preview_only_var = tk.BooleanVar(value=False)
        
        self.setup_ui_layout()
        
        # Schedule auto-detection slightly after initialization to prevent string discarding
        self.after(50, self.prepopulate_and_lock_user_library)

    def setup_ui_layout(self):
        """Constructs a responsive control panel for path entry and log rendering grids."""
        t = gui_theme.THEME

        ttk.Label(
            self, text="Import sounds", font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=15, pady=(14, 0))
        tk.Label(
            self,
            text="Bring in a new pack safely. Choose the folders, preview the plan, "
                 "then make copies in your Ableton Library.",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(12, 0))

        # 1. PATH CONFIGURATION CARD LAYER
        paths_frame = ttk.LabelFrame(self, text=" Step 1: Choose folders ")
        paths_frame.pack(fill="x", padx=15, pady=10, ipady=5)

        # Source Path Layout Matrix
        f_src_row = tk.Frame(paths_frame, bg=t["bg_dark"])
        f_src_row.pack(fill="x", padx=15, pady=6)
        
        tk.Label(f_src_row, text="Sounds to organize:", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], width=22, anchor="w").pack(side="left")
        self.src_entry = tk.Entry(f_src_row, font=("Consolas", 9), bg=t["bg_field"], fg=t["fg_light"], bd=1, relief="solid", textvariable=self.src_dir_var, insertbackground=t["fg_light"])
        self.src_entry.pack(side="left", fill="x", expand=True, ipady=3)
        
        btn_browse_src = tk.Button(
            f_src_row, text="Choose folder...", font=("Segoe UI", 9),
            bg=t["bg_panel"], fg=t["fg_light"], activebackground=t["hover_dark"], activeforeground=t["accent_neon"],
            bd=1, relief="solid", padx=15, command=self.browse_src_directory
        )
        btn_browse_src.pack(side="right", padx=(8, 0))

        # Target Library Path Layout Matrix
        f_dest_row = tk.Frame(paths_frame, bg=t["bg_dark"])
        f_dest_row.pack(fill="x", padx=15, pady=6)

        tk.Label(f_dest_row, text="Your Ableton Library:", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], width=22, anchor="w").pack(side="left")
        
        self.dest_entry = tk.Entry(
            f_dest_row, font=("Consolas", 9), 
            bg=t["bg_field"], fg=t["accent_gold"], 
            readonlybackground=t["bg_field"], 
            state="readonly",
            bd=1, relief="solid", textvariable=self.dest_dir_var, insertbackground=t["fg_light"]
        )
        self.dest_entry.pack(side="left", fill="x", expand=True, ipady=3)

        # 2. SAFETY AND ACTION CONTROLS
        actions_frame = tk.Frame(self, bg=t["bg_dark"])
        actions_frame.pack(fill="x", padx=15, pady=5)
        tk.Label(
            actions_frame, text="Step 2: Preview, then choose an action",
            font=("Segoe UI", 10, "bold"), bg=t["bg_dark"], fg=t["accent_neon"]
        ).pack(anchor="w", padx=5, pady=(4, 6))

        action_choices = tk.Frame(actions_frame, bg=t["bg_dark"])
        action_choices.pack(fill="x", padx=5)
        action_choices.columnconfigure(0, weight=1)
        action_choices.columnconfigure(1, weight=1)
        action_choices.columnconfigure(2, weight=1)
        action_choices.columnconfigure(3, weight=0)

        self.copy_radio = tk.Radiobutton(
            action_choices, text="Make copies (recommended)", variable=self.copy_mode_var, value=True,
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0
        )
        self.move_radio = tk.Radiobutton(
            action_choices, text="Move files (remove originals)", variable=self.copy_mode_var, value=False,
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0
        )

        self.preview_check = tk.Checkbutton(
            action_choices, text="Preview first (recommended; no changes)",
            variable=self.preview_only_var, font=("Segoe UI", 9),
            bg=t["bg_dark"], fg=t["fg_light"],
            activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0,
            anchor="w", justify="left"
        )
        self.preview_check.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.copy_radio.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.move_radio.grid(row=0, column=2, sticky="w")

        self.run_btn = tk.Button(
            action_choices, text="⚡ Start import", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            bd=0, padx=16, pady=4, width=14,
            wraplength=0, command=self.kickoff_pipeline_sorting
        )
        self.run_btn.grid(row=0, column=3, sticky="e", padx=(12, 0))

        # 3. LIVE CONSOLE LEDGER VIEW
        console_frame = ttk.LabelFrame(self, text=" Step 3: Review activity ")
        console_frame.pack(fill="both", expand=True, padx=15, pady=(10, 15))

        f_txt_wrapper = tk.Frame(console_frame, bg=t["bg_field"], bd=1, relief="solid")
        f_txt_wrapper.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(f_txt_wrapper, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.console_log = tk.Text(
            f_txt_wrapper, 
            wrap="none", 
            state="disabled",
            font=("Consolas", 9),
            background=t["bg_field"],
            foreground=t["fg_light"],
            insertbackground=t["fg_light"],
            yscrollcommand=scrollbar.set,
            bd=0,
            highlightthickness=0
        )
        self.console_log.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.console_log.yview)
        
        self.focus_set()

    def browse_src_directory(self):
        directory = filedialog.askdirectory(title="Select Raw Ingestion Audio Source Path")
        if directory:
            self.src_dir_var.set(os.path.normpath(directory))

    def prepopulate_and_lock_user_library(self):
        """Cross-platform path discovery sequence that injects values safely through state handles."""
        resolved_library_path = gui_theme.resolve_user_library_path()

        self.dest_entry.config(state="normal")
        self.dest_dir_var.set(resolved_library_path)
        self.dest_entry.config(state="readonly")

    def write_console_message(self, text_line):
        """Thread-safe UI callback interface mapping lines onto console ledger blocks."""
        self.console_log.config(state="normal")
        self.console_log.insert(tk.END, f"[*] {text_line}\n")
        self.console_log.see(tk.END)
        self.console_log.config(state="disabled")
        
        if self.status_lbl:
            self.status_lbl.config(text=f" Ingestion Flow: {text_line}", fg=gui_theme.THEME["accent_gold"])

    def kickoff_pipeline_sorting(self):
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            return
        """Initializes parameter matrices and launches ParallelLibrarySorter thread workers."""
        src_path = self.src_dir_var.get().strip()
        dest_path = self.dest_dir_var.get().strip()
        
        # 🌟 FIXED: Pass the raw Boolean primitive directly to synchronize state logic flawlessly 
        copy_mode_flag = bool(self.copy_mode_var.get())

        if not src_path or not os.path.exists(src_path):
            messagebox.showwarning("Missing Source Folder", "Please select a valid source folder containing your raw samples before starting.")
            return

        if not dest_path:
            messagebox.showwarning("Missing Destination Folder", "Choose a destination before starting.")
            return
        if not self.preview_only_var.get():
            try:
                os.makedirs(dest_path, exist_ok=True)
            except OSError as error:
                messagebox.showerror("Could not create destination", str(error))
                return

        self.run_btn.config(state="disabled")
        self.copy_radio.config(state="disabled")
        self.move_radio.config(state="disabled")
        self.preview_check.config(state="disabled")

        self.console_log.config(state="normal")
        self.console_log.delete("1.0", tk.END)
        self.console_log.config(state="disabled")

        self.write_console_message("Initializing multi-threaded organizer engine pipelines...")
        
        self.active_sorter = ParallelLibrarySorter(
            src_path=src_path,
            dest_path=dest_path,
            window_el=self,
            update_status_callback=self.write_console_message,
            done_callback=self.handle_pipeline_completion,
            copy_mode=copy_mode_flag,
            preview_only=bool(self.preview_only_var.get())
        )
        self.active_sorter.start_parallel_sort()

    def handle_pipeline_completion(self, execution_analytics, was_copied):
        """Callback engine interface triggered automatically upon sorting group completion."""
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            return
        self.event_generate("<<LibraryChanged>>", when="tail")
        tab_matrix.rescan_suggestions()
        self.write_console_message("=" * 65)
        self.write_console_message("  INGESTION SUMMARY LEDGER DISPATCH")
        self.write_console_message("=" * 65)
        
        for record_stat, frequency in execution_analytics.items():
            if frequency > 0:
                self.write_console_message(f" -> {record_stat:<45}: {frequency}")
        
        self.write_console_message("=" * 65)
        self.write_console_message("Backing task networks successfully resolved!")

        if self.active_sorter and self.active_sorter.preview_only:
            self.write_console_message("PREVIEW ONLY: no files were changed.")
            records = self.active_sorter.preview_records
            for record in records[:100]:
                self.write_console_message(
                    f" -> {record['filename']} | {record['destination']} | "
                    f"{record['reason']} | confidence {record['confidence']:.0%} | "
                    f"tags: {', '.join(record['tags']) or 'none'}"
                )
                evidence = tag_evidence.describe_preview_evidence(record)
                if evidence:
                    self.write_console_message(f"    {evidence}")
            if len(records) > 100:
                self.write_console_message(
                    f" -> ... {len(records) - 100} additional preview records omitted."
                )

        self.run_btn.config(state="normal")
        self.copy_radio.config(state="normal")
        self.move_radio.config(state="normal")
        self.preview_check.config(state="normal")
        
        # 🌟 Build an itemized ingestion ledger string matching your tab entries
        lines = []
        if execution_analytics.get("Native Live Racks (.adg, .amxd, .alc, .adv)", 0) > 0:
            lines.append(f"• Native Live Racks Imported: {execution_analytics['Native Live Racks (.adg, .amxd, .alc, .adv)']}")
        if execution_analytics.get("Synth Presets & Wavetables (.fxp, .vital)", 0) > 0:
            lines.append(f"• Synth Presets Imported: {execution_analytics['Synth Presets & Wavetables (.fxp, .vital)']}")
        if execution_analytics.get("Loops Separated by BPM & Key", 0) > 0:
            lines.append(f"• Loops Sorted by BPM/Key: {execution_analytics['Loops Separated by BPM & Key']}")
        if execution_analytics.get("One-Shots Grouped by Drum Type", 0) > 0:
            lines.append(f"• One-Shots Categorized: {execution_analytics['One-Shots Grouped by Drum Type']}")
        if execution_analytics.get("Skipped Duplicate Items", 0) > 0:
            action_verb = "Skipped" if was_copied else "Deleted from Source"
            lines.append(f"• Identical Duplicates ({action_verb}): {execution_analytics['Skipped Duplicate Items']}")
        if execution_analytics.get("Errors/Skipped Files", 0) > 0:
            lines.append(f"• Errors/Skipped Items: {execution_analytics['Errors/Skipped Files']}")
        operation_errors = self.active_sorter.operation_errors if self.active_sorter else []
        if operation_errors:
            lines.append("• Review required: see the detailed file errors in the activity log.")
            for failure in operation_errors[:25]:
                self.write_console_message(
                    f"ERROR [{failure['operation']}] {failure['source']} -> "
                    f"{failure['destination'] or 'destination unavailable'}: {failure['error']}"
                )
            if len(operation_errors) > 25:
                self.write_console_message(
                    f"ERROR: {len(operation_errors) - 25} additional file errors omitted from the log."
                )

        summary = "\n".join(lines)
        if not summary:
            summary = "No audio files or presets required ingestion."

        # 🌟 FIXED WINDOW SNAP CONSTRAINTS: 
        # Safely extract the absolute top-level root window using Tkinter's master dot notation name lookups
        try:
            master_window_container = self.nametowidget(".")
        except Exception:
            try:
                master_window_container = self.winfo_toplevel()
            except Exception:
                master_window_container = self

        mode_string = "Copy Mode" if was_copied else "Move Mode"

        self.bell()
        messagebox.showinfo(
            "Ingestion Pipeline Complete", 
            f"Sample Ingestion resolved successfully under {mode_string}!\n\n"
            f"Filing Summary:\n{summary}",
            parent=master_window_container  # 🌟 Forces the message window to stay locked directly over the main UI application window
        )
        
        if self.status_lbl:
            self.status_lbl.config(text=" Application Status: Import operation sequence resolved clean.", fg=gui_theme.THEME["accent_neon"])

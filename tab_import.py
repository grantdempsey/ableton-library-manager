# tab_import.py - Core Library Sorting Execution Panel Component
import tkinter as tk
from tkinter import ttk, filedialog
from tab_matrix import messagebox
import tab_matrix
import os
import platform
import json
import hashlib
import queue
import gui_theme
import tag_evidence
import serum_presets
import sorter_engine
from sorter_engine import ParallelLibrarySorter, SerumResourceImporter

class ImportTab(ttk.Frame):
    def __init__(self, parent, status_label_ref=None):
        """Initializes the multi-threaded sample ingestion control panel layer."""
        super().__init__(parent)
        self.status_lbl = status_label_ref
        self.active_sorter = None
        self._undo_pending = False
        self._undo_results = queue.Queue()
        
        # Track targeted folder directory selection string states
        self.src_dir_var = tk.StringVar(value="")
        self.dest_dir_var = tk.StringVar(value="")
        self.copy_mode_var = tk.BooleanVar(value=True)
        self.import_scope_var = tk.StringVar(value="supported")
        self.audio_only_var = tk.BooleanVar(value=False)
        self.supported_only_var = tk.BooleanVar(value=True)
        self.reviewed_plan = None
        self._reviewed_settings = None
        
        self.setup_ui_layout()
        for variable in (self.src_dir_var, self.dest_dir_var, self.copy_mode_var,
                         self.import_scope_var):
            variable.trace_add("write", self._invalidate_review)
        
        # Schedule auto-detection slightly after initialization to prevent string discarding
        self.after(50, self.prepopulate_and_lock_user_library)
        self.after(30, self._poll_undo_results)

    def setup_ui_layout(self):
        """Constructs a responsive control panel for path entry and log rendering grids."""
        t = gui_theme.THEME

        ttk.Label(
            self, text="Import sounds", font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=15, pady=(14, 0))
        tk.Label(
            self,
            text="Choose a source and destination, preview the plan, then apply it.",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(12, 0))

        # 1. PATH CONFIGURATION CARD LAYER
        paths_frame = ttk.LabelFrame(self, text=" 1. Choose folders ")
        paths_frame.pack(fill="x", padx=15, pady=10, ipady=5)

        # Source Path Layout Matrix
        f_src_row = tk.Frame(paths_frame, bg=t["bg_dark"])
        f_src_row.pack(fill="x", padx=15, pady=6)
        
        tk.Label(f_src_row, text="Source folder:", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], width=17, anchor="w").pack(side="left")
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

        tk.Label(f_dest_row, text="Destination:", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], width=17, anchor="w").pack(side="left")
        
        self.dest_entry = tk.Entry(
            f_dest_row, font=("Consolas", 9), 
            bg=t["bg_field"], fg=t["accent_gold"], 
            readonlybackground=t["bg_field"],
            bd=1, relief="solid", textvariable=self.dest_dir_var, insertbackground=t["fg_light"]
        )
        self.dest_entry.pack(side="left", fill="x", expand=True, ipady=3)
        tk.Button(
            f_dest_row, text="Choose…", font=("Segoe UI", 9),
            bg=t["bg_panel"], fg=t["fg_light"], activebackground=t["hover_dark"],
            activeforeground=t["accent_neon"], bd=1, relief="solid", padx=12,
            command=self.browse_dest_directory,
        ).pack(side="right", padx=(8, 0))

        # 2. SAFETY AND ACTION CONTROLS
        actions_frame = tk.Frame(self, bg=t["bg_dark"])
        actions_frame.pack(fill="x", padx=15, pady=5)
        action_choices = tk.Frame(actions_frame, bg=t["bg_dark"])
        action_choices.pack(fill="x", padx=5)
        for column in range(3):
            action_choices.columnconfigure(column, weight=1)
        self.audio_type_group = ttk.LabelFrame(action_choices, text=" 2. Audio type ")
        self.operation_group = ttk.LabelFrame(action_choices, text=" 3. Operation ")
        self.review_group = ttk.LabelFrame(action_choices, text=" 4. Review and import ")
        for column, group in enumerate((
            self.audio_type_group, self.operation_group, self.review_group,
        )):
            group.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))

        self.copy_radio = tk.Radiobutton(
            self.operation_group, text="Copy (keep originals)", variable=self.copy_mode_var, value=True,
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0
        )
        self.move_radio = tk.Radiobutton(
            self.operation_group, text="Move (remove originals)", variable=self.copy_mode_var, value=False,
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"], activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0
        )

        self.copy_radio.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        self.move_radio.grid(row=1, column=0, sticky="w", padx=8, pady=(4, 8))

        self.audio_only_check = tk.Radiobutton(
            self.audio_type_group, text="Audio only", variable=self.import_scope_var, value="audio",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"],
            activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0,
        )
        self.supported_only_check = tk.Radiobutton(
            self.audio_type_group, text="Audio + supported presets", variable=self.import_scope_var,
            value="supported", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"],
            activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0,
        )
        self.audio_only_check.grid(row=0, column=0, sticky="w", padx=8, pady=(6, 0))
        self.supported_only_check.grid(row=1, column=0, sticky="w", padx=8, pady=(4, 8))
        self.preview_btn = tk.Button(
            self.review_group, text="Preview plan", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            disabledforeground=t["fg_muted"], bd=0, padx=10, pady=4, command=self.preview_import,
        )
        self.preview_btn.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=(6, 4))
        self.apply_btn = tk.Button(
            self.review_group, text="Apply plan", font=("Segoe UI", 9, "bold"),
            bg=t["btn_secondary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            disabledforeground=t["fg_muted"], bd=0, padx=10, pady=4, state="disabled", command=self.apply_approved_plan,
        )
        self.apply_btn.grid(row=0, column=1, sticky="ew", padx=(4, 8), pady=(6, 4))
        self.export_btn = tk.Button(
            self.review_group, text="Export plan…", state="disabled",
            command=self.export_reviewed_plan, bg=t["btn_secondary"], fg=t["fg_light"],
        )
        self.export_btn.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(0, 8))
        self.cancel_btn = tk.Button(
            self.review_group, text="Cancel import", state="disabled",
            command=self.cancel_import, bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_secondary_hover"], disabledforeground=t["fg_muted"],
        )
        self.cancel_btn.grid(row=1, column=1, sticky="ew", padx=(4, 8), pady=(0, 8))
        self.review_group.columnconfigure((0, 1), weight=1)
        self.import_status_var = tk.StringVar(value="Choose a source folder to begin.")
        tk.Label(
            actions_frame, textvariable=self.import_status_var,
            bg=t["bg_dark"], fg=t["fg_muted"], anchor="w",
        ).pack(fill="x", padx=5, pady=(6, 0))
        tk.Label(
            actions_frame,
            text="Supported presets use configured formats; unknown files and MIDI are excluded. Move history is in History / Recovery.",
            bg=t["bg_dark"], fg=t["fg_muted"], wraplength=900, justify="left",
        ).pack(anchor="w", padx=5, pady=(6, 0))

        # 3. LIVE CONSOLE LEDGER VIEW
        console_frame = ttk.LabelFrame(self, text=" Activity ")
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
        directory = filedialog.askdirectory(title="Select sounds or a complete Serum 2 Presets folder")
        if directory:
            self.src_dir_var.set(os.path.normpath(directory))

    def browse_dest_directory(self):
        directory = filedialog.askdirectory(
            parent=self, title="Choose the destination folder",
            initialdir=self.dest_dir_var.get().strip() or None,
        )
        if directory:
            self.dest_dir_var.set(os.path.normpath(directory))

    def _invalidate_review(self, *_):
        self.reviewed_plan = None
        self._reviewed_settings = None
        if hasattr(self, "apply_btn"):
            self.apply_btn.config(state="disabled", bg=gui_theme.THEME["btn_secondary"])
            self.preview_btn.config(bg=gui_theme.THEME["btn_primary"])
            self.export_btn.config(state="disabled")
            self.import_status_var.set("Settings changed. Preview the plan again before applying.")

    def _selected_scope(self):
        audio_only = self.import_scope_var.get() == "audio"
        self.audio_only_var.set(audio_only)
        self.supported_only_var.set(not audio_only)
        return audio_only, not audio_only

    def _settings_snapshot(self):
        audio_only, supported_only = self._selected_scope()
        return (
            os.path.normcase(os.path.abspath(self.src_dir_var.get().strip())),
            os.path.normcase(os.path.abspath(self.dest_dir_var.get().strip())),
            bool(self.copy_mode_var.get()), audio_only, supported_only,
        )

    def prepopulate_and_lock_user_library(self):
        """Cross-platform path discovery sequence that injects values safely through state handles."""
        resolved_library_path = gui_theme.USER_LIBRARY_PATH

        self.dest_entry.config(state="normal")
        self.dest_dir_var.set(resolved_library_path)
        self.dest_entry.config(state="readonly")

    def set_active_library_path(self, path):
        self.dest_dir_var.set(path)

    def write_console_message(self, text_line):
        """Thread-safe UI callback interface mapping lines onto console ledger blocks."""
        self.console_log.config(state="normal")
        self.console_log.insert(tk.END, f"[*] {text_line}\n")
        self.console_log.see(tk.END)
        self.console_log.config(state="disabled")
        
        if self.status_lbl:
            self.status_lbl.config(text=f" Ingestion Flow: {text_line}", fg=gui_theme.THEME["accent_gold"])

    def _start_import(self, *, preview, approved_plan=None):
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            return
        if getattr(self, "_undo_pending", False) is True:
            return
        if self.active_sorter is not None and self.active_sorter.is_running() is True:
            gui_theme.library_job_available(self, "another import")
            return
        src_path = self.src_dir_var.get().strip()
        dest_path = self.dest_dir_var.get().strip()
        copy_mode_flag = bool(self.copy_mode_var.get())
        audio_only_flag, supported_only_flag = self._selected_scope()

        if not src_path or not os.path.exists(src_path):
            messagebox.showwarning("Missing source folder", "Choose a valid source folder first.", parent=self)
            return

        if not dest_path:
            messagebox.showwarning("Missing destination folder", "Choose a valid destination folder first.", parent=self)
            return
        if not gui_theme.library_job_available(self, "Import preview" if preview else "Import"):
            return
        resource_import = serum_presets.is_resource_root(src_path)
        if audio_only_flag and resource_import:
            messagebox.showwarning(
                "Complete Serum resources require their own workflow",
                "Choose Audio + supported presets to copy the complete Serum resource folder intact.",
            )
            return
        if resource_import and not copy_mode_flag:
            messagebox.showwarning(
                "Serum 2 resources are copy-only",
                "Select Make copies to import the complete Serum 2 folder. "
                "The installed Xfer resource folder must remain intact.",
            )
            return
        if not preview and not copy_mode_flag and not resource_import:
            if not messagebox.askyesno(
                "Move imported files?",
                "Files will be removed from their source after verified transfer. Presets that "
                "reference moved samples may stop working. Completed moves can be undone from "
                "History / Recovery.\n\nApply the reviewed plan?",
                parent=self,
            ):
                return
        for button in (self.preview_btn, self.apply_btn, self.export_btn):
            button.config(state="disabled")
        self.copy_radio.config(state="disabled")
        self.move_radio.config(state="disabled")
        self.audio_only_check.config(state="disabled")
        self.supported_only_check.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.import_status_var.set(
            "Previewing plan — no files will change." if preview else "Applying the approved plan…"
        )
        self._preview_settings = self._settings_snapshot() if preview else None

        self.console_log.config(state="normal")
        self.console_log.delete("1.0", tk.END)
        self.console_log.config(state="disabled")

        self.write_console_message("Previewing the complete import plan..." if preview else
                                   "Applying the reviewed import plan...")
        if audio_only_flag:
            self.write_console_message(
                f"AUDIO-ONLY {'COPY' if copy_mode_flag else 'MOVE'}: only supported audio extensions are planned. "
                "Presets, MIDI, drumsets and other non-audio resources are excluded. "
                + ("Originals are kept." if copy_mode_flag else
                   "Transferred originals are removed; completed moves have undo history.")
            )
        if resource_import:
            self.write_console_message(
                "SERUM 2 RESOURCE IMPORT: copying the complete folder structure to "
                f"{os.path.join(dest_path, 'Serum 2 Presets')}. "
                "User presets are sorted by type, then pack. Factory presets, tables, samples "
                "and other resources keep their relative paths. Originals are kept; "
                "conflicting files are never replaced."
            )
        
        worker = SerumResourceImporter if resource_import else ParallelLibrarySorter
        options = ({"approved_plan": approved_plan} if approved_plan is not None else {})
        if not resource_import:
            options.update(audio_only=audio_only_flag, supported_only=supported_only_flag)
        self.active_sorter = worker(
            src_path=src_path,
            dest_path=dest_path,
            window_el=self,
            update_status_callback=self.write_console_message,
            done_callback=self.handle_pipeline_completion,
            copy_mode=copy_mode_flag,
            preview_only=preview,
            **options,
        )
        self.active_sorter.start_parallel_sort()

    def preview_import(self):
        self._invalidate_review()
        self._start_import(preview=True)

    def kickoff_pipeline_sorting(self):
        """Compatibility entry point; importing always starts with a non-mutating preview."""
        self.preview_import()

    def apply_approved_plan(self):
        if self.reviewed_plan is None or self._reviewed_settings != self._settings_snapshot():
            self._invalidate_review()
            messagebox.showwarning(
                "Preview again", "The import settings changed. Preview the plan again before applying.",
                parent=self,
            )
            return
        self._start_import(preview=False, approved_plan=self.reviewed_plan)

    def export_reviewed_plan(self):
        if self.reviewed_plan is None or self.active_sorter is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export approved import plan",
            defaultextension=".json", filetypes=[("JSON plan", "*.json")],
        )
        if not path:
            return
        try:
            self.active_sorter.export_plan(path)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror("Could not export plan", str(error), parent=self)
            return
        self.import_status_var.set(f"Reviewed plan exported to {path}")

    def cancel_import(self):
        if self.active_sorter is None or not self.active_sorter.is_running():
            return
        self.active_sorter.cancel()
        self.cancel_btn.config(state="disabled")
        self.write_console_message(
            "Cancellation requested. Current transfers finish safely; no new files will start. "
            "Completed moves remain and can be undone. Completed copies are kept."
        )

    def undo_move_import(self, log_path=None):
        if self._undo_pending or getattr(self.winfo_toplevel(), "_closing", False):
            return
        if not gui_theme.library_job_available(self, "Undo Move import"):
            return
        path = log_path or filedialog.askopenfilename(
            parent=self, title="Select a Move history log to undo",
            initialdir=sorter_engine._move_log_dir(), filetypes=[("Move logs", "*.jsonl")],
        )
        if not path:
            return
        try:
            with open(path, "rb") as handle:
                reviewed_contents = handle.read()
            records = [json.loads(line) for line in reviewed_contents.splitlines() if line.strip()]
            reviewed_digest = hashlib.sha256(reviewed_contents).digest()
            if any(
                record.get("copy_mode") is True
                or record.get("operation") == "copy"
                or record.get("action") == "copy"
                for record in records
            ):
                raise ValueError("Copy imports cannot be undone. Select a Move history item.")
            count, created = sorter_engine.describe_move_log(path)
            if not count:
                raise ValueError("This log has no remaining moves to undo.")
            sources = sorted({record.get("source_root", os.path.dirname(record["source"])) for record in records})
            if not messagebox.askyesno(
                "Undo this history item?",
                f"Log: {path}\nRecorded: {created}\nMoves remaining: {count:,}\n"
                f"Original folders:\n" + "\n".join(sources[:5]) +
                "\n\nRestore these recorded moves and duplicate merges? Nothing is overwritten. "
                "Changed or occupied paths are skipped. Copy imports cannot be undone here.",
                parent=self,
            ):
                return
        except (OSError, ValueError, KeyError, TypeError) as error:
            messagebox.showerror("Cannot undo import", str(error), parent=self)
            return
        self._undo_pending = True
        for button in (self.preview_btn, self.apply_btn, self.export_btn):
            button.config(state="disabled")
        def work():
            try:
                with open(path, "rb") as handle:
                    if hashlib.sha256(handle.read()).digest() != reviewed_digest:
                        raise ValueError("Move log changed during review. Select and review it again.")
                result = sorter_engine.undo_move_log(path)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                self._undo_results.put((None, error))
            else:
                self._undo_results.put((result, None))
        try:
            thread = gui_theme.start_background_job(self, work, library_job="Undo Move import")
        except RuntimeError as error:
            self._undo_results.put((None, error))
            return
        if thread is None:
            self._undo_pending = False
            self.preview_btn.config(state="normal")
            self.apply_btn.config(state="disabled")
            self.export_btn.config(state="disabled")

    def _poll_undo_results(self):
        try:
            result, error = self._undo_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._undo_pending = False
            if not getattr(self.winfo_toplevel(), "_closing", False):
                self.preview_btn.config(state="normal")
                self.apply_btn.config(state="disabled")
                self.export_btn.config(state="disabled")
                if error is not None:
                    messagebox.showerror("Import undo failed", str(error), parent=self)
                else:
                    self.winfo_toplevel().event_generate("<<LibraryChanged>>", when="tail")
                    text = f"{result['restored']:,} files restored; {result['skipped']:,} skipped."
                    for failure in result["errors"]:
                        self.write_console_message(f"UNDO ERROR: {failure}")
                    notify = messagebox.showwarning if result["errors"] or result["skipped"] else messagebox.showinfo
                    notify("Import undo", text + "\nUnresolved entries are retained for retry.", parent=self)
                refresh = getattr(self.winfo_toplevel(), "_refresh_history_list", None)
                if callable(refresh):
                    refresh()
        self.after(30, self._poll_undo_results)

    def handle_pipeline_completion(self, execution_analytics, was_copied):
        """Callback engine interface triggered automatically upon sorting group completion."""
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            return
        preview = bool(self.active_sorter and self.active_sorter.preview_only)
        if not preview:
            self.winfo_toplevel().event_generate("<<LibraryChanged>>", when="tail")
            tab_matrix.rescan_suggestions()
        self.write_console_message("=" * 65)
        self.write_console_message("  INGESTION SUMMARY LEDGER DISPATCH")
        self.write_console_message("=" * 65)
        
        for record_stat, frequency in execution_analytics.items():
            if frequency > 0:
                self.write_console_message(f" -> {record_stat:<45}: {frequency}")
        
        self.write_console_message("=" * 65)
        self.write_console_message(
            "Import finished with errors; review the details below."
            if self.active_sorter and self.active_sorter.operation_errors
            else "Import task finished."
        )

        if preview:
            self.write_console_message("PREVIEW ONLY: no files were changed.")
            records = self.active_sorter.preview_records
            for record in records[:100]:
                destination = record.get("destination_path", record["destination"])
                action = record.get("action", "copy")
                self.write_console_message(
                    f" -> {action}: {record['source']} -> {destination} | "
                    f"collision: {record.get('collision', 'none')} | "
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

        for button in (self.preview_btn, self.apply_btn, self.export_btn):
            button.config(state="normal")
        self.copy_radio.config(state="normal")
        self.move_radio.config(state="normal")
        self.audio_only_check.config(state="normal")
        self.supported_only_check.config(state="normal")
        self.cancel_btn.config(state="disabled")
        
        # 🌟 Build an itemized ingestion ledger string matching your tab entries
        lines = []
        if execution_analytics.get("Non-audio Files Excluded", 0):
            lines.append(f"Non-audio files excluded: {execution_analytics['Non-audio Files Excluded']:,}")
        for key in ("Serum 2 Resource Files Copied", "Serum 2 Resource Files Planned",
                    "Serum 2 Resource Folders Created"):
            if execution_analytics.get(key, 0):
                lines.append(f"{key}: {execution_analytics[key]}")
        if execution_analytics.get("Native Live Racks (.adg, .amxd, .alc, .adv)", 0) > 0:
            lines.append(f"• Native Live Racks Imported: {execution_analytics['Native Live Racks (.adg, .amxd, .alc, .adv)']}")
        if execution_analytics.get("Synth Presets & Wavetables (.fxp, .vital)", 0) > 0:
            lines.append(f"• Synth Presets Imported: {execution_analytics['Synth Presets & Wavetables (.fxp, .vital)']}")
        if execution_analytics.get("Loops Separated by BPM & Key", 0) > 0:
            lines.append(f"• Loops Sorted by BPM/Key: {execution_analytics['Loops Separated by BPM & Key']}")
        if execution_analytics.get("One-Shots Grouped by Drum Type", 0) > 0:
            lines.append(f"• One-Shots Categorized: {execution_analytics['One-Shots Grouped by Drum Type']}")
        if execution_analytics.get("Skipped Duplicate Items", 0) > 0:
            action_verb = (
                "Would skip" if self.active_sorter and self.active_sorter.preview_only and was_copied else
                "Would merge with undo recovery" if self.active_sorter and self.active_sorter.preview_only else
                "Skipped" if was_copied else "Merged with undo recovery"
            )
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
        cancelled = self.active_sorter and self.active_sorter.cancel_event.is_set()
        outcome = (
            "Import needs review; some files were not imported." if operation_errors else
            ("Import cancelled; completed copies were kept." if was_copied else
             "Import cancelled; completed moves remain and can be undone.") if cancelled else
            "Preview complete; no files were changed." if preview else
            f"Import complete under {mode_string}."
        )
        setup_notice = ""
        if isinstance(self.active_sorter, SerumResourceImporter):
            resource_folder = os.path.abspath(
                os.path.join(self.active_sorter.dest, "Serum 2 Presets")
            )
            self.write_console_message(f"Serum 2 resource destination: {resource_folder}")
            setup_notice = f"\n\nSerum 2 resource destination:\n{resource_folder}"
            if not preview and not cancelled and not operation_errors:
                instructions = (
                    "NEXT STEP: In Serum 2 (opened inside Ableton), select this folder as "
                    "the presets/resource location to use the imported copy. Select the "
                    "Serum 2 Presets root, not its Presets/User subfolder.\n"
                    "Use Rescan Folders on Disk in Serum's preset browser after external changes.\n"
                    "In Ableton's browser, find it under User Library, or add this folder "
                    "to Places if needed.\n"
                    "Serum 2 and Ableton preferences were not changed automatically. "
                    "The original Xfer folder is unchanged. A successful copy does not verify "
                    "that Serum 2 resolves the copied samples, tables, or presets; open a "
                    "representative preset in Serum 2 and check that its dependencies load."
                )
                setup_notice += "\n\n" + instructions
                self.write_console_message(instructions)
        notification = messagebox.showwarning if operation_errors else messagebox.showinfo
        notification(
            "Ingestion Pipeline Complete", 
            f"{outcome}\n\n"
            f"Filing Summary:\n{summary}{setup_notice}",
            parent=master_window_container  # 🌟 Forces the message window to stay locked directly over the main UI application window
        )
        
        if self.status_lbl:
            self.status_lbl.config(
                text=f" Application Status: {outcome}",
                fg=gui_theme.THEME["accent_gold"] if operation_errors else gui_theme.THEME["accent_neon"],
            )
        if preview:
            plan = getattr(self.active_sorter, "reviewed_plan", None)
            complete = (
                isinstance(plan, dict)
                and not operation_errors
                and not cancelled
                and self._preview_settings == self._settings_snapshot()
            )
            if complete:
                self.reviewed_plan = plan
                self._reviewed_settings = self._settings_snapshot()
                self.apply_btn.config(state="normal")
                self.export_btn.config(state="normal")
                self.import_status_var.set(
                    "Preview complete. Review the activity, then apply or export this plan."
                )
            else:
                self.reviewed_plan = None
                self._reviewed_settings = None
                self.apply_btn.config(state="disabled")
                self.export_btn.config(state="disabled")
                self.import_status_var.set(
                    "Preview incomplete. Resolve errors and preview again; nothing was applied."
                )
        else:
            self.reviewed_plan = None
            self._reviewed_settings = None
            self.apply_btn.config(state="disabled")
            self.export_btn.config(state="disabled")
            self.import_status_var.set(outcome)
        self.apply_btn.config(bg=gui_theme.THEME["btn_primary"] if self.reviewed_plan is not None
                              else gui_theme.THEME["btn_secondary"])
        self.preview_btn.config(bg=gui_theme.THEME["btn_secondary"] if self.reviewed_plan is not None
                                else gui_theme.THEME["btn_primary"])

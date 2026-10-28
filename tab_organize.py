# tab_organize.py - Piece 1: Framework Component Initialization & UI Grid Layout
import tkinter as tk
from tkinter import ttk, filedialog
from tab_matrix import messagebox, themed_dialog, ask_confirm, show_notice
import tab_matrix
import os
import re
import platform
import threading
import queue
import zipfile
import json
import tempfile
import hashlib

import gui_theme
import sorter_engine
import tag_evidence

class OrganizeTab(ttk.Frame):
    def __init__(self, parent, status_label_ref):
        """Initializes the master user library optimization panel with backup safeguards."""
        super().__init__(parent)
        self.status_lbl = status_label_ref
        
        self.library_dir_var = tk.StringVar(value="")
        self.backup_required_var = tk.BooleanVar(value=True)
        self.backup_location_var = tk.StringVar(value="")
        self.nested_repair_suggestions = []
        self.active_sorter = None
        self.preview_running = False
        self._volume_results = queue.Queue()
        self._volume_thread = None
        self._job_results = queue.Queue()
        self._job_pending = False
        self._sort_pending = False
        self._console_messages = queue.Queue()
        
        self.setup_ui_layout()
        self.after(30, self._poll_job_results)
        self.after(50, self.prepopulate_user_library_path)

        # 🌟 FIXED INTERCEPT BIND: Checks event targets cleanly to suppress recursive sub-widget event bubbling
        self.bind("<Visibility>", lambda e: self.handle_tab_view_activation(e))

    def handle_tab_view_activation(self, event):
        """Triggers path cleaning constraints and runs the rules intercept scanning loop seamlessly on view."""
        # 🌟 CRITICAL SAFETY SHIELD: Only run if the event target matches this specific frame container widget
        if event.widget == self:
            self.strip_text_highlights()
            self.check_for_new_learned_rules_intercept()

    def setup_ui_layout(self):
        """Draws the single-path routing layout matched perfectly to the Import Dashboard geometry."""
        t = gui_theme.THEME

        # 1. Main Action Title Header
        header_lbl = ttk.Label(self, text="Clean up an existing library", font=("Segoe UI", 12, "bold"))
        header_lbl.pack(anchor="w", padx=15, pady=15)
        tk.Label(
            self,
            text="Use this for a library that is already on your computer. A backup is recommended. "
                 "Use the normal cleanup for standard organization. Use Repair nested folders separately "
                 "when you want to review repeated folder names.",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(0, 8))

        # 2. TARGET DIRECTORY SELECTION BLOCK
        src_group = ttk.LabelFrame(self, text=" Step 1: Choose the library ")
        src_group.pack(fill="x", padx=15, pady=8, ipady=5)

        f_src_row = tk.Frame(src_group, bg=t["bg_dark"])
        f_src_row.pack(fill="x", padx=15, pady=8)

        self.ent_src = tk.Entry(f_src_row, font=("Consolas", 9), bg=t["bg_field"], fg=t["accent_gold"], bd=1, relief="solid", textvariable=self.library_dir_var, insertbackground=t["fg_light"])
        self.ent_src.pack(side="left", fill="x", expand=True, ipady=3)

        btn_browse_src = tk.Button(
            f_src_row, text="Change…", font=("Segoe UI", 8),
            bg=t["bg_dark"], fg=t["fg_muted"], activebackground=t["hover_dark"], activeforeground=t["tag_enabled"],
            bd=1, relief="solid", padx=10, command=self.select_library_directory
        )
        btn_browse_src.pack(side="right", padx=(8, 0))

        # 3. SAFETY CARD: keep the size warning next to the backup choice
        safety_group = tk.Frame(
            self, bg=t["bg_field"], bd=1, relief="solid",
            highlightbackground=t["bg_panel"], highlightcolor=t["bg_panel"]
        )
        safety_group.pack(fill="x", padx=15, pady=10)
        self.f_alert_box = tk.Frame(safety_group, bg=t["bg_field"])
        self.f_alert_box.pack(fill="x", padx=12, pady=(8, 2))
        
        self.lbl_alert = tk.Label(
            self.f_alert_box, 
            text="⚠️ This changes files inside the selected library. Keep the backup option on unless you have another backup.",
            font=("Segoe UI", 11, "bold"), bg=t["bg_field"], fg="#ff9900",
            anchor="w", justify="left", wraplength=900
        )
        self.lbl_alert.pack(fill="x", pady=8)

        repair_group = ttk.LabelFrame(self, text=" Optional: Find repeated folders ")
        repair_group.pack(fill="x", padx=15, pady=(0, 8))
        tk.Label(
            repair_group,
            text="Find repeated folders such as Samples/Samples or Loops/.../Loops. "
                 "Nothing moves until you review and approve the suggestions.",
            font=("Segoe UI", 8), bg=t["bg_dark"], fg=t["fg_muted"],
            anchor="w", justify="left", wraplength=900
        ).pack(fill="x", padx=10, pady=(6, 3))
        repair_actions = tk.Frame(repair_group, bg=t["bg_dark"])
        repair_actions.pack(fill="x", padx=10, pady=(0, 6))
        self.scan_nested_btn = tk.Button(
            repair_actions, text="Find repeated folders", command=self.scan_nested_folders,
            bg=t["bg_panel"], fg=t["fg_light"], activebackground=t["hover_dark"],
            activeforeground=t["accent_neon"], bd=1
        )
        self.scan_nested_btn.pack(side="left")
        self.repair_nested_btn = tk.Button(
            repair_actions, text="Repair listed files", command=self.repair_nested_folders,
            bg=t["btn_secondary"], fg=t["fg_muted"], activebackground=t["btn_primary_hover"],
            activeforeground=t["btn_primary_fg"], disabledforeground=t["fg_muted"],
            bd=1, state="disabled"
        )
        self.repair_nested_btn.pack(side="left", padx=8)
        self.nested_status_lbl = tk.Label(
            repair_actions, text="No scan run yet.", font=("Segoe UI", 8),
            bg=t["bg_dark"], fg=t["fg_muted"]
        )
        self.nested_status_lbl.pack(side="left", padx=4)
        nested_wrapper = ttk.Frame(repair_group)
        nested_wrapper.pack(fill="x", padx=10, pady=(0, 5))
        nested_scroll = ttk.Scrollbar(nested_wrapper, orient="vertical")
        nested_scroll.pack(side="right", fill="y")
        self.nested_tree = ttk.Treeview(
            nested_wrapper, columns=("Source", "Destination", "Reason"),
            show="headings", height=2, yscrollcommand=nested_scroll.set,
            selectmode="extended"
        )
        self.nested_tree.pack(fill="x", expand=True)
        nested_scroll.config(command=self.nested_tree.yview)
        for column, width in (("Source", 300), ("Destination", 300), ("Reason", 220)):
            self.nested_tree.heading(column, text=column)
            self.nested_tree.column(column, width=width, anchor="w")

        # 4. UNIFIED DESKTOP ACTION CONTROL ROW
        f_actions_row = tk.Frame(safety_group, bg=t["bg_field"])
        f_actions_row.pack(fill="x", padx=12, pady=(4, 10))
        f_actions_row.columnconfigure(0, weight=1)

        try:
            style = ttk.Style(self.master)
            style.configure("Dark.TCheckbutton", background=t["bg_field"], foreground=t["fg_light"], font=("Segoe UI", 9, "bold"))
            style.map("Dark.TCheckbutton", background=[("active", t["bg_field"]), ("pressed", t["bg_field"])], foreground=[("active", t["accent_neon"])])
        except Exception:
            pass

        cb_wrapper = tk.Frame(f_actions_row, bg=t["bg_field"])
        cb_wrapper.grid(row=0, column=0, sticky="w")

        self.cb_backup = ttk.Checkbutton(
            cb_wrapper, 
            text="Create a backup before cleanup (saved as a .zip file)",
            variable=self.backup_required_var, 
            style="Dark.TCheckbutton",
            command=self.trigger_instant_volume_safeguard_check
        )
        self.cb_backup.pack(side="left", padx=5, anchor="w")
        self.lbl_backup_location = tk.Label(
            f_actions_row, textvariable=self.backup_location_var,
            font=("Segoe UI", 8), bg=t["bg_field"], fg=t["fg_muted"],
            anchor="w", justify="left", wraplength=620
        )
        self.lbl_backup_location.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=(4, 0))
        self.lbl_backup_location.bind(
            "<Configure>",
            lambda event: self.lbl_backup_location.configure(wraplength=max(1, event.width)),
        )

        self.btn_execute = tk.Button(
            f_actions_row, text="⚡ Start cleanup", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            bd=0, padx=20, pady=6, command=self.confirm_and_start
        )
        self.btn_execute.grid(row=0, column=1, sticky="e", padx=5)

        f_tools_row = tk.Frame(safety_group, bg=t["bg_field"])
        f_tools_row.pack(fill="x", padx=12, pady=(0, 10))
        self.btn_preview = tk.Button(
            f_tools_row, text="Preview changes", font=("Segoe UI", 9),
            bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_secondary_hover"], activeforeground=t["accent_neon"],
            bd=1, padx=12, pady=4, command=self.preview_cleanup
        )
        self.btn_preview.pack(side="left", padx=5)
        self.btn_undo = tk.Button(
            f_tools_row, text="Undo last cleanup", font=("Segoe UI", 9),
            bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_secondary_hover"], activeforeground=t["accent_neon"],
            bd=1, padx=12, pady=4, command=self.undo_last_cleanup
        )
        self.btn_undo.pack(side="left", padx=5)
        self.btn_cancel = tk.Button(
            f_tools_row, text="Cancel", font=("Segoe UI", 9),
            bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_danger_hover"], activeforeground="white",
            bd=1, padx=12, pady=4, state="disabled", command=self.cancel_running_job
        )
        self.btn_cancel.pack(side="left", padx=5)
        tk.Label(
            f_tools_row, text="Preview shows what would move. Undo reverses the most recent cleanup.",
            font=("Segoe UI", 8), bg=t["bg_field"], fg=t["fg_muted"]
        ).pack(side="left", padx=10)

# tab_organize.py - Piece 2: Automated Verification Loops & Safeguard Intercept Logic
        # 5. PROGRESS FEEDBACK BAR MATRIX
        f_progress_row = tk.Frame(self, bg=t["bg_dark"])
        f_progress_row.pack(fill="x", padx=15, pady=2)

        self.progress_bar = ttk.Progressbar(f_progress_row, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", pady=(2, 1))
        self.progress_text_var = tk.StringVar(value="")
        tk.Label(
            f_progress_row, textvariable=self.progress_text_var, font=("Segoe UI", 9),
            bg=t["bg_dark"], fg=t["fg_muted"], anchor="w"
        ).pack(fill="x")

        # 6. ACTIVE PIPELINE PROCESSING CONSOLE OUTPUT
        console_frame = ttk.LabelFrame(self, text=" Step 2: Review activity ")
        console_frame.pack(fill="both", expand=True, padx=15, pady=(6, 10))

        f_txt_wrapper = tk.Frame(console_frame, bg=t["bg_field"], bd=1, relief="solid")
        f_txt_wrapper.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(f_txt_wrapper, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.console_log = tk.Text(
            f_txt_wrapper, wrap="none", state="disabled", font=("Consolas", 9),
            background=t["bg_field"], foreground=t["fg_light"], insertbackground=t["fg_light"],
            yscrollcommand=scrollbar.set, bd=0, highlightthickness=0
        )
        self.console_log.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.console_log.yview)
        
        self.focus_set()

    def check_for_new_learned_rules_intercept(self):
        """🌟 FIXED INTERCEPT: Explicitly reads local configuration script matrices directly to intercept unverified background rules."""
        config_filepath = getattr(sorter_engine, 'CONFIG_FILE', 'library_config.json')
        if not os.path.exists(config_filepath):
            return

        try:
            with open(config_filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            has_new_rules = data.get("NEW_RULES_PENDING", False)
            
            if has_new_rules:
                # Enforce style modifications cleanly on main loop parameters
                self.lbl_alert.config(
                    text="⚠️ SORTER ALERT: New automated naming patterns have been learned! Review them in the Rule Matrix tab or proceed.",
                    fg="#ff9900"
                )
                self.f_alert_box.config(
                    highlightbackground="#ff9900", 
                    highlightcolor="#ff9900"
                )
            else:
                self.lbl_alert.config(
                        text="⚠️ WARNING: In-Place Restructuring Active! Your library folders will be organized inline. Backup recommended.",
                        fg="#ff9900"
                )
                self.f_alert_box.config(
                        highlightbackground="#ff9900",
                        highlightcolor="#ff9900"
                )
        except Exception as e:
            print(f"DEBUG: Rule Intercept Error -> {str(e)}")

    def wipe_console_log(self):
        self.console_log.config(state="normal")
        self.console_log.delete("1.0", tk.END)
        self.console_log.config(state="disabled")

    def scan_nested_folders(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        target_path = self.library_dir_var.get().strip()
        if not target_path or not os.path.isdir(target_path):
            messagebox.showerror("Folder Required", "Choose a valid library folder before scanning.")
            return
        self.scan_nested_btn.config(state="disabled")
        self.repair_nested_btn.config(state="disabled", bg=gui_theme.THEME["btn_secondary"], fg=gui_theme.THEME["fg_muted"])
        self.nested_status_lbl.config(text="Scanning for repeated folders...")

        self._start_job("nested", lambda: sorter_engine.find_nested_folder_repairs(target_path))

    def has_pending_job(self):
        return self._job_pending or self._sort_pending or self.preview_running

    def _start_job(self, kind, work):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return False
        self._job_pending = True
        self._job_target = self.library_dir_var.get().strip()
        def worker():
            try:
                result = work()
            except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile, sorter_engine.sqlite3.Error) as error:
                self._job_results.put((kind, None, error))
            else:
                self._job_results.put((kind, result, None))
        if gui_theme.start_background_job(self, worker) is None:
            self._job_pending = False
            return False
        return True

    def _poll_job_results(self):
        try:
            while True:
                message = self._console_messages.get_nowait()
                self.console_log.config(state="normal")
                self.console_log.insert(tk.END, f"{message}\n")
                self.console_log.see(tk.END)
                self.console_log.config(state="disabled")
                self.update_progress_from_message(message)
        except queue.Empty:
            pass
        try:
            kind, result, error = self._job_results.get_nowait()
        except queue.Empty:
            pass
        else:
            self._job_pending = False
            closing = getattr(self.winfo_toplevel(), "_closing", False)
            if error is not None:
                if kind == "backup":
                    self.handle_backup_fault(self._job_target, str(error))
                else:
                    self._restore_job_controls()
                    if closing:
                        self.write_console_message(f"Library operation failed: {error}")
                    else:
                        messagebox.showerror("Library operation failed", str(error), parent=self)
            elif kind == "backup":
                if not closing:
                    self.write_backup_success_log(*result)
            elif kind == "undo":
                if not closing:
                    self.finish_undo(result)
            elif kind == "nested":
                if not closing:
                    self.show_nested_suggestions(result)
        self.after(30, self._poll_job_results)

    def _restore_job_controls(self):
        for button in (self.btn_execute, self.btn_preview, self.btn_undo, self.scan_nested_btn):
            button.config(state="normal")
        self.cb_backup.config(state="normal")
        self.btn_cancel.config(state="disabled")

    def show_nested_suggestions(self, suggestions):
        self.nested_repair_suggestions = suggestions
        self.nested_tree.delete(*self.nested_tree.get_children())
        for suggestion in suggestions[:500]:
            self.nested_tree.insert(
                "", "end",
                values=(suggestion["source"], suggestion["destination"], suggestion["reason"])
            )
        self.scan_nested_btn.config(state="normal")
        if suggestions:
            self.repair_nested_btn.config(
                state="normal", bg=gui_theme.THEME["btn_primary"],
                fg=gui_theme.THEME["btn_primary_fg"]
            )
        else:
            self.repair_nested_btn.config(
                state="disabled", bg=gui_theme.THEME["btn_secondary"],
                fg=gui_theme.THEME["fg_muted"]
            )
        count = len(suggestions)
        self.nested_status_lbl.config(
            text=f"{count} repair suggestion(s) found." if count else "No repeated folders found."
        )

    def repair_nested_folders(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        if not self.nested_repair_suggestions:
            return
        approved = messagebox.askyesno(
            "Confirm Nested Folder Repair",
            f"Move {len(self.nested_repair_suggestions)} file(s) to the proposed locations?\n\n"
            "Existing files will never be overwritten. Files with collisions will be skipped.",
            icon="warning"
        )
        if not approved:
            return
        results = sorter_engine.repair_nested_folder_files(self.nested_repair_suggestions)
        self.event_generate("<<LibraryChanged>>", when="tail")
        self.write_console_message(
            f"Nested-folder repair complete: {results['moved']} moved, "
            f"{results['skipped']} skipped, {len(results['errors'])} errors."
        )
        if results["errors"]:
            self.write_console_message("First repair error: " + results["errors"][0])
        self.scan_nested_folders()

    def write_console_message(self, feedback_string):
        self._console_messages.put(feedback_string)

    def update_progress_from_message(self, message):
        match = re.search(r"\((\d+)/(\d+)\)", str(message))
        if match:
            done, total = int(match.group(1)), int(match.group(2))
            if total > 0:
                percent = min(100, done * 100 / total)
                self.progress_bar["value"] = percent
                self.progress_text_var.set(f"{done:,} of {total:,} files checked  ({percent:.0f}%)")
        elif str(message).startswith("Scanning directory layout"):
            self.progress_text_var.set(str(message).replace("Scanning directory layout safely...", "Scanning...").strip())
        elif "complete" in str(message).lower() or "cancelled" in str(message).lower():
            self.progress_text_var.set("")

    def trigger_instant_volume_safeguard_check(self):
        target_path = self.library_dir_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            return
        if self.backup_required_var.get():
            if self._volume_thread is not None and self._volume_thread.is_alive():
                return
            self._volume_thread = threading.Thread(
                target=self.evaluate_folder_mass_asynchronously, args=(target_path,), daemon=True,
            )
            self._volume_thread.start()
            self.after(50, self._finish_volume_check)

    def _finish_volume_check(self):
        try:
            target, result, error = self._volume_results.get_nowait()
        except queue.Empty:
            self.after(50, self._finish_volume_check)
            return
        self._volume_thread = None
        if target != self.library_dir_var.get().strip():
            self.trigger_instant_volume_safeguard_check()
            return
        if error is not None:
            self.lbl_alert.config(
                text=f"Library size could not be checked completely: {error}",
                fg=gui_theme.THEME["accent_gold"],
            )
        elif result[2]:
            self.render_high_volume_warning_modal(*result)
        else:
            self.lbl_alert.config(text="")

    def strip_text_highlights(self):
        try:
            self.ent_src.selection_clear()
            self.ent_src.xview_moveto(0)
        except Exception:
            pass

    def select_library_directory(self):
        current_typed_path = self.library_dir_var.get().strip()
        starting_dir = current_typed_path if (current_typed_path and os.path.exists(current_typed_path)) else None
        
        selected = filedialog.askdirectory(title="Select Library Folder to Scan and Organize", initialdir=starting_dir)
        if selected:
            self.library_dir_var.set(os.path.normpath(selected))
            self.update_backup_location()
            self.strip_text_highlights()
            self.trigger_instant_volume_safeguard_check()
            self.check_for_new_learned_rules_intercept()

    def prepopulate_user_library_path(self):
        resolved_library_path = gui_theme.resolve_user_library_path()

        self.library_dir_var.set(resolved_library_path)
        self.update_backup_location()
        self.strip_text_highlights()
        
        # Fire rule checks natively right when the path Discovery loop maps successfully
        self.check_for_new_learned_rules_intercept()

# tab_organize.py - Piece 3: Thread-Safe Zip Archivers & Storage Mass Calculators
    def preview_cleanup(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        target_path = self.library_dir_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("Routing Fault", "Please select a valid user library path first.")
            return
        for button in (self.btn_execute, self.btn_preview, self.btn_undo):
            button.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress_bar["value"] = 0
        self.wipe_console_log()
        self.write_console_message("Previewing cleanup. Nothing will be moved...")
        clean_target = os.path.normpath(target_path)
        self.preview_sorter = sorter_engine.ParallelLibrarySorter(
            src_path=clean_target, dest_path=clean_target, window_el=self,
            update_status_callback=self.write_console_message,
            done_callback=self.show_preview_results, copy_mode=False, preview_only=True
        )
        self.preview_running = True
        self.preview_sorter.start_parallel_sort()

    def show_preview_results(self, _stats, _copy_mode):
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            self.preview_running = False
            return
        self.event_generate("<<LibraryChanged>>", when="tail")
        self.btn_cancel.config(state="disabled")
        self.preview_running = False
        for button in (self.btn_execute, self.btn_preview, self.btn_undo):
            button.config(state="normal")
        self.progress_bar["value"] = 100
        records = self.preview_sorter.preview_records
        moves = [r for r in records if os.path.normpath(os.path.dirname(r["source"])) != os.path.normpath(r["destination"])]
        in_place = len(records) - len(moves)
        scope_note = (
            f"Checked {len(records):,} sound and instrument files; other files "
            "(such as .asd analysis files) are left alone, so this is lower than the total file count shown above. "
        )
        evidence_records = [
            record
            for record in records if record.get("tag_suggestion")
        ]
        for record in evidence_records[:100]:
            self.write_console_message(
                f"{record['source']}\n    {tag_evidence.describe_preview_evidence(record)}"
            )
        if len(evidence_records) > 100:
            self.write_console_message(
                f"Showing the first 100 of {len(evidence_records):,} manual Live-tag recommendations."
            )
        evidence_cards = [(
            f"{len(evidence_records):,} manual Live-tag recommendations",
            "Exact tags, alternatives and conflicts are shown in the activity log below "
            "(first 100). These are review-only; they do not change this cleanup plan."
        )] if evidence_records else []
        if not moves:
            show_notice(
                self.winfo_toplevel(), "Preview",
                f"All {len(records):,} sound and instrument files already sit in the right folders. "
                "Other files (such as .asd analysis files) are not counted. "
                "Any tag recommendations are review-only and do not change the routing plan.",
                heading="No planned moves", cards=evidence_cards
            )
            return
        library_root = os.path.normpath(self.library_dir_var.get().strip())
        groups = {}
        for record in moves:
            try:
                label = os.path.relpath(record["destination"], library_root)
            except ValueError:
                label = record["destination"]
            groups.setdefault(label, []).append(record["filename"])
        ordered = sorted(groups.items(), key=lambda item: -len(item[1]))
        cards = [
            (f"{label}  -  {len(names):,} file{'s' if len(names) != 1 else ''}",
             "e.g. " + ", ".join(names[:3]))
            for label, names in ordered[:8]
        ]
        if len(ordered) > 8:
            rest = sum(len(names) for _label, names in ordered[8:])
            cards.append((f"{len(ordered) - 8} more folders  -  {rest:,} files", ""))
        cards.extend(evidence_cards)
        start = themed_dialog(
            self.winfo_toplevel(), "Preview of cleanup",
            f"{len(moves):,} files would move; {in_place:,} are already in place. " + scope_note +
            "Nothing has been changed yet. Every move is logged so you can undo it.",
            [("Close", False), ("Start cleanup", True)], default=False,
            heading="Here is what would happen", cards=cards
        )
        if start:
            self.execute_library_restructure()

    def undo_last_cleanup(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        log_path = sorter_engine.latest_move_log()
        if not log_path:
            show_notice(self.winfo_toplevel(), "Undo", "There is no cleanup to undo.", heading="Nothing to undo")
            return
        count, created = sorter_engine.describe_move_log(log_path)
        if not ask_confirm(
            self.winfo_toplevel(), "Undo last cleanup?",
            f"Move {count:,} files from the cleanup on {created} back to where they were?\n\n"
            "Files that were changed or moved since then are skipped, and nothing is overwritten.",
            "Undo cleanup"
        ):
            return
        for button in (self.btn_execute, self.btn_preview, self.btn_undo):
            button.config(state="disabled")
        self.write_console_message(f"Undoing {count:,} moves...")

        self._start_job("undo", lambda: sorter_engine.undo_move_log(log_path))

    def finish_undo(self, result):
        self.event_generate("<<LibraryChanged>>", when="tail")
        for button in (self.btn_execute, self.btn_preview, self.btn_undo):
            button.config(state="normal")
        message = f"{result['restored']:,} files moved back."
        if result["skipped"]:
            message += f"\n{result['skipped']:,} were skipped because they had changed since."
        if result["errors"]:
            message += f"\n{len(result['errors'])} failed; see the activity log."
            for error in result["errors"][:25]:
                self.write_console_message(f"UNDO ERROR: {error}")
        self.write_console_message(message.replace("\n", " "))
        show_notice(self.winfo_toplevel(), "Undo complete", message, heading="Undo finished")

    def confirm_and_start(self):
        if ask_confirm(
            self.winfo_toplevel(), "Start cleanup?",
            "This will move files inside your library into organized folders. "
            "Every move is logged so you can undo it afterwards. Use 'Preview changes' first to see what would happen.",
            "Start cleanup"
        ):
            self.execute_library_restructure()

    def execute_library_restructure(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        target_path = self.library_dir_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("Routing Fault", "Please select a valid user library path before launching execution threads.")
            return

        self.btn_execute.config(state="disabled")
        self.btn_preview.config(state="disabled")
        self.btn_undo.config(state="disabled")
        self.cb_backup.config(state="disabled")
        self.progress_bar["value"] = 0
        self.wipe_console_log()

        if self.backup_required_var.get():
            self.write_console_message("Initializing pre-sorting environment security snapshots...")
            target_dest = self.get_backup_directory(target_path)
            self.write_console_message(f"Backup Destination Directory Target: {target_dest}")
            self._start_job("backup", lambda: self.run_safeguard_archiver_thread(target_path))
        else:
            self.kickoff_sorting_engine(target_path)

    def evaluate_folder_mass_asynchronously(self, target_path):
        """Count the complete library so the safety notice reports actual totals."""
        total_bytes = 0
        local_files_count = 0
        try:
            stack = [os.path.normpath(target_path)]
            while stack:
                current_dir = stack.pop()
                with os.scandir(current_dir) as scandir_iterator:
                    for entry in scandir_iterator:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name != "Ableton Folder Info":
                                stack.append(os.path.normpath(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            if not entry.name.startswith("._") and entry.name != "desktop.ini":
                                total_bytes += entry.stat().st_size
                                local_files_count += 1
        except OSError as error:
            self._volume_results.put((target_path, None, error))
        else:
            gigabytes_mass = total_bytes / (1024 ** 3)
            is_massive_structure = local_files_count > 15000 or total_bytes > (100 * 1024 ** 3)
            self._volume_results.put((
                target_path, (gigabytes_mass, local_files_count, is_massive_structure), None,
            ))

    def render_high_volume_warning_modal(self, gigabytes_mass, local_files_count, is_massive_structure=False):
        """Shows a persistent inline warning instead of interrupting the user's workflow."""
        self.f_alert_box.config(
            highlightbackground="#ff9900",
            highlightcolor="#ff9900"
        )
        self.lbl_alert.config(
            text=(
                f"Large library detected ({local_files_count:,} files, approximately "
                f"{gigabytes_mass:.1f} GB). A backup may take some time and needs extra disk space."
            ),
            fg="#ff9900"
        )

    def run_safeguard_archiver_thread(self, target_path):
        backup_dir = self.get_backup_directory(target_path)
        if os.path.commonpath((os.path.abspath(target_path), os.path.abspath(backup_dir))) == os.path.abspath(target_path):
            raise ValueError("Choose a library whose backup directory is outside the library.")
        os.makedirs(backup_dir, exist_ok=True)
        descriptor, archive_full_path = tempfile.mkstemp(
            prefix="User_Library_Backup_", suffix=".zip", dir=backup_dir
        )
        os.close(descriptor)
        try:
            self.write_console_message("Backing up audio, presets and Live sidecar metadata...")
            local_files_to_pack = []
            stack = [os.path.normpath(target_path)]
            while stack:
                current_dir = stack.pop()
                with os.scandir(current_dir) as entries:
                    for entry in entries:
                        if entry.is_symlink():
                            raise ValueError(f"Backup cannot safely include linked content: {entry.path}")
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(os.path.normpath(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            local_files_to_pack.append((entry.path, sorter_engine._file_identity(entry.path)))
            with zipfile.ZipFile(archive_full_path, "w", zipfile.ZIP_STORED, allowZip64=True) as archive:
                for index, (path, identity) in enumerate(local_files_to_pack, 1):
                    if sorter_engine._file_identity(path) != identity:
                        raise ValueError(f"File changed during backup: {path}")
                    archive.write(path, os.path.relpath(path, target_path))
                    if index % 1000 == 0:
                        self.write_console_message(f"Backup ({index}/{len(local_files_to_pack)})")
            with zipfile.ZipFile(archive_full_path) as archive:
                expected_names = {os.path.relpath(path, target_path).replace(os.sep, "/") for path, _identity in local_files_to_pack}
                if len(archive.infolist()) != len(expected_names) or set(archive.namelist()) != expected_names:
                    raise OSError("Backup archive does not contain every selected file exactly once.")
                if archive.testzip() is not None:
                    raise OSError("Backup archive integrity check failed.")
                for path, identity in local_files_to_pack:
                    with archive.open(os.path.relpath(path, target_path).replace(os.sep, "/")) as contents:
                        if hashlib.file_digest(contents, "sha256").hexdigest() != identity["sha256"]:
                            raise OSError(f"Backup bytes differ from source: {path}")
                    if sorter_engine._file_identity(path) != identity:
                        raise ValueError(f"File changed during backup: {path}")
            self.write_console_message(f"Verified backup: {len(local_files_to_pack):,} files, including metadata.")
            return target_path, archive_full_path
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            try:
                os.remove(archive_full_path)
            except OSError as cleanup_error:
                raise OSError(
                    f"Backup failed ({error}); incomplete archive could not be removed: "
                    f"{archive_full_path}: {cleanup_error}"
                ) from error
            raise OSError(f"Backup incomplete; cleanup did not start: {error}") from error

    def get_backup_directory(self, target_path):
        """Keep backups beside, not inside, the library for visibility and safe rescans."""
        parent_dir = os.path.dirname(os.path.normpath(target_path))
        return os.path.join(parent_dir, "Ableton Library Backups")

    def update_backup_location(self):
        target_path = self.library_dir_var.get().strip()
        if target_path:
            self.backup_location_var.set(
                f"Backup location: {self.get_backup_directory(target_path)}"
            )
        else:
            self.backup_location_var.set("Backup location will appear after you choose a library.")

# tab_organize.py - Piece 4: Parallel Sorting Engine Activation & Reporting Matrices
    def write_backup_success_log(self, target_path, archive_full_path):
        self.write_console_message(f"Archival package generated cleanly at location:\n -> {archive_full_path}")
        self.kickoff_sorting_engine(target_path)

    def handle_backup_fault(self, target_path, error_string):
        self.btn_execute.config(state="normal")
        self.btn_preview.config(state="normal")
        self.btn_undo.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.cb_backup.config(state="normal")
        if getattr(self.winfo_toplevel(), "_closing", False):
            self.write_console_message(f"Backup failed; cleanup did not start: {error_string}")
            return
        proceed_regardless = messagebox.askyesno("Safeguard Fault", f"Archive failed:\n{error_string}\n\nProceed without backup?", icon="warning")
        if proceed_regardless: self.kickoff_sorting_engine(target_path)

    def kickoff_sorting_engine(self, target_path):
        if getattr(self.winfo_toplevel(), "_closing", False):
            return
        self._sort_pending = True
        for button in (self.btn_execute, self.btn_preview, self.btn_undo):
            button.config(state="disabled")
        self.cb_backup.config(state="disabled")
        clean_target = os.path.normpath(target_path.strip())
        self.write_console_message("Firing parallel sorting network threads...")
        self.active_sorter = sorter_engine.ParallelLibrarySorter(src_path=clean_target, dest_path=clean_target, window_el=self, update_status_callback=self.write_console_message, done_callback=self.handle_execution_complete, copy_mode=False)
        self.btn_cancel.config(state="normal")
        self.active_sorter.start_parallel_sort()

    def cancel_running_job(self):
        sorter = self.active_sorter if self.btn_execute.cget("state") == "disabled" and self.active_sorter else None
        sorter = getattr(self, "preview_sorter", None) if self.preview_running else sorter
        if not sorter:
            return
        if ask_confirm(
            self.winfo_toplevel(), "Stop now?",
            "The current file finishes, then everything stops. Files already moved stay where they are, and a cleanup can be undone with 'Undo last cleanup'.",
            "Stop"
        ):
            sorter.cancel()
            self.btn_cancel.config(state="disabled")
            self.write_console_message("Stopping...")

    def handle_execution_complete(self, tracking_stats, copy_mode_flag):
        self._sort_pending = False
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            return
        self.event_generate("<<LibraryChanged>>", when="tail")
        self.btn_cancel.config(state="disabled")
        self.btn_execute.config(state="normal")
        self.btn_preview.config(state="normal")
        self.btn_undo.config(state="normal")
        self.cb_backup.config(state="normal")
        self.progress_bar["value"] = 100
        
        was_cancelled = bool(self.active_sorter and self.active_sorter.cancel_event.is_set())
        tab_matrix.rescan_suggestions()
        self.write_console_message("Cleanup stopped early. Files already moved can be undone." if was_cancelled else "In-place database restructure operations resolved clean!")
        lines = []
        if tracking_stats.get("Native Live Racks (.adg, .amxd, .alc, .adv)", 0) > 0: lines.append(f"• Native Racks: {tracking_stats['Native Live Racks (.adg, .amxd, .alc, .adv)']}")
        if tracking_stats.get("Synth Presets & Wavetables (.fxp, .vital)", 0) > 0: lines.append(f"• Presets: {tracking_stats['Synth Presets & Wavetables (.fxp, .vital)']}")
        if tracking_stats.get("Loops Separated by BPM & Key", 0) > 0: lines.append(f"• Loops Sorted: {tracking_stats['Loops Separated by BPM & Key']}")
        if tracking_stats.get("One-Shots Grouped by Drum Type", 0) > 0: lines.append(f"• One-Shots Filed: {tracking_stats['One-Shots Grouped by Drum Type']}")
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
        summary = "\n".join(lines) if lines else "• State Coherent: All existing audio assets match target directory definitions."

        try: master_window_container = self.nametowidget(".")
        except Exception:
            try: master_window_container = self.master
            except Exception: master_window_container = self.winfo_toplevel()

        self.bell() 
        messagebox.showinfo("Structural Optimization Complete", f"In-Place Library operations finished successfully!\n\nSummary:\n{summary}", parent=master_window_container)
        if self.status_lbl: self.status_lbl.config(text=" Application Status: Structural allocation pass verified clean.", fg=gui_theme.THEME["accent_neon"])

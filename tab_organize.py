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
import ableton_tags
import performance_log

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
        self.reviewed_plan = None
        self._reviewed_settings = None
        self._volume_results = queue.Queue()
        self._volume_thread = None
        self._job_results = queue.Queue()
        self._job_pending = False
        self._cleanup_lease = None
        self._sort_pending = False
        self._console_messages = queue.Queue()
        
        self.setup_ui_layout()
        self.library_dir_var.trace_add("write", self._invalidate_review)
        self.backup_required_var.trace_add("write", self._invalidate_review)
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
        """Create a scrollable cleanup workspace that remains usable on short screens."""
        t = gui_theme.THEME

        canvas = tk.Canvas(self, bg=t["bg_dark"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = ttk.Frame(canvas)
        self._organize_canvas = canvas
        self._organize_content = content
        self._organize_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", self._resize_workspace)
        canvas.bind("<Configure>", self._resize_workspace)

        header_lbl = ttk.Label(content, text="Clean up an existing library", font=("Segoe UI", 12, "bold"))
        header_lbl.pack(anchor="w", padx=15, pady=15)
        tk.Label(
            content,
            text="Preview your existing library, review the plan, then apply it. Backups are recommended.",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(0, 8))

        # 2. TARGET DIRECTORY SELECTION BLOCK
        src_group = ttk.LabelFrame(content, text=" 1. Choose the library ")

        f_src_row = tk.Frame(src_group, bg=t["bg_dark"])
        f_src_row.pack(fill="x", padx=15, pady=8)

        self.ent_src = tk.Entry(
            f_src_row, font=("Consolas", 9), bg=t["bg_field"], fg=t["accent_gold"],
            readonlybackground=t["bg_field"], state="readonly", bd=1, relief="solid",
            textvariable=self.library_dir_var, insertbackground=t["fg_light"],
        )
        self.ent_src.pack(side="left", fill="x", expand=True, ipady=3)

        btn_browse_src = tk.Button(
            f_src_row, text="Change…", font=("Segoe UI", 8),
            bg=t["bg_dark"], fg=t["fg_muted"], activebackground=t["hover_dark"], activeforeground=t["tag_enabled"],
            bd=1, relief="solid", padx=10, command=self.select_library_directory
        )
        btn_browse_src.pack(side="right", padx=(8, 0))

        # 3. SAFETY CARD: keep the size warning next to the backup choice
        safety_group = tk.Frame(
            content, bg=t["bg_field"], bd=1, relief="solid",
            highlightbackground=t["bg_panel"], highlightcolor=t["bg_panel"]
        )
        self.safety_group = safety_group
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

        repair_group = ttk.LabelFrame(content, text=" Advanced repair: repeated folders ")
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
        self.repair_group = repair_group
        self.repair_group_open = False
        repair_group.pack_forget()

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

        f_tools_row = tk.Frame(content, bg=t["bg_dark"])
        f_tools_row.pack(fill="x", padx=15, pady=(4, 8))
        self.btn_execute = tk.Button(
            f_tools_row, text="Apply plan", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            disabledforeground=t["fg_muted"],
            bd=0, padx=14, pady=6, state="disabled", command=self.execute_library_restructure
        )
        self.btn_preview = tk.Button(
            f_tools_row, text="Preview plan", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            disabledforeground=t["fg_muted"], bd=0, padx=14, pady=6, command=self.preview_cleanup
        )
        self.btn_preview.pack(side="left")
        self.btn_execute.pack(side="left", padx=8)
        self.btn_undo = tk.Button(
            f_tools_row, text="Undo last cleanup", font=("Segoe UI", 9),
            bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_secondary_hover"], activeforeground=t["accent_neon"],
            bd=1, padx=12, pady=4, command=self.undo_last_cleanup
        )
        self.btn_undo.pack_forget()
        self.btn_recover = tk.Button(
            f_tools_row, text="Recover interrupted transfers", font=("Segoe UI", 9),
            bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_secondary_hover"], activeforeground=t["accent_neon"],
            bd=1, padx=8, pady=4, command=self.scan_transfer_recovery,
        )
        self.btn_recover.pack_forget()
        self.btn_export_plan = tk.Button(
            f_tools_row, text="Export plan…", state="disabled", command=self.export_reviewed_plan,
            bg=t["btn_secondary"], fg=t["fg_light"],
        )
        self.btn_tools = tk.Button(
            f_tools_row, text="More tools ▾",
            bg=t["btn_secondary"], fg=t["fg_light"], relief="raised", padx=10, pady=5,
            command=self.show_more_tools,
        )
        self.tools_menu = tk.Menu(self.btn_tools, tearoff=False)
        self.tools_menu.add_command(label="Export plan…", command=self.export_reviewed_plan, state="disabled")
        self.tools_menu.add_command(label="Repeated-folder repair…", command=self.toggle_repair_options)
        self.btn_tools.pack(side="right")
        self.plan_summary_var = tk.StringVar(value="Preview the library to review proposed changes.")
        tk.Label(
            content, textvariable=self.plan_summary_var, bg=t["bg_dark"], fg=t["fg_light"],
            anchor="w", justify="left", wraplength=900,
        ).pack(fill="x", padx=15, pady=(0, 8))

# tab_organize.py - Piece 2: Automated Verification Loops & Safeguard Intercept Logic
        # 5. PROGRESS FEEDBACK BAR MATRIX
        f_progress_row = tk.Frame(content, bg=t["bg_dark"])
        f_progress_row.pack(fill="x", padx=15, pady=2)

        self.progress_bar = ttk.Progressbar(f_progress_row, orient="horizontal", mode="determinate")
        self.btn_cancel = tk.Button(
            f_progress_row, text="Cancel", font=("Segoe UI", 9),
            bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_danger_hover"], activeforeground="white",
            bd=1, padx=12, pady=4, state="disabled", command=self.cancel_running_job,
        )
        self.progress_text_var = tk.StringVar(value="")
        tk.Label(
            f_progress_row, textvariable=self.progress_text_var, font=("Segoe UI", 9),
            bg=t["bg_dark"], fg=t["fg_muted"], anchor="w"
        ).pack(fill="x")

        # 6. ACTIVE PIPELINE PROCESSING CONSOLE OUTPUT
        console_frame = ttk.LabelFrame(content, text=" Activity ")
        console_frame.pack(fill="both", expand=True, padx=15, pady=(6, 10))

        f_txt_wrapper = tk.Frame(console_frame, bg=t["bg_field"], bd=1, relief="solid")
        f_txt_wrapper.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(f_txt_wrapper, orient="vertical")
        scrollbar.pack(side="right", fill="y")

        self.console_log = tk.Text(
            f_txt_wrapper, wrap="none", state="disabled", font=("Consolas", 9),
            background=t["bg_field"], foreground=t["fg_light"], insertbackground=t["fg_light"],
            yscrollcommand=scrollbar.set, bd=0, highlightthickness=0, height=8
        )
        self.console_log.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        scrollbar.config(command=self.console_log.yview)
        
        self.focus_set()
        self.lbl_alert.bind("<Configure>", lambda event: self.lbl_alert.configure(wraplength=max(1, event.width)))
        self._sync_workflow_controls()

    def _resize_workspace(self, _event=None):
        canvas = self._organize_canvas
        canvas.itemconfigure(
            self._organize_window, width=canvas.winfo_width(),
            height=max(canvas.winfo_height(), self._organize_content.winfo_reqheight()),
        )
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _sync_workflow_controls(self):
        busy = self.has_pending_job()
        reviewed = self.reviewed_plan is not None
        t = gui_theme.THEME
        self.btn_preview.config(
            bg=t["btn_secondary"] if reviewed or busy else t["btn_primary"],
            fg=t["fg_light"] if reviewed or busy else t["btn_primary_fg"],
        )
        self.btn_execute.config(bg=t["btn_primary"] if reviewed and not busy else t["btn_secondary"])
        for index, state in (
            (0, "normal" if reviewed and not busy else "disabled"),
            (1, "disabled" if busy else "normal"),
        ):
            if self.tools_menu.entrycget(index, "state") != state:
                self.tools_menu.entryconfigure(index, state=state)
        if busy:
            if not self.progress_bar.winfo_manager():
                self.btn_cancel.pack(side="right", padx=(8, 0))
                self.progress_bar.pack(side="left", fill="x", expand=True, pady=(2, 1))
        else:
            self.btn_cancel.pack_forget()
            self.progress_bar.pack_forget()
        if self.lbl_alert.cget("text"):
            if not self.f_alert_box.winfo_manager():
                self.f_alert_box.pack(fill="x", padx=12, pady=(8, 2), before=self.cb_backup.master.master)
        else:
            self.f_alert_box.pack_forget()

    def show_more_tools(self):
        try:
            self.tools_menu.tk_popup(
                self.btn_tools.winfo_rootx(),
                self.btn_tools.winfo_rooty() + self.btn_tools.winfo_height(),
            )
        finally:
            self.tools_menu.grab_release()

    def toggle_repair_options(self):
        if self.repair_group_open:
            self.repair_group.pack_forget()
            self.repair_group_open = False
            self.tools_menu.entryconfigure(1, label="Repeated-folder repair…")
        else:
            self.repair_group.pack(fill="x", padx=15, pady=(0, 8), after=self.safety_group)
            self.repair_group_open = True
            self.tools_menu.entryconfigure(1, label="Hide repeated-folder repair")
        self._organize_canvas.configure(scrollregion=self._organize_canvas.bbox("all"))

    def _settings_snapshot(self):
        library = self.library_dir_var.get().strip()
        return (
            os.path.normcase(os.path.abspath(library)) if library else "",
            bool(self.backup_required_var.get()),
        )

    def _invalidate_review(self, *_):
        had_review = self.reviewed_plan is not None
        self.reviewed_plan = None
        self._reviewed_settings = None
        if hasattr(self, "btn_execute"):
            self.btn_execute.config(state="disabled")
            self.btn_export_plan.config(state="disabled")
            self.plan_summary_var.set("Preview the library to review proposed changes.")
            self.progress_text_var.set(
                "Settings changed. Preview the plan again before applying." if had_review else ""
            )
            self._sync_workflow_controls()

    def export_reviewed_plan(self):
        sorter = getattr(self, "preview_sorter", None)
        if self.reviewed_plan is None or sorter is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="Export approved cleanup plan",
            defaultextension=".json", filetypes=[("JSON plan", "*.json")],
        )
        if not path:
            return
        try:
            sorter.export_plan(path)
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror("Could not export plan", str(error), parent=self)
            return
        self.progress_text_var.set(f"Reviewed plan exported to {path}")

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
                    text="New sorting suggestions are available. Review them in Rules before cleanup.",
                    fg="#ff9900"
                )
                self.f_alert_box.config(
                    highlightbackground="#ff9900", 
                    highlightcolor="#ff9900"
                )
            else:
                self.lbl_alert.config(
                        text="Cleanup moves files inside the active library. Keep a backup.",
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
        labels = {
            "backup": "Library backup", "undo": "Undo cleanup", "nested": "Nested-folder scan",
            "recovery_scan": "Transfer recovery scan", "transfer_recovery": "Transfer recovery",
        }
        cleanup_lease = self.__dict__.get("_cleanup_lease") if kind == "backup" else None
        try:
            thread = gui_theme.start_background_job(
                self, worker, library_job=labels[kind], lease=cleanup_lease,
                release_lease=cleanup_lease is None,
            )
        except RuntimeError as error:
            self._job_results.put((kind, None, error))
            return True
        if thread is None:
            self._job_pending = False
            self._release_cleanup_lease()
            self._restore_job_controls()
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
                else:
                    self._release_cleanup_lease()
            elif kind == "undo":
                if not closing:
                    self.finish_undo(result)
            elif kind == "nested":
                if not closing:
                    self.show_nested_suggestions(result)
            elif kind == "recovery_scan":
                if not closing:
                    self.show_transfer_recovery(result)
            elif kind == "transfer_recovery":
                if not closing:
                    self.finish_transfer_recovery(result)
        self._sync_workflow_controls()
        self.after(30, self._poll_job_results)

    def _restore_job_controls(self):
        self.btn_execute.config(state="normal" if self.reviewed_plan is not None else "disabled")
        self.btn_export_plan.config(state="normal" if self.reviewed_plan is not None else "disabled")
        for button in (self.btn_preview, self.btn_undo, self.scan_nested_btn, self.btn_recover):
            button.config(state="normal")
        self.cb_backup.config(state="normal")
        self.btn_cancel.config(state="disabled")

    def _release_cleanup_lease(self):
        lease = self.__dict__.get("_cleanup_lease")
        if lease is not None:
            lease.release()
            self._cleanup_lease = None

    def scan_transfer_recovery(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        root = self.library_dir_var.get().strip()
        if not root or not os.path.isdir(root):
            messagebox.showerror("Folder required", "Choose the destination library to check for interrupted transfers.")
            return
        self.btn_recover.config(state="disabled")
        self._start_job("recovery_scan", lambda: ableton_tags.find_transfer_recovery(root))

    def show_transfer_recovery(self, journals):
        self._restore_job_controls()
        if not journals:
            show_notice(self.winfo_toplevel(), "Transfer recovery", "No interrupted transfers found.")
            return
        for journal in journals:
            self.write_console_message(f"TRANSFER RECOVERY: {journal}")
        if ask_confirm(
            self.winfo_toplevel(), "Recover interrupted transfers?",
            f"Found {len(journals):,} recovery records. Close Live and other manager instances first.\n\n"
            "Unfinished transfers are rolled back to their original audio and Live tags. "
            "Already committed transfers are kept. Changed or conflicting files are left for review. "
            "Recorded index and undo changes are reconciled automatically for new transfers. "
            "Older journals still require a Library rescan. Keep backups; no file is intentionally overwritten.",
            "Recover transfers",
        ):
            self.btn_recover.config(state="disabled")
            self._start_job("transfer_recovery", lambda: sorter_engine.recover_library_transfers(journals))

    def finish_transfer_recovery(self, result):
        self._restore_job_controls()
        self.winfo_toplevel().event_generate("<<LibraryChanged>>", when="tail")
        for error in result["errors"]:
            self.write_console_message(f"TRANSFER RECOVERY ERROR: {error}")
        heading = "Recovery needs review" if result["errors"] else "Recovery finished"
        show_notice(
            self.winfo_toplevel(), heading,
            f"{result['recovered']:,} transfer records recovered; {len(result['errors']):,} need review.\n"
            "Recorded index and undo changes were reconciled for recovered application transfers. "
            "Older journals still require a Library rescan. Unresolved journals and recovery audio were retained.",
            heading=heading,
        )

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
        lease = gui_theme.claim_library_job(self, "Nested-folder repair")
        if lease is None:
            return
        with lease:
            results = sorter_engine.repair_nested_folder_files(self.nested_repair_suggestions)
        self.winfo_toplevel().event_generate("<<LibraryChanged>>", when="tail")
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
            app = self.winfo_toplevel()
            if hasattr(app, "set_active_library"):
                app.set_active_library(selected)
            else:
                self.set_active_library_path(selected)

    def prepopulate_user_library_path(self):
        resolved_library_path = gui_theme.USER_LIBRARY_PATH

        self.set_active_library_path(resolved_library_path, check_safety=False)

    def set_active_library_path(self, path, *, check_safety=True):
        self.ent_src.config(state="normal")
        self.library_dir_var.set(os.path.normpath(path))
        self.ent_src.config(state="readonly")
        self.update_backup_location()
        self.strip_text_highlights()
        if check_safety:
            self.trigger_instant_volume_safeguard_check()
        self.check_for_new_learned_rules_intercept()

# tab_organize.py - Piece 3: Thread-Safe Zip Archivers & Storage Mass Calculators
    def preview_cleanup(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        target_path = self.library_dir_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("Routing Fault", "Please select a valid user library path first.")
            return
        if not gui_theme.library_job_available(self, "Cleanup preview"):
            return
        self._invalidate_review()
        for button in (self.btn_execute, self.btn_preview, self.btn_undo, self.btn_export_plan):
            button.config(state="disabled")
        self.btn_cancel.config(state="normal")
        self.progress_bar["value"] = 0
        self.wipe_console_log()
        self.write_console_message("Previewing cleanup. Nothing will be moved or indexed...")
        clean_target = os.path.normpath(target_path)
        self.preview_sorter = sorter_engine.ParallelLibrarySorter(
            src_path=clean_target, dest_path=clean_target, window_el=self,
            update_status_callback=self.write_console_message,
            done_callback=self.show_preview_results, copy_mode=False, preview_only=True
        )
        self.preview_running = True
        self._preview_settings = self._settings_snapshot()
        self.preview_sorter.start_parallel_sort()

    def show_preview_results(self, _stats, _copy_mode):
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            self.preview_running = False
            return
        self.btn_cancel.config(state="disabled")
        self.preview_running = False
        self.btn_preview.config(state="normal")
        self.btn_undo.config(state="normal")
        errors = self.preview_sorter.operation_errors
        cancelled = self.preview_sorter.cancel_event.is_set()
        plan = getattr(self.preview_sorter, "reviewed_plan", None)
        if (
            errors or cancelled or not isinstance(plan, dict)
            or self._preview_settings != self._settings_snapshot()
        ):
            self.progress_bar["value"] = 0
            self.reviewed_plan = None
            self._reviewed_settings = None
            self.btn_execute.config(state="disabled")
            self.btn_export_plan.config(state="disabled")
            self.progress_text_var.set(
                "Preview incomplete or settings changed. Preview again before applying."
            )
            for failure in errors[:25]:
                self.write_console_message(
                    f"PREVIEW ERROR [{failure['operation']}] {failure['source']}: {failure['error']}"
                )
            show_notice(
                self.winfo_toplevel(), "Preview incomplete",
                "The preview is incomplete because it was cancelled or files could not be checked. "
                "No files were moved. Review the activity log and run preview again before cleanup.",
                heading="Preview incomplete",
            )
            return
        self.reviewed_plan = plan
        self._reviewed_settings = self._settings_snapshot()
        self.btn_execute.config(state="normal")
        self.btn_export_plan.config(state="normal")
        self.progress_text_var.set("Preview complete. Review the plan, then apply or export it.")
        self.progress_bar["value"] = 100
        records = self.preview_sorter.preview_records
        moves = [r for r in records if os.path.normpath(os.path.dirname(r["source"])) != os.path.normpath(r["destination"])]
        duplicates = sum(record.get("action") == "duplicate" for record in moves)
        renames = sum(record.get("collision") == "rename" for record in moves)
        for record in moves[:100]:
            destination = record.get("destination_path", os.path.join(record["destination"], record["filename"]))
            self.write_console_message(
                f"{record.get('action', 'move')}: {record['source']} -> {destination} "
                f"(collision: {record.get('collision', 'none')})"
            )
        if len(moves) > 100:
            self.write_console_message(f"Showing the first 100 of {len(moves):,} planned file operations.")
        in_place = len(records) - len(moves)
        self.plan_summary_var.set(
            f"{len(moves):,} planned operations · {duplicates:,} duplicates · "
            f"{renames:,} renamed collisions · {in_place:,} already organized.\n"
            "Review the detailed preview before applying. Export the complete plan from More tools."
        )
        self._sync_workflow_controls()
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
            groups.setdefault(label, []).append(
                os.path.basename(record.get("destination_path", record["filename"]))
            )
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
        themed_dialog(
            self.winfo_toplevel(), "Preview of cleanup",
            f"{len(moves) - duplicates:,} files would move; {duplicates:,} identical duplicates would merge "
            f"with undo recovery; {renames:,} files need renamed destinations; "
            f"{in_place:,} are already in place. " + scope_note +
            "Audio and sidecars have not been changed. Exact names are in the activity log (first 100). "
            "Apply will verify that the reviewed files, destinations and settings are unchanged. "
            "A mismatch stops the cleanup before writes. Every move is logged for recovery.",
            [("Close", False)], default=False,
            heading="Here is what would happen", cards=cards
        )

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
        self.winfo_toplevel().event_generate("<<LibraryChanged>>", when="tail")
        for button in (self.btn_execute, self.btn_preview, self.btn_undo):
            button.config(state="normal")
        message = f"{result['restored']:,} files moved back."
        if result["skipped"]:
            message += (
                f"\n{result['skipped']:,} were skipped because an original path is occupied, "
                "a moved file is missing, or a file changed. Unresolved entries are kept for retry."
            )
        if result["errors"]:
            message += f"\n{len(result['errors'])} failed; see the activity log."
            for error in result["errors"][:25]:
                self.write_console_message(f"UNDO ERROR: {error}")
        self.write_console_message(message.replace("\n", " "))
        heading = "Undo needs review" if result["errors"] or result["skipped"] else "Undo finished"
        show_notice(self.winfo_toplevel(), heading, message, heading=heading)

    def confirm_and_start(self):
        self.execute_library_restructure()

    def execute_library_restructure(self):
        if self.has_pending_job() or getattr(self.winfo_toplevel(), "_closing", False):
            return
        target_path = self.library_dir_var.get().strip()
        if not target_path or not os.path.exists(target_path):
            messagebox.showerror("Routing Fault", "Please select a valid user library path before launching execution threads.")
            return
        if self.reviewed_plan is None or self._reviewed_settings != self._settings_snapshot():
            self._invalidate_review()
            messagebox.showwarning(
                "Preview again", "The cleanup settings changed. Preview the plan again before applying.",
                parent=self,
            )
            return
        approved_plan = self.reviewed_plan
        if not ask_confirm(
            self.winfo_toplevel(), "Apply reviewed cleanup?",
            f"Library: {target_path}\n\nFiles will be moved inside this library according to the reviewed plan. "
            "A changed file, rule, destination or setting stops the cleanup before it writes. "
            "Completed moves can be undone from History / Recovery.",
            "Apply cleanup"
        ):
            return
        lease = gui_theme.claim_library_job(self, "Library backup and cleanup")
        if lease is None:
            return
        self._cleanup_lease = lease

        self.btn_execute.config(state="disabled")
        self.btn_export_plan.config(state="disabled")
        self.btn_preview.config(state="disabled")
        self.btn_undo.config(state="disabled")
        self.cb_backup.config(state="disabled")
        self.progress_bar["value"] = 0
        self.wipe_console_log()

        if self.backup_required_var.get():
            self.write_console_message("Initializing pre-sorting environment security snapshots...")
            target_dest = self.get_backup_directory(target_path)
            self.write_console_message(f"Backup Destination Directory Target: {target_dest}")
            self._approved_plan_after_backup = approved_plan
            self._start_job(
                "backup",
                lambda: self.run_safeguard_archiver_thread(target_path),
            )
        else:
            self.kickoff_sorting_engine(target_path, approved_plan)

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

    @performance_log.timed("library_backup", lambda result, self, *args, **kwargs: {
        "files": self._performance_backup_files,
        "source_bytes": self._performance_backup_bytes,
    })
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
            self._performance_backup_files = len(local_files_to_pack)
            self._performance_backup_bytes = sum(identity["size"] for _, identity in local_files_to_pack)
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
        self.kickoff_sorting_engine(
            target_path, getattr(self, "_approved_plan_after_backup", None),
        )

    def handle_backup_fault(self, target_path, error_string):
        self.btn_execute.config(state="normal" if self.reviewed_plan is not None else "disabled")
        self.btn_export_plan.config(state="normal" if self.reviewed_plan is not None else "disabled")
        self.btn_preview.config(state="normal")
        self.btn_undo.config(state="normal")
        self.btn_cancel.config(state="disabled")
        self.cb_backup.config(state="normal")
        if getattr(self.winfo_toplevel(), "_closing", False):
            self.write_console_message(f"Backup failed; cleanup did not start: {error_string}")
            self._release_cleanup_lease()
            return
        proceed_regardless = messagebox.askyesno("Safeguard Fault", f"Archive failed:\n{error_string}\n\nProceed without backup?", icon="warning")
        if proceed_regardless:
            self.kickoff_sorting_engine(
                target_path, getattr(self, "_approved_plan_after_backup", None),
            )
        else:
            self._release_cleanup_lease()

    def kickoff_sorting_engine(self, target_path, approved_plan=None):
        if getattr(self.winfo_toplevel(), "_closing", False):
            self._release_cleanup_lease()
            return
        if approved_plan is None:
            approved_plan = self.reviewed_plan
        self._sort_pending = True
        for button in (self.btn_execute, self.btn_preview, self.btn_undo, self.btn_export_plan):
            button.config(state="disabled")
        self.cb_backup.config(state="disabled")
        clean_target = os.path.normpath(target_path.strip())
        self.write_console_message("Firing parallel sorting network threads...")
        self.active_sorter = sorter_engine.ParallelLibrarySorter(
            src_path=clean_target, dest_path=clean_target, window_el=self,
            update_status_callback=self.write_console_message,
            done_callback=self.handle_execution_complete, copy_mode=False,
            approved_plan=approved_plan,
        )
        self.btn_cancel.config(state="normal")
        lease = self.__dict__.get("_cleanup_lease")
        self._cleanup_lease = None
        self.active_sorter.start_parallel_sort(job_lease=lease)

    def cancel_running_job(self):
        sorter = self.active_sorter if self.btn_execute.cget("state") == "disabled" and self.active_sorter else None
        sorter = getattr(self, "preview_sorter", None) if self.preview_running else sorter
        if not sorter:
            return
        if ask_confirm(
            self.winfo_toplevel(), "Stop now?",
            "The current file finishes, then everything stops. Files already moved stay where they are; use History / Recovery to undo completed cleanup moves.",
            "Stop"
        ):
            sorter.cancel()
            self.btn_cancel.config(state="disabled")
            self.write_console_message("Stopping...")

    def handle_execution_complete(self, tracking_stats, copy_mode_flag):
        self._sort_pending = False
        if getattr(self.winfo_toplevel(), "_closing", False) is True:
            return
        self.winfo_toplevel().event_generate("<<LibraryChanged>>", when="tail")
        self.btn_cancel.config(state="disabled")
        self.reviewed_plan = None
        self._reviewed_settings = None
        self.btn_execute.config(state="disabled")
        self.btn_export_plan.config(state="disabled")
        self.btn_preview.config(state="normal")
        self.btn_undo.config(state="normal")
        self.cb_backup.config(state="normal")
        self.progress_bar["value"] = 100
        
        was_cancelled = bool(self.active_sorter and self.active_sorter.cancel_event.is_set())
        operation_errors = self.active_sorter.operation_errors if self.active_sorter else []
        needs_review = bool(operation_errors or tracking_stats.get("Errors/Skipped Files", 0))
        outcome = (
            "Cleanup finished with errors; review the activity log." if needs_review else
            "Cleanup stopped early. Files already moved can be undone." if was_cancelled else
            "Cleanup complete."
        )
        self.progress_bar["value"] = 0 if was_cancelled or needs_review else 100
        tab_matrix.rescan_suggestions()
        self.write_console_message(outcome)
        self.progress_text_var.set(outcome)
        self.plan_summary_var.set(outcome + " Preview again to review any remaining work.")
        lines = []
        if tracking_stats.get("Native Live Racks (.adg, .amxd, .alc, .adv)", 0) > 0: lines.append(f"• Native Racks: {tracking_stats['Native Live Racks (.adg, .amxd, .alc, .adv)']}")
        if tracking_stats.get("Synth Presets & Wavetables (.fxp, .vital)", 0) > 0: lines.append(f"• Presets: {tracking_stats['Synth Presets & Wavetables (.fxp, .vital)']}")
        if tracking_stats.get("Loops Separated by BPM & Key", 0) > 0: lines.append(f"• Loops Sorted: {tracking_stats['Loops Separated by BPM & Key']}")
        if tracking_stats.get("One-Shots Grouped by Drum Type", 0) > 0: lines.append(f"• One-Shots Filed: {tracking_stats['One-Shots Grouped by Drum Type']}")
        if tracking_stats.get("Errors/Skipped Files", 0):
            lines.append(f"Errors/Skipped Items: {tracking_stats['Errors/Skipped Files']}")
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
        summary = "\n".join(lines) if lines else "No file moves were recorded."

        try: master_window_container = self.nametowidget(".")
        except Exception:
            try: master_window_container = self.master
            except Exception: master_window_container = self.winfo_toplevel()

        self.bell()
        notification = messagebox.showwarning if needs_review or was_cancelled else messagebox.showinfo
        notification("Library cleanup", f"{outcome}\n\nSummary:\n{summary}", parent=master_window_container)
        if self.status_lbl:
            self.status_lbl.config(
                text=f" Application Status: {outcome}",
                fg=gui_theme.THEME["accent_gold"] if needs_review or was_cancelled else gui_theme.THEME["accent_neon"],
            )

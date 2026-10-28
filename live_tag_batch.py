import queue
import threading
import tkinter as tk
from tkinter import ttk

import ableton_tags
import gui_theme
import sorter_engine
from tab_matrix import ask_confirm, messagebox, show_notice


class LiveTagBatchDialog(tk.Toplevel):
    """A fixed selection and an ordered queue, reviewed before any sidecar writes."""

    def __init__(self, browser, paths):
        super().__init__(browser)
        self.browser = browser
        self.paths = tuple(paths)
        self.off_page = len(set(paths) - set(browser._asset_paths.values()))
        self.operations = []
        self.plan = None
        self.busy = False
        self.saving = False
        self.results = queue.Queue()
        self.title("Batch Live tags")
        self.minsize(680, 560)
        browser._place_dialog(self, 760, 650)
        self.configure(bg=gui_theme.THEME["bg_dark"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.action_var = tk.StringVar(self, value="add")
        self.tag_var = tk.StringVar(self, value=browser.live_tag_var.get())
        self.group_var = tk.StringVar(self, value=browser.live_group_var.get())
        self.replacement_var = tk.StringVar(self)
        self.status_var = tk.StringVar(self, value="Queue changes, then review. No files have been changed.")
        ttk.Label(
            self, text=f"Captured selection: {len(paths):,} sounds ({self.off_page:,} off page)"
        ).pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(
            self, wraplength=640, justify="left",
            text="Actions run in queue order on this fixed selection. Rename affects these "
                 "assignments only, not Live's global vocabulary. Close Live before saving. "
                 "Existing sidecars get backups; audio is unchanged. "
                 "Plain labels use Tag group; explicit Group|Tag hierarchies keep their group."
        ).pack(fill="x", padx=12)
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=12, pady=8)
        self.action_entry = ttk.Combobox(
            controls, textvariable=self.action_var, values=("add", "remove", "rename"),
            state="readonly", width=9
        )
        self.action_entry.grid(row=0, column=0, sticky="w")
        self.tag_entry = ttk.Combobox(controls, textvariable=self.tag_var, width=35)
        self.tag_entry.grid(row=0, column=1, sticky="ew", padx=6)
        self.queue_button = ttk.Button(controls, text="Queue", command=self.enqueue)
        self.queue_button.grid(row=0, column=2)
        ttk.Label(controls, text="Rename to:").grid(row=1, column=0, pady=5)
        self.replacement_entry = ttk.Entry(controls, textvariable=self.replacement_var)
        self.replacement_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=6)
        controls.columnconfigure(1, weight=1)
        ttk.Label(controls, text="Tag group:").grid(row=2, column=0, pady=4)
        self.group_entry = ttk.Combobox(
            controls, textvariable=self.group_var, values=ableton_tags.TAG_GROUPS, width=20,
            postcommand=self.load_suggestions
        )
        self.group_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6)
        theme = gui_theme.THEME
        self.listing = tk.Listbox(
            self, height=5, exportselection=False,
            bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground=theme["fg_light"],
            highlightbackground=theme["border"], highlightcolor=theme["accent_neon"],
            highlightthickness=1, bd=0, font=("Segoe UI", 9)
        )
        self.listing.pack(fill="x", padx=12)
        actions = ttk.Frame(self)
        actions.pack(fill="x", padx=12, pady=6)
        self.remove_button = ttk.Button(actions, text="Remove queued action", command=self.remove)
        self.remove_button.pack(side="left")
        self.review_button = ttk.Button(actions, text="Review combined changes", command=self.review)
        self.review_button.pack(side="right")
        ttk.Label(self, textvariable=self.status_var, wraplength=640).pack(fill="x", padx=12, pady=4)
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill="both", expand=True, padx=12)
        scroll = ttk.Scrollbar(preview_frame)
        scroll.pack(side="right", fill="y")
        self.preview = tk.Text(
            preview_frame, height=8, wrap="word", state="disabled",
            yscrollcommand=scroll.set, bg=theme["bg_field"], fg=theme["fg_light"],
            insertbackground=theme["fg_light"], selectbackground=theme["tag_enabled"],
            selectforeground=theme["fg_light"], highlightbackground=theme["border"],
            highlightcolor=theme["accent_neon"], highlightthickness=1, bd=0,
            font=("Segoe UI", 9), padx=10, pady=8
        )
        self.preview.pack(fill="both", expand=True)
        scroll.configure(command=self.preview.yview)
        footer = ttk.Frame(self)
        footer.pack(fill="x", padx=12, pady=12)
        self.close_button = ttk.Button(footer, text="Close / discard", command=self.close)
        self.close_button.pack(side="left")
        self.save_button = ttk.Button(footer, text="Save reviewed batch", command=self.save, state="disabled")
        self.save_button.pack(side="right")
        self.edit_controls = (
            self.tag_entry, self.replacement_entry, self.queue_button,
            self.remove_button, self.review_button, self.group_entry
        )
        self.tag_var.trace_add("write", self.invalidate)
        self.replacement_var.trace_add("write", self.invalidate)
        self.action_var.trace_add("write", self.invalidate)
        self.group_var.trace_add("write", self.invalidate)
        self.tag_entry.configure(postcommand=self.load_suggestions)

    def load_suggestions(self):
        self.browser._load_live_tag_suggestions()
        self.tag_entry.configure(values=self.browser.live_tag_entry.cget("values"))
        self.group_entry.configure(values=self.browser.live_group_entry.cget("values"))

    def set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def invalidate(self, *_args):
        self.plan = None
        self.save_button.configure(state="disabled")
        self.set_preview("")
        self.status_var.set("Queue or entry changed. Review again before saving.")

    def enqueue(self):
        if self.busy:
            return
        try:
            action = self.action_var.get()
            if action not in {"add", "remove", "rename"}:
                raise ValueError("Choose add, remove, or rename.")
            tag = ableton_tags.qualify_tag(self.tag_var.get(), self.group_var.get())
            replacement = (
                ableton_tags.qualify_tag(self.replacement_var.get(), self.group_var.get()) if action == "rename" else None
            )
        except ValueError as error:
            messagebox.showerror("Invalid Live tag action", str(error), parent=self)
            return
        self.operations.append(ableton_tags.TagOperation(action, tag, replacement))
        self.listing.insert("end", f"{action}: {tag}" + (f" -> {replacement}" if replacement else ""))
        self.invalidate()

    def remove(self):
        if self.busy:
            return
        selection = self.listing.curselection()
        if selection:
            self.operations.pop(selection[0])
            self.listing.delete(selection[0])
            self.invalidate()

    def set_busy(self, busy, saving=False):
        self.busy = busy
        self.saving = saving
        for control in self.edit_controls:
            control.configure(state="disabled" if busy else "normal")
        self.action_entry.configure(state="disabled" if busy else "readonly")
        self.close_button.configure(state="disabled" if busy else "normal")
        self.save_button.configure(state="disabled")
        self.browser._show_selected_asset()

    def review(self):
        if self.busy:
            return
        if not self.operations:
            show_notice(self, "Batch Live tags", "Queue at least one action before reviewing.")
            return
        self.invalidate()
        self.set_busy(True)
        operations = tuple(self.operations)
        self.status_var.set("Reading sidecars and planning combined changes...")
        def worker():
            try:
                sorter_engine.summarize_asset_selection(self.paths)
                plan = ableton_tags.prepare_batch(self.paths, operations)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                self.results.put(("review", None, error))
            else:
                self.results.put(("review", plan, None))
        threading.Thread(target=worker, daemon=True).start()
        self.after(30, self.finish)

    def save(self):
        if self.busy or self.plan is None:
            return
        plan = self.plan
        if not ask_confirm(
            self, "Save reviewed Live tag batch",
            f"{len(plan.sample_changes):,} changed sounds; {plan.unchanged_count:,} unchanged.\n"
            f"{len(plan.changes):,} sidecars; {len(self.paths):,} captured sounds "
            f"({self.off_page:,} off page).\n\n"
            "Close Live before saving. Existing sidecars receive unique .bak backups. "
            "Audio is unchanged. Concurrent changes abort saving; rollback is best effort, "
            "not a crash-safe transaction.",
            "Save batch"
        ):
            return
        self.set_busy(True, saving=True)
        self.status_var.set("Saving reviewed sidecars. Do not close the app...")
        def worker():
            try:
                sorter_engine.summarize_asset_selection(self.paths)
                backups = plan.commit()
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                self.results.put(("save", None, error))
                return
            try:
                sorter_engine.refresh_live_tag_cache(self.paths)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                self.results.put(("cache", backups, error))
            else:
                self.results.put(("save", backups, None))
        threading.Thread(target=worker, daemon=False).start()
        self.after(30, self.finish)

    def finish(self):
        try:
            stage, result, error = self.results.get_nowait()
        except queue.Empty:
            self.after(30, self.finish)
            return
        self.set_busy(False)
        if error is not None:
            self.plan = None
            if stage == "cache":
                self.operations.clear()
                self.listing.delete(0, "end")
                self.status_var.set("Sidecars saved. Index refresh failed; rescan the library.")
                messagebox.showerror(
                    "Batch Saved - Cache Refresh Failed",
                    f"The sidecars were saved, but the index could not refresh: {error}\n"
                    "Rescan the library. Do not repeat this batch just to refresh the display.",
                    parent=self
                )
            else:
                self.status_var.set("Batch failed. Review again before retrying; see error for recovery details.")
                messagebox.showerror("Live Tag Batch Failed", str(error), parent=self)
            return
        if stage == "review":
            self.plan = result
            self.status_var.set(
                f"{len(result.sample_changes):,} changed; {result.unchanged_count:,} unchanged; "
                f"{len(result.changes):,} sidecars. No files changed yet."
            )
            lines = []
            for path, added, removed in result.sample_changes[:200]:
                lines.append(path)
                lines.extend(f"  + {tag}" for tag in added)
                lines.extend(f"  - {tag}" for tag in removed)
            if len(result.sample_changes) > 200:
                lines.append(f"... {len(result.sample_changes) - 200:,} more changed sounds (included in save).")
            self.set_preview("\n".join(lines) or "No net assignment changes. Nothing to save.")
            if result.changes:
                self.save_button.configure(state="normal")
        else:
            self.plan = None
            self.operations.clear()
            self.listing.delete(0, "end")
            self.set_preview("")
            self.status_var.set(f"Batch saved. {len(result):,} sidecar backup(s) created.")
            try:
                self.browser._render_results(refresh_sidebar=True)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                messagebox.showerror(
                    "Batch Saved - Display Refresh Failed",
                    f"Sidecars and index were saved. Refresh the Library display: {error}", parent=self
                )

    def close(self):
        if self.busy:
            show_notice(self, "Batch Live tags", "Wait for the current review or save to finish.")
            return
        if self.operations and not ask_confirm(
            self, "Discard queued Live tags", "Discard these queued actions? Unsaved actions change no files.",
            "Discard"
        ):
            return
        self.browser._live_batch_dialog = None
        self.destroy()
        self.browser._show_selected_asset()

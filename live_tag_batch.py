import queue
import os
import threading
import tkinter as tk
from tkinter import ttk

import ableton_tags
import gui_theme
import sorter_engine
from tab_matrix import ask_confirm, messagebox, show_notice


class LiveTagBatchDialog(tk.Toplevel):
    """Edits a fixed selection through assigned tags, optional extra edits and a previewed save."""

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
        self.title("Edit Live tags")
        self.minsize(680, 620)
        browser._place_dialog(self, 760, 700)
        self.configure(bg=gui_theme.THEME["bg_dark"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.action_var = tk.StringVar(self, value="add")
        self.tag_var = tk.StringVar(self)
        self.group_var = tk.StringVar(self, value=browser.live_group_var.get())
        self.replacement_var = tk.StringVar(self)
        self._initial_draft = self._draft_values()
        self.status_var = tk.StringVar(self, value="Choose an edit, then preview changes. No files have been changed.")
        self.selection_label = ttk.Label(
            self, text=f"Editing {len(paths):,} selected {'sound' if len(paths) == 1 else 'sounds'} "
                       f"({self.off_page:,} off page)"
        )
        self.selection_label.pack(anchor="w", padx=12, pady=(12, 4))
        ttk.Label(
            self, wraplength=640, justify="left",
            text="1. Choose an edit below.  2. Preview the changes.  3. Save when ready.\n"
                 "This selection stays fixed, even if you change the Library selection."
        ).pack(fill="x", padx=12)
        assigned_frame = ttk.LabelFrame(self, text="Assigned Live tags — select a row to remove or rename it")
        assigned_frame.pack(fill="x", padx=12, pady=(8, 0))
        assigned_scroll = ttk.Scrollbar(assigned_frame)
        assigned_scroll.pack(side="right", fill="y")
        self.assigned_tree = ttk.Treeview(
            assigned_frame, columns=("tag", "count"), show="headings", height=3,
            selectmode="browse", yscrollcommand=assigned_scroll.set
        )
        self.assigned_tree.heading("tag", text="Group | tag")
        self.assigned_tree.heading("count", text="Selected sounds")
        self.assigned_tree.column("tag", width=400, minwidth=200)
        self.assigned_tree.column("count", width=130, minwidth=120, stretch=False)
        self.assigned_tree.pack(fill="x", expand=True)
        assigned_scroll.configure(command=self.assigned_tree.yview)
        self.assigned_tree.bind("<<TreeviewSelect>>", self.select_assignment)
        tools = ttk.Frame(self)
        tools.pack(fill="x", padx=12, pady=4)
        self.refresh_button = ttk.Button(tools, text="Reload assigned tags", command=self.refresh_assignments)
        self.refresh_button.pack(side="left")
        self.vocabulary_button = ttk.Button(
            tools, text="Tag suggestions source...", command=browser._choose_live_vocabulary_database
        )
        self.vocabulary_button.pack(side="right")
        ttk.Label(self, textvariable=browser.tag_suggestions_status, wraplength=640).pack(fill="x", padx=12)
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=12, pady=8)
        self.action_entry = ttk.Combobox(
            controls, textvariable=self.action_var, values=("add", "remove", "rename"),
            state="readonly", width=9
        )
        self.action_entry.grid(row=1, column=0, sticky="w")
        self.tag_entry = ttk.Combobox(controls, textvariable=self.tag_var, width=24)
        self.tag_entry.grid(row=1, column=2, sticky="ew", padx=(6, 0))
        self.replacement_label = ttk.Label(controls, text="Rename to:")
        self.replacement_label.grid(row=2, column=0, pady=5)
        self.replacement_entry = ttk.Entry(controls, textvariable=self.replacement_var)
        self.replacement_entry.grid(row=2, column=1, columnspan=2, sticky="ew", padx=(6, 0))
        controls.columnconfigure(2, weight=1)
        self.group_entry = ttk.Combobox(
            controls, textvariable=self.group_var, values=ableton_tags.TAG_GROUPS, width=16,
            postcommand=self.load_suggestions
        )
        self.group_entry.grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Label(controls, text="Action:").grid(row=0, column=0, sticky="w")
        ttk.Label(controls, text="Group:").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(controls, text="Tag name:").grid(row=0, column=2, sticky="w", padx=6)
        ttk.Label(
            controls, text="Example: Genres + Ambient. Full hierarchies such as Genres|Ambient|Drone also work."
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(5, 0))
        theme = gui_theme.THEME
        self.listing = tk.Listbox(
            self, height=3, exportselection=False,
            bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground=theme["fg_light"],
            highlightbackground=theme["border"], highlightcolor=theme["accent_neon"],
            highlightthickness=1, bd=0, font=("Segoe UI", 9)
        )
        actions = ttk.Frame(self)
        self.actions_frame = actions
        actions.pack(fill="x", padx=12, pady=6)
        self.queue_button = ttk.Button(actions, text="Add another change", command=self.enqueue)
        self.queue_button.pack(side="left")
        self.remove_button = ttk.Button(actions, text="Remove extra change", command=self.remove)
        self.review_button = ttk.Button(actions, text="Preview changes", command=self.review)
        self.review_button.pack(side="right")
        ttk.Label(self, textvariable=self.status_var, wraplength=640).pack(fill="x", padx=12, pady=4)
        preview_frame = ttk.Frame(self)
        preview_frame.pack(fill="both", expand=True, padx=12)
        ttk.Label(preview_frame, text="Changes to save (+ add, - remove)").pack(anchor="w", pady=(0, 3))
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
        footer.pack(side="bottom", fill="x", padx=12, pady=12, before=preview_frame)
        ttk.Label(
            footer, wraplength=620, justify="left",
            text="Close Ableton Live before saving. Save writes only the previewed sidecar changes; "
                 "audio is unchanged. Existing sidecars receive backups. Concurrent edits abort saving; "
                 "rollback is best effort, not crash-safe."
        ).pack(fill="x", pady=(0, 6))
        self.close_button = ttk.Button(footer, text="Close / discard", command=self.close)
        self.close_button.pack(side="left")
        self.save_button = ttk.Button(footer, text="Save changes", command=self.save, state="disabled")
        self.save_button.pack(side="right")
        self.edit_controls = (
            self.tag_entry, self.replacement_entry, self.queue_button,
            self.remove_button, self.review_button, self.group_entry,
            self.refresh_button, self.vocabulary_button, self.assigned_tree
        )
        self.tag_var.trace_add("write", self.invalidate)
        self.replacement_var.trace_add("write", self.invalidate)
        self.action_var.trace_add("write", self.invalidate)
        self.group_var.trace_add("write", self.invalidate)
        self.tag_entry.configure(postcommand=self.load_suggestions)
        self._show_rename_fields()
        self.after_idle(self.refresh_assignments)

    def load_suggestions(self):
        self.browser._load_live_tag_suggestions()
        self.browser._update_tag_suggestion_choices()

    def select_assignment(self, _event=None):
        if self.busy:
            return
        selection = self.assigned_tree.selection()
        if selection:
            tag = self.assigned_tree.item(selection[0], "values")[0]
            self.tag_var.set(tag)
            self.group_var.set(tag.split("|")[0])
            if self.action_var.get() == "add":
                self.action_var.set("remove")

    def refresh_assignments(self):
        if self.busy:
            return
        self.invalidate()
        self.set_busy(True)
        self.status_var.set("Reading assigned Live tags. No sample tags are being written.")
        def worker():
            try:
                sorter_engine.refresh_live_tag_cache(self.paths)
                summary = sorter_engine.summarize_asset_selection(self.paths)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                self.results.put(("assignments", None, error))
            else:
                self.results.put(("assignments", summary, None))
        threading.Thread(target=worker, daemon=True).start()
        self.after(30, self.finish)

    def show_assignments(self, summary):
        self.assigned_tree.delete(*self.assigned_tree.get_children())
        for tag, count in sorted(summary["live_counts"].items()):
            self.assigned_tree.insert("", "end", values=(tag, f"{count:,}/{len(self.paths):,}"))

    def set_preview(self, text):
        self.preview.configure(state="normal")
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", text)
        self.preview.configure(state="disabled")

    def _draft_values(self):
        return (
            self.action_var.get(), self.tag_var.get(),
            self.group_var.get(), self.replacement_var.get(),
        )

    def invalidate(self, *_args):
        self.plan = None
        self.save_button.configure(state="disabled")
        self.set_preview("Preview changes to see additions (+) and removals (-) for each sound.")
        self.status_var.set(
            f"{len(self.operations):,} extra change(s). Preview includes these and the current edit. Nothing saved."
        )
        if self.operations:
            self.listing.pack(fill="x", padx=12, before=self.actions_frame)
            self.remove_button.pack(side="left")
        else:
            self.listing.pack_forget()
            self.remove_button.pack_forget()
        self._show_rename_fields()

    def _show_rename_fields(self):
        for control in (self.replacement_label, self.replacement_entry):
            if self.action_var.get() == "rename":
                control.grid()
            else:
                control.grid_remove()

    def _current_operation(self):
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
            return None
        return ableton_tags.TagOperation(action, tag, replacement)

    def enqueue(self):
        if self.busy:
            return
        operation = self._current_operation()
        if operation is None:
            return
        self.operations.append(operation)
        self.listing.insert(
            "end", f"{operation.action}: {operation.tag}"
            + (f" -> {operation.replacement}" if operation.replacement else "")
        )
        self.tag_var.set("")
        self.replacement_var.set("")
        self.invalidate()
        self.tag_entry.focus_set()

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
            if control is self.assigned_tree:
                control.state(["disabled"] if busy else ["!disabled"])
            else:
                control.configure(state="disabled" if busy else "normal")
        self.action_entry.configure(state="disabled" if busy else "readonly")
        self.close_button.configure(state="disabled" if busy else "normal")
        self.save_button.configure(state="disabled")
        self.browser._show_selected_asset()

    def review(self):
        if self.busy:
            return
        operations = list(self.operations)
        if self.tag_var.get().strip() or self.replacement_var.get().strip():
            operation = self._current_operation()
            if operation is None:
                return
            operations.append(operation)
        if not operations:
            show_notice(self, "Edit Live tags", "Enter a tag to preview.")
            return
        self.invalidate()
        self.set_busy(True)
        operations = tuple(operations)
        self.status_var.set("Preparing preview. No tags have been saved.")
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
                summary = sorter_engine.summarize_asset_selection(self.paths)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                self.results.put(("cache", backups, error))
            else:
                self.results.put(("save", (backups, summary), None))
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
                self.tag_var.set("")
                self.replacement_var.set("")
                self.status_var.set("Sidecars saved. Index refresh failed; rescan the library.")
                messagebox.showerror(
                    "Tags Saved - Index Refresh Failed",
                    f"The sidecars were saved, but the index could not refresh: {error}\n"
                    "Rescan the library. Do not repeat this batch just to refresh the display.",
                    parent=self
                )
            elif stage == "assignments":
                self.status_var.set("Could not read assigned tags. Reload to retry; no tag assignments were written.")
                messagebox.showerror("Read Live Tags Failed", str(error), parent=self)
            else:
                self.status_var.set("Tag edit failed. Preview again before retrying; see error for recovery details.")
                messagebox.showerror("Live Tag Edit Failed", str(error), parent=self)
            return
        if stage == "assignments":
            self.show_assignments(result)
            self.status_var.set(
                "Choose Add to assign a tag, or select an assigned tag to remove or rename it. Nothing saved."
                if result["live_counts"] else "No Live tags assigned. Choose a group and enter a tag to add."
            )
        elif stage == "review":
            self.plan = result
            self.status_var.set(
                f"{len(result.sample_changes):,} "
                f"{'sound' if len(result.sample_changes) == 1 else 'sounds'} will change; "
                f"{result.unchanged_count:,} unchanged. No tags saved yet."
            )
            lines = []
            for path, added, removed in result.sample_changes[:200]:
                lines.extend((os.path.basename(path), f"  Location: {path}"))
                lines.extend(f"  + {tag}" for tag in added)
                lines.extend(f"  - {tag}" for tag in removed)
            if len(result.sample_changes) > 200:
                lines.append(f"... {len(result.sample_changes) - 200:,} more changed sounds (included in save).")
            self.set_preview("\n".join(lines) or "No net assignment changes. Nothing to save.")
            if result.changes:
                self.save_button.configure(state="normal")
        else:
            backups, summary = result
            self.plan = None
            self.operations.clear()
            self.listing.delete(0, "end")
            self.tag_var.set("")
            self.replacement_var.set("")
            self.set_preview("")
            self.status_var.set(f"Changes saved. {len(backups):,} sidecar backup(s) created.")
            self.show_assignments(summary)
            try:
                self.browser._render_results(refresh_sidebar=True)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                messagebox.showerror(
                    "Tags Saved - Display Refresh Failed",
                    f"Sidecars and index were saved. Refresh the Library display: {error}", parent=self
                )

    def close(self):
        if self.busy:
            show_notice(self, "Edit Live tags", "Wait for the current tag operation to finish.")
            return
        has_draft = (
            self._draft_values() != self._initial_draft
            and (self.tag_var.get().strip() or self.replacement_var.get().strip())
        )
        if (self.operations or self.plan is not None or has_draft) and not ask_confirm(
            self, "Discard Live tag changes", "Discard these unsaved edits? No files will change.",
            "Discard"
        ):
            return
        self.browser._live_batch_dialog = None
        self.destroy()
        self.browser._show_selected_asset()

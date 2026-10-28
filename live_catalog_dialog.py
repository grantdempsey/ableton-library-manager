import queue
import threading
import tkinter as tk
from tkinter import ttk

import gui_theme
import live_catalog


class _CatalogBrowser:
    """A deliberately isolated browser: no manager index, tag writer, or filesystem operations."""

    def _build_catalog(self):
        self._pending_callbacks = set()
        self.bind("<Destroy>", self._cancel_callbacks, add="+")
        theme = gui_theme.THEME
        style = ttk.Style(self)
        style.configure("Catalog.Treeview", background="#181b20", fieldbackground="#181b20",
                        foreground=theme["fg_light"], rowheight=27, font=("Segoe UI", 10))
        style.map("Catalog.Treeview", background=[("selected", theme["tag_enabled"])],
                  foreground=[("selected", "#101014")])
        style.configure("Catalog.Treeview.Heading", background=theme["btn_secondary"],
                        foreground=theme["fg_light"], font=("Segoe UI", 10, "bold"), padding=6)
        style.map("Catalog.Treeview.Heading",
                  background=[("active", theme["btn_secondary_hover"])],
                  foreground=[("active", theme["fg_light"])])
        style.configure("Catalog.TEntry", fieldbackground="#181b20", foreground=theme["fg_light"],
                        padding=6, font=("Segoe UI", 10))
        style.configure("Catalog.TButton", padding=(10, 5), font=("Segoe UI", 9, "bold"))
        style.configure("Catalog.Accent.TButton", background=theme["btn_primary"], foreground=theme["btn_primary_fg"],
                        padding=(10, 5), font=("Segoe UI", 9, "bold"))
        style.map("Catalog.Accent.TButton", background=[("active", theme["btn_primary_hover"])],
                  foreground=[("active", theme["btn_primary_fg"])])
        self.samples = ()
        self.vocabulary = ()
        self.results = None
        self.rows = {}
        self.tag_rows = []
        self.active_tags = set()
        self.matches = ()
        self.page_index = 0
        self.page_size = 250
        self._query_revision = 0
        self._query_results = None
        self._pending_query = None
        self.selected_filters = tk.StringVar(
            self, value="Click to select; Ctrl/Cmd-click to toggle; Shift-click for a range. Same group: OR; groups: AND."
        )
        self.page_label = tk.StringVar(self, value="Page 0 of 0")
        self.search = tk.StringVar(self)
        self.group = tk.StringVar(self, value="All groups")
        self.source = tk.StringVar(self, value="All sources")
        self.item_type = tk.StringVar(self, value="All item types")
        self.status = tk.StringVar(self, value="Choose a Live database and load its read-only catalog.")
        self.database = tk.StringVar(self)
        ttk.Label(self, text="Ableton catalog", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        scope_label = ttk.Label(
            self, text="READ ONLY  |  Core Library, Packs and Live-indexed files. "
            "Browsing does not move files, edit tags or add items to your editable Library.",
            foreground=theme["accent_neon"],
            wraplength=850, justify="left"
        )
        scope_label.pack(fill="x", padx=12)
        scope_label.bind("<Configure>", lambda event: scope_label.configure(wraplength=max(200, event.width)))
        locations = ttk.Frame(self)
        locations.pack(fill="x", padx=12, pady=8)
        databases = tuple(str(path) for path in live_catalog.available_databases())
        ttk.Label(locations, text="Live database").pack(side="left", padx=(0, 8))
        self.database_picker = ttk.Combobox(locations, textvariable=self.database, values=databases, state="readonly")
        self.database_picker.pack(side="left", fill="x", expand=True)
        if len(databases) == 1:
            self.database.set(databases[-1])
        self.reload_button = ttk.Button(locations, text="Load / refresh", command=self.load)
        self.reload_button.pack(side="left", padx=(6, 0))
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(controls, text="Search").pack(side="left", padx=(0, 8))
        entry = ttk.Entry(controls, textvariable=self.search, style="Catalog.TEntry")
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.apply())
        ttk.Button(controls, text="Search", command=self.apply, style="Catalog.Accent.TButton").pack(side="left", padx=5)
        type_row = ttk.Frame(self)
        type_row.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(type_row, text="Group").pack(side="left", padx=(0, 6))
        self.group_picker = ttk.Combobox(type_row, textvariable=self.group, values=("All groups",), state="readonly", width=15)
        self.group_picker.pack(side="left")
        ttk.Label(type_row, text="Source").pack(side="left", padx=(10, 6))
        self.source_picker = ttk.Combobox(
            type_row, textvariable=self.source, state="readonly", width=24,
            values=("All sources", "Non-auto (catalog)", "Automatic", "Factory / catalog metadata",
                    "Additional hierarchy metadata", "Browser fields (read only)", "User Library sidecars")
        )
        self.source_picker.pack(side="left")
        for picker in (self.group_picker, self.source_picker):
            picker.bind("<<ComboboxSelected>>", lambda _event: self.apply())
        ttk.Label(type_row, text="Item type").pack(side="left", padx=(10, 6))
        self.type_picker = ttk.Combobox(
            type_row, textvariable=self.item_type, state="readonly",
            values=("All item types",), width=16
        )
        self.type_picker.pack(side="left")
        self.type_picker.bind("<<ComboboxSelected>>", lambda _event: self.apply())
        page_controls = ttk.Frame(self)
        page_controls.pack(fill="x", padx=12, pady=(0, 6))
        self.next_button = ttk.Button(page_controls, text="Next", command=self.next_page, state="disabled", width=7)
        self.next_button.pack(side="right")
        self.previous_button = ttk.Button(page_controls, text="Previous", command=self.previous_page, state="disabled", width=8)
        self.previous_button.pack(side="right", padx=4)
        ttk.Label(page_controls, textvariable=self.page_label).pack(side="right", padx=8)
        filters_label = ttk.Label(page_controls, textvariable=self.selected_filters, wraplength=430,
                                 foreground=theme["accent_gold"], justify="left")
        filters_label.pack(side="left", fill="x", expand=True)
        filters_label.bind("<Configure>", lambda event: filters_label.configure(wraplength=max(100, event.width)))
        panes = tk.PanedWindow(self, orient="horizontal", bg=gui_theme.THEME["bg_dark"], sashwidth=6, height=150)
        panes.pack(fill="both", expand=True, padx=12)
        tag_frame = ttk.Frame(panes)
        panes.add(tag_frame, minsize=180, width=260)
        ttk.Label(tag_frame, text="TAG FILTERS", foreground=theme["accent_neon"],
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(2, 4))
        ttk.Button(tag_frame, text="Clear tag filters", command=self.clear_tag, style="Catalog.TButton").pack(fill="x", pady=(0, 5))
        scroll = ttk.Scrollbar(tag_frame)
        scroll.pack(side="right", fill="y")
        self.tags = tk.Listbox(
            tag_frame, exportselection=False, selectmode="extended", height=5, bg="#181b20", fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground="#101014",
            yscrollcommand=scroll.set, font=("Segoe UI", 10), bd=0, highlightthickness=1,
            highlightbackground=theme["border"], highlightcolor=theme["accent_neon"], activestyle="none"
        )
        self.tags.pack(fill="both", expand=True)
        scroll.configure(command=self.tags.yview)
        self.tags.bind("<<ListboxSelect>>", self.pick_tag)
        sound_frame = ttk.Frame(panes)
        panes.add(sound_frame, minsize=320)
        scroll = ttk.Scrollbar(sound_frame)
        scroll.pack(side="right", fill="y")
        self.sounds = ttk.Treeview(sound_frame, columns=("Name", "Folder"), height=5, show="headings",
                                  style="Catalog.Treeview", selectmode="browse", yscrollcommand=scroll.set)
        self.sounds.tag_configure("alternate", background=theme["bg_panel"])
        self.sounds.heading("Name", text="Item (read only)")
        self.sounds.heading("Folder", text="Catalog folder")
        self.sounds.column("Name", width=220)
        self.sounds.column("Folder", width=300)
        self.sounds.pack(fill="both", expand=True)
        scroll.configure(command=self.sounds.yview)
        self.sounds.bind("<<TreeviewSelect>>", self.show_details)
        horizontal = ttk.Scrollbar(sound_frame, orient="horizontal", command=self.sounds.xview)
        horizontal.pack(side="bottom", fill="x", before=self.sounds)
        self.sounds.configure(xscrollcommand=horizontal.set)
        detail_frame = ttk.Frame(self)
        self.detail_frame = detail_frame
        detail_frame.pack(fill="x", padx=12, pady=8)
        ttk.Label(detail_frame, text="ITEM DETAILS", foreground=theme["accent_neon"],
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))
        detail_scroll = ttk.Scrollbar(detail_frame)
        detail_scroll.pack(side="right", fill="y")
        self.details = tk.Text(
            detail_frame, height=5, wrap="word", state="disabled", bg="#181b20", fg=theme["fg_light"],
            selectbackground=theme["accent_neon"], selectforeground=theme["btn_primary_fg"],
            padx=10, pady=8, font=("Segoe UI", 10), bd=0, yscrollcommand=detail_scroll.set
        )
        self.details.pack(fill="x")
        detail_scroll.configure(command=self.details.yview)
        self.details.tag_configure("heading", foreground=theme["accent_neon"], font=("Segoe UI", 10, "bold"))
        self.details.tag_configure("path", foreground=theme["accent_gold"])
        self.details.tag_configure("matched", foreground=theme["accent_neon"])
        status_label = ttk.Label(self, textvariable=self.status, wraplength=700)
        self.status_label = status_label
        status_label.pack(fill="x", padx=12)
        status_label.bind("<Configure>", lambda event: status_label.configure(wraplength=max(200, event.width)))
        self.loading_banner = tk.Frame(
            panes, bg="#181b20", highlightthickness=2,
            highlightbackground=theme["accent_gold"], cursor="watch"
        )
        loading_card = tk.Frame(self.loading_banner, bg="#181b20")
        loading_card.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.85)
        self.loading_heading = tk.Label(
            loading_card, text="Loading Ableton catalog",
            font=("Segoe UI", 20, "bold"), bg="#181b20", fg=theme["fg_light"]
        )
        self.loading_heading.pack(fill="x", pady=(0, 12))
        self.loading_message = tk.StringVar(self)
        loading_label = tk.Label(
            loading_card, textvariable=self.loading_message,
            font=("Segoe UI", 11), bg="#181b20", fg=theme["accent_gold"],
            wraplength=550, justify="center"
        )
        loading_label.pack(fill="x", pady=(0, 18))
        loading_label.bind("<Configure>", lambda event: loading_label.configure(wraplength=max(100, event.width)))
        self.loading_progress = ttk.Progressbar(loading_card, mode="indeterminate", length=360)
        self.loading_progress.pack(fill="x", padx=25, pady=(0, 12))
        if len(databases) == 1:
            self.load()
        elif databases:
            self.status.set("Multiple Live databases found. Choose the database for your Live version, then Load.")
        else:
            self.status.set("No Live browser database found. Open Live and let its browser finish indexing.")

    def load(self):
        if self.results is not None:
            return
        if not self.database.get():
            self.status.set("No Live database selected.")
            return
        database = self.database.get()
        library_root = gui_theme.USER_LIBRARY_PATH
        results = queue.Queue()
        self.results = results
        self.reload_button.configure(state="disabled")
        self.database_picker.configure(state="disabled")
        self.loading_message.set(
            "Large libraries can take tens of seconds.\n"
            "Reading the Live database and tag sidecars.\n"
            "Please wait. No files or tags are changed."
        )
        self.loading_banner.place(x=0, y=0, relwidth=1, relheight=1, bordermode="outside")
        self.loading_banner.lift()
        self.detail_frame.pack_forget()
        self.loading_progress.start(40)
        self.status.set("Reading Live catalog and User Library sidecars in the background; no files or tags are changed.")
        def worker():
            try:
                samples = live_catalog.read_catalog(database, include_other_items=True)
                vocabulary = live_catalog.read_vocabulary(database)
                samples = live_catalog.read_user_sidecars(samples, library_root)
                vocabulary = tuple(sorted(
                    set(vocabulary) | {tag for sample in samples for tag in sample.manual}, key=str.casefold
                ))
            except (OSError, ValueError, live_catalog.sqlite3.Error) as error:
                results.put(error)
            else:
                results.put((samples, vocabulary))
        threading.Thread(target=worker, daemon=True).start()
        self._schedule(30, self.finish)

    def finish(self):
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self._schedule(30, self.finish)
            return
        self.results = None
        self.loading_progress.stop()
        self.loading_banner.place_forget()
        self.detail_frame.pack(before=self.status_label, fill="x", padx=12, pady=8)
        self.reload_button.configure(state="normal")
        self.database_picker.configure(state="readonly")
        if isinstance(result, Exception):
            self.status.set(f"Catalog refresh failed; previous snapshot retained: {result}")
            return
        self.samples, self.vocabulary = result
        groups = sorted(
            {tag.split("|")[0] for tag in self.vocabulary}
            | {tag.split("|")[0] for sample in self.samples for tag in sample.tags}
        )
        self.group_picker.configure(values=("All groups", *groups))
        if self.group.get() not in groups:
            self.group.set("All groups")
        types = sorted({sample.item_type for sample in self.samples})
        self.type_picker.configure(values=("All item types", *types))
        if self.item_type.get() not in types:
            self.item_type.set("All item types")
        self.apply()
        self.event_generate("<<LiveCatalogLoaded>>")

    def clear_tag(self):
        self.active_tags.clear()
        self.apply()

    def pick_tag(self, _event=None):
        selected = {self.tag_rows[index] for index in self.tags.curselection()}
        updated = (self.active_tags - set(self.tag_rows)) | selected
        if updated != self.active_tags:
            self.active_tags = updated
            self.apply()

    def apply(self):
        self._query_revision += 1
        self.page_index = 0
        groups = {}
        for tag in sorted(self.active_tags, key=str.casefold):
            root, _, label = tag.partition("|")
            groups.setdefault(root, []).append(label or root)
        summary = " AND ".join(f"{root}: ({' OR '.join(labels)})" for root, labels in groups.items())
        if len(summary) > 160:
            summary = summary[:157] + "..."
        self.selected_filters.set(
            f"{len(self.active_tags)} selected | {summary}" if self.active_tags else
            "Click to select; Ctrl/Cmd-click to toggle; Shift-click for a range. Same group: OR; groups: AND."
        )
        query = (
            self._query_revision, self.samples, self.search.get(),
            "" if self.group.get() == "All groups" else self.group.get(),
            self.source.get(), self.item_type.get(), tuple(sorted(self.active_tags))
        )
        self._pending_query = query
        self.matches = ()
        self.render_sounds()
        self.status.set("Filtering catalog; no files or tags are changed.")
        if self._query_results is None:
            self._start_query()

    def _start_query(self):
        query = self._pending_query
        self._pending_query = None
        revision, samples, search, group, source, item_type, tags = query
        def filter_items():
            return live_catalog.filter_catalog(
                samples, search, group, source=source, item_type=item_type, tags=tags
            )
        if len(samples) <= 500:
            try:
                matches, counts = filter_items()
            except ValueError as error:
                self.status.set(f"Catalog filtering failed: {error}")
            else:
                self._show_query(matches, counts)
            return
        self.status.set("Filtering catalog in the background; no files or tags are changed.")
        results = queue.Queue()
        self._query_results = results
        def worker():
            try:
                results.put(filter_items())
            except ValueError as error:
                results.put(error)
        threading.Thread(target=worker, daemon=True).start()
        self._schedule(30, lambda: self._finish_query(revision, results))

    def _finish_query(self, revision, results):
        try:
            result = results.get_nowait()
        except queue.Empty:
            self._schedule(30, lambda: self._finish_query(revision, results))
            return
        self._query_results = None
        if revision == self._query_revision:
            if isinstance(result, Exception):
                self.status.set(f"Catalog filtering failed: {result}")
            else:
                self._show_query(*result)
        if self._pending_query is not None:
            self._start_query()

    def _schedule(self, delay, callback):
        def finish():
            self._pending_callbacks.discard(identifier)
            callback()
        identifier = self.after(delay, finish)
        self._pending_callbacks.add(identifier)

    def _cancel_callbacks(self, event):
        if event.widget is self:
            for identifier in self._pending_callbacks:
                self.after_cancel(identifier)
            self._pending_callbacks.clear()

    def _show_query(self, matches, counts):
        self.matches = matches
        top_tag = self.tag_rows[self.tags.nearest(0)] if self.tag_rows else None
        anchor_index = self.tags.index("anchor")
        anchor_tag = self.tag_rows[anchor_index] if 0 <= anchor_index < len(self.tag_rows) else None
        active_index = self.tags.index("active")
        active_tag = self.tag_rows[active_index] if 0 <= active_index < len(self.tag_rows) else None
        self.tags.delete(0, "end")
        terms = self.search.get().casefold().split()
        vocabulary = {
            tag for tag in self.vocabulary
            if (self.group.get() == "All groups" or tag.split("|")[0] == self.group.get())
            and all(term in tag.casefold() for term in terms)
        }
        self.tag_rows = sorted(set(counts) | vocabulary, key=str.casefold)
        for tag in self.tag_rows:
            parts = tag.split("|")
            label = parts[0] if len(parts) == 1 else "  " * (len(parts) - 1) + " > ".join(parts[1:])
            self.tags.insert("end", f"{label}  ({counts.get(tag, 0):,})")
            if len(parts) == 1:
                self.tags.itemconfigure("end", foreground=gui_theme.THEME["accent_neon"], background=gui_theme.THEME["bg_panel"])
            if tag in self.active_tags:
                self.tags.selection_set(self.tags.size() - 1)
        if top_tag in self.tag_rows:
            self.tags.yview(self.tag_rows.index(top_tag))
        if anchor_tag in self.tag_rows:
            self.tags.selection_anchor(self.tag_rows.index(anchor_tag))
        if active_tag in self.tag_rows:
            self.tags.activate(self.tag_rows.index(active_tag))
        self.render_sounds()

    def next_page(self):
        if self._query_results is None and (self.page_index + 1) * self.page_size < len(self.matches):
            self.page_index += 1
            self.render_sounds()

    def previous_page(self):
        if self._query_results is None and self.page_index > 0:
            self.page_index -= 1
            self.render_sounds()

    def render_sounds(self):
        import os
        matches = self.matches
        pages = (len(matches) + self.page_size - 1) // self.page_size
        self.page_index = min(self.page_index, max(0, pages - 1))
        start = self.page_index * self.page_size
        end = min(start + self.page_size, len(matches))
        self.page_label.set(f"Page {self.page_index + 1 if pages else 0} of {pages}")
        self.previous_button.configure(state="normal" if self.page_index > 0 else "disabled")
        self.next_button.configure(state="normal" if end < len(matches) else "disabled")
        self.sounds.delete(*self.sounds.get_children())
        self.rows = {}
        for index, sample in enumerate(matches[start:end]):
            item = self.sounds.insert("", "end", values=(os.path.basename(sample.path), os.path.dirname(sample.path)),
                                      tags=("alternate",) if index % 2 else ())
            self.rows[item] = sample
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "Select an item to inspect its path, matched filters and tag sources.")
        self.details.configure(state="disabled")
        self.status.set(
            f"{len(matches):,} matching items; showing {start + 1 if matches else 0:,}-{end:,}. "
            "Catalog snapshot only; disk availability is not checked."
        )

    def show_details(self, _event=None):
        selected = self.sounds.selection()
        if not selected or selected[0] not in self.rows:
            return
        sample = self.rows[selected[0]]
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("end", sample.path + "\n", "path")
        self.details.insert("end", f"Item type: {sample.item_type}  |  Read only\n")
        selected = sorted(
            tag for tag in self.active_tags
            if live_catalog.filter_catalog((sample,), tag=tag, source=self.source.get())[0]
        )
        if self.active_tags:
            self.details.insert("end", "Matched filters: ", "heading")
            self.details.insert("end", (", ".join(selected) or "none in this item's current tags") + "\n", "matched")
            self.details.insert("end", "Alternatives in the same group use OR; an item need not match every alternative.\n")
        for label, tags in (
            ("User Library sidecars (fresh read; not catalog non-auto)", sample.manual),
            ("Non-auto (catalog; may be factory-provided)", sample.non_auto), ("Automatic", sample.automatic),
            ("Factory / catalog metadata", sample.factory),
            ("Raw metadata (hierarchies and device fields)", sample.metadata_details),
            ("Browser fields (Live labels; File extension is separate)", sample.fields)
        ):
            self.details.insert("end", "\n" + label + "\n", "heading")
            self.details.insert("end", "\n".join(tags) + "\n" if tags else "None\n")
        self.details.yview_moveto(0)
        self.details.configure(state="disabled")


class LiveCatalogPanel(_CatalogBrowser, ttk.Frame):
    """Protected Library source; never shares editable selections or write actions."""

    def __init__(self, parent):
        super().__init__(parent)
        self._build_catalog()


class LiveCatalogDialog(_CatalogBrowser, tk.Toplevel):
    def __init__(self, browser):
        super().__init__(browser)
        self.title("Ableton catalog - read only")
        self.configure(bg=gui_theme.THEME["bg_dark"])
        self.geometry("960x680")
        self.minsize(760, 560)
        self._build_catalog()
        ttk.Button(self, text="Close", command=self.destroy).pack(anchor="e", padx=12, pady=8)
        self.bind("<Escape>", lambda _event: self.destroy())

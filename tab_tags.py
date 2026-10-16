import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
from tab_matrix import messagebox, ask_confirm, ask_fields, show_notice

import gui_theme
import sorter_engine


SUPPORTED_AUDIO_EXTENSIONS = {
    ".wav", ".aif", ".aiff", ".mp3", ".flac", ".ogg", ".oga", ".m4a",
    ".aac", ".wma", ".opus", ".caf", ".au", ".snd", ".mid", ".midi"
}

MAX_WAVEFORM_BYTES = 60 * 1024 * 1024
NO_TAGS_LABEL = "None"


def _wav_peaks(path, buckets):
    """Returns [(low, high)] per bucket scaled to -1..1, or [] if the WAV can't be read."""
    import array
    import wave
    try:
        if os.path.getsize(path) > MAX_WAVEFORM_BYTES:
            return []
        with wave.open(path, "rb") as handle:
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            data = handle.readframes(handle.getnframes())
    except (OSError, EOFError, wave.Error):
        return []
    if width == 2:
        samples = array.array("h")
        samples.frombytes(data[: len(data) - len(data) % 2])
        scale = 32768.0
    elif width == 3:
        count = len(data) // 3
        high = bytearray(count * 2)
        high[0::2] = data[1:count * 3:3]
        high[1::2] = data[2:count * 3:3]
        samples = array.array("h")
        samples.frombytes(bytes(high))
        scale = 32768.0
    elif width == 1:
        samples = array.array("b", (b - 128 for b in data))
        scale = 128.0
    else:
        return []
    if sys.byteorder == "big" and width in (2, 3):
        samples.byteswap()
    samples = samples[::channels] if channels > 1 else samples
    total = len(samples)
    if total == 0:
        return []
    buckets = min(buckets, total)
    peaks = []
    for index in range(buckets):
        chunk = samples[index * total // buckets:(index + 1) * total // buckets]
        if not chunk:
            continue
        peaks.append((min(chunk) / scale, max(chunk) / scale))
    return peaks


class TagsTab(ttk.Frame):
    """Displays indexed assets and permits lightweight user tag maintenance."""

    def __init__(self, parent, status_label_ref=None):
        super().__init__(parent)
        self.status_label_ref = status_label_ref
        self.search_var = tk.StringVar()
        self.new_tag_var = tk.StringVar()
        self.favorites_only = False
        self.autoplay_var = tk.BooleanVar(value=False)
        self._waveform_generation = 0
        self.active_tag_filter = ""
        self._updating_browser_filters = False
        self._filter_refresh_after_id = None
        self._page_size = 250
        self._page_index = 0
        self.selected_asset_var = tk.StringVar(value="No sound selected")
        self.selected_tags_var = tk.StringVar(value="")
        self._asset_paths = {}
        self._audio_process = None
        self._audio_path = None
        self.bind("<Unmap>", lambda e: self.stop_sound() if e.widget is self else None)
        self._refresh_running = False
        self._active_collection = "All sounds"
        self._cached_tags = []
        self._cached_tag_scope = None
        self._rendered_tag_scope = None
        self._cached_total_count = 0
        self._collection_counts = {}
        self._static_counts = {}
        self._filtered_count = 0
        self._sidebar_loaded = False
        self._sidebar_loading = False
        self._sidebar_generation = 0
        self._tag_render_generation = 0
        self._tag_selection_generation = 0
        self._tag_render_after_id = None
        self._has_loaded = False
        self._build_ui()

    def ensure_loaded(self):
        """Loads the browser when the Sounds & Tags tab is first opened."""
        if not self._has_loaded:
            self._has_loaded = True
            self._render_results(load_sidebar=False)
            self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def _build_ui(self):
        theme = gui_theme.THEME
        header = tk.Frame(self, bg=theme["bg_dark"])
        header.pack(fill="x", padx=15, pady=(14, 4))
        tk.Label(
            header, text="Find Sounds & Edit Tags", font=("Segoe UI", 12, "bold"),
            bg=theme["bg_dark"], fg=theme["fg_light"]
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Search indexed sounds, then double-click a result to edit its tags.",
            font=("Segoe UI", 9), bg=theme["bg_dark"], fg=theme["fg_muted"],
            wraplength=900, justify="left"
        ).pack(anchor="w", pady=(2, 0))
        search_controls = tk.Frame(self, bg=theme["bg_dark"])
        search_controls.configure(
            bg=theme["bg_panel"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        search_controls.pack(fill="x", padx=15, pady=(12, 8), ipady=7)
        tk.Label(search_controls, text="Search:", bg=theme["bg_dark"], fg=theme["fg_light"]).pack(side="left")
        self.search_entry = tk.Entry(
            search_controls, textvariable=self.search_var, width=34,
            bg=theme["bg_panel"], fg=theme["fg_light"],
            relief="solid", bd=1,
            insertbackground=theme["fg_light"]
        )
        self.search_entry.pack(side="left", padx=6)
        self.search_entry.bind("<Return>", lambda _event: self._apply_filter())
        self.filter_button = tk.Button(
            search_controls, text="Apply filter", command=self._apply_filter,
            bg=theme["btn_primary"], fg=theme["btn_primary_fg"],
            activebackground=theme["btn_primary_hover"],
            activeforeground=theme["btn_primary_fg"], bd=1
        )
        self.filter_button.pack(side="left", padx=6)
        self.saved_button = tk.Button(
            search_controls, text="Saved searches ▾", command=self._show_saved_searches_menu,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"],
            activeforeground=theme["fg_light"], bd=1
        )
        self.saved_button.pack(side="left", padx=6)
        self.rescan_button = tk.Button(
            search_controls, text="Rescan library", command=self.rescan_library,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"],
            activeforeground=theme["fg_light"], bd=1
        )
        self.rescan_button.pack(side="left", padx=6)
        tk.Label(
            search_controls, text="Ctrl+F search  •  Space play/stop  •  F favorite",
            font=("Segoe UI", 8), bg=theme["bg_panel"], fg=theme["fg_muted"]
        ).pack(side="right", padx=8)

        tk.Label(
            self, text="Sounds",
            font=("Segoe UI", 10, "bold"),
            bg=theme["bg_dark"], fg=theme["fg_light"], anchor="w"
        ).pack(fill="x", padx=15, pady=(0, 5))
        page_controls = tk.Frame(self, bg=theme["bg_dark"])
        page_controls.pack(fill="x", padx=15, pady=(0, 5), ipady=2)
        self.page_label = tk.Label(
            page_controls, text="", bg=theme["bg_dark"], fg=theme["fg_muted"]
        )
        self.page_label.pack(side="left")
        self.total_label = tk.Label(
            page_controls, text="", bg=theme["bg_dark"], fg=theme["fg_muted"]
        )
        self.total_label.pack(side="left", padx=(12, 0))
        self.previous_page_button = tk.Button(
            page_controls, text="Previous", command=self._previous_page,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"], bd=1, state="disabled"
        )
        self.previous_page_button.pack(side="right", padx=(4, 0))
        self.next_page_button = tk.Button(
            page_controls, text="Next", command=self._next_page,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"], bd=1, state="disabled"
        )
        self.next_page_button.pack(side="right")
        browser = tk.Frame(
            self, bg=theme["bg_dark"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        browser.pack(fill="both", expand=True, padx=15, pady=(0, 8))
        sidebar = tk.Frame(
            browser, bg=theme["bg_field"], width=270, bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        sidebar.pack(side="left", fill="y", padx=(0, 8))
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar, text="Collections", bg=theme["bg_field"], fg=theme["fg_muted"],
            font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(fill="x", padx=10, pady=(10, 4))
        self.collection_list = tk.Listbox(
            sidebar, height=8, bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground="white",
            relief="flat", highlightthickness=0, activestyle="none",
            exportselection=False
        )
        self.collection_list.pack(fill="x", padx=5)
        self.collection_list.bind("<<ListboxSelect>>", self._collection_selected)
        tk.Label(
            sidebar, text="Tags", bg=theme["bg_field"], fg=theme["fg_muted"],
            font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(fill="x", padx=10, pady=(12, 4))
        tag_list_frame = tk.Frame(sidebar, bg=theme["bg_field"])
        tag_list_frame.pack(fill="both", expand=True, padx=5, pady=(0, 8))
        tag_scrollbar = ttk.Scrollbar(tag_list_frame, orient="vertical")
        tag_scrollbar.pack(side="right", fill="y")
        self.tag_list = tk.Listbox(
            tag_list_frame, bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground="white",
            relief="flat", highlightthickness=0, activestyle="none", exportselection=False,
            yscrollcommand=tag_scrollbar.set
        )
        self.tag_list.pack(in_=tag_list_frame, side="left", fill="both", expand=True)
        tag_scrollbar.configure(command=self.tag_list.yview)
        self.tag_list.bind("<Button-1>", self._stop_tag_batch_render, add="+")
        self.tag_list.bind("<ButtonRelease-1>", self._tag_released, add="+")
        wrapper = tk.Frame(
            browser, bg=theme["bg_field"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        wrapper.pack(side="left", fill="both", expand=True)
        vertical_scrollbar = ttk.Scrollbar(wrapper, orient="vertical")
        vertical_scrollbar.pack(side="right", fill="y")
        horizontal_scrollbar = ttk.Scrollbar(wrapper, orient="horizontal")
        horizontal_scrollbar.pack(side="bottom", fill="x")
        self.asset_tree = ttk.Treeview(
            wrapper,
            columns=("Filename", "Folder"),
            show="headings",
            selectmode="extended",
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set
        )
        self.asset_tree.pack(fill="both", expand=True)
        vertical_scrollbar.config(command=self.asset_tree.yview)
        horizontal_scrollbar.config(command=self.asset_tree.xview)
        for column, width in (("Filename", 420), ("Folder", 360)):
            self.asset_tree.heading(column, text=column)
            self.asset_tree.column(column, width=width, anchor="w")

        selected = tk.Frame(
            self, bg=theme["bg_field"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        selected.pack(fill="x", padx=15, pady=(0, 10), ipady=14)
        selected_header = tk.Frame(selected, bg=theme["bg_field"])
        selected_header.pack(fill="x", padx=10, pady=(7, 0))
        tk.Label(
            selected, textvariable=self.selected_asset_var,
            font=("Segoe UI", 12, "bold"), bg=theme["bg_field"], fg=theme["accent_neon"]
        ).pack(in_=selected_header, side="left")
        self.favorite_button = tk.Button(
            selected_header, text="☆ Favorite", command=self.toggle_selected_favorite,
            bg=theme["tag_enabled"], fg="white",
            activebackground=theme["tag_enabled"], activeforeground="white",
            bd=1, padx=8
        )
        self.favorite_button.pack(side="right", padx=(0, 6))
        self.autoplay_check = tk.Checkbutton(
            selected_header, text="Auto-play on select", variable=self.autoplay_var,
            bg=theme["bg_field"], fg=theme["fg_light"], selectcolor=theme["bg_dark"],
            activebackground=theme["bg_field"], activeforeground=theme["fg_light"],
            disabledforeground=theme["fg_muted"]
        )
        self.autoplay_check.pack(side="right", padx=(0, 10))
        tk.Button(
            selected_header, text="Play sound", command=self.play_selected_sound,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"],
            activeforeground=theme["fg_light"],
            bd=1, padx=8
        ).pack(side="right")
        tk.Button(
            selected_header, text="Stop", command=self.stop_sound,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"], bd=1, padx=8
        ).pack(side="right", padx=(0, 6))
        tk.Label(
            selected,
            textvariable=self.selected_tags_var,
            font=("Segoe UI", 9), bg=theme["bg_field"], fg=theme["fg_muted"],
            justify="left", wraplength=900
        ).pack(anchor="w", padx=10, pady=(2, 7))
        self.waveform_canvas = tk.Canvas(
            selected, height=50, bg=theme["bg_dark"], highlightthickness=1,
            highlightbackground=theme["border"]
        )
        self.waveform_canvas.pack(fill="x", padx=10, pady=(0, 6))
        self.asset_tree.bind("<<TreeviewSelect>>", lambda _event: self._show_selected_asset())
        self.asset_tree.bind("<Double-1>", lambda _event: self._open_asset_details())
        self.asset_tree.bind("<space>", self._shortcut_play_toggle)
        self.asset_tree.bind("<KeyPress-f>", self._shortcut_favorite)
        self.bind_all("<Control-f>", self._shortcut_focus_search, add="+")

    def _tab_is_visible(self):
        try:
            return self.winfo_viewable()
        except tk.TclError:
            return False

    def _shortcut_focus_search(self, _event):
        if not self._tab_is_visible():
            return None
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")
        return "break"

    def _shortcut_play_toggle(self, _event):
        if self._audio_process is not None and self._audio_process.poll() is None:
            self.stop_sound()
        else:
            self.play_selected_sound()
        return "break"

    def _shortcut_favorite(self, _event):
        if self._selected_path():
            self.toggle_selected_favorite()
        return "break"

    def _saved_searches_file(self):
        return os.path.join(
            os.path.dirname(os.path.abspath(sorter_engine.CONFIG_FILE)), "saved_searches.json"
        )

    def _load_saved_searches(self):
        try:
            with open(self._saved_searches_file(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return [item for item in data if isinstance(item, dict) and item.get("name")]
        except (OSError, ValueError):
            return []

    def _write_saved_searches(self, items):
        try:
            with open(self._saved_searches_file(), "w", encoding="utf-8") as handle:
                json.dump(items, handle, indent=2)
        except OSError:
            show_notice(self.winfo_toplevel(), "Saved searches", "Could not save the list.", heading="Not saved")

    def _show_saved_searches_menu(self):
        theme = gui_theme.THEME
        menu = tk.Menu(
            self, tearoff=0, bg=theme["bg_panel"], fg=theme["fg_light"],
            activebackground=theme["btn_primary"], activeforeground=theme["btn_primary_fg"]
        )
        menu.add_command(label="Save current search…", command=self._save_current_search)
        items = self._load_saved_searches()
        if items:
            menu.add_separator()
            for item in items:
                menu.add_command(label=item["name"], command=lambda i=item: self._apply_saved_search(i))
            menu.add_separator()
            delete_menu = tk.Menu(
                menu, tearoff=0, bg=theme["bg_panel"], fg=theme["fg_light"],
                activebackground=theme["btn_primary"], activeforeground=theme["btn_primary_fg"]
            )
            for item in items:
                delete_menu.add_command(label=item["name"], command=lambda i=item: self._delete_saved_search(i))
            menu.add_cascade(label="Delete a saved search", menu=delete_menu)
        x = self.saved_button.winfo_rootx()
        y = self.saved_button.winfo_rooty() + self.saved_button.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _describe_search(self, item):
        parts = []
        if item.get("collection") and item["collection"] != "All sounds":
            parts.append(item["collection"])
        if item.get("tag"):
            parts.append(f"tag '{item['tag']}'")
        if item.get("text"):
            parts.append(f"text '{item['text']}'")
        return ", ".join(parts) or "everything"

    def _save_current_search(self):
        item = {
            "text": self.search_var.get().strip(),
            "collection": self._active_collection,
            "tag": self.active_tag_filter,
        }
        if not item["text"] and not item["tag"] and item["collection"] == "All sounds":
            show_notice(
                self.winfo_toplevel(), "Saved searches",
                "Type a search or pick a category or tag first, then save it.",
                heading="Nothing to save"
            )
            return
        result = ask_fields(
            self.winfo_toplevel(), "Save search",
            f"This will remember: {self._describe_search(item)}.", ["Name"]
        )
        if not result or not result[0].strip():
            return
        item["name"] = result[0].strip()
        items = [i for i in self._load_saved_searches() if i["name"].lower() != item["name"].lower()]
        items.append(item)
        self._write_saved_searches(items)

    def _apply_saved_search(self, item):
        self.search_var.set(item.get("text", ""))
        self._active_collection = item.get("collection") or "All sounds"
        self.favorites_only = self._active_collection == "Favorites"
        self.active_tag_filter = item.get("tag", "")
        self._page_index = 0
        self._set_collection_selection()
        self._tag_selection_generation = 0
        self._safe_render_results()
        self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def _delete_saved_search(self, item):
        if not ask_confirm(
            self.winfo_toplevel(), "Delete saved search",
            f"Delete '{item['name']}'? Your sounds and tags are not affected.", "Delete"
        ):
            return
        self._write_saved_searches([i for i in self._load_saved_searches() if i["name"] != item["name"]])

    def refresh(self):
        self._cached_tags = []
        self._cached_tag_scope = None
        self._rendered_tag_scope = None
        self._sidebar_loaded = False
        self._render_results(load_sidebar=False)
        self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def rescan_library(self):
        if self._refresh_running:
            return
        library_root = gui_theme.USER_LIBRARY_PATH
        if not library_root or not os.path.isdir(library_root):
            return
        self._refresh_running = True
        self.rescan_button.configure(state="disabled")
        self._set_status("Scanning the library for sounds...")
        threading.Thread(
            target=self._discover_then_refresh, args=(library_root,), daemon=True
        ).start()

    def _discover_then_refresh(self, library_root):
        try:
            discovered = sorter_engine.index_existing_library(library_root)
        except (
            OSError, ValueError, KeyError, TypeError, sorter_engine.sqlite3.Error
        ) as error:
            self.after(0, lambda: self._finish_refresh(0, error))
            return
        self.after(0, lambda: self._finish_refresh(discovered, None))

    def _request_sidebar_load(self, library_root):
        self._sidebar_generation += 1
        generation = self._sidebar_generation
        active_collection = self._active_collection
        favorites_only = self.favorites_only
        search_text = self.search_var.get()
        collection_query = {
            "Loops": "type:loop", "One-shots": "type:one-shot",
            "MIDI": "type:midi"
        }.get(active_collection, "")
        scoped_search = f"{search_text} {collection_query}".strip()
        if self._sidebar_loading:
            return
        self._sidebar_loading = True
        threading.Thread(
            target=self._load_sidebar_then_apply,
            args=(
                library_root, active_collection, favorites_only,
                scoped_search, generation
            ),
            daemon=True
        ).start()

    def _load_sidebar_then_apply(
        self, library_root, active_collection, favorites_only,
        search_text, generation
    ):
        try:
            sidebar_data = self._load_sidebar_data(
                library_root, active_collection, favorites_only, search_text
            )
        except (
            OSError, ValueError, KeyError, TypeError, tk.TclError,
            sorter_engine.sqlite3.Error
        ) as error:
            self.after(
                0, lambda: self._finish_sidebar_load(None, error, generation)
            )
            return
        self.after(
            0, lambda: self._finish_sidebar_load(sidebar_data, None, generation)
        )

    def _finish_sidebar_load(self, sidebar_data, error, generation):
        self._sidebar_loading = False
        if generation != self._sidebar_generation:
            self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)
            return
        if error:
            self._set_status(f"Tag counts unavailable: {error}")
            return
        current_scope = (
            {"Loops": "type:loop", "One-shots": "type:one-shot",
             "MIDI": "type:midi"}.get(self._active_collection, ""),
            self.favorites_only,
            (
                f"{self.search_var.get()} "
                f"{ {'Loops': 'type:loop', 'One-shots': 'type:one-shot', 'MIDI': 'type:midi'}.get(self._active_collection, '')}"
            ).strip(),
        )
        if sidebar_data["tag_scope"] != current_scope:
            self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)
            return
        self._cached_total_count = sidebar_data["total_count"]
        self._collection_counts = sidebar_data["collection_counts"]
        self._cached_tags = sidebar_data["tags"]
        self._cached_tag_scope = sidebar_data["tag_scope"]
        self._sidebar_loaded = True
        self._sidebar_loading = False
        self._safe_render_results()

    def _load_sidebar_data(
        self, library_root, active_collection, favorites_only, search_text=""
    ):
        """Loads only the bounded sidebar data needed by the browser."""
        collection_queries = {
            "Loops": "type:loop",
            "One-shots": "type:one-shot",
            "MIDI": "type:midi",
        }
        tag_scope = (
            collection_queries.get(active_collection, ""),
            favorites_only,
            search_text,
        )
        cache = self.__dict__.setdefault("_static_counts", {})
        static_counts = cache.get(library_root)
        default_scope = tag_scope == ("", False, "")
        fingerprint = sorter_engine._index_fingerprint()
        if default_scope and static_counts is None:
            snapshot = sorter_engine.load_sidebar_snapshot(library_root)
            if snapshot is not None:
                cache[library_root] = snapshot["static_counts"]
                return {
                    "total_count": snapshot["static_counts"]["All sounds"],
                    "collection_counts": {
                        **snapshot["static_counts"], "Favorites": snapshot["favorites"]
                    },
                    "tags": snapshot["tags"],
                    "tag_scope": tag_scope,
                }
        if static_counts is None:
            static_counts = {
                "All sounds": sorter_engine.count_indexed_assets(library_root),
                "Loops": sorter_engine.count_indexed_assets(
                    library_root, search_text="type:loop"
                ),
                "One-shots": sorter_engine.count_indexed_assets(
                    library_root, search_text="type:one-shot"
                ),
                "MIDI": sorter_engine.count_indexed_assets(
                    library_root, search_text="type:midi"
                ),
            }
            cache[library_root] = static_counts
        favorites_count = sorter_engine.count_indexed_assets(
            library_root, favorites_only=True
        )
        tags = sorter_engine.list_indexed_tags(
            library_root,
            search_text=search_text,
            favorites_only=tag_scope[1]
        )
        if default_scope:
            sorter_engine.save_sidebar_snapshot(
                library_root, static_counts, favorites_count, tags, fingerprint
            )
        return {
            "total_count": static_counts["All sounds"],
            "collection_counts": {**static_counts, "Favorites": favorites_count},
            "tags": tags,
            "tag_scope": tag_scope,
        }

    def _finish_refresh(self, discovered, error, sidebar_data=None):
        self._refresh_running = False
        self.rescan_button.configure(state="normal")
        self.__dict__.setdefault("_static_counts", {}).clear()
        self.filter_button.configure(state="normal")
        if error:
            self._set_status(f"Refresh failed: {error}")
            messagebox.showerror("Refresh Failed", str(error))
            return
        self._set_status(
            f"Refresh complete. Found {discovered:,} sounds in the User Library."
        )
        if sidebar_data is not None:
            self._cached_total_count = sidebar_data["total_count"]
            self._collection_counts = sidebar_data["collection_counts"]
            self._cached_tags = sidebar_data["tags"]
            self._cached_tag_scope = sidebar_data["tag_scope"]
            self._sidebar_loaded = True
        self._render_results()

    def _render_results(self, refresh_sidebar=False, load_sidebar=True):
        selected_path = None
        selection = self.asset_tree.selection()
        if selection and selection[0] in self._asset_paths:
            selected_path = self._asset_paths[selection[0]]
        library_root = gui_theme.USER_LIBRARY_PATH
        collection_queries = {
            "Loops": "type:loop",
            "One-shots": "type:one-shot",
            "MIDI": "type:midi",
        }
        tag_scope = (
            collection_queries.get(self._active_collection, ""),
            self.favorites_only,
            (
                f"{self.search_var.get()} "
                f"{collection_queries.get(self._active_collection, '')}"
            ).strip(),
        )
        if refresh_sidebar:
            self.__dict__.setdefault("_static_counts", {}).clear()
        if load_sidebar and (
            refresh_sidebar or not self._sidebar_loaded
            or self._cached_tag_scope != tag_scope
        ):
            self._request_sidebar_load(library_root)
        if getattr(self, "_rendered_tag_scope", None) != self._cached_tag_scope:
            self._updating_browser_filters = True
            try:
                self._refresh_collections(
                    self._cached_tags, self._collection_counts
                )
                self._rendered_tag_scope = self._cached_tag_scope
            finally:
                self._updating_browser_filters = False
        else:
            self._set_collection_selection()
        collection_queries = {
            "Loops": "type:loop",
            "One-shots": "type:one-shot",
            "MIDI": "type:midi",
        }
        search_text = self.search_var.get()
        if self._active_collection in collection_queries:
            search_text = (
                f"{search_text} {collection_queries[self._active_collection]}"
            ).strip()
        records = sorter_engine.list_indexed_assets(
            search_text, self.active_tag_filter, self.favorites_only,
            limit=self._page_size + 1, offset=self._page_index * self._page_size,
            library_root=library_root
        )
        has_next_page = len(records) > self._page_size
        records = records[:self._page_size]
        self.page_label.configure(
            text=f"Showing {self._page_index * self._page_size + 1}-"
            f"{self._page_index * self._page_size + len(records)}"
            if records else "No sounds on this page"
        )
        self._filtered_count = self._page_index * self._page_size + len(records)
        if has_next_page:
            try:
                self._filtered_count = sorter_engine.count_indexed_assets(
                    library_root, search_text, self.active_tag_filter,
                    self.favorites_only
                )
            except (OSError, sorter_engine.sqlite3.Error):
                pass
        total_text = (
            f"Showing {self._filtered_count:,} results"
            if not self._sidebar_loaded else
            f"Showing {self._filtered_count:,} results "
            f"(library total: {self._cached_total_count:,})"
        )
        self.total_label.configure(text=total_text)
        self.previous_page_button.configure(
            state="normal" if self._page_index else "disabled"
        )
        self.next_page_button.configure(
            state="normal" if has_next_page else "disabled"
        )
        self.asset_tree.delete(*self.asset_tree.get_children())
        self._asset_paths.clear()
        selected_item = None
        for record in records:
            folder = os.path.relpath(record["destination"], library_root)
            if folder == ".":
                folder = "User Library"
            item_id = self.asset_tree.insert(
                "", "end",
                values=(
                    record["filename"], folder
                )
            )
            self._asset_paths[item_id] = record["path"]
            if record["path"] == selected_path:
                selected_item = item_id
        if not records:
            self.asset_tree.insert(
                "", "end",
                values=("No matching sounds", "Try another filter")
            )
        elif selected_item:
            self.asset_tree.selection_set(selected_item)
            self.asset_tree.focus(selected_item)
        self._show_selected_asset()

    def _previous_page(self):
        if self._page_index:
            self._page_index -= 1
            self._render_results()

    def _next_page(self):
        if not self.next_page_button["state"] == "disabled":
            self._page_index += 1
            self._render_results()

    def _apply_filter(self):
        self._page_index = 0
        self._render_results()

    def _refresh_collections(self, tags, collection_counts=None):
        collection_counts = collection_counts or {}
        self.collection_list.delete(0, "end")
        for collection in (
            "All sounds", "Favorites", "Loops", "One-shots", "MIDI"
        ):
            count = collection_counts.get(collection)
            label = f"{collection}  ({count:,})" if count is not None else collection
            self.collection_list.insert("end", label)
        self._set_collection_selection()
        if self._tag_render_after_id is not None:
            self.after_cancel(self._tag_render_after_id)
            self._tag_render_after_id = None
        self.tag_list.delete(0, "end")
        self._tag_render_generation += 1
        if not tags:
            self.tag_list.insert("end", NO_TAGS_LABEL)
            return
        self._insert_tag_batch(tags, 0, self._tag_render_generation)

    def _insert_tag_batch(self, tags, start, generation):
        if generation != self._tag_render_generation:
            return
        batch_end = min(start + 250, len(tags))
        for tag, count in tags[start:batch_end]:
            self.tag_list.insert("end", f"{tag}  ({count})")
        if batch_end < len(tags):
            self._tag_render_after_id = self.after(
                1, lambda: self._insert_tag_batch(
                    tags, batch_end, generation
                )
            )
            return
        self._tag_render_after_id = None
        if self.active_tag_filter and (
            self._tag_selection_generation != generation
            and not self.tag_list.curselection()
        ):
            for index, (tag, _count) in enumerate(tags):
                if tag.lower() == self.active_tag_filter.lower():
                    self.tag_list.selection_set(index)
                    self.tag_list.see(index)
                    break

    def _stop_tag_batch_render(self, _event):
        self._tag_render_generation += 1
        if self._tag_render_after_id is not None:
            self.after_cancel(self._tag_render_after_id)
            self._tag_render_after_id = None

    def _tag_released(self, event):
        index = self.tag_list.nearest(event.y)
        if index < 0 or index >= self.tag_list.size():
            return
        if self.tag_list.get(index) == NO_TAGS_LABEL:
            self.tag_list.selection_clear(0, "end")
            return
        self._updating_browser_filters = True
        try:
            self.tag_list.selection_clear(0, "end")
            self.tag_list.selection_set(index)
        finally:
            self._updating_browser_filters = False
        value = self.tag_list.get(index)
        self._apply_tag_filter(value)

    def _set_collection_selection(self):
        was_updating = self._updating_browser_filters
        self._updating_browser_filters = True
        try:
            self.collection_list.selection_clear(0, "end")
            collection_index = {
                "All sounds": 0, "Favorites": 1, "Loops": 2,
                "One-shots": 3, "MIDI": 4
            }
            if self._active_collection in collection_index:
                self.collection_list.selection_set(
                    collection_index[self._active_collection]
                )
        finally:
            self._updating_browser_filters = was_updating

    def _collection_selected(self, _event):
        if self._updating_browser_filters:
            return
        selection = self.collection_list.curselection()
        if not selection:
            return
        collections = (
            "All sounds", "Favorites", "Loops", "One-shots", "MIDI"
        )
        self.stop_sound()
        self._active_collection = collections[selection[0]]
        self.active_tag_filter = ""
        self.favorites_only = self._active_collection == "Favorites"
        self._page_index = 0
        self._updating_browser_filters = True
        try:
            self.tag_list.selection_clear(0, "end")
        finally:
            self._updating_browser_filters = False
        self._safe_render_results()
        self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def _tag_selected(self, _event):
        if self._updating_browser_filters:
            return
        selection = self.tag_list.curselection()
        if not selection:
            return
        if self.tag_list.get(selection[0]) == NO_TAGS_LABEL:
            return
        self._apply_tag_filter(self.tag_list.get(selection[0]))

    def _apply_tag_filter(self, value):
        self.stop_sound()
        self.active_tag_filter = value.rsplit("  (", 1)[0]
        self.favorites_only = self._active_collection == "Favorites"
        self._page_index = 0
        self._tag_selection_generation = getattr(
            self, "_tag_render_generation", 0
        )
        self._safe_render_results()

    def _safe_render_results(self):
        try:
            self._render_results(load_sidebar=False)
        except (
            OSError, ValueError, KeyError, TypeError, tk.TclError,
            sorter_engine.sqlite3.Error
        ) as error:
            self._set_status(f"Browser update failed: {error}")
            messagebox.showerror("Sounds & Tags", str(error))

    def _schedule_filter_refresh(self):
        if self._filter_refresh_after_id is not None:
            self.after_cancel(self._filter_refresh_after_id)
        self._filter_refresh_after_id = self.after(50, self._run_filter_refresh)

    def _run_filter_refresh(self):
        self._filter_refresh_after_id = None
        self.stop_sound()
        try:
            self._render_results()
        except (
            OSError, ValueError, KeyError, TypeError, tk.TclError,
            sorter_engine.sqlite3.Error
        ) as error:
            self._set_status(f"Filter failed: {error}")
            messagebox.showerror("Sounds & Tags", str(error))

    def _set_status(self, text):
        if self.status_label_ref:
            self.status_label_ref.config(
                text=f" Application Status: {text}",
                fg=gui_theme.THEME["accent_gold"]
            )

    def _show_selected_asset(self):
        selection = self.asset_tree.selection()
        if not selection or selection[0] not in self._asset_paths:
            self.selected_asset_var.set("No sound selected")
            self.selected_tags_var.set(
                "No matching sound is selected. Use Import or Organize to index new files."
            )
            self.favorite_button.configure(text="☆ Favorite")
            return
        path = self._asset_paths[selection[0]]
        record = sorter_engine.get_indexed_asset(path)
        if record is None:
            self.selected_asset_var.set("No sound selected")
            self.selected_tags_var.set("The selected sound is no longer indexed.")
            self.favorite_button.configure(text="☆ Favorite")
            return
        self.selected_asset_var.set(record["filename"])
        self.selected_tags_var.set(
            "Tags: " + (", ".join(record["tags"]) if record["tags"] else "No tags yet")
            + f"\nLocation: {record['path']}"
        )
        self.favorite_button.configure(
            text="★ Favorite" if "favorite" in record["tags"] else "☆ Favorite"
        )
        self._draw_waveform(path)
        is_midi = os.path.splitext(path)[1].lower() in (".mid", ".midi")
        self.autoplay_check.configure(state="disabled" if is_midi else "normal")
        if self.autoplay_var.get() and len(selection) == 1 and not is_midi:
            try:
                self._play_sound(path)
            except (OSError, ValueError):
                pass

    def _draw_waveform(self, path):
        canvas = self.waveform_canvas
        canvas.delete("all")
        self._waveform_generation += 1
        generation = self._waveform_generation
        if os.path.splitext(path)[1].lower() != ".wav":
            canvas.create_text(8, 25, anchor="w", fill=gui_theme.THEME["fg_muted"],
                               text="Waveform preview is available for WAV files.")
            return
        canvas.create_text(8, 25, anchor="w", fill=gui_theme.THEME["fg_muted"], text="Reading waveform…")
        buckets = max(100, canvas.winfo_width() or 600)

        def worker():
            peaks = _wav_peaks(path, buckets)
            try:
                self.after(0, lambda: self._finish_waveform(generation, peaks))
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _finish_waveform(self, generation, peaks):
        if generation != self._waveform_generation:
            return
        canvas = self.waveform_canvas
        canvas.delete("all")
        height = int(canvas["height"])
        mid = height / 2
        if not peaks:
            canvas.create_text(8, mid, anchor="w", fill=gui_theme.THEME["fg_muted"],
                               text="Waveform not available for this file.")
            return
        canvas.create_line(0, mid, len(peaks), mid, fill=gui_theme.THEME["border"])
        for x, (low, high) in enumerate(peaks):
            canvas.create_line(
                x, mid - high * (mid - 2), x, mid - low * (mid - 2) + 1,
                fill=gui_theme.THEME["accent_neon"]
            )

    def toggle_selected_favorite(self):
        try:
            path = self._selected_path()
            record = sorter_engine.get_indexed_asset(path)
            if "favorite" in record["tags"]:
                sorter_engine.remove_asset_tag(path, "favorite")
            else:
                sorter_engine.add_asset_tag(path, "favorite")
            self._render_results(refresh_sidebar=True)
            if self.status_label_ref:
                self.status_label_ref.config(
                    text=" Application Status: Favorite updated.",
                    fg=gui_theme.THEME["accent_neon"]
                )
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Favorite Update Failed", str(error))

    def _selected_path(self):
        selection = self.asset_tree.selection()
        if not selection:
            raise ValueError("Select an indexed asset first.")
        if selection[0] not in self._asset_paths:
            raise ValueError("Select an indexed sound first.")
        return self._asset_paths[selection[0]]

    def _selected_paths(self):
        paths = [
            self._asset_paths[item_id]
            for item_id in self.asset_tree.selection()
            if item_id in self._asset_paths
        ]
        if not paths:
            raise ValueError("Select at least one indexed sound.")
        return paths

    def bulk_add_tag(self):
        try:
            paths = self._selected_paths()
            tag = self.new_tag_var.get().strip()
            sorter_engine.bulk_update_asset_tags(paths, tag)
            self.new_tag_var.set("")
            self._render_results(refresh_sidebar=True)
            if self.status_label_ref:
                self.status_label_ref.config(
                    text=f" Application Status: Tag applied to {len(paths)} sounds.",
                    fg=gui_theme.THEME["accent_neon"]
                )
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Bulk Tag Update Failed", str(error))

    def play_selected_sound(self):
        try:
            self._play_sound(self._selected_path())
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Play Sound", str(error))

    def _play_sound(self, path):
        if not os.path.isfile(path):
            raise OSError("The sound file could not be found.")
        extension = os.path.splitext(path)[1].lower()
        if extension not in SUPPORTED_AUDIO_EXTENSIONS:
            raise OSError(
                f"{extension or 'This file type'} is not an audio file that can be previewed."
            )
        try:
            self.stop_sound()
            if platform.system() == "Windows":
                if extension == ".wav":
                    import winsound
                    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                else:
                    self._launch_broad_format_player(path)
            elif platform.system() == "Darwin":
                player = shutil.which("afplay")
                if player:
                    self._audio_process = subprocess.Popen([player, path])
                else:
                    self._launch_broad_format_player(path)
            else:
                player = shutil.which("paplay") or shutil.which("aplay")
                if player:
                    self._audio_process = subprocess.Popen([player, path])
                else:
                    self._launch_broad_format_player(path)
            self._audio_path = path
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            raise OSError(f"Could not play the sound: {error}") from error

    def _launch_broad_format_player(self, path):
        """Use a broad decoder when installed, otherwise the OS file association."""
        vlc = shutil.which("vlc") or shutil.which("vlc.exe")
        ffplay = shutil.which("ffplay") or shutil.which("ffplay.exe")
        mpv = shutil.which("mpv") or shutil.which("mpv.exe")
        if vlc:
            self._audio_process = subprocess.Popen(
                [vlc, "--intf", "dummy", "--play-and-exit", "--no-video", path]
            )
        elif ffplay:
            self._audio_process = subprocess.Popen(
                [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        elif mpv:
            self._audio_process = subprocess.Popen(
                [mpv, "--no-video", "--really-quiet", "--keep-open=no", path]
            )
        else:
            self._open_with_default_player(path)

    def _open_with_default_player(self, path):
        """Open the file with the OS association without blocking the UI thread."""
        def launch():
            try:
                if platform.system() == "Windows":
                    os.startfile(path)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", path])
                else:
                    opener = shutil.which("xdg-open")
                    if opener:
                        subprocess.Popen([opener, path])
            except OSError:
                pass

        if platform.system() not in ("Windows", "Darwin") and not shutil.which("xdg-open"):
            raise OSError("No compatible audio player was found. Install a player or xdg-open.")
        threading.Thread(target=launch, daemon=True).start()

    def stop_sound(self):
        if platform.system() == "Windows":
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except (ImportError, RuntimeError):
                pass
        if getattr(self, "_audio_process", None) is not None:
            try:
                if self._audio_process.poll() is None:
                    self._audio_process.terminate()
            except (OSError, subprocess.SubprocessError):
                pass
            self._audio_process = None
        self._audio_path = None

    def _open_asset_details(self):
        try:
            path = self._selected_path()
            record = sorter_engine.get_indexed_asset(path)
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Sound Details", str(error))
            return

        theme = gui_theme.THEME
        dialog = tk.Toplevel(self)
        self._details_dialog = dialog
        self._details_path = path
        dialog.protocol("WM_DELETE_WINDOW", lambda: self._close_details_dialog(dialog))
        dialog.title("Sound details")
        dialog.geometry("620x360")
        dialog.minsize(520, 300)
        dialog.configure(bg=theme["bg_dark"])
        self._place_dialog(dialog, 620, 360)
        tk.Label(
            dialog, text=record["filename"], font=("Segoe UI", 13, "bold"),
            bg=theme["bg_dark"], fg=theme["accent_neon"], anchor="w"
        ).pack(fill="x", padx=18, pady=(16, 8))
        details = f"Location: {record['path']}"
        tk.Label(
            dialog, text=details, font=("Segoe UI", 9), bg=theme["bg_field"],
            fg=theme["fg_muted"], justify="left", anchor="nw", wraplength=570
        ).pack(fill="both", expand=True, padx=18, pady=8)

        tk.Label(
            dialog, text="Tags — click a button to enable or disable it for this sound:",
            font=("Segoe UI", 9, "bold"), bg=theme["bg_dark"],
            fg=theme["fg_light"], anchor="w"
        ).pack(fill="x", padx=18, pady=(2, 4))
        tag_buttons = tk.Frame(dialog, bg=theme["bg_dark"])
        tag_buttons.pack(fill="x", padx=18, pady=(0, 10))
        all_tags = sorted(
            tag for tag in set(record["tags"]) | set(record.get("disabled_tags", []))
            if not tag.startswith("category:")
        )
        tag_states = {tag: tag in record["tags"] for tag in all_tags}
        tag_button_refs = {}
        tag_columns = 3
        for column in range(tag_columns):
            tag_buttons.grid_columnconfigure(column, weight=1)
        for index, tag in enumerate(all_tags):
            enabled = tag_states[tag]
            tag_button = tk.Button(
                tag_buttons, text=tag, font=("Segoe UI", 8),
                bg=theme["tag_enabled"] if enabled else theme["tag_disabled"],
                fg="white" if enabled else theme["fg_muted"],
                activebackground=theme["tag_enabled"] if enabled else theme["tag_disabled"],
                activeforeground="white" if enabled else theme["fg_light"],
                bd=0, padx=8, pady=3,
                command=lambda selected_tag=tag: self._toggle_asset_tag(
                    path, selected_tag, tag_states, tag_button_refs[selected_tag]
                )
            )
            tag_button.grid(
                row=index // tag_columns, column=index % tag_columns,
                sticky="w", padx=(0, 8), pady=2
            )
            tag_button_refs[tag] = tag_button
        if not all_tags:
            tk.Label(
                tag_buttons, text="No tags yet", font=("Segoe UI", 8, "italic"),
                bg=theme["bg_dark"], fg=theme["fg_muted"]
            ).pack(anchor="w")

        tag_row = tk.Frame(dialog, bg=theme["bg_dark"])
        tag_row.pack(fill="x", padx=18, pady=(0, 16))
        tk.Label(tag_row, text="Personal tag:", bg=theme["bg_dark"], fg=theme["fg_light"]).pack(side="left")
        entry = tk.Entry(tag_row, textvariable=self.new_tag_var, width=24, bg=theme["bg_field"], fg=theme["fg_light"], insertbackground=theme["fg_light"])
        entry.pack(side="left", padx=6)
        tk.Button(
            tag_row, text="Add tag", command=self.add_tag,
            bg=theme["btn_primary"], fg=theme["btn_primary_fg"],
            activebackground=theme["btn_primary_hover"],
            activeforeground=theme["btn_primary_fg"], bd=0
        ).pack(side="left", padx=4)
        tk.Button(
            tag_row, text="Remove tag", command=self.remove_tag,
            bg=theme["btn_danger"], fg="white",
            activebackground=theme["btn_danger_hover"],
            activeforeground="white", bd=1
        ).pack(side="left", padx=4)
        entry.focus_set()

    def _place_dialog(self, dialog, width, height):
        """Centers a child window over the main app and keeps it on-screen."""
        parent = self.winfo_toplevel()
        parent.update_idletasks()
        dialog.update_idletasks()
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        x = parent_x + max((parent_width - width) // 2, 0)
        y = parent_y + max((parent_height - height) // 2, 0)
        screen_width = dialog.winfo_screenwidth()
        screen_height = dialog.winfo_screenheight()
        x = min(x, max(screen_width - width, 0))
        y = min(y, max(screen_height - height, 0))
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        dialog.transient(parent)
        dialog.lift()
        dialog.focus_force()

    def _close_details_dialog(self, dialog):
        if dialog.winfo_exists():
            dialog.destroy()
        if getattr(self, "_details_dialog", None) is dialog:
            self._details_dialog = None
            self._details_path = None

    def _reopen_details_dialog(self):
        dialog = getattr(self, "_details_dialog", None)
        if dialog is not None and dialog.winfo_exists():
            self._close_details_dialog(dialog)
            self._open_asset_details()

    def _toggle_asset_tag(self, path, tag, tag_states, tag_button):
        """Enables or disables a tag for the sound shown in the details dialog."""
        enabled = not tag_states[tag]
        try:
            sorter_engine.set_asset_tag_enabled(path, tag, enabled)
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Tag Update Failed", str(error))
            return
        tag_states[tag] = enabled
        theme = gui_theme.THEME
        tag_button.configure(
            bg=theme["tag_enabled"] if enabled else theme["tag_disabled"],
            fg="white" if enabled else theme["fg_muted"],
            activebackground=theme["tag_enabled"] if enabled else theme["tag_disabled"],
            activeforeground="white" if enabled else theme["fg_light"],
        )
        self._render_results()
        if self.status_label_ref:
            self.status_label_ref.config(
                text=f" Application Status: Tag {'enabled' if enabled else 'disabled'} for sound.",
                fg=theme["accent_neon"]
            )

    def add_tag(self):
        try:
            sorter_engine.add_asset_tag(self._selected_path(), self.new_tag_var.get())
            self.new_tag_var.set("")
            self._render_results(refresh_sidebar=True)
            self._reopen_details_dialog()
            if self.status_label_ref:
                self.status_label_ref.config(
                    text=" Application Status: Asset tag added.",
                    fg=gui_theme.THEME["accent_neon"]
                )
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Tag Update Failed", str(error))

    def remove_tag(self):
        try:
            path = self._selected_path()
            tags = sorter_engine.get_indexed_asset(path)["tags"]
            tag = self.new_tag_var.get().strip().lower()
            if not tag or tag not in tags:
                raise ValueError("Enter an existing tag for the selected asset.")
            sorter_engine.remove_asset_tag(path, tag)
            self.new_tag_var.set("")
            self._render_results(refresh_sidebar=True)
            self._reopen_details_dialog()
            if self.status_label_ref:
                self.status_label_ref.config(
                    text=" Application Status: Asset tag removed.",
                    fg=gui_theme.THEME["accent_neon"]
                )
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Tag Update Failed", str(error))

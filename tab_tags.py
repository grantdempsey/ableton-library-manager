import json
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import datetime
import tkinter as tk
from tkinter import ttk, filedialog
from tab_matrix import messagebox, ask_confirm, ask_fields, show_notice

import gui_theme
import sorter_engine
import ableton_tags
import tag_evidence
import live_catalog
from live_tag_batch import LiveTagBatchDialog
import live_tag_sync


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
    """Browses indexed sounds with auditioning and inline tag curation."""

    def __init__(self, parent, status_label_ref=None):
        super().__init__(parent)
        self.status_label_ref = status_label_ref
        self.search_var = tk.StringVar()
        self.live_tag_var = tk.StringVar()
        self.live_group_var = tk.StringVar(value="Sounds")
        self.tag_source_var = tk.StringVar(value="All tags")
        self.tag_group_var = tk.StringVar(value="All groups")
        self.tag_search_var = tk.StringVar()
        self._tag_browser_rows = []
        self._tag_browser_after_id = None
        self._live_refresh_queue = None
        self._live_batch_dialog = None
        self._live_vocabulary = ()
        self._live_vocabulary_database = None
        self._selected_vocabulary_database = None
        self._live_vocabulary_queue = None
        self._tag_suggestions_queue = None
        self._tag_suggestions_scope = None
        self._indexed_live_suggestions = ()
        self._tag_suggestions_revision = 0
        self.tag_suggestions_status = tk.StringVar(value="")
        self.monitor_live_var = tk.BooleanVar(value=True)
        self.freshness_var = tk.StringVar(value="Live metadata: not checked this session. Audio discovery requires Rescan.")
        self._metadata_baseline = None
        self._metadata_candidate = None
        self._metadata_root = None
        self._metadata_queue = None
        self._metadata_after_id = None
        self._last_metadata_sync = None
        self._last_full_scan = None
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
        self.selection_count_var = tk.StringVar(value="No sounds selected")
        self.inspector_visible_var = tk.BooleanVar(value=True)
        self._asset_paths = {}
        self._selection_paths = set()
        self._selection_scope = None
        self._selection_revision = 0
        self._select_all_queue = None
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
        self._saved_collections = []
        self._build_ui()
        self._library_work_results = queue.Queue()
        self._library_work_after_id = self.after(30, self._finish_library_work)
        self._selection_summary_queue = None
        self._metadata_after_id = self.after(5000, self._poll_live_metadata)

    def ensure_loaded(self):
        """Loads the browser when the Library tab is first opened."""
        if not self._has_loaded:
            self._has_loaded = True
            self._render_results(load_sidebar=False)
            self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def _build_ui(self):
        theme = gui_theme.THEME
        header = tk.Frame(self, bg=theme["bg_dark"])
        header.pack(fill="x", padx=15, pady=(14, 4))
        tk.Label(
            header, text="Library", font=("Segoe UI", 12, "bold"),
            bg=theme["bg_dark"], fg=theme["fg_light"]
        ).pack(side="left")
        tk.Label(
            header, text="Find sounds, curate shared Live tags, and review your selection.",
            font=("Segoe UI", 9), bg=theme["bg_dark"], fg=theme["fg_muted"]
        ).pack(side="right")
        self._editable_content = ttk.Frame(self)
        self._editable_content.pack(fill="both", expand=True)
        search_controls = tk.Frame(self._editable_content, bg=theme["bg_dark"])
        search_controls.configure(
            bg=theme["bg_panel"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        search_controls.pack(fill="x", padx=15, pady=(8, 6), ipady=3)
        tk.Label(search_controls, text="Search", bg=theme["bg_panel"], fg=theme["fg_muted"]).pack(side="left", padx=(10, 0))
        self.search_entry = tk.Entry(
            search_controls, textvariable=self.search_var, width=26,
            bg=theme["bg_field"], fg=theme["fg_light"],
            relief="solid", bd=1,
            insertbackground=theme["fg_light"]
        )
        self.search_entry.pack(side="left", padx=6, fill="x", expand=True, ipady=2)
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
        self.discovery_button = tk.Button(
            search_controls, text="Discovery...", command=self._open_discovery_filters,
            bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
        )
        self.discovery_button.pack(side="left", padx=4)
        self.rescan_button = tk.Button(
            search_controls, text="Rescan library", command=self.rescan_library,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"],
            activeforeground=theme["fg_light"], bd=1
        )
        self.rescan_button.pack(side="left", padx=6)

        view_controls = tk.Frame(self._editable_content, bg=theme["bg_dark"])
        view_controls.pack(fill="x", padx=15, pady=(0, 3))
        self.total_label = tk.Label(
            view_controls, text="", bg=theme["bg_dark"], fg=theme["fg_muted"]
        )
        self.total_label.pack(side="left")
        self.inspector_toggle = tk.Checkbutton(
            view_controls, text="Show selection details (right)", variable=self.inspector_visible_var,
            command=self._toggle_inspector, bg=theme["bg_dark"],
            fg=theme["fg_light"], selectcolor=theme["bg_field"],
            activebackground=theme["bg_dark"], activeforeground=theme["fg_light"]
        )
        self.inspector_toggle.pack(side="right", padx=12)
        self.filter_chips = tk.Frame(self._editable_content, bg=theme["bg_dark"])
        self.filter_chips.pack(fill="x", padx=15, pady=(0, 4))
        freshness = tk.Frame(self._editable_content, bg=theme["bg_dark"])
        freshness.pack(side="bottom", fill="x", padx=15, pady=(0, 6))
        self.monitor_live_check = tk.Checkbutton(
            freshness, text="Auto-refresh Live tags", variable=self.monitor_live_var,
            command=self._monitor_toggled, bg=theme["bg_dark"], fg=theme["fg_light"],
            selectcolor=theme["bg_field"], activebackground=theme["bg_dark"],
            activeforeground=theme["fg_light"]
        )
        self.monitor_live_check.pack(side="left", padx=(0, 12))
        self.freshness_label = tk.Label(
            freshness, textvariable=self.freshness_var, bg=theme["bg_dark"],
            fg=theme["fg_muted"], anchor="w", font=("Segoe UI", 8),
            wraplength=800, justify="left"
        )
        self.freshness_label.pack(side="left", fill="x", expand=True)
        selection_bar = tk.Frame(self._editable_content, bg=theme["bg_dark"])
        selection_bar.pack(fill="x", padx=15, pady=(0, 5))
        tk.Label(
            selection_bar, textvariable=self.selection_count_var, bg=theme["bg_dark"],
            fg=theme["fg_muted"], anchor="w"
        ).pack(side="left")
        for text, command in (
            ("Select page", self._select_page),
            ("Select all matching", self._select_all_matching),
            ("Clear selection", self._clear_selection),
        ):
            tk.Button(
                selection_bar, text=text, command=command,
                bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
            ).pack(side="right", padx=(5, 0))

        self.browser_panes = tk.PanedWindow(
            self._editable_content, orient="horizontal", bg=theme["bg_dark"], bd=0,
            sashwidth=7, sashrelief="flat", showhandle=False, opaqueresize=True
        )
        browser = self.browser_panes
        browser.pack(fill="both", expand=True, padx=15, pady=(0, 8))
        sidebar = tk.Frame(
            browser, bg=theme["bg_field"], width=200, bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        browser.add(sidebar, minsize=150, width=200, stretch="never")
        collection_tabs = ttk.Notebook(sidebar)
        self.collection_tabs = collection_tabs
        collection_tabs.pack(fill="x", padx=5, pady=(6, 0))
        collections_panel = tk.Frame(collection_tabs, bg=theme["bg_field"])
        saved_panel = tk.Frame(collection_tabs, bg=theme["bg_field"])
        collection_tabs.add(collections_panel, text="Collections")
        collection_tabs.add(saved_panel, text="Saved")
        self.collection_list = tk.Listbox(
            collections_panel, height=3, bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground="white",
            relief="flat", highlightthickness=0, activestyle="none",
            exportselection=False
        )
        self.collection_list.pack(fill="x", padx=5)
        self.collection_list.bind("<<ListboxSelect>>", self._collection_selected)
        saved_frame = tk.Frame(saved_panel, bg=theme["bg_field"])
        saved_frame.pack(fill="x", padx=5)
        saved_scroll = ttk.Scrollbar(saved_frame, orient="vertical")
        saved_scroll.pack(side="right", fill="y")
        self.saved_collection_list = tk.Listbox(
            saved_frame, height=2, exportselection=False, activestyle="none",
            bg=theme["bg_field"], fg=theme["fg_light"], relief="flat",
            highlightthickness=0, selectbackground=theme["tag_enabled"],
            selectforeground="white", yscrollcommand=saved_scroll.set
        )
        self.saved_collection_list.pack(side="left", fill="x", expand=True)
        saved_scroll.configure(command=self.saved_collection_list.yview)
        self.saved_collection_list.bind("<<ListboxSelect>>", self._saved_collection_selected)
        saved_actions = tk.Frame(saved_panel, bg=theme["bg_field"])
        saved_actions.pack(fill="x", padx=5, pady=(4, 0))
        self.save_collection_button = tk.Button(
            saved_actions, text="Save current...", command=self._save_current_search,
            bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
        )
        self.save_collection_button.pack(side="left")
        self.delete_collection_button = tk.Button(
            saved_actions, text="Delete", command=self._delete_selected_collection,
            bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
        )
        self.delete_collection_button.pack(side="left", padx=4)
        tk.Label(
            sidebar, text="Tags", bg=theme["bg_field"], fg=theme["fg_muted"],
            font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(fill="x", padx=10, pady=(2, 4))
        tag_navigation = tk.Frame(sidebar, bg=theme["bg_field"])
        tag_navigation.pack(fill="x", padx=5)
        self.tag_source_picker = ttk.Combobox(
            tag_navigation, textvariable=self.tag_source_var, state="readonly",
            values=("All tags", "Live manual tags", "Generated tags"), width=15
        )
        self.tag_source_picker.pack(fill="x")
        self.tag_source_picker.bind("<<ComboboxSelected>>", self._tag_navigation_changed)
        self.tag_group_picker = ttk.Combobox(
            tag_navigation, textvariable=self.tag_group_var, state="readonly",
            values=("All groups",), width=15
        )
        self.tag_group_picker.pack(fill="x", pady=3)
        self.tag_group_picker.bind("<<ComboboxSelected>>", self._tag_navigation_changed)
        tag_search_row = tk.Frame(tag_navigation, bg=theme["bg_field"])
        tag_search_row.pack(fill="x")
        tk.Label(
            tag_search_row, text="Find:", bg=theme["bg_field"], fg=theme["fg_muted"]
        ).pack(side="left")
        self.tag_search_entry = tk.Entry(
            tag_search_row, textvariable=self.tag_search_var, width=10,
            bg=theme["bg_dark"], fg=theme["fg_light"], insertbackground=theme["fg_light"]
        )
        self.tag_search_entry.pack(side="left", fill="x", expand=True)
        self.tag_search_var.trace_add("write", self._schedule_tag_navigation)
        self.tag_browser_status = tk.Label(
            tag_navigation, text="", bg=theme["bg_field"], fg=theme["fg_muted"],
            wraplength=175, justify="left", anchor="w", font=("Segoe UI", 8)
        )
        self.tag_browser_status.pack(fill="x", pady=(3, 0))
        tk.Button(
            tag_navigation, text="Tag sources / help", command=self._explain_tag_sources,
            bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
        ).pack(fill="x", pady=(0, 3))
        tag_list_frame = tk.Frame(sidebar, bg=theme["bg_field"])
        tag_list_frame.pack(fill="both", expand=True, padx=5, pady=(0, 8))
        tag_scrollbar = ttk.Scrollbar(tag_list_frame, orient="vertical")
        tag_scrollbar.pack(side="right", fill="y")
        tag_horizontal = ttk.Scrollbar(tag_list_frame, orient="horizontal")
        tag_horizontal.pack(side="bottom", fill="x")
        self.tag_list = tk.Listbox(
            tag_list_frame, bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground="white",
            relief="flat", highlightthickness=0, activestyle="none", exportselection=False,
            yscrollcommand=tag_scrollbar.set, xscrollcommand=tag_horizontal.set
        )
        self.tag_list.pack(in_=tag_list_frame, side="left", fill="both", expand=True)
        self.tag_list.bind("<Configure>", self._size_tag_navigation, add="+")
        tag_scrollbar.configure(command=self.tag_list.yview)
        tag_horizontal.configure(command=self.tag_list.xview)
        self.tag_list.bind("<ButtonRelease-1>", self._tag_released, add="+")
        self.tag_list.bind("<KeyRelease-Up>", self._tag_selected, add="+")
        self.tag_list.bind("<KeyRelease-Down>", self._tag_selected, add="+")
        self.tag_list.bind("<Return>", self._tag_selected, add="+")
        wrapper = tk.Frame(
            browser, bg=theme["bg_field"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        browser.add(wrapper, minsize=300, width=500, stretch="always")
        page_controls = tk.Frame(wrapper, bg=theme["bg_field"])
        page_controls.pack(side="bottom", fill="x", pady=4)
        self.previous_page_button = tk.Button(
            page_controls, text="Previous page", command=self._previous_page,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"], bd=1, state="disabled"
        )
        self.previous_page_button.pack(side="left", padx=4)
        self.next_page_button = tk.Button(
            page_controls, text="Next page", command=self._next_page,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"], bd=1, state="disabled"
        )
        self.next_page_button.pack(side="right", padx=4)
        self.page_label = tk.Label(
            page_controls, text="", bg=theme["bg_field"], fg=theme["fg_muted"],
            justify="center", wraplength=130
        )
        self.page_label.pack(side="left", fill="x", expand=True)
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
        for column, width in (("Filename", 280), ("Folder", 220)):
            self.asset_tree.heading(column, text=column)
            self.asset_tree.column(column, width=width, anchor="w")

        selected = tk.Frame(
            browser, bg=theme["bg_field"], bd=1, relief="solid",
            highlightbackground=theme["border"], highlightcolor=theme["border"]
        )
        self.inspector = selected
        browser.add(selected, minsize=280, width=310, stretch="never")
        selected_header = tk.Frame(selected, bg=theme["bg_field"])
        selected_header.pack(fill="x", padx=10, pady=(7, 0))
        tk.Label(
            selected, textvariable=self.selected_asset_var,
            font=("Segoe UI", 11, "bold"), bg=theme["bg_field"], fg=theme["accent_neon"],
            wraplength=275, justify="left", anchor="w"
        ).pack(in_=selected_header, fill="x")
        playback_row = tk.Frame(selected, bg=theme["bg_field"])
        playback_row.pack(fill="x", padx=10, pady=(8, 0))
        favorite_row = tk.Frame(selected, bg=theme["bg_field"])
        favorite_row.pack(fill="x", padx=10, pady=(8, 0))
        self.favorite_button = tk.Button(
            favorite_row, text="Favorite selected", command=self.toggle_selected_favorite,
            bg=theme["tag_enabled"], fg="white",
            activebackground=theme["tag_enabled"], activeforeground="white",
            bd=1, padx=8
        )
        self.favorite_button.pack(side="left")
        self.unfavorite_button = tk.Button(
            favorite_row, text="Unfavorite", command=self.bulk_remove_favorite,
            bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
        )
        self.unfavorite_button.pack(side="left", padx=(6, 0))
        self.autoplay_check = tk.Checkbutton(
            playback_row, text="Auto-play", variable=self.autoplay_var,
            bg=theme["bg_field"], fg=theme["fg_light"], selectcolor=theme["bg_dark"],
            activebackground=theme["bg_field"], activeforeground=theme["fg_light"],
            disabledforeground=theme["fg_muted"]
        )
        self.play_button = tk.Button(
            playback_row, text="Play sound", command=self.play_selected_sound,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"],
            activeforeground=theme["fg_light"],
            bd=1, padx=8
        )
        self.play_button.pack(side="left")
        tk.Button(
            playback_row, text="Stop", command=self.stop_sound,
            bg=theme["btn_secondary"], fg=theme["fg_light"],
            activebackground=theme["btn_secondary_hover"], bd=1, padx=8
        ).pack(side="left", padx=(6, 0))
        self.autoplay_check.pack(side="left", padx=(6, 0))
        tk.Label(
            selected,
            textvariable=self.selected_tags_var,
            font=("Segoe UI", 9), bg=theme["bg_field"], fg=theme["fg_muted"],
            justify="left", wraplength=275, anchor="w"
        ).pack(anchor="w", padx=10, pady=(2, 7))
        self.waveform_canvas = tk.Canvas(
            selected, height=24, bg=theme["bg_dark"], highlightthickness=1,
            highlightbackground=theme["border"]
        )
        self.waveform_canvas.pack(fill="x", padx=10, pady=(0, 6))
        editor_actions = tk.Frame(selected, bg=theme["bg_field"])
        editor_actions.pack(side="bottom", fill="x", padx=10, pady=(0, 8))
        tag_summary = tk.Frame(selected, bg=theme["bg_field"])
        tag_summary.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        tk.Label(
            tag_summary, text="TAGS", bg=theme["bg_field"], fg=theme["accent_neon"],
            font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(fill="x", pady=(0, 4))
        summary_scroll = ttk.Scrollbar(tag_summary)
        summary_scroll.pack(side="right", fill="y")
        self.assigned_tags_text = tk.Text(
            tag_summary, width=25, height=3, wrap="word", state="disabled",
            bg=theme["bg_dark"], fg=theme["fg_light"], bd=0,
            yscrollcommand=summary_scroll.set
        )
        self.assigned_tags_text.pack(fill="both", expand=True)
        summary_scroll.configure(command=self.assigned_tags_text.yview)
        self.edit_live_tags_button = tk.Button(
            editor_actions, text="Edit Live tags...", command=self._open_tag_editor,
            bg=theme["btn_primary"], fg=theme["btn_primary_fg"], bd=1
        )
        self.edit_live_tags_button.pack(side="left")
        self.asset_tree.bind("<<TreeviewSelect>>", self._page_selection_changed)
        self.asset_tree.bind("<Double-1>", lambda _event: self._open_asset_details())
        self.asset_tree.bind("<space>", self._shortcut_play_toggle)
        self.asset_tree.bind("<KeyPress-f>", self._shortcut_favorite)
        self.bind_all("<Control-f>", self._shortcut_focus_search, add="+")
        self._refresh_saved_collections()
        self._refresh_filter_chips()
        self._show_selected_asset()

    def _open_tag_editor(self):
        self._load_live_tag_suggestions()
        self._open_live_batch()

    def _toggle_inspector(self):
        if self.inspector_visible_var.get():
            self.browser_panes.add(
                self.inspector, minsize=280, width=310, stretch="never"
            )
        else:
            self.browser_panes.forget(self.inspector)


    def _load_live_tag_suggestions(self):
        self._request_live_vocabulary()
        scope = (gui_theme.USER_LIBRARY_PATH, self._tag_suggestions_revision)
        if self._tag_suggestions_queue is not None or scope == self._tag_suggestions_scope:
            return
        results = queue.Queue()
        self._tag_suggestions_queue = results
        self.tag_suggestions_status.set("Loading tag choices in the background...")
        def worker():
            try:
                tags = sorter_engine.list_indexed_tags(library_root=scope[0])
                results.put(tuple(
                    tag[len(ableton_tags.CACHE_PREFIX):] for tag, _count in tags
                    if tag.startswith(ableton_tags.CACHE_PREFIX)
                ))
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                results.put(error)
        threading.Thread(target=worker, daemon=True).start()
        self.after(30, lambda: self._finish_tag_suggestions(scope, results))

    def _finish_tag_suggestions(self, scope, results):
        try:
            result = results.get_nowait()
        except queue.Empty:
            self.after(30, lambda: self._finish_tag_suggestions(scope, results))
            return
        self._tag_suggestions_queue = None
        if scope != (gui_theme.USER_LIBRARY_PATH, self._tag_suggestions_revision):
            self._load_live_tag_suggestions()
            return
        if isinstance(result, Exception):
            self.tag_suggestions_status.set("Tag choices could not refresh; previous choices retained.")
            self._set_status(f"Tag suggestions failed; previous suggestions retained: {result}")
            messagebox.showerror("Live Tag Suggestions Failed", str(result), parent=self._live_batch_dialog or self)
            return
        self._indexed_live_suggestions = result
        self._tag_suggestions_scope = scope
        self.tag_suggestions_status.set("")
        self._update_tag_suggestion_choices()

    def _update_tag_suggestion_choices(self):
        hierarchies = sorted(set(self._live_vocabulary) | set(self._indexed_live_suggestions), key=str.casefold)
        groups = sorted(set(ableton_tags.TAG_GROUPS) | {tag.split("|")[0] for tag in hierarchies})
        if self._live_batch_dialog is not None:
            self._live_batch_dialog.tag_entry.configure(values=hierarchies)
            self._live_batch_dialog.group_entry.configure(values=groups)

    def _request_live_vocabulary(self):
        if self._live_vocabulary_queue is not None:
            return
        if self._selected_vocabulary_database is not None:
            database = self._selected_vocabulary_database
        else:
            databases = live_catalog.available_databases()
            if len(databases) != 1:
                if databases:
                    self._set_status("Multiple Live databases found. Use Tag suggestions source... in the tag editor to choose one.")
                return
            database = str(databases[0])
        if database == self._live_vocabulary_database:
            return
        results = queue.Queue()
        self._live_vocabulary_queue = results
        self._set_status("Loading Live tag vocabulary in the background; no assignments are changed.")
        def worker():
            try:
                results.put(live_catalog.read_vocabulary(database))
            except (OSError, ValueError, live_catalog.sqlite3.Error) as error:
                results.put(error)
        threading.Thread(target=worker, daemon=True).start()
        self.after(30, lambda: self._finish_live_vocabulary(database, results))

    def _finish_live_vocabulary(self, database, results):
        try:
            vocabulary = results.get_nowait()
        except queue.Empty:
            self.after(30, lambda: self._finish_live_vocabulary(database, results))
            return
        self._live_vocabulary_queue = None
        if self._selected_vocabulary_database is not None and self._selected_vocabulary_database != database:
            self._request_live_vocabulary()
            return
        if isinstance(vocabulary, Exception):
            self._set_status(f"Live tag vocabulary failed to load; previous suggestions retained: {vocabulary}")
            messagebox.showerror("Live Tag Vocabulary Failed", str(vocabulary), parent=self)
            return
        self._live_vocabulary = tuple(tag for tag in vocabulary if "|" in tag)
        self._live_vocabulary_database = database
        self._update_tag_suggestion_choices()
        self._set_status(f"Loaded {len(self._live_vocabulary):,} Live tag suggestions; assignments unchanged.")

    def _choose_live_vocabulary_database(self):
        databases = live_catalog.available_databases()
        selected = filedialog.askopenfilename(
            parent=self._live_batch_dialog or self, title="Choose Live tag vocabulary database (read only)",
            initialdir=os.path.dirname(str(databases[0])) if databases else None,
            filetypes=(("Live catalog database", "Live-files-*.db"), ("SQLite database", "*.db")),
        )
        if selected:
            self._selected_vocabulary_database = selected
            self._request_live_vocabulary()


    def _refresh_selected_live_tags(self):
        if self._metadata_queue is not None or self._live_refresh_queue is not None or self._live_batch_dialog is not None:
            return
        try:
            paths = tuple(self._selected_paths())
        except ValueError as error:
            messagebox.showerror("Live tags", str(error))
            return
        results = queue.Queue()
        self._live_refresh_queue = results
        self._show_selected_asset()
        self._set_status(f"Reading Live metadata for {len(paths):,} selected sounds...")
        def worker():
            try:
                sorter_engine.refresh_live_tag_cache(paths)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                results.put(error)
            else:
                results.put(None)
        threading.Thread(target=worker, daemon=True).start()
        self.after(30, self._finish_selected_live_refresh, len(paths))

    def _finish_selected_live_refresh(self, count):
        try:
            error = self._live_refresh_queue.get_nowait()
        except queue.Empty:
            self.after(30, self._finish_selected_live_refresh, count)
            return
        self._live_refresh_queue = None
        self._show_selected_asset()
        if error is not None:
            self._set_freshness(f"Selected refresh failed: {error}")
            messagebox.showerror("Live Metadata Refresh Failed", str(error))
            self._set_status("Live metadata refresh failed; cached assignments were not replaced.")
            return
        self._render_results(refresh_sidebar=True)
        self._set_freshness(f"Selected metadata refreshed ({count:,} sounds); not a full-library check.")
        self._set_status(f"Read Live metadata for {count:,} sounds. No sidecars or audio changed.")


    def _edit_live_tags(self, paths, tag, action, replacement=None):
        if self._metadata_queue is not None or self._live_refresh_queue is not None or self._live_batch_dialog is not None:
            show_notice(self.winfo_toplevel(), "Live tags", "Finish the metadata refresh or close the tag editor first.")
            return False
        try:
            operation = ableton_tags.TagOperation(
                action, ableton_tags.normalize_tag(tag),
                ableton_tags.normalize_tag(replacement) if replacement is not None else None,
            )
        except ValueError as error:
            messagebox.showerror("Invalid Live tag action", str(error))
            return False
        dialog = LiveTagBatchDialog(self, tuple(paths))
        self._live_batch_dialog = dialog
        dialog.title("Review Live tag change")
        dialog.action_var.set(operation.action)
        dialog.tag_var.set(operation.tag)
        dialog.replacement_var.set(operation.replacement or "")
        dialog.review()
        return True

    def _open_live_batch(self):
        if self._live_batch_dialog is not None:
            self._live_batch_dialog.lift()
            return
        if self._metadata_queue is not None or self._live_refresh_queue is not None:
            show_notice(self.winfo_toplevel(), "Edit Live tags", "Wait for the metadata refresh to finish.")
            return
        try:
            paths = tuple(self._selected_paths())
        except ValueError as error:
            messagebox.showerror("Edit Live tags", str(error))
            return
        self._live_batch_dialog = LiveTagBatchDialog(self, paths)
        self._update_tag_suggestion_choices()
        self._show_selected_asset()

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
            if not isinstance(data, list) or any(
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str) or not item["name"].strip()
                or any(not isinstance(item.get(key, ""), str) for key in ("text", "tag"))
                or item.get("collection", "All sounds") not in (
                    "All sounds", "Favorites", "Loops", "One-shots", "MIDI"
                )
                for item in data
            ):
                raise ValueError("Saved collections must contain named searches with valid filters.")
            return data
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            messagebox.showerror("Saved collections", f"Could not load saved collections: {error}")
            return None

    def _write_saved_searches(self, items):
        temporary_path = None
        try:
            path = self._saved_searches_file()
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=os.path.dirname(path),
                prefix="saved_searches-", suffix=".tmp", delete=False
            ) as handle:
                temporary_path = handle.name
                json.dump(items, handle, indent=2)
            os.replace(temporary_path, path)
        except OSError as error:
            messagebox.showerror("Saved collections", f"Could not save collections: {error}")
            return False
        finally:
            if temporary_path and os.path.exists(temporary_path):
                os.remove(temporary_path)
        self._refresh_saved_collections()
        return True

    def _refresh_saved_collections(self):
        items = self._load_saved_searches()
        self._saved_collections = items if items is not None else []
        self.saved_collection_list.delete(0, "end")
        for item in self._saved_collections:
            self.saved_collection_list.insert("end", item["name"])
        if not self._saved_collections:
            self.saved_collection_list.insert(
                "end", "Could not load collections" if items is None else "No saved collections"
            )
        self._sync_saved_collection_selection()

    def _sync_saved_collection_selection(self):
        self.saved_collection_list.selection_clear(0, "end")
        for index, item in enumerate(self._saved_collections):
            if (
                item.get("text", "") == self.search_var.get().strip()
                and (item.get("collection") or "All sounds") == self._active_collection
                and item.get("tag", "") == self.active_tag_filter
            ):
                self.saved_collection_list.selection_set(index)
                break

    def _saved_collection_selected(self, _event=None):
        selection = self.saved_collection_list.curselection()
        if selection and selection[0] < len(self._saved_collections):
            self._apply_saved_search(self._saved_collections[selection[0]])

    def _delete_selected_collection(self):
        selection = self.saved_collection_list.curselection()
        if selection and selection[0] < len(self._saved_collections):
            self._delete_saved_search(self._saved_collections[selection[0]])
        else:
            show_notice(
                self.winfo_toplevel(), "Saved collections",
                "Select a saved collection to delete it. Your sounds and tags are not affected."
            )

    def _refresh_filter_chips(self):
        for widget in self.filter_chips.winfo_children():
            widget.destroy()
        filters = []
        if self.search_var.get().strip():
            filters.append(("search", f"Search: {self.search_var.get().strip()}"))
        if self._active_collection != "All sounds":
            filters.append(("collection", f"Collection: {self._active_collection}"))
        if self.active_tag_filter:
            filters.append(("tag", f"Tag: {self.active_tag_filter}"))
        theme = gui_theme.THEME
        for column, (kind, label) in enumerate(filters):
            label = label if len(label) <= 30 else label[:27] + "..."
            tk.Button(
                self.filter_chips, text=f"{label}  x",
                command=lambda kind=kind: self._clear_filter(kind),
                bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
            ).grid(row=0, column=column, sticky="w", padx=(0, 5), pady=1)
        if filters:
            tk.Button(
                self.filter_chips, text="Clear all", command=self._clear_all_filters,
                bg=theme["btn_secondary"], fg=theme["fg_light"], bd=1
            ).grid(row=0, column=len(filters), sticky="w", padx=3)
        self._sync_saved_collection_selection()

    def _clear_filter(self, kind):
        if kind == "search":
            self.search_var.set("")
        elif kind == "collection":
            self._active_collection = "All sounds"
            self.favorites_only = False
        elif kind == "tag":
            self.active_tag_filter = ""
        self._reload_filter_results()

    def _clear_all_filters(self):
        self.search_var.set("")
        self._active_collection = "All sounds"
        self.favorites_only = False
        self.active_tag_filter = ""
        self._reload_filter_results()

    def _reload_filter_results(self):
        self.stop_sound()
        self._page_index = 0
        self._rendered_tag_scope = None
        self._tag_selection_generation = 0
        self._safe_render_results()
        self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def _show_saved_searches_menu(self):
        theme = gui_theme.THEME
        menu = tk.Menu(
            self, tearoff=0, bg=theme["bg_panel"], fg=theme["fg_light"],
            activebackground=theme["btn_primary"], activeforeground=theme["btn_primary_fg"]
        )
        menu.add_command(label="Save current search…", command=self._save_current_search)
        items = self._load_saved_searches()
        if items is None:
            menu.destroy()
            return
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

    def _open_discovery_filters(self):
        try:
            tags = sorter_engine.list_indexed_tags(gui_theme.USER_LIBRARY_PATH)
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Discovery filters", str(error))
            return
        dialog = tk.Toplevel(self)
        dialog.title("Add discovery filters")
        dialog.minsize(580, 490)
        self._place_dialog(dialog, 640, 560)
        theme = gui_theme.THEME
        dialog.configure(bg=theme["bg_dark"])
        ttk.Label(
            dialog, text="Add constraints to the current search. Saved collections remember them.",
            wraplength=540
        ).pack(fill="x", padx=12, pady=10)
        ttk.Label(
            dialog, text="Choose tags (Ctrl/Shift for several). Live assignments appear first."
        ).pack(anchor="w", padx=12)
        tags = [
            (tag, count) for tag, count in tags
            if tag.startswith((ableton_tags.CACHE_PREFIX, "category:", "name:"))
        ]
        ordered = sorted(tags, key=lambda row: (
            not row[0].startswith(ableton_tags.CACHE_PREFIX), row[0].casefold()
        ))
        frame = ttk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=12, pady=5)
        scroll = ttk.Scrollbar(frame)
        scroll.pack(side="right", fill="y")
        listing = tk.Listbox(
            frame, selectmode="extended", exportselection=False, height=8,
            yscrollcommand=scroll.set, bg=theme["bg_field"], fg=theme["fg_light"],
            selectbackground=theme["tag_enabled"], selectforeground=theme["fg_light"],
            highlightbackground=theme["border"], highlightcolor=theme["accent_neon"],
            highlightthickness=1, bd=0, relief="flat", activestyle="dotbox",
            font=("Segoe UI", 9)
        )
        listing.pack(fill="both", expand=True)
        scroll.configure(command=listing.yview)
        for tag, count in ordered:
            listing.insert("end", f"{tag} ({count})")
        mode = tk.StringVar(dialog, value="Match all")
        ttk.Combobox(
            dialog, textvariable=mode, state="readonly",
            values=("Match all", "Match any", "Exclude selected")
        ).pack(fill="x", padx=12, pady=4)
        live_state = tk.StringVar(dialog, value="Any manual Live tags")
        ttk.Combobox(
            dialog, textvariable=live_state, state="readonly",
            values=("Any manual Live tags", "No manual Live tags", "Has manual Live tags")
        ).pack(fill="x", padx=12, pady=4)
        ttk.Label(dialog, text="Missing Live group (optional; e.g. Character):").pack(anchor="w", padx=12)
        group = tk.StringVar(dialog)
        ttk.Combobox(
            dialog, textvariable=group,
            values=sorted({
                tag[len(ableton_tags.CACHE_PREFIX):].split("|")[0]
                for tag, _count in tags if tag.startswith(ableton_tags.CACHE_PREFIX)
            })
        ).pack(fill="x", padx=12, pady=4)
        ttk.Label(
            dialog, text="Manual Live filters use cached sidecar assignments, not automatic/factory "
            "metadata. Rescan after external edits. Match-any tags form one OR set across the search.",
            wraplength=540, justify="left"
        ).pack(fill="x", padx=12, pady=6)
        def apply():
            if self._add_discovery_filters(
                [ordered[index][0] for index in listing.curselection()],
                mode.get(), live_state.get(), group.get()
            ):
                dialog.destroy()
        ttk.Button(dialog, text="Add to search", command=apply).pack(side="right", padx=12, pady=12)
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).pack(side="left", padx=12, pady=12)

    def _add_discovery_filters(self, tags, mode, live_state, group):
        try:
            if mode not in {"Match all", "Match any", "Exclude selected"}:
                raise ValueError("Choose a supported tag matching mode.")
            if live_state not in {"Any manual Live tags", "No manual Live tags", "Has manual Live tags"}:
                raise ValueError("Choose a supported manual Live tag filter.")
            tokens = []
            prefix = {"Match all": "tag:", "Match any": "anytag:", "Exclude selected": "-tag:"}[mode]
            for tag in tags:
                if not tag or '"' in tag or any(ord(char) < 32 for char in tag):
                    raise ValueError("This tag cannot be represented in search syntax.")
                tokens.append(f'"{prefix}{tag}"')
            if live_state != "Any manual Live tags":
                tokens.append("live:none" if live_state == "No manual Live tags" else "live:tagged")
            group = group.strip()
            if group:
                if "|" in group or '"' in group or any(ord(char) < 32 for char in group):
                    raise ValueError("Enter one Live group name, not a hierarchy.")
                tokens.append(f'"missing-group:{group}"')
            if not tokens:
                raise ValueError("Choose at least one discovery constraint.")
            search = " ".join([self.search_var.get().strip(), *tokens]).strip()
            sorter_engine._discovery_clauses(sorter_engine._parse_asset_search(search))
        except ValueError as error:
            messagebox.showerror("Discovery filters", str(error))
            return False
        self.search_var.set(search)
        self._reload_filter_results()
        return True

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
        existing = self._load_saved_searches()
        if existing is None:
            return
        items = [i for i in existing if i["name"].lower() != item["name"].lower()]
        items.append(item)
        self._write_saved_searches(items)

    def _apply_saved_search(self, item):
        self.stop_sound()
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
        items = self._load_saved_searches()
        if items is not None:
            self._write_saved_searches([i for i in items if i["name"] != item["name"]])

    def refresh(self):
        self._static_counts.clear()
        self._cached_tags = []
        self._cached_tag_scope = None
        self._rendered_tag_scope = None
        self._sidebar_loaded = False
        self._render_results(load_sidebar=False)
        self._request_sidebar_load(gui_theme.USER_LIBRARY_PATH)

    def invalidate_library(self, _event=None):
        """Invalidates index-derived state and reloads now or on the next visit."""
        self._clear_selection()
        self._sidebar_generation += 1
        self._static_counts.clear()
        self._cached_tags = []
        self._cached_tag_scope = None
        self._rendered_tag_scope = None
        self._sidebar_loaded = False
        self._has_loaded = False
        self._page_index = 0
        if self._tab_is_visible():
            self.ensure_loaded()

    def _set_freshness(self, text):
        scan = self._last_full_scan or "not this session"
        sync = self._last_metadata_sync or "not this session"
        self.freshness_var.set(f"{text}\nFull scan: {scan} | Library Live-tag sync: {sync}")

    def _monitor_toggled(self):
        if self.monitor_live_var.get():
            self._set_freshness("Live-tag monitoring enabled; waiting for a stable check.")
        else:
            self._set_freshness("Live-tag monitoring paused; external edits may not be reflected.")

    def _poll_live_metadata(self):
        self._metadata_after_id = None
        if getattr(self.winfo_toplevel(), "_closing", False):
            return
        if not self.monitor_live_var.get() or not self._tab_is_visible():
            self._metadata_after_id = self.after(5000, self._poll_live_metadata)
            return
        if self._refresh_running or self._live_refresh_queue is not None or self._live_batch_dialog is not None:
            self._set_freshness("Live-tag monitoring paused during scan / selected refresh / batch editing.")
            self._metadata_after_id = self.after(5000, self._poll_live_metadata)
            return
        root = gui_theme.USER_LIBRARY_PATH
        if root != self._metadata_root:
            self._metadata_baseline = None
            self._metadata_candidate = None
            self._metadata_root = root
        results = queue.Queue()
        self._metadata_queue = results
        baseline, candidate = self._metadata_baseline, self._metadata_candidate
        self._set_freshness("Checking manual Live sidecars in the background...")
        self._show_selected_asset()
        def worker():
            try:
                state, snapshot = live_tag_sync.poll_live_metadata(root, baseline, candidate)
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                results.put((None, None, error))
            else:
                results.put((state, snapshot, None))
        threading.Thread(target=worker, daemon=True).start()
        self._metadata_after_id = self.after(30, self._finish_metadata_poll, root)

    def _finish_metadata_poll(self, root):
        self._metadata_after_id = None
        try:
            state, snapshot, error = self._metadata_queue.get_nowait()
        except queue.Empty:
            self._metadata_after_id = self.after(30, self._finish_metadata_poll, root)
            return
        self._metadata_queue = None
        self._show_selected_asset()
        if root != gui_theme.USER_LIBRARY_PATH:
            self._metadata_baseline = None
            self._metadata_candidate = None
            self._set_freshness("Library location changed; waiting for a new metadata check.")
        elif error is not None:
            self._metadata_candidate = None
            self._set_freshness(f"Live-tag sync failed; cached assignments retained: {error}")
            self._set_status(f"Live-tag sync failed: {error}")
        elif state == "pending":
            self._metadata_candidate = snapshot
            self._set_freshness("Live metadata differs / not yet checked; waiting for a stable second probe.")
        else:
            self._metadata_baseline = snapshot
            self._metadata_candidate = None
            self._last_metadata_sync = datetime.datetime.now().strftime("%H:%M:%S")
            if state == "refreshed":
                self._tag_suggestions_revision += 1
                self._safe_render_results()
                self._static_counts.clear()
                self._request_sidebar_load(root)
            self._set_freshness(
                "Manual Live metadata checked. New / deleted audio still requires Rescan."
                if self.monitor_live_var.get() else "Final metadata check finished; monitoring is paused."
            )
        self._metadata_after_id = self.after(5000, self._poll_live_metadata)

    def rescan_library(self, *, notify_busy=True):
        if getattr(self.winfo_toplevel(), "_closing", False):
            return
        if self._refresh_running:
            return
        if self._metadata_queue is not None or self._live_refresh_queue is not None or self._live_batch_dialog is not None:
            if notify_busy:
                show_notice(self.winfo_toplevel(), "Rescan library", "Finish the metadata refresh or close the tag editor first.")
            else:
                self.after(500, lambda: self.rescan_library(notify_busy=False))
            return
        library_root = gui_theme.USER_LIBRARY_PATH
        if not library_root or not os.path.isdir(library_root):
            self._set_freshness("Library unavailable; cached results may be stale.")
            messagebox.showerror("Rescan library", "The configured User Library is unavailable.")
            return
        self._refresh_running = True
        self.rescan_button.configure(state="disabled")
        self._set_status("Scanning the library for sounds...")
        self._set_freshness("Scanning audio and manual Live metadata...")
        threading.Thread(
            target=self._discover_then_refresh, args=(library_root,), daemon=True
        ).start()

    def _discover_then_refresh(self, library_root):
        try:
            discovered = sorter_engine.index_existing_library(library_root)
        except (
            OSError, ValueError, KeyError, TypeError, sorter_engine.sqlite3.Error
        ) as error:
            self._library_work_results.put(("scan", 0, error, None))
            return
        self._library_work_results.put(("scan", discovered, None, None))

    def _finish_library_work(self):
        try:
            while True:
                kind, result, error, generation = self._library_work_results.get_nowait()
                if kind == "scan":
                    self._finish_refresh(result, error)
                else:
                    self._finish_sidebar_load(result, error, generation)
        except queue.Empty:
            pass
        self._library_work_after_id = self.after(30, self._finish_library_work)

    def has_pending_library_work(self):
        return (
            self._refresh_running or self._sidebar_loading
            or self._metadata_queue is not None or self._live_refresh_queue is not None
        )

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
            self._library_work_results.put(("sidebar", None, error, generation))
            return
        self._library_work_results.put(("sidebar", sidebar_data, None, generation))

    def _finish_sidebar_load(self, sidebar_data, error, generation):
        self._sidebar_loading = False
        if generation != self._sidebar_generation:
            self._static_counts.clear()
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
        self._rendered_tag_scope = None
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
            self._set_freshness(f"Scan failed; cached results may be stale: {error}")
            self._set_status(f"Refresh failed: {error}")
            messagebox.showerror("Refresh Failed", str(error))
            return
        self._last_full_scan = datetime.datetime.now().strftime("%H:%M:%S")
        self._metadata_baseline = None
        self._metadata_candidate = None
        self._set_freshness("Full scan complete; manual Live tags read.")
        self._set_status(
            f"Refresh complete. Found {discovered:,} sounds in the User Library."
        )
        if sidebar_data is not None:
            self._cached_total_count = sidebar_data["total_count"]
            self._collection_counts = sidebar_data["collection_counts"]
            self._cached_tags = sidebar_data["tags"]
            self._cached_tag_scope = sidebar_data["tag_scope"]
            self._sidebar_loaded = True
        self._page_index = 0
        self._render_results(refresh_sidebar=sidebar_data is None)

    def _render_results(self, refresh_sidebar=False, load_sidebar=True):
        if refresh_sidebar:
            self._tag_suggestions_revision += 1
        self._refresh_filter_chips()
        self._capture_page_selection()
        scope = self._current_selection_scope()
        if scope != self._selection_scope:
            self._selection_paths.clear()
            self._selection_revision += 1
            self._selection_scope = scope
        selected_paths = self._selection_paths
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
            text=f"Page {self._page_index + 1}\n"
            f"{self._page_index * self._page_size + 1:,}-"
            f"{self._page_index * self._page_size + len(records):,}"
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
        selected_items = []
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
            if record["path"] in selected_paths:
                selected_items.append(item_id)
        if not records:
            self.asset_tree.insert(
                "", "end",
                values=("No matching sounds", "Try another filter")
            )
        elif selected_items:
            self.asset_tree.selection_set(selected_items)
            self.asset_tree.focus(selected_items[0])
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
        self._render_tag_browser(tags)

    def _size_tag_navigation(self, event):
        self.tag_browser_status.configure(wraplength=max(100, event.width))

    def _explain_tag_sources(self):
        show_notice(
            self.winfo_toplevel(), "Library tag sources",
            "Live manual tags: exact assignments read from Ableton Folder Info .xmp sidecars "
            "for sounds inside the configured User Library. Groups come from those assignments "
            "(for example Sounds or Character); empty groups and unused vocabulary are not listed.\n\n"
            "Generated tags: category: and name: labels derived by the manager, not Live tags.\n\n"
            "Live tag editor: dropdown suggestions can include Live's stored vocabulary, "
            "including unused tags. Use Tag suggestions source... to choose a database when more than "
            "one is available. Suggestions do not assign tags or change manual-tag counts.\n\n"
            "Ableton's automatic/factory tags, colored Collections, and its complete global tag "
            "vocabulary are not imported by this sidecar workflow. Tags on external folders will "
            "not appear unless the sounds are imported into the configured library.\n\n"
            "Watch Live tags checks manual sidecars in the background while Library is visible. "
            "Allow two stable probes; see the freshness line for pending checks or errors. "
            "Rescan discovers new/deleted audio; Refresh selected rereads just those samples. "
            "Group/source/Find controls browse the tag list only; "
            "they do not change the sound selection or active sound filter."
        )

    def _schedule_tag_navigation(self, *_args):
        if self._tag_browser_after_id is not None:
            self.after_cancel(self._tag_browser_after_id)
        self._tag_browser_after_id = self.after(100, self._tag_navigation_changed)

    def _tag_navigation_changed(self, _event=None):
        if self._tag_browser_after_id is not None:
            self.after_cancel(self._tag_browser_after_id)
            self._tag_browser_after_id = None
        self._render_tag_browser(self._cached_tags)

    def _render_tag_browser(self, tags):
        if self._tag_render_after_id is not None:
            self.after_cancel(self._tag_render_after_id)
            self._tag_render_after_id = None
        self.tag_list.delete(0, "end")
        self._tag_render_generation += 1
        groups = sorted({
            tag[len(ableton_tags.CACHE_PREFIX):].split("|")[0]
            for tag, _count in tags if tag.startswith(ableton_tags.CACHE_PREFIX)
        })
        self.tag_group_picker.configure(values=("All groups", *groups))
        if self.tag_group_var.get() not in ("All groups", *groups):
            self.tag_group_var.set("All groups")
        self.tag_group_picker.configure(
            state="readonly" if self.tag_source_var.get() in ("All tags", "Live manual tags") else "disabled"
        )
        source = self.tag_source_var.get()
        group = self.tag_group_var.get()
        search = self.tag_search_var.get().strip().casefold()
        rows = []
        for tag, count in tags:
            if tag.startswith(ableton_tags.CACHE_PREFIX):
                kind = "Live manual tags"
                label = tag[len(ableton_tags.CACHE_PREFIX):]
                rank = 0
            elif tag.startswith(("category:", "name:")):
                kind, label, rank = "Generated tags", tag, 2
            else:
                continue
            if source != "All tags" and source != kind:
                continue
            if source in ("All tags", "Live manual tags") and group != "All groups":
                if kind != "Live manual tags" or label.split("|")[0] != group:
                    continue
            if search and search not in label.casefold():
                continue
            display = f"Live: {label}" if kind == "Live manual tags" else label
            rows.append((rank, label.casefold(), tag, count, display))
        rows.sort(key=lambda row: (row[0], row[1], row[2]))
        self._tag_browser_rows = [(tag, count, display) for _rank, _label, tag, count, display in rows]
        live_count = sum(tag.startswith(ableton_tags.CACHE_PREFIX) for tag, _count in tags)
        self.tag_browser_status.configure(
            text=f"{len(rows):,} tags; {live_count:,} manual Live.\n"
            + ("No manual Live assignments in these results." if not live_count else "Counts follow search / collection.")
        )
        if not rows:
            self.tag_list.insert("end", NO_TAGS_LABEL)
            return
        self._insert_tag_batch(self._tag_browser_rows, 0, self._tag_render_generation)

    def _insert_tag_batch(self, tags, start, generation):
        if generation != self._tag_render_generation:
            return
        batch_end = min(start + 250, len(tags))
        for _tag, count, display in tags[start:batch_end]:
            self.tag_list.insert("end", f"{display}  ({count})")
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
            for index, (tag, _count, _display) in enumerate(tags):
                if tag.lower() == self.active_tag_filter.lower():
                    self.tag_list.selection_set(index)
                    self.tag_list.see(index)
                    break

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
        self._apply_browser_tag_index(index)

    def _apply_browser_tag_index(self, index):
        if index < len(self._tag_browser_rows):
            self._apply_tag_filter(self._tag_browser_rows[index][0], exact=True)

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
        self._apply_browser_tag_index(selection[0])

    def _apply_tag_filter(self, value, exact=False):
        self.stop_sound()
        self.active_tag_filter = value if exact else value.rsplit("  (", 1)[0]
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
            messagebox.showerror("Library", str(error))

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
            messagebox.showerror("Library", str(error))

    def _set_status(self, text):
        if self.status_label_ref:
            self.status_label_ref.config(
                text=f" Application Status: {text}",
                fg=gui_theme.THEME["accent_gold"]
            )

    def _show_selected_asset(self, selection_summary=None):
        paths = sorted(self._selection_paths)
        self.assigned_tags_text.configure(state="normal")
        self.assigned_tags_text.delete("1.0", "end")
        self.assigned_tags_text.insert(
            "end", "Loading assigned tags..." if paths else "Select sounds to see their assigned tags."
        )
        self.assigned_tags_text.configure(state="disabled")
        off_page = len(self._selection_paths - set(self._asset_paths.values()))
        self.selection_count_var.set(
            f"{len(paths):,} sound{'s' if len(paths) != 1 else ''} selected"
            + (f" ({off_page:,} off page)" if off_page else "")
            if paths else "No sounds selected"
        )
        state = "normal" if paths else "disabled"
        for control in (
            self.favorite_button, self.unfavorite_button
        ):
            control.configure(state=state)
        live_state = (
            "normal" if paths and self._live_refresh_queue is None and self._metadata_queue is None
            and self._live_batch_dialog is None else "disabled"
        )
        self.edit_live_tags_button.configure(state=live_state)
        try:
            if selection_summary is None and len(paths) > 500:
                self.selected_asset_var.set(f"{len(paths):,} sounds selected")
                self.selected_tags_var.set("Loading selection tags in the background. You can clear or change selection.")
                for control in (
                    self.favorite_button, self.unfavorite_button,
                    self.play_button, self.autoplay_check, self.edit_live_tags_button
                ):
                    control.configure(state="disabled")
                self.stop_sound()
                self._waveform_generation += 1
                self.waveform_canvas.delete("all")
                if self._selection_summary_queue is None:
                    results = queue.Queue()
                    self._selection_summary_queue = results
                    revision = self._selection_revision
                    scope = self._current_selection_scope()
                    def worker():
                        try:
                            result = sorter_engine.summarize_asset_selection(paths)
                        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                            results.put(error)
                        else:
                            results.put(result)
                    threading.Thread(target=worker, daemon=True).start()
                    self.after(30, self._finish_selection_summary, paths, revision, scope)
                return
            if isinstance(selection_summary, Exception):
                raise selection_summary
            summary = selection_summary if selection_summary is not None else sorter_engine.summarize_asset_selection(paths)
            lines = []
            for label, counts in (
                ("Generated (search / classification)", summary["generated_counts"]),
                ("Manual Live (shared with Ableton)", summary["live_counts"]),
            ):
                lines.append(label)
                lines.extend(
                    f"{' > '.join(tag.split('|'))}"
                    + (f" ({count:,}/{len(paths):,})" if len(paths) > 1 else "")
                    for tag, count in sorted(counts.items())
                )
                if not counts:
                    lines.append("None")
                lines.append("")
            self.assigned_tags_text.configure(state="normal")
            self.assigned_tags_text.delete("1.0", "end")
            self.assigned_tags_text.insert(
                "end", "\n".join(lines) if paths else "Select sounds to see their assigned tags."
            )
            self.assigned_tags_text.configure(state="disabled")
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            for control in (
                self.favorite_button,
                self.unfavorite_button, self.play_button,
                self.edit_live_tags_button
            ):
                control.configure(state="disabled")
            self.selected_asset_var.set("Selection is out of date")
            self.selected_tags_var.set("Clear selection or rescan the Library before editing.")
            self.assigned_tags_text.configure(state="normal")
            self.assigned_tags_text.delete("1.0", "end")
            self.assigned_tags_text.insert("end", "Assignments unavailable: selection is out of date.")
            self.assigned_tags_text.configure(state="disabled")
            self._set_status(f"Live tag summary unavailable: {error}")
            return
        self.play_button.configure(state="normal" if len(paths) == 1 else "disabled")
        self.autoplay_check.configure(state="disabled")
        self._waveform_generation += 1
        self.waveform_canvas.delete("all")
        if not paths:
            self.selected_asset_var.set("No sound selected")
            self.selected_tags_var.set(
                "Select a sound to inspect it.\n"
                "Shift/Ctrl (Command on Mac): select several."
            )
            self.favorite_button.configure(text="Favorite selected")
            return
        if len(paths) > 1:
            self.stop_sound()
            self.selected_asset_var.set(f"{len(paths):,} sounds selected")
            self.selected_tags_var.set(
                "Tag and favorite actions apply to every selected sound. "
                "Playback is available for a single sound."
            )
            self.favorite_button.configure(text="Favorite selected")
            return
        path = paths[0]
        record = sorter_engine.get_indexed_asset(path)
        if record is None:
            self.selected_asset_var.set("No sound selected")
            self.selected_tags_var.set("The selected sound is no longer indexed.")
            self.favorite_button.configure(text="☆ Favorite")
            return
        self.selected_asset_var.set(record["filename"])
        folder = os.path.relpath(os.path.dirname(path), gui_theme.USER_LIBRARY_PATH)
        self.selected_tags_var.set(
            f"Folder: {'User Library' if folder == '.' else folder}"
        )
        self.favorite_button.configure(
            text="★ Favorite" if "favorite" in record["tags"] else "☆ Favorite"
        )
        self._draw_waveform(path)
        is_midi = os.path.splitext(path)[1].lower() in (".mid", ".midi")
        self.autoplay_check.configure(state="disabled" if is_midi else "normal")
        if self.autoplay_var.get() and not is_midi:
            try:
                self._play_sound(path)
            except (OSError, ValueError):
                pass

    def _finish_selection_summary(self, paths, revision, scope):
        if self._selection_summary_queue is None:
            return
        try:
            summary = self._selection_summary_queue.get_nowait()
        except queue.Empty:
            self.after(30, self._finish_selection_summary, paths, revision, scope)
            return
        self._selection_summary_queue = None
        if (
            revision != self._selection_revision
            or scope != self._current_selection_scope()
            or set(paths) != self._selection_paths
        ):
            self._show_selected_asset()
            return
        self._show_selected_asset(selection_summary=summary)

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
            paths = self._selected_paths()
            if len(paths) > 1:
                self._update_selected_tag("favorite")
                return
            path = self._selected_path()
            record = sorter_engine.get_indexed_asset(path)
            if record is None:
                raise ValueError("The selected sound is no longer indexed.")
            if not self._update_selected_tag("favorite", remove="favorite" in record["tags"]):
                return
            if self.status_label_ref:
                self.status_label_ref.config(
                    text=" Application Status: Favorite updated.",
                    fg=gui_theme.THEME["accent_neon"]
                )
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Favorite Update Failed", str(error))

    def _selected_path(self):
        paths = self._selected_paths()
        if len(paths) != 1:
            raise ValueError("Select exactly one sound for playback or details.")
        return paths[0]

    def _selected_paths(self):
        self._capture_page_selection()
        paths = sorted(self._selection_paths)
        if not paths:
            raise ValueError("Select at least one indexed sound.")
        return paths

    def _current_selection_scope(self):
        return (
            gui_theme.USER_LIBRARY_PATH, self.search_var.get(),
            self.active_tag_filter, self.favorites_only, self._active_collection
        )

    def _capture_page_selection(self):
        visible = set(self._asset_paths.values())
        selected = {
            self._asset_paths[item] for item in self.asset_tree.selection()
            if item in self._asset_paths
        }
        updated = (self._selection_paths - visible) | selected
        if updated != self._selection_paths:
            self._selection_paths = updated
            self._selection_revision += 1

    def _page_selection_changed(self, _event=None):
        revision = self._selection_revision
        self._capture_page_selection()
        if revision != self._selection_revision:
            self._show_selected_asset()

    def _select_page(self):
        items = tuple(self._asset_paths)
        if set(self.asset_tree.selection()) == set(items):
            return
        self.asset_tree.selection_set(items)
        self._page_selection_changed()

    def _clear_selection(self):
        self._selection_paths.clear()
        self._selection_revision += 1
        self.asset_tree.selection_remove(self.asset_tree.selection())
        self._show_selected_asset()

    def _select_all_matching(self):
        if self._select_all_queue is not None:
            return
        self._capture_page_selection()
        scope = self._current_selection_scope()
        revision = self._selection_revision
        root, search, tag, favorites, collection = scope
        type_query = {"Loops": "type:loop", "One-shots": "type:one-shot", "MIDI": "type:midi"}
        search = f"{search} {type_query.get(collection, '')}".strip()
        results = queue.Queue()
        self._select_all_queue = results
        self._set_status("Capturing all matching sounds for selection...")
        def worker():
            try:
                paths = sorter_engine.list_indexed_assets(
                    search, tag, favorites, library_root=root, limit=-1, paths_only=True
                )
            except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
                results.put((None, error))
            else:
                results.put((paths, None))
        threading.Thread(target=worker, daemon=True).start()
        self.after(30, self._finish_select_all, scope, revision)

    def _finish_select_all(self, scope, revision):
        try:
            paths, error = self._select_all_queue.get_nowait()
        except queue.Empty:
            self.after(30, self._finish_select_all, scope, revision)
            return
        self._select_all_queue = None
        self._capture_page_selection()
        if error is not None:
            messagebox.showerror("Selection Failed", str(error))
            return
        if scope != self._current_selection_scope() or revision != self._selection_revision:
            self._set_status("Select all cancelled because filters or selection changed.")
            return
        self._selection_scope = scope
        self._selection_paths = set(paths)
        self._selection_revision += 1
        self.asset_tree.selection_set(tuple(
            item for item, path in self._asset_paths.items() if path in self._selection_paths
        ))
        self._show_selected_asset()
        self._set_status(f"Captured {len(paths):,} matching sounds. Changing filters clears selection.")


    def bulk_remove_favorite(self):
        try:
            self._update_selected_tag("favorite", remove=True)
        except (OSError, ValueError, sorter_engine.sqlite3.Error) as error:
            messagebox.showerror("Favorite Update Failed", str(error))

    def _update_selected_tag(self, tag, remove=False):
        paths = self._selected_paths()
        normalized_tag = tag.strip().lower()
        if normalized_tag != "favorite":
            raise ValueError("App-only tags have been removed. Use Edit Live tags instead.")
        off_page = len(set(paths) - set(self._asset_paths.values()))
        if off_page and not ask_confirm(
            self.winfo_toplevel(), "Update captured selection",
            f"{'Remove' if remove else 'Apply'} favorite "
            f"for {len(paths):,} selected sounds, including {off_page:,} off the current page.\n"
            "This changes favorites only, not Live tags.",
            "Update selected"
        ):
            return False
        sorter_engine.bulk_update_asset_tags(paths, normalized_tag, remove=remove)
        self._render_results(refresh_sidebar=True)
        self._set_status(
            f"Tag '{normalized_tag}' {'removed from' if remove else 'applied to'} "
            f"{len(paths):,} sound{'s' if len(paths) != 1 else ''}."
        )
        return True

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
        if record["ableton_tags"]:
            details += "\n\nLive tags (read-only):\n" + "\n".join(record["ableton_tags"])
        details += "\n\nFolder advice (review only)\n" + tag_evidence.describe_library_evidence(
            path, gui_theme.USER_LIBRARY_PATH, record["ableton_tags"]
        )
        details_frame = tk.Frame(dialog, bg=theme["bg_field"])
        details_frame.pack(fill="both", expand=True, padx=18, pady=8)
        details_scroll = ttk.Scrollbar(details_frame)
        details_scroll.pack(side="right", fill="y")
        self.sound_details_text = tk.Text(
            details_frame, height=6, wrap="word", font=("Segoe UI", 9),
            bg=theme["bg_field"], fg=theme["fg_light"], bd=0,
            yscrollcommand=details_scroll.set
        )
        self.sound_details_text.pack(fill="both", expand=True)
        details_scroll.configure(command=self.sound_details_text.yview)
        self.sound_details_text.insert("1.0", details)
        self.sound_details_text.configure(state="disabled")

        tk.Label(
            dialog, text="Generated search tags — click to enable or disable:",
            font=("Segoe UI", 9, "bold"), bg=theme["bg_dark"],
            fg=theme["fg_light"], anchor="w"
        ).pack(fill="x", padx=18, pady=(2, 4))
        tag_buttons = tk.Frame(dialog, bg=theme["bg_dark"])
        tag_buttons.pack(fill="x", padx=18, pady=(0, 10))
        all_tags = sorted(
            tag for tag in set(record["tags"]) | set(record.get("disabled_tags", []))
            if tag.startswith("name:")
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

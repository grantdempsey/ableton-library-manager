# tab_matrix.py - Core Automation Logic, Profile Portability Engines & Layout Matrix Assemblies
import tkinter as tk
from tkinter import ttk, filedialog
import re
import os
import json
import datetime
import sorter_engine
import gui_theme
import rule_suggester
import threading
import webbrowser

_drum_tree = None
_synth_tree = None
_status_label_ref = None
_candidate_tree = None
_loop_path_label = None
_auto_suggest_ref = None
def refresh_matrix_data():
    """Distributes dictionary rule matrices out cleanly to their respective table grids."""
    if _drum_tree is not None:
        _drum_tree.delete(*_drum_tree.get_children())
        ordered_patterns = sorter_engine._ordered_rule_patterns({
            "DRUM_KEYWORDS": sorter_engine.DRUM_KEYWORDS,
            "RULE_METADATA": sorter_engine.RULE_METADATA,
        })
        try:
            shadowed = sorter_engine.find_shadowed_rules()
        except Exception:
            shadowed = {}
        for pat in ordered_patterns:
            fld = sorter_engine.DRUM_KEYWORDS[pat]
            metadata = sorter_engine.RULE_METADATA.get(pat, {})
            if not metadata.get("enabled", True):
                state = "Disabled"
            elif pat in shadowed:
                state = "Never wins"
            else:
                state = "Enabled"
            _drum_tree.insert(
                '', 'end',
                values=(pat, fld, metadata.get("priority", 0), state),
                tags=("shadowed",) if state == "Never wins" else ()
            )
        _drum_tree.tag_configure("shadowed", foreground="#ffa94d")
            
    if _synth_tree is not None:
        _synth_tree.delete(*_synth_tree.get_children())
        for pat, fld in sorter_engine.SYNTH_EXTS.items():
            _synth_tree.insert('', 'end', values=(pat, fld))
        for pat, fld in sorter_engine.NATIVE_EXTS.items():
            _synth_tree.insert('', 'end', values=(pat, fld))
    if _candidate_tree is not None:
        _candidate_tree.delete(*_candidate_tree.get_children())
        ordered = sorted(sorter_engine.LEARNED_RULE_CANDIDATES,
                         key=lambda c: (-int(c.get("count", 0) or 0), c.get("token", "")))
        for candidate in ordered:
            if candidate.get("status", "pending") == "pending":
                try:
                    placement = sorter_engine.suggest_rule_priority(
                        candidate.get("pattern", ""), candidate.get("target", ""))
                    priority = f"{placement['total'] - placement['position'] + 1} of {placement['total']}"
                except (re.error, ValueError):
                    priority = "-"
                _candidate_tree.insert(
                    '', 'end',
                    values=(candidate.get("token", ""), candidate.get("target", ""), priority,
                            candidate.get("count", 0), candidate.get("pattern", ""))
                )

def _sync_config_state(status_msg):
    """Safely dumps data mappings down onto physical local config file layouts."""
    try:
        disk_data = {}
        if os.path.exists(sorter_engine.CONFIG_FILE):
            with open(sorter_engine.CONFIG_FILE, 'r', encoding='utf-8') as f:
                disk_data = json.load(f)
        
        disk_data["DRUM_KEYWORDS"] = sorter_engine.DRUM_KEYWORDS
        disk_data["SYNTH_EXTS"] = sorter_engine.SYNTH_EXTS
        disk_data["NATIVE_EXTS"] = sorter_engine.NATIVE_EXTS
        disk_data["LOOP_LAYOUT"] = list(sorter_engine.LOOP_LAYOUT)
        if hasattr(sorter_engine, 'IGNORED_DIRECTORIES'):
            disk_data["IGNORED_DIRECTORIES"] = sorter_engine.IGNORED_DIRECTORIES
            
        sorter_engine.backup_config()
        with open(sorter_engine.CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(disk_data, f, indent=4)

        sorter_engine.load_external_config()
        refresh_matrix_data()
        if _status_label_ref:
            _status_label_ref.config(text=f" Application Status: {status_msg}", fg=gui_theme.THEME["accent_neon"])
    except Exception as e:
        messagebox.showerror("Sync Failure", f"Could not commit parameters script: {str(e)}")

# tab_matrix.py - Piece 2: Workspace Serialization Portability Engines (Import/Export)
def execute_profile_json_export(parent_window):
    """Packages and dumps custom studio sorting dictionaries directly inside the User Library."""
    # 🌟 FIXED CROSS-PLATFORM ROUTING: Dynamically tracks studio paths to stay immune to Mac tracebacks
    user_library_default_route = gui_theme.USER_LIBRARY_PATH
    
    target_filepath = filedialog.asksaveasfilename(
        title="Export Studio Workspace Profile JSON",
        initialdir=user_library_default_route if os.path.exists(user_library_default_route) else None,
        initialfile="ableton_studio_profile.json",
        defaultextension=".json",
        filetypes=[("JSON Profile Configurations", "*.json")]
    )
    if not target_filepath:
        return

    try:
        profile_package = {
            "profile_identity": "AFC_Production_Workspace",
            "export_timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "DRUM_KEYWORDS": sorter_engine.DRUM_KEYWORDS,
            "SYNTH_EXTS": sorter_engine.SYNTH_EXTS,
            "NATIVE_EXTS": sorter_engine.NATIVE_EXTS,
            "IGNORED_DIRECTORIES": getattr(sorter_engine, 'IGNORED_DIRECTORIES', ["No Key Info"])
        }
        
        with open(target_filepath, 'w', encoding='utf-8') as f:
            json.dump(profile_package, f, indent=4)
            
        if _status_label_ref:
            _status_label_ref.config(text=" Application Status: Studio configuration profile exported cleanly!", fg=gui_theme.THEME["accent_gold"])
        messagebox.showinfo("Export Successful", f"Workspace taxonomy definitions logged to location:\n{os.path.basename(target_filepath)}")
    except Exception as e:
        messagebox.showerror("Export Failed", f"Could not package profile file system tracks: {str(e)}")

def execute_profile_json_import(parent_window):
    """Ingests external configuration profiles directly out of the User Library to restore rule parameters."""
    # 🌟 FIXED CROSS-PLATFORM ROUTING: Dynamically tracks studio paths to stay immune to Mac tracebacks
    user_library_default_route = gui_theme.USER_LIBRARY_PATH
    
    target_filepath = filedialog.askopenfilename(
        title="Import Studio Workspace Profile JSON",
        initialdir=user_library_default_route if os.path.exists(user_library_default_route) else None,
        filetypes=[("JSON Profile Configurations", "*.json")]
    )
    if not target_filepath:
        return

    try:
        with open(target_filepath, 'r', encoding='utf-8') as f:
            imported_package = json.load(f)

        if not any(k in imported_package for k in ["DRUM_KEYWORDS", "SYNTH_EXTS", "NATIVE_EXTS"]):
            messagebox.showerror("Parsing Failure", "Selected file lacks valid rule matrix dictionaries or pattern fields.")
            return

        confirm_overwrite = messagebox.askyesno(
            "Confirm Workspace Import",
            "Importing this profile will merge or overwrite your current taxonomy rules.\n\n"
            "Do you want to proceed with rule array synchronization?",
            icon="warning"
        )
        if not confirm_overwrite:
            return

        if "DRUM_KEYWORDS" in imported_package:
            sorter_engine.DRUM_KEYWORDS.update(imported_package["DRUM_KEYWORDS"])
        if "SYNTH_EXTS" in imported_package:
            sorter_engine.SYNTH_EXTS.update(imported_package["SYNTH_EXTS"])
        if "NATIVE_EXTS" in imported_package:
            sorter_engine.NATIVE_EXTS.update(imported_package["NATIVE_EXTS"])
        if "IGNORED_DIRECTORIES" in imported_package:
            current_ignored = set(getattr(sorter_engine, 'IGNORED_DIRECTORIES', []))
            current_ignored.update(imported_package["IGNORED_DIRECTORIES"])
            setattr(sorter_engine, 'IGNORED_DIRECTORIES', sorted(list(current_ignored)))

        _sync_config_state("Workspace parameters reconstructed and synchronized clean!")
        messagebox.showinfo("Import Complete", "Studio profile ingested successfully! Grid ledgers updated.")
    except Exception as e:
        messagebox.showerror("Import Failed", f"Could not ingest configuration script data: {str(e)}")

# Function 1: Window Generation and Geometry Target Anchoring
def _center_over(win, anchor):
    win.update_idletasks()
    anchor.update_idletasks()
    x = anchor.winfo_rootx() + (anchor.winfo_width() - win.winfo_reqwidth()) // 2
    y = anchor.winfo_rooty() + (anchor.winfo_height() - win.winfo_reqheight()) // 2
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")


def themed_dialog(anchor, title, message, buttons, default=None, heading=None, cards=None):
    """Modal dialog centered over `anchor`. `buttons` is a list of (label, value); returns the chosen value."""
    theme = gui_theme.THEME
    dialog = tk.Toplevel(anchor)
    dialog.title(title)
    dialog.configure(bg=theme["bg_dark"])
    dialog.transient(anchor.winfo_toplevel())
    dialog.resizable(False, False)
    result = {"value": default}

    def choose(value):
        result["value"] = value
        dialog.destroy()

    if heading:
        tk.Label(dialog, text=heading, font=("Segoe UI", 12, "bold"), bg=theme["bg_dark"],
                 fg=theme["accent_neon"], anchor="w", wraplength=440, justify="left"
                 ).pack(fill="x", padx=20, pady=(16, 4))
    tk.Label(dialog, text=message, font=("Segoe UI", 10), bg=theme["bg_dark"], fg=theme["fg_light"],
             anchor="w", wraplength=440, justify="left").pack(fill="x", padx=20, pady=(8 if not heading else 0, 10))
    for card in cards or []:
        box = tk.Frame(dialog, bg=theme["bg_field"], padx=10, pady=8)
        box.pack(fill="x", padx=20, pady=(0, 8))
        tk.Label(box, text=card[0], font=("Segoe UI", 10, "bold"), bg=theme["bg_field"],
                 fg=theme["fg_light"], anchor="w", wraplength=420, justify="left").pack(fill="x")
        tk.Label(box, text=card[1], font=("Segoe UI", 9), bg=theme["bg_field"],
                 fg=theme["fg_muted"], anchor="w", wraplength=420, justify="left").pack(fill="x", pady=(4, 0))
    row = tk.Frame(dialog, bg=theme["bg_dark"])
    row.pack(fill="x", padx=20, pady=(6, 16))
    for index, (label, value) in enumerate(reversed(buttons)):
        primary = value is True or len(buttons) == 1
        tk.Button(
            row, text=label, command=lambda v=value: choose(v), width=12, height=1,
            bg=theme["btn_primary"] if primary else theme["btn_secondary"],
            fg=theme["btn_primary_fg"] if primary else theme["fg_light"], bd=0, font=("Segoe UI", 9, "bold")
        ).pack(side="right", padx=(8, 0))
    dialog.protocol("WM_DELETE_WINDOW", lambda: choose(default))
    dialog.bind("<Escape>", lambda _e: choose(default))
    _center_over(dialog, anchor)
    dialog.grab_set()
    dialog.focus_set()
    dialog.wait_window()
    return result["value"]


def plain_rule_name(pattern):
    """Readable text for a rule pattern, e.g. '\\bkick(s)?\\b' -> 'kick(s)'."""
    core = pattern.replace("(?:^|[^a-zA-Z0-9])", "").replace("(?:$|[^a-zA-Z0-9])", "").replace("\\b", "")
    core = re.sub(r"\(\?:([^)]*)\)", r"(\1)", core).replace("\\s*", " ").replace(")?", ")")
    return core.strip() or pattern


def open_filename_tester(anchor):
    """Small window: type a filename and see which rule would sort it."""
    theme = gui_theme.THEME
    win = tk.Toplevel(anchor)
    win.title("Test a filename")
    win.configure(bg=theme["bg_dark"])
    win.transient(anchor.winfo_toplevel())
    win.resizable(False, False)
    tk.Label(win, text="Test a filename", font=("Segoe UI", 12, "bold"), bg=theme["bg_dark"],
             fg=theme["accent_neon"]).pack(anchor="w", padx=20, pady=(16, 2))
    tk.Label(win, text="Type or paste a file name to see where your rules would send it. Nothing is moved.",
             font=("Segoe UI", 9), bg=theme["bg_dark"], fg=theme["fg_muted"], wraplength=420,
             justify="left").pack(anchor="w", padx=20, pady=(0, 8))
    var = tk.StringVar()
    entry = tk.Entry(win, textvariable=var, width=54, bg=theme["bg_field"], fg=theme["fg_light"],
                     insertbackground=theme["fg_light"], bd=0, highlightthickness=1,
                     font=("Segoe UI", 10))
    entry.pack(padx=20, ipady=5)
    output = tk.Label(win, text="", font=("Segoe UI", 10), bg=theme["bg_field"], fg=theme["fg_light"],
                      wraplength=420, justify="left", anchor="nw", padx=10, pady=8, height=10, width=60)
    output.pack(fill="x", padx=20, pady=12)

    def update(*_):
        name = var.get().strip()
        if not name:
            output.config(text="Result appears here as you type.")
            return
        info = sorter_engine.explain_filename(name)
        lines = []
        if info["file_type"]:
            ext, folder = info["file_type"]
            lines.append(f"File type rule: {ext} files go to '{folder}'.")
        elif info["winner"]:
            lines.append(f"Goes to: {info['destination']}")
            lines.append(f"Winning rule: {plain_rule_name(info['winner'][0])}")
            if info["others"]:
                lines.append("")
                lines.append("Also matched, but lower priority:")
                lines += [f"   {plain_rule_name(p)}  ->  {f}" for p, f in info["others"][:6]]
        else:
            lines.append("No rule matches this name. It would be left for the metadata/tag checks or stay unsorted.")
        if info["excluded"]:
            lines.append("")
            lines.append("Skipped because of an exclusion:")
            lines += [f"   {plain_rule_name(p)}  ->  {f}" for p, f in info["excluded"][:6]]
        output.config(text="\n".join(lines))

    var.trace_add("write", update)
    update()
    row = tk.Frame(win, bg=theme["bg_dark"])
    row.pack(fill="x", padx=20, pady=(0, 16))
    tk.Button(row, text="Close", width=12, command=win.destroy, bg=theme["btn_secondary"],
              fg=theme["fg_light"], bd=0, font=("Segoe UI", 9, "bold")).pack(side="right")
    win.bind("<Escape>", lambda _e: win.destroy())
    _center_over(win, anchor)
    entry.focus_set()


def open_loop_layout(anchor, library):
    """Pick which folder levels loops are filed into, and in what order."""
    theme = gui_theme.THEME
    names = {"bpm": "Tempo (BPM range)", "key": "Musical key"}
    samples = {"bpm": "100-114 BPM", "key": "AMIN"}
    win = tk.Toplevel(anchor)
    win.title("Loop folder layout")
    win.configure(bg=theme["bg_dark"])
    win.transient(anchor.winfo_toplevel())
    win.resizable(False, False)
    current = list(sorter_engine.LOOP_LAYOUT)
    state = {"levels": [[level, True] for level in current]
             + [[level, False] for level in sorter_engine.LOOP_LEVELS if level not in current],
             "recommended": None}

    def label(text, font=("Segoe UI", 9), fg=None, **pack):
        widget = tk.Label(win, text=text, font=font, bg=theme["bg_dark"], fg=fg or theme["fg_muted"],
                          wraplength=460, justify="left", anchor="w")
        widget.pack(fill="x", padx=20, **pack)
        return widget

    label("Loop folder layout", ("Segoe UI", 12, "bold"), theme["accent_neon"], pady=(16, 2))
    label("Loops are filed into nested folders. Put the broadest level first and the most specific last, "
          "so you narrow down as you open folders. Untick a level to skip it.", pady=(0, 8))
    advice = label("Checking your library for a recommendation...", fg=theme["fg_light"], pady=(0, 8))
    rows = tk.Frame(win, bg=theme["bg_field"])
    rows.pack(fill="x", padx=20)
    example = label("", font=("Consolas", 9), fg=theme["accent_gold"], pady=(10, 2))
    message = label("", fg=theme["fg_light"], pady=(0, 4))

    def enabled_layout():
        return [level for level, on in state["levels"] if on]

    def render():
        for child in rows.winfo_children():
            child.destroy()
        for index, (level, on) in enumerate(state["levels"]):
            row = tk.Frame(rows, bg=theme["bg_field"])
            row.pack(fill="x", padx=8, pady=3)
            var = tk.BooleanVar(value=on)

            def toggle(i=index, v=var):
                state["levels"][i][1] = v.get()
                render()

            tk.Checkbutton(row, text=f"{index + 1}.  {names[level]}", variable=var, command=toggle,
                           bg=theme["bg_field"], fg=theme["fg_light"], selectcolor=theme["bg_dark"],
                           activebackground=theme["bg_field"], activeforeground=theme["fg_light"],
                           font=("Segoe UI", 10), anchor="w").pack(side="left")
            for text, delta in (("▼", 1), ("▲", -1)):
                target = index + delta
                tk.Button(row, text=text, width=3, bd=0, bg=theme["btn_secondary"], fg=theme["fg_light"],
                          state="normal" if 0 <= target < len(state["levels"]) else "disabled",
                          command=lambda i=index, t=target: move(i, t)).pack(side="right", padx=(4, 0))
        parts = ["Samples", "Loops"] + [samples[level] for level in enabled_layout()] + ["My Loop 105 BPM Amin.wav"]
        example.config(text="Example:  " + "\\".join(parts))

    def move(index, target):
        state["levels"][index], state["levels"][target] = state["levels"][target], state["levels"][index]
        message.config(text="")
        render()

    def describe(result):
        stats = result["stats"]
        if not result["loops"]:
            return "No loops found yet, so Tempo then Key is suggested."
        lines = [f"Recommended: {' then '.join(names[l] for l in result['layout']) or 'no sub-folders'}."]
        for level in sorter_engine.LOOP_LEVELS:
            info = stats[level]
            percent = round(info["coverage"] * 100)
            if level in result["layout"]:
                lines.append(f"{names[level]}: {percent}% of your {result['loops']:,} loops have one "
                             f"({info['folders']} folders).")
            else:
                lines.append(f"{names[level]} left out: only {percent}% of loops have one, so most would "
                             "pile into a 'No Key Info' or 'Unsorted' folder.")
        if len(result["layout"]) > 1:
            lines.append("Fewest folders first keeps the top level short and lets the detailed level sit last.")
        return "\n".join(lines)

    def apply_recommendation():
        result = state["recommended"]
        if not result:
            return
        chosen = result["layout"]
        state["levels"] = [[level, True] for level in chosen] + \
                          [[level, False] for level in sorter_engine.LOOP_LEVELS if level not in chosen]
        message.config(text="Recommended layout selected. Click Save to keep it.")
        render()

    def save():
        layout = enabled_layout()
        sorter_engine.LOOP_LAYOUT = layout
        _sync_config_state("Loop layout saved: " + (" > ".join(names[l] for l in layout) or "no sub-folders"))
        message.config(text="Saved. Run Organize (use Preview first) to apply it to existing loops. "
                            "Folders you created yourself are left alone.")

    render()
    row = tk.Frame(win, bg=theme["bg_dark"])
    row.pack(fill="x", padx=20, pady=(6, 16))
    tk.Button(row, text="Close", width=10, command=win.destroy, bg=theme["btn_secondary"],
              fg=theme["fg_light"], bd=0, font=("Segoe UI", 9, "bold")).pack(side="right")
    tk.Button(row, text="Save", width=10, command=save, bg=theme["btn_primary"],
              fg=theme["btn_primary_fg"], bd=0, font=("Segoe UI", 9, "bold")).pack(side="right", padx=8)
    recommend_button = tk.Button(row, text="Use recommended", command=apply_recommendation, state="disabled",
                                 bg=theme["tag_enabled"], fg="white", activebackground=theme["tag_enabled"],
                                 activeforeground="white", bd=0, font=("Segoe UI", 9, "bold"), padx=10, pady=3)
    recommend_button.pack(side="left")

    result = {}

    def work():
        result["value"] = sorter_engine.recommend_loop_layout(library)

    def poll():
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        if thread.is_alive():
            win.after(150, poll)
            return
        state["recommended"] = result["value"]
        advice.config(text=describe(result["value"]))
        recommend_button.config(state="normal")
        _center_over(win, anchor)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    win.after(150, poll)
    win.bind("<Escape>", lambda _e: win.destroy())
    _center_over(win, anchor)
    return win


def _loop_path_text():
    labels = {"bpm": "<BPM range>", "key": "<Key>"}
    parts = [labels[level] for level in sorter_engine.LOOP_LAYOUT if level in labels]
    return "Samples\\Loops\\" + "\\".join(parts) if parts else "Samples\\Loops"


def ask_confirm(anchor, title, message, yes_text="Yes"):
    return bool(themed_dialog(anchor, title, message, [("Cancel", False), (yes_text, True)], default=False))


def ask_confirm_cards(anchor, title, message, yes_text, cards):
    return bool(themed_dialog(anchor, title, message, [("Cancel", False), (yes_text, True)],
                              default=False, cards=cards))


def show_notice(anchor, title, message, heading=None, cards=None):
    themed_dialog(anchor, title, message, [("OK", None)], heading=heading, cards=cards)


_advanced_popup = {"window": None}


def _default_anchor():
    popup = _advanced_popup["window"]
    try:
        if popup is not None and popup.winfo_exists():
            return popup
    except tk.TclError:
        pass
    return tk._default_root


class _ThemedMessageBox:
    """Drop-in for tkinter.messagebox that shows themed dialogs centered over the Advanced popup or the app."""

    @staticmethod
    def _notice(title, message, **_kwargs):
        show_notice(_default_anchor(), title, message)

    showinfo = showwarning = showerror = _notice

    @staticmethod
    def askyesno(title, message, **_kwargs):
        return ask_confirm(_default_anchor(), title, message)


messagebox = _ThemedMessageBox()


def ask_fields(anchor, title, message, labels):
    """Modal form centered over `anchor`; returns a list of entered strings or None if cancelled."""
    theme = gui_theme.THEME
    dialog = tk.Toplevel(anchor)
    dialog.title(title)
    dialog.configure(bg=theme["bg_dark"])
    dialog.transient(anchor.winfo_toplevel())
    dialog.resizable(False, False)
    result = {"value": None}
    entries = []
    tk.Label(dialog, text=message, font=("Segoe UI", 10), bg=theme["bg_dark"], fg=theme["fg_light"],
             anchor="w", wraplength=380, justify="left").pack(fill="x", padx=20, pady=(16, 8))
    for label in labels:
        tk.Label(dialog, text=label, font=("Segoe UI", 9, "bold"), bg=theme["bg_dark"],
                 fg=theme["fg_muted"], anchor="w").pack(fill="x", padx=20)
        entry = tk.Entry(dialog, font=("Segoe UI", 10), bg=theme["bg_field"], fg=theme["fg_light"],
                         insertbackground=theme["fg_light"], bd=0, relief="flat")
        entry.pack(fill="x", padx=20, pady=(2, 8), ipady=4)
        entries.append(entry)

    def submit():
        result["value"] = [e.get().strip() for e in entries]
        dialog.destroy()

    row = tk.Frame(dialog, bg=theme["bg_dark"])
    row.pack(fill="x", padx=20, pady=(6, 16))
    tk.Button(row, text="Continue", command=submit, width=12, bg=theme["btn_primary"], fg=theme["btn_primary_fg"],
              bd=0, font=("Segoe UI", 9, "bold")).pack(side="right", padx=(8, 0))
    tk.Button(row, text="Cancel", command=dialog.destroy, width=12, bg=theme["btn_secondary"],
              fg=theme["fg_light"], bd=0, font=("Segoe UI", 9, "bold")).pack(side="right")
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    _center_over(dialog, anchor)
    dialog.grab_set()
    entries[0].focus_set()
    dialog.wait_window()
    return result["value"]


def launch_interactive_rule_builder(parent_win):
    """Spawns an interactive custom expression template generation dialog popup."""
    popup = tk.Toplevel(parent_win)
    popup.title("Create New Sorting Rule Wizard")
    popup.geometry("540x440")
    popup.resizable(False, False)
    popup.configure(bg=gui_theme.THEME["bg_dark"])
    popup.grab_set()

    # Calculate system display geometry states to center the canvas accurately
    popup.update_idletasks()
    master_top = parent_win._root()
    target_x = master_top.winfo_x() + int((master_top.winfo_width() - 540) / 2)
    target_y = master_top.winfo_y() + int((master_top.winfo_height() - 440) / 2)
    popup.geometry(f"540x440+{target_x}+{target_y}")

    # Initialize tracking variables for custom user entry overrides
    var_custom_regex = tk.BooleanVar(value=False)
    var_user_typed_folder = tk.BooleanVar(value=False)

    tk.Label(
        popup, text="Fill in the blanks to build your sorting rule:", 
        font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]
    ).pack(anchor="w", padx=20, pady=(20, 10))

    # Hand off window configurations down to individual field builders
    build_rule_input_matrix_fields(popup, var_custom_regex, var_user_typed_folder)

# Function 2: UI Form Construction and Component Generation Triggers
def build_rule_input_matrix_fields(popup, var_custom_regex, var_user_typed_folder):
    """Assembles layout forms and connects dynamic input elements to tracking loops."""
    f_conv = tk.Frame(popup, bg=gui_theme.THEME["bg_dark"])
    f_conv.pack(fill="x", padx=20, pady=5)

    lbl_prefix = tk.Label(f_conv, text="When file name contains the word:", font=("Segoe UI", 9), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"])
    lbl_prefix.grid(row=0, column=0, sticky="w", pady=6)
    
    ent_token = tk.Entry(f_conv, font=("Segoe UI", 9), bg=gui_theme.THEME["bg_field"], fg=gui_theme.THEME["fg_light"], insertbackground=gui_theme.THEME["fg_light"], bd=1, relief="solid", width=22)
    ent_token.grid(row=0, column=1, padx=8, sticky="w")
    ent_token.insert(0, "snare")

    tk.Label(f_conv, text="Move it into a subfolder named:", font=("Segoe UI", 9), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]).grid(row=1, column=0, sticky="w", pady=6)
    
    f_folder_input = tk.Frame(f_conv, bg=gui_theme.THEME["bg_dark"])
    f_folder_input.grid(row=1, column=1, padx=8, sticky="w")
    
    ent_fld = tk.Entry(f_folder_input, font=("Segoe UI", 9), bg=gui_theme.THEME["bg_field"], fg=gui_theme.THEME["fg_light"], insertbackground=gui_theme.THEME["fg_light"], bd=1, relief="solid", width=22)
    ent_fld.pack(side="left")
    ent_fld.insert(0, "Snares")

    lbl_hint = tk.Label(f_folder_input, text="(or type custom name)", font=("Segoe UI", 8, "italic"), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"])
    lbl_hint.pack(side="left", padx=6)

    # Wipe descriptive auto-text guides upon detecting immediate typing overrides
    ent_fld.bind("<Key>", lambda e: [var_user_typed_folder.set(True), lbl_hint.pack_forget()])

    tk.Label(f_conv, text="✨ Add to an existing sorting folder:", font=("Segoe UI", 9), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]).grid(row=2, column=0, sticky="w", pady=(14, 2))
    
    cb_existing = ttk.Combobox(f_conv, font=("Segoe UI", 9), state="readonly", width=20)
    existing_folders = sorted(list(set(sorter_engine.DRUM_KEYWORDS.values())))
    cb_existing['values'] = ["-- Select Active Folder --"] + existing_folders
    cb_existing.current(0)
    cb_existing.grid(row=2, column=1, padx=8, pady=(14, 2), sticky="w")

    # Forward configurations down to structural display calculators
    assemble_formula_preview_blocks(popup, f_conv, ent_token, ent_fld, cb_existing, lbl_prefix, lbl_hint, var_custom_regex, var_user_typed_folder)

# Function 3: Text Formula Analyzers and Live Validation Loops
def assemble_formula_preview_blocks(popup, f_conv, ent_token, ent_fld, cb_existing, lbl_prefix, lbl_hint, var_custom_regex, var_user_typed_folder):
    """Sets up the live regex code syntax visualizer block and links variable bindings."""
    f_toggle = tk.Frame(popup, bg=gui_theme.THEME["bg_dark"])
    f_toggle.pack(fill="x", padx=20, pady=(15, 0))

    lbl_preview_title = tk.Label(popup, text="Generated System Matching Formula Code:", font=("Segoe UI", 9, "bold"), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"])
    lbl_preview_title.pack(anchor="w", padx=20, pady=(15, 2))

    f_viz = tk.Frame(popup, bg=gui_theme.THEME["bg_field"], bd=1, relief="solid")
    f_viz.pack(fill="x", padx=20, pady=4)

    lbl_formula = tk.Label(f_viz, text="", font=("Consolas", 10, "bold"), bg=gui_theme.THEME["bg_field"], fg=gui_theme.THEME["accent_neon"], padx=10, pady=10, anchor="w")
    lbl_formula.pack(fill="x")

    def update_live_calculations(*args):
        if var_custom_regex.get(): return 
        tok = ent_token.get().strip()
        if not tok:
            if not var_user_typed_folder.get(): 
                ent_fld.delete(0, tk.END)
            lbl_formula.config(text="[Enter scan keyword above]")
            return
            
        if not var_user_typed_folder.get():
            suggested_fld = tok.title() + ('s' if not tok.title().endswith('s') else '')
            ent_fld.delete(0, tk.END)
            ent_fld.insert(0, suggested_fld)
            
        lbl_formula.config(text=f"\\b{tok.lower()}(s)?\\b")

    # Map menu select inputs to trigger appropriate recalculation sequences
    cb_existing.bind("<<ComboboxSelected>>", lambda e: [var_user_typed_folder.set(True), lbl_hint.pack_forget(), ent_fld.delete(0, tk.END), ent_fld.insert(0, cb_existing.get()), update_live_calculations()])

    def toggle_custom_mode():
        if var_custom_regex.get():
            cb_existing.config(state="disabled")
            lbl_prefix.config(text="Custom RegEx Expression:")
            lbl_formula.config(text="[Direct Entry Mode Active]")
            ent_token.delete(0, tk.END)
            ent_token.insert(0, "\\b(hi)?hat(s)?\\b")
        else:
            cb_existing.config(state="readonly")
            lbl_prefix.config(text="When file name contains the word:")
            ent_token.delete(0, tk.END)
            ent_token.insert(0, "kick")
            var_user_typed_folder.set(False)
            update_live_calculations()

    tk.Checkbutton(f_toggle, text="Use Manual/Custom RegEx Formula Mode", variable=var_custom_regex, command=toggle_custom_mode, bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"], selectcolor=gui_theme.THEME["bg_field"], font=("Segoe UI", 9, "italic")).pack(side="left")
    
    lbl_link = tk.Label(f_toggle, text="[Learn RegExr.com ↗]", font=("Segoe UI", 8, "underline"), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["accent_neon"], cursor="hand2")
    lbl_link.pack(side="left", padx=15)
    lbl_link.bind("<Button-1>", lambda e: webbrowser.open("https://regexr.com"))

    ent_token.bind("<KeyRelease>", update_live_calculations)
    update_live_calculations()

    # Pass the populated elements to the terminal controller actions row
    build_builder_action_buttons(popup, ent_token, ent_fld, lbl_formula, var_custom_regex)

# Function 4: Parameter Commit Handlers and Action Control Stacks
def build_builder_action_buttons(popup, ent_token, ent_fld, lbl_formula, var_custom_regex):
    """Attaches validation controls and execution buttons to finalize active settings imports."""
    btn_panel = tk.Frame(popup, bg=gui_theme.THEME["bg_dark"])
    btn_panel.pack(fill="x", side="bottom", padx=20, pady=20)
    
    tk.Button(
        btn_panel, text="Cancel", font=("Segoe UI", 9, "bold"), 
        bg=gui_theme.THEME["bg_panel"], fg=gui_theme.THEME["fg_light"], 
        bd=0, padx=18, pady=6, command=popup.destroy
    ).pack(side="left")
    
    def save_new_rule_action():
        f = ent_fld.get().strip()
        p = ent_token.get().strip() if var_custom_regex.get() else lbl_formula.cget("text")
        
        # Shield parameters against empty variables or missing setup values
        if not f or not p or p.startswith("["): 
            return
            
        try: 
            re.compile(p)
        except re.error: 
            messagebox.showerror("Expression Fault", "Provided string values contain syntax profile errors.")
            return
            
        try:
            placement_preview = sorter_engine.plan_rule_placement(p, f)
        except (ValueError, re.error):
            placement_preview = None
        question = f"Add a new rule that sends filenames matching\n{p}\ninto the folder '{f}'?"
        if placement_preview and placement_preview[1]:
            question += "\n\nIt will be ranked above a broader rule it would otherwise lose to."
        if not ask_confirm(popup, "Add this rule?", question, "Add rule"):
            return
        try:
            placement = sorter_engine.add_rule_with_smart_priority(p, f)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Rule Update Failure", str(error))
            return
        refresh_matrix_data()
        note = f"Added rule for {f} at priority position {placement['position']} of {placement['total']}"
        if placement["above"]:
            note += " (placed above a broader rule it would otherwise lose to)"
        if _status_label_ref:
            _status_label_ref.config(text=f" Application Status: {note}", fg=gui_theme.THEME["accent_neon"])
        popup.destroy()

    tk.Button(
        btn_panel, text="Save Sorting Rule", font=("Segoe UI", 9, "bold"), 
        bg=gui_theme.THEME["btn_primary"], fg=gui_theme.THEME["btn_primary_fg"],
        activebackground=gui_theme.THEME["btn_primary_hover"], activeforeground=gui_theme.THEME["btn_primary_fg"],
        bd=0, padx=18, pady=6, command=save_new_rule_action
    ).pack(side="right")

# tab_matrix.py - Piece 4: Graphical Layout Assembly & Action Bindings
def build(parent, status_label_ref):
    """Initializes the rule canvas ledger tables and maps component references cleanly."""
    global _drum_tree, _synth_tree, _candidate_tree, _status_label_ref
    _status_label_ref = status_label_ref
    
    style = ttk.Style()
    style.configure(
        "Treeview",
        background=gui_theme.THEME["bg_field"],      
        foreground=gui_theme.THEME["fg_light"],      
        fieldbackground=gui_theme.THEME["bg_field"], 
        rowheight=24,
        font=("Segoe UI", 9)
    )
    style.configure(
        "Treeview.Heading",
        background=gui_theme.THEME["bg_panel"],
        foreground=gui_theme.THEME["fg_light"],
        font=("Segoe UI", 9, "bold")
    )
    
    style.map("Treeview", 
        background=[("selected", gui_theme.THEME["tag_enabled"]), ("active", gui_theme.THEME["bg_field"])], 
        foreground=[("selected", "white"), ("active", gui_theme.THEME["fg_light"])]
    )
    style.map("Treeview.Heading",
        background=[("active", gui_theme.THEME["hover_dark"]), ("pressed", gui_theme.THEME["bg_dark"])],
        foreground=[("active", gui_theme.THEME["tag_enabled"]), ("pressed", gui_theme.THEME["fg_light"])]
    )

    header = tk.Frame(parent, bg=gui_theme.THEME["bg_dark"])
    header.pack(fill="x", padx=15, pady=(14, 4))
    tk.Label(
        header, text="Rules & Learning", font=("Segoe UI", 12, "bold"),
        bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]
    ).pack(anchor="w")
    tk.Label(
        header,
        text="Pick a kind of file below. Each tab shows where it goes and the controls for changing it.",
        font=("Segoe UI", 9), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"],
        wraplength=900, justify="left"
    ).pack(anchor="w", pady=(2, 0))

    master_workspace = tk.Frame(parent, bg=gui_theme.THEME["bg_dark"])
    master_workspace.pack(fill="both", expand=True, padx=15, pady=10)
    master_workspace.columnconfigure(0, weight=1)
    master_workspace.rowconfigure(0, weight=1)

    sections = ttk.Notebook(master_workspace)
    sections.grid(row=0, column=0, sticky="nsew")
    loops_tab = tk.Frame(sections, bg=gui_theme.THEME["bg_dark"], padx=14, pady=12)
    oneshot_tab = tk.Frame(sections, bg=gui_theme.THEME["bg_dark"], padx=14, pady=12)
    preset_tab = tk.Frame(sections, bg=gui_theme.THEME["bg_dark"], padx=14, pady=12)
    sections.add(loops_tab, text="  Loops  ")
    sections.add(oneshot_tab, text="  One-shots  ")
    sections.add(preset_tab, text="  Presets & racks  ")
    for tab in (oneshot_tab, preset_tab):
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=0)
        tab.rowconfigure(0, weight=1)

    lists_frame = tk.Frame(oneshot_tab, bg=gui_theme.THEME["bg_dark"])
    lists_frame.grid(row=0, column=0, sticky="nsew")
    lists_frame.columnconfigure(0, weight=1)
    lists_frame.rowconfigure(0, weight=1, uniform="sections")
    lists_frame.rowconfigure(1, weight=1, uniform="sections")

    # LOOPS TAB
    global _loop_path_label
    tk.Label(loops_tab, text="Loop folders", font=("Segoe UI", 11, "bold"),
             bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]).pack(anchor="w")
    tk.Label(loops_tab, text="Loops ignore the one-shot rules. They are filed only by tempo and key, "
             "in the order you choose.", font=("Segoe UI", 9), bg=gui_theme.THEME["bg_dark"],
             fg=gui_theme.THEME["fg_muted"], wraplength=700, justify="left").pack(anchor="w", pady=(2, 12))
    loop_card = tk.Frame(loops_tab, bg=gui_theme.THEME["bg_field"], bd=1, relief="solid", padx=14, pady=12)
    loop_card.pack(fill="x")
    tk.Label(loop_card, text="Loops are filed into", font=("Segoe UI", 9), bg=gui_theme.THEME["bg_field"],
             fg=gui_theme.THEME["fg_muted"]).pack(anchor="w")
    _loop_path_label = tk.Label(loop_card, text=_loop_path_text(), font=("Consolas", 10),
                                bg=gui_theme.THEME["bg_field"], fg=gui_theme.THEME["fg_light"])
    _loop_path_label.pack(anchor="w", pady=(2, 10))

    def edit_loop_layout_from_strip():
        win = open_loop_layout(parent, gui_theme.USER_LIBRARY_PATH)
        win.bind("<Destroy>", lambda e: _loop_path_label.config(text=_loop_path_text())
                 if e.widget is win and _loop_path_label is not None else None, add="+")

    tk.Button(loop_card, text="Edit layout…", command=edit_loop_layout_from_strip,
              bg=gui_theme.THEME["tag_enabled"], fg="white", activebackground=gui_theme.THEME["tag_enabled"],
              activeforeground="white", bd=0, font=("Segoe UI", 9, "bold"), padx=14, pady=4).pack(anchor="w")

    # ONE-SHOTS TAB, SECTION 1: LEARNING SUGGESTIONS
    candidate_section = tk.Frame(lists_frame, bg=gui_theme.THEME["bg_dark"])
    candidate_section.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
    tk.Label(
        candidate_section, text="Suggestions to review",
        font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_dark"],
        fg=gui_theme.THEME["fg_light"]
    ).pack(anchor="w", pady=(0, 2))
    tk.Label(
        candidate_section,
        text="Smart Learning only suggests rules. Select a suggestion, then choose Use or Dismiss. Nothing is changed automatically. "
             "Priority uses the same scale as the rules below: a higher number is checked first, so new words go to the bottom (1) and never take files from a more specific rule.",
        font=("Segoe UI", 8), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"],
        wraplength=760, justify="left"
    ).pack(anchor="w", pady=(0, 4))
    candidate_wrapper = ttk.Frame(candidate_section)
    candidate_wrapper.pack(fill="both", expand=True)
    candidate_scroll = ttk.Scrollbar(candidate_wrapper)
    candidate_scroll.pack(side="right", fill="y")
    _candidate_tree = ttk.Treeview(
        candidate_wrapper,
        columns=("Token", "Target", "Priority", "Evidence", "Generated Pattern"),
        show="headings", style="Treeview", height=5,
        yscrollcommand=candidate_scroll.set
    )
    _candidate_tree.pack(fill="both", expand=True)
    candidate_scroll.config(command=_candidate_tree.yview)
    for column, heading, width in (
        ("Token", "Word found", 100), ("Target", "Suggested folder", 150),
        ("Priority", "Priority if used", 100),
        ("Evidence", "Examples", 70), ("Generated Pattern", "Matching pattern", 260)
    ):
        _candidate_tree.heading(column, text=heading)
        _candidate_tree.column(column, width=width, anchor="w")

    # SECTION 2: DRUM MATRIX GRID
    drum_section = tk.Frame(lists_frame, bg=gui_theme.THEME["bg_dark"])
    drum_section.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
    
    tk.Label(drum_section, text="How should the app recognize one-shots?", font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]).pack(anchor="w", pady=(0, 2))
    tk.Label(drum_section, text="These rules apply to one-shots only (drums, bass hits, vocals, FX and more). They look at filenames and choose a folder inside Samples\\One-Shots. Most users can leave them as they are.", font=("Segoe UI", 8), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"], wraplength=760, justify="left").pack(anchor="w", pady=(0, 4))
    
    drum_wrapper = ttk.Frame(drum_section)
    drum_wrapper.pack(fill="both", expand=True)
    drum_scroll = ttk.Scrollbar(drum_wrapper)
    drum_scroll.pack(side="right", fill="y")
    
    _drum_tree = ttk.Treeview(drum_wrapper, columns=('Regex Pattern', 'Target Destination Folder', 'Priority', 'State'), show='headings', style="Treeview", height=5, yscrollcommand=drum_scroll.set)
    _drum_tree.pack(fill="both", expand=True)
    drum_scroll.config(command=_drum_tree.yview)
    _drum_tree.heading('Regex Pattern', text='What the filename contains')
    _drum_tree.heading('Target Destination Folder', text='Put it in this folder')
    _drum_tree.heading('Priority', text='Priority')
    _drum_tree.heading('State', text='State')
    _drum_tree.column('Regex Pattern', width=320, anchor='w')
    _drum_tree.column('Target Destination Folder', width=200, anchor='w')
    _drum_tree.column('Priority', width=70, anchor='center')
    _drum_tree.column('State', width=100, anchor='center')

    # SECTION 3: SYNTH & PRESET EXTENSIONS MATRIX GRID
    synth_section = tk.Frame(preset_tab, bg=gui_theme.THEME["bg_dark"])
    synth_section.grid(row=0, column=0, sticky="nsew")
    
    tk.Label(synth_section, text="Where should presets, racks and other special files go?", font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_light"]).pack(anchor="w", pady=(0, 2))
    tk.Label(synth_section, text="These rules organize presets, Ableton devices, and MIDI files by their file type.", font=("Segoe UI", 8), bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"], wraplength=760, justify="left").pack(anchor="w", pady=(0, 4))
    
    synth_wrapper = ttk.Frame(synth_section)
    synth_wrapper.pack(fill="both", expand=True)
    synth_scroll = ttk.Scrollbar(synth_wrapper)
    synth_scroll.pack(side="right", fill="y")
    
    _synth_tree = ttk.Treeview(synth_wrapper, columns=('Extension Pattern', 'Target Destination Folder'), show='headings', style="Treeview", height=5, yscrollcommand=synth_scroll.set)
    _synth_tree.pack(fill="both", expand=True)
    synth_scroll.config(command=_synth_tree.yview)
    _synth_tree.heading('Extension Pattern', text='File type')
    _synth_tree.heading('Target Destination Folder', text='Put it in this folder')
    _synth_tree.column('Extension Pattern', width=320, anchor='w')
    _synth_tree.column('Target Destination Folder', width=200, anchor='w')

    def _clear_other_selection(active, other):
        if active.selection() and other.selection():
            other.selection_remove(*other.selection())
    _drum_tree.bind("<<TreeviewSelect>>", lambda _e: _clear_other_selection(_drum_tree, _synth_tree), add="+")
    _synth_tree.bind("<<TreeviewSelect>>", lambda _e: _clear_other_selection(_synth_tree, _drum_tree), add="+")

    # SECTION 3: CONTROL COLUMN PANEL
    action_panel = tk.Frame(
        oneshot_tab, bg=gui_theme.THEME["bg_field"],
        bd=1, relief="solid", padx=12, pady=12
    )
    action_panel.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
    action_panel.config(width=230)
    action_panel.grid_propagate(False)
    preset_panel = tk.Frame(
        preset_tab, bg=gui_theme.THEME["bg_field"],
        bd=1, relief="solid", padx=12, pady=12
    )
    preset_panel.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
    preset_panel.config(width=230)
    preset_panel.grid_propagate(False)
    
    def dialog_anchor():
        popup_ref = advanced_window["popup"]
        if popup_ref is not None and popup_ref.winfo_exists():
            return popup_ref
        return action_panel.winfo_toplevel()

    def handle_rule_deletion():
        drum_sel = _drum_tree.selection()
        synth_sel = _synth_tree.selection() if _synth_tree else None
        
        if drum_sel:
            vals = _drum_tree.item(drum_sel[0], 'values')
            if vals and len(vals) > 0:
                pattern = vals[0]
                if pattern in sorter_engine.DRUM_KEYWORDS:
                    if not ask_confirm(
                        dialog_anchor(), "Delete rule?",
                        f"Permanently delete the rule '{pattern}'?\n\n"
                        "To keep it but stop using it, choose Disable instead.",
                        "Delete"
                    ):
                        return
                    del sorter_engine.DRUM_KEYWORDS[pattern]
                    _sync_config_state(f"Deleted sound rule for: {pattern}")
        elif synth_sel:
            vals = _synth_tree.item(synth_sel[0], 'values')
            if vals and len(vals) > 0:
                pattern = vals[0]
                if pattern in sorter_engine.SYNTH_EXTS or pattern in sorter_engine.NATIVE_EXTS:
                    if not ask_confirm(
                        dialog_anchor(), "Delete rule?",
                        f"Permanently delete the rule '{pattern}'?", "Delete"
                    ):
                        return
                if pattern in sorter_engine.SYNTH_EXTS:
                    del sorter_engine.SYNTH_EXTS[pattern]
                    _sync_config_state(f"Deleted preset rule for: {pattern}")
                elif pattern in sorter_engine.NATIVE_EXTS:
                    del sorter_engine.NATIVE_EXTS[pattern]
                    _sync_config_state(f"Deleted Live rack rule for: {pattern}")
        else:
            messagebox.showwarning("Selection Required", "Please select a rule row from either table category to delete.")

    def set_selected_rule_enabled(enabled):
        selection = _drum_tree.selection()
        if not selection:
            messagebox.showwarning("Selection Required", "Select a sound rule first.")
            return
        pattern = _drum_tree.item(selection[0], "values")[0]
        try:
            sorter_engine.set_rule_metadata(pattern, enabled=enabled)
            _sync_config_state(f"{'Enabled' if enabled else 'Disabled'} rule: {pattern}")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Rule Update Failure", str(error))

    def move_selected_rule(direction):
        selection = _drum_tree.selection()
        if not selection:
            messagebox.showwarning("Selection Required", "Select a sound rule first.")
            return
        pattern = _drum_tree.item(selection[0], "values")[0]
        try:
            moved = sorter_engine.move_rule(pattern, direction)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Rule Update Failure", str(error))
            return
        refresh_matrix_data()
        for item in _drum_tree.get_children():
            if _drum_tree.item(item, "values")[0] == pattern:
                _drum_tree.selection_set(item)
                _drum_tree.see(item)
                break
        if _status_label_ref and moved:
            _status_label_ref.config(
                text=f" Application Status: Moved rule {'up' if direction < 0 else 'down'}: {pattern}",
                fg=gui_theme.THEME["accent_neon"]
            )

    def show_rule_conflicts():
        competitions = sorter_engine.find_rule_competitions()
        anchor = dialog_anchor()
        if not competitions:
            show_notice(
                anchor, "Competing rules",
                "Good news: no filename matches two enabled rules that send it to "
                "different folders.", heading="No competing rules"
            )
            return
        cards = [
            (
                f"Names like \"{example}\" go to {winner_folder}",
                f"Rule '{winner}' wins.\n"
                f"Rule '{loser}' would send them to {loser_folder}, but never gets the chance.",
            )
            for winner, loser, winner_folder, loser_folder, example in competitions
        ]
        show_notice(
            anchor, "Competing rules",
            "Some filenames fit two rules at once. The rule higher in the list "
            "wins. If a result below is wrong, select the rule you want to win "
            "and choose \"Raise priority\".",
            heading=f"{len(competitions)} competing rule{'s' if len(competitions) != 1 else ''} found",
            cards=cards
        )

    advanced_window = {"popup": None}

    def open_advanced_options(parent_widget):
        existing = advanced_window["popup"]
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        theme = gui_theme.THEME
        popup = tk.Toplevel(parent_widget)
        advanced_window["popup"] = popup
        _advanced_popup["window"] = popup
        popup.title("Advanced rule options")
        popup.configure(bg=theme["bg_dark"])
        popup.transient(parent_widget.winfo_toplevel())
        popup.resizable(False, False)
        master = parent_widget.winfo_toplevel()
        master.bind(
            "<<NotebookTabChanged>>", lambda _e: popup.winfo_exists() and popup.destroy(), add="+"
        )
        popup.bind("<Destroy>", lambda e: _advanced_popup.update(window=None) if e.widget is popup else None)
        popup.geometry(
            f"380x640+{max(min(master.winfo_x() + master.winfo_width() - 230, popup.winfo_screenwidth() - 390), 0)}"
            f"+{max(min(master.winfo_y() + 40, popup.winfo_screenheight() - 700), 0)}"
        )
        tk.Label(
            popup, text="Advanced rule options", font=("Segoe UI", 12, "bold"),
            bg=theme["bg_dark"], fg=theme["accent_neon"], anchor="w"
        ).pack(fill="x", padx=18, pady=(16, 2))
        tk.Label(
            popup, text="Select a rule in the Rules list, then choose an action. "
            "You will always be asked to confirm before anything changes.",
            font=("Segoe UI", 9), bg=theme["bg_dark"], fg=theme["fg_muted"],
            wraplength=340, justify="left", anchor="w"
        ).pack(fill="x", padx=18, pady=(0, 8))
        selected_var = tk.StringVar()
        tk.Label(
            popup, textvariable=selected_var, font=("Segoe UI", 9, "bold"),
            bg=theme["bg_field"], fg=theme["fg_light"], wraplength=340,
            justify="left", anchor="w", padx=8, pady=6
        ).pack(fill="x", padx=18, pady=(0, 10))

        def current_rule():
            drum = _drum_tree.selection()
            if drum:
                values = _drum_tree.item(drum[0], "values")
                return "drum", values[0], values[1]
            other = _synth_tree.selection() if _synth_tree else ()
            if other:
                values = _synth_tree.item(other[0], "values")
                return "file", values[0], values[1]
            return None, None, None

        def update_selected_label(_event=None):
            if not popup.winfo_exists():
                return
            kind, pattern, folder = current_rule()
            selected_var.set(
                f"Selected rule: {pattern}  →  {folder}" if kind
                else "No rule selected. Pick one in the Rules list first."
            )

        def reselect(kind, pattern):
            tree = _drum_tree if kind == "drum" else _synth_tree
            for item in tree.get_children():
                if tree.item(item, "values")[0] == pattern:
                    tree.selection_set(item)
                    tree.see(item)
                    break

        def confirmed_action(requires_sound_rule, question, action):
            kind, pattern, folder = current_rule()
            if not kind:
                messagebox.showwarning("Select a rule", "Select a rule in the Rules list first.", parent=popup)
                return
            if requires_sound_rule and kind != "drum":
                show_notice(
                    popup, "Not needed for file types",
                    "Priority and enable/disable apply to sound rules. Each file type "
                    "(like .fxp) has only one rule, so nothing competes. To stop using "
                    "one, use Remove selected rule; to redirect it, use Change folder."
                )
                return
            if not ask_confirm(popup, "Please confirm", question.format(pattern=pattern, folder=folder)):
                return
            action()
            if kind == "drum" or pattern in sorter_engine.DRUM_KEYWORDS:
                reselect(kind, pattern)
            update_selected_label()

        def remove_action():
            kind, pattern, folder = current_rule()
            if not kind:
                messagebox.showwarning("Select a rule", "Select a rule in the Rules list first.", parent=popup)
                return
            handle_rule_deletion()
            update_selected_label()

        def add_action():
            launch_interactive_rule_builder(parent_widget)

        def add_file_type_action():
            values = ask_fields(
                popup, "Add a file type",
                "Send every file with a given extension (for example .vital or .nmsv) into one folder.",
                ["File extension (e.g. .vital)", "Put it in this folder"]
            )
            if values is None:
                return
            extension, folder = values
            extension = "." + extension.lstrip(".").lower() if extension.strip(". ") else ""
            if not extension or not folder:
                messagebox.showwarning("Missing info", "Enter both an extension and a folder.", parent=popup)
                return
            if extension in sorter_engine.SYNTH_EXTS or extension in sorter_engine.NATIVE_EXTS:
                messagebox.showwarning("Already exists", f"A rule for {extension} already exists. Use 'Change folder' instead.", parent=popup)
                return
            if not ask_confirm(popup, "Add this file type?", f"Send every {extension} file into the folder '{folder}'?", "Add"):
                return
            sorter_engine.SYNTH_EXTS[extension] = folder
            _sync_config_state(f"Added file type rule: {extension} → {folder}")
            reselect("file", extension)
            update_selected_label()

        def change_folder_action():
            kind, pattern, folder = current_rule()
            if not kind:
                messagebox.showwarning("Select a rule", "Select a rule in the Rules list first.", parent=popup)
                return
            values = ask_fields(
                popup, "Change folder", f"Choose a new folder for '{pattern}'.\nCurrently: {folder}",
                ["New folder"]
            )
            if values is None or not values[0]:
                return
            new_folder = values[0]
            if not ask_confirm(popup, "Please confirm", f"Send '{pattern}' to '{new_folder}' instead of '{folder}'?", "Change"):
                return
            if kind == "drum":
                sorter_engine.DRUM_KEYWORDS[pattern] = new_folder
            elif pattern in sorter_engine.NATIVE_EXTS:
                sorter_engine.NATIVE_EXTS[pattern] = new_folder
            else:
                sorter_engine.SYNTH_EXTS[pattern] = new_folder
            _sync_config_state(f"Changed folder for {pattern} → {new_folder}")
            reselect(kind, pattern)
            update_selected_label()

        def restore_backup_action():
            backups = sorter_engine.list_config_backups()
            if not backups:
                show_notice(popup, "Restore a backup", "No automatic backups exist yet. One is saved each time you change a rule.", heading="No backups yet")
                return

            def label_for(path):
                stamp = os.path.basename(path)[len("library_config_"):-len(".json")][:15]
                try:
                    return datetime.datetime.strptime(stamp, "%Y%m%d_%H%M%S").strftime("%b %d, %Y  %I:%M:%S %p")
                except ValueError:
                    return stamp

            dialog = tk.Toplevel(popup)
            dialog.title("Restore a previous rules backup")
            dialog.configure(bg=theme["bg_dark"])
            dialog.transient(popup.winfo_toplevel())
            tk.Label(dialog, text="Pick a backup to go back to", font=("Segoe UI", 12, "bold"),
                     bg=theme["bg_dark"], fg=theme["accent_neon"]).pack(anchor="w", padx=20, pady=(16, 4))
            tk.Label(dialog, text="Your current rules are saved first, so you can undo a restore the same way.",
                     font=("Segoe UI", 9), bg=theme["bg_dark"], fg=theme["fg_muted"], wraplength=360,
                     justify="left").pack(anchor="w", padx=20, pady=(0, 8))
            listbox = tk.Listbox(dialog, height=min(len(backups), 10), width=40, exportselection=False,
                                 bg=theme["bg_field"], fg=theme["fg_light"], font=("Segoe UI", 10),
                                 selectbackground=theme["tag_enabled"], bd=0, highlightthickness=1)
            for path in backups:
                listbox.insert("end", label_for(path))
            listbox.selection_set(0)
            listbox.pack(padx=20, pady=(0, 8))
            chosen = {"path": None}

            def restore_selected():
                selection = listbox.curselection()
                if selection:
                    chosen["path"] = backups[selection[0]]
                    dialog.destroy()

            row = tk.Frame(dialog, bg=theme["bg_dark"])
            row.pack(fill="x", padx=20, pady=(0, 16))
            tk.Button(row, text="Restore", width=12, command=restore_selected, bg=theme["btn_primary"],
                      fg=theme["btn_primary_fg"], bd=0, font=("Segoe UI", 9, "bold")).pack(side="right", padx=(8, 0))
            tk.Button(row, text="Cancel", width=12, command=dialog.destroy, bg=theme["btn_secondary"],
                      fg=theme["fg_light"], bd=0, font=("Segoe UI", 9, "bold")).pack(side="right")
            dialog.bind("<Escape>", lambda _e: dialog.destroy())
            _center_over(dialog, popup)
            dialog.grab_set()
            dialog.wait_window()
            path = chosen["path"]
            if not path:
                return
            if not ask_confirm(popup, "Restore this backup?",
                               f"Replace your current rules with the backup from {label_for(path)}?", "Restore"):
                return
            try:
                sorter_engine.restore_config_backup(path)
            except Exception as error:
                messagebox.showerror("Restore failed", str(error), parent=popup)
                return
            refresh_matrix_data()
            update_selected_label()
            show_notice(popup, "Restored", "Your rules were restored from the backup.", heading="Done")

        def restore_defaults_action():
            missing = sorter_engine.missing_default_rules()
            if not missing:
                show_notice(popup, "Restore default rules", "All the built-in rules are already present.", heading="Nothing to restore")
                return
            cards = [
                (plain_rule_name(pattern) if key == "DRUM_KEYWORDS" else pattern, f"→ {folder}")
                for key, rules in missing.items() for pattern, folder in rules.items()
            ]
            if not ask_confirm_cards(
                popup, "Restore default rules?",
                "These built-in rules are missing. They will be added back. Your other rules are left alone.",
                "Restore", cards
            ):
                return
            for key, rules in missing.items():
                getattr(sorter_engine, key).update(rules)
            _sync_config_state(f"Restored {sum(len(r) for r in missing.values())} default rules")
            update_selected_label()

        def advanced_button(text, command, primary=False, danger=False):
            tk.Button(
                popup, text=text, command=command,
                bg=theme["btn_primary"] if primary else theme["btn_secondary"],
                fg=theme["btn_primary_fg"] if primary else theme["fg_light"],
                activebackground=theme["btn_primary_hover"] if primary else theme["btn_secondary_hover"],
                activeforeground=theme["btn_primary_fg"] if primary else theme["accent_neon"],
                bd=0 if primary else 1, relief="solid", font=("Segoe UI", 9, "bold"), height=1
            ).pack(fill="x", padx=18, pady=(0, 5), ipady=4)

        advanced_button("Add a custom rule", add_action, primary=True)
        advanced_button("Add a file type (.fxp, .vital…)", add_file_type_action)
        advanced_button("Change folder of selected rule", change_folder_action)
        advanced_button("Remove selected rule", remove_action)
        advanced_button(
            "Enable selected rule",
            lambda: confirmed_action(
                True, "Enable the rule '{pattern}'?\n\nFiles matching it will be sorted into '{folder}'.",
                lambda: set_selected_rule_enabled(True)
            )
        )
        advanced_button(
            "Disable selected rule",
            lambda: confirmed_action(
                True, "Disable the rule '{pattern}'?\n\nIt is kept, but no files will be sorted by it until you enable it again.",
                lambda: set_selected_rule_enabled(False)
            )
        )
        advanced_button(
            "Raise priority (checked earlier)",
            lambda: confirmed_action(
                True, "Move the rule '{pattern}' up one step?\n\nThis changes which rule wins when a file matches several.",
                lambda: move_selected_rule(-1)
            )
        )
        advanced_button(
            "Lower priority (checked later)",
            lambda: confirmed_action(
                True, "Move the rule '{pattern}' down one step?\n\nThis changes which rule wins when a file matches several.",
                lambda: move_selected_rule(1)
            )
        )
        advanced_button("Find competing rules", show_rule_conflicts)
        advanced_button("Restore default rules", restore_defaults_action)
        advanced_button("Restore a previous rules backup…", restore_backup_action)
        advanced_button("Close", popup.destroy)

        for tree in (_drum_tree, _synth_tree):
            if tree is not None:
                tree.bind("<<TreeviewSelect>>", update_selected_label, add="+")
        update_selected_label()

    def review_selected_candidate(decision):
        selection = _candidate_tree.selection()
        if not selection:
            messagebox.showwarning("Selection Required", "Select a pending learning candidate first.")
            return
        values = _candidate_tree.item(selection[0], "values")
        try:
            sorter_engine.review_learning_candidate(values[0], values[1], decision)
            _sync_config_state(
                f"{'Approved' if decision == 'approved' else 'Rejected'} learning candidate: {values[0]}"
            )
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Candidate Review Failure", str(error))

    # Keep the common action first and separate advanced maintenance controls below it.
    tk.Label(
        action_panel, text="Review a suggestion",
        font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_field"],
        fg=gui_theme.THEME["fg_light"], anchor="w"
    ).pack(fill="x", pady=(0, 3))
    tk.Label(
        action_panel, text="Select a suggestion in the list, then decide whether to use it.",
        font=("Segoe UI", 9), bg=gui_theme.THEME["bg_field"],
        fg=gui_theme.THEME["fg_muted"], wraplength=190, justify="left", anchor="w"
    ).pack(fill="x", pady=(0, 6))
    tk.Button(
        action_panel, text="Use this suggestion",
        bg=gui_theme.THEME["btn_primary"], fg=gui_theme.THEME["btn_primary_fg"],
        activebackground=gui_theme.THEME["btn_primary_hover"],
        activeforeground=gui_theme.THEME["btn_primary_fg"], bd=0,
        font=("Segoe UI", 9, "bold"), height=2,
        command=lambda: review_selected_candidate("approved")
    ).pack(fill="x", pady=(0, 5))

    def use_all_candidates():
        pending = [c for c in sorter_engine.LEARNED_RULE_CANDIDATES if c.get("status", "pending") == "pending"]
        if not pending:
            show_notice(parent, "Use all suggestions", "There are no suggestions to review.")
            return
        if not ask_confirm(parent, "Use all suggestions",
                           f"Add all {len(pending)} suggested rules? Each one is ranked automatically so it "
                           "won't steal files from a more specific rule. You can still disable or remove any "
                           "rule later, and Organize backs up before moving anything.", yes_text="Use all"):
            return
        applied = 0
        try:
            for candidate in pending:
                sorter_engine.review_learning_candidate(candidate["token"], candidate["target"], "approved")
                applied += 1
        except (OSError, ValueError, json.JSONDecodeError) as error:
            messagebox.showerror("Candidate Review Failure", str(error))
        _sync_config_state(f"Added {applied} suggested rules")

    tk.Button(
        action_panel, text="Use all suggestions",
        bg=gui_theme.THEME["btn_secondary"], fg=gui_theme.THEME["fg_light"],
        activebackground=gui_theme.THEME["btn_secondary_hover"],
        activeforeground=gui_theme.THEME["accent_neon"], bd=1, relief="solid",
        font=("Segoe UI", 9, "bold"), height=2, command=use_all_candidates
    ).pack(fill="x", pady=(0, 5))
    tk.Button(
        action_panel, text="Dismiss this suggestion",
        bg=gui_theme.THEME["bg_panel"], fg=gui_theme.THEME["fg_light"],
        activebackground=gui_theme.THEME["btn_danger_hover"],
        activeforeground="white", bd=1,
        relief="solid", font=("Segoe UI", 9), height=2,
        command=lambda: review_selected_candidate("rejected")
    ).pack(fill="x", pady=(0, 14))

    tk.Label(
        action_panel, text="Advanced options",
        font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_field"],
        fg=gui_theme.THEME["fg_light"], anchor="w"
    ).pack(fill="x", pady=(0, 2))
    tk.Label(
        action_panel, text="Add, remove, disable or re-rank rules. Every change asks you to confirm first.",
        font=("Segoe UI", 9), bg=gui_theme.THEME["bg_field"],
        fg=gui_theme.THEME["fg_muted"], wraplength=190, justify="left", anchor="w"
    ).pack(fill="x", pady=(0, 6))

    def add_action_button(text, command, *, primary=False, bottom=5, panel=None):
        tk.Button(
            panel or action_panel, text=text,
            bg=gui_theme.THEME["btn_primary"] if primary else gui_theme.THEME["btn_secondary"],
            fg=gui_theme.THEME["btn_primary_fg"] if primary else gui_theme.THEME["fg_light"],
            activebackground=(
                gui_theme.THEME["btn_primary_hover"]
                if primary else gui_theme.THEME["btn_secondary_hover"]
            ),
            activeforeground=gui_theme.THEME["btn_primary_fg"] if primary else gui_theme.THEME["accent_neon"],
            bd=0 if primary else 1, relief="solid", font=("Segoe UI", 9, "bold"),
            height=2, command=command
        ).pack(fill="x", pady=(0, bottom))

    def auto_suggest_from_library():
        library = gui_theme.USER_LIBRARY_PATH
        if not library or not os.path.isdir(library):
            return
        result = {}

        def work():
            try:
                found = rule_suggester.suggest_rules(library)
                result["added"] = rule_suggester.add_suggestions_as_candidates(found)
            except (OSError, ValueError, json.JSONDecodeError):
                result["added"] = 0

        def poll():
            if thread.is_alive():
                parent.after(300, poll)
                return
            try:
                refresh_matrix_data()
                if result.get("added") and _status_label_ref:
                    _status_label_ref.config(
                        text=f" Application Status: Found {result['added']} new rule suggestion(s) in your library. Review them on the Rules tab.",
                        fg=gui_theme.THEME["accent_neon"])
            except tk.TclError:
                pass

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        parent.after(300, poll)

    add_action_button("Advanced options…", lambda: open_advanced_options(parent), primary=True, bottom=5)
    add_action_button("Test a filename…", lambda: open_filename_tester(parent), bottom=0)
    tk.Label(
        preset_panel, text="Advanced options",
        font=("Segoe UI", 10, "bold"), bg=gui_theme.THEME["bg_field"],
        fg=gui_theme.THEME["fg_light"], anchor="w"
    ).pack(fill="x", pady=(0, 2))
    tk.Label(
        preset_panel, text="Add, remove or change where a file type goes. Every change asks you to confirm first.",
        font=("Segoe UI", 9), bg=gui_theme.THEME["bg_field"],
        fg=gui_theme.THEME["fg_muted"], wraplength=190, justify="left", anchor="w"
    ).pack(fill="x", pady=(0, 6))
    add_action_button("Advanced options…", lambda: open_advanced_options(parent), primary=True, bottom=0,
                      panel=preset_panel)

    footer = tk.Frame(master_workspace, bg=gui_theme.THEME["bg_dark"])
    footer.grid(row=1, column=0, sticky="ew", pady=(8, 0))
    tk.Label(footer, text="Profile (all rules and settings):", font=("Segoe UI", 9),
             bg=gui_theme.THEME["bg_dark"], fg=gui_theme.THEME["fg_muted"]).pack(side="left")
    for text, command in (("Import", lambda: execute_profile_json_import(parent)),
                          ("Export", lambda: execute_profile_json_export(parent))):
        tk.Button(footer, text=text, command=command, bg=gui_theme.THEME["btn_secondary"],
                  fg=gui_theme.THEME["fg_light"], activebackground=gui_theme.THEME["btn_secondary_hover"],
                  activeforeground=gui_theme.THEME["accent_neon"], bd=1, relief="solid",
                  font=("Segoe UI", 9, "bold"), width=9).pack(side="right", padx=(6, 0))

    refresh_matrix_data()
    global _auto_suggest_ref
    _auto_suggest_ref = auto_suggest_from_library
    parent.after(2000, auto_suggest_from_library)


def rescan_suggestions():
    """Re-run the library rule scan after files were organized or imported."""
    if _auto_suggest_ref is not None:
        try:
            _auto_suggest_ref()
        except tk.TclError:
            pass

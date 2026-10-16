import os
import threading
import tkinter as tk
from tkinter import filedialog

import gui_theme
import xo_filter
from tab_matrix import _center_over, show_notice

DEFAULT_DEST = r"C:\XO Samples for Filters"


def _drive(path):
    return os.path.splitdrive(os.path.abspath(path))[0].lower()


def open_xo_builder(anchor):
    theme = gui_theme.THEME
    library = gui_theme.USER_LIBRARY_PATH
    if not library or not os.path.isdir(library):
        show_notice(anchor, "XO filter folder", "Set your Ableton User Library location first (Organize tab).")
        return

    win = tk.Toplevel(anchor)
    win.title("Build XO filter folder")
    win.configure(bg=theme["bg_dark"])
    win.transient(anchor.winfo_toplevel())
    win.resizable(False, False)
    state = {"plan": None, "busy": False, "cancel": False, "vars": {}}

    def label(text, font=("Segoe UI", 9), fg=None, **pack):
        widget = tk.Label(win, text=text, font=font, bg=theme["bg_dark"], fg=fg or theme["fg_muted"],
                          wraplength=520, justify="left", anchor="w")
        widget.pack(fill="x", padx=20, **pack)
        return widget

    label("Build XO filter folder", ("Segoe UI", 12, "bold"), theme["accent_neon"], pady=(16, 2))
    label("Groups your sounds by type (kicks, nature, vocals, foley...) into one folder per type, so XO can "
          "filter by folder. Files are hard-linked: no extra disk space, and your originals are never moved "
          "or changed. Safe to re-run any time to add new sounds.", pady=(0, 10))

    dest_var = tk.StringVar(value=DEFAULT_DEST)
    row = tk.Frame(win, bg=theme["bg_dark"])
    row.pack(fill="x", padx=20)
    tk.Entry(row, textvariable=dest_var, bg=theme["bg_field"], fg=theme["fg_light"],
             insertbackground=theme["fg_light"], bd=0, highlightthickness=1,
             font=("Segoe UI", 10)).pack(side="left", fill="x", expand=True, ipady=4)

    def browse():
        chosen = filedialog.askdirectory(parent=win, title="Choose the XO filter folder location")
        if chosen:
            dest_var.set(os.path.normpath(chosen))
            refresh_notes()

    tk.Button(row, text="Change…", command=browse, bg=theme["btn_secondary"], fg=theme["fg_muted"],
              bd=0, font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
    note = label("", pady=(4, 0))

    def refresh_notes(*_):
        dest = dest_var.get().strip()
        messages = []
        if "onedrive" in dest.lower():
            messages.append("This is inside OneDrive, which doesn't understand hard links and would upload every "
                            "file again. Choose a folder outside OneDrive.")
        if dest and _drive(dest) != _drive(library):
            messages.append("This is on a different drive than your library, so files will be copied "
                            "(uses disk space) instead of linked.")
        note.config(text="\n".join(messages), fg=theme["accent_neon"] if messages else theme["fg_muted"])

    dest_var.trace_add("write", refresh_notes)
    refresh_notes()

    loops_var = tk.BooleanVar(value=False)
    tk.Checkbutton(win, text="Include loops (XO works best with one-shots)", variable=loops_var,
                   bg=theme["bg_dark"], fg=theme["fg_light"], selectcolor=theme["bg_field"],
                   activebackground=theme["bg_dark"], activeforeground=theme["fg_light"],
                   font=("Segoe UI", 9)).pack(anchor="w", padx=18, pady=(8, 0))

    status = label("Click Scan to see what will be created.", fg=theme["fg_light"], pady=(8, 4))
    types_frame = tk.Frame(win, bg=theme["bg_field"])
    types_frame.pack(fill="x", padx=20)

    buttons = tk.Frame(win, bg=theme["bg_dark"])
    buttons.pack(fill="x", padx=20, pady=(12, 16))
    close_button = tk.Button(buttons, text="Close", width=10, command=lambda: close(), bg=theme["btn_secondary"],
                             fg=theme["fg_light"], bd=0, font=("Segoe UI", 9, "bold"))
    close_button.pack(side="right")
    build_button = tk.Button(buttons, text="Build folder", width=12, state="disabled", bg=theme["btn_secondary"],
                             fg=theme["fg_muted"], bd=0, font=("Segoe UI", 9, "bold"))
    build_button.pack(side="right", padx=8)
    scan_button = tk.Button(buttons, text="Scan", width=10, bg=theme["btn_primary"], fg=theme["btn_primary_fg"],
                            bd=0, font=("Segoe UI", 9, "bold"))
    scan_button.pack(side="right")

    def close():
        state["cancel"] = True
        win.destroy()

    def set_busy(busy):
        state["busy"] = busy
        scan_button.config(state="disabled" if busy else "normal")
        if busy:
            build_button.config(state="disabled", bg=theme["btn_secondary"], fg=theme["fg_muted"])

    def alive():
        try:
            return win.winfo_exists()
        except tk.TclError:
            return False

    def show_plan(plan, stats):
        for child in types_frame.winfo_children():
            child.destroy()
        state["vars"] = {}
        state["plan"] = plan
        counts = sorted(plan.items(), key=lambda kv: -len(kv[1]))
        for index, (sound_type, files) in enumerate(counts):
            var = tk.BooleanVar(value=True)
            state["vars"][sound_type] = var
            tk.Checkbutton(types_frame, text=f"{sound_type}  ({len(files):,})", variable=var,
                           bg=theme["bg_field"], fg=theme["fg_light"], selectcolor=theme["bg_dark"],
                           activebackground=theme["bg_field"], activeforeground=theme["fg_light"],
                           font=("Segoe UI", 9), anchor="w").grid(row=index // 2, column=index % 2,
                                                                  sticky="w", padx=10, pady=1)
        total = sum(len(files) for files in plan.values())
        skipped = []
        if stats["loops_skipped"]:
            skipped.append(f"{stats['loops_skipped']:,} loops skipped")
        if stats["unclassified"]:
            skipped.append(f"{stats['unclassified']:,} not recognized")
        status.config(text=f"Found {total:,} sounds in {len(plan)} types"
                           + (f" ({', '.join(skipped)})." if skipped else "."))
        if total:
            build_button.config(state="normal", bg=theme["btn_primary"], fg=theme["btn_primary_fg"])
        _center_over(win, anchor)

    def scan():
        if state["busy"]:
            return
        set_busy(True)
        status.config(text="Scanning your library...")
        result = {}

        def work():
            result["value"] = xo_filter.build_plan(library, include_loops=loops_var.get(),
                                                   should_cancel=lambda: state["cancel"])

        def poll():
            if not alive():
                return
            if thread.is_alive():
                win.after(150, poll)
                return
            set_busy(False)
            show_plan(*result["value"])

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        win.after(150, poll)

    def build():
        dest = dest_var.get().strip()
        if state["busy"] or not state["plan"] or not dest:
            return
        chosen = {name for name, var in state["vars"].items() if var.get()}
        plan = {name: files for name, files in state["plan"].items() if name in chosen}
        set_busy(True)
        progress = {"done": 0, "total": sum(len(f) for f in plan.values())}
        result = {}

        def work():
            try:
                result["value"] = xo_filter.build_folder(
                    plan, dest, library,
                    progress=lambda done, total: progress.update(done=done),
                    should_cancel=lambda: state["cancel"])
            except (OSError, ValueError) as error:
                result["error"] = str(error)

        def poll():
            if not alive():
                return
            if thread.is_alive():
                status.config(text=f"Building... {progress['done']:,} of {progress['total']:,}")
                win.after(200, poll)
                return
            set_busy(False)
            if "error" in result:
                status.config(text=f"Could not build the folder: {result['error']}")
                return
            outcome = result["value"]
            parts = [f"{outcome['linked']:,} linked"]
            if outcome["copied"]:
                parts.append(f"{outcome['copied']:,} copied")
            if outcome["existing"]:
                parts.append(f"{outcome['existing']:,} already there")
            if outcome["failed"]:
                parts.append(f"{outcome['failed']:,} failed")
            status.config(text="Done: " + ", ".join(parts) + f".\nIn XO, point your filter folder at {dest}.")

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        win.after(200, poll)

    scan_button.config(command=scan)
    build_button.config(command=build)
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda _e: close())
    _center_over(win, anchor)

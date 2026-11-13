import os
import sqlite3
import threading
import tkinter as tk
from tkinter import filedialog

import gui_theme
import xo_filter
from tab_matrix import _center_over, show_notice, ask_confirm

def default_destination(home=None):
    """Returns the XO output location beneath the current user's home directory."""
    return os.path.join(home or os.path.expanduser("~"), "XO Samples for Filters")


DEFAULT_DEST = default_destination()


def open_xo_builder(anchor):
    theme = gui_theme.THEME
    library = gui_theme.USER_LIBRARY_PATH
    if not library or not os.path.isdir(library):
        show_notice(anchor, "XO filter folder", "Choose your active User Library in the top bar first.")
        return

    win = tk.Toplevel(anchor)
    win.title("Build XO filter folder")
    win.configure(bg=theme["bg_dark"])
    win.transient(anchor.winfo_toplevel())
    win.resizable(True, True)
    win.geometry("700x680")
    win.minsize(640, 580)
    state = {"plan": None, "busy": False, "cancel": False, "vars": {}}

    def label(text, font=("Segoe UI", 9), fg=None, **pack):
        widget = tk.Label(win, text=text, font=font, bg=theme["bg_dark"], fg=fg or theme["fg_muted"],
                          wraplength=520, justify="left", anchor="w")
        widget.pack(fill="x", padx=20, **pack)
        return widget

    label("Build XO filter folder", ("Segoe UI", 12, "bold"), theme["accent_neon"], pady=(16, 2))
    label("Keeps your library's one-shot categories. Uncategorized sounds use filename and folder keywords. "
          "Files are hard-linked when possible and copied otherwise; originals are not moved. "
          "Hard links share contents, so they are not independent backups. "
          "After building, add the output folder in XO and check the sounds.",
          pady=(0, 10))
    label("Rebuilding replaces this managed folder after a successful build, removing outdated groups. "
          "A failed or cancelled build keeps the previous output. Use a dedicated local folder outside cloud sync.",
          pady=(0, 10))

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
        if dest and "onedrive" in os.path.abspath(dest).lower():
            messages.append("This is inside OneDrive. Linked files may be uploaded as separate files; "
                            "choose a folder outside OneDrive to avoid extra sync traffic.")
        if dest:
            try:
                if xo_filter.same_filesystem(library, dest):
                    messages.append("The destination is on the same filesystem as your library. "
                                    "Hard links will be attempted; unsupported links fall back to copies.")
                else:
                    messages.append("The destination is on a different filesystem, so files will be "
                                    "copied (uses disk space) instead of linked.")
            except OSError as error:
                messages.append(f"Could not check filesystem for the destination: {error}. "
                                "The build will still use links when possible and copy otherwise.")
        note.config(text="\n".join(messages), fg=theme["accent_neon"] if messages else theme["fg_muted"])

    dest_var.trace_add("write", refresh_notes)
    refresh_notes()

    loops_var = tk.BooleanVar(value=False)
    loops_check = tk.Checkbutton(win, text="Include loops (XO works best with one-shots)", variable=loops_var,
                   bg=theme["bg_dark"], fg=theme["fg_light"], selectcolor=theme["bg_field"],
                   activebackground=theme["bg_dark"], activeforeground=theme["fg_light"],
                   font=("Segoe UI", 9))
    loops_check.pack(anchor="w", padx=18, pady=(8, 0))

    status = label("Click Scan to see what will be created.", fg=theme["fg_light"], pady=(8, 4))
    type_area = tk.Frame(win, bg=theme["bg_field"])
    type_area.pack(fill="both", expand=True, padx=20)
    type_scroll = tk.Scrollbar(type_area, orient="vertical")
    type_scroll.pack(side="right", fill="y")
    type_canvas = tk.Canvas(
        type_area, height=170, bg=theme["bg_field"], highlightthickness=0,
        yscrollcommand=type_scroll.set
    )
    type_canvas.pack(side="left", fill="both", expand=True)
    type_scroll.configure(command=type_canvas.yview)
    types_frame = tk.Frame(type_canvas, bg=theme["bg_field"])
    type_window = type_canvas.create_window((0, 0), window=types_frame, anchor="nw")
    types_frame.bind("<Configure>", lambda _event: type_canvas.configure(scrollregion=type_canvas.bbox("all")))
    type_canvas.bind("<Configure>", lambda event: type_canvas.itemconfigure(type_window, width=event.width))
    for column in (0, 1):
        types_frame.columnconfigure(column, weight=1)

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
    cancel_button = tk.Button(
        buttons, text="Cancel", bg=theme["btn_secondary"], fg=theme["fg_light"],
        bd=0, font=("Segoe UI", 9, "bold"),
    )
    def cancel():
        state["cancel"] = True
        cancel_button.config(state="disabled")
        status.config(text="Stopping safely; previous output stays intact until publication.")
    cancel_button.config(command=cancel)
    def set_scan_primary(primary):
        scan_button.config(bg=theme["btn_primary"] if primary else theme["btn_secondary"],
                           fg=theme["btn_primary_fg"] if primary else theme["fg_light"])

    def folders_changed():
        set_scan_primary(True)
        build_button.config(state="disabled", bg=theme["btn_secondary"], fg=theme["fg_muted"])
        if state["busy"]:
            status.config(text="Folders changed. Click Scan to refresh the list.")
        else:
            scan()

    loops_var.trace_add("write", lambda *_: folders_changed()
                        if state["plan"] is not None else None)

    def close():
        state["cancel"] = True
        win.destroy()

    def set_busy(busy):
        state["busy"] = busy
        scan_button.config(state="disabled" if busy else "normal")
        loops_check.configure(state="disabled" if busy else "normal")
        if busy:
            state["cancel"] = False
            cancel_button.config(state="normal")
            cancel_button.pack(side="left")
            build_button.config(state="disabled", bg=theme["btn_secondary"], fg=theme["fg_muted"])
        else:
            cancel_button.pack_forget()
            if state["plan"]:
                build_button.config(state="normal", bg=theme["btn_primary"], fg=theme["btn_primary_fg"])

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
        status.config(text=f"Scan complete: found {total:,} sounds in {len(plan)} types"
                           + (f" ({', '.join(skipped)})." if skipped else "."))
        if total:
            build_button.config(state="normal", bg=theme["btn_primary"], fg=theme["btn_primary_fg"])
            set_scan_primary(False)
        else:
            set_scan_primary(True)
        _center_over(win, anchor)

    def scan():
        if state["busy"]:
            return
        lease = gui_theme.claim_library_job(win, "XO library scan")
        if lease is None:
            return
        set_busy(True)
        set_scan_primary(True)
        status.config(text="Scanning your library...")
        result = {}

        include_loops = loops_var.get()
        state["plan"] = None

        def work():
            try:
                result["value"] = xo_filter.build_plan(
                    library, include_loops=include_loops,
                    should_cancel=lambda: state["cancel"])
            except (OSError, ValueError, sqlite3.Error) as error:
                result["error"] = str(error)

        def poll():
            if not alive():
                return
            if thread.is_alive():
                win.after(150, poll)
                return
            set_busy(False)
            if state["cancel"]:
                status.config(text="Scan cancelled. Scan again before building.")
                return
            if "error" in result:
                status.config(text=f"Could not scan the library: {result['error']}")
                return
            show_plan(*result["value"])

        try:
            thread = gui_theme.start_background_job(
                win, work, cancel=lambda: state.update(cancel=True), lease=lease,
            )
        except RuntimeError as error:
            set_busy(False)
            status.config(text=f"Could not start the library scan: {error}")
            return
        if thread is None:
            set_busy(False)
            return
        win.after(150, poll)

    def build():
        dest = dest_var.get().strip()
        if state["busy"] or not state["plan"] or not dest:
            return
        chosen = {name for name, var in state["vars"].items() if var.get()}
        plan = {name: files for name, files in state["plan"].items() if name in chosen}
        if not plan:
            show_notice(win, "Choose categories", "Select at least one category before building.")
            return
        lease = gui_theme.claim_library_job(win, "XO folder build")
        if lease is None:
            return
        set_busy(True)
        status.config(text="Checking destination; existing output is unchanged…")
        progress = {"text": "Checking destination; existing output is unchanged…", "cancellable": True}
        result = {}
        confirmation = threading.Event()
        approval = {"needed": False, "answered": False, "adopt": False}
        def update_status(text):
            progress["text"] = text
            if text.startswith("Switching to"):
                progress["cancellable"] = False

        def work():
            try:
                digest_cache = {}
                reviewed = xo_filter.review_output_destination(
                    dest, library, digest_cache=digest_cache, should_cancel=lambda: state["cancel"],
                    status=update_status,
                )
                if reviewed["exists"] and not reviewed["managed"] and (
                    reviewed["snapshot"]["files"] or reviewed["snapshot"]["directories"]
                ):
                    approval["needed"] = True
                    while not confirmation.wait(0.1):
                        if state["cancel"]:
                            raise xo_filter.BuildCancelled()
                    if not approval["adopt"]:
                        raise xo_filter.BuildCancelled()
                result["value"] = xo_filter.rebuild_folder(
                    plan, dest, library,
                    progress=lambda done, total: update_status(
                        f"Creating replacement links/copies: {done:,} / {total:,} files"),
                    should_cancel=lambda: state["cancel"],
                    reviewed_destination=reviewed, adopt_existing=approval["adopt"],
                    status=update_status, digest_cache=digest_cache)
            except xo_filter.BuildCancelled:
                result["value"] = {
                    "linked": 0, "copied": 0, "existing": 0, "failed": 0, "cancelled": True,
                    "errors": [], "published": False, "retained_backup": None,
                }
            except (OSError, ValueError) as error:
                result["error"] = str(error)

        def poll():
            if not alive():
                return
            if approval["needed"] and not approval["answered"]:
                approval["answered"] = True
                try:
                    if not state["cancel"]:
                        approval["adopt"] = ask_confirm(
                            win, "Replace older XO output?",
                            f"Destination: {dest}\n\nThis folder is not marked as builder-managed. "
                            "After a successful build, its entire contents will be replaced. The original "
                            "folder will be retained beside it as a .previous- backup, including manually added files. "
                            "Future builds replace only unchanged builder-managed output.\n\n"
                            "Confirm only if this is your dedicated generated XO folder.",
                            "Replace and keep backup",
                        )
                finally:
                    confirmation.set()
            if thread.is_alive():
                status.config(text=progress["text"])
                if not progress["cancellable"] or state["cancel"]:
                    cancel_button.config(state="disabled")
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
                failures = outcome.get("errors", [])
                cards = [
                    (
                        failure["source"],
                        f"Destination: {failure['destination']}\nError: {failure['error']}",
                    )
                    for failure in failures[:25]
                ]
                omitted = max(outcome["failed"] - len(cards), 0)
                details = (
                    "Some files were not added. Resolve the reported file or destination "
                    "problem, then scan and build again. The previous output was not replaced."
                )
                if omitted:
                    details += f"\n\n{omitted:,} additional failed file(s) are not shown here."
                show_notice(
                    win, "XO folder build needs attention", details,
                    heading=f"{outcome['failed']:,} file(s) failed",
                    cards=cards or [("No per-file error details were returned.", "")],
                )
            if outcome["cancelled"] or outcome["failed"]:
                status.config(text=("Build cancelled." if outcome["cancelled"] else "Build failed.")
                              + "\nPrevious output was not replaced.")
                return
            backup_note = (
                f"\nPrevious unmanaged output retained at {outcome['retained_backup']}."
                if outcome.get("retained_backup") else ""
            )
            status.config(
                text="Folder replaced: " + ", ".join(parts)
                + f".\nIn XO, point your filter folder at {dest} and verify the expected sounds appear. "
                  "XO recognition is not verified here." + backup_note
            )

        try:
            thread = gui_theme.start_background_job(
                win, work, cancel=lambda: state.update(cancel=True), lease=lease,
            )
        except RuntimeError as error:
            set_busy(False)
            build_button.config(state="normal")
            status.config(text=f"Could not start the folder build: {error}")
            return
        if thread is None:
            set_busy(False)
            return
        win.after(200, poll)

    scan_button.config(command=scan)
    build_button.config(command=build)
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda _e: close())
    _center_over(win, anchor)

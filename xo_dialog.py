import os
import re
import sqlite3
import tkinter as tk
from tkinter import filedialog
from tkinter.scrolledtext import ScrolledText

import gui_theme
import xo_filter
from tab_matrix import _center_over, show_notice, messagebox

DEFAULT_DEST = r"C:\XO Samples for Filters"


def _drive(path):
    return os.path.splitdrive(os.path.abspath(path))[0].lower()


def _clean_name(name):
    return re.sub(r'[<>:"/\\|?*]', "", name).strip().strip(".")


def open_type_editor(win, anchor, library, on_change, auto_find=False, include_loops=False, *, use_live_tags=False):
    """Lets the user add folders, add keywords to any folder, or learn new folders from the library."""
    theme = gui_theme.THEME
    editor = tk.Toplevel(win)
    editor.title("Edit XO folders")
    editor.configure(bg=theme["bg_dark"])
    editor.transient(win)
    editor.resizable(False, False)
    state = {"selected": None, "suggestions": [], "busy": False}

    def make_label(parent, text, fg=None, font=("Segoe UI", 9), **pack):
        tk.Label(parent, text=text, font=font, bg=theme["bg_dark"], fg=fg or theme["fg_muted"],
                 wraplength=470, justify="left", anchor="w").pack(fill="x", **pack)

    make_label(editor, "Edit XO folders", theme["accent_neon"], ("Segoe UI", 12, "bold"), padx=20, pady=(16, 2))
    make_label(editor, "Pick a folder to add your own keywords (★ marks folders you created). Or create a new "
               "folder: type a name and the words that belong in it. Keywords match filenames, folder names "
               "and your tags.", padx=20, pady=(0, 8))

    body = tk.Frame(editor, bg=theme["bg_dark"])
    body.pack(fill="x", padx=20)
    listbox = tk.Listbox(body, width=26, height=14, exportselection=False, bg=theme["bg_field"],
                         fg=theme["fg_light"], selectbackground=theme["tag_enabled"],
                         selectforeground="white", bd=0, highlightthickness=0,
                         font=("Segoe UI", 9))
    listbox.pack(side="left", fill="y")
    form = tk.Frame(body, bg=theme["bg_dark"])
    form.pack(side="left", fill="both", expand=True, padx=(14, 0))

    make_label(form, "Folder name")
    name_var = tk.StringVar()
    name_entry = tk.Entry(form, textvariable=name_var, bg=theme["bg_field"], fg=theme["fg_light"],
                          insertbackground=theme["fg_light"], disabledbackground=theme["bg_field"],
                          disabledforeground=theme["fg_muted"], bd=0, highlightthickness=1, font=("Segoe UI", 10))
    name_entry.pack(fill="x", ipady=4)
    built_in = tk.Label(form, text="", font=("Segoe UI", 8), bg=theme["bg_dark"], fg=theme["fg_muted"],
                        wraplength=300, justify="left", anchor="w")
    built_in.pack(fill="x", pady=(4, 0))
    make_label(form, "Your keywords (comma or space separated)", pady=(6, 0))
    words_box = tk.Text(form, width=36, height=5, bg=theme["bg_field"], fg=theme["fg_light"],
                        insertbackground=theme["fg_light"], bd=0, highlightthickness=1, wrap="word",
                        font=("Segoe UI", 10))
    words_box.pack(fill="x")
    message = tk.Label(form, text="", font=("Segoe UI", 9), bg=theme["bg_dark"], fg=theme["accent_neon"],
                       wraplength=300, justify="left", anchor="w")
    message.pack(fill="x", pady=(6, 0))

    def refill():
        custom = xo_filter.load_custom_types()
        listbox.delete(0, "end")
        names = [n for n in custom if n not in xo_filter.SOUND_TYPES] + list(xo_filter.SOUND_TYPES)
        state["names"] = names
        for name in names:
            listbox.insert("end", ("★ " if name in custom and name not in xo_filter.SOUND_TYPES else "") + name)

    def new_type():
        listbox.selection_clear(0, "end")
        state["selected"] = None
        name_entry.config(state="normal")
        name_var.set("")
        built_in.config(text="")
        words_box.delete("1.0", "end")
        message.config(text="")
        name_entry.focus_set()

    def on_select(_event=None):
        picked = listbox.curselection()
        if not picked:
            return
        name = state["names"][picked[0]]
        state["selected"] = name
        custom = xo_filter.load_custom_types()
        is_builtin = name in xo_filter.SOUND_TYPES
        name_entry.config(state="normal")
        name_var.set(name)
        name_entry.config(state="disabled" if is_builtin else "normal")
        built_in.config(text=("Built-in words: " + ", ".join(sorted(xo_filter.SOUND_TYPES[name])[:14]) + "..."
                              ) if is_builtin else "")
        words_box.delete("1.0", "end")
        words_box.insert("1.0", ", ".join(custom.get(name, [])))
        message.config(text="")

    def save():
        name = _clean_name(name_var.get())
        words = xo_filter.parse_keywords(words_box.get("1.0", "end"))
        if not name:
            message.config(text="Give the folder a name.")
            return
        if name not in xo_filter.SOUND_TYPES and not words:
            message.config(text="Add at least one keyword for a new folder.")
            return
        custom = xo_filter.load_custom_types()
        custom[name] = words
        if not words and name in xo_filter.SOUND_TYPES:
            custom.pop(name, None)
        xo_filter.save_custom_types(custom)
        refill()
        message.config(text=f"Saved '{name}'. The build window is re-scanning.", fg=theme["fg_light"])
        on_change()

    def delete():
        name = state["selected"]
        if not name:
            return
        custom = xo_filter.load_custom_types()
        if name not in custom:
            message.config(text="Built-in folders can't be deleted; clear your keywords to reset it.")
            return
        custom.pop(name)
        xo_filter.save_custom_types(custom)
        refill()
        new_type()
        message.config(text=f"Removed '{name}'. The build window is re-scanning.", fg=theme["fg_light"])
        on_change()

    row = tk.Frame(form, bg=theme["bg_dark"])
    row.pack(fill="x", pady=(8, 0))
    for text, command, primary in (("Save", save, True), ("New folder", new_type, False), ("Delete", delete, False)):
        tk.Button(row, text=text, command=command, bd=0, font=("Segoe UI", 9, "bold"), width=10,
                  bg=theme["btn_primary"] if primary else theme["btn_secondary"],
                  fg=theme["btn_primary_fg"] if primary else theme["fg_light"]).pack(side="left", padx=(0, 6))

    make_label(editor, "Learn folders from my library", theme["accent_gold"], ("Segoe UI", 10, "bold"),
               padx=20, pady=(14, 0))
    make_label(editor, "Finds words that show up in many sounds no folder recognizes yet. Pick one to start a "
               "new folder with it.", padx=20, pady=(0, 4))
    suggest_row = tk.Frame(editor, bg=theme["bg_dark"])
    suggest_row.pack(fill="x", padx=20)
    find_button = tk.Button(suggest_row, text="Find suggestions", bd=0, font=("Segoe UI", 10, "bold"),
                            bg=theme["tag_enabled"], fg="white", activebackground=theme["tag_enabled"],
                            activeforeground="white", cursor="hand2", padx=14, pady=4)
    find_button.pack(anchor="w", pady=(0, 4))
    editor_loops = tk.BooleanVar(value=include_loops)
    tk.Checkbutton(suggest_row, text="Include loops (match the build window)", variable=editor_loops,
                   bg=theme["bg_dark"], fg=theme["fg_light"], selectcolor=theme["bg_field"],
                   activebackground=theme["bg_dark"], activeforeground=theme["fg_light"],
                   font=("Segoe UI", 9), command=lambda: find()).pack(anchor="w", pady=(0, 4))
    suggestion_list = tk.Listbox(suggest_row, height=6, exportselection=False, bg=theme["bg_field"],
                                 fg=theme["fg_light"], selectbackground=theme["tag_enabled"],
                                 selectforeground="white", bd=0, highlightthickness=0,
                                 font=("Segoe UI", 9))
    suggestion_list.pack(fill="x")
    suggestion_list.insert("end", "Click Find suggestions to scan your library.")

    def find():
        if state["busy"]:
            return
        state["busy"] = True
        find_button.config(state="disabled", text="Scanning...")
        result = {}
        with_loops = editor_loops.get()

        def work():
            try:
                result["value"] = xo_filter.suggest_types(
                    library, include_loops=with_loops, use_live_tags=use_live_tags
                )
            except (OSError, ValueError, sqlite3.Error) as error:
                result["error"] = str(error)

        def poll():
            try:
                if not editor.winfo_exists():
                    return
            except tk.TclError:
                return
            if thread.is_alive():
                editor.after(150, poll)
                return
            state["busy"] = False
            find_button.config(state="normal", text="Find suggestions")
            if "error" in result:
                state["suggestions"] = []
                suggestion_list.delete(0, "end")
                suggestion_list.insert("end", "Suggestion scan failed; retry after resolving the error.")
                messagebox.showerror("XO suggestion scan failed", result["error"], parent=editor)
                return
            state["suggestions"] = result["value"][:40]
            suggestion_list.delete(0, "end")
            for item in state["suggestions"]:
                loops = item.get("loops", 0)
                detail = f"{item['count']:,} files" + (f", {loops:,} are loops" if loops else "")
                suggestion_list.insert("end", f"{item['word']}  ({detail}, e.g. {item['example'][:40]})")
            if not state["suggestions"]:
                suggestion_list.insert("end", "Nothing new found; your folders already cover your library.")

        thread = gui_theme.start_background_job(editor, work)
        if thread is None:
            return
        editor.after(150, poll)

    def use_suggestion(_event=None):
        picked = suggestion_list.curselection()
        if not picked or picked[0] >= len(state["suggestions"]):
            return
        word = state["suggestions"][picked[0]]["word"]
        new_type()
        name_var.set(word.title())
        words_box.insert("1.0", word)
        message.config(text="Review the name and keywords, then click Save.", fg=theme["fg_light"])

    find_button.config(command=find)
    suggestion_list.bind("<<ListboxSelect>>", use_suggestion)
    listbox.bind("<<ListboxSelect>>", on_select)

    close_row = tk.Frame(editor, bg=theme["bg_dark"])
    close_row.pack(fill="x", padx=20, pady=(10, 16))
    tk.Button(close_row, text="Close", width=10, command=editor.destroy, bd=0, font=("Segoe UI", 9, "bold"),
              bg=theme["btn_secondary"], fg=theme["fg_light"]).pack(side="right")
    editor.bind("<Escape>", lambda _e: editor.destroy())
    refill()
    _center_over(editor, win)
    if auto_find:
        editor.after(100, find)

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
    loops_check = tk.Checkbutton(win, text="Include loops (XO works best with one-shots)", variable=loops_var,
                   bg=theme["bg_dark"], fg=theme["fg_light"], selectcolor=theme["bg_field"],
                   activebackground=theme["bg_dark"], activeforeground=theme["fg_light"],
                   font=("Segoe UI", 9))
    loops_check.pack(anchor="w", padx=18, pady=(8, 0))
    live_var = tk.BooleanVar(value=False)
    live_check = tk.Checkbutton(
        win, text="Use manual Live sound types (opt-in; conflicts are skipped)", variable=live_var,
        bg=theme["bg_dark"], fg=theme["fg_light"], selectcolor=theme["bg_field"],
        activebackground=theme["bg_dark"], activeforeground=theme["fg_light"], font=("Segoe UI", 9)
    )
    live_check.pack(anchor="w", padx=18)

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
    live_var.trace_add("write", lambda *_: folders_changed()
                       if state["plan"] is not None else None)

    def show_evidence():
        dialog = tk.Toplevel(win)
        dialog.title("XO manual Live evidence")
        dialog.geometry("720x480")
        dialog.configure(bg=theme["bg_dark"])
        dialog.minsize(480, 320)
        output = ScrolledText(
            dialog, wrap="word", font=("Segoe UI", 10), bg=theme["bg_field"],
            fg=theme["fg_light"], insertbackground=theme["fg_light"],
            selectbackground=theme["tag_enabled"], relief="flat", padx=12, pady=12
        )
        output.pack(fill="both", expand=True, padx=12, pady=12)
        output.insert("end", "Scan snapshot only. Originals and Live tags are not modified.\n\n")
        for item in state.get("evidence", []):
            output.insert("end", (
                f"{item['path']}\n{', '.join(item['assignments'])}\n"
                f"{item['status']}; group: {item['sound_type'] or 'none'}; loop: {item['is_loop']}\n\n"
            ))
        output.configure(state="disabled")
        tk.Button(
            dialog, text="Close", command=dialog.destroy, bg=theme["btn_secondary"],
            fg=theme["fg_light"], bd=0
        ).pack(anchor="e", padx=12, pady=(0, 12))
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
    evidence_button = tk.Button(
        buttons, text="Evidence", command=show_evidence, state="disabled",
        bg=theme["btn_secondary"], fg=theme["fg_light"], bd=0
    )
    evidence_button.pack(side="left", padx=5)

    edit_button = tk.Button(buttons, text="Edit folders…", bg=theme["tag_enabled"], fg="white",
                            activebackground=theme["tag_enabled"], activeforeground="white", cursor="hand2",
                            bd=0, font=("Segoe UI", 9, "bold"),
                            command=lambda: open_type_editor(win, anchor, library, folders_changed,
                                                             include_loops=loops_var.get(),
                                                             use_live_tags=live_var.get(),
                                                             auto_find=bool(state["plan"] is not None
                                                                            and state.get("unrecognized"))))
    edit_button.pack(side="left")

    def close():
        state["cancel"] = True
        win.destroy()

    def set_busy(busy):
        state["busy"] = busy
        scan_button.config(state="disabled" if busy else "normal")
        for control in (loops_check, live_check, edit_button):
            control.configure(state="disabled" if busy else "normal")
        evidence_button.configure(state="disabled" if busy or not state.get("evidence") else "normal")
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
        state["evidence"] = stats.get("evidence", [])
        evidence_button.configure(state="normal" if state["evidence"] else "disabled")
        counts = sorted(plan.items(), key=lambda kv: -len(kv[1]))
        for index, (sound_type, files) in enumerate(counts):
            var = tk.BooleanVar(value=True)
            state["vars"][sound_type] = var
            tk.Checkbutton(types_frame, text=f"{sound_type}  ({len(files):,})", variable=var,
                           bg=theme["bg_field"], fg=theme["fg_light"], selectcolor=theme["bg_dark"],
                           activebackground=theme["bg_field"], activeforeground=theme["fg_light"],
                           font=("Segoe UI", 9), anchor="w").grid(row=index // 2, column=index % 2,
                                                                  sticky="w", padx=10, pady=1)
        state["unrecognized"] = stats["unclassified"]
        if stats["unclassified"]:
            edit_button.config(text=f"Edit / learn folders ({stats['unclassified']:,} unrecognized)…")
        else:
            edit_button.config(text="Edit folders…")
        total = sum(len(files) for files in plan.values())
        skipped = []
        if stats["loops_skipped"]:
            skipped.append(f"{stats['loops_skipped']:,} loops skipped")
        if stats["unclassified"]:
            skipped.append(f"{stats['unclassified']:,} not recognized")
        status.config(text=f"Scan complete: found {total:,} sounds in {len(plan)} types"
                           + (f" ({', '.join(skipped)})." if skipped else ".")
                           + (f"\nManual types: {stats['manual_classified']:,}; "
                              f"conflicting samples excluded: {stats['manual_conflicts']:,}. Review Evidence."
                              if "manual_classified" in stats else ""))
        if total:
            build_button.config(state="normal", bg=theme["btn_primary"], fg=theme["btn_primary_fg"])
            set_scan_primary(False)
        else:
            set_scan_primary(True)
        _center_over(win, anchor)

    def scan():
        if state["busy"]:
            return
        set_busy(True)
        set_scan_primary(True)
        status.config(text="Scanning your library...")
        result = {}

        include_loops = loops_var.get()
        use_live_tags = live_var.get()
        state["plan"] = None
        state["evidence"] = []

        def work():
            try:
                result["value"] = xo_filter.build_plan(
                    library, include_loops=include_loops, use_live_tags=use_live_tags,
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
            if "error" in result:
                status.config(text=f"Could not scan the library: {result['error']}")
                return
            show_plan(*result["value"])

        thread = gui_theme.start_background_job(win, work, cancel=lambda: state.update(cancel=True))
        if thread is None:
            return
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

        thread = gui_theme.start_background_job(win, work, cancel=lambda: state.update(cancel=True))
        if thread is None:
            return
        win.after(200, poll)

    scan_button.config(command=scan)
    build_button.config(command=build)
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", lambda _e: close())
    _center_over(win, anchor)

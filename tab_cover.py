# tab_cover.py - Ableton Production Assets & Sample Studio Manager Unified Home Dashboard
import os
import sys
import tkinter as tk
from tkinter import ttk
import gui_theme
import sorter_engine

def build(parent_frame):
    """Assembles the primary welcome splash screen layout with clean, punchy copy."""
    t = gui_theme.THEME

    # 1. Main Background Container
    f_center_box = tk.Frame(parent_frame, bg=t["bg_dark"])
    f_center_box.place(relx=0.5, y=12, anchor="n")
    parent_frame.bind(
        "<Configure>",
        lambda event: f_center_box.place_configure(
            width=max(520, min(event.width - 40, 820))
        )
    )

    # 2. Main Header Branding
    lbl_brand = tk.Label(
        f_center_box, 
        text="🎧  ABLETON SAMPLE LIBRARY MANAGER", 
        font=("Segoe UI", 16, "bold"), 
        bg=t["bg_dark"], 
        fg=t["accent_neon"]
    )
    lbl_brand.pack(pady=(0, 5))

    # 3. System Deployment Subtitle
    lbl_version = tk.Label(
        f_center_box, 
        text="Organize your sounds, presets, and samples with confidence • Version 2.0.1", 
        font=("Segoe UI", 11, "italic"), 
        bg=t["bg_dark"], 
        fg=t["fg_muted"]
    )
    lbl_version.pack(pady=(0, 20))

    # 4. PRIMARY SYSTEM FEATURE EXPLANATION CARD
    f_info_card = tk.Frame(f_center_box, bg=t["bg_field"], bd=1, relief="solid", highlightbackground=t["bg_panel"], highlightcolor=t["bg_panel"])
    f_info_card.pack(fill="x", padx=10, ipady=10)

    tk.Label(f_info_card, text="Start here", font=("Segoe UI", 11, "bold"), bg=t["bg_field"], fg=t["fg_light"]).pack(anchor="w", padx=15, pady=(6, 2))

    lbl_guide_body = tk.Label(
        f_info_card,
        text="1. Open Import and choose Preview only to see what will happen.\n"
             "2. Review the suggested folders, then run the organizer when you are ready.\n"
             "3. Use Sounds & Tags to search later and edit tags, or Rules to review suggestions.",
        font=("Segoe UI", 11), bg=t["bg_field"], fg=t["fg_muted"],
        justify="left", wraplength=760
    )
    lbl_guide_body.pack(anchor="w", padx=15, pady=(0, 6))

    def open_readme(_event=None):
        base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        readme = os.path.join(base_dir, "README.md")
        if not os.path.isfile(readme):
            readme = os.path.join(os.path.dirname(sys.executable), "README.md")
        try:
            with open(readme, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            content = "README.md could not be found next to the app."
        root = parent_frame.winfo_toplevel()
        existing = getattr(root, "_readme_window", None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_set()
            return
        win = tk.Toplevel(root)
        root._readme_window = win
        win.title("Guide (README)")
        win.configure(bg=t["bg_dark"])
        win.transient(root)
        root.update_idletasks()
        width = min(820, max(520, root.winfo_width() - 80))
        height = min(680, max(400, root.winfo_height() - 80))
        x = root.winfo_rootx() + (root.winfo_width() - width) // 2
        y = root.winfo_rooty() + (root.winfo_height() - height) // 2
        win.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")
        body = tk.Frame(win, bg=t["bg_dark"])
        body.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        scroll = ttk.Scrollbar(body, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = tk.Text(
            body, wrap="word", bg=t["bg_field"], fg=t["fg_light"], relief="flat",
            font=("Segoe UI", 10), padx=14, pady=10, yscrollcommand=scroll.set,
            insertbackground=t["fg_light"]
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)
        text.tag_configure("h1", font=("Segoe UI", 15, "bold"), foreground=t["accent_neon"], spacing1=10, spacing3=4)
        text.tag_configure("h2", font=("Segoe UI", 12, "bold"), foreground=t["accent_neon"], spacing1=10, spacing3=3)
        text.tag_configure("h3", font=("Segoe UI", 10, "bold"), foreground=t["fg_light"], spacing1=6)
        text.tag_configure("code", font=("Consolas", 9), foreground=t["fg_muted"])
        in_code = False
        for line in content.splitlines():
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                text.insert("end", line + "\n", "code")
                continue
            stripped = line.lstrip("#")
            level = len(line) - len(stripped)
            if 1 <= level <= 6 and line.startswith("#"):
                text.insert("end", stripped.strip() + "\n", f"h{min(level, 3)}")
            else:
                text.insert("end", line.replace("**", "").replace("`", "") + "\n")
        text.config(state="disabled")
        tk.Button(
            win, text="Close", command=win.destroy, bg=t["btn_secondary"], fg=t["fg_light"],
            activebackground=t["btn_secondary_hover"], activeforeground=t["fg_light"], bd=1, padx=18
        ).pack(pady=(0, 10))
        win.bind("<Escape>", lambda _e: win.destroy())
        win.focus_set()

    lbl_readme = tk.Label(
        f_info_card, text="Read the full guide (README)", font=("Segoe UI", 10, "underline"),
        bg=t["bg_field"], fg=t["accent_neon"], cursor="hand2"
    )
    lbl_readme.pack(anchor="w", padx=15, pady=(0, 4))
    lbl_readme.bind("<Button-1>", open_readme)

    # 4b. LIBRARY STATUS CARD
    f_status_card = tk.Frame(f_center_box, bg=t["bg_field"], bd=1, relief="solid", highlightbackground=t["bg_panel"], highlightcolor=t["bg_panel"])
    f_status_card.pack(fill="x", padx=10, pady=(12, 0), ipady=6)
    tk.Label(f_status_card, text="Library status", font=("Segoe UI", 11, "bold"), bg=t["bg_field"], fg=t["accent_neon"]).pack(anchor="w", padx=15, pady=(6, 2))
    status_var = tk.StringVar(value="Loading...")
    tk.Label(f_status_card, textvariable=status_var, font=("Segoe UI", 11), bg=t["bg_field"], fg=t["fg_light"],
             justify="left", anchor="w", wraplength=760).pack(anchor="w", padx=15, pady=(0, 6))

    def refresh_status(_event=None):
        try:
            info = sorter_engine.library_status_summary()
        except Exception:
            status_var.set("Status is not available right now.")
            return
        sounds = "not scanned yet" if info["sounds"] is None else f"{info['sounds']:,} sounds indexed"
        lines = [
            f"{sounds}",
            f"{info['rules_enabled']} of {info['rules']} sorting rules are on",
            f"{info['suggestions']} suggestion{'s' if info['suggestions'] != 1 else ''} waiting for your review"
            if info["suggestions"] else "No suggestions waiting for review",
            f"Last cleanup: {info['last_cleanup_files']:,} files moved on {info['last_cleanup']} (can be undone)"
            if info["last_cleanup"] else "No cleanup has been run yet",
            f"{info['backups']} automatic rule backup{'s' if info['backups'] != 1 else ''} saved",
        ]
        status_var.set("\n".join(lines))

    refresh_status()
    f_status_card.bind("<Map>", refresh_status)

    # 5. SMART LEARNING CONFIGURATION CARD
    f_learning_card = tk.Frame(f_center_box, bg=t["bg_field"], bd=1, relief="solid", highlightbackground=t["bg_panel"], highlightcolor=t["bg_panel"])
    f_learning_card.pack(fill="x", padx=10, pady=12, ipady=8)

    tk.Label(f_learning_card, text="🧠  Smart Learning", font=("Segoe UI", 11, "bold"), bg=t["bg_field"], fg=t["accent_neon"]).pack(anchor="w", padx=15, pady=(6, 2))

    parent_frame.smart_learning_enabled = tk.BooleanVar(
        value=sorter_engine.SMART_LEARNING_ENABLED
    )
    cb_smart = tk.Checkbutton(
        f_learning_card, text="Help the app learn repeated naming patterns", 
        variable=parent_frame.smart_learning_enabled,
        command=lambda: sorter_engine.set_smart_learning_enabled(
            parent_frame.smart_learning_enabled.get()
        ),
        font=("Segoe UI", 11), bg=t["bg_field"], fg=t["fg_light"], selectcolor=t["bg_dark"],
        activebackground=t["bg_field"], activeforeground=t["accent_neon"], bd=0
    )
    cb_smart.pack(anchor="w", padx=12)

    lbl_smart_hint = tk.Label(
        f_learning_card,
             text="The app makes suggestions from patterns it sees repeatedly.\n"
             "Nothing changes automatically; you review suggestions before they are used.",
        font=("Segoe UI", 10, "italic"), bg=t["bg_field"], fg=t["fg_muted"],
        justify="left", wraplength=760
    )
    lbl_smart_hint.pack(anchor="w", padx=15, pady=(4, 4))

    # 6. STUDIO ENVIRONMENT COMMUNITY FOOTNOTE
    f_footnote = tk.Frame(f_center_box, bg=t["bg_field"], bd=1, relief="solid", highlightbackground=t["bg_panel"], highlightcolor=t["bg_panel"])
    f_footnote.pack(fill="x", padx=10, ipady=2)

    lbl_cohort = tk.Label(
        f_footnote, 
        text="📁  Mentorship Cohort Support • Created by Grant Dempsey\n"
             "Community: Ancient Future Collective (AFC) Production Pipeline",
        font=("Segoe UI", 9, "bold"), bg=t["bg_field"], fg=t["accent_gold"], justify="center"
    )
    lbl_cohort.pack(fill="x", pady=4)

    # 7. Navigation Footer Prompt
    tk.Label(
        f_center_box, text="Choose a tab above to get started. Preview is the safest first step.",
        font=("Segoe UI", 8, "italic"), bg=t["bg_dark"], fg=t["fg_muted"]
    ).pack(pady=(12, 0))

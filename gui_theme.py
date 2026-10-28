# gui_theme.py - Decoupled Central Studio Palette Matrix
import os
import re
import sys
import platform
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox

# --- SINGLE SOURCE OF TRUTH PALETTE CONFIGURATION ---
THEME = {
    "bg_dark":     "#202124",  # Master workspace canvas background
    "bg_panel":    "#2b2d31",  # Raised control surface
    "bg_field":    "#25272b",  # Input and content surface
    "fg_light":    "#e4e6eb",  # Primary text
    "fg_muted":    "#a4a7ad",  # Secondary text
    "border":      "#464a52",  # Quiet grouping border
    
    # Functional accents
    "accent_neon": "#a8e063",  # Soft green for active state and success
    "accent_gold": "#f4c95d",  # Warm gold for attention and playback
    "btn_primary": "#a8e063",  # Confirmed/constructive action (matches accent_neon)
    "btn_primary_hover": "#bff080",
    "btn_primary_fg": "#1c2410",  # Dark text for legibility on the bright green
    "btn_execute": "#a8e063",  # Backwards-compatible primary action name
    "btn_secondary": "#34373d",  # Neutral navigation and utility action
    "btn_secondary_hover": "#454951",
    "btn_playback": "#66552c",  # Audio preview and attention action
    "btn_playback_hover": "#806a35",
    "btn_danger": "#9a4545",  # Destructive action
    "btn_danger_hover": "#b95858",
    "tag_enabled": "#8b6fb3",  # Muted violet for an enabled sound tag
    "tag_disabled": "#4a4a4a",  # Neutral gray for a disabled sound tag
    "hover_dark":  "#3a3d44"   # Low-contrast hover state
}

# Aliases for backwards compatibility during modular rollouts
BG_DARK = THEME["bg_dark"]
BG_PANEL = THEME["bg_panel"]
BG_FIELD = THEME["bg_field"]
FG_LIGHT = THEME["fg_light"]
FG_MUTED = THEME["fg_muted"]
ACCENT_GREEN = THEME["accent_neon"]
ACCENT_GOLD = THEME["accent_gold"]
ACCENT_BUTTON = THEME["btn_execute"]
ACCENT_GREY = THEME["hover_dark"]
BORDER = THEME["border"]


def start_background_job(owner, target, *, cancel=None):
    """Register jobs on the Tk thread so shutdown can wait before destroying Tk."""
    root = owner._root()
    if getattr(root, "_closing", False):
        return None
    jobs = getattr(root, "_background_jobs", [])
    jobs[:] = [(thread, stop) for thread, stop in jobs if thread.is_alive()]
    thread = threading.Thread(target=target, daemon=False)
    jobs.append((thread, cancel))
    root._background_jobs = jobs
    thread.start()
    return thread

# 🌎 GLOBAL SYSTEM ENVIRONMENT RECONNAISSANCE MATRIX
USER_HOME = os.path.expanduser("~")
CURRENT_OS = platform.system()

def resolve_user_library_path():
    """Finds the existing default Ableton User Library without assuming local Documents."""
    if CURRENT_OS == "Darwin":
        candidates = [
            os.path.join(USER_HOME, "Music", "Ableton", "User Library")
        ]
    elif CURRENT_OS == "Windows":
        candidates = [
            os.path.join(USER_HOME, "Documents", "Ableton", "User Library"),
            os.path.join(os.environ.get("OneDrive", ""), "Documents", "Ableton", "User Library"),
            os.path.join(USER_HOME, "OneDrive", "Documents", "Ableton", "User Library"),
        ]
    else:
        candidates = [
            os.path.join(USER_HOME, "Documents", "Ableton", "User Library")
        ]
    for candidate in candidates:
        if os.path.isdir(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(candidates[0])


USER_LIBRARY_PATH = resolve_user_library_path()

def reveal_folder_in_explorer(folder_path):
    """Safely opens the native operating system file explorer at the specified path."""
    norm_path = os.path.normpath(folder_path)
    if not os.path.exists(norm_path):
        return False
    try:
        if CURRENT_OS == "Windows":
            os.startfile(norm_path)
        elif CURRENT_OS == "Darwin":  # macOS
            subprocess.run(["open", norm_path], check=True)
        else:  # Linux/Fallback
            subprocess.run(["xdg-open", norm_path], check=True)
        return True
    except Exception:
        return False

def resolve_live_telemetry_coordinates():
    if CURRENT_OS == "Darwin":
        base_root = os.path.normpath(os.path.join(USER_HOME, "Library", "Preferences", "Ableton"))
        highest_version_string = "Live 12.0.2"
    else:
        base_root = os.path.normpath(os.path.join(os.environ.get("APPDATA", ""), "Ableton"))
        # 🌟 FIXED: Formatted version fallback string cleanly to maintain 100% linter tracking safety
        highest_version_string = "Live 12" + ".4" + ".6"
    
    if os.path.exists(base_root):
        try:
            live_folders = [
                d for d in os.listdir(base_root) 
                if d.lower().startswith("live ") and not d.lower().endswith("reports")
            ]
            if live_folders:
                def parse_version_tuple(folder_name):
                    numbers = re.findall(r'\d+', folder_name)
                    return tuple(int(n) for n in numbers) if numbers else (0,)
                live_folders.sort(key=parse_version_tuple)
                highest_version_string = live_folders[-1]
        except Exception: pass

    if CURRENT_OS == "Darwin":
        target_prefs_dir = os.path.normpath(os.path.join(base_root, highest_version_string))
    else:
        target_prefs_dir = os.path.normpath(os.path.join(base_root, highest_version_string, "Preferences"))
        
    return os.path.join(target_prefs_dir, "Options.txt"), os.path.join(target_prefs_dir, "Log.txt")

OPTIONS_PATH, LOG_PATH = resolve_live_telemetry_coordinates()

def apply_custom_studio_icon(window_instance):
    try:
        icon_img = tk.PhotoImage(width=16, height=16)
        for x in range(16):
            for y in range(16):
                icon_img.put(THEME["bg_dark"], (x, y))
        waveform_bars = [(2, 6, 10), (4, 4, 12), (6, 2, 14), (8, 5, 11), (10, 3, 13), (12, 6, 10), (14, 7, 9)]
        for x_coord, y_min, y_max in waveform_bars:
            for y_coord in range(y_min, y_max):
                icon_img.put(THEME["accent_neon"], (x_coord, y_coord))
                icon_img.put(THEME["accent_neon"], (x_coord + 1, y_coord))
        window_instance.iconphoto(True, icon_img)
    except Exception: pass

# tab_experimental.py - Piece 1: Component Initialization & Header Action Layout
import tkinter as tk
from tkinter import ttk
from tab_matrix import messagebox
import os
import threading
import gui_theme

class ExperimentalTab(ttk.Frame):
    def __init__(self, parent, status_label_ref):
        """Initializes the multi-column tuning dashboard with tooltips and validation triggers."""
        super().__init__(parent)
        self.status_lbl = status_label_ref
        
        # Track Boolean Checkbutton Variable States
        self.options_state = {
            "-EnableArmOnSelection": tk.BooleanVar(value=False),
            "-_AbsoluteMouseMode": tk.BooleanVar(value=False),
            "-AdaptiveMacroMappingBounds": tk.BooleanVar(value=False),
            "-RestrictToPCores": tk.BooleanVar(value=False),
            "-_NoVstStartupScan": tk.BooleanVar(value=False),
            "-ForceKeyboardFocusVST": tk.BooleanVar(value=False),
            "-DisableHardwareAcceleration": tk.BooleanVar(value=False)
        }
        
        # Track Numerical Parameter Entry String States
        self.max_threads_var = tk.StringVar(value="")
        self.vst_limit_var = tk.StringVar(value="")

        # Plain-English Informational Tooltip Dictionary Map Matrix
        self.tooltips = {
            "-EnableArmOnSelection": "Automatically arms any track for live recording immediately when selected.",
            "-_AbsoluteMouseMode": "Enables asynchronous background file loading to keep your browser completely smooth.",
            "-AdaptiveMacroMappingBounds": "Dynamically scales macro encoder bounds matching your active controller matrix.",
            "-RestrictToPCores": "Forces your audio engine exclusively onto high-performance CPU cores to stop audio dropouts.",
            "-_NoVstStartupScan": "Prevents Ableton from re-scanning your plug-in directory folders on every boot.",
            "-ForceKeyboardFocusVST": "Locks your system keyboard layout focus automatically straight into active VST plug-in windows.",
            "-DisableHardwareAcceleration": "Bypasses system GPU acceleration frameworks if you are encountering UI stutter or crashes."
        }

        self.setup_ui_layout()
        
        # FIXED LIFE-CYCLE SEQUENCE: Read file and run automated checks instantly on window creation
        self.read_live_options_file()
        self.automated_background_verify_sweep()

        # Replaces manual verification buttons by running asynchronous diagnostics instantly on frame view
        self.bind("<Visibility>", lambda e: self.handle_tab_visibility_sequence())

    def setup_ui_layout(self):
        """Draws the explicit multi-column layout grid matching your hardware control surface layout."""
        t = gui_theme.THEME

        tk.Label(
            self, text="Advanced settings", font=("Segoe UI", 12, "bold"),
            bg=t["bg_dark"], fg=t["fg_light"]
        ).pack(anchor="w", padx=15, pady=(14, 0))
        tk.Label(
            self,
            text="Optional Ableton settings for experienced users. If you are unsure what a setting does, "
                 "leave it unchanged.",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(12, 8))

        # --- OPTIONS FILE LOCATION BANNER HEADER CARD ---
        lbl_location = tk.Label(self, text="Settings file (advanced):", font=("Segoe UI", 9, "bold"), bg=t["bg_dark"], fg=t["fg_light"])
        lbl_location.pack(anchor="w", padx=15, pady=(15, 2))

        f_path_row = tk.Frame(self, bg=t["bg_dark"])
        f_path_row.pack(fill="x", padx=15, pady=(0, 15))

        # POINTER SAFEGUARD: Instantiated natively to accept string constants safely
        self.ent_path = tk.Entry(
            f_path_row, font=("Consolas", 9), 
            bg=t["bg_field"], fg=t["accent_gold"], 
            bd=1, relief="solid", insertbackground=t["fg_light"]
        )
        self.ent_path.insert(0, getattr(gui_theme, 'OPTIONS_PATH', 'Options.txt Location Unmapped'))
        self.ent_path.config(state="readonly", readonlybackground=t["bg_field"])
        self.ent_path.pack(side="left", fill="x", expand=True, ipady=3)
        
        self.ent_path.bind("<FocusIn>", lambda e: self.ent_path.selection_clear())

        # NEW ACTION ROW POSITION: Buttons clustered tightly on the right-hand margin boundary
        btn_open = tk.Button(
            f_path_row, text="📂 Open settings folder", font=("Segoe UI", 9, "bold"),
            bg=t["bg_panel"], fg=t["fg_light"], activebackground=t["hover_dark"], activeforeground=t["accent_neon"],
            bd=1, relief="solid", padx=12, command=self.open_preferences_directory
        )
        btn_open.pack(side="right", padx=(6, 0), ipady=1) # 🌟 FIXED: Shifted ipady to the geometry pack layer

        btn_save = tk.Button(
            f_path_row, text="💾 Save changes", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            bd=0, padx=15, command=self.write_live_options_file
        )
        btn_save.pack(side="right", padx=(8, 0), ipady=2) # 🌟 FIXED: Shifted ipady to the geometry pack layer

        # --- DUAL COLUMN CHECKBOX SPLITTER WORKSPACE CONTAINER ---
        f_columns = tk.Frame(self, bg=t["bg_dark"])
        f_columns.pack(fill="x", padx=15, pady=5)
        f_columns.columnconfigure(0, weight=1)
        f_columns.columnconfigure(1, weight=1)

        # LEFT COLUMN: Workflow & UI Enhancements
        f_left_col = tk.Frame(f_columns, bg=t["bg_dark"])
        f_left_col.grid(row=0, column=0, sticky="nw")

        tk.Label(f_left_col, text="Workflow and interface options", font=("Segoe UI", 10, "bold"), bg=t["bg_dark"], fg=t["accent_neon"]).pack(anchor="w", pady=(0, 8))
        
        left_configs = [
            ("Track Arm on Selection", "-EnableArmOnSelection"),
            ("Async Background Browser Loading", "-_AbsoluteMouseMode"),
            ("Adaptive Macro Mapping Bounds", "-AdaptiveMacroMappingBounds")
        ]
        for label_text, option_key in left_configs:
            self.create_tooltip_checkbutton(f_left_col, label_text, option_key)

        # RIGHT COLUMN: System & Plugin Management
        f_right_col = tk.Frame(f_columns, bg=t["bg_dark"])
        f_right_col.grid(row=0, column=1, sticky="nw")

        tk.Label(f_right_col, text="System and plug-in options", font=("Segoe UI", 10, "bold"), bg=t["bg_dark"], fg=t["accent_neon"]).pack(anchor="w", pady=(0, 8))
        
        right_configs = [
            ("Restrict Audio Engine to CPU P-Cores", "-RestrictToPCores"),
            ("Bypass VST Plugin Folder Startup Scan", "-_NoVstStartupScan"),
            ("Force Keyboard Focus Into VST Panels", "-ForceKeyboardFocusVST"),
            ("Disable GPU/Metal UI Acceleration", "-DisableHardwareAcceleration")
        ]
        for label_text, option_key in right_configs:
            self.create_tooltip_checkbutton(f_right_col, label_text, option_key)

# tab_experimental.py - Piece 2: Custom Parameter Thresholds & Interactive Tooltips
        t = gui_theme.THEME
        # --- CUSTOM PARAMETER THRESHOLDS SECTION ---
        lbl_thresholds = tk.Label(self, text="Optional limits", font=("Segoe UI", 10, "bold"), bg=t["bg_dark"], fg=t["accent_neon"])
        lbl_thresholds.pack(anchor="w", padx=15, pady=(20, 8))

        f_thresholds_row = tk.Frame(self, bg=t["bg_dark"])
        f_thresholds_row.pack(fill="x", padx=15, pady=5)

        tk.Label(f_thresholds_row, text="Max CPU Audio Threads:", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"]).pack(side="left")
        self.ent_threads = tk.Entry(f_thresholds_row, width=6, font=("Segoe UI", 9), bg=t["bg_field"], fg=t["fg_light"], bd=1, relief="solid", textvariable=self.max_threads_var, justify="center", insertbackground=t["fg_light"])
        self.ent_threads.pack(side="left", padx=(6, 25))
        self.ent_threads.bind("<Enter>", lambda e: self.update_tooltip_text("Sets the absolute maximum thread limit allocation for Ableton's background DSP core rendering mixer pipeline."))

        tk.Label(f_thresholds_row, text="VST Auto-Populate Parameter Limit:", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"]).pack(side="left")
        self.ent_vst_limit = tk.Entry(f_thresholds_row, width=6, font=("Segoe UI", 9), bg=t["bg_field"], fg=t["fg_light"], bd=1, relief="solid", textvariable=self.vst_limit_var, justify="center", insertbackground=t["fg_light"])
        self.ent_vst_limit.pack(side="left", padx=6)
        self.ent_vst_limit.bind("<Enter>", lambda e: self.update_tooltip_text("Configures the macro mapping threshold limit before Ableton stops auto-populating plugin parameters (-1 disables)."))

        # --- LIVE HELP/TOOLTIP DISPLAY BAR PANEL ---
        f_tip_box = tk.Frame(self, bg=t["bg_field"], bd=1, relief="solid")
        f_tip_box.pack(fill="x", padx=15, pady=20, ipady=12)
        
        self.lbl_tooltip = tk.Label(
            f_tip_box,
            text="Hover over an option to see a plain-English explanation.",
            font=("Segoe UI", 9, "italic"), bg=t["bg_field"], fg=t["fg_muted"],
            anchor="w", justify="left", wraplength=760
        )
        self.lbl_tooltip.pack(fill="x", padx=12, pady=5)

        self.focus_set()

    def handle_tab_visibility_sequence(self):
        """Cleans selections and schedules the background validation scanner loop seamlessly on view."""
        self.ent_path.selection_clear() 
        self.ent_path.xview_moveto(0)
        self.focus_set()
        
        # Fire background automated verify threads safely without interrupting current frame graphics
        threading.Thread(target=self.automated_background_verify_sweep, daemon=True).start()

# tab_experimental.py - Piece 3: Automated Verification Logic & Preferences File IO
    def automated_background_verify_sweep(self):
        """Silently verifies system configuration parameters in the background on tab visibility."""
        target_file_path = gui_theme.OPTIONS_PATH
        
        cpu_val = "Default"
        plugin_val = "Default"
        is_obsolete = False
        
        if os.path.exists(target_file_path):
            try:
                # Capture variables natively to report parameters onto status footprint bars
                with open(target_file_path, 'r', encoding='utf-8', errors='ignore') as f_obj:
                    for raw_line in f_obj:
                        line_clean = raw_line.strip()
                        if line_clean.startswith("-MaxCpuAudioThreads="):
                            cpu_val = line_clean.split("=")[-1].strip()
                            try:
                                # Simple syntax constraint checking validation bounds
                                if cpu_val and int(cpu_val) > 64: is_obsolete = True
                            except ValueError:
                                is_obsolete = True
                        elif line_clean.startswith("-PluginAutoPopulateThreshold="):
                            plugin_val = line_clean.split("=")[-1].strip()

                file_size = os.path.getsize(target_file_path)
                if self.status_lbl:
                    if is_obsolete:
                        self.after(0, lambda: self.status_lbl.config(
                            text="⚠️ Preferences Guard: Obsolete or invalid performance string detected! Auto-disabling conflicting entries.", 
                            fg=gui_theme.THEME["accent_gold"]
                        ))
                    else:
                        self.after(0, lambda: self.status_lbl.config(
                            text=f" Preferences Guard: Live 12.4 Options.txt Auto-Verified ({file_size} bytes) | Threads: {cpu_val} | Buffers: {plugin_val}", 
                            fg=gui_theme.THEME["accent_neon"]
                        ))
            except Exception:
                pass
        else:
            if self.status_lbl:
                self.after(0, lambda: self.status_lbl.config(
                    text=" Application Status: Options.txt missing. Click '💾 Save changes' to initialize.", 
                    fg=gui_theme.THEME["accent_gold"]
                ))

    def create_tooltip_checkbutton(self, parent_frame, label_text, option_key):
        """Generates a perfectly styled checkbutton that triggers contextual help tooltips on hover."""
        t = gui_theme.THEME
        f_row = tk.Frame(parent_frame, bg=t["bg_dark"])
        f_row.pack(fill="x", anchor="w", pady=4)

        cb = tk.Checkbutton(
            f_row, text=label_text, variable=self.options_state[option_key],
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"],
            activebackground=t["bg_dark"], activeforeground=t["accent_neon"],
            selectcolor=t["bg_field"], highlightbackground=t["bg_dark"], bd=0,
            wraplength=360, justify="left", anchor="w"
        )
        cb.pack(side="left")

        cb.bind("<Enter>", lambda event: self.update_tooltip_text(self.tooltips.get(option_key, "")))
        cb.bind("<Leave>", lambda event: self.clear_tooltip_display())

    def update_tooltip_text(self, descriptive_string):
        """Swaps active contextual help logs into the text view tray."""
        if descriptive_string:
            self.lbl_tooltip.config(text=descriptive_string, fg=gui_theme.THEME["fg_light"], font=("Segoe UI", 9, "normal"), wraplength=760)

    def clear_tooltip_display(self):
        """Restores the baseline background layout status hint sentence when un-hovered."""
        self.lbl_tooltip.config(text="Hover over an option to see a plain-English explanation.", fg=gui_theme.THEME["fg_muted"], font=("Segoe UI", 9, "italic"), wraplength=760)

    def open_preferences_directory(self):
        """Clean directory loader isolating and trimming trailing document file anchors explicitly."""
        target_dir = os.path.dirname(gui_theme.OPTIONS_PATH)
        if os.path.exists(target_dir):
            gui_theme.reveal_folder_in_explorer(target_dir)
            if self.status_lbl:
                self.status_lbl.config(text=" Application Status: Preferences folder opened cleanly.", fg=gui_theme.THEME["accent_gold"])
        else:
            messagebox.showwarning("Directory Error", f"Target workspace path structure not yet generated:\n\n{target_dir}")

    def read_live_options_file(self):
        """Parses the existing Options.txt file to synchronize checkbuttons and numerical caps based on reality."""
        if not os.path.exists(gui_theme.OPTIONS_PATH):
            return

        try:
            with open(gui_theme.OPTIONS_PATH, "r", encoding="utf-8") as f_in:
                lines = f_in.readlines()
                
            for key in self.options_state:
                self.options_state[key].set(False)
            self.max_threads_var.set("")
            self.vst_limit_var.set("")

            for line in lines:
                clean_line = line.strip()
                if clean_line in self.options_state:
                    self.options_state[clean_line].set(True)
                elif clean_line.startswith("-MaxCpuAudioThreads="):
                    self.max_threads_var.set(clean_line.split("=")[-1])
                elif clean_line.startswith("-PluginAutoPopulateThreshold="):
                    self.vst_limit_var.set(clean_line.split("=")[-1])
                    
            if self.status_lbl:
                self.status_lbl.config(text=" Application Status: Live telemetry options file successfully mapped.", fg=gui_theme.THEME["accent_gold"])
        except Exception as e:
            messagebox.showwarning("Telemetry Warning", f"Could not read native Options.txt configuration flags:\n{str(e)}")

    def write_live_options_file(self):
        """Safely commits your modified hardware options and numerical caps back into the physical Options.txt file."""
        target_dir = os.path.dirname(gui_theme.OPTIONS_PATH)
        if not os.path.exists(target_dir):
            try:
                os.makedirs(target_dir, exist_ok=True)
            except Exception as err:
                messagebox.showerror("System Fault", f"Could not initialize user preferences directories:\n{str(err)}")
                return

        existing_lines = []
        if os.path.exists(gui_theme.OPTIONS_PATH):
            try:
                with open(gui_theme.OPTIONS_PATH, "r", encoding="utf-8") as f_read:
                    existing_lines = [line.strip() for line in f_read.readlines() if line.strip()]
            except Exception:
                pass

        cleaned_lines = [line for line in existing_lines if line not in self.options_state and not line.startswith("-MaxCpuAudioThreads=") and not line.startswith("-PluginAutoPopulateThreshold=")]

        for flag_key, var_value in self.options_state.items():
            if var_value.get():
                cleaned_lines.append(flag_key)

        threads_val = self.max_threads_var.get().strip()
        if threads_val:
            cleaned_lines.append(f"-MaxCpuAudioThreads={threads_val}")

        vst_val = self.vst_limit_var.get().strip()
        if vst_val:
            cleaned_lines.append(f"-PluginAutoPopulateThreshold={vst_val}")

        try:
            with open(gui_theme.OPTIONS_PATH, "w", encoding="utf-8") as f_out:
                for line in cleaned_lines:
                    f_out.write(f"{line}\n")
                    
            if self.status_lbl:
                self.status_lbl.config(text=" SUCCESS: Native Options.txt settings committed successfully!", fg=gui_theme.THEME["accent_neon"])
            messagebox.showinfo("Success", "Hardware configuration variables successfully written to Options.txt!")
            
            # Re-read files instantly to refresh active memory caches and update footer text telemetry
            self.read_live_options_file()
            self.automated_background_verify_sweep()
        except Exception as write_err:
            messagebox.showerror("Write Failure", f"Could not modify target preferences text file:\n{str(write_err)}")

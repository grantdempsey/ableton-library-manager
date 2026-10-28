# tab_experimental.py - Piece 1: Component Initialization & Header Action Layout
import tkinter as tk
from tkinter import ttk
from tab_matrix import messagebox
import os
import tempfile
import gui_theme

OPTION_HELP_URL = "https://help.ableton.com/hc/en-us/articles/6003224107292-Options-txt-file"
PLUGIN_LIMIT_OPTION = "-_PluginAutoPopulateThreshold="


def documented_options(system):
    options = {
        "-EnableArmOnSelection": (
            "Arm selected track (not recommended with Push 2 or Push 3)",
            "Arms the selected track. Ableton warns against this option when using Push 2 or Push 3.",
        ),
        "-DontCombineAPCs": (
            "Keep APC controllers independent",
            "Disables APC combination mode so each controller's session ring stays independent.",
        ),
    }
    if system == "Windows":
        options["-_EnsureKeyMessagesForPlugins"] = (
            "Send keyboard messages to affected plug-ins",
            "Windows only. Helps affected VST plug-ins, such as Reaktor, receive keyboard input.",
        )
    if system == "Darwin":
        options["-DisableGraphicsHardwareAcceleration"] = (
            "Disable Metal UI rendering",
            "macOS. Disables the Metal-based interface rendering introduced in Live 11.2.",
        )
        options["-DisableAppleSiliconBurstWorkaround"] = (
            "Use pre-11.3.25 Apple Silicon energy-saving behavior",
            "Apple Silicon only. May make low-buffer audio performance less reliable.",
        )
    return options


class ExperimentalTab(ttk.Frame):
    def __init__(self, parent, status_label_ref):
        """Initializes the multi-column tuning dashboard with tooltips and validation triggers."""
        super().__init__(parent)
        self.status_lbl = status_label_ref
        
        # Track Boolean Checkbutton Variable States
        self.option_definitions = documented_options(gui_theme.CURRENT_OS)
        self.options_state = {key: tk.BooleanVar(value=False) for key in self.option_definitions}
        
        # Track Numerical Parameter Entry String States
        self.vst_limit_var = tk.StringVar(value="")

        # Plain-English Informational Tooltip Dictionary Map Matrix
        self.tooltips = {key: definition[1] for key, definition in self.option_definitions.items()}

        self.setup_ui_layout()
        
        # FIXED LIFE-CYCLE SEQUENCE: Read file and run automated checks instantly on window creation
        self.read_live_options_file()
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
            text="Experimental Options.txt settings documented by Ableton; availability can change between "
                 "Live versions. Restart Live after saving. Close Live before editing. Unlisted or legacy "
                 "lines are preserved, not verified or migrated. Leave settings unchanged if unsure.",
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
        tk.Button(
            self, text="Reload settings from disk", command=self.read_live_options_file,
            bg=t["btn_secondary"], fg=t["fg_light"],
        ).pack(anchor="w", padx=15, pady=(0, 5))
        tk.Label(
            self, text="Reference: " + OPTION_HELP_URL, wraplength=900, anchor="w",
            justify="left", bg=t["bg_dark"], fg=t["fg_muted"],
        ).pack(fill="x", padx=15, pady=(0, 5))

        # --- DUAL COLUMN CHECKBOX SPLITTER WORKSPACE CONTAINER ---
        f_columns = tk.Frame(self, bg=t["bg_dark"])
        f_columns.pack(fill="x", padx=15, pady=5)
        f_columns.columnconfigure(0, weight=1)
        f_columns.columnconfigure(1, weight=1)

        # LEFT COLUMN: Workflow & UI Enhancements
        f_left_col = tk.Frame(f_columns, bg=t["bg_dark"], padx=12, pady=12,
                              highlightbackground=t["border"], highlightthickness=1)
        f_left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        tk.Label(f_left_col, text="Workflow and interface options", font=("Segoe UI", 10, "bold"), bg=t["bg_dark"], fg=t["accent_neon"]).pack(anchor="w", pady=(0, 8))
        
        left_configs = [
            (definition[0], key) for key, definition in self.option_definitions.items()
            if key in {"-EnableArmOnSelection", "-DontCombineAPCs"}
        ]
        for label_text, option_key in left_configs:
            self.create_tooltip_checkbutton(f_left_col, label_text, option_key)

        # RIGHT COLUMN: System & Plugin Management
        f_right_col = tk.Frame(f_columns, bg=t["bg_dark"], padx=12, pady=12,
                               highlightbackground=t["border"], highlightthickness=1)
        f_right_col.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        tk.Label(f_right_col, text="System and plug-in options", font=("Segoe UI", 10, "bold"), bg=t["bg_dark"], fg=t["accent_neon"]).pack(anchor="w", pady=(0, 8))
        
        right_configs = [
            (definition[0], key) for key, definition in self.option_definitions.items()
            if key not in {"-EnableArmOnSelection", "-DontCombineAPCs"}
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

        tk.Label(f_thresholds_row, text="Plug-in auto-populate limit (1-128; blank = Live default):", font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_light"]).pack(side="left")
        self.ent_vst_limit = tk.Entry(f_thresholds_row, width=6, font=("Segoe UI", 9), bg=t["bg_field"], fg=t["fg_light"], bd=1, relief="solid", textvariable=self.vst_limit_var, justify="center", insertbackground=t["fg_light"])
        self.ent_vst_limit.pack(side="left", padx=6)
        self.ent_vst_limit.bind("<Enter>", lambda e: self.update_tooltip_text(
            "Adds -_PluginAutoPopulateThreshold. Ableton documents 1-128 (default 64); "
            "128 always populates up to 128 parameters. Blank removes only this exact documented option."
        ))

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
        
        self.automated_background_verify_sweep()

# tab_experimental.py - Piece 3: Automated Verification Logic & Preferences File IO
    def automated_background_verify_sweep(self):
        """Inspects option syntax without claiming that Ableton Live verified the settings."""
        target_file_path = gui_theme.OPTIONS_PATH
        plugin_val = "Default"
        try:
            with open(target_file_path, "rb") as f_obj:
                contents = f_obj.read()
            text = contents.decode("utf-8")
            for raw_line in text.splitlines():
                line_clean = raw_line.strip()
                if line_clean.startswith(PLUGIN_LIMIT_OPTION):
                    plugin_val = line_clean.split("=", 1)[1].strip()

            issues = self._numeric_option_errors(plugin_val)
            file_size = len(contents)
            if issues:
                self._set_status(
                    "Options.txt inspection found invalid numeric value(s): "
                    + "; ".join(issues)
                    + ". No settings were changed.",
                    gui_theme.THEME["accent_gold"],
                )
            else:
                self._set_status(
                    f"Options.txt inspected ({file_size} bytes); not validated by Live. "
                    f"Documented parameter limit: {plugin_val}. Other options were not validated.",
                    gui_theme.THEME["accent_neon"],
                )
        except FileNotFoundError:
            self._set_status(
                "Options.txt is missing. Save changes to create it.",
                gui_theme.THEME["accent_gold"],
            )
        except (OSError, UnicodeError) as error:
            self._set_status(
                f"Could not inspect Options.txt: {error}",
                gui_theme.THEME["accent_gold"],
            )

    def _set_status(self, text, color):
        if self.status_lbl:
            self.status_lbl.config(text=text, fg=color)

    @staticmethod
    def _numeric_option_errors(plugin_limit_value):
        errors = []
        if plugin_limit_value != "Default":
            try:
                plugin_limit = int(plugin_limit_value)
                if not 1 <= plugin_limit <= 128:
                    errors.append("-_PluginAutoPopulateThreshold must be an integer from 1 to 128")
            except ValueError:
                errors.append("-_PluginAutoPopulateThreshold must be an integer from 1 to 128")
        return errors

    @staticmethod
    def _is_numeric_option(line):
        return line.startswith(PLUGIN_LIMIT_OPTION)

    @staticmethod
    def _read_bytes_or_missing(path):
        try:
            with open(path, "rb") as source:
                return source.read()
        except FileNotFoundError:
            return None

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
        cb.bind("<FocusIn>", lambda event: self.update_tooltip_text(self.tooltips.get(option_key, "")))
        cb.bind("<FocusOut>", lambda event: self.clear_tooltip_display())

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
        path = gui_theme.OPTIONS_PATH
        try:
            contents = self._read_bytes_or_missing(path)
            lines = [] if contents is None else contents.decode("utf-8").splitlines()
        except (OSError, UnicodeError) as e:
            self._options_snapshot_path = path
            self._options_snapshot = None
            self._options_read_error = e
            self._set_status(
                f"Could not read Options.txt; saving is disabled until it can be read: {e}",
                gui_theme.THEME["accent_gold"],
            )
            messagebox.showwarning(
                "Options.txt read failure",
                f"Could not read native Options.txt configuration flags:\n{str(e)}",
            )
            return

        self._options_snapshot_path = path
        self._options_snapshot = contents
        self._options_read_error = None
        if contents is None:
            for key in self.options_state:
                self.options_state[key].set(False)
            self.vst_limit_var.set("")
            self._set_status(
                "Options.txt is missing. Save changes to create it.",
                gui_theme.THEME["accent_gold"],
            )
            return

        for key in self.options_state:
            self.options_state[key].set(False)
        self.vst_limit_var.set("")

        for line in lines:
            clean_line = line.strip()
            if clean_line in self.options_state:
                self.options_state[clean_line].set(True)
            elif clean_line.startswith(PLUGIN_LIMIT_OPTION):
                self.vst_limit_var.set(clean_line.split("=", 1)[1])

        self._set_status(
            "Options.txt settings loaded; experimental options are not verified by Live.",
            gui_theme.THEME["accent_gold"],
        )

    def write_live_options_file(self):
        """Validates, backs up, and atomically replaces Options.txt after a conflict check."""
        path = gui_theme.OPTIONS_PATH
        target_dir = os.path.dirname(gui_theme.OPTIONS_PATH)
        temp_path = None
        backup_path = None
        try:
            if getattr(self, "_options_read_error", None) is not None:
                raise OSError(
                    f"The current Options.txt could not be read; refusing to overwrite it: "
                    f"{self._options_read_error}"
                )
            if getattr(self, "_options_snapshot_path", None) != path:
                raise RuntimeError("Options.txt location changed since it was loaded; reload before saving.")

            vst_val = self.vst_limit_var.get().strip()
            errors = self._numeric_option_errors(vst_val or "Default")
            if errors:
                raise ValueError("; ".join(errors))

            os.makedirs(target_dir, exist_ok=True)
            snapshot = getattr(self, "_options_snapshot", None)
            current = self._read_bytes_or_missing(path)
            if current != snapshot:
                raise RuntimeError(
                    "Options.txt changed since it was loaded; reload it and review the "
                    "new contents before saving."
                )

            existing_lines = (
                [] if current is None else current.decode("utf-8").splitlines(keepends=True)
            )
            retained_lines = []
            for raw_line in existing_lines:
                line = raw_line.strip()
                if line in self.options_state or self._is_numeric_option(line):
                    continue
                retained_lines.append(raw_line)

            additions = [
                key for key, value in self.options_state.items() if value.get()
            ]
            if vst_val:
                additions.append(PLUGIN_LIMIT_OPTION + vst_val)

            output = "".join(retained_lines)
            if output and not output.endswith(("\n", "\r")) and additions:
                output += "\n"
            if additions:
                output += "".join(f"{line}\n" for line in additions)
            output_bytes = output.encode("utf-8")

            if current is not None:
                backup_fd, backup_path = tempfile.mkstemp(
                    prefix=f".{os.path.basename(path)}.", suffix=".bak", dir=target_dir
                )
                with os.fdopen(backup_fd, "wb") as backup:
                    backup.write(current)
                    backup.flush()
                    os.fsync(backup.fileno())

            temp_fd, temp_path = tempfile.mkstemp(
                prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=target_dir
            )
            with os.fdopen(temp_fd, "wb") as temporary:
                temporary.write(output_bytes)
                temporary.flush()
                os.fsync(temporary.fileno())

            if self._read_bytes_or_missing(path) != snapshot:
                raise RuntimeError(
                    "Options.txt changed while saving; no replacement was made. "
                    "Reload and review the current contents."
                )
            os.replace(temp_path, path)
            temp_path = None
            self._options_snapshot = output_bytes
            self._options_snapshot_path = path
            self._options_read_error = None
            self._set_status(
                "Options.txt saved successfully. Its experimental settings are not verified by Live.",
                gui_theme.THEME["accent_neon"],
            )
            messagebox.showinfo(
                "Success",
                "Options.txt was saved. "
                + (f"Original backup: {backup_path}. " if backup_path else "No previous file existed. ")
                + "Restart Live to apply changes. Ableton Live behavior was not verified.",
            )
        except (OSError, ValueError, RuntimeError) as write_err:
            self._set_status(
                f"Options.txt was not saved: {write_err}",
                gui_theme.THEME["accent_gold"],
            )
            messagebox.showerror(
                "Options.txt save failure",
                f"Could not safely modify Options.txt:\n{str(write_err)}",
            )
        finally:
            for leftover in (temp_path,):
                if leftover and os.path.exists(leftover):
                    try:
                        os.unlink(leftover)
                    except OSError as cleanup_error:
                        messagebox.showerror(
                            "Options.txt temporary file cleanup failed",
                            f"Remove this temporary file when it is no longer locked:\n{leftover}\n{cleanup_error}",
                        )

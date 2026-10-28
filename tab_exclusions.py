# tab_exclusions.py - Piece 1: Framework Imports & Configuration Synchronization
import tkinter as tk
from tkinter import ttk
import gui_theme
import sorter_engine
from tab_matrix import ask_confirm, show_notice, messagebox

class ExclusionsTab(ttk.Frame):
    def __init__(self, parent):
        """Initializes the folder tracking block ignore rule dashboard array."""
        super().__init__(parent)
        
        self.resolved_backend_key = "IGNORED_DIRECTORIES"
        self.active_exclusions_set = set()
        
        # Pull configurations and align memory slots
        self.synchronize_backend_variables()

        self.setup_ui_layout()
        self.refresh_exclusion_list()

    def synchronize_backend_variables(self):
        """Forces the backend config loader to run and maps IGNORED_DIRECTORIES into UI memory."""
        try:
            sorter_engine.load_external_config()
        except (OSError, ValueError) as error:
            messagebox.showerror("Could not load skipped folders", str(error))

        if hasattr(sorter_engine, 'IGNORED_DIRECTORIES'):
            raw_val = sorter_engine.IGNORED_DIRECTORIES
            if isinstance(raw_val, (list, set)):
                self.active_exclusions_set = set(raw_val)

        # 🌟 CORE DEFENSIVE AUTOMATION:
        # Guarantees unpitched loop containers are protected right out of the box
        if "No Key Info" not in self.active_exclusions_set:
            self.active_exclusions_set.add("No Key Info")

    def flush_changes_to_backend_memory(self):
        """Publish the new selection only after the profile was saved successfully."""
        try:
            sorter_engine.save_ignored_directories(self.active_exclusions_set)
        except (OSError, ValueError) as error:
            self.active_exclusions_set = set(sorter_engine.IGNORED_DIRECTORIES) | {"No Key Info"}
            messagebox.showerror("Could not save skipped folders", str(error))
            return False
        return True

    def setup_ui_layout(self):
        """Draws the simplified high-fidelity exclusion panels with all headers stripped down."""
        t = gui_theme.THEME

        # 1. Main Simplified Title Header
        header_lbl = ttk.Label(self, text="Folders to skip", font=("Segoe UI", 12, "bold"))
        header_lbl.pack(anchor="w", padx=15, pady=15)
        tk.Label(
            self,
            text="Add folder names that the app should leave alone while scanning. "
                 "For example, you can skip a vendor library or a folder you do not want organized.",
            font=("Segoe UI", 9), bg=t["bg_dark"], fg=t["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(0, 8))

        # 2. INPUT SELECTION TRAY
        input_group = ttk.LabelFrame(self, text=" Add a folder name to skip ")
        input_group.pack(fill="x", padx=15, pady=10, ipady=5)

        f_row = tk.Frame(input_group, bg=t["bg_dark"])
        f_row.pack(fill="x", padx=15, pady=8)

        self.ent_pattern = tk.Entry(f_row, font=("Consolas", 10), bg=t["bg_field"], fg=t["fg_light"], bd=1, relief="solid", insertbackground=t["fg_light"])
        self.ent_pattern.pack(side="left", fill="x", expand=True, ipady=3, padx=(0, 10))
        self.ent_pattern.bind("<Return>", lambda e: self.add_exclusion_pattern())

        btn_add = tk.Button(
            f_row, text="Add folder", font=("Segoe UI", 9, "bold"),
            bg=t["btn_primary"], fg=t["btn_primary_fg"],
            activebackground=t["btn_primary_hover"], activeforeground=t["btn_primary_fg"],
            bd=0, padx=20, command=self.add_exclusion_pattern
        )
        btn_add.pack(side="right")
        self.btn_remove = tk.Button(
            f_row, text="Remove selected", font=("Segoe UI", 9),
            bg=t["btn_danger"], fg="white", activebackground=t["btn_danger_hover"],
            activeforeground="white", bd=1, relief="solid", padx=15,
            command=self.remove_exclusion_pattern
        )
        self.btn_remove.pack(side="right", padx=(0, 8))

        # 3. INSULATED STYLE CONFIGURATION
        try:
            style = ttk.Style(self.master)
            style.configure("Exclusions.Treeview", background=t["bg_field"], foreground=t["fg_light"], fieldbackground=t["bg_field"], rowheight=24, font=("Segoe UI", 9))
            
            # Hide the table header completely by setting its font sizing constraints to zero
            style.configure("Exclusions.Treeview.Heading", background=t["bg_panel"], foreground=t["bg_panel"], font=("Segoe UI", 0, "bold"), rowheight=0)
            
            style.map("Exclusions.Treeview",
                background=[("selected", t["tag_enabled"]), ("active", t["bg_field"])],
                foreground=[("selected", "white"), ("active", t["fg_light"])]
            )
        except Exception:
            pass

        # tab_exclusions.py - Piece 3: Treeview Generation Elements
        t = gui_theme.THEME

        # 4. ENTRY LISTING TABLE WINDOW DISPLAY CONTAINER
        grid_group = ttk.LabelFrame(self, text=" Folders currently skipped ")
        grid_group.pack(fill="both", expand=True, padx=15, pady=10)

        f_tree_frame = tk.Frame(grid_group, bg=t["bg_field"], bd=1, relief="solid")
        f_tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        # Using show="tree" instead of show="headings" entirely deletes the text header row block completely
        self.tree = ttk.Treeview(f_tree_frame, columns=("pattern",), show="tree", style="Exclusions.Treeview", selectmode="browse")
        
        self.tree.column("#0", width=0, minwidth=0, stretch=False) # Strip out native padding column channel
        self.tree.column("pattern", stretch=True, anchor="w", minwidth=300)
        self.tree.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(f_tree_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=scroll.set)

        self.focus_set()

    def refresh_exclusion_list(self):
        """Wipes and re-populates active registry logs into layout grids accurately."""
        self.tree.delete(*self.tree.get_children())
        if self.active_exclusions_set:
            try:
                for item in sorted(list(self.active_exclusions_set)):
                    if item:
                        self.tree.insert("", tk.END, values=(item,))
            except Exception:
                pass

    def add_exclusion_pattern(self):
        token = self.ent_pattern.get().strip()
        if not token:
            messagebox.showwarning("Validation Error", "Exclusion token matching string field cannot be blank.")
            return
            
        if token in self.active_exclusions_set:
            messagebox.showinfo("Ignored Duplicated Pattern", "Specified exclusion path string pattern is already active.")
            return
            
        self.active_exclusions_set.add(token)
        if not self.flush_changes_to_backend_memory():
            return
        self.refresh_exclusion_list()
        self.ent_pattern.delete(0, tk.END)

    def remove_exclusion_pattern(self):
        """Removes a chosen directory pattern from backend rules with an active safety verification gate."""
        selected_target = self.tree.selection()
        if not selected_target:
            messagebox.showwarning("Selection Error", "Please highlight a target exclusion layout line to drop.")
            return
            
        values = self.tree.item(selected_target, "values")
        if values and len(values) > 0:
            actual_token = values[0]
            
            # 🚨 BASELINE SAFETY SYSTEM INTENT EXCLUSION:
            # Prevents you from accidentally removing core engine layout protection routes
            if actual_token == "No Key Info":
                show_notice(
                    self.winfo_toplevel(), "Permission Denied",
                    "The 'No Key Info' rule is a built-in guard that keeps unpitched samples out of key-based sorting.\n\n"
                    "It can't be removed.",
                    heading="This rule can't be removed"
                )
                return
            
            confirm_purge = ask_confirm(
                self.winfo_toplevel(), "Verify Exclusion Removal",
                f"Stop skipping '{actual_token}'?\n\n"
                "It will be included in future sorting scans.",
                "Remove"
            )
            
            if confirm_purge:
                if actual_token in self.active_exclusions_set:
                    self.active_exclusions_set.remove(actual_token)
                    self.flush_changes_to_backend_memory()
                    self.refresh_exclusion_list()

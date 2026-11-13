import tkinter as tk
from tkinter import ttk

import gui_theme
import xo_dialog


class IntegrationsTab(ttk.Frame):
    """Provides application-specific tools separate from everyday sound browsing."""

    def __init__(self, parent):
        super().__init__(parent)
        theme = gui_theme.THEME
        ttk.Label(
            self, text="Integrations", font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", padx=15, pady=(15, 5))
        tk.Label(
            self,
            text="Prepare sample folders for other music apps.",
            bg=theme["bg_dark"], fg=theme["fg_muted"],
            justify="left", anchor="w", wraplength=900
        ).pack(fill="x", padx=15, pady=(0, 15))

        xo_group = ttk.LabelFrame(self, text=" XO - Sample folders ")
        xo_group.pack(fill="x", padx=15, pady=(0, 10))
        tk.Label(
            xo_group,
            text="Keep your library's one-shot categories in a folder you can add to XO.\n\n"
                 "Originals stay put; output uses hard links or copies. Links share contents, "
                 "so they are not backups. Choose a folder outside OneDrive.\n"
                 "Successful rebuilds replace managed output and remove old groups. "
                 "Older unmarked folders require confirmation and are kept as backups. "
                 "Add the output in XO and verify the sounds.",
            bg=theme["bg_dark"], fg=theme["fg_muted"],
            justify="left", anchor="w", wraplength=850
        ).pack(fill="x", padx=12, pady=(10, 8))
        self.xo_button = tk.Button(
            xo_group, text="Build XO folder", command=self.open_xo_builder,
            bg=theme["btn_primary"], fg=theme["btn_primary_fg"],
            activebackground=theme["btn_primary_hover"],
            activeforeground=theme["btn_primary_fg"], bd=1
        )
        self.xo_button.pack(anchor="w", padx=12, pady=(0, 12))

    def open_xo_builder(self):
        xo_dialog.open_xo_builder(self)

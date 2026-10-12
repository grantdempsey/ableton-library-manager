# 🎹 Ableton Production Assets & Sample Studio Manager v1.0.0

A high-performance, cross-platform desktop tool designed to automate the categorization, sorting, and structural cleanup of Ableton audio libraries, presets, and preferences.

---

## 🏛️ System Features
- **Cross-Platform Compatibility:** Runs identically on Windows and macOS using native directory structures.
- **OneDrive Insulation:** Automatically detects and isolates asset paths to protect local libraries from intrusive OneDrive sync locks.
- **Background Execution:** Leverages multi-threaded workers to execute tasks silently without freezing the interface.

---

## 🎛️ Workspace Layout Modules
1. **Home:** System landing screen displaying real-time telemetry logs and a toggle for the background Smart Learning Engine.
2. **Import Dashboard:** Scans, extracts, and moves incoming sample packs from external paths directly into library directories. Moves only verify duplicates to save space.
3. **Organize Library:** Executes absolute in-place recursive library flattening and folder organization. Features a fast size calculator and a multi-threaded ZIP backup utility.
4. **Rule Matrix:** Multi-grid view mapping active regex configurations. Features an interactive Rule Builder wizard and automated profile import/export presets.
5. **Folder Exclusions:** Simple lookup layout designating directories to ignore entirely during scanning procedures.
6. **Experimental Options:** Advanced setup menu that safely writes performance argument variables directly to native Ableton `Options.txt` configuration files.

---

## 🛠️ Build and Compilation
This repository includes a `build_app.py` script wrapper using PyInstaller to compress code files and assets into a single standalone binary bundle.

```powershell
# Set execution permissions (Windows)
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

# Compile standalone production application binaries
python build_app.py
```

---

## 🎨 Palette Specifications
- **Background Matte:** `#1e1e1e`
- **Component Slate:** `#2d2d2d`
- **Field Canvas:** `#252526`
- **Accent Neon Green:** `#39ff14`

---

## 🤝 Project Credits
- **Engineering:** Grant Dempsey
- **Community:** Developed for the Ancient Future Collective (AFC) production mentorship program.

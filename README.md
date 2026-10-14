# 🎹 Ableton Production Assets & Sample Studio Manager v2.0.0

A high-performance, cross-platform desktop tool designed to automate the categorization, sorting, and structural cleanup of Ableton audio libraries, presets, and preferences.

---

## 🏛️ System Features
- **Cross-Platform Compatibility:** Runs identically on Windows and macOS using native directory structures.
- **OneDrive Insulation:** Automatically detects and isolates asset paths to protect local libraries from intrusive OneDrive sync locks.
- **Background Execution:** Leverages multi-threaded workers to execute tasks without freezing the interface.
  Closing the app requests a safe cancellation and lets the current file finish before shutting down.
- **Safe Smart Learning:** Repeated metadata-backed filename evidence is persisted as reviewable rule
  candidates. Candidates are never activated automatically, and Smart Learning can be disabled from
  the Home tab.
- **Configuration recovery:** Rule settings are validated before use and saved atomically. The
  previous valid configuration is kept as `library_config.json.bak` so a malformed or interrupted
  update can be recovered instead of silently falling back to incomplete settings.

---

## 🎛️ Workspace Layout Modules
1. **Home:** A simple starting point with a guided preview-first workflow and optional Smart Learning.
2. **Import:** Choose the folders, preview the suggested organization, and then copy or move files into the library.
3. **Organize:** Clean up an existing library after reviewing the available safety options.
4. **Sounds & Tags:** Search the indexed library by words from filenames, folders, or tags and manage personal tags.
5. **Rules:** Review the app's sorting rules and approve or reject learning suggestions.
6. **Skip Folders:** Tell the app which folders should never be scanned.
7. **Advanced:** Optional performance and Ableton configuration tools for experienced users.

## 🧠 Smart learning workflow

The current learning foundation is intentionally conservative:

1. A file must be classified from Ableton metadata before its naming tokens become evidence.
2. Evidence is accumulated across runs instead of resetting after each import.
3. A token/category pair reaching five observations becomes a pending candidate.
4. Pending candidates are stored separately from `DRUM_KEYWORDS`; they do not change sorting until explicitly approved.
5. Generated expressions are escaped with `re.escape()` and compiled before being stored.

This staged workflow prevents a single sample pack or a noisy filename from silently changing the active taxonomy. Classification previews now make the proposed destination and reason visible before a file operation.

## 🔎 Classification preview

The **Import** tab includes **Preview only (no file changes)**. Preview mode runs the same
classification logic as an import, but does not move, copy, delete, rename, or clean up files.
Each preview record reports:

- Source filename
- Proposed destination
- Classification reason, such as `filename_rule`, `ableton_metadata`, `file_extension`,
  `loop_name_or_metadata`, or `audio_fallback`
- A confidence estimate for the classification

The preview is written to the execution console, with the first 100 records displayed directly
to keep the interface responsive for large libraries. Use this mode before Move Mode when
reviewing new rules or unfamiliar sample packs.

## ⚙️ Rule lifecycle

Drum rules support lifecycle metadata under `RULE_METADATA` while retaining the legacy
`DRUM_KEYWORDS` mapping:

```json
"RULE_METADATA": {
    "\\bkick(s)?\\b": {
        "priority": 100,
        "enabled": true,
        "exclude": ["\\bloop\\b"]
    }
}
```

- Higher priority rules are evaluated first.
- Disabled rules remain visible in **Rules** but are skipped during sorting.
- Exclusions prevent a rule from matching a filename or source path.
- Legacy rules without metadata remain enabled and receive a stable fallback priority.
- **Rules** includes enable/disable actions and a representative conflict check.

Learned candidates are approved with a default priority of 50, so they do not automatically
override high-priority built-in rules.

## 🏷️ Persistent asset tags

Classifications and tags are stored in a local SQLite database at `library_assets.db`.
This keeps asset history separate from portable rule configuration:

- `assets` records the normalized path, file identity data, destination, classification reason,
  confidence, and last update time.
- `asset_tags` stores multiple tags per asset, including Ableton browser tags when available and
  a `category:<folder>` tag for the current routing category.

The index is updated during preview and real import operations. Re-indexing an asset updates its
classification-derived tags without removing user-added tags, and replaces stale generated tags
rather than creating duplicates. When a previewed asset is moved into the library, its existing
index record and personal tags move with it instead of leaving a duplicate source record. Copies
remain represented at both paths because both files still exist. Preview output displays
the tags for each record, making it possible to inspect how Ableton metadata and routing decisions
relate before changing files.

The **Sounds & Tags** tab exposes the indexed User Library directly. It supports:

- Searching by filename or path
- Filtering by an exact tag
- Viewing the sound folder and all tags in the main preview
- Viewing the full file location in the optional details popup
- Adding user tags such as `favorite`, `reference`, or `needs-review`
- Removing a tag from the selected asset

The browser only shows sound and MIDI records whose paths are inside the configured Ableton
User Library. On Windows, the app checks both local Documents and the OneDrive Documents
location and uses the existing folder. Preview records for source files elsewhere, including
files inside the project folder, are not shown there. Tag counts use the same boundary. Sounds & Tags reads the existing index so the page stays
responsive; use Import or Organize to discover and index new files before browsing them.
The results table shows the file name and its folder relative to the User Library; the full
path is available only in Sound details.
Sound details opens centered over the main application window and stays within the screen
when the application is moved or resized.

The interface uses a dark neutral surface hierarchy with quiet borders around grouped
controls. Green indicates active or successful states, gold is reserved for status or attention,
and lavender indicates enabled tags and favorites. Buttons use the same role system throughout:
green for constructive actions, charcoal for neutral navigation and playback, and red for
destructive actions.

Use **Apply filter** or press **Enter** in the search box to run a search without rescanning
the library. Favorite uses the same lavender visual treatment as enabled tags. The results
summary shows the visible results for the active search, collection, and tag filters. Tag
counts, collection totals, and the overall indexed-library total load from the indexed User
Library in the background so collection navigation stays responsive.

Generated filename tags use the `name:` namespace and remain separate from routing rules. For
example, `dark_kick_v2.wav` produces `name:dark` and `name:kick`; these tags improve discovery
without causing unexpected reclassification.

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

## 🆕 What's new in v2.0.0
- Safety: automatic backups before cleanup, move log with **Undo last cleanup**, **Preview changes**, Cancel.
- Sounds & Tags: independent category/tag highlights, accurate result counts, waveform strip, Auto-play, saved searches, keyboard shortcuts, favorites, faster startup via cached tag counts.
- Rules: priorities, shadowed-rule detection, explain-a-filename, backup/restore of rules.
- Home: library status card and in-app README viewer.
- Polish: all dialogs centre on the app, unified green and lavender theme, progress bar with file counts.

---

## 🎨 Palette Specifications
- **Background:** `#202124`
- **Panel:** `#2b2d31`
- **Field:** `#25272b`
- **Accent Green:** `#a8e063`
- **Accent Lavender:** `#8b6fb3`
- **Accent Gold:** `#f4c95d`

---

## 🤝 Project Credits
- **Engineering:** Grant Dempsey
- **Community:** Developed for the Ancient Future Collective (AFC) production mentorship program.

## 🎨 GUI usability notes

The application shell is sized for the wider Sounds & Tags and Rules views and remains resizable.
For the safest workflow:

1. Use **Preview only** on the Import tab for unfamiliar packs.
2. Review destination, confidence, and tags before using Move Mode.
3. Use the **Sounds & Tags** tab to search by filename or exact tag and curate user tags.
4. Use **Rules** to review suggestions, disable questionable rules, and check conflicts.

The GUI intentionally keeps destructive actions explicit while placing inspection and review
controls before them.

If a file cannot be copied, moved, indexed, or otherwise processed, the operation continues
where it is safe to do so and records the source, destination, operation type, and error reason
in the Activity log. The completion summary calls out when individual files need review instead
of hiding failures inside only a total count.

The automated test suite includes temporary-directory integration workflows for Preview, Copy,
and Move modes. These tests verify the complete worker lifecycle, file placement, and searchable
index results without modifying a user's library.

### Folder nesting safety

The organizer is designed to be safe to run more than once. Files already inside an organized
top-level structure such as `Samples/One-Shots`, `Samples/Loops`, `Percussion`, `Midi`, or
Ableton preset/device folders are left where they are. Suspicious repeated structures such as
`Samples/Loops/.../Loops` are also skipped rather than moved or deleted. This prevents a second
import or in-place organization pass from creating paths such as
`Samples/Samples/One-Shots/...`.

If nested folders already exist, use **Organize Library → Repair nested folders**. Choose
**Find nested folders** to generate a review list. The proposed source and destination are
shown before anything changes. Choose **Repair reviewed files** only after checking the list.
Choose **Repair listed files** only after checking the list.
Repairs never overwrite an existing file; collisions are skipped and reported in the Activity
log. A repair scan is separate from normal organization so routine imports cannot unexpectedly
rearrange existing files.

Organize cleanup can create a backup before changing the library. The backup is a `.zip` file
saved in an **Ableton Library Backups** folder beside the selected library, rather than inside
the library itself. Keeping it beside the library makes the location easy to find and prevents
the organizer from scanning its own backup during a later cleanup.

### Finding sounds and managing tags

The **Sounds & Tags** tab is a searchable browser, not another sorting tool. It reads existing
supported files from the User Library index; use Import or Organize to discover and index new
files before browsing them. Use the **Collections** list
to switch between all sounds, **Favorites**, Loops, One-shots, and MIDI, or choose a tag from
the **Tags** list to browse that collection. Results are paged so large libraries remain
responsive; use **Previous** and **Next** to browse every indexed sound. The selected collection remains
highlighted while you move through its tags. The index includes
common audio formats such as
WAV, AIFF, FLAC, MP3, OGG, M4A, AAC, WMA, Opus, CAF, AU, and SND, plus MIDI files.
Documents such as TXT and PDF files are intentionally excluded. Re-run Preview or Import
after adding support for a format so existing files are indexed. You can also search by filename or use search syntax such as `tag:favorite`, `type:loop`,
`bpm:120`, `key:Am`, `reason:filename_rule`, and `-vocal` to exclude a term. Select a sound
to see its details and use **Play sound** for a preview. WAV files use the lightweight
in-app player on Windows. Other formats are opened with the operating system's default
audio application, so formats such as MP3, FLAC, OGG, AIFF, M4A, AAC, and Opus
can be played when an appropriate application is installed. Ableton project files such as
`.adv`, `.adg`, `.als`, and `.amxd` are not audio files and are rejected with a clear message.
If VLC, FFplay, or MPV is
installed, the app uses it as a broad decoder before falling back to the operating system.
macOS uses `afplay` when available, and Linux uses `paplay` or `aplay`, with `xdg-open` as
a fallback. The **Stop**
button stops previews started by the lightweight player; previews opened in an external
application must be stopped there. Playback stops automatically when you change category,
tag, search, or tab. Tick **Auto-play on select** to hear each sound as you click it; it is
greyed out for MIDI files, which would otherwise open an external player on every click.
WAV files also show a waveform strip. Shortcuts: **Ctrl+F** focuses search, **Space**
plays or stops the selected sound, and **F** toggles Favorite. **Saved searches** stores
and recalls your favorite search strings. Empty tag lists (for example in Favorites) show
**None**. Tag counts are cached between launches and refreshed whenever the index changes. Use **Add a personal tag** for
labels such as `favorite`, `reference`, or `needs-review`. Tag buttons disable a tag without
destroying its assignment, so it can be enabled again later. Disabled tags are excluded from
search and remain visible as muted buttons in the sound details view.
Tag removal is intentionally handled in the sound-details
popup, where each tag has an enable/disable button and the **Remove tag** action is tied to
the sound you are editing.
The results area explicitly says **Double-click any sound to edit its tags**. Double-click a
sound to open its details. Its tags appear as buttons that can be clicked to
enable or disable each tag for that sound. This changes the stored tag assignment, not the
sound file itself; use **Add tag** to create a new personal tag.

Tags beginning with `name:` or `category:` are created by the app. Other tags are personal
labels. Tags never move, rename, or delete files. Re-indexing refreshes generated tags while
preserving their enabled or disabled state.

### Tags that can guide sorting

Most tags are search labels only. To deliberately let a tag guide future classification, use
one of the explicit routing namespaces:

- `type:loop` — treat the audio as a loop and organize it by BPM and key.
- `type:one-shot` — prevent loop-name guesses and keep the file in one-shot handling.
- `role:kick`, `role:snare`, `role:hat`, `role:clap`, `role:tom`
- `role:perc`, `role:shaker`, `role:vocal`, `role:fx`
- `instrument:bass`, `instrument:808`, `instrument:synth`, `instrument:ambient`

Routing tags are intentionally opt-in. Tags such as `favorite`, `mood:dark`, `name:kick`, and
`category:Kicks` do not change file destinations. When multiple routing tags exist, `type:loop`
or `type:one-shot` defines the broad audio type, then the role or instrument tag defines the
one-shot destination. A routing tag is only used for a file already present in the local index;
new files still use filename, metadata, extension, BPM, and key detection during their first
preview.

### Rules in everyday use

Most people only need the **Suggestions to review** section. Select a suggestion and choose
**Use this suggestion** if the repeated naming pattern and destination look right, or choose
**Dismiss this suggestion** if they do not. The filename and file-type rule tables appear below
for reference. **Advanced options** are available for custom library setups but can be left
alone during normal imports.

## 🚀 First-launch checklist

Use this checklist the first time you set up the app on a computer. The first test is
intentionally non-destructive.

### Windows

- [ ] Install Python 3 and make sure **Tkinter** is included.
- [ ] Open the project folder.
- [ ] Double-click `Launch-Windows.bat`.
- [ ] If Windows says Python cannot be found, install Python again with **Add Python to PATH**
      enabled, or start the app with:

      ```powershell
      python AbletonLibraryManager.pyw
      ```

- [ ] Confirm that **Your Ableton Library** points to the intended library folder.

### macOS

- [ ] Install Python 3 with Tkinter support.
- [ ] Open Terminal and change to the project folder.
- [ ] If needed, allow the launcher to run once:

      ```bash
      chmod +x Launch-Mac.command
      ```

- [ ] Double-click `Launch-Mac.command`, or start it from Terminal with:

      ```bash
      ./Launch-Mac.command
      ```

- [ ] Confirm that **Your Ableton Library** points to:
      `~/Music/Ableton/User Library`, or choose the correct library location.

### Safe first test — Windows or macOS

- [ ] Open **Import**.
- [ ] Choose a small folder containing a few test samples, not your only copy of a library.
- [ ] Leave **Make copies (recommended)** selected.
- [ ] Select **Preview only (make no changes)**.
- [ ] Click **Organize Samples**.
- [ ] Review the Activity list for the proposed destination folders, tags, and confidence.
- [ ] Confirm that the original test files are still in place.
- [ ] Only after the preview looks correct, run a small real test using copy mode.
- [ ] Open **Tags** and confirm that the test assets can be searched.

### Before using Move files

- [ ] Make sure the preview results are correct.
- [ ] Keep a backup of important files.
- [ ] Confirm that the source folder is not a shared, synced, or actively edited folder.
- [ ] Use **Move files (remove originals)** only when you intentionally want the source files
      removed after they are copied into the library.

If the app opens but Tkinter is missing, the Python installation needs to be repaired or
reinstalled with Tcl/Tk support. If the automatically detected Ableton path is not correct,
do not run the organizer yet—choose or enter the intended library path first.

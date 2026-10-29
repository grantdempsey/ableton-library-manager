# 🎹 Ableton Production Assets & Sample Studio Manager v2.1.0

A high-performance, cross-platform desktop tool designed to automate the categorization, sorting, and structural cleanup of Ableton audio libraries, presets, and preferences.

## Release status: unreleased development

The `v2.1.0` title and build paths are provisional; no release is published.
Final source `2e76076` passes 358 Windows source tests (one POSIX-only skip)
and native macOS 15 validation on Apple Silicon and Intel, including native
builds, bundled-code fixtures, startup/profile checks and extracted-ZIP smoke.
The final Windows candidate passes 224 bundled-code tests and archive integrity
checks, but Windows Application Control blocked its native launch. Do not bypass
that policy. Hands-on Ableton Live acceptance, final Windows package launch,
and trusted signing/download validation remain open. See
[RELEASE-HANDOFF.md](RELEASE-HANDOFF.md) for exact evidence and hashes.

**Full tagging parity is not complete.** Library is an editable sound browser;
the separate read-only Ableton catalog viewer and source switch have been removed.
Live tag editing, reviewed batches and database-backed vocabulary suggestions remain.
Racks, presets and other non-audio items do not have an end-to-end editing workflow.
Non-audio write acceptance in Live, virtual device/plugin coverage, full plugin
Format coverage, and native global custom-group/tag lifecycle operations remain
open. Serializing a sidecar successfully is not proof that Live accepts it.

For current release blockers, safety boundaries, the manual test checklist, and
where to resume development, see [RELEASE-HANDOFF.md](RELEASE-HANDOFF.md).
[RELEASE-AUDIT.md](RELEASE-AUDIT.md) is a historical audit; its findings are not
a current unresolved-issue list.

---

## 🏛️ System Features
- **Platform support:** Includes Windows and macOS path handling. Native Apple Silicon
  and Intel validation passes on macOS 15 for the final source. Native input, older
  macOS releases and Live acceptance remain unverified.
- **OneDrive Insulation:** Automatically detects and isolates asset paths to protect local libraries from intrusive OneDrive sync locks.
- **Background Execution:** Leverages multi-threaded workers to execute tasks without freezing the interface.
  Closing the app requests a safe cancellation and lets the current file finish before shutting down.
- **Safe Smart Learning:** Repeated metadata-backed filename evidence is persisted as reviewable rule
  candidates. Candidates are never activated automatically, and Smart Learning can be disabled from
  the Home tab.
- **Configuration recovery:** The engine's rule-settings writer validates changes and saves atomically. The
  previous valid configuration is kept as `library_config.json.bak` so a malformed or interrupted
  update can be recovered instead of silently falling back to incomplete settings.
  Skip Folders and Rules now use that writer too. In-process configuration updates
  are serialized, and temporary files are unique.
- **Rules transactions:** Profile import, rule deletion, file-type addition,
  folder changes, default restoration and loop-layout saves stage changes
  before persistence. Failed saves leave active rules unchanged and never show
  import success. Unrelated profile fields are retained and concurrent disk
  changes during staging are refused.
- **Native Mac safeguards:** File operations preserve POSIX read permissions;
  startup rescans defer while metadata editing is active instead of opening a
  blocking dialog. Explicit manual rescans still explain when editing is busy.

---

## 🎛️ Workspace Layout Modules
1. **Home:** A simple starting point with a guided preview-first workflow and optional Smart Learning.
2. **Import:** Choose the folders, preview the suggested organization, and then copy or move files into the library.
3. **Organize:** Clean up an existing library after reviewing the available safety options.
4. **Library:** Find and audition indexed sounds, review assigned tags, and edit selected sounds in a dedicated tag editor.
5. **Integrations:** Prepare categorized sample folders for XO using the existing folder builder.
6. **Rules:** Review the app's sorting rules and approve or reject learning suggestions.
7. **Skip Folders:** Tell the app which folders should never be scanned.
8. **Advanced:** Optional performance and Ableton configuration tools for experienced users.

## 🧠 Smart learning workflow

The current learning foundation is intentionally conservative:

1. A file must be classified from Ableton metadata before its naming tokens become evidence.
2. Evidence is accumulated across runs instead of resetting after each import.
3. A token/category pair reaching 20 observations becomes a pending candidate.
4. Pending candidates are stored separately from `DRUM_KEYWORDS`; they do not change sorting until explicitly approved.
5. Generated expressions are escaped with `re.escape()` and compiled before being stored.
6. Historical observations alone cannot authorize a rule. Refresh suggestions from
   the current Library to establish current file evidence before approval.

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

### Manual Live-tag evidence (review only)

Import and Organize previews now read current manual Live sidecars by **full sample
path**, rather than matching assignments by filename or relying on the index cache.
For mapped Sounds and Drums hierarchies (for example `Drums|Snare|Rim`,
`Sounds|Piano & Keys|Synth Keys`, or `Sounds|Bass|808 Bass`), previews show the exact assignments, a suggested one-shot
destination, and whether that evidence agrees with or conflicts with the normal
classification. Specific subtags refine their parent rather than adding a second
vote; distinct sound types remain ambiguous. Drums percussion subtags retain their
percussion role instead of using a leaf such as Bell as a melodic instrument.
Character, Genres, Function, Format, MIDI Tools, unknown categories, generated labels, and automatic/factory Live classifications
are not sound-type evidence.

These are **separate recommendations**, not new routing instructions. Existing rules
retain their precedence; loop classification is
not replaced with a one-shot destination. Preview and actual execution still use the
same normal routing plan. Organize also shows recommendations for tagged samples
that would remain in the catch-all folder. Already organized non-catch-all folders
retain their existing protection from reclassification.
`Type|Loop` and Drums loop hierarchies block one-shot recommendations, as does the
legacy `Sounds|Loop` assignment. Kits, multisamples and impulse responses receive
no audio one-shot recommendation; non-audio items never get an audio one-shot
destination. A Type role alone does not invent an instrument. `Type|One Shot` does
not silently override an existing filename loop classification.

The Rules catch-all scan can now propose previously unknown filename words using
manual sound-type evidence. By default, at least 20 samples must support the same
type and at least 90% of eligible catch-all samples containing that word must agree.
Untagged and ambiguously tagged samples count against that share, rather than
quietly strengthening the result. Filename loops and non-one-shot roles are excluded
from manual-evidence learning. Filename-only fallback proposals cannot bypass
mapped manual evidence.
Only manual assignments supply these
labels, never the app's generated category or name tags. As with other suggestions,
pack-name coincidences still require human review.

Candidates retain their source, supporting tag hierarchies, sample counts, example
filenames, Library scope and scan thresholds in the profile. Select **View evidence** or double-click a pending candidate
in Rules to inspect this evidence. Nothing becomes active until **Use this suggestion** (or **Use all
suggestions**) is chosen. Approval creates a normal filename rule; it does not write
Live tags or move sounds immediately. Scan-based candidates are rechecked against
current files, manual sidecars and rules before approval, using
at least 20 supporters and 90% agreement, or stricter saved thresholds. Rechecks run in the background;
counts/examples are refreshed on successful approval. **Use all suggestions**
validates the whole selection before saving any rules: one stale candidate blocks
the selection rather than partially approving it. A profile change detected during
review also aborts without overwriting it. Preview again before running cleanup.

Malformed or unreadable sidecars abort classification before file processing and
report an error; Rules reports failed evidence refreshes instead of treating them as
an empty scan. Pending rows remain snapshots until refreshed or reviewed; they are
not silently removed after external tag changes. A successful **Refresh suggestions**
updates matching candidates and retires unsupported pending candidates in that
Library scope. Retired entries remain stored and can become pending again if a
later scan supports them; dismissed entries are not reset. Failed/unavailable
scans do not retire candidates, and stricter saved thresholds remain enforced.
Older scan-based candidates missing scope/thresholds must be refreshed before
approval; dismissal remains available. Historical pending candidates below 20
supporters are retained but hidden and cannot be approved, even through bulk or
direct approval. Legacy learning-count candidates use accumulated observations,
not a reconstructible distinct-file scan. They must reach 20 to appear for review,
but approval requires refreshing into verified current-file evidence.
XO no longer flattens cached Live or generated
tags into keyword hints. Its optional manual-evidence mode is described below.

### Loop-layout tag evidence

The **Loop folder layout** advisor also reads fresh manual sidecars. Its audit
reports tagged loops that filenames do not identify, conflicting one-shot/loop or
non-one-shot roles, complete/incomplete/ambiguous Key assignments, and disagreements
with filename keys. Live's Key root and Major/Minor tags must both be present and
unambiguous; Unicode sharps/flats and enharmonic equivalents are compared without
guessing a mode from a root alone. **Evidence** shows up to ten exact-path examples
and their assignments in a read-only, scrollable viewer.

The recommended layout and coverage still describe the existing executable
filename-based loop routing, not a silently substituted tag-based routing plan.
Manual roles/keys are an independent review-only audit; they do not change
filename-based organization rules. A failed sidecar read displays an error
and leaves **Use recommended** disabled rather than recommending from partial data.

### One editable Library, shared Live vocabulary

Library no longer includes a read-only Core Library/Packs viewer or a catalog
source switch. The workspace stays focused on finding and editing indexed sounds.
Legacy app-only tag rows remain stored but are inactive. Favorites, saved searches,
and manual Ableton assignments are separate supported data.

The read-only Live database adapter remains behind tag dropdown suggestions, not
as a separate library browser. It never writes Live's database or turns factory
content into editable library items. Use **Edit Live tags... → Tag suggestions source...**
to choose a Live database independently of the removed viewer. A single detected
database is used automatically; multiple databases require an explicit choice.

### Library hints and opt-in XO grouping

Custom manual assignments are not limited to Sounds. The single Live tag editor
offers an editable group selector covering the
verified catalog groups: Character, Clips, Creator, Devices, Drums, Genres, Grooves,
Key, Sounds, Tunings, and Type. Existing custom groups from indexed manual
assignments are also suggested, and you can type a group explicitly.
Opening a tag/group suggestion list loads Live's stored hierarchy vocabulary in
the background, including unused tags, custom groups/subtags and hierarchy values
stored in metadata. Suggestions serve all actions in the same editor;
they do not assign tags or count as manual evidence. A single detected
Live database is selected automatically; with multiple databases, use
**Tag suggestions source...** in the Live tag editor to select one.
Read errors are reported and retain the previous vocabulary. Derived browser
fields are not added as writable tag suggestions.

A plain label uses the selected group (`Genres` + `My style` becomes
`Genres|My style`). An explicit hierarchy always keeps its own group, even when
the picker differs. Plain rename targets use the selected group; use a
full hierarchy to rename across groups explicitly. Changing the group invalidates
the review, and queued actions retain their already-qualified hierarchies.

These are per-file sidecar assignments, not edits to Live's global vocabulary.
Custom groups and field-like categories are not guaranteed to appear in Live merely
because a hierarchy can be serialized. Format, Function and MIDI Tools are read-only
browser fields, not supported custom keyword groups. Factory/Core Library and
Packs are not added to the editable browser by choosing a vocabulary database.
Descriptive groups such as Genres or
Character do not become automatic routing or manual sound-type learning evidence.

Selecting all matching sounds also works with an empty search (the whole indexed
library). Large selection tag summaries load in the background, with editing
temporarily disabled until validation completes. Clear or change selection without
waiting; obsolete summaries are discarded. **Select page** adds visible sounds to
the captured selection and is a no-op when that page is already selected.

The existing dark theme now uses consistent control typography, visible disabled
states, and keyboard focus accents throughout the app. Library search expands with
the window while preserving compact tag-list space. Advanced settings groups have
clearer visual boundaries; option explanations are available on keyboard focus as
well as hover. These visual updates do not change any options or routing behavior.

**Sound details** (double-click a sound) includes read-only **Folder advice**, explaining mapped manual sound assignments for
one selected sample, including conflicting types,
and differences between its current folder and the suggested one-shot folder.
Suggestions use the **cached** Live assignments and are read-only. Use **Reload assigned tags**
in **Edit Live tags...** (or the metadata watcher/rescan) to update that cache. Multi-selection
does not present one sample's advice as representative.

In **Integrations → Build XO filter folder**, enable **Use manual Live sound types**
before scanning to opt in. Each scan reads current sidecars by full sample path.
A single mapped manual type takes precedence over keyword grouping; conflicting
manual types are excluded rather than guessed. Unknown or Character-only assignments use normal keyword
grouping. Manual `Type|Loop`, Drums loop hierarchies and `Sounds|Loop` assignments
participate in loop exclusion. Kits, multisamples and impulse responses are excluded
from the opt-in audio build.
**Edit folders → Find suggestions** inherits the builder's Live-tag option: already
classified sounds and conflicting/non-one-shot evidence are not mined as new folder
words. Failed sidecar reads report an error instead of showing an empty success.

Scan reports manual classifications and ambiguous samples. **Evidence** opens a
scrollable snapshot of exact assignments, keyword disagreements, chosen types, and
loop flags in a dark, resizable viewer. The XO builder is resizable, with a scrollable
type list that keeps its action buttons accessible for large taxonomies. The existing
type checkboxes and **Include loops** still control the
build. Changing either classification option rescans; scan failures disable Build
and report the error. The default keyword-only mode remains unchanged.

Building uses the reviewed scan snapshot; it does not re-read metadata at Build time.
Rescan after editing tags. Existing XO output is additive: rerunning does not remove
older links from previously chosen groups. Originals, manual sidecars, and manager
rules are not changed by this grouping mode.

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
- `asset_tags` stores generated classification metadata, manual Ableton assignments
  read from sidecars, and favorites. Legacy app-only rows remain dormant for
  recovery compatibility and are excluded from visible tag APIs.

The index is updated during scans and file operations. Re-indexing an asset refreshes
generated tags and manual sidecar assignments, and replaces stale generated tags
rather than creating duplicates. When a previewed asset is moved into the library, its existing
index record and favorites move with it instead of leaving a duplicate source record. Copies
remain represented at both paths because both files still exist. Preview output displays
the visible tags for each record, making it possible to inspect Ableton metadata and
classification before changing files.

The **Library** tab exposes the indexed User Library directly. It supports:

- Searching by filename or path
- Filtering by an exact tag
- Viewing the sound folder and all tags in the main preview
- Viewing the full file location in the optional details popup
- Viewing and filtering visible generated and manual Live tags
- Marking sounds as favorites

App-only custom tags are not a feature. Legacy app-only tag rows remain dormant
in the database for recovery compatibility; they are not shown, searchable,
exported, or used for classification and routing.

The browser only shows sound and MIDI records whose paths are inside the configured Ableton
User Library. On Windows, the app checks both local Documents and the OneDrive Documents
location and uses the existing folder. Preview records for source files elsewhere, including
files inside the project folder, are not shown there. Tag counts use the same boundary. Library reads the existing index so the page stays
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
Import and Organize completion (including previews, undo, and nested-folder repairs)
invalidates the browser's cached results and counts. They reload immediately if the
browser is visible, or when you next open Library, without another filesystem scan.
Your search, collection, and tag filters are preserved, and paging returns to the first page.

After deleting files with another tool, use **Library > Rescan library** to
update the index and its counts without moving any files. Rescanning discovers new sounds
and removes records and tags for confirmed-missing files inside the selected library.
Completed Import and Organize operations also remove missing records in their destination
library. Existing files retain their favorites and dormant legacy data. Unavailable libraries or access errors
are reported rather than treated as deleted files.

Generated filename tags use the `name:` namespace and remain separate from routing rules. For
example, `dark_kick_v2.wav` produces `name:dark` and `name:kick`; these tags improve discovery
without causing unexpected reclassification.

---

## 🛠️ Build and Compilation
The build helper creates a new isolated candidate directory on each invocation,
without stopping apps or deleting existing output. Runtime source uses Python's
standard library, including Tk, and requires Python 3.11 or newer; the currently tested environment is Python 3.14
on Windows. The build tool version is recorded in `requirements-build.txt`.

```powershell
python -m pip install -r requirements-build.txt
python build_app.py
```

Outputs are under `release_builds\candidate-*\dist`. Smoke-test a separate copy
and inspect the final archive for private profiles, asset databases, journals,
sidecar backups and move-recovery data. Never archive a used runtime directory
as the release. A source test pass is not a packaged-app certification.

macOS builds must be produced on a Mac; a Windows build is not a Mac app.
The manual `macOS release validation` GitHub workflow prepares separate Apple
Silicon and Intel runs: source tests, native PyInstaller builds, embedded-code
fixtures, and fresh/upgrade startup plus native Quit smoke. The prepared workflow
passed on both architectures in
[run 40620273566](https://github.com/grantdempsey/ableton-library-manager/actions/runs/40620273566)
at production commit `0836eef`; it does not publish artifacts. On a Mac, after building:

```bash
python3 tests/verify_windows_bundle.py "/path/to/AbletonLibraryManager.app"
python3 tests/smoke_macos_package.py "/path/to/AbletonLibraryManager.app"
```

The legacy-named bundle verifier accepts either platform's package. Its fixtures
use the host interpreter, not native mouse/keyboard automation. The native Mac
smoke launches the exact app with a disposable home and working directory `/`,
then requests macOS Quit. Neither check certifies Live behavior, signing,
notarization or Gatekeeper distribution. Test the final distributed app by
opening it in Finder on each supported architecture too.

For a reproducible Windows startup check, run this against the new package:

```powershell
.\tests\smoke_windows_package.ps1 -PackageDirectory <candidate-dist-directory> -EvidenceDirectory <evidence-directory>
```

The smoke runs copies with disposable fresh/legacy profiles and redirected home
directories. It checks private-state exclusion, window startup/responsiveness,
resize, profile preservation and graceful exit. It does **not** certify packaged
page navigation, editing workflows or Live acceptance.

With the build environment installed, also exercise the executable's embedded
production code against disposable workflow/UI fixtures:

```powershell
python .\tests\verify_windows_bundle.py <candidate-dist-directory>
```

This checks bundled—not working-tree—production modules for whole-app UI,
reviewed tag writes, conflicts, copy/move/undo, Rules and preference safety. It
uses the build interpreter and bundled Tcl/Tk data. It complements native startup
smoke; it is not mouse/keyboard automation of the running executable or proof
that Live accepts every supported metadata shape.

### Advanced Options.txt scope

Advanced exposes only options checked against Ableton's
[Options.txt documentation](https://help.ableton.com/hc/en-us/articles/6003224107292-Options-txt-file):

- `-EnableArmOnSelection` (not recommended with Push 2 or Push 3).
- `-DontCombineAPCs`.
- Windows: `-_EnsureKeyMessagesForPlugins`.
- macOS: `-DisableGraphicsHardwareAcceleration` and
  `-DisableAppleSiliconBurstWorkaround`, with rendering/latency cautions.
- `-_PluginAutoPopulateThreshold=` accepts 1–128; blank removes this exact
  managed option and leaves Live's default.

These are experimental, version/platform-dependent settings, not performance
guarantees. Close Live before saving, restart afterward, and validate behavior in
Live. Unlisted/legacy lines are preserved, not certified or silently migrated;
the old differently spelled plug-in threshold and CPU-thread options remain
unmanaged. Reload from disk if preferences changed externally.

### Stabilization changes after the release audit

- Skip Folders saves atomically and reports errors without publishing failed changes.
- Advanced refuses unreadable/stale preferences, validates numeric input, and
  preserves unknown options with unique backups and atomic replacement. The
  controls are limited to documented platform-specific options; unverified
  controls were removed and existing unmanaged lines remain.
- Duplicate moves retain recovery audio and metadata in `move_logs` for undo.
  Recovery refuses changed destination audio or Live tags. Retained recovery files
  consume disk space and must not be included in a release archive.
- Single tag actions now open the same background review/save workflow as batches:
  no sidecars change until the reviewed operation is explicitly saved.
- Generated classification tags are regenerated on copy/move. Broad Bass tag
  advice uses a neutral Bass folder, not a synth-specific destination.
- Watcher refresh invalidates dropdown suggestions. Library rescan/sidebar
  completion is queued to the UI thread, and shutdown waits for that work.

---

## 🆕 What's new in v2.1.0
- **Library workspace:** Resizable browsing panes, a focused selection inspector, one consolidated Live tag editor, bulk favorites, saved collections, removable filter chips, and Clear all. App-only custom tags are retired; legacy rows remain dormant, and favorites are preserved.
- **Cross-page curation:** Select a page or capture all matching sounds, keep the selection while paging, and see an explicit off-page count. Changing filters clears selection; edits never automatically include newly indexed matches.
- **Assigned Live tags:** The consolidated editor lists current assignments and selected-sound counts, with add/remove/rename and Preview/Save.
- **Previewed Live-tag edits:** Choose add/remove/rename, preview exact assignment changes, then save. Use Add another change for optional multi-edit batches. Planning and saving run in the background with sidecar conflict checks and backups.
- **Discovery filters:** Find untagged samples or sounds missing a manual Live group; combine exact tags with match-all, match-any, or exclusions, and save those searches as collections.
- **Metadata freshness:** A visible Live-tag monitor checks sidecars in the background, waits for two stable probes, and updates cached assignments without writing audio or sidecars. Full-scan and library metadata-check times are displayed separately.
- **Shared Live tags:** Read manual Live 12 sidecars on scans and review cached assignments in the inspector. **Edit Live tags...** opens one editor with current assignments, selected-sound counts, add/remove/rename, optional multiple edits, and Preview/Save. Existing sidecars receive backups; concurrent changes detected during review abort saving. Close Live during writes.
- **Tag-preserving operations:** Manual assignments follow sample copy/move, duplicate merging, nested-folder repair, and undo. See the shared-tag section for limitations and recovery guidance.
- **Integrations workspace:** The XO folder builder has a dedicated home for third-party workflows. Serum support is not included.
- **Accurate library counts:** Rescans remove confirmed-missing files after external deletion; operation completion refreshes the browser and its sidebar counts.
- **Live acceptance:** Earlier disposable WAV checks were limited to the tested Live 12.4.7 metadata workflow. The current consolidated editor's add/rename/remove visibility round trip remains a human acceptance gate.
- **Focused Library:** Removed the separate read-only Ableton catalog viewer and source switch while retaining shared Live vocabulary and all editing features. Results have explicit page navigation, a source-separated generated/manual tag summary, and detailed folder evidence in Sound details.
- **Conservative suggestions:** All reviewable suggestions, including historical pending candidates, require at least 20 supporters. Scan revalidation uses at least 20 files and 90% agreement, or stricter saved thresholds. Below-threshold candidates remain stored but are hidden and cannot be approved individually or in bulk. Tag-editor dropdown queries run in the background with cached, single-flight loading and stale-result rejection.

### Previous release: v2.0.1
- Safety: automatic backups before cleanup, move log with **Undo last cleanup**, **Preview changes**, Cancel.
- Sounds & Tags: independent category/tag highlights, accurate result counts, waveform strip, Auto-play, saved searches, keyboard shortcuts, favorites, faster startup via cached tag counts.
- Rules: priorities, shadowed-rule detection, explain-a-filename, backup/restore of rules.
- Home: library status card and in-app README viewer.
- XO filter folder: **Integrations > Build XO folder** groups your sounds by type (kicks, snares, nature, foley, vocals, textures...) into one folder per type so XO can filter by folder. Files are hard-linked when possible and copied otherwise (copies use extra disk space). Originals are never moved. Hard links share file contents and are not independent backups. Keep the folder outside OneDrive. This is a folder-based workflow, not direct XO control. Serum preset management is not implemented yet.
- Rule suggestions: the Rules tab scans your catch-all folder (Other One-Shots) when the app opens and after every Organize or Import, and proposes new keyword rules (e.g. "djembe" → Percussion, "rain" → a new Nature folder). Each suggestion shows the priority it would get; **Use this suggestion** ranks it automatically, and **Use all suggestions** adds them in one go. Nothing changes until you approve.
- Loop folder layout: on the Rules tab's **Loops** tab, **Edit layout…** lets you choose which levels loops are filed into (Tempo, Key) and reorder them with ▲/▼. The recommendation puts the level with the fewest folders first and leaves out a level most of your loops can't fill. Organize applies the layout to new loops and re-files loops that sit in folders this app created; folders you made yourself are left alone. Use Preview changes first; Undo covers it.
- The Rules tab is split into **Loops**, **One-shots** and **Presets & racks** tabs, so each kind of file shows where it goes and the controls for changing it.
- XO folders are editable: **Edit folders…** in the XO builder lets you add your own keywords to any folder, create new folders, and **Find suggestions** learns candidate folder names from words common in sounds no folder recognizes yet.
- Organize now re-checks the Other One-Shots folder, so files that match a rule (or a rule you approve later) move to the right folder. Use **Preview** first; Undo is available.
- Local app tags were separate from Ableton tags; v2.1.0 adds the explicit shared manual-tag workflow described below.
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

The application shell is sized for the Library and Rules views and remains resizable.
For the safest workflow:

1. Use **Preview only** on the Import tab for unfamiliar packs.
2. Review destination, confidence, and tags before using Move Mode.
3. Use the **Library** tab to search by filename or exact tag and curate shared Live tags.
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

Automatic shell-based force-moving and recursive repair are no longer part of
ordinary cleanup. Reviewed repairs use the same metadata-preserving transfer
and durable move log as normal moves.

Organize cleanup can create a backup before changing the library. The backup is a `.zip` file
saved in an **Ableton Library Backups** folder beside the selected library, rather than inside
the library itself. Keeping it beside the library makes the location easy to find and prevents
the organizer from scanning its own backup during a later cleanup.
The archive includes Live sidecars and explicit AppleDouble files, verifies its
entry list, CRC and audio/metadata bytes, and refuses unreadable or linked
content. A failure does not start cleanup unless you explicitly choose to
proceed without a backup. This is a content recovery archive, not a complete
macOS filesystem backup: native extended attributes, ACLs and resource forks
not represented as ordinary files are not guaranteed. Keep an independent
Time Machine or equivalent backup.

Ordinary moves now record content identity before transfer; undo refuses
changed destinations. Older ordinary move logs have no identity and are kept
for manual recovery rather than trusting possibly changed files. Duplicate
recovery retains its separate safeguarded handling. Do not delete `move_logs`
or its recovery files while you might need them. Closing waits for active
undo/backup and tracked workers; it can take time and should not be force-quit.

AppleDouble `._` files are metadata, not sounds: indexing, sorting, suggestions,
XO and Live-sidecar reads exclude them. A rescan removes previously indexed
AppleDouble records without deleting the files.

### Finding sounds and managing tags

The **Library** tab is a searchable browser, not another sorting tool. Drag the dividers
to resize Collections/Tags, results, and the inspector. Use
**Show selection details (right)** above the results to hide or restore the right panel.
It separates playback/favorites from one compact **Tags** summary. Generated search
and classification tags and manual Live assignments have separate
headings. Multiple selections show each tag's assignment count, including tags
present on only some sounds.
Empty manual-tag results do not imply factory tags are missing.
Double-click a sound for **Sound details**, including scrollable, read-only folder
advice. Folder advice is destination guidance, not new tag suggestions, and is no
longer a permanent inspector panel.
**Previous page** / **Next page** sit below the results with the current page and
visible range. **Auto-refresh Live tags** sits with metadata freshness in the footer;
it rereads metadata, not audio discovery.
Use **Edit Live tags...** to open the larger tag editor.
Live tags are shared via sidecars. App-only custom tagging has been removed:
legacy labels no longer appear in search, filters, routing, rule learning, or XO
classification. Their database rows remain dormant; nothing is deleted or migrated
into Live. Favorites and generated classification/search tags remain supported.
Dropdown choices load in the background and are cached until the index changes;
opening a group/tag dropdown never waits for the indexed-tag query. Failed reads
report an error and retain the previous choices.
Opening or closing the editor does not write tag assignments. The editor captures
the current Library selection, including sounds on other pages, and keeps it fixed
until closed. Reopen it to edit a different selection.
Select several results with Shift or Ctrl (Command on macOS) to edit them together.
The selection count is always shown above the results. **Favorite selected** and
**Unfavorite** apply only to selected sounds, including those off page, not the
entire filtered library. Generated `name:` and `category:` tags are read-only in
the inspector. Favorites change index metadata only, never sound files.
Playback and waveform support are unchanged.

**Saved collections** in the sidebar are reusable searches, not copies of your sounds.
Choose your search, collection, and tag filters, then use **Save current...** and give
the view a name. Click its name to restore that combination of filters. The existing
**Saved searches** menu uses the same saved views and storage. **Delete** removes only
the saved view, never sounds or tags. Saving with an existing name replaces that view.
Active search, collection, and tag filters appear above the results; click a chip's
**x** to remove just that filter, or **Clear all** to return to All sounds.
Changing filters returns to the first results page.

Saved collections and favorites remain app-specific. They are not exported to
Live. Use **Edit Live tags...** for manual tags shared with Ableton.
No existing local labels are migrated or deleted automatically.

### Shared Ableton Live 12 manual tags

**Rescan library** now reads folder-based Live 12 `.xmp` sidecars inside
`Ableton Folder Info`. It preserves full, case-sensitive hierarchies such as
`Sounds|Bass|Synth Bass` and matches relative paths, not just filenames. Sidecar
changes are reread even when the audio file has not changed. Renamed or removed
Live assignments replace the previous cached assignments; dormant legacy rows
are not removed. Invalid or inaccessible sidecars fail the scan explicitly,
leaving its uncommitted index updates rolled back.

Live tags appear as metadata in the inspector and Sound details.
The searchable cache uses `ableton:` before the exact Live hierarchy, for example
`ableton:Sounds|Test Tag`. This prefix identifies provenance inside the app only;
it is never written to Live. Local tag actions cannot edit these cached entries.
The `.xmp` sidecar remains the source of truth for these manual Live assignments.

The left sidebar separates **All tags**, **Live manual tags**, and
**Generated tags**. Live assignments sort first and display as `Live: Group|Tag`,
while keeping the exact `ableton:` cache identity internally. The group dropdown
is derived from assignments actually indexed in the current search/collection;
it is not a hardcoded list of Ableton tag types. **Find** searches the complete
hierarchy without changing the sound filters or captured selection. Select a tag
row to filter sounds. Collections and saved views have separate sidebar tabs to
leave room for the tag list.

Counts describe assignments on sounds in the configured User Library, not every
tag in Ableton's global vocabulary. An empty Live list can mean there are no
manual sidecar assignments in that scope, including when tags exist only on
external samples not yet imported into the User Library. Automatic/factory tags
visible only in Live are not imported by this workflow. **Tag sources / help**
explains these boundaries. Use **Rescan library** after external edits; scans
also read ancestor-folder sidecars that reference samples inside the library.
Malformed sidecars still fail explicitly rather than clearing cached assignments.

Select one or more samples and choose **Edit Live tags...**. The dedicated editor
reads the selected sounds' sidecars in the background and lists assigned tags,
with counts such as `18/25` or `25/25`. Click a row to select its exact hierarchy
for removal or renaming. Choose **add** to assign a new tag;
suggestions come from indexed Live assignments and the read-only Live vocabulary.
The **Group** field qualifies plain labels; an explicit `Group|Tag|Subtag` hierarchy
overrides that field. Dropdown choices are suggestions, not assigned tags.
Choose **add**, **remove**, or **rename** in this same editor, then **Preview changes**
and **Save changes**. Rename reveals a **Rename to** field and affects only these
sample assignments, not Live's global vocabulary. **Reload assigned tags** rereads
sidecars without changing assignments; it invalidates any previous preview.

Use **Select page** to add the visible page to your selection, or **Select all
matching** to capture the complete current search/filter result in the background.
The selection persists across pages; deselecting a visible row removes just that
sound. The selection count explicitly includes sounds off the current page.
The Live-tag preview describes that off-page scope, and favorite
changes require confirmation when off-page sounds are included.

Selections are explicit snapshots, not live queries: newly indexed matches are
not automatically added. Tag changes may cause selected sounds to disappear from
the current results, but they remain selected with an off-page count until you
clear them. Changing search/filter/collection scope clears the entire selection
on the next result refresh. Library-change notifications also clear it because
file operations may have invalidated paths. **Clear selection** drops all targets,
including off-page sounds. A delayed select-all result is discarded if you have
changed filters or selection in the meantime. Playback/details require exactly
one selected sound.

### Previewing Live-tag edits

Open **Edit Live tags...**, choose the action, group and tag, then **Preview changes**.
Inspect the per-sample changes, then **Save changes**. No second editor or rename
dialog is needed. The editor captures the current selection, including off-page
sounds, and keeps that exact target list even
if you subsequently change the browser selection or filters. Choose **add**,
**remove**, or **rename**, enter the group and tag, then click **Preview changes**.
No queue step is required for a single edit. For multiple edits, click
**Add another change** to keep an edit and clear the inputs for the next one.
Preview includes the listed extra changes followed by the current entered edit.
Actions run in that order. For example,
adding and then removing the same tag produces no net assignment change.
Renaming affects only assignments on the captured sounds, not Live's global
taxonomy. Existing indexed hierarchy suggestions are available in the tag dropdown.

**Preview changes** reads sidecars in the background without writing
anything. The review shows changed and unchanged sample counts, the number of
sidecars to write, and exact additions/removals per changed sample (the first 200
changed samples are displayed; the totals and save include all targets).
Editing the queue or entry fields invalidates the review. A no-op review cannot
be saved. Close Live before clicking **Save changes**, which writes that reviewed
plan once without a second confirmation dialog. The warning and backup/recovery
limitations remain visible next to Save. Closing/discarding the editor instead
leaves files unchanged.

Planning and saving disable the editor controls. Other Live-tag writes and
selected metadata refreshes in this browser are disabled while the batch editor
is open. The app will not close through its normal close button during review or
save; close/discard the editor after it finishes. Unsaved queues are in memory
only and require discard confirmation when closing. There is no mid-save cancel
or crash-recovery journal; do not terminate the app or run competing file operations.

Sidecar changes or changed/missing samples detected after review abort the save;
review again rather than overwrite newer assignments. A save failure retains the
queue but invalidates its plan, and reports rollback/backup details when recovery
is incomplete. If sidecars save but cache refresh fails, the editor explicitly
reports that outcome and clears the completed queue: rescan instead of replaying
the batch. Existing backups and best-effort rollback limitations described below
also apply to queued batches.

### Discovery and curation searches

**Discovery...** beside the search controls adds constraints to the current
search. Select several indexed tags with Ctrl/Shift, then choose **Match all**,
**Match any**, or **Exclude selected**. You can also choose **No manual Live tags**,
**Has manual Live tags**, or enter a **Missing Live group** such as `Character`.
The tag picker uses assignments across the configured library, not Live's unused
global vocabulary. Group names can be entered even when no assignment in that
group is indexed yet.

These controls use the same search syntax as the results, result counts, tag
facets, and **Select all matching**:

- `live:none`: no enabled manual Live assignments in the cache (local/generated
  tags do not count).
- `live:tagged`: at least one enabled manual Live assignment.
- `missing-group:Character`: no manual assignment under `Character|...`.
  Group matching is case-insensitive and literal, not a wildcard search.
  Sounds with no Live tags also match a missing-group query.
- `"tag:ableton:Sounds|Bass"`: require an exact tag; multiple `tag:` constraints
  mean match all.
- `"anytag:ableton:Sounds|Bass" "anytag:ableton:Sounds|Synth Bass"`:
  match either exact assignment. All `anytag:` terms across the search form one
  OR set; other constraints still combine with that set using AND.
- `"-tag:ableton:Character|Bright"`: exclude an exact tag.

Quote the entire token when a hierarchy or group includes spaces, for example
`"missing-group:Custom Group"`. The builder handles quoting; double quotes and
control characters in tag names cannot be represented by this search syntax and
are reported explicitly rather than producing a misleading filter.

Example: `bass missing-group:Character` finds bass-related indexed sounds needing
Character assignments. Save the search as a collection, capture its matching
sounds, then open **Edit Live tags...** to curate them. Applying discovery constraints clears
the old captured selection just like other search changes. Existing collection
and selected-tag filters remain in effect. Use **Clear all** to start a new search.

Discovery reads the cached **manual** assignments only. A sound that Live
automatically tagged can still match `live:none` here; this does not assert that
Live considers the sound completely untagged. Rescan or refresh selected sounds
after external sidecar edits before relying on these views.

**Reload assigned tags** rereads sidecars in the background and updates only the
selected sounds' cached Live assignments. It does not write sidecars or audio.
The targets are captured when refresh starts, so selecting another sound does
not redirect the operation. Write controls are disabled during that refresh.
Changes made in Live are also monitored while the Library is visible when
**Auto-refresh Live tags** is enabled (see below). Legacy app-only tag rows remain
stored but are not exposed or exported by these actions.

### Metadata freshness and external changes

**Auto-refresh Live tags** is enabled for the current session by default. While Library
is visible, a background probe checks roughly every five seconds after the last
probe finishes. It hashes `.xmp` files in indexed sounds' folders and their
ancestors, including metadata folders created after the previous check.
Only metadata associated with already-indexed folder locations is monitored;
this is not an audio-file watcher or a whole-drive scan.

The initial check and changed snapshots require two consecutive identical probes
before refreshing the cache. First-time checks can therefore take roughly ten
seconds plus filesystem/refresh time. Sidecars are checked again during refresh;
detected concurrent changes roll back the cache transaction and retry on a later
probe. This is best-effort consistency, not a lock against Live.

The monitor reads metadata and writes only the app's Live-tag cache. It never
writes audio, sidecars, or Live's database. Local tags/favorites are preserved.
Assignments, result counts, tag groups, and the inspector refresh after a
successful sync. Captured selections are not retargeted: sounds disappearing from
filtered results remain selected and explicitly counted as off-page targets.

Monitoring pauses while Library is hidden, during a full scan or selected
metadata refresh, and while its batch editor is open. Live write/refresh controls
are disabled during a monitoring probe; an already-open edit dialog cannot save
until that probe finishes. Disabling **Auto-refresh Live tags** pauses future probes;
an in-flight read/cache transaction may finish. It does not undo an existing
cache update. The setting is session-only.

The freshness line distinguishes **Full scan** from **Library Live-tag sync**
times, both session-local. A successful selected-only refresh does not claim
the whole library is current. Pending changes, paused monitoring, unavailable
libraries, and malformed/inaccessible metadata are shown explicitly. Failed
monitor refreshes retain valid cached assignments and retry; they do not produce
repeated modal error dialogs. A failed manual scan/refresh still reports its error.

Use **Rescan library** to discover new/deleted audio files or newly introduced
folders, and before relying on completeness. A metadata check is not evidence
that the full audio index is fresh. Large/remote libraries can take longer to
probe; monitoring is single-flight, and can be disabled. Close Live during app
sidecar writes as before; automatic read-side refresh does not make concurrent
writing safe. Factory/automatic Live tags remain outside this manual workflow.

Enter the exact hierarchy, for example `Sounds|Bass|Synth Bass`;
plain labels default to `Sounds|Label`. Names preserve case. A rename applies only
to the selected samples; it does not rename Live's global tag definition or delete
unused tag names from Live. The dialog previews the number of sidecars affected
and requires confirmation before saving.

Existing sidecars receive uniquely named `.bak` backups beside them. Writes use
temporary files and atomic replacement. Changes detected between planning and
saving abort the edit. A multi-file write failure attempts to restore already
written files, provided no concurrent edit has changed them; backups are retained.
These checks do **not** lock Ableton itself or provide crash-safe multi-file
transactions. **Close Live while saving or organizing tagged samples**, then reopen
it to verify the result. Unattended concurrent editing is not supported.

Import/copy, organize/move, duplicate merging, nested-folder repairs, and undo now
transfer manual Live assignments. Copies keep the source assignments; moves clear
them at the source and create them at the destination. Duplicate merging unions
the assignments. Audio transfer is rolled back if sidecar saving fails during
normal operation. This is not a crash-recovery journal for sidecars; keep normal
library backups. Other per-file XMP properties are preserved in existing documents,
but only manual keyword assignments are carried to a new location.

A disposable Live 12.4.7 sample verified that an externally added manual sidecar
tag appears in Live, and that this app can read its assignments into a temporary
index without modifying the audio or sidecar. A subsequent rename of `Test Tag`
to `Test Tag Renamed` and unassignment of `Round Trip Check` in Live were also
confirmed in the real sidecar and temporary app index. New sidecars generated by
the app's writer were then confirmed in Live on both a copied and a moved
disposable WAV, with manual assignments in the Sounds and Character groups.
The writer and transfer paths are also covered by temporary-directory tests. Automatic tags,
colored Collections, factory/device metadata, and global tag taxonomy editing are
not part of this manual sample-tag workflow. Cached Live tags are never converted
into local tags when a sample moves.

The browser reads existing
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
**None**. Tag counts are cached between launches and refreshed whenever the index
changes. Double-click a sound to open its details. Generated `name:` search-tag
buttons can enable or disable those terms without changing the sound file.
App-only custom-tag creation, removal and display are no longer available.

Tags beginning with `name:` or `category:` are generated search/classification metadata.
Manual tags shared with Ableton are edited through **Edit Live tags...**.
Re-indexing refreshes generated tags while
preserving their enabled or disabled state.

Legacy app-only labels, including `type:`, `role:` and `instrument:`, remain stored
but are ignored by search, classification, routing and export. Use Rules for
organization changes; manual Live tags still support reviewed recommendations
and optional XO mode described above.

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

- [ ] Install Python 3.11 or newer and make sure **Tkinter** is included.
- [ ] Open the project folder.
- [ ] Double-click `Launch-Windows.bat`.
- [ ] If Windows says Python cannot be found, install Python again with **Add Python to PATH**
      enabled, or start the app with:

      ```powershell
      python AbletonLibraryManager.pyw
      ```

- [ ] Confirm that **Your Ableton Library** points to the intended library folder.

### macOS

- [ ] Install Python 3.11 or newer with Tkinter support. Confirm `python3 -m tkinter`
      opens a test window before running the source.
- [ ] Open Terminal and change to the project folder.
- [ ] If needed, allow the launcher to run once:

      ```bash
      chmod +x Launch-Mac.command
      ```

- [ ] Double-click `Launch-Mac.command`, or start it without an executable-bit
      requirement from Terminal with:

      ```bash
      bash Launch-Mac.command
      ```

- [ ] Confirm that **Your Ableton Library** points to:
      `~/Music/Ableton/User Library`, or choose the correct library location.

Frozen Mac apps keep settings, the asset index, saved views and move logs under
`~/Library/Application Support/AbletonLibraryManager`, independent of Finder's
working directory and outside the app bundle. Source launches retain their
project-local state. There is no automatic migration from an older source or
portable folder: close both copies and preserve the original profile, database,
saved views and move logs before relocating anything. Do not assume a fresh
profile means earlier settings or recovery files were deleted.

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

# Release readiness audit

## Remediation status and macOS gate

The user authorized the full remediation, then made macOS a priority. The current
Windows source suite passes **347 tests in 53.242 seconds**, including seven
Rules transaction regressions and 21
release-recovery/platform regressions. Editor error checks and whitespace checks
pass. These results are not native Mac or rebuilt-package evidence.

- H1: automatic destructive shell preflight/helper removed. Reviewed repair
  uses metadata-preserving transfers and fsynced pre-transfer undo intent.
- H2/H3: backup includes genuine Live sidecars and explicit AppleDouble files;
  validates manifest, CRC and hashes; scan/write/verification failures remove
  the partial archive and require explicit informed bypass before cleanup.
- H4: root-registered non-daemon jobs, Organize result queues, pending
  sort/preview/undo/backup tracking and native Mac Quit share safe shutdown.
  Active Organize operations cannot overlap. Closing suppresses new work and
  completion/error modals; owned audio playback is stopped.
- H5: ordinary undo validates saved identity and skips changed/legacy
  destinations explicitly. Older logs remain available for manual recovery.
- H6: XO allocates genuinely unused names and uses exclusive-copy fallback;
  occupied/race-created files are retained and copy modification time is
  preserved.
- H8: Discovery applies the same visible-tag policy without removing saved
  personal labels or routing data.
- H7: implemented directly after the bounded agent was cancelled without
  delivering a fix. Profile import and related Rules delete/add/change-folder/
  restore-default/layout actions stage isolated edits, validate and atomically
  save with content-conflict detection before publishing active memory.
  Failed imports show an error only, not Import Complete. Enable/disable uses
  its existing engine transaction without a redundant second save. Seven new
  regressions pass, including the original disk-full reproduction.
  H1-H8 source remediation is verified; rebuilt-package and native acceptance
  remain separate gates.
- Additional Mac-specific repro: AppleDouble XML stubs previously caused
  sidecar parse failure; audio stubs could be indexed and exported to XO.
  Shared filtering now excludes these across relevant scanners/readers,
  prunes old indexed stub records and leaves the physical metadata intact.
  Genuine metadata stays in content backups.

Frozen Mac state now uses per-user Application Support rather than Finder's
working directory. Native Apple Silicon/Intel CI and startup/Quit smoke are
prepared, **not run**. The user has no Mac available and requested GitHub Actions
preparation; the minimum macOS target is still unknown. No source commit/push
or workflow execution is authorized by preparation alone. See the native
acceptance gate in [RELEASE-HANDOFF.md](RELEASE-HANDOFF.md).

The old Windows ZIP remains unsafe and superseded. New candidate
`candidate-mkzpz215` passes **218 overlapping bundled-code tests in 45.663
seconds** against 19 production modules from the exact ZIP-extracted executable,
plus native fresh/legacy startup, responsiveness, resize and graceful close.
The ZIP's 33 files (14,812,224 bytes) have exact manifest/CRC/content-hash
verification. Its SHA-256 is
`58207f62c06c7eafbba0a6766c6262b8a2104824b7c2101a6907a6f74abcf1f2`.
Rules workers now register with root shutdown and refuse new work while closing.
The fixture verifier explicitly reports host Tcl/Tk when external script folders
are absent (Tcl 9 embedded zipfs); native smoke is the separate runtime check.
No native macOS run, publication or personal Live write has occurred.
See [RELEASE-HANDOFF.md](RELEASE-HANDOFF.md) for the exact artifact and evidence.
The findings below preserve the original audit evidence, not the current
implementation of each now-fixed path.

## October 27 evening re-review: release hold

**The prepared Windows candidate is not safe to publish yet.** The 319 passing
source tests, 179 overlapping bundled-code tests and native startup smoke remain
valid results, but they do not cover the defects below. The earlier conclusion
that remaining work was chiefly acceptance was too optimistic.

This pass directly reviewed the current orchestrator, sorter/index/undo,
sidecar editor, Organize backup/repair/preview, Import, Library/watch/discovery,
Rules/profile persistence, Advanced, XO and build/verification surfaces.
No new production fixes, commits or publication were performed.
Reproductions used temporary files, mock failures and isolated UI fixtures.
Destructive PowerShell commands were intercepted, not executed.

| ID | Priority | Confirmed finding | Release action |
|---|---|---|---|
| H1 | P0 blocker | Automatic move-mode preflight runs force-moving/recursive-removal shell repairs outside reviewed metadata-safe moves and undo logging. | Remove automatic destructive repair; route any retained repair through reviewed, collision-safe, metadata-preserving operations. |
| H2 | P1 high | Backup write failures are counted then ignored; cleanup starts even when zero files were archived. The outer error callback also loses its exception variable. | Fail closed on incomplete backup, report failed paths, retain the original exception, and require explicit informed bypass. |
| H3 | P1 high | The pre-cleanup ZIP excludes every Ableton Folder Info directory and therefore manual Live sidecars. | Include metadata in the recovery archive and verify audio plus assignments can actually be restored. |
| H4 | P1 high | App shutdown ignores active undo/backup workers and several other jobs; undo and backup use daemon threads. | Track mutating jobs across pages and wait/cancel safely before destroying the root. |
| H5 | P2 medium | Ordinary undo does not detect changed destination audio, despite the UI promising changed files are skipped. | Record and validate destination identity before undo; retain explicit handling for older logs. |
| H6 | P1 high | XO's hashed-name collision can overwrite an existing output through its copy fallback. | Allocate genuinely unused output names and never overwrite on link failure. |
| H7 | P1 high | Failed Rules profile import leaves changed active memory and still displays Import Complete. | Stage/validate changes, persist before publishing memory, and propagate failure to callers. |
| H8 | P2 medium | Discovery exposes saved app-only labels even though those tags were intentionally removed from visible UI. | Apply the same visible-tag policy as the browser/editor without deleting stored data. |

### H1: unreviewed cleanup before the safe pipeline

[Move-mode preflight](sorter_engine.py:2050) invokes `Move-Item -Force` and
`Remove-Item -Recurse -Force`; [the legacy flatten helper](sorter_engine.py:2681)
also recursively removes a parent tree after moving only its immediate files.
The first preset repair can therefore delete nested material rather than safely
relocate it. These shell moves bypass `transfer_sample`, per-file collision
handling and `log_move`. Errors/exit status are not checked.

An isolated nested-preset fixture captured two shell calls during a normal
move-mode run, both containing force moves and recursive removal, with no move
log created at either call. The shell commands were not executed. Preview skips
this preflight, so its plan does not describe these mutations.

### H2/H3: backup is not a dependable recovery point

[Backup traversal](tab_organize.py:620) suppresses scan errors and excludes
Ableton Folder Info. Per-file ZIP errors increment `skipped`, but the code still
queues [the success callback](tab_organize.py:698), which starts cleanup.

With one disposable WAV and a genuine Genres assignment, the resulting ZIP
contained only the WAV and was reported successful. With every `ZipFile.write`
forced to fail with disk-full, it logged `0/1 files (100%)` and still called the
success/start-cleanup callback. A separate denied-directory failure caused the
queued [error callback](tab_organize.py:681) to raise `NameError`, because Python
clears the captured exception variable after the except block.

The worker also calls Tk console methods directly. Recovery must cover both
backup contents and job/error lifecycle, not just successful ZIP creation.

### H4: graceful close has an incomplete job inventory

[Shutdown](AbletonLibraryManager.pyw:233) waits for Import/Organize
`active_sorter` and Library rescan/sidebar work. It does not register
[undo](tab_organize.py:514), the pre-cleanup archiver, the separate
`preview_sorter`, Rules workers or XO jobs. In an isolated full-app fixture with
undo deliberately blocked, shutdown called `destroy` while undo was still
active. Actual destruction was mocked to avoid interrupting the fixture.

An exit during daemon-thread undo can stop a multi-file recovery partway through.
Backup completion also risks Tk calls against a destroyed application. The
existing sorter-close tests cover only part of the actual job set.

### H5: normal undo's unchanged-file promise is not enforced

[Ordinary undo](sorter_engine.py:358) checks destination existence and source
absence, then moves the destination back. It stores/checks no post-move content
identity. The duplicate-undo branch has additional safeguards, but they do not
protect ordinary moves.

A fixture moved a sample, replaced the destination bytes, then ran normal undo:
the edited audio was moved back, with `restored=1`, `skipped=0`, no errors.
This does not discard those edited bytes, but it unexpectedly relocates a
user-changed file contrary to the confirmation text.

### H6: XO collision fallback overwrites existing output

If both the ordinary target and six-character hashed target exist and are not
the source, [_unique_name](xo_filter.py:359) returns the occupied hashed path.
[build_folder](xo_filter.py:380) then falls back from the failed hard link to
`shutil.copy2`, replacing that file.

In a disposable fixture, pre-existing hashed output bytes `KEEP-HASHED` became
`NEW`, and the result reported `copied=1`, `failed=0`. If the occupied output is
a hard link, overwriting it can also modify the other linked file.

### H7: atomic disk writes do not make caller state transactional

[Profile import](tab_matrix.py:135) mutates shared rule dictionaries before
[_sync_config_state](tab_matrix.py:76) attempts persistence. That helper reports
an error but does not signal failure or restore memory; its caller then displays
Import Complete. Other Rules actions also mutate shared state before this helper.

A forced disk-full failure left the new rule active in memory, absent from the
unchanged disk profile, and produced both an error and a success dialog. The
atomic writer preserved disk bytes correctly; the higher-level transaction is
the missing part.

### H8: app-only tags remain visible through Discovery

[Discovery](tab_tags.py:1196) lists every `list_indexed_tags` result, unlike the
browser's filtered rendering. A genuine isolated UI fixture with a saved personal
label displayed `my app-only label (1)` among Discovery choices. Hiding these
choices must preserve saved labels and routing overrides, as previously agreed.

### Current release recommendation

1. Fix H1-H4, H6 and H7 before distributing a stable file-management build.
2. Resolve H5/H8 before advertising unchanged-file undo and Live-only visible
   tags; add targeted tests for every reproduction above.
3. Re-run the source and bundled-code suites and native smoke on a new artifact.
   The current ZIP contains these defects; a checksum does not certify safety.
4. Perform hands-on packaged acceptance on disposable content, then separately
   authorize any new Live-side write acceptance. Do not expand taxonomy scope
   merely to ship tonight.

The editor's reviewed sidecar transactions, current-evidence Rules safeguards,
and isolated builder are meaningful improvements. The principal release risk is
now legacy destructive/recovery workflows bypassing those newer guarantees,
not the removal of the read-only viewer or a lack of additional tag features.

## Assessment

**Do not publish the current development tree as a stable release or as full
Ableton tagging parity.** The initial audit found correctness and persistence
failures; the remediation table below distinguishes resolved source defects
from remaining acceptance gates. Further expansion should pause until acceptance
of the narrower current feature set.

## Latest Windows acceptance and scope update

- **319 source tests passed in 53.216 seconds**, including temporary-profile
  whole-app navigation at normal/minimum sizes. Latest edited UI diagnostics and
  whitespace checks are clean.
- Added whole-app real disposable tag-write acceptance: cancel/add/assignment
  rename/remove, exact backups, audio identity, unselected-neighbor preservation,
  rescan after external deletion and refusal of externally changed review plans.
  Fixture database discovery now stays isolated for the entire test lifecycle.
- The user chose to remove the read-only Ableton catalog viewer/source switch.
  The editable browser, sidecar editor, reviewed batches, suggestions and
  read-only database vocabulary remain. The editor now has an independent
  **Vocabulary source...** database chooser; dead catalog help was removed.
- Advanced controls now match documented platform-specific Options.txt flags;
  exact plug-in threshold spelling/range (1–128) is tested. Unknown/legacy lines
  remain unchanged. Documentation verification is not Live behavior acceptance.
- Whole-app acceptance exposed an encoding-breaking Organize debug print and a
  worker-thread Tk call in size inspection; both were fixed. Queue-based
  completion, single-flight scanning and explicit scan failures are covered.
- A real Python 3.14.8 / PyInstaller 6.22.3 Windows build succeeded at
  `release_builds\candidate-nbbt6kxi\dist\AbletonLibraryManager`. Bundled README
  matches source; required tagging modules remain, legacy viewer UI is absent.
- Isolated fresh/legacy package startups, responsiveness, resize, preserved
  custom settings and graceful exit0 passed. All 33 packaged files passed the
  runtime/private-state name check.
- A distribution ZIP and checksum were prepared beside the candidate. Every
  archived/extracted file matches the clean build by SHA-256; archive integrity
  and duplicate-entry checks passed. Native smoke passed on its extracted files.
- **179 overlapping focused tests passed in 48.967 seconds** against code read
  from that executable's embedded archive, including its entry point and all 19
  app modules. This verifies bundled workflow/UI code using the build interpreter
  and bundled Tcl/Tk data; it is not native mouse/keyboard automation.
- Packaged page-click automation did not navigate. Mislabelled screenshots were
  discarded; the reproducible startup smoke explicitly excludes page navigation.
  Packaged operations, real-library performance, broader Live writes and macOS
  acceptance remain open. No personal metadata writes or publication occurred.

## Remediation status after authorized implementation

The findings below preserve the original audit evidence. They are **not all still
open**. The first pass reached **311 passing Windows source tests**; the later
319-test/package pass is recorded above. Personal Live write acceptance and
macOS validation have not been performed.

| Finding | Current source status |
|---|---|
| A1 | Skip Folders uses the validated atomic writer; initialization no longer saves; failures retain prior memory and report an error. Rules' legacy sync writer was routed through the same safe path. |
| A2 | Options read failures/conflicts abort; unknown content is preserved; numeric input is checked; unique backups and atomic replacement are used. |
| A3 | Completed refresh retires unsupported pending candidates within its scope, preserves unrelated scopes and stricter thresholds, and can revive newly supported stale entries. An actual sidecar-change/refresh/approval regression passes. |
| A4 | Missing/unknown/historical provenance cannot approve from saved counts. Refresh must establish current scan evidence. Accumulated candidates have explicit historical provenance. |
| A5 | The Import preview entry point does not create its destination; regression passes. |
| A6 | Broad Bass evidence now uses a neutral Bass folder. |
| A7 | Unverified controls removed; remaining flags checked against official documentation and gated by platform. Exact threshold spelling/range tested. Unknown/legacy content preserved. Per-version Live behavior acceptance remains open. |
| A8 | Real clean candidate built and checked for runtime/private state; existing used output remains untouched. Final publication/archive review remains required. |
| A9 | Non-destructive isolated builder, pinned tool, own-directory launcher and matching development identity verified. Actual Windows build and isolated fresh/legacy startup smoke passed; packaged workflows remain open. |
| A10 | Duplicate moves retain audio recovery and prior metadata with durable undo records before removal. Undo restores both originals; changed destination audio, Live tags or personal app tags cause refusal rather than overwrite. Recovery files consume disk until deliberately removed. |
| A11 | Direct edit plans capture sample fingerprints and reject a replaced sample. |
| A12 | Operation input discards old generated category/name tags before regenerating them. |
| A13 | Watcher refresh advances the dropdown revision; regression passes. |
| A14 | Single-action edits use the existing asynchronous batch review/save workflow. Slow-plan heartbeat regression passes; broad real-storage benchmarking remains open. |
| A15 | Home uses the same reviewability floor/status policy as Rules. |

Configuration mutations are serialized **within this process**, use unique
temporary files, and approval compares expected profile bytes inside the writer
lock. This does not claim an OS-wide transaction against external programs.
Rescan/sidebar workers now queue results without invoking Tk; graceful shutdown
waits for them and active sorters instead of destroying the window after a fixed
five-second deadline. Catalog callbacks are tracked and cancelled on destruction.
Focused lifecycle tests pass, but prolonged real-world close-under-load
acceptance remains a release gate.

**Remaining work is chiefly hands-on packaged workflows, real-library/Live and
cross-platform acceptance, and the separately documented full-parity gaps.** Do not
treat these source fixes as certification of a release. Continue from the
[updated handoff](RELEASE-HANDOFF.md), not the original proposed fix list alone.

The original assessment was a read-only production-code audit. Documentation was updated; production
fixes, personal metadata writes, building, committing, pushing, tagging and
publication were not performed. Three independent reviewers covered core
operations/metadata, UI/lifecycle, and catalog/evidence/integrations. The primary
review covered supporting settings pages, packaging and release claims.
The remediation section above describes subsequent user-authorized code changes.

The assessment applies to the current intentional dirty worktree, not just the
last commit. New modules and tests remain untracked and must be included in any
future authorized source commit. See [the handoff](RELEASE-HANDOFF.md).

## Verified baseline and limits

- Full Windows source suite: **282 tests passed in 39.712 seconds**.
- Independent focused catalog/evidence/suggestions/XO suite: **80 tests passed**;
  these overlap the full suite and are not an additional 80 unique tests.
- Core reviewer: **114 focused tests passed**. UI reviewer: **51 focused tests
  passed**. These also overlap the baseline; do not sum the counts.
- `git diff --check` passed.
- Persistence reproductions used mocks and temporary files, not personal data.
- Python 3.14 and PyInstaller 6.22.3 are available in the terminal environment;
  this does not establish a supported-runtime matrix or packaged correctness.
- No fresh package, macOS run, or expanded Live-side write acceptance was tested.
- Automated coverage is not proof of full taxonomy parity, every-page usability,
  large-library performance, or failure recovery outside the tested cases.

## Findings

Priorities here describe product/release impact, not vulnerability severity.
Existing defects are included because a holistic stable-release decision must
consider the shipped behavior, not just the newest diff.

### A1. High: Skip Folders can silently corrupt the shared profile

**Location:** [tab_exclusions.py](tab_exclusions.py:24),
[flush_changes_to_backend_memory](tab_exclusions.py:44).

The page synchronizes and writes configuration during construction. Its writer
modifies in-memory exclusions first, opens the shared profile directly in write
mode, and suppresses all exceptions. It bypasses the engine's validated atomic
writer and backup path.

**Reproduction:** An isolated existing profile was written through this method
with a simulated write failure after a partial JSON prefix. The on-disk file
contained only `{"partial":`; the method returned without reporting failure.

**Impact:** Opening or changing this page can damage shared settings on an I/O
failure. The UI can appear to have accepted changes that did not persist.
The atomic-recovery guarantee cannot currently be applied to all settings pages.
This is a pre-existing writer, not a new tagging regression.

**Release gate:** Route changes through the validated atomic persistence path,
report errors, and commit memory/UI changes only on success. Cover construction,
read failure, interrupted write, recovery, and unchanged unrelated settings.

### A2. High: Advanced can replace unreadable Options.txt and report success

**Location:** [write_live_options_file](tab_experimental.py:293).

When an existing Options.txt cannot be read, the exception is ignored and save
continues with an empty set of existing settings. Direct write-mode replacement
has no backup, atomic replacement or concurrent-change guard.

**Reproduction:** A mocked UTF-8 read failure with all optional controls empty
produced an empty replacement and one success dialog, with no error dialog.
No actual Live preferences were accessed.

**Impact:** Unrecognized/pre-existing Live options can be lost. Partial write
failures can also leave damaged preferences. This is a pre-existing save path.

**Release gate:** Abort if the original cannot be read; validate edits; preserve
unknown lines; use backup/atomic replacement and conflict detection; test errors
without touching personal preferences. Alternatively withhold this write feature
from the release until it is safe.

### A3. Medium: Rules refresh leaves stale candidates actionable

**Location:** [refresh flow](tab_matrix.py:1505),
[candidate merge](rule_suggester.py:177),
[review eligibility](tab_matrix.py:22).

Refresh scans for currently qualifying candidates, then merges only returned
token/target pairs. A saved pending candidate absent from the scan is not marked
stale or reconciled. The UI still uses its saved count to apply the 20-supporter
floor. Approval can reject recognized evidence after a fresh scan, leaving the
user in a refresh/retry loop.

**Evidence:** The user reported this exact loop and confirmed refreshing did not
fix it. Independent source tracing establishes the lifecycle gap. Existing tests
cover updating returned matches, but not reconciling absent candidates.

**Screenshot limitation:** The displayed legacy provenance and exact selection
are not enough to prove which candidate triggered the rejection. Unknown-source
candidates follow the separate path in A4. Do not claim every screenshot detail
was reproduced or that the guard itself should be removed.

**Release gate:** Reconcile all relevant pending candidates within the actual
scan scope. Mark stale/unavailable evidence explicitly, distinguish historical
count from current support/agreement, and disable approval when unsupported.
Do not delete candidates merely because a different scan scope omits them.
Test the complete scan -> evidence changes -> refresh -> review -> approval flow,
including Use all and all-or-nothing failures.

### A4. Medium: Historical/unknown-provenance approval is not freshly validated

**Location:** [revalidate_candidates](rule_suggester.py:137);
accumulated creation in [sorter_engine.py](sorter_engine.py:1804).

Missing or unrecognized evidence sources pass through the fresh-evidence
validator unchanged. The accumulated-observation path can create such candidates.
The >=20 saved-observation floor still applies, but is not proof of 20 distinct
currently supporting files or 90% current agreement.

This does not invalidate the newer scanned-candidate checks. Historical
accumulated observations are explicitly a different evidence model, but the
approval and UI contract should make that difference unmistakable.

**Release gate:** Give legacy/cumulative evidence explicit provenance and an
intentional approval policy. Prefer refreshing from current files before normal
approval; do not silently imply current-file certification. Test missing and
unknown provenance, deleted files, repeated observations and mixed bulk approval.

### A5. Medium: Import preview creates a missing destination directory

**Location:** [tab_import.py](tab_import.py:188).

The UI creates a nonexistent destination before handing `preview_only=True` to
the engine. The engine's file-operation preview can be correct while the UI still
violates the documented no-filesystem-changes promise.

**Release gate:** Avoid destination creation for preview and add an end-to-end UI
entry-point test asserting that the nonexistent directory remains nonexistent.

### A6. Medium: Broad Bass evidence becomes synth-specific folder advice

**Location:** [tag_evidence.py](tag_evidence.py:10),
[suggested_folder](tag_evidence.py:156).

The broad `Sounds|Bass` category resolves to `Bass`, then to
`Synth Bass One-Shots`. The independent reviewer verified this output. A broad
bass classification does not establish that a sound is a synthesizer one-shot.
This affects advice and explicitly opted-in XO folder grouping; it does not mean
all normal organization silently uses that destination.

**Release gate:** Require specific evidence for the synth destination or use a
neutral Bass destination. Test parent-only, specific child, conflicting, loop and
instrument evidence in every consumer of the shared helper.

### A7. Medium: Advanced labels and verification overstate known behavior

**Location:** [option descriptions](tab_experimental.py:33),
[checkbox mapping](tab_experimental.py:116),
[verification sweep](tab_experimental.py:181).

The UI presents `-_AbsoluteMouseMode` as asynchronous background browser loading.
Ableton's official documentation describes `-AbsoluteMouseMode` as a mouse/tablet
input option. The app uses a different, underscored spelling whose actual behavior
was not verified; neither spelling is evidence of asynchronous loading.

The status also says invalid entries are being "Auto-disabling" without disabling
them, and "Live 12.4 ... Auto-Verified" after a limited text scan rather than
validation by Live. Numeric fields are written without validating their values.

**Release gate:** Verify each exact flag and supported version, correct/remove
misleading controls, validate numeric input, and describe only checks actually
performed. Ableton explicitly warns Options.txt flags are experimental and may
change without warning.

Sources:
[Ableton Pen Tablet Mode](https://help.ableton.com/hc/en-us/articles/209769585-Pen-Tablet-Mode),
[Ableton Options.txt](https://help.ableton.com/hc/en-us/articles/6003224107292-Options-txt-file).

### A8. Release blocker: Used distribution folder is not a distributable artifact

**Location:** Existing local `dist\AbletonLibraryManager` output.

The used runtime directory contains `library_assets.db`, its rollback journal,
and `library_config.json` alongside a stale executable. Only names/timestamps
were inspected; personal contents were not needed for this finding.

**Impact:** Blindly archiving that directory risks publishing private/runtime
state and does not ship the current tested source.

**Release gate:** Build to a clean isolated directory, smoke-test a separate copy,
and inspect the final archive for private configuration, indexes, journals,
backups and temporary files. Do not delete the user's working state as cleanup.

### A9. Medium: Build and source-launch workflows need hardening

**Location:** [build_app.py](build_app.py:7),
[Launch-Windows.bat](Launch-Windows.bat:1),
[Home version](tab_cover.py:36).

- The build helper kills matching app processes by executable name and removes
  build/dist/spec paths before rebuilding. This can interrupt a real operation;
  it was deliberately not executed during the audit.
- No tracked dependency/runtime manifest, CI workflow or build spec was found.
  The local generated spec is ignored. A local global environment is not a
  reproducible release recipe.
- The Windows launcher relies on the caller's working directory; it does not
  resolve the script relative to itself. This is a source-launch portability risk.
- Home still says 2.0.1 while the README/main development window use provisional
  2.1.0. Agree on a version and update all visible/build surfaces together.

**Release gate:** Use a non-destructive explicit build workflow with pinned
requirements where applicable and a documented runtime/toolchain. Test launching
from another working directory and from a clean extracted package. Never kill
unrelated live operations to make a build succeed.

### A10. High: Duplicate moves delete the source without sorter undo history

**Location:** [duplicate branch](sorter_engine.py:2503),
[regular move logging](sorter_engine.py:2526).

The duplicate-move branch merges tags and removes the source, then returns
without recording the operation through the normal move log.

**Reproduction:** An isolated fixture left the source absent and
`move_log_path` equal to `None`. The existing regular-move undo path cannot
restore this duplicate removal from an absent operation record.

**Release gate:** Record duplicate moves with enough information to restore the
source and both original metadata sets. Test sorter-level undo after duplicate
merge, including failure recovery. A duplicate is not authorization to bypass
the app's undo contract.

### A11. Medium: Single-edit plans do not detect a replaced sample

**Location:** [prepare_edit](ableton_tags.py:321),
[commit guard](ableton_tags.py:247),
[batch fingerprints](ableton_tags.py:412).

Batch plans capture sample fingerprints, but direct edit plans omit them.
The commit guard therefore cannot detect a sample replaced between planning
and saving through that API.

**Reproduction:** Replace a temporary audio fixture after `prepare_edit`; commit
succeeds and assigns the planned tag to the replacement.

**Release gate:** Give direct plans the same sample-identity guard as batches.
Test replacement/deletion during review and preserve the original sidecar on
conflict. This finding is a demonstrated API safety gap, not proof that every
current UI edit exposes a long review window.

### A12. Medium: Generated category tags survive reclassification

**Location:** [operation tags](sorter_engine.py:2270),
[copy/move tags](sorter_engine.py:2432),
[index_asset](sorter_engine.py:534).

Operations seed tags from the existing indexed asset and add a new category.
The index accepts the old generated tags alongside the new ones.

**Reproduction:** Moving a temporary indexed `category:Incoming` asset into Kicks
left both `category:Incoming` and `category:Kicks`. An unchanged-file rescan can
skip reclassification, so this is not necessarily self-correcting.

**Release gate:** Preserve personal/manual assignments while regenerating
derived `category:`/`name:` tags from the current asset and classification.
Cover both copy and move and ensure unrelated saved data is retained.

### A13. Medium: External tag refresh does not invalidate dropdown suggestions

**Location:** [suggestion scope](tab_tags.py:707),
[metadata-refresh handling](tab_tags.py:1467).

The suggestion cache uses library path/revision, but the successful external
metadata refresh path reloads the index without advancing that revision.
Source tracing identifies a missing invalidation path; the reviewer did not
report a timed live-sidecar reproduction.

**Impact:** Responsive cached dropdowns can keep showing old choices after the
watcher updates indexed assignments.

**Release gate:** Invalidate/reload choices on successful metadata sync, retain
typed values and error states, and add a watcher -> index -> dropdown regression.

### A14. Medium: Normal selection edits still perform sidecar I/O on the UI thread

**Location:** [selection tag operations](tab_tags.py:957).

The regular editor performs planning, commits and cache refresh synchronously
for its captured selection. The separate batch dialog already uses background
review/save behavior; moving dropdown reads off-thread does not remove this
remaining blocking path.

**Evidence limitation:** The synchronous call path was reviewed, but a specific
freeze duration or selection-size threshold was not benchmarked.

**Release gate:** Reuse the reviewed background-save pattern with captured
targets, explicit errors and safe cancellation. Measure UI heartbeat on slow
storage and large selections; do not rely solely on small local fixtures.

### A15. Low: Home counts candidates that Rules intentionally hides

**Location:** [library_status_summary](sorter_engine.py:274),
[reviewability policy](sorter_engine.py:1794).

Home counts every pending suggestion, while Rules excludes historical pending
candidates below 20 supporters. The user can see a waiting count without that
many actionable review rows.

**Release gate:** Use the shared reviewability policy for the actionable count,
or label retained historical/stale counts separately. Test 5/7/19/20 boundaries.

## Concurrency/lifecycle risks requiring focused tests

These are source-supported risks, **not reproduced failures** in this audit:

- **Concurrent config writers:** [approval byte comparison](sorter_engine.py:1908)
  precedes replacement without a single protected transaction; the
  [writer](sorter_engine.py:172) uses a shared temporary filename. Another writer
  may race the check or collide with the temporary file. Add serialized writes,
  unique temporary files and a concurrent-writer regression.
- **Close during Library work:** [shutdown](AbletonLibraryManager.pyw:234)
  waits for Import/Organize operations, but does not manage Library rescan/sidebar
  workers in the same way. [Library workers](tab_tags.py:1496) call Tk scheduling
  directly. Verify cancel/close during indexing and prevent callbacks after
  destruction; do not assert shutdown recovery based only on sorter tests.
- **Catalog callback cleanup:** [catalog polling](live_catalog_dialog.py:327)
  and [filter polling](live_catalog_dialog.py:453) need explicit close-while-busy
  coverage. Uncancelled polling is not by itself proof of a crash.

Reproduce the exact failure before selecting a fix where practical. None of
these risks justifies broad exception suppression.

## Strengths worth preserving

- Externally deleted indexed files have dedicated reconciliation regression
  coverage; the original stale-total bug is not the reason for this release hold.
- Sidecar work includes exact-path assignment preservation, backups, conflict
  checks and rollback tests rather than direct Live database writes.
- Catalog reads separate provenance and use read-only/WAL-aware access.
- Hierarchical filters, OR-within/AND-across semantics, pagination, native
  selection and stale background-result handling have targeted tests.
- Slow dropdown reads have worker/single-flight/cache regressions, including UI
  heartbeat, retained text and rejection of stale results.
- Shared tag evidence rejects incompatible types and separates roles from sound
  types; unrelated Genre/Character labels do not become routing rules.
- Modern rule approval rechecks current evidence and enforces the new floor.
- XO manual-tag routing is opt-in. Read-only catalog browsing is kept apart from
  editable-library operations.
- Visible app-only tagging was removed without deleting saved data, favorites or
  explicit routing overrides.

The UI reviewer initially reported unreachable app-only controls as a defect.
That finding was excluded: hiding those controls is the user's explicit
requirement, not a feature to restore. A suspected invisible Skip Folders column
was also excluded after a native Tk check confirmed the data column is displayed.

## Full parity is a separate unfinished goal

Do not confuse fixing the findings above with finishing parity:

1. Indexed editable sounds do not provide complete editable workflows for
   presets, racks, MIDI, clips, grooves, tunings, Max devices and Live Sets.
   The separate read-only viewer was removed at the user's request.
2. Virtual plugin/device entries and full plugin Format coverage remain partial.
3. Per-file assignment rename is not global custom-group/tag/subtag lifecycle
   support inside Live.
4. The catalog/evidence allowlists are bounded verified mappings, not universal
   coverage of future taxonomy concepts.
5. Narrow prior WAV acceptance and XML fixtures do not establish acceptance of
   writes on every supported Live item type/version/platform.
6. Windows results do not certify macOS UI, modifiers, packaging or metadata.

No additional Live acceptance writes are authorized by this audit. Ask first and
use agreed disposable fixtures rather than personal or factory originals.

## Release sequence and remaining gates

1. **Stabilization implemented:** Persistence safety, duplicate-move undo,
   direct-edit identity and Rules refresh/approval regressions pass.
2. **Claims narrowed:** Preview side effects, broad Bass routing and Advanced
   labels/validation corrected. Official flag scope checked; Live behavior is
   not claimed as validated.
3. **Choose scope:** Either continue to full parity, or explicitly approve a
   narrower release with the missing workflows prominently documented.
4. **Finish hands-on UI acceptance:** Source normal/minimum-size fixtures pass.
   Test the packaged dropdowns and independent vocabulary choice, cross-page
   selection, batch capture, Rules refresh/bulk actions, Import/Organize and XO.
   Include watcher invalidation, slow sidecar edits and close-while-busy behavior.
5. **Authorize Live fixtures separately:** Verify intended writes, preservation,
   conflicts, cancellation and recovery across the agreed format/version matrix.
6. **Candidate built:** Full tests and clean Windows build passed. Review all
   tracked/untracked source and agree final version strings before publishing.
7. **Complete artifact acceptance:** Fresh/legacy startup, resize, responsiveness,
   settings preservation and graceful exit passed. Permissions, failure messages,
   large-library behavior, packaged operations/cancellation, final archive review
   and platform-specific acceptance remain.
8. **Publish only after approval:** Commit, push, tag and upload only when the user
   authorizes those actions.

The current state is a promising development candidate, not a release candidate
that should be shipped after one final build.

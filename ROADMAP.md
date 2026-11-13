# Improvement roadmap

Updated November 12, 2026. Based on the holistic audit of current source, including
the uncommitted Serum workflows. This is a stabilization roadmap, not a rewrite.
Keep Tkinter, SQLite, reviewed learning, metadata preservation, and disposable tests.

## Next release scope

Agreed November 7, 2026:

- Clear sequential Import choices: Copy/Move, Audio only/Audio + supported
  presets, Preview/Start; move Undo into a separate history/recovery area.
- Review UI clarity across all tabs with a less-is-more approach: prioritize
  the primary task, remove redundant labels/controls, shorten explanatory text,
  and reveal advanced settings and recovery actions only where relevant.
  Preserve discoverable safety warnings, operation status and error details;
  validate layouts at the minimum supported window size.
- Fix Organize fitting poorly at the default window size: measure required
  layout space, increase the initial/minimum size where practical, and ensure
  essential controls remain accessible on smaller displays through responsive
  layout or scrolling rather than relying solely on a larger window.
- Automatic retention for disposable logs/build artifacts and a storage summary,
  protecting active work, validated releases, backups and unresolved recovery.
- Review real-run phase timings and optimize only demonstrated bottlenecks.
- Export complete classification plans, make previews side-effect-free, and
  revalidate input identities/settings before applying an approved plan.
  Explicitly replace the existing preview-index-write contract and test that
  preview leaves profile, index, tags and source/destination files unchanged.
- Show build/version information, add Windows CI, and run clean-package,
  bundled-code, extracted-package and fresh/upgrade startup gates. Record
  hands-on Live/Serum acceptance separately.

Deferred beyond this release: whole-job resume/durability certification and
Copy-import/Serum-copy undo. Existing per-transfer recovery and Move undo remain
supported; this scope does not promise power-loss safety or copy removal.

Implementation: preview-first Import/Organize and complete plan export are wired,
Undo is in shared History / Recovery, and Organize uses scrolling plus screen-aware
window sizing. Marked inactive logs/build artifacts have conservative retention;
Storage accounting remains internal and About identifies dirty-source builds. Windows CI is
prepared, not yet run remotely. Current candidate validation is recorded below;
hands-on Live/Serum/XO and current native macOS acceptance remain pending.

### November 12 cross-platform release candidate preparation

- Feature freeze at v2.2.0-rc.1; Windows x64 and both macOS architectures.
- Reuse platform validation workflows from a tag-triggered candidate workflow.
  Publish an unsigned prerelease only after source/bundled/native/archive checks
  succeed on all platforms and all archives match the clean tagged source.
- Embed the candidate version alongside build/source identity, retain earlier
  schema-1 metadata compatibility, and use LF source checkouts for consistent
  cross-platform byte hashes.
- Add candidate release notes and explicitly retain manual acceptance, high-DPI,
  signing/notarization and whole-job recovery limitations.

### November 12 confirmation labels and simpler XO status

- Shared confirmation buttons now use natural text width plus padding instead
  of a fixed 12-character width. The XO adoption label remains fully visible.
- Removed elapsed time from XO feedback; phase/file/byte progress and Cancel
  remain. No change to verification or replacement safety.
- 31 targeted source UI tests passed without skips. Label/padding/bounds checks
  at three Tk font scales cover approval and cancellation; the responsive XO
  test also asserts that elapsed time is absent.
- Current candidate: `release_builds/windows-20261112-dialog-buttons`.
  572 bundled cases passed, four skips. Native fresh/restart and extracted
  startup passed; all 34 package files passed hash, ZIP and private-state checks.
  Restart tests used the same fixture profile, not old-version migration.
- Source identity:
  `9bfa0f63cb8195fe17958e2047ca983b7d57112a8c20abe82a559d5a957a82d5`.

### November 12 XO rebuild feedback and verification cost

- Moved initial destination hashing from the UI thread into the owned build
  worker. Adoption confirmation remains on the main thread.
- Show phase/file/byte progress throughout verification,
  linking/copying, publication and cleanup; expose Cancel while cancellation
  can still preserve previous output.
- Reuse digests within the job only while device/inode/size/write/change time
  matches. Windows queries native ChangeTime because st_ctime is creation time.
  Cancelled staging cleanup validates entries without rehashing audio.
- Regression tests verify UI heartbeat during blocked verification, cancellation
  during chunked hashing, cache invalidation after edits/restored mtime and at
  most two full audio reads for a stable hard-linked rebuild.
- Prior candidate: `release_builds/windows-20261112-xo-progress`.
  651 source cases and 571 bundled cases passed, four skips each. Native
  fresh/upgrade and extracted-ZIP startup and all 34 package-file integrity/
  private-state checks passed. Native macOS and target-app acceptance remain
  separate gates.
- Source identity:
  `13a83e20a9aef538bf4c720415b4ab01bcc03dbf389a65dad0154b7ac700a37f`.
  Validation used disposable files only; the user's stopped build/output was
  not inspected, restarted or deleted. Compiler duplicates were removed.

### November 12 managed XO replacement

- Build XO folder now builds a complete replacement beside the destination
  before switching it in. Successful managed rebuilds remove stale groups;
  failed/cancelled builds leave the previous output intact.
- First adoption of older unmarked output requires confirmation and retains
  the entire previous folder as a sibling `.previous-...` backup. Managed
  output changed outside the builder is rejected, not silently pruned.
- Keep the portable default `~/XO Samples for Filters` on Windows/macOS:
  outside the User Library and normally outside cloud sync. Same-filesystem
  output can use hard links; other filesystems copy. User folder roots,
  library overlap and linked destinations are rejected.
- Current candidate: `release_builds/windows-20261112-xo-rebuild`.
  Full source suite passed 647 cases, four skips; bundled suite passed 567
  cases, four skips. Native fresh/upgrade and extracted-ZIP startup passed;
  all 34 package files passed inventory/CRC/private-state/hash checks.
- Source identity:
  `433620d0946d28d2c13e9012499a4bde05eb7a5b779309cad0a5dd7abd4ba31d`.
  No real XO output or library was rebuilt. Compiler duplicates were removed;
  the prior Organize-fixes build remains as a fallback. Native macOS, target-app
  acceptance, Python 3.11 runtime and signing remain unverified.

### November 12 Organize corrections

- Fixed More tools menu ownership: Tk requires the menu to be a descendant of
  its menubutton. A new test actually posts the menu rather than only invoking
  entries directly; native Windows menu detection confirms it opens.
- Organize's canvas now gives its content at least the viewport height so
  Activity expands like Import. Content taller than the viewport still scrolls,
  including repeated-folder repair and warnings.
- Pack the bottom status strip before the expanding notebook so it stays visible
  at default/minimum heights. Previously the Options.txt inspection status could
  appear only after enlarging the window; it is shared status, not cleanup work.
- New candidate: `release_builds/windows-20261112-organize-fixes`. Targeted source
  suite passed 50 cases, one skip; bundled suite passed 555 cases, three skips.
  Native fresh/upgrade and extracted-ZIP startup gates passed. All 34 package
  files passed clean-state, exact inventory, CRC and SHA-256 checks.
- Source identity:
  `7c06c90bef75bc09e9ea219e8e3e6abdccb689d1b93e4768ad654264f35793df`.
  Earlier builds are preserved; external release gates below remain unchanged.

### November 12 approved build cleanup

Removed seven superseded Windows release folders, two duplicate validated
compiler-candidate folders, the three old v2.1.1 Windows/macOS ZIPs and their
obsolete checksum file. Reclaimed 417.2 MiB. The current
`windows-20261112-organize-fixes` build, ZIP and validation evidence remain;
their hashes were verified unchanged after cleanup.

The three older `candidate-5cdixp0u`, `candidate-uw1c3_wy` and
`candidate-y2o53mhv` directories now contain only legacy runtime state.
Preserved their settings, databases, configuration backups and Move undo
history in place, with byte-for-byte verification. Historical statements
below about preserved earlier builds describe the state before this cleanup.

### November 12 end-to-end manager workflow pass

- Added six full-application regression cases using disposable profiles/audio:
  Import Copy/Move preview/export/apply, Organize backup/export/apply, global
  History/Undo, safe partial cancellation for both imports and cleanup, renamed
  collisions/duplicate merges, and rejection of changed inputs after preview.
- Verified file bytes, source preservation, sidecar tags, index reconciliation,
  complete backup ZIP contents and archived/refreshed undo history.
- Primary task buttons receive synthetic Tk press/release events; other
  controls use real widget commands. Dialog answers are fixture-controlled.
  Workers/transfers remain real; only cancellation timing is gated.
- Focused source suite: 56 cases, one skip. Current executable bundled suite:
  561 cases, three skips, exercising 25 embedded modules. Both passed.
  No production fixes were needed, and the candidate EXE/ZIP/source identity
  remains unchanged. This is not a full-source suite rerun.
- Native packaged-process input automation, high-DPI, hands-on Live/Serum/XO,
  macOS, Python 3.11 runtime/CI and signing remain separate acceptance gates.
  Coverage and evidence locations are recorded in `RELEASE-ACCEPTANCE.md`.

### November 9 UI-refined Windows candidate

The approved UI audit and XO follow-ups are packaged together in
`release_builds/windows-20261109-ui-refined`. Earlier candidates are preserved.

- Source suite: 632 cases, three skipped; bundled-code suite: 552 cases, three
  skipped, covering 25 embedded production modules. Both suites passed.
- All eight pages rendered at 1180x760 and 1020x700 using disposable fixtures;
  reviewed/running Organize states also captured. Library Rescan has a regression
  assertion for actual footer visibility, not just widget existence.
- Native fresh/upgrade startup, resize, responsiveness, profile preservation and
  graceful close passed for the build and extracted ZIP. All 34 files passed
  private-state, candidate/release identity, ZIP CRC/inventory and extracted
  SHA-256 checks.
- Source identity:
  `f14c24eaa00c275f9c5ad9e7222863ace83cead896ca6eb8bd71f2df8cc5a07c`.
  This is an unsigned dirty-working-tree review build, not a tagged/public release.
- Current guidance is consolidated in `RELEASE-HANDOFF.md`; the earlier long
  handoff is preserved in `RELEASE-HISTORY.md`. Package checksums and evidence
  are beside the current candidate.

Python 3.11 runtime/remote Windows CI, current native macOS, hands-on target-app
acceptance and trusted signing remain external release gates. Python 3.11 grammar
parsing passed but does not certify runtime compatibility. Historical evidence
below applies only to its named candidates.

### November 9 UI review follow-up

- Replaced bright green primary button fills app-wide with muted slate and light
  text; green remains a small active-state/success accent, not an action fill.
- Import choices now form left-to-right groups: Audio type, Operation, then
  Review and import. Audio only / Audio + supported presets stay together, as do
  Copy / Move. Folder selection remains above the flow.
- Removed performance-log and storage-summary controls/explanations from Advanced.
  Automatic local timing and conservative retention remain unchanged; diagnostics
  and storage accounting are support/development facilities.
- Separate review build: `release_builds/windows-20261109-ui-polish`, source
  identity `2251230b7599a2600a3e77d21ba5d1ed09ba8c25a04a18083bd226f7590cc8b8`.
  The earlier expanded candidate has not been overwritten.
- Validation: 620 source cases and 539 bundled-code cases passed, three skips
  each; fresh/upgrade native startup and extracted-ZIP startup passed. All 34
  packaged files passed private-state exclusion, ZIP CRC/inventory and SHA-256
  identity checks. Small-window tests assert grouping/order and muted action
  colors; diagnostic UI assertions replace the removed diagnostic-button tests.

### November 9 XO simplification follow-up

- Preserve the immediate category under `Samples/One-Shots`, including custom
  names, instead of reclassifying organized sounds. Nested folders flatten into
  that category; `Other One-Shots` and audio outside a categorized path retain
  keyword fallback.
- Keyword fallback uses the shared library category names too, preventing
  parallel `808 & Sub Bass` / `808 Sub Bass`, `Cymbals` / `Cymbals & Crashes`,
  vocal, guitar, ambience, FX and synth-category output. Existing organized
  category names and custom fallback groups remain unchanged.
- Simplified the builder to destination, Scan, category selection, Build and
  Include loops. Removed the separate keyword editor, folder-learning suggestions,
  manual Live-tag option and Evidence controls. Existing fallback configuration
  and internal manual-evidence support are retained; other Live-tag tools are
  unchanged.
- Originals are not moved. Existing output remains additive; the dialog explains
  that a new output folder is needed for a clean layout.
- Validation: 82 isolated XO, manual-evidence and foundation/UI cases passed,
  including mixed organized/fallback names, combined-category filename
  collisions, category selection and internal manual-output consistency.
  Category precedence, custom names, fallback, loop filtering, selected groups,
  output naming, source preservation, simplified controls, failed scans and
  small-window scrolling are covered.
- Included in the current UI-refined Windows candidate above, not the earlier
  packages. No real library or existing XO output was modified.

### November 9 fresh UI audit implementation

Reviewed current source and rendered all eight top-level tabs at 1180x760 and
1020x700 using a disposable Windows profile/library. This was an idle-page
layout audit; the implementation also has reviewed/running Organize fixture
captures and automated state tests. Neither substitutes for populated-library,
hands-on running-job/dialog, native macOS or high-DPI acceptance.
No real library or XO output was modified.

- [x] Prioritize Organize hierarchy: keep backup settings separate from actions;
      put Preview and Apply together in reading order, with only the next
      available step emphasized. Keep Cancel with running progress.
- [x] Remove Organize's duplicate History / Recovery entry and instructional
      reminder; retain the global top-bar entry. Consolidate advanced repairs
      and plan export as secondary tools without losing discoverability.
- [x] Avoid repeating the active-library path and chooser in Organize when the
      global bar already identifies the same library. Preserve explicit target
      context immediately before execution.
- [x] Collapse empty warning space, retain actionable backup/size warnings, and
      replace the always-visible idle progress strip with useful operation status.
- [x] Give preview results a readable summary/review surface rather than relying
      mainly on Activity text; keep full details/export available.
- [x] Standardize Import/Organize terms (Preview plan / Apply plan), button
      sizing, secondary actions and disabled states. Preserve Import's existing
      left-to-right choices rather than redesigning them again.
- [x] Fix Home's obsolete "Preview only" instruction and hard-coded version;
      reduce branding/support furniture and prevent bottom-content clipping at
      minimum size.
- [x] Put Advanced Save/Reload with the edited settings, not the file path;
      replace the visible documentation URL with one help link.
- [x] Put Skip Folders' Remove selected beside the list it acts on, not in the
      add-folder input row; disable it without a selection.
- [x] Reduce Library's competing toolbar/selection actions and duplicate saved
      search entry points; use selection-dependent actions while preserving
      multi-selection and tag-source clarity.
- [x] Shorten Integrations copy without hiding hard-link, additive-output,
      OneDrive or target-app verification limitations. Review Rules action
      placement within its nested tabs before changing their functionality.

Implemented locally. Rules keeps its nested workflows, with neutral secondary
Advanced actions and explicit Import profile / Export profile labels. Library
keeps Saved in the sidebar, moves Rescan beside freshness, and disables selection
actions without matching results/selection. Organize has a persistent plan
summary plus its existing detailed review dialog and full JSON export. Validation
and package identity are recorded in the current release handoff; historical
handoffs are preserved separately in `RELEASE-HISTORY.md`.

Local UI/XO implementation, matching Windows package gates and guidance
consolidation are complete. Release work still outstanding: execute Python
3.11/Windows CI and record current native macOS and hands-on Live/Serum/XO
acceptance. Signing is availability-dependent. Whole-job durability/resume,
Copy/Serum-copy undo and broader structured operation/progress work remain
separate future scope.

### November 9 Windows candidate validation

The expanded candidate is available at
`release_builds/windows-20261109-expanded-rc/AbletonLibraryManager`, with its matching
ZIP, source identity, checksums and validation evidence in that release folder.

- 621 source cases passed, three skipped; 540 bundled-code cases passed, three
  skipped, exercising 25 embedded runtime modules. Build-driver fixtures use host
  tooling; they do not imply that the compiler is part of the application.
- Native fresh/upgrade-profile startup, resize, responsiveness, stable-profile
  preservation and graceful close passed for both the release and extracted ZIP.
- All 34 package files passed private-state exclusion, ZIP CRC, exact inventory,
  candidate/release identity and extracted SHA-256 comparisons.
- Source identity: `9c81795d927f8977f9efad646c64f6d4a5ca9488d2f83ee6bea322b99afa966d`.
  This is an unsigned dirty-working-tree build, not a clean tagged release.
- Fixed outdated preview-index expectations and preview-first UI/backup fixtures;
  the previously hanging collision-preview test now completes. Backup ownership,
  explicit failure bypass, cancellation and shutdown coverage remain intact.
- Test screenshots now live in disposable fixture directories, not the worktree.

These are Windows/Python 3.14.8 automated results, not native packaged-page
navigation/editing or hands-on Live/Serum acceptance. Python 3.11 runtime CI and
current native macOS validation have not been run; those remain pending along
with signing, whole-job durability/resume and Copy undo.

## Phase 1: Safety stabilization (in progress)

- [x] Enforce safe relative routing destinations and resolved-path containment.
- [x] Clean up failed ordinary copies without overwriting existing files.
- [x] Guarantee exactly-once completion when scanning is cancelled.
- [x] Keep skipped undo entries available for review and retry.
- [x] Report failed/incomplete Organize previews and execution honestly.
- [x] Reserve collision destinations deterministically across workers; show final
      names, duplicate decisions, and conflicts in preview.
- [x] Stage and verify ordinary transfers before no-replace publication,
      with per-file process-interruption recovery including sidecars and cross-volume moves.
- [x] Retain per-transfer application intent through SQLite and undo checkpoints;
      replay it during confirmed or startup recovery, including ordinary move undo.
- [x] Discover and recover pending transfer journals automatically at startup;
      retain conflicts for Organize review and retry.
- [ ] Reconcile whole-job state after interruption and validate platform/filesystem
      durability beyond process termination.

Exit criteria: isolated regressions for every audited failure, unchanged source
and executable workflow tests, no false clean-success states or unreviewed path escapes.
Do not equate handling an I/O exception with crash-safe atomic file transfer.

### Automatic startup recovery tranche

Startup now scans the active User Library plus source/destination folders named
by the app's move logs, so interrupted undo transfers outside the library are
included. Recovery runs in the background before the Library rescan; it reuses
the verified per-transfer rollback/replay logic and reports retained conflicts.
A per-user OS file lock is acquired before profile migration and held through
startup recovery; the shared job coordinator uses it for later library writes.
This coordinates instances of the updated manager, not Live, older manager
builds, cloud synchronization, or external tools.

This is still per-transfer recovery, not whole-job resume or power-loss
durability certification. Legacy journals without application intent need the
Library rescan to rebuild index state.

Validation: 519 source tests and 407 bundled-code tests passed, with three
skips in each suite. New cases cover automatic committed-transfer and external
undo discovery, conflict retention, cross-process exclusion, lock release after
process exit, startup recovery UI reporting, and lock release after migration
failure. Windows fresh/upgrade-profile startup, responsiveness, resize and
graceful-close smoke passed for isolated candidate `candidate-8d_jijjw`.
Native macOS and Live/Serum acceptance remain unverified.

## Phase 2: Shared application state and job ownership

- [x] Persist one explicit active User Library shared by all tabs.
- [x] Coordinate imports, cleanup, undo, repairs, tag writes, and conflicting index
      jobs application-wide within one process; initially allow only one conflicting writer.
- [x] Coordinate conflicting writers across separate manager instances with a
      per-user process lock; Live and external tools remain outside this lock.
- [x] Use a stable per-user application-data directory in source and packaged
      modes on Windows, macOS and Linux.
- [x] Migrate legacy working-directory settings, SQLite state, caches, backups,
      and move logs without overwriting newer state; retain recoverable originals.

Exit criteria: launching another build or working directory preserves settings,
favorites, and recovery history; conflicting cross-tab jobs cannot start.

## Phase 3: Plan, review, execute, reconcile

- [x] Separate classification plans from persistent asset indexing. Preview leaves
      the index/profile/source/destination untouched; timing logs and locks remain
      operational bookkeeping.
- [x] Export the complete plan rather than only the first 100 console records.
- [x] Include final destination filenames, collisions, duplicates, skipped-file
      reasons, resource preservation, and proposed integration setup steps.
- [x] Revalidate input identities and settings before applying approved plans.
- [ ] Journal per-operation outcomes, unresolved undo entries, retry, and recovery.
- [ ] Use structured job results/progress instead of parsing text in UI panels.

Exit criteria: preview agrees with execution or explains why a plan became stale;
interrupted jobs have actionable, durable recovery records.

## Phase 4: Workflow clarity and measured scale

- [x] Classify learned-rule evidence using actual nested sample paths.
- [x] Surface unreadable/malformed XO configuration rather than silently dropping
      custom types; keep Skip Folders read-only after configuration load failure.
- [x] Use platform-appropriate XO defaults and filesystem-aware volume checks.
- [x] Report failed XO integration files with paths, causes, and safe retry guidance.
- [x] Explain candidate refresh side effects in the Rules UI and user guide.
- [x] Make Advanced Options.txt help actionable with a direct Ableton documentation link.
- [x] Make integration success boundaries explicit in the UI and guide: saved
      sidecars are not proof of Live acceptance; copied resources are not proof
      of Serum dependency resolution or XO folder recognition.
- [x] Report incomplete referenced Live vocabulary hierarchies instead of
      silently omitting suggestions; retain previous choices on load failure.
- [x] Benchmark first-page/warm-search latency, memory, unchanged sidecar polling,
      cancellation latency, backups, and import throughput on large fixtures.
- [x] Automatically record local timings/counts from real Import/Organize,
      backups, Library rendering/search and sidecar polls; keep diagnostics
      internal following the November 9 UI review.
- [x] Avoid repeated unfiltered Library count queries after the sidebar loads:
      real logs measured a 0.283 s median count phase; an 82,215-record disposable
      fixture measured 233.9 ms versus under 0.007 ms for count reuse. Filtered
      views still query; rescan invalidates reuse. Live SHA checks remain intact.
- [ ] Keep dormant catalog-viewer work deferred unless the feature is reintroduced.

Exit criteria: clear source-type detection, actionable errors, explicit integration
limits, and a recorded baseline; set representative performance budgets before
optimization.

## Phase 5: Release and support discipline

- [x] Fix cross-build Skip Folders retention: detect conflicting registered legacy profiles,
      surface missing safety exclusions before Import/Organize, and provide an
      explicit reconciliation flow without overwriting unrelated settings.
- [x] Add a visible Import Cancel control that finishes the current transfer
      safely and clearly reports which completed moves remain.
- [x] Separate audio-only filtering from Copy/Move, with a compact Import UI;
      Preview and execution share the filter, non-audio resources remain intact,
      and audio-only Move warns about preset dependencies and retains undo history.
- [x] Clarify Import as a sequential flow: choose folders, choose Copy or Move,
      choose Audio only or Audio + supported presets, then preview/start.
      Define the supported-preset allowlist explicitly rather than treating all
      non-audio files as presets. Move Undo out of import setup into a separate
      history/recovery area; keep Cancel beside the running operation.
- [x] Expose undo for Move imports, including duplicate merges, using verified
      recovery records; identify the import being undone and preserve unrelated
      operations.
- [ ] Define separate verified-removal safeguards before offering undo for Copy
      imports or Serum resource copies.
- [ ] Add Windows CI alongside native macOS jobs; test the supported Python floor
      as well as the packaged runtime. Workflow for Python 3.11/3.14 is implemented;
      remote execution and the Python 3.11 runtime pass remain pending.
- [x] Generate build metadata and show version/revision in About.
- [x] Package only clean validated outputs; never distribute a used runtime folder.
- [x] Run source, bundled-code, extracted-package, and native Windows startup gates.
- [x] Add automatic retention for old performance-log sessions and disposable
      build artifacts, with explicit age/size limits and protection for active
      sessions, running builds/apps, and validated release outputs.
- [x] Keep an internal storage summary for logs, settings backups, build artifacts,
      undo/recovery history, and library ZIP backups; report cleanup failures.
      Require explicit approval before deleting undo/recovery data or library
      backups, and preserve unresolved recovery records. Not exposed in the user
      interface following the November 9 UI review.
- [ ] Record focused hands-on Live/Serum acceptance separately from automated tests.
- [x] Consolidate current user guidance; archive historical release evidence and
      replace broad claims such as OneDrive insulation with specific guarantees.
- [ ] Pursue trusted signing when available without bypassing OS protections.

Exit criteria: every distribution identifies its exact source/build and validation
limits; no runtime profiles, databases, journals, or recovery data enter archives.

## Incremental architecture

Extract only the responsibilities needed by these phases: application paths and
settings, operation coordination, planning, execution/recovery, and index
reconciliation. Avoid a new framework or wholesale rewrite.

## Audit baseline

- Windows, Python 3.14.8 / Tk 9: 399 source cases, zero failures/errors, two skipped.
- Existing Windows executable: 270 bundled cases, zero failures/errors, two skipped.
- These counts predate roadmap implementation. They do not establish current native
  macOS, downloaded-app trust, or hands-on Live/Serum acceptance.

## First stabilization tranche

The five completed Phase 1 items have regression coverage, including Windows
junctions, equivalent extended-path spellings, partial copy failures, cancellation,
mixed ordinary/duplicate undo retries, index reconciliation retries, and outcome messaging.
Preview progress no longer counts each file twice.

Validation: 416 source cases and 287 bundled-code cases, zero failures/errors,
two skipped in each suite; clean Windows fresh/upgrade startup smoke passed.
Full-suite fixtures need an existing disposable default User Library, including
for the dormant catalog viewer test. No real library was modified by these tests.
Native macOS and hands-on Live/Serum acceptance remain unverified for this tranche.

## Collision planning tranche

Ordinary imports and cleanup now plan in stable source-path order before execution.
Preview and execution share exact destination names, suffix reservation, and
SHA-256 duplicate decisions. Files targeting one destination run in plan order;
unrelated destinations still use up to four workers. Failed providers cannot
consume their dependent duplicates. Transfers additionally verify duplicate bytes,
refuse stale inputs/targets, and use no-replace moves or exclusive copy fallback.
Preview reports final filenames, renamed destinations, duplicate merges, and
blocking folder conflicts. Planning detects routing-setting changes before execution.

Starting cleanup still builds a fresh plan: unchanged inputs produce the same
names, but this is not yet an immutable saved approval, full-plan export, or
cross-instance writer coordination. Ordinary preview still updates the index.
This paragraph describes that historical tranche, not current behavior:
the November 7 release candidate replaces preview writes with read-only plans,
complete export and pre-write revalidation.

Validation: 440 isolated source cases and 311 bundled-code cases, zero
failures/errors, two skipped in each suite. Windows clean-package fresh/upgrade
startup, resize, responsiveness, profile preservation, and graceful-close smoke
passed. The 24 new regressions include concurrent same-name files, duplicate/tag
undo chains, stale plans, folder/file conflicts, and no-overwrite transfer/rollback
races. Native macOS and hands-on Live/Serum acceptance remain unverified.

## Staged transfer and interruption recovery tranche

Ordinary transfers now retain the source until verified staging, no-replace
publication, and sidecar completion. JSON journals in the destination metadata
folder preserve audio identities and original/intended sidecars. Organize has a
background scan/confirmed recovery action; unfinished transfers roll back,
committed ones retain their outputs, conflicts stay journaled for review.
Recovery itself is retryable after interruption. Same-folder pending records
block further transfers; source-copy and readonly behavior remain covered.

This is per-file recovery, not an atomic whole-job transaction. Recovery requires
a subsequent Library rescan; SQLite/index and move-log reconciliation are not
automatically replayed. Full Serum resource copies remain a separate workflow.
Hard termination tests do not establish power-loss durability, filesystem
corruption recovery, native macOS acceptance, or cross-instance coordination.

Validation: 460 isolated source cases and 331 bundled-code cases, zero
failures/errors, two skipped in each suite. The 20 recovery tests include actual
child-process exits during staging, publication, partial metadata saves, source
removal, recovery, and committed cleanup; bundled fixtures run extracted executable
code in those children. Clean Windows fresh/upgrade-profile startup, resize,
responsiveness, profile preservation, and graceful-close smoke passed.
All fixtures used disposable libraries; the real User Library was not modified.

Next: job/index/undo reconciliation and application-wide writer ownership
(the in-process ownership tranche below is now implemented).
Phase 1 is not yet complete under those broader recovery criteria.

## Application-wide job ownership tranche

A thread-safe, process-wide coordinator now serializes library writers across
tabs: ordinary/Serum imports and previews, cleanup, backup, undo, nested repairs,
transfer recovery, Live tag saves, favorites/tag-state changes, metadata/index
refreshes, and XO scans/builds. One active lease covers backup through cleanup,
including the explicit backup-failure bypass decision. Declining, closing,
startup failure, cancellation completion, and worker errors release ownership.
Requests to cancel do not release an active worker's ownership early.

Busy actions name the running operation and do not start a second writer.
Automatic metadata monitoring defers silently; automatic rescans retry.
Tag drafts and reviewed XO plans remain available after a busy refusal.
Registered non-daemon metadata/tag workers participate in graceful shutdown.
Read-only browsing/search and review planning remain independent.

This intentionally serializes writers even for different selected folders.
It is not a cross-instance filesystem lock and cannot coordinate Live, cloud
sync, or external edits. Shared active-library/settings persistence, whole-job
restart/reconciliation, and cross-instance locking remain pending.

Validation: 485 isolated source cases and 356 bundled-code cases, zero
failures/errors, two skipped in each suite. The 25 added cases cover atomic
claims, stale releases, cross-tab refusals, cancellation lifetime, worker/start
failures, retained backup ownership and actual Tk backup-to-cleanup execution,
declined backup bypass, graceful shutdown, and index-monitor deferral.
The XO UI regression also verifies that a busy refusal preserves its reviewed plan.
Pylance syntax checks and changed-signature call-site compatibility checks passed.
Clean Windows fresh/upgrade-profile startup, resize, responsiveness, profile
preservation, and graceful-close smoke passed for `candidate-hdigmo9w`.
All fixtures used disposable libraries and profiles; the real User Library was
not modified. Native macOS and hands-on Live/Serum acceptance remain unverified
for this tranche.

## Transfer/index/undo reconciliation tranche

New ordinary imports/copies, cleanup, duplicate merges, nested repairs, and
ordinary move undo record application intent in their transfer journals before
audio changes. Journals are retained until the index transaction and associated
undo checkpoint finish. Confirmed recovery replays committed index updates
idempotently, preserves favorite/dormant tag states during moves, refreshes Live
tags, cancels rolled-back undo entries, and checkpoints completed ordinary undo.
An Undo retry first reconciles pending journals tied to its exact move log.
Completed/cancelled-only logs no longer hide earlier outstanding undo history.

Missing/changed undo records, a different index/profile, occupied restored
source paths, index failures, and checkpoint failures retain the journal with
an explicit error. Committed audio is not rolled back merely because its index
update failed. Recovery replay can itself be interrupted and retried.

Limits: recovery is still a confirmed Organize action, not an unattended startup
rollback. Legacy journals lack application intent and still require a rescan.
This is not whole-job resume, duplicate-merge undo interruption recovery, full
Serum resource recovery, profile migration, cross-instance locking, or
power-loss/filesystem durability certification. Keep the original profile,
index, move logs, duplicate backups, and journals together.

Validation: 500 isolated source cases and 371 bundled-code cases, zero
failures/errors, two skipped in each suite. Fifteen new regressions exercise
real child-process exits at audio, index, undo, and replay checkpoints, plus
copy/duplicate preservation, ordinary undo retry, nested repairs, index/log
failures, profile/undo conflicts, reoccupied sources, and unresolved history.
Child fixtures execute marshalled production modules, including extracted
candidate bytecode in the bundled suite. Pylance syntax and transfer/recovery
signature compatibility checks passed. Clean Windows fresh/upgrade-profile
startup, resize, responsiveness, profile preservation, and graceful-close smoke
passed for `candidate-nl9q2qpk`. Fixtures used disposable libraries/profiles;
the real User Library was not modified. Native macOS, hands-on Live/Serum,
power-loss behavior, and large-library performance remain unverified.

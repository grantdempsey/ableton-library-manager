# Current release handoff

Updated November 12, 2026.

## Cross-platform candidate preparation

The frozen candidate version is **v2.2.0-rc.1**. The tag-triggered
`release-candidate.yml` workflow calls Windows and both macOS architecture
validation workflows before creating an unsigned GitHub prerelease. Windows
tests Python 3.11 and 3.14; packaging uses Python 3.14.

Publication requires all archives to identify the same clean tagged commit,
version and source hash. Source files use LF checkout endings on every platform
so byte-level build identity is comparable. Release notes and manual acceptance
instructions accompany the candidate. CI validation remains pending until its
run completes; the local build evidence below is not substituted for it.

Hands-on third-party acceptance, high-DPI/native interactions and trusted signing
remain unverified and are explicitly disclosed rather than claimed passed.

## Candidate scope

The expanded release candidate includes preview-first Import/Organize with
complete JSON exports and pre-write revalidation, shared active-library state,
History / Recovery, serialized library jobs, transfer recovery, conservative
log/build retention, build identity and Windows CI configuration.

The current UI refinement keeps Organize's Preview plan and Apply plan adjacent,
separates backup settings, shows operation controls only during work, and groups
export/repair under More tools. The global library and history controls are no
longer duplicated there. Home, Library, Advanced, Skip Folders, Rules and
Integrations have received the approved clarity pass. The November 12 follow-up
fixes More tools menu posting, lets Organize's Activity area grow vertically, and
reserves space for the global status strip at default and minimum window sizes.
The Options.txt inspection message uses that shared strip; it is not an
Organize operation.

XO preserves existing one-shot categories and uses the shared library names for
uncategorized keyword fallback. This prevents separate 808/cymbal and other
fallback aliases. The builder now replaces unchanged app-managed output only
after a complete successful build, removing outdated groups. Failed/cancelled
builds preserve previous output. Adopting an older unmarked output folder
requires confirmation and retains its original contents in a sibling backup.
Externally modified managed output is refused rather than silently deleted.
Destination verification now runs off the UI thread. The dialog shows phase,
file/byte progress, with Cancel until publication starts.
Per-job verified hashes are reused only while file identity/change time matches;
incomplete staging cleanup does not reread all audio.
The default on Windows/macOS is `~/XO Samples for Filters`: a dedicated folder
outside the library and normally outside cloud sync. Hard links share contents;
originals are not moved.
Confirmation buttons now size to their labels rather than a fixed character
width, preventing the XO adoption action from clipping. Elapsed time has been
removed from XO status; phase/file/byte feedback and Cancel remain.

## Validation and packaging

The current unsigned Windows review candidate is
`release_builds/windows-20261112-dialog-buttons/AbletonLibraryManager`.
Launch `AbletonLibraryManager.exe` from that folder; keep `_internal` beside it.
The matching `AbletonLibraryManager-windows-20261112-dialog-buttons.zip`, build
identity, checksums and validation evidence are in the same release directory.
Superseded packages were removed in the approved November 12 cleanup.
The earlier Organize-fixes build remains as a pre-XO-replacement fallback.
Compiler/intermediate output for this pass was removed. Three older candidate directories
contain settings/databases and recovery history only; those files remain in
their original locations and must not be treated as disposable builds.

- Current follow-up: 31 targeted source UI cases passed without skips;
  bundled-code suite: 572 cases passed, four skipped, exercising 25 embedded
  production modules. Button label/padding/bounds were checked at three Tk font
  scales, including both confirmation and cancellation; XO feedback is checked
  to omit elapsed time. The prior XO-progress full source run passed 651 cases,
  four skipped; a full source rerun was not needed for this follow-up.
  XO replacement tests cover obsolete-group removal, cancellation/failure
  preservation, first adoption/backup retention, external changes, destination
  guards and publish-failure rollback. The symlink-specific case skipped on this
  Windows machine because symlink creation privilege was unavailable.
  Added checks prove UI heartbeat/cancellation during destination verification,
  cancellable chunked hashes, invalidation after same-size edits/restored mtime,
  at most two audio reads in a stable hard-linked rebuild and hash-free disposal
  of cancelled staging. The responsive-dialog regression also runs against
  bundled code. Windows uses native file ChangeTime, not creation-time st_ctime,
  when deciding whether a cached digest remains valid.
  New regressions exercise actual Tk menu posting (including native Windows
  menu detection), Activity growth and short-screen scrolling, repair expansion/
  collapse, and global status visibility at default/minimum/taller sizes.
  The expanded workflow pass also covers Copy/Move, JSON export, Organize
  backup, partial-transfer Cancel, History/Undo, collision merges and changed
  inputs after preview. These use real workers/files and synthetic Tk button
  events or widget commands, with fixture dialog responses. They do not claim
  native packaged-process input automation or target-app acceptance.
  See [RELEASE-ACCEPTANCE.md](RELEASE-ACCEPTANCE.md) for the exact coverage/limits.
- Changed Python sources/tests passed Python 3.11 grammar parsing; Pylance
  syntax checks on Organize and the application shell found no errors.
  This does not substitute for Python 3.11 runtime execution.
- Native fresh and same-fixture-profile restart startup, resize and graceful
  close passed; fixture profile files remained present. ZIP-extracted fresh
  startup also passed. These restarts do not claim old-version migration.
- All 34 package files passed private-state exclusion, exact candidate/release
  comparison, ZIP CRC/inventory and extracted SHA-256 comparison.
- Source SHA-256:
  `9bfa0f63cb8195fe17958e2047ca983b7d57112a8c20abe82a559d5a957a82d5`.
- EXE SHA-256:
  `d26224fd9204eb9bc2df68e8621104a9bc01663cce37b3df2b57d2373e3e9330`.
- ZIP SHA-256:
  `7ee6a92e484bc7c2a81ef995c9d6073c38609a51f7649f82fa895937acfdd6a2`.

The historical November 9 UI-refined candidate had 632 source cases and 552
bundled-code cases, three skips each, plus eight-page source fixture captures.
Those are historical results, not a full-source rerun for November 12.
Its build output was removed during cleanup; the recorded results are historical.

This is a dirty-working-tree build, not a clean tagged or signed release.
Prior evidence and hashes are preserved in [RELEASE-HISTORY.md](RELEASE-HISTORY.md).
No commit, push or publication has been performed for this pass.

## Remaining release gates

- Complete the tagged Windows CI workflow, including Python 3.11. Only Python
  3.14 is installed in this environment; native CI certifies the frozen commit.
- Run current native macOS source/build/extracted-app gates on both supported
  architectures. Earlier macOS results do not certify the current source.
- Record hands-on Live/Serum/XO acceptance using disposable content. Follow
  [RELEASE-ACCEPTANCE.md](RELEASE-ACCEPTANCE.md); sidecar writes, copied resources
  and built folders are not proof that the target app accepts them.
- Obtain approved signing credentials/services before claiming trusted
  distribution. Do not bypass OS protections.

Whole-job resume/power-loss certification, Copy-import/Serum-copy undo, broader
structured operation journals/progress and dormant catalog-viewer work remain
deferred. Existing per-transfer recovery and verified Move undo remain supported.

## Safety boundaries

Use disposable profiles/libraries for validation. Never distribute used runtime
folders, profiles, databases, journals, undo history or personal paths.
Do not delete unresolved recovery data or library backups as build cleanup.
The manager's lock does not coordinate Live, cloud sync or external edits.

See [ROADMAP.md](ROADMAP.md) for the implementation checklist and
[README.md](README.md) for the current user workflow.

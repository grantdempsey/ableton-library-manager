# Release handoff

Updated: October 29, 2026, optional-preview workflow and verified Windows test package.

## Latest workflow update

Save changes now prepares and confirms a draft directly; Preview changes is
optional. The focused Library/release-acceptance suite passes 86 tests.
The user chose to skip further manual acceptance for now. Those checks remain
unverified, not passed. The user subsequently authorized pushing the commits and
updated Apple Silicon/Intel CI validation, and confirmed signing credentials
are unavailable. Keep artifacts explicitly unsigned test builds; do not bypass
OS protections. Tagging and release publication remain unauthorized.
Commits `720c418` and `21ad0af` are pushed. The latter's `[skip ci]` marker
suppressed push validation; this handoff update triggers a fresh run. Updated
native Mac results are pending, not passed.

### Latest Windows test package

- Production source commit: `720c418` (pushed).
- Candidate: `release_builds\candidate-o4umhk6n`.
- ZIP: `release_builds\candidate-o4umhk6n\AbletonLibraryManager-720c418-windows-unsigned-test.zip`.
  The matching `.zip.sha256` file is beside it.
- ZIP SHA-256:
  `105fad15c1da6bc9d749c2fccb93f627b8ee8ba4381b4fa91e9dcc92bd2513d0`.
- Executable SHA-256:
  `ef9b6b36f297062fe73f0fa2c7e4c709e79bb2867ef2e8543e4ed7ce4e97018d`.
- Built with Python 3.14.8 / PyInstaller 6.22.3 on Windows 11.
  All 33 packaged files passed private/runtime-state checks, ZIP manifest/CRC,
  and original/archive/extracted SHA-256 comparison.
- Exact ZIP-extracted executable bundled-code fixtures: 226 tests ran
  successfully in 41.218s, one POSIX-only skip, exercising 19 production modules.
  Tcl/Tk fixtures use the host interpreter; native startup is checked separately.
- Native smoke on copies of the ZIP extraction passed fresh and legacy-profile
  startup, responsiveness, resize, profile preservation and graceful exit 0.
  No security-policy bypass or change was used. This supersedes the blocked
  startup of the older candidate; it is not signed/downloaded distribution
  acceptance or packaged page-navigation/Live acceptance.
- No new full source-suite or native macOS run was performed for this change.
  The bundled README matches source at `720c418`; this later results entry is
  not part of that already-verified archive.

The platform results for `2e76076` below predate this workflow change and do not
validate its new package or native macOS behavior.

## Current tagging redesign

The user requested removal of app-only tagging and one consolidated Live editor.
This supersedes the earlier hidden-panel and preview-button work below.

- Removed app-only creation/editing controls and the intermediate/rename dialogs.
  Edit Live tags opens one fixed-selection editor with current assignments and
  counts, add/remove/rename fields, optional additional edits, and Save with
  optional Preview.
  Opening/reloading reads sidecars in the background without writing assignments.
- Legacy app-tag database rows remain dormant: excluded from search, facets,
  classification, rule learning and XO export. New app-tag writes are rejected.
  Favorites and generated classification/search metadata remain supported.
  Old sidebar snapshots are invalidated so they cannot expose legacy labels.
- Recovery snapshots retain complete stored rows separately from visible tags.
  Duplicate undo preserves enabled/disabled legacy data and still refuses changed
  metadata; historical snapshots without the new raw-row field remain supported.
- Live editor polish uses scoped higher-contrast fields, raised sections, clearer
  headings, an emphasized Save action and a separate close-Live warning.
  Contrast ratios and minimum-size multi-edit/rename layout have regression tests.
- On October 29, the user confirmed that an added tag appeared in Live and that
  removing it made it disappear. The editor now lets Save changes plan and confirm
  a draft directly; Preview changes is optional for detailed per-sample inspection.
  Saving without preview summarizes affected sounds, tags and sidecars before the
  write. Focused Library/release-acceptance tests pass (86 tests). Rename
  visibility, untouched-neighbor/audio checks, and the Live/Windows versions were
  not reported, so full human acceptance remains open. See
  [RELEASE-ACCEPTANCE.md](RELEASE-ACCEPTANCE.md).
- Native run 40626941834 exposed an initial idle assignment-read race that could
  invalidate a completed inline preview. Reproduced deterministically on Windows;
  starting a preview now cancels the pending initial read.
- Final production source: `2e76076` (contrast/race fix `26740ce`, followed by
  minimum-size preview refinement). Windows source suite: 358 tests passed in
  48.699s, one POSIX-only skip. Themed expanded multi-edit/rename preview remains
  64px high at 680x620 after repeated resizing, with no callback errors.
- Final Windows candidate: `release_builds/candidate-hz8sv07x`.
  Bundled-code fixtures: 224 tests passed in 40.688s, one POSIX-only skip,
  exercising 19 production modules. All 33 ZIP-extracted files match their
  original SHA-256 hashes, with no private/runtime files found.
  Final native launch was blocked by Windows Application Control; testing stopped
  without bypassing protection. Earlier successful native smoke on `26740ce`
  does not validate this final executable.
  Unsigned ZIP: `tester-download/AbletonLibraryManager-2e76076-windows-unsigned-test.zip`.
  SHA-256: `21c06ab7dcb28ea3037ff981ea05808bc6136352c408e21bd63d560308a33722`.
- Native Mac final-source run
  [40628597415](https://github.com/grantdempsey/ableton-library-manager/actions/runs/40628597415)
  passed on `2e76076` for Apple Silicon and Intel: disposable-home source tests,
  native builds, bundled-code fixtures, fresh/legacy-profile native smoke,
  ZIP integrity/extracted-app smoke and unsigned artifact uploads.
  Both `unsigned-macos-15` and `unsigned-macos-15-intel` tester artifacts are
  retained for 14 days with checksums and the acceptance guide.
  This does not establish downloaded-app Gatekeeper trust or Live visibility.
- No release is published. Full human Live acceptance, final Windows native
  package acceptance and trusted signing/download validation remain open.

> **Historical notes below:** The remaining sections are retained as an audit
> trail. Their candidates, feature descriptions, test counts and release
> assessments predate the final source above and are not current acceptance
> evidence. Use the current status at the top of this file.

## Final acceptance preparation

Live tag editing now uses Preview add/remove followed by Save changes, without
a queue step or second save-confirmation dialog. Multiple changes supports
optional extra edits plus the current draft; entry edits invalidate the reviewed
plan. The save warning remains visible, and conflict checks/backups are unchanged.
Windows suite: 356 tests passed in 51.217s, one POSIX-only skip.
Human Live acceptance is still pending. The disposable fixture was verified
unchanged after the user was unsure whether the original workflow had saved.
Restart the already-open test app to load the new UI before continuing.

Organize's cleanup action now reserves its own column; the backup path wraps
on a separate row instead of squeezing the button during resizing. A regression
reproduced the button shrinking to 119px against its requested 139px at 1020x700.
Repeated wide/narrow resizing with a long path now preserves its full dimensions.
The updated Windows suite passes 354 tests in 54.324s, one POSIX-only skip.
Earlier packaged candidates do not contain this layout fix.

The user has no signing credentials available and requested guided Live testing
on this Windows PC. No security controls will be bypassed and signing/trust
remains an explicit public-distribution gate.

- [RELEASE-ACCEPTANCE.md](RELEASE-ACCEPTANCE.md) provides the exact disposable
  Live add/cancel/rename/remove and unchanged-neighbor/audio checks.
- `tests/prepare_live_acceptance.py` creates generated tones, verifies their
  hashes/assignments and launches source with isolated profile/index/library,
  isolated Options location and no personal catalog database discovery.
  It does not launch Live or edit personal content. Four new tests cover the
  fixture, changed-audio/neighbor detection and launcher isolation.
- Before the layout fix, Windows suite: 353 tests passed in 54.691s,
  one POSIX-only skip.
- With the user's authorization, Mac CI now packages each architecture using
  `ditto`, checks ZIP integrity/extracted content, reruns native smoke on the
  extraction, and retains unsigned test ZIPs/checksums/source SHA/guide for
  14 days in Actions artifacts. This is not a GitHub Release or notarization.
  Run [40621547528](https://github.com/grantdempsey/ableton-library-manager/actions/runs/40621547528)
  passed both native jobs for `18e6240`, before the layout fix. That run does
  not establish native validation of the newer layout.

The human Live test remains pending; do not infer acceptance from the generated
fixture's automated round trip. Signing credentials/services still need a user
decision before a trusted stable binary distribution can be completed.

## Current release decision — native automated gates passed

The user authorized commit/push and macOS validation only, **not publication**.
All production source through `0836eef` is pushed and passes native validation:
[GitHub run 40620273566](https://github.com/grantdempsey/ableton-library-manager/actions/runs/40620273566).

| Platform | Source suite | Exact executable bundled-code fixtures | Native app smoke |
|---|---|---|---|
| Windows / Python 3.14.8 | 349 tests, 54.311s; one POSIX-only skip | 220 tests, 49.552s; same skip | Fresh/upgrade startup, responsiveness, resize, close pass |
| macOS 15.7.9 Apple Silicon | 349 tests, 45.251s | 220 tests, 34.307s | Fresh/upgrade startup from `/`, Application Support state and native Quit exit 0 pass |
| macOS 15.7.9 Intel | 349 tests, 73.066s | 220 tests, 60.563s | Same native smoke, both scenarios exit 0 |

Both Mac binaries were built natively and verified as arm64 / x86_64.
Apple Silicon executable SHA-256:
`7d1b9d38225a16749f242484539a2eba23f7335700227871e3571127f96c5915`.
Intel executable SHA-256:
`6b204908b92931e8ff28ecefd3470dc6c6c7f2496158e4114458108dde1377ae`.
Python reports a 10.15 deployment target, but this is **not** older-macOS
certification, and does not imply Apple Silicon support before macOS 11.
CI creates disposable test apps; it does not retain/publish Mac packages.

Current Windows test ZIP:
`release_builds\candidate-ictp6a3t\AbletonLibraryManager-v2.1.0-windows-candidate.zip`.
33 files, 14,812,496 bytes, exact manifest/CRC/archive/extracted-byte verification.
ZIP SHA-256:
`b3e7a8b01020718bc831adf6d5d51b54bc70a055e5d55a5f2e96c542ad37de14`.
Executable SHA-256:
`113f488ce159a1bfc8c5e00a9f4bd8a5660ab74f5ac86fb104a421cc85d7bbcf`.
This supersedes every earlier candidate below. README status updates after
this build do not change production code but must accompany final packaging.

The README-current rebuild `candidate-3krq9pdb` passed 220 bundled-code tests
in 47.482s (one POSIX-only skip), exact archive hashes and private-state checks,
but **Windows Application Control blocked native process startup** during its
final smoke. No policy bypass was attempted. This is not a successful native
smoke, and it is not the recommended distribution artifact. The preceding
`candidate-ictp6a3t` contains identical production code and passed native smoke,
but that does not prove a new unsigned binary will be trusted on another PC.
Windows signing/trust verification is therefore also a distribution gate.
The blocked rebuild's ZIP SHA-256 is
`899c02130a939587d0590f0f18583c34ff486f93c2214c7bca0b61c7b303f849`;
its executable SHA-256 is
`9cf5e8373faa4e90c50a595b1d6bfb192596e19a01cac727ac5ed081db6f345c`.

### Remaining publication gates

1. Hands-on acceptance of the final packaged pages, selection/modifier behavior,
   dropdowns, audio and reviewed writes on disposable content. Automated
   fixtures do not certify physical input or Live-side acceptance.
2. Explicitly approve any disposable Live writes and confirm save/reopen behavior.
   No personal/factory metadata has been written by this validation work.
3. Choose and test the distribution/signing/notarization route for Mac users.
   No Developer ID/notarization or downloaded-app Gatekeeper check was performed.
   Do not advertise older macOS compatibility without additional native testing.
   Resolve Windows Application Control/code-signing trust for the final binary
   as well; do not disable protection to manufacture a passing smoke.
4. Confirm the provisional release version/scope. Full Ableton tagging parity
   remains incomplete; the editable-audio/tagging scope and removed viewer are
   intentional. Do not promise non-audio/global-taxonomy editing.
5. Only after explicit publication approval: produce final distribution packages,
   retain both Mac architectures, verify checksums, tag and publish.

All notes below that say CI is only prepared or native Mac runs are unavailable
are historical and superseded by this section. No tag or release exists from
this validation work. The unrelated local `AbletonLibraryManager-v2.0.1.zip`
was deliberately left untracked and untouched.

## Native validation follow-up

Source is now pushed with authorization; no tag or publication is authorized.
Native CI confirmed and corrected:

- Windows-only permission handling previously stripped POSIX source read bits,
  breaking copy/move on Macs. It now runs only on Windows; the native mode
  regression passes alongside copy/move/undo workflows.
- Library sidebar sizing now retains the existing minimum tag-list height
  under Aqua. The inactive legacy viewer's Close button also reserves space.
- An automatic startup rescan could enter a modal wait during metadata edits.
  Stack traces from real Mac runners identified this reentrancy. Automatic
  rescans now retry after editing instead of showing a modal; manual rescans
  retain their explicit busy notice. A regression covers the deferred branch.
- Apple Silicon at commit `2aefe7e` passed the 348-test source suite and native
  build. This is intermediate evidence, not final packaged certification.
  The updated run includes the startup-rescan fix on both architectures.
- CI has bounded source/smoke stages, diagnostic stack dumps and concurrency
  cancellation for superseded pushes. All fixtures use disposable home/library
  content, not personal Live files.

All previously listed Windows ZIPs predate these native-discovered fixes and
are superseded. Build and verify a new candidate before distribution.

## Authorized validation push

The user authorized committing and pushing the release source and running
native macOS validation, explicitly **without tagging or publishing**. The
macOS workflow now runs on pushes to `main` as well as manual dispatch, so the
authorized source push starts Apple Silicon/Intel validation without requiring
a separate Actions CLI credential. Actual CI results must be recorded before
recommending release; the earlier local-only workflow status below is historical.
The source launcher's executable bit is now included in the release commit,
with LF line endings. Earlier notes about its unset tracked bit are superseded.

The first native Apple Silicon run (40619005212) exposed a genuine POSIX
permission bug: applying Windows `S_IWRITE` removed read permission before
copy/move. The permission adjustment is now Windows-only, with a native POSIX
mode-preservation regression. Native Mac tag-list sizing also failed the
existing 70px minimum; the collection header/search padding is more compact
without weakening that requirement. The legacy, inactive catalog dialog now
reserves footer/details space before expanding its panes. Windows validation:
348 tests, one POSIX-only skip, passed in 61.971 seconds. Native revalidation is
required; the earlier Windows candidate predates these fixes and is superseded.

## Latest verified Windows candidate

H1-H8 source remediation is implemented. **347 source tests passed in 53.242
seconds**. The Rules workers also register with safe shutdown, refuse new
reviews/scans during close and suppress completion dialogs after close begins.
The existing UI regression verifies non-daemon/root-registered review work and
refusal to start new work while closing.

- Candidate: `release_builds\candidate-mkzpz215\dist\AbletonLibraryManager`.
- ZIP: `release_builds\candidate-mkzpz215\AbletonLibraryManager-v2.1.0-windows-candidate.zip`.
- ZIP SHA-256:
  `58207f62c06c7eafbba0a6766c6262b8a2104824b7c2101a6907a6f74abcf1f2`.
- Executable SHA-256:
  `a401a2032cdb657d5de93aac0c55e5b08828c25d867b419c28755553ddb430be`.
- Clean ZIP: 33 files, 14,812,224 bytes; exact file manifest, CRC and every
  original/archive/extracted byte hash verified.
- **218 overlapping tests passed in 45.663 seconds** against 19 production
  modules extracted from the exact ZIP's executable, including seven Rules
  transaction regressions.
- Native fresh/legacy-profile startup, responsiveness, resize and graceful
  close passed on that exact extraction in disposable profiles.
- Tcl 9.0.4 stores scripts in embedded zipfs rather than external `_tcl_data`
  folders. The verifier now reports host Tcl/Tk use for those fixtures instead
  of treating missing external folders as a broken package. Native process
  smoke separately verifies the executable starts with its actual runtime.
- Evidence: `files\rules-transactions-final-tests.log`,
  `files\build-remediated-final.log`, `files\bundle-remediated-final-archive.log`
  and `files\package-smoke-remediated-final\package-smoke.json`.

This supersedes `candidate-nbbt6kxi` (unsafe pre-remediation) and intermediate
`candidate-3mx775b7` (before final Rules lifecycle guards). Use neither older
candidate for distribution. The new ZIP is an unpublished Windows test
candidate, not Mac validation or hands-on packaged/Live acceptance.

## macOS is a required release gate

The user explicitly prioritizes Mac collaborators. A Windows test/build pass
is not sufficient to release this update. No native Mac host has been used in
this pass; simulated Darwin branches are regression tests, not certification.
The user has no Mac access and chose GitHub Actions preparation. The oldest
macOS version needed is unknown. Prepare CI without choosing an unsupported
compatibility promise; source commit/push and actual execution are separate
steps, not implied publication approval.

Implemented safeguards and preparation:

- Frozen Darwin settings/index use
  `~/Library/Application Support/AbletonLibraryManager`, not Finder's working
  directory or the app bundle. Derived saved views, cache, profile backups and
  move recovery use the same per-user location. Source state stays project-local;
  no automatic migration from earlier source/portable folders is performed.
- Native `tk::mac::Quit` routes through the same job-aware close as the window
  button. Owned preview playback is stopped; active mutating workers are waited
  for rather than daemon-killed.
- AppleDouble `._` audio/XML stubs are excluded from indexing, sidecar reads,
  sorting, nested-repair scans, Rules scans and XO. A rescan prunes previously
  indexed stub records but never deletes the files. Backups still include the
  explicit files, including AppleDouble and genuine Live sidecars.
- The source launcher stays in the foreground, reports failures and uses LF.
  Its tracked executable bit is not set: use `bash Launch-Mac.command` or
  explicitly grant executable permission locally. Runtime minimum is Python
  3.11 with working Tk; only 3.14 on Windows has been exercised here.
- `.github/workflows/macos-validation.yml` is manual-only, read-only and has no
  publication step. It prepares independent `macos-15` Apple Silicon and
  `macos-15-intel` source/build/bundled-fixture/native-smoke runs. It is local
  preparation, not a workflow run or evidence of passing CI.
- `tests/smoke_macos_package.py` launches a copied exact native app from `/`
  with disposable fresh/upgrade homes and requests native Quit.
  `tests/verify_windows_bundle.py` also accepts `.app` bundles despite its
  legacy name. Its host-interpreter fixtures complement, not replace, native
  process and hands-on tests.

Native evidence still required:

1. Run the workflow or equivalent commands on actual Apple Silicon and Intel
   Macs. Record machine/OS/Python/Tk, executable architecture, deployment target,
   app hash, source tests, bundled fixtures and native startup/Quit results.
   The workflow requires a separately authorized commit/push before it can run.
2. Open the final distributed app in Finder, outside the build environment,
   from a folder with spaces. Verify fresh/upgrade profile preservation and
   per-user recovery paths. Establish and test the oldest macOS version to be
   advertised; macOS 15 CI alone cannot certify older versions.
3. Use disposable libraries for page navigation, Aqua/Retina layout, dropdown
   responsiveness, Command/Shift selection, audition/stop and Command-Q during
   preview, backup, undo, Rules and XO work.
4. Verify Unicode/decomposed names, case-sensitive volumes, an external-volume
   copy fallback, permission failures and the explicit linked-content backup
   refusal. Restore a backup and inspect both audio and Live assignments;
   content ZIPs are not full extended-attribute/ACL/resource-fork backups.
5. Test exact Live manual-tag save/reopen behavior only on explicitly authorized
   disposable Live content. Confirm native Options paths and Mac-only flag
   choices without writing personal preferences as part of automated fixtures.
6. Confirm signing/notarization and Gatekeeper behavior for the intended
   distribution route. No signed or notarized Mac artifact exists from this
   Windows-only work.

Do not silently remove this gate to meet a release date. No commit, push, tag,
upload or publication has been performed for these changes.

## Bottom line

**Release hold after October 27 evening holistic re-review.** Source remediation
of H1-H6/H8 now passes the current Windows suite: automatic destructive repair
is gone, backups cover Live metadata and fail closed, shutdown waits tracked
work, ordinary undo rejects changed files, and XO never overwrites occupied
outputs. H7 Rules transactions are now implemented and verified directly:
staged edits save before activation, failed imports never display success,
and related delete/add/change-folder/default/layout actions use the same path.
The cancelled implementation agent delivered no fix; this was completed directly.
See the current status above the historical H1-H8 findings in
[RELEASE-AUDIT.md](RELEASE-AUDIT.md). The old ZIP still contains the original
defects; use only the new Windows candidate documented above for testing.
Publication is explicitly paused at the user's request. Do not commit/push/tag
or publish while conducting this review.

This is a substantial unreleased feature update, not just the original stale-count
bugfix. Do not publish it as "full Ableton tag parity": that goal is still open.
The new Windows package is verified within the bounds above. Native
Mac/hands-on acceptance is still required, not an unattended release. The user authorized work on the
audit findings without further routine approval. No personal Live acceptance
writes, publication, or commits were performed in this pass.

The subsequent holistic audit is recorded in [RELEASE-AUDIT.md](RELEASE-AUDIT.md).
It found concrete persistence, duplicate-move undo, edit-identity, Rules refresh,
preview and generated-tag defects, plus UI/cache and packaging gaps. See the
audit's remediation status for implemented fixes and remaining gates. Rules
refresh now reconciles unsupported pending candidates; the approval safeguard
remains intact, with a regression covering refresh, retirement and revival.

Home matches the provisional v2.1.0 development identity. The release number is
still provisional. A clean Windows candidate was built and startup-smoked in
disposable fresh/legacy profiles. No commit, tag, upload or publication occurred.

The user explicitly chose to **remove the read-only Ableton catalog viewer and
source switch**, not the tagging work. Preserve the editable Library, Live tag
editor, reviewed batches, tag-aware suggestions and database-backed dropdown
vocabulary. Do not reinstate the viewer as a solution to missing parity.

## Repository and artifacts

- Branch: `main`.
- Last pushed baseline: `c865b96` (stale indexed totals after external deletion).
- Two local commits ahead of `origin/main`: `82d6e9b` (Integrations/refresh
  foundation) and `820d29c` (Library inspector/bulk curation foundation).
- Substantial intentional modified and untracked source follows those commits.
  Preserve it; do not reset, discard, or overwrite the worktree.
- New modules and their tests are still untracked. Include them in a future
  authorized release commit; do not stage tracked files alone.
- `AbletonLibraryManager-v2.0.1.zip` is an unrelated untracked archive, not the
  current deliverable. Do not include it automatically.
- Superseded, unsafe candidate:
  `release_builds\candidate-nbbt6kxi\dist\AbletonLibraryManager`.
  This includes viewer removal but predates H1-H8 remediation. Do not distribute.
- Superseded ZIP:
  `release_builds\candidate-nbbt6kxi\AbletonLibraryManager-v2.1.0-windows-candidate.zip`.
  A sibling `.zip.sha256` file records the checksum. These are preparation
  artifacts containing confirmed audit defects, not a stable release.
- Session evidence: `files\build-tonight-windows.log`,
  `files\test-tonight-release.log`, `files\test-bundle-archive-tonight.log`,
  and `files\package-smoke-tonight\package-smoke.json`.
  The executable SHA-256 is
  `a8dc99c635e9b953c50d639c04de13e6ba77906a74a97dc87c22793ff3607331`.
  The ZIP SHA-256 is
  `6031e4ae25590a03c7c1dbb2de9a0327434be5089c3bd333ca4dbba2ee9301c8`.

## Verified automated baseline

Latest full command:

```powershell
python -m unittest discover -s tests
git --no-pager diff --check
```

Result: **347 tests passed in 53.242 seconds**; whitespace validation passed.
Terminal tests and the build used Python 3.14.8 on Windows, with PyInstaller
6.22.3; that is not cross-platform or all-supported-runtime certification.
Editor diagnostics reported no errors in the latest changed UI/acceptance files.

Relevant regression coverage includes:

- Rules transactions: seven focused tests cover actual profile import failure
  under simulated disk-full, unchanged active memory and disk, no false success,
  persist-before-publish on successful import, preservation of unrelated profile
  fields/metadata, invalid-input refusal, external-change conflict detection,
  failed staged edits and successful layout/add/change/delete/default edits.
  The bundle verifier now includes these tests.
- Release recovery: fail-closed verified archives including Live sidecars,
  AppleDouble retention, failed/missing ZIP entry refusal, no automatic shell
  repairs, logged reviewed repair/undo, changed/legacy undo refusal and
  occupied/race-created XO output preservation with copy timestamps.
- Lifecycle/platform: blocked undo prevents destruction, Toplevel jobs register
  on the application root, error modals are suppressed during close, concurrent
  Organize operations are refused, simulated native-Quit wiring and frozen
  Darwin paths, Mac library/preferences resolution and AppleDouble filtering.
- A forced scan failure moves nothing and reports the retained error through
  the deferred callback rather than losing its exception variable.
- Missing indexed files after external deletion, scope/error safety.
- Exact-path sidecar parsing, assignment preservation, backups, conflicts,
  copy/move/undo and metadata refresh.
- Removal of the catalog source/panel and dead help references; independent
  vocabulary database selection without assignment writes.
- Retained catalog-model/filtering and legacy-dialog tests are historical
  coverage, not an indication that the removed viewer is still an app feature.
- Large/cross-page selections, captured batch targets, explicit write review,
  discovery and saved views.
- Tag-aware previews, rules and opt-in XO grouping; threshold boundaries and
  current-evidence approval validation.
- Slow dropdown queries: workers, UI heartbeat, single-flight/cached reads,
  invalidation/stale-result rejection, batch/rename choice updates, and retaining
  previous choices after errors.
- App-only tagging controls hidden without deleting saved data.
- Atomic profile failure/conflict handling, serialized updates and no Skip
  Folders initialization writes; Options preservation, backups and read failures.
- Duplicate-move undo restores both audio files and prior Live/index assignments;
  direct edit rejects replaced samples.
- Completed Rules refresh retires unsupported candidates, preserves unrelated
  scopes/stricter thresholds, and revives repaired evidence.
- Single-action background review, Tk heartbeat, watcher suggestion invalidation,
  catalog callback cleanup and waiting for active rescan on close.
- Preview entry point does not create missing destinations; build helper uses
  isolated output under mocked execution without deleting used data.
- Whole-app temporary-profile fixtures visit every notebook page at 1020x700
  and 1180x760, open selection/editor/review flows, and detect callback/worker
  failures. Legacy settings survive initialization and Rules refresh.
- Organize size checks use queue/main-thread polling and surface scan failures;
  the encoding-breaking tab debug print was removed.
- Whole-app UI tag-write acceptance: cancellation writes nothing; add, assignment
  rename and removal save to real disposable sidecars and update the index.
  Existing sidecar backups match exact previous bytes; both WAVs and the
  unselected neighbor's assignments remain unchanged.
- Whole-app UI rescan reconciles external deletion/new audio and Home counts.
  An external sidecar edit after review causes explicit save refusal without
  overwrite or backup creation.
- Test database discovery is isolated for the entire fixture lifecycle, not only
  app construction. Dropdown tests cannot discover a personal Live database.

Fresh minimum-size source snapshots were inspected for Library, the Live tag
editor, reviewed changes and Advanced using disposable fixtures. These do not
replace real-library/user acceptance. A supplemental external screenshot refresh
stalled and its owned fixture was stopped; it is not additional acceptance
evidence. The later dead-help cleanup is covered by the regression suite.

The actual clean package contains 33 files and no detected runtime/private state.
The bundled README matches source; tagging modules and vocabulary backend are
present, and `live_catalog_dialog` is absent from PyInstaller analysis. Both fresh
and legacy fixture launches created responsive windows, preserved the legacy
custom-setting sentinel, resized and exited gracefully with code 0.
Reproduce with `tests\smoke_windows_package.ps1` as documented in the README.

The final ZIP contains exactly the same 33 files as the clean candidate; archive
integrity, duplicate-entry exclusion and SHA-256 equality of every original,
archived and extracted file were verified. The native startup smoke above passed
using the extracted ZIP, not a different executable.

Additionally, **179 focused tests passed in 48.967 seconds** against production
code read from the extracted executable's embedded archive. All 19 app modules,
including the actual entry-point code, were loaded from the bundle rather than
the working-tree implementations. These cover the whole-app UI fixtures plus
tag safety, copy/move/undo, Rules, Advanced and inspector behavior.
Run `python .\tests\verify_windows_bundle.py <package-directory>` in the matching
build interpreter. This reuses the source test fixtures and build interpreter
with bundled Tcl/Tk data; it is not native process input automation.
The 179 tests overlap the 319-test source suite; do not sum them.

**Native packaged input navigation is not verified.** Targeted native clicks did not switch
pages; those misleading captures were discarded. The startup smoke intentionally
does not claim page navigation, packaged editing, large-library performance or
Live write acceptance. Source and bundled-code fixtures cover navigation and
disposable writes separately; hands-on use of the running executable remains.

## What exists now

### Editable Library

- Resizable browser, selection details, audition/favorites, discovery, saved views,
  explicit Previous page/Next page controls under results.
- Generated and manual Live tag summary; multi-selection assignment counts.
- Live-only visible tag editor with group/hierarchy suggestions, add/remove
  confirmation, assignment rename, reviewed batches, and disk refresh.
  Single actions now open a pre-populated asynchronous review dialog; review
  changes no files, and Save is still explicit.
- App-only custom-tag creation/editing/display removed from the visible editor,
  tag browser, summary and details. Existing data, favorites and explicit routing
  overrides remain intact. Internal compatibility controls/code still exist;
  removal from the UI is intentional, not a data migration.
- Folder advice is read-only and available in scrollable Sound details, not a
  permanent inspector tab. It interprets supported manual one-shot evidence,
  not audio analysis or a general loop-layout recommendation.
- Background sidecar watcher and distinct full-scan/metadata freshness.

### Shared vocabulary, without a separate catalog viewer

- Library has one editable browser, no catalog panel/source switch.
- `live_catalog.py` remains the read-only vocabulary backend. It is not a new
  editing surface and never writes Live's database.
- **Vocabulary source...** in the Live editor selects a database independently;
  one detected database is automatic, multiple databases require explicit choice.
- Existing manual assignments and cached indexed custom groups remain dropdown
  suggestions; read failures retain prior choices and report the failure.
- The standalone `live_catalog_dialog.py` and legacy tests remain in source for
  now, but the app does not import it and the candidate does not bundle it.

### Advanced

- Only officially documented, platform-specific controls remain. See the README
  for exact options and warnings; flags are experimental/version-dependent.
- The exact managed threshold is `-_PluginAutoPopulateThreshold=` (1–128).
  Old differently spelled or CPU-thread lines are preserved as unmanaged content.
- Atomic save/backup, stale-file refusal, read failure handling and reload remain.
  Documentation verification is not proof that each option changes behavior in
  every installed Live version; no personal Options.txt was modified.

### Suggestions

- Shared Drums/Sounds/Type evidence interpretation across Library details,
  Import/Organize previews, Rules and opt-in XO paths.
- New rule scan default: 20 supporting files, at least 90% agreement.
  Accumulated legacy learning default also raised to 20 observations.
- Historical pending candidates below 20 supporters are retained but no longer
  shown in review or included by Use all. Direct/bulk approval also enforces that
  floor. Retained legacy accumulated evidence updates its existing candidate count
  and can become reviewable on reaching 20, without duplicate candidates.
- Scan candidates are rescanned before approval with at least 20 files and 90%
  agreement (or stricter recorded thresholds). Bulk validation happens before
  the profile write. Legacy accumulated observations are not proof of distinct
  files or measurable 90% agreement; their provenance remains explicitly labeled.
  Historical/unknown-provenance candidates cannot approve from saved counts:
  Refresh must establish current evidence. A successful completed scan retires
  unsupported pending entries only within its scope (and unscoped historical
  entries), preserving them as stale rather than deleting them.
- Loop-layout advisor has a separate manual role/key audit. Its executable
  layout remains filename-based; the evidence audit does not silently reroute.

## Full-parity gaps: release blockers for that claim

1. **Non-audio editing:** editable selection/editor/batch workflows for racks, presets, clips, MIDI,
   grooves, tunings, Max devices and Live Sets are not complete.
2. **Live acceptance:** do not equate XML serialization tests with Live accepting
   tags on every item type. Prior copied/moved WAV acceptance is narrow evidence.
3. **Virtual entries:** devices/plugins without filesystem paths are not covered
   by the filesystem editor workflow.
4. **Format completeness:** verified Ableton/Max mappings are not complete plugin
   format coverage. Unknown identifiers must not default to Ableton.
5. **Global custom taxonomy:** per-file assignment rename is not native Live
   create/rename/delete of global custom groups/tags/subtags. That lifecycle is
   not implemented end-to-end.
6. **Cross-platform/runtime acceptance:** current Windows evidence does not
   establish macOS packaging, display, modifier behavior or sidecar acceptance.

Also manually verify the new UI and latest packaged app before any release,
even if releasing a narrower, explicitly limited feature set.

## Safety and authorization boundaries

- The user previously chose **read-only investigation** rather than additional
  disposable Live acceptance writes. No permission to modify personal metadata,
  factory content or the Live database is implied by "keep going" or this handoff.
- Ask for permission before new Live acceptance writes. If granted, use disposable
  copies in a clearly agreed test location, not the personal/factory originals.
- Keep Core Library/Packs protected. Never inflate manual counts by relabeling
  factory/non-auto assignments.
- Read Live SQLite in read-only/query-only mode with WAL-aware connections.
  Do not use immutable mode or write the database.
- Save-sidecar workflows retain backup, conflict and rollback safeguards.
- No publication/commit/build-number change without authorization.

## Manual acceptance checklist

Start with read-only checks against the real library:

- [ ] Launch from current source, not a stale executable.
- [ ] At the user's normal window size and minimum supported size, inspect
  Library, Live editor, Batch, Discovery, Rules, Integrations and
  Advanced. Check clipping, contrast, keyboard focus and actionable errors.
- [ ] Editable Library page controls affect results, not selection scope.
  There is no catalog source switch. Test actual macOS modifiers separately.
- [ ] Select one, several, off-page and all matching sounds; clear/change filters
  during pending work. Summary generated/manual sources and counts are correct.
- [ ] Open both group and tag dropdowns cold and repeatedly, before/after
  vocabulary loading. No stalls; typed text retained; loading/error states
  understandable. Test multiple-database choice in Vocabulary source..., Batch
  and Rename.
- [ ] Existing app-only custom labels are not displayed/editable; favorites and
  routing overrides still work. No existing saved data was deleted.
- [ ] Read tags from disk and auto-refresh update only intended cached targets.
  No writes occur merely by opening editors or viewing suggestions.
- [ ] Rules: 19 supporters yields no new default suggestion; 20 can qualify;
  below 90% agreement fails. Historical 5/7/19-support rows must not appear or
  approve; Use all must include only qualifying rows. Review evidence, stale
  rejection and thresholds upgraded from old saved values.
- [ ] Preview Import/Organize and XO opt-in/manual folder grouping; no file changes
  from previews. Compare conflicts, roles, kits, loops and non-audio exclusions.

Only after explicit authorization, on disposable fixtures:

- [ ] Live custom group/subtag add/remove/assignment rename and visibility after
  reopening/rescanning Live; distinguish assignment rename from taxonomy rename.
- [ ] Each supported non-audio format once a proper edit surface is implemented.
- [ ] Batch captured scope, cancellation, conflict abort, unique backups and
  recovery. External edits during review must not be overwritten.
- [ ] Copy/move/undo and duplicate handling preserve assignments, original audio
  and expected routing.

## Resume instructions and code map

1. Read this handoff and inspect `git status --short`. Do not redo already
   completed UI changes or call parity complete based on test count.
2. Read the audit's remediation status. Validate the new persistence/undo and
   Rules fixes before expanding scope. Let the user finish acceptance of current pages;
   preserve intentional removal of app-only tagging and the read-only viewer.
3. Establish explicit scope for missing non-audio edit workflows and global
   taxonomy operations; research/verify actual Live behavior before implementing.
4. Request permission for isolated Live acceptance tests when needed.
5. Re-run focused tests, then the suite; update this handoff with observed results.

Key files:

- `tab_tags.py`: Library/editor, background suggestion cache and invalidation,
  selection summaries, watcher UI, vocabulary database chooser and Sound details.
- `live_catalog.py`: retained read-only vocabulary backend/model.
- `live_catalog_dialog.py`: legacy unreachable viewer, not an active app feature.
- `ableton_tags.py`, `live_tag_batch.py`, `live_tag_sync.py`: sidecar safety,
  reviewed batch editing and metadata watching.
- `sorter_engine.py`: index/summaries, operations, approval wrappers and loop audit.
- `tag_evidence.py`, `rule_suggester.py`: shared evidence and suggestion validation.
- `tab_matrix.py`, `xo_filter.py`, `xo_dialog.py`: Rules/advisor and XO surfaces.
- Corresponding `tests\test_*.py` modules: reuse existing unittest/Tk fixtures,
  temporary libraries and mocked database discovery. Never tests against personal
  metadata writes.
- `tests\verify_windows_bundle.py`: runs selected disposable fixtures against
  embedded production bytecode and the embedded entry point.
- `tests\smoke_windows_package.ps1`: native isolated executable startup/profile/
  responsiveness/resize/close checks; no page-navigation claim.

On Windows use backslash filesystem paths and explicit SQLite connection closing.
Tk tests must cancel pending callbacks and destroy roots on the main thread.
Do not install packages unless validation reports a missing dependency or a
dependency manifest changed.

## Packaging/publication gate

Once the user accepts the scope and test results:

1. Decide the release number and accurately state remaining parity limitations.
2. Review all intended tracked and untracked source/tests; exclude archives,
   personal config/index data, backups, captures and build outputs.
3. Run automated tests and platform-specific manual acceptance on exact source.
4. Use the README's build workflow. `build_app.py` is a non-destructive,
   isolated-candidate builder. The pinned Windows build completed successfully;
   rebuild and re-smoke if production source or bundled README changes.
5. Smoke-test the newly built executable, not an older build. Verify included data
   and version strings, cold starts and dropdown responsiveness.
   Startup/profile/close smoke passed on the candidate above; packaged page
   navigation and operation workflows still need hands-on acceptance.
   The existing used `dist\AbletonLibraryManager` directory contains a mutable
   library database, its journal, and a user profile. Do not zip or publish that
   directory. Use isolated clean build and smoke-test locations, and inspect the
   final archive for private/runtime data.
6. Only with authorization: commit, push, tag and publish. Include the required
   `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>` trailer
   unless the user asks otherwise.

Recommendation: postpone release rather than claim parity prematurely. A narrower
release is possible only if the user explicitly accepts the documented limits;
full parity remains a separate completion gate.

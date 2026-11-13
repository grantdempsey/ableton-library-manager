# v2.2.0-rc.8 - Windows and macOS release candidate

This is an **unsigned prerelease for testing**, not a signed/notarized stable
distribution. Keep normal OS protections enabled. If the app is blocked, record
the message; do not disable protections or remove quarantine.

## Highlights

- Clearer Import/Organize layout, adjacent Preview/Apply controls, expandable
  Activity, working More tools, and a visible global status strip.
- Complete preview-plan export, input revalidation before Apply, conservative
  collision handling, verified transfers, and shared History / Recovery.
- Serum User presets use type / pack organization for imports and existing
  library presets, with preview and supported Move undo. Recognized header tags,
  type folders and filename labels guide routing; unclear types stay Unsorted.
  Preset bytes, Factory content and non-preset resource paths are preserved.
  Complete resource imports remain copy-only; rescan Serum after changes.
- Shared active-library state and exclusive library jobs, retained through
  cancellation and backup handoffs.
- Background startup transfer recovery with explicit unresolved-item reporting.
- XO preserves organized one-shot categories and avoids duplicate fallback
  groups. Successful rebuilds replace unchanged app-managed output; first
  adoption retains the old folder in a sibling backup.
- Responsive XO verification, phase/file/byte feedback, Cancel before
  publication, and safe per-job hash reuse. No elapsed-time display.
- Confirmation buttons fit their labels, including the XO adoption action.
- Organize More tools opens on a completed click rather than hover/press menu
  tracking, and unchanged menu states are not repeatedly rewritten by polling.
- Persistent per-user settings/index and build version/source identity.
- Correct XO containment checks when Windows supplies short-name path aliases.

## Downloads and checks

Choose Windows, macOS Apple Silicon (arm64), or macOS Intel (x86_64); do not
substitute one Mac architecture for the other. Verify the download against
`SHA256SUMS.txt`. Extract the whole archive; keep Windows `_internal` beside
the executable. Preserve your existing settings, logs and recovery data.

Publication is gated on Windows Python 3.11/3.14 source tests, native builds,
bundled-code tests, original/extracted startup checks, and macOS validation on
both architectures. All three archives must identify the same clean tagged
source commit. Automated checks do not certify third-party application behavior.

Before using valuable content, follow `RELEASE-ACCEPTANCE.md` with disposable
libraries and keep verified backups. Hands-on Live tag round trips, Serum
resource loading, XO indexing and high-DPI/native interaction acceptance remain
unverified. Signing/notarization is not included in this candidate.
Native Cocoa menu tracking is an explicit manual check: automated tests verify
menu ownership and repair commands on macOS, but do not certify native posting.
The Windows fixture exercises actual native menu posting.

## Known boundaries

- Cancel may leave completed transfers; use History to undo supported Moves.
  Copy imports and Serum resource copies do not have general undo.
- Recovery is per transfer, not whole-job resume or power-loss certification.
- External edits, older manager versions, Live and cloud sync do not share the
  manager's job lock.
- Edited/unknown files in marked XO output cause refusal, not silent deletion.
  A first-adoption backup is retained and must not be confused with originals.
- Native startup and bundled fixtures are not proof of packaged interaction
  workflows or acceptance inside Live, Serum or XO.

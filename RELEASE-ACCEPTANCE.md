# Final release acceptance

These are **unpublished test builds**, not signed/trusted public distributions.
Do not disable Windows Application Control, Gatekeeper or other protection.
If the operating system blocks an app, record the exact message and stop.
Unsigned/ad-hoc signatures do not establish trusted publisher identity.

## Windows: disposable Live test

This tests the current source, not native packaged input or signing. It creates
two short, low-amplitude generated tones and an isolated app profile/index.
Start with monitoring volume low. Keep real projects and libraries untouched.
Do not change Live's User Library location, Options or global taxonomy.

From the repository in PowerShell, create a fixture under your temporary folder:

```powershell
python tests\prepare_live_acceptance.py prepare $env:TEMP
```

Copy the printed fixture path. In the commands below, replace `<fixture>` with
that exact path. Verify the starting state:

```powershell
python tests\prepare_live_acceptance.py verify "<fixture>" baseline
python tests\prepare_live_acceptance.py launch "<fixture>"
```

The second command opens the source app with a disposable profile/index, no
personal vocabulary database discovery and the fixture as its Library. Do not
change its library path or open Advanced preference tools during this test.
The fixture's `runtime` folder holds its settings/recovery data; source code
and your normal application profile are not modified.

1. In Library, confirm exactly two sounds. Audition each briefly, stop, and
   check selection, Ctrl/Shift selection, dropdown response and window resizing.
2. Select **only release_kick.wav**. Open Edit Live tags, choose Genres and enter
   `ALM Release Test`. Click Preview add and check the sample and added tag.
   Close/discard the editor without clicking Save changes.
   Run the `baseline` verification again: nothing should have changed.
3. Enter and preview the same assignment with Live closed. Click Save changes
   (this writes the reviewed changes without another confirmation). Run:

   ```powershell
   python tests\prepare_live_acceptance.py verify "<fixture>" add
   ```

4. Open Live in a blank, unsaved Set. Add **only the fixture's Test Library**
   to Places, not your real library. Wait for indexing and inspect
   release_kick.wav in Live's tag editor. Record whether `Genres|ALM Release Test`
   is visible on the sample and absent from untouched_neighbor.wav.
   Merely finding XML on disk does not count as a Live acceptance pass.
5. Close Live. In the manager, rename that assignment to
   `Character|ALM Round Trip`. Run verification with `rename`, reopen Live and
   check that the new assignment appears and the old one is absent.
6. Close Live. Remove the test assignment through the manager. Run verification
   with `remove`, reopen Live and confirm removal. The neighbor must stay
   unassigned throughout; audio verification must always report unchanged.
7. Record Live's exact version, Windows version, pass/fail for each step, any
   errors, and whether Live needed a rescan/restart to display changes.
   If Live does not recognize a change, stop and retain the fixture for diagnosis.
8. Remove the test folder from Live Places when finished. Do not delete the
   fixture until results and recovery files are no longer needed. Close the
   isolated manager before returning to the normal app.

This deliberately does not automate Live or write your existing content.
Results are not yet filled in: a human must perform and report the checks.

## Mac tester downloads

After both jobs pass, download the matching `unsigned-macos-15` (Apple Silicon)
or `unsigned-macos-15-intel` artifact from the Actions run. Each contains a ZIP
created by `ditto`, its SHA-256 checksum and this guide. Do not substitute one
architecture for the other. Verify the ZIP hash against the checksum file.

The CI smoke runs against the ZIP-extracted app before upload. This verifies
native startup/state/Quit, not downloaded-app Gatekeeper approval. Test opening
the downloaded app in Finder with normal protections. If blocked, record it;
do not remove quarantine attributes or disable Gatekeeper.

Once a trusted distribution is available, repeat page navigation, resizing,
Command/Shift selection, dropdowns, audio/stop and Quit while work finishes.
Use only a disposable profile/library. A Mac Live test should mirror the
assignment round trip above, with Live closed during manager writes.

## Signing and distribution decision

- **macOS:** obtain Apple Developer Program access and a Developer ID Application
  identity, then use an approved signing/notarization service or CI secrets.
  Sign nested code correctly, notarize, staple, and test the downloaded final
  package under Gatekeeper. Never paste private keys or passwords into chat.
- **Windows:** choose an appropriate trusted code-signing certificate/service.
  Sign and timestamp the final executable, verify its signature, then test the
  exact downloaded distribution under the normal Application Control policy.
  Signing does not guarantee every managed policy or reputation check accepts it.
- If those accounts/services are unavailable, keep binary distribution as an
  explicitly limited unsigned test, not a clean trusted stable release.
  Source availability is not proof of packaged distribution readiness.

No signing purchase, credential upload, security-policy change, release tag or
publication is authorized by this checklist.

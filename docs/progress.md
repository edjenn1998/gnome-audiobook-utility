# Development progress

For the current state, see [CachyOS validation](cachyos-validation.md) and the
latest dated entry at the end. Earlier phase records are historical.

Automatic-login and fixed-toolbar work is described in
[authentication/UI verification](authentication-ui.md).

## Phase 1 — research and foundation

- Located `/home/edwin/coding` and created this independent repository.
- Researched upstream source, activity, authentication transition and licenses;
  selected Python/GTK4/Libadwaita, FFmpeg, Mutagen and audible 0.13.1.
- Native application shell launched under Xvfb with GTK 4.22 and Libadwaita 1.9.
- Foundation tests: **6 passed**, including actual native window creation,
  preferences persistence, dependency checks and no-clobber transactions.
- Host is headless Ubuntu, not the requested CachyOS desktop. Native runtime
  packages were extracted into ignored `.deps/`; no system packages installed.

## Phases 2–4 — local audio, merge, metadata

- Implemented actual probing, M4B/MP3 conversion, compatible AAC stream copy,
  progress, cancellation, output verification and atomic no-overwrite publication.
- Implemented natural track order, manual reorder/removal, folder import,
  mixed-format merge and sample-count-derived editable M4B chapters.
- Implemented MP3/MP4 audiobook field mappings, artwork validation/preview,
  add/replace/remove, unknown-tag preservation and transactional metadata editing.
- **13 media/metadata tests passed** using synthetic audio, actual FFmpeg and
  FFprobe. Includes 100-track merge, chapter timestamps, active cancellation,
  cover roundtrips and compressed-audio packet hashes before/after tag edits.
- UI now exposes these operations with native file dialogs, drop targets,
  nonblocking workers, progress/cancel, preferences and flat output directories.

## Phase 5 — Audible adapter

- Browser-only external login callback through audible 0.13.1, redirect validation,
  Secret Service persistence, disconnect, paginated library parsing and US marketplace.
- Streaming HTTPS download queue, length/container validation, bounded retries,
  cancellation cleanup and SHA-256 local-download receipts. Downloads retain the
  delivered MP3/AAXC format and conversion is a separate action.
- Account media licenses stay in the keyring. FFmpeg protected-input secrets are
  passed via anonymous RAM files, not visible process arguments or disk config.
- **13 mocked Audible/download tests passed**: auth state, pagination, session
  expiration, network errors, license denial, active cancellation, verification
  and cleanup. No real credentials or commercial media used.
- Live browser login/MFA, token refresh, actual account library/downloads and
  protected AAX/AAXC decoding remain **unverified pending account-owner testing**.

## Phase 6 — integration and delivery

- Replaced deprecated Adwaita windows with adaptive alert/preferences/about
  dialogs, added accessible button labels and compact action/navigation layouts.
  Native UI test verifies resizing to 400 pixels as well as real media workflows.
- Added concurrent metadata edit locking, standard ID3 comment removal and
  cancellation, bounded redacted diagnostic logs, and anonymous FFmpeg option files.
- Added desktop launcher, icon, AppStream metadata, Meson installation,
  setuptools wheel/sdist, pinned runtime requirements and full AGPLv3 license.
- README includes an actual Xvfb screenshot of the running merge view. Build,
  architecture, account integration and third-party licensing docs are present.
- Full final automated suite: **41 passed, 0 failed, 0 skipped**, in 20.54 seconds.
  PyGObject emitted 162 deprecation warnings from its Python 3.14 event-loop and
  GLib compatibility code. No application test failures remain.
- Ruff and `git diff --check`: passed.
- Python wheel and source distribution: built successfully. Installed-wheel
  native startup smoke test: passed under Xvfb.
- Meson configure and staged install: passed, entirely inside `.deps/install`.
- `desktop-file-validate`: passed.
- `appstreamcli validate --no-net`: passed; one informational pedantic note
  concerns uppercase characters in the conventional reverse-DNS application ID.
- Validation environment: Python 3.14.4, GTK 4.22.4, Libadwaita 1.9.1,
  PyGObject 3.56.2, FFmpeg/FFprobe 8.0.1, headless Ubuntu with Xvfb.
- Fixed integration issues found during development: shared GTK application
  registration in tests, missing Ninja in the build environment, duplicated wide
  navigation, and AppStream's required homepage URL. No remote publication/push.

## Acceptance record

| # | Criterion | Status / evidence |
| --- | --- | --- |
| 1 | Launch on supported desktop | Native Xvfb startup and installed-wheel startup verified; actual CachyOS GNOME/Wayland session pending |
| 2 | GTK4 / Libadwaita | Verified native widgets and dialogs |
| 3 | Import existing audiobook | Native UI worker integration test passed; desktop chooser/drop interaction still needs manual smoke test |
| 4 | Convert to MP3/M4B | Verified actual outputs with FFprobe |
| 5 | Merge multiple files | Verified mixed formats, natural/manual order and 100-track input |
| 6 | Correct M4B chapters | Verified timestamps, counts, titles and decoded signal order/continuity |
| 7 | Edit supported metadata | Verified MP3/MP4 read/write/delete and unknown-tag preservation |
| 8 | Add/replace/remove artwork | Verified exact artwork roundtrips and preview construction |
| 9 | Flat chosen output directory | Verified settings and native UI output destinations |
| 10 | Preserve originals | Verified success, failure, cancellation and no-clobber paths |
| 11 | Responsive operations | Background workers and main-loop-driven native workflow verified |
| 12 | Safe error handling | Verified staging cleanup, packet integrity and edit locks |
| 13 | Automated tests | 41 passed; no failures/skips |
| 14 | Documentation and licensing | Full AGPLv3, dependency notices and requested documents included |
| 15 | Real Audible sign-in | Implemented; fixture-tested only, **account-owner test pending** |
| 16 | Purchased library retrieval | Parsing/pagination implemented and fixture-tested; **live test pending** |
| 17 | Eligible purchases downloaded | Streaming/verification/cancel/retry implemented and fixture-tested; **live test pending** |
| 18 | Download separate from conversion | Separate adapter, queue and native actions implemented; local/fixture paths verified, account end-to-end pending |

## Known limits and next work

1. Run the account-owner checklist in audible-integration.md. No live Audible
   acceptance criterion or protected-media decoding is claimed passed.
2. Test CachyOS GNOME/Wayland, actual file dialogs/drop targets, screen readers,
   system appearance/accent changes and real keyring unlock/disconnect.
3. Add validated download resume and multipart-title resolution. Current transfers
   restart after interruption; unsupported newer license formats are rejected.
4. Evaluate a proven-safe compressed-stream merge path; current merging encodes
   once from normalized PCM. Large books need substantial temporary disk space.
5. Review Flatpak filesystem, Secret Service and browser integration before
   distributing a sandboxed package. No Flatpak release is currently provided.

Conversion conflict choices are rename or fail; destructive output overwrite,
source deletion, retained intermediates, automatic recovery after power loss and
non-MP3/MP4 metadata editing are not provided. These limits are explicit in the
README, rather than represented as finished features.

## AAXC conversion investigation and fix

The account owner reports that real Audible.com authentication, library retrieval
and AAXC downloading work, followed by a protected-inspection error on conversion.
This updates the earlier account-status notes above; the development environment
still cannot independently access the owner's purchased file or keyring.

### Trace and changes

- The original Convert worker did resolve options before calling `convert`, and
  `convert` forwarded them into FFprobe. Source inspection was not unconditionally
  missing its key/IV. Import itself skipped inspection for protected extensions.
- The old resolver ignored download receipts and matched the first bracketed
  filename component. It also reused `media:ASIN` for every download, allowing
  a later voucher to replace the license for a different file of the same title.
- Imports now resolve size/SHA-256 against persistent receipt history and load
  the associated keyring voucher. Moved/renamed files work after restart. Existing
  receipts/ASIN keyring items still work, and the original trailing ASIN is a
  compatibility fallback when no matching receipt exists. New downloads use
  per-download voucher references; old license items are not overwritten.
- Real encrypted synthetic AAXC reproduced a separate conversion failure:
  FFprobe accepted `-/audible_key` but FFmpeg 8.0.1 rejected that syntax despite
  supporting `audible_key`. FFmpeg now reads the same MOV demuxer parameters from
  per-file options in a one-file concat script held in anonymous RAM. FFprobe
  retains its supported private file-option path. No key/IV enters argv.
- Source inspection is performed on import and again during conversion with
  the resolved license. Malformed vouchers and changed known downloads are
  rejected explicitly. FFREPORT is removed from media-child environments.
- Original probe chapters and tags are supplied through a separate ffmetadata
  RAM input; Mutagen transfers cover artwork. `-copyts` preserves negative AAC
  priming timestamps, fixing a leading-sample shift caught by PCM comparison.
  Protected results must fully decode before atomic publication.

### Verification

- Added 14 protected-media regression cases using generated AES-CBC-encrypted
  AAC and an encrypted voucher processed by the actual audible library, plus a
  service-level MPEG download regression that needs no AAXC voucher.
- Verified the full mocked download → secure-store JSON → receipt → restart →
  rename → protected inspection → M4B conversion chain. Decoded PCM matches the
  unencrypted reference exactly; chapter titles/times, usable tags and artwork
  match. Native GTK import/conversion of the renamed protected fixture passed.
- Full suite: **56 passed, 0 failed, 0 skipped**, in 29.17 seconds. Existing
  authentication, library, download, local audio and UI tests still pass.
  PyGObject emitted 230 upstream compatibility/deprecation warnings.
- Ruff and `git diff --check`: passed.
- No `.aaxc` exists in the accessible home directory; there are no application
  receipts/configuration here, mounted `/media` and `/mnt` are empty, and Secret
  Service is unavailable in this session. Therefore the owner's exact
  “Cannot inspect audio” error cannot yet be conclusively attributed or replayed.
- **Blocked:** convert and listen to the already downloaded purchased audiobook
  on its owning desktop. `tools/verify-protected.py` performs conversion, full
  decode and chapter/metadata/source-integrity checks using the existing keyring;
  the resulting M4B still needs a human playback/navigation check. No credentials
  or media keys need to be pasted into the assistant or exported.
- The owner clarified that development runs on Evo over SSH, while the copied
  application, purchased download and keyring are on a separate CachyOS rig.
  Deliver the updated source archive to that existing CachyOS project and run
  verification in its desktop session. Transferring the audiobook alone to Evo
  would not provide access to its locally stored keyring voucher.

## Follow-up after the CachyOS conversion still failed

The owner reports that both conversion actions and the verification command
still fail at protected inspection despite both tools recognizing the normal
Audible options. The purchased file and keyring remain on CachyOS, not Evo.

### Evidence collected on Evo

- The prior transport used CLOEXEC memfds but did not pass them to children;
  instead it gave tools `/proc/<parent-pid>/fd/N` paths. This worked only when
  cross-process descriptor access was allowed.
- A disposable non-dumpable parent reproduced the same catch-all inspection
  error with the real FFprobe, correct fixture keys and genuinely encrypted AAC.
  An explicit reproduction of the legacy route returned **exit 1** with
  **Error opening file** and **Error reading the value for option audible_key**.
  FFprobe's loader did not include the OS errno. An independent child read under
  the same restriction returned **EACCES (13)**. No system security settings changed.
- The identical source and license are inspected successfully using child-local
  `/proc/self/fd/N` paths and explicit `pass_fds`. Conversion/full decoding also
  succeeds under that restriction and matches the unencrypted reference PCM.
- This establishes a transport defect, not the specific CachyOS root cause.
  Parent dumpability and actual tool behavior on that rig still need collection.
- A separate parser defect was found: optional FFprobe bitrate fields containing
  `N/A` raised ValueError inside otherwise successful inspection. Valid fallback
  fields now handle unavailable bitrate/duration without bypassing required
  sample-rate/channel/duration validation.

### Changes and verification

- All private key, IV, concat and ffmetadata descriptors are now explicitly
  inherited, remain CLOEXEC for unrelated execs, and close after their operation.
- Media errors identify operation, exit status, classified cause, redacted
  recognized stderr lines and safe numeric property summaries. Full FFprobe
  stdout, media tags, source paths, authentication data and keys are not logged.
- `verify-protected.py --diagnose-only --report FILE` collects actual executable
  versions/paths, FD-access/option-loading checks, receipt fingerprint matching,
  keyring/voucher shape checks, source inspection and a short decode-to-null.
  It creates no M4B and does not request authentication, licenses or downloads.
- Added regressions for restricted-parent FFprobe/conversion, legacy failure
  evidence, explicit-only FD inheritance/cleanup, unavailable numeric metadata,
  redacted errors/logs/reports and the non-converting diagnostic CLI.
- Final suite: **70 passed, 0 failed, 0 skipped**, in 33.67 seconds. There were
  223 existing upstream PyGObject compatibility/deprecation warnings.
  Ruff and `git diff --check` passed. Existing authentication/download tests pass;
  no login interface or download-to-conversion automation was added.
- **Still required:** the redacted JSON report from the actual CachyOS file and
  keyring session. A passing synthetic or mocked test does not verify this
  purchased audiobook, prove its stored voucher is correct, or establish complete
  real-world playback. Updated investigation/collection steps are in
  docs/audible-integration.md.

## Migration to the main CachyOS computer

The owner requested moving development to the computer that already holds the
real audiobook, account state and desktop keyring, ending the Evo/desktop split.

- `OPENCODE_HANDOFF.md` contains a self-contained continuation prompt: product
  scope, current architecture, exact user reports, AAXC investigation/evidence,
  secure transport, tests, Git state, licensing and a prioritized completion plan.
- `MIGRATION.md` explains transfer, checksum verification, clean extraction next
  to a preserved old copy, fresh CachyOS dependencies/venv, state preservation,
  first local diagnostics and desktop installation.
- `tools/package-migration.py` packages current files **and the local `.git`
  history**, preserving the intentional uncommitted/untracked AAXC work. It
  excludes Evo's runtime packages, virtual environment, builds, caches, media and
  account state. It verifies archive hashes/modes, a restored Git HEAD/status,
  and `git fsck --full`, then writes a checksum sidecar.
- `MIGRATION_MANIFEST.json` is included inside the archive as an ignored generated
  inventory. The destination should expect a dirty working tree, not reset it.
- The latest recorded application test result remains **70 passed on Evo**.
  The app was not behaviorally changed for migration, and that prior result is
  not a claim that the suite or purchased-book conversion passed on CachyOS.
- First development action after migration: run the current diagnostic revision
  against the real local AAXC in its owning desktop bus/keyring session, establish
  the actual failing stage, fix it with evidence, then verify complete conversion
  and playback before resuming the broader remaining roadmap.

## 2026-11-02 — native CachyOS continuation

- Verified the arrival folder against the nested migration archive and checksum;
  Git integrity passed. The outer ZIP is an older committed snapshot. Preserved
  all intentional dirty/untracked work and copied Evo runtimes under ignored
  `dist/evo-runtime-backup/`; created a native `.venv` with the pinned dependencies.
- Both actual downloads matched receipts and resolved existing keyring licenses.
  Native FFmpeg/FFprobe 9.0.2 inspected them and decoded their initial audio.
- Complete M4B conversions passed: 30,019.69 s / 48 chapters and 72,980.89 s /
  138 chapters. Full output decoding, chapters/titles/times, covers and source
  SHA-256 checks passed. The smaller book also passed protected-source MP3
  conversion with complete decoding and retained summary/publisher/cover.
- Both native conversion handlers passed on the real smaller book under Wayland.
  Added `tools/verify-native.py` for repeatable handler verification. Owner listening
  and player navigation remain pending; no automatic download/conversion added.
- Live library retrieval using the saved session passed with a read-only store;
  no stored account data or media licenses were modified.
- Implemented strong-ETag/Range-validated resume within retry operations, with
  restart on unsupported/invalid ranges and cleanup after cancellation/failure.
  Added regressions for resumed bytes, changed objects, weak/missing validators,
  invalid range fields, HTTP 416 and exhausted retries.
- Implemented audiobook multipart expansion through the upstream child-library
  query, preserving individual part rights and safely handling empty/repeated
  results. Covered with fixtures; live multipart/CDN-resume checks remain pending.
- Fixed actual Audible summary/publisher tag mapping, long-description writes,
  paragraph-preserving native summary editing, unsupported Adwaita row parents
  and the Metadata-page import shortcut. Expired-session guidance retains licenses.
- Final `./tools/check-local`: **88 passed, 0 failed, 0 skipped**, 27.74 s;
  35 upstream PyGObject deprecation warnings. Ruff and whitespace checks passed.
- Wheel/sdist built on CachyOS. Meson installation staged completely inside
  `dist/install`; both installed-wheel and Meson-installed native Wayland startup
  passed. Desktop validation passed; AppStream validation passed with the existing
  single pedantic application-ID note. Mesa emitted its driver conformance warning
  during native startup, without application failure.
- Full details, repeatable commands and remaining manual checks are in
  `docs/cachyos-validation.md`. No commit, remote publication or global installation.

## Follow-up — restore working whole-book downloads

- Owner reports successful AAXC-to-M4B conversion and playback, but multiple
  downloads fail after successful login/library refresh.
- Reproduced the regression: the new library expansion replaced original
  MultiPartBook entries with AudioPart children. Two child license requests failed
  with HTTP 404; the original parent's license and full transfer succeeded.
- Restored original whole-book entries/rights and removed the parent-download
  prohibition. The transfer-resume implementation was not the cause of this
  reproduced failure. Added actionable HTTP 404 license errors and safe per-item
  queue logging, preserving the actual failure stack before aggregation.
- Real corrected native queue download passed, followed by Convert Last Download
  and explicit M4B conversion: 72,980.89 seconds, 138 chapters, full audio decode.
  Diagnostic licenses remained in memory; new test media/receipts stayed in `dist/`.
  Existing account/keyring licenses, receipts and original books were preserved.
- Expanded the encrypted end-to-end regression to cover original multipart library
  entries, and checked queue continuation, selection retention and log privacy.
- `./tools/check-local`: **90 passed, 0 failed, 0 skipped**, 28.71 s, with 448
  upstream PyGObject deprecation warnings. Ruff and whitespace checks passed.
- The earlier multipart-expansion completion claim above is superseded. Listing
  child offline rights and passing fixtures did not prove usable live licenses.
  Restart and refresh are needed to remove old in-memory part entries.

## Authentication and fixed-library-toolbar improvements

- Inspected `audible==0.13.1`'s actual external-login callback, URL builder, PKCE,
  initial cookies and Playwright helper. The existing supported return target is
  an Amazon/Audible HTTPS maplanding URL; no configurable localhost redirect is
  exposed. Kept the working registration, session storage and US marketplace.
- Added `login_flow.py` and `login_window.py`: a dedicated ephemeral WebKitGTK 6
  login window, automatic expected-destination callback capture, no password/DOM
  field-value inspection, no clipboard/manual URL step, secure registration,
  completion state, cancellation/timeout and useful fixed errors. Failed/canceled
  reauthentication retains existing authentication/media licenses.
- Moved the Audible account/search/action header outside its only scroller. Only
  audiobook rows scroll. Native breakpoints adapt account/selection groups to
  compact widths; selection-dependent buttons and the last-download conversion
  action reflect current selection/operation state. Whole-book IDs, queue/retry
  behavior, saved paths and explicit conversion are preserved.
- Real WebKit tests automatically intercepted synthetic navigation callbacks and
  covered success, cancellation, callback denial, registration/network failure
  and missing WebKit. Pure tests cover callback validation, timeout, late cancel
  and safe errors. Native layout tests measured stationary toolbar/progress
  coordinates while scrolling 150 rows and a usable 400×780 layout.
- A live public Amazon sign-in page loaded with email/password fields present and
  no unsupported-browser message. Only boolean DOM-presence checks left the
  renderer; no credentials were entered. **Full fresh account login/MFA through
  the new window remains an owner test**, not a claimed live-authentication pass.
- A real saved-session native-toolbar download passed, followed by Convert Last
  Download and explicit M4B conversion/full decoding: 72,980.89 seconds and all
  138 chapters. Test state stayed under `dist/`; licenses stayed in memory.
- `GDK_BACKEND=x11 ./tools/check-local`: **111 passed, 0 failed, 0 skipped**,
  29.89 seconds, 1,478 upstream PyGObject asyncio-policy deprecation warnings.
  Ruff and whitespace checks passed; no GTK warning/exception failures remained.
  Background Wayland test surfaces had zero allocations in this session, so
  actual geometry/page-render verification used GNOME/Xwayland. Interactive
  Wayland layout and the owner's verification/security steps remain manual.
- Native dependency is system `webkitgtk-6.0` (already installed here), including
  libsoup 3. No new pip dependency or downloaded browser runtime. Updated README,
  architecture, integration/development notes and third-party notices.

## Follow-up — automatic login confirmed; AAX quality-format fix

- Owner confirms that the new automatic login works and the library buttons have
  moved as requested, but another download attempt failed. The safe per-item log
  identified the adapter's format/URL validation at `download_book`, rather than
  authentication or network transfer.
- Reused the newly saved desktop session without another login. The previously
  working title downloaded and fully converted. A different original whole-book
  entry returned a granted license, valid URL/voucher and `AAX_22_64` format. The
  adapter's hardcoded format list omitted that legitimate quality variant.
- Accepted bounded numeric AAX sample-rate/bitrate variants through the existing
  protected download path. Kept voucher validation, container/transfer checks,
  unknown-DRM rejection and explicit conversion. Missing download URLs now have
  a separate useful error instead of the format message.
- Real corrected native-toolbar download and Convert Last Download / explicit M4B
  conversion passed: **88,143.88 seconds, 50 chapters**, complete output decoding.
  Test credentials/licenses stayed in memory and media/receipts under `dist/`;
  existing account state and original downloads were preserved.
- Extended encrypted library → license → download → receipt → restart/rename →
  conversion regressions for both AAX_44_128 and AAX_22_64 and both single/multipart
  entries. Unsupported formats and absent URLs are rejected before saving licenses
  or starting a transfer.
- `GDK_BACKEND=x11 ./tools/check-local`: **117 passed, 0 failed, 0 skipped**,
  31.46 seconds; 1,519 upstream PyGObject deprecation warnings. Ruff and whitespace
  checks passed. No additional interactive login was needed for diagnosis/testing.

## Title-only download filenames

- Removed the automatically appended `[ASIN]` from new Audible download filenames.
  ASIN remains the internal library/receipt/license identifier. New MP3/AAXC files
  use sanitized book titles and existing collision numbering; conversion inherits
  the cleaner source filename. Existing files are not renamed.
- Extended existing encrypted download/restart/rename/conversion checks to assert
  the title-only name and resolve its license from persisted receipts before and
  after renaming. Legacy bracketed filename lookup remains supported.
- Targeted download/license/legacy compatibility checks: **7 passed** in 4.05 s.
  Ruff and whitespace checks passed.

## Self-contained AppImage

- Added `tools/build-appimage.py` plus a static C launcher, packaged entrypoint
  and media/browser self-test under `tools/appimage/`. The builder uses a
  checksum-pinned local build tool and writes all work/caches/artifacts in `dist/`.
- Bundles CPython, 23 Python runtime distributions, GTK/Adwaita, WebKit/helper
  processes, FFmpeg/FFprobe, matching glibc/loader and complete ELF/GI dependency
  closure. Native provenance covers 290 package owners. Includes browser/image/
  GStreamer modules, schemas, certificates, locales, fonts/aliases, keyboard/cursor
  data, software rendering, public application source and dependency notices.
- Uses bundled Bubblewrap to expose read-only private `/usr` and `/etc` paths so
  hardcoded helper paths cannot pick up the host's Python/GTK/WebKit/FFmpeg.
  WebKit's inner sandbox remains enabled. Desktop display, D-Bus/keyring and user
  directories retain normal access; host file dialogs/folder opening use portals.
- Fixed missing runtime assets found by isolated tests: transitive GI typelibs,
  system schema enums, p11-kit trust module/data, generated locale archive, actual
  enabled Fontconfig alias rules and Wayland keyboard definitions. These were
  packaging fixes; working account/download/conversion source paths were retained.
- Final artifact: `dist/Audiobook_Utility-0.1.0-x86_64.AppImage`, **309,842,232 bytes
  (295.49 MiB)**. SHA-256:
  `fa28ad2603e3d30c92c268b2f1ceef226b8ef6a34187d96944c392e490b76acf`.
  Matching `.sha256` sidecar verified successfully.
- Final AppImage passed media conversion/merge/tagging/chapters/cover/full-decode,
  native GTK/Adwaita, WebKit automatic callback and real public Amazon sign-in-form
  loading under both GNOME/Wayland and Xwayland. The renamed/moved image also
  passed using FUSE-free extraction and an empty host PATH from another directory.
  Import assertions confirmed bundled `/usr` modules. No broken/external symlinks
  or personal audio/voucher files were present in the AppDir.
- The final executable reused the desktop keyring session for a live library
  refresh. A packaged candidate with identical application code also passed a
  real AAXC download and full M4B conversion: 30,019.69 s / 48 chapters, plus host
  output-folder portal opening. The final runtime then added keyboard/cursor/X11
  locale data. Exact per-artifact evidence is in `dist/AppImage-VALIDATION.json`.
- Source regression suite: **117 passed, 0 failed, 0 skipped**, 31.45 s; 419
  upstream PyGObject deprecation warnings. Ruff, whitespace and C launcher
  `-Wall -Wextra` syntax checks passed. Fresh interactive packaged login/MFA and
  other-distribution/CPU testing remain manual; public page loading is not login.
- See `docs/appimage.md` for build/run/self-test instructions and OS-service
  requirements. No system installation, publication or commit was performed.

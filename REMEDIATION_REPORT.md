# Code review remediation

## Scope and safeguards

- Review: `CODE_REVIEW.md`, 2026-11-04, revision `659d59c4fdfc34e02d0379ae25c1e708101622e9`.
- Local branch: `remediation/code-review-2026-11-04`; no merge or publication authorized.
- The original untracked review was preserved byte-for-byte (SHA-256
  `19e7db9cf91c1d78b7d9b5849f28a1b0e910a07c0769add9df7baea7bda866bd`).
- No actual credentials, media licenses, audiobooks, conversion outputs or installed
  application data are used for remediation tests. No live Audible operations.
- Existing AppImage remains unchanged (SHA-256
  `83553972578ed8debf0e445043fb7a1cd44d059f43e87e3850bea56ecb9f0791`).
  No distributable AppImage rebuild or system-package installation is authorized.

## Phase 0 — baseline

Verified branch/revision, clean tracked working tree, structure and all findings in
the complete review. The findings still apply to the reviewed source. Conditional
portability/trust-store observations remain conditions to test, not demonstrated
failures on other distributions. Tests and lint ran using new isolated state in
`dist/remediation/baseline/`, preserving previous test outputs.

- Existing suite: **117 passed**, 31.43 s, 1,702 upstream PyGObject deprecation warnings.
- Ruff: passed. No source modifications before this baseline.

## Phase results

Implementation and per-finding evidence will be recorded below as each phase passes.

| Findings | Status |
| --- | --- |
| H01–H04 | Fixed and Phase 1 validated (details below) |
| M01–M14 | Implemented/mitigated; Phase 2 validation below; external portability tests deferred |
| L01–L06 | Fixed and Phase 3 validated (details below) |

No fixes are represented as complete until their regression checks and phase gate pass.

## Phase 1 — high-severity findings

- **H01 (reproduced):** ISO-BMFF Audible brands now take precedence over filename
  suffixes; renamed protected inputs resolve the existing receipt/license path.
  Conversion rejects protected inputs without options and fully decodes every
  converted output before atomic publication. Private memfd/pass_fds transport is
  retained. Tests cover misleading `.m4b/.m4a/.mp3/.bin/.aax` and absent licenses.
- **H02 (reproduced):** Added non-secret, durable started/ready journals with
  per-transaction activity locks. The ready fingerprint/license reference is saved
  before file publication. Receipt-commit failures retain a resolvable journal;
  idempotent recovery commits completed files or deletes only this transaction's
  owned orphan key, never user files or earlier license items. Late cancellation
  after publication preserves the completed operation. Fault tests cover journal
  ENOSPC, receipt ENOSPC, canceled transfer, interrupted ready/started states,
  repeated recovery and active-transaction exclusion.
- **H03 (confirmed):** Introduced explicit `PACKAGING_FILES.txt` plus shared
  `package_sources.py` policy for runtime modules, embedded source and setuptools
  sdist/build_py hooks. Git-backed builds require approved tracked files; archive
  builds retain the same manifest. Escaping symlinks and private file types fail.
  Synthetic packaging tests exclude ignored/untracked sentinels; no actual release
  or AppImage was built.
- **H04 (confirmed):** Normal sign-out deletes only auth; explicit media forgetting
  preserves the session, requires a native destructive confirmation, and explains
  loss of conversion capability. Fake-collection and native cancel/confirm tests
  verify media/other-application preservation.
- Shared transaction prerequisites also address **M05** (strict validation,
  corruption rejection, last-valid backup and sidecar-locked updates) and **L01**
  (parent-directory fsync). Additional dedicated checks follow in their phases.
- Changed application files: `media.py`, `files.py`, `receipts.py`,
  `audible_service.py`, `download.py`, `credentials.py`, `ui.py`; packaging policy,
  setuptools hooks, builder, public manifest and high-severity regression tests.
- New regression cases initially failed against the baseline; targeted set now
  **21 passed**. Final Phase 1 gate: **138 passed**, 41.33 s; Ruff/whitespace passed.
- One initial gate aborted inside WebKit when the test runtime socket path was too
  long. Short, private runtime directories under Projects resolved that test
  environment failure; the complete login tests and full gate then passed. No
  WebKit security setting or production login protocol was weakened.

## Phase 2 — medium-severity findings

| Finding | Confirmation and implemented correction | Principal files / regression evidence |
| --- | --- | --- |
| M01 | Reproduced downgrade. Each HTTPS hop is checked before connection; bounded manual redirects and cross-host auth stripping. Read/connection and total-operation bounds retain TLS verification. | `network.py`, `download.py`, `thumbnails.py`; downgrade, redirect-limit/header and slow-trickle tests |
| M02 | Reproduced late ADTS failure. Unsupported source tag containers use best-effort transfer instead of aborting valid audio merging. | `media.py`; ADTS-first real FFmpeg merge |
| M03 | Reproduced restored cover. Separate `INHERIT_ARTWORK` sentinel from explicit `None` removal. Original artwork bytes stay intact. | `media.py`; keep/remove output checks |
| M04 | Confirmed native markup default. All external row titles/subtitles now use literal text. | `ui.py`; ampersand/markup native test |
| M05 | Addressed as H02 prerequisite; dedicated corruption and eight-writer tests now verify fail-closed load, backups and serialized updates. | `receipts.py`; corruption and concurrent-update tests |
| M06 | Reproduced ENOSPC masking. Only known transport/API exceptions get connection messages; original causes retain safe type evidence. API auth persistence completes before CDN/local publication. | `audible_service.py`; local ENOSPC and auth-resave-before-transfer tests |
| M07 | Confirmed unbounded idle queue. `ProgressDispatch` keeps one pending callback and latest state; close/operation IDs reject stale updates. | `progress.py`, `ui.py`; 10,000-event bounded-delivery test |
| M08 | Confirmed main-thread decode/eager rows. Pillow previews are prepared in workers; original bytes are separate. Library uses recycled native ListView rows with small preview textures. Preview completion uses weak references/generation guards and owned cleanup. | `metadata.py`, `ui.py`, `thumbnails.py`; 5,000-book widget bound and off-main/stale-preview tests |
| M09 | Reproduced malformed URL failure. Cover errors are best-effort; stream cancellation, small read units and a 15-second total deadline stop trickles and close responses. | `thumbnails.py`, `network.py`; malformed/no-network, active cancel and deadline tests |
| M10 | Reproduced accepted relative tilde path. Preferences normalize expanded absolute paths; merge normalizes at its filesystem boundary too. | `settings.py`, `media.py`; path normalization test |
| M11 | Reproduced null contributor/runtime errors. Invalid essential IDs are skipped with a count; nonessential fields normalize safely. Rights are true/false/unknown with distinct text; unknown is never assumed entitled. | `audible_service.py`, `ui.py`; mixed-page/schema/unknown-rights tests |
| M12 | Confirmed discarded lock versions. Version checks, editable/pth rejection, wheel RECORD/native mtree integrity and file-hash provenance are now explicit. PATH overrides cannot substitute media binaries. | `tools/build-appimage.py`; fake version/editable tests and read-only validation of existing installed dependencies (no copies/builds) |
| M13 | Confirmed private trust-store mismatch. Runtime-only override/additional CA support validates inputs and preserves TLS; temporary PEM cleanup restores the environment. | `AppRun.c`, `appimage_trust.py`, entry/builder; synthetic CA and malformed-certificate tests |
| M14 | Confirmed documented baseline limitation. Static launcher diagnostics and a no-build/no-install portability evidence runner are added. No insecure fallback or support claim for untested platforms. | `AppRun.c`, `tools/check-portability.py`, `docs/portability.md`; compiled diagnostic fixture and supplied-image runner fixture |

The original application architecture, automatic backend callback, US marketplace,
whole-book ASINs, secure key transport, output naming and separate explicit
download/conversion operations are retained. No real account activity was used.
Cross-distribution VM tests and actual integration of launcher/CA changes in an
AppImage are **deferred until an owner-authorized candidate build/environment**;
no distributable AppImage was rebuilt. This is an untested compatibility boundary,
not a remaining failed source regression.

Phase 2 targeted regressions: **24 passed** (the M05 corruption/concurrency checks
were already green from the transaction prerequisites). Final full gate:
**162 passed**, 47.88 s; Ruff and whitespace passed. The original review and
distributable AppImage checksums remain identical to baseline. **L06** launcher
allocation/path/errno checks were implemented alongside M13/M14 to avoid adding
new unchecked startup paths; its fault-injection tests follow in Phase 3.

## Phase 3 — low-severity findings

- **L01:** Dedicated fault injection verifies file-before-directory fsync ordering
  and reports a directory-sync failure without deleting the already committed file.
- **L02:** Corrupt/oversized cache entries are removed and refetched; owned regular
  hash-named entries expire after 30 days and are evicted oldest-access-first above
  64 MiB/1,000 entries. Foreign files and symlink targets are preserved.
- **L03:** Metadata forms compare text and original artwork against the last loaded
  or saved state. Opening/restoring another file or closing prompts Save/Discard/
  Cancel. Failed saves retain dirty state and do not continue the pending action.
- **L04:** Migration path/member/hash/mode/Git checks, AppImage self-tests and Meson
  version checks use explicit failures, including under optimized Python. The
  migration root allowlist includes the reviewed packaging/remediation files.
- **L05:** Screenshot tooling is import-safe, uses project-local synthetic media,
  and renders only the allocated application widget through GTK. Missing render
  nodes fail explicitly. No whole-desktop capture fallback exists.
- **L06:** A compiled synthetic launcher with failed `strdup` verifies a useful
  allocation diagnostic; bounds/errno checks were implemented during Phase 2.

The initial low-severity run reproduced six failures (four prerequisites were
already green). Expanded targeted checks: **12 passed**, including a real native
application-only PNG render. Full Phase 3 suite: **174 passed**, 48.66 s;
Ruff passed. Synthetic archives/binaries only; no release rebuild or account use.

## Phase 4 — GNOME lifecycle and ownership

- Each Secret Service operation now explicitly owns and closes its D-Bus
  connection, including acquisition and item failures. Fifteen fake-service cases
  cover get/put/delete/account clearing/media clearing; no real keyring was opened.
  This improves ownership; the review did not establish a preexisting FD leak.
- A window-scoped `Gio.SimpleAction` routes Open to the current local workflow.
  Ctrl+O on Audible no longer imports into the hidden conversion page.
- Login's capture-phase Escape handler uses the existing cancellation/cleanup
  path. Automatic ephemeral login and its backend remain unchanged.
- Destroyed windows reject newly requested work and late chooser results. Terminal
  worker status is announced on GTK versions supporting accessible announcements;
  the GTK 4.10 baseline remains supported without that optional API.
- Targeted lifecycle/workflow/login/protected-media/high-severity checks:
  **77 passed**. Full phase gate: **191 passed**, 48.78 s; Ruff/whitespace passed.

These focused changes preserve native layout and appearance. Full gettext/catalog
adoption, actual screen-reader/keyboard-only acceptance, fractional scaling and a
long-running measured heap/FD soak remain follow-up work, not claimed results.

# Audiobook Utility — continuation prompt

> **Updated on CachyOS, 2026-11-02:** read `docs/cachyos-validation.md` and the
> latest `docs/progress.md` entry first. Actual purchased AAXC-to-M4B/MP3 conversion,
> full decoding and both native conversion handlers now pass. The remaining text
> records the migration-era situation and must not override newer evidence.

You are taking over an existing software project on the owner's main CachyOS
GNOME computer. Continue implementing and testing this application in this
directory. Do not recreate it, replace it with a demonstration, or start a new
repository. Work autonomously wherever possible and ask for human interaction
only when necessary, such as unlocking the desktop keyring or completing MFA.

Read this file completely, then `MIGRATION.md`, `docs/progress.md`,
`docs/audible-integration.md`, `docs/architecture.md`, and `docs/development.md`.
Inspect the actual code and Git diff before making changes. The progress document
is chronological: its earlier acceptance table and smaller test counts describe
older snapshots, not the latest state summarized here.

## 1. The user's objective and current direction

Build a genuinely useful, fully free and open-source Linux audiobook utility
with a native GNOME GTK4/Libadwaita interface. Working name: **Audiobook Utility**.
The four workflows are:

1. Connect an Audible.com US account, browse eligible purchases, and download them.
2. Convert downloaded or local audio to M4B/AAC or MP3.
3. Merge chapter files into a single audiobook, with useful M4B chapters.
4. Edit audiobook metadata and embedded cover artwork.

This is a utility, not a player, server or elaborate library manager. Local
functions must remain useful without an Audible account. Downloads and conversion
are separate, explicit operations. Keep output folders simple and flat, with
readable filenames rather than automatic author/series hierarchies.

**Immediate priority:** determine and fix the actual failure converting the
owner's already downloaded AAXC on CachyOS. Preserve working authentication,
library retrieval and downloading. The user's latest instruction is explicit:
**do not introduce automatic M4B conversion or redesign login yet. First make
existing AAXC conversion reliable.** Once that is verified, continue completing
the broader project and acceptance criteria below.

## 2. Why the project moved

Development previously ran on a separate machine called Evo, reached by SSH.
Despite the original target being CachyOS, the execution environment on Evo was
headless Ubuntu. It lacked native GTK4/Libadwaita and FFmpeg packages. For tests,
Ubuntu packages were extracted into an ignored project-local `.deps/` directory,
and a Python `.venv/` used system PyGObject. No system packages were installed.

The owner copied code to the main CachyOS rig and tested it there. This split
caused repeated confusion about installed versions, actual files, credentials and
what had been verified. The owner now wants development and real testing on the
same CachyOS machine. **Treat CachyOS as the source of truth from now on.**

The migration archive excludes Evo's `.deps/`, `.venv/`, `build/`, `dist/`, caches
and generated Python metadata. Rebuild those locally. In particular, do not
merge an old copied `.deps/` into this checkout: `tools/run-local` will prepend
that directory's executables/libraries whenever it exists, potentially selecting
Ubuntu runtimes instead of CachyOS's actual FFmpeg/FFprobe.

## 3. Git state — important

The complete local `.git` history and current working files are included.
Repository branch at handoff: `master`. There is no configured remote and no
GitHub publication. The last committed HEAD is:

```text
1aa768b feat: refine native workflows and add packaging and release documentation
d2060ef feat: implement local audio workflows and isolated Audible adapter
bff4ec1 feat: establish native GNOME application and media foundation
```

**The latest AAXC fixes, new diagnostic modules, regression tests and updated
documentation are uncommitted, including untracked source files.** They are
intentional development work, not disposable artifacts. The migration preserves
this dirty state; do not reset, clean, restore or overwrite it. `git archive HEAD`
alone would lose these fixes and must not be used as the working snapshot.

`MIGRATION_MANIFEST.json` in the extracted project records the exact HEAD,
porcelain status, file hashes and modes at packaging. It is an ignored generated
inventory, not an application preference or credential file. Inspect `git status
--short --untracked-files=all` and `git diff` on arrival and compare the inventory.

Follow the destination machine's applicable AGENTS.md and harness instructions.
Do not publish, create a GitHub repository or push without the owner's explicit
authorization and any required confirmation. The owner's GitHub account is
`edjenn1998`. Do not change global Git or system configuration to get tests past
a failure. The original project request calls for logical development commits;
follow current user/harness authorization before committing. No migration commit
was created just to make the archive look clean.

## 4. What is implemented

- Native Adwaita application with Audible, Convert, Merge and Metadata views.
- Responsive compact navigation/action layouts, standard dialogs, system
  appearance/accent behavior, accessible labels, keyboard shortcuts and drops.
- Native file/folder import; FFprobe properties; actual MP3/M4B conversion.
- Compatible single-input AAC-to-M4B stream copy.
- Natural numeric ordering, manual track reorder/removal, editable chapter titles,
  mixed-format merging and sample-count-based chapter positions.
- MP3/MP4 metadata mapping, JPEG/PNG artwork validation/preview/add/replace/remove,
  unknown-tag preservation and transactional saves with advisory edit locking.
- Background workers, progress, cancellation, output verification, no-clobber
  atomic publication and preservation of originals.
- Focused persisted preferences, separate download/output/temp paths and flat
  output names with rename-or-fail collision behavior.
- Audible external-browser sign-in, Secret Service session persistence,
  paginated library parsing, selection/search, serial download queue, retries,
  cancellation cleanup, original-format downloads and verified local receipts.
- Desktop entry, SVG icon, AppStream metadata, Meson installation, Python
  packaging, dependency notices, architecture/development docs and screenshot.

These are actual implementations, but the project is **not complete**. See the
distinction between automated coverage, owner reports and unverified work below.

## 5. What the owner has actually reported

On the main CachyOS rig:

- Audible.com authentication succeeds.
- Purchased-library retrieval succeeds.
- An AAXC audiobook downloads successfully.
- Both **Convert Imported Files** and **Convert Last Download** fail.
- The first failure said `Cannot inspect audio. The file may be corrupt,
  unsupported or protected.` Imported protected files initially showed only
  `Protected Audible input; account license required.` and 0% progress.
- After an update, `tools/verify-protected.py` still failed with:
  `Cannot inspect protected audio with the saved Audible license. The license
  may not match this file, or FFprobe may not support secure option loading.`
- The owner independently confirmed BOTH FFmpeg and FFprobe recognize normal
  `audible_key` and `audible_iv` options.

The most recent inherited-descriptor/diagnostic revision was packaged on Evo,
but **no actual CachyOS diagnostic JSON or successful real-book conversion has
been returned**. Do not assume that this latest revision was tested on the rig.

Evo had no purchased AAXC, application receipt/configuration, or accessible
Secret Service account data. Do not look for the owner's real audiobook on Evo
or ask them to export keys. The main rig already holds the relevant file and
keyring. The exact book path has not been recorded here; find it locally from
preferences/receipts or ask the owner if necessary without dumping private data.

## 6. AAXC investigation: evidence and fixes already in this tree

### Original problems

The conversion worker already called `input_options` and forwarded its result
to `probe`. It was not simply omitting keys unconditionally. However:

- Protected import skipped actual probing and displayed a generic label.
- License lookup ignored receipts and matched the first bracketed filename
  component, which could be title text rather than the trailing ASIN.
- One mutable `media:ASIN` voucher was reused per title, so later downloads could
  replace a license needed for an earlier file.
- The first private-option helper used `-/audible_key` for both tools. Real
  FFmpeg 8.0.1 rejected that syntax even though FFprobe accepted it and both
  exposed normal MOV demuxer Audible options.
- A catch-all exception replaced different process/JSON/property failures with
  the same vague protected-inspection message.

### Current receipt/voucher handling

`AudibleService.download_book` uses the upstream audible library to decrypt the
granted license response's voucher. Key/IV values must each be 32 hex characters
(16 bytes). New protected downloads save a distinct Secret Service item:

```text
media:<ASIN>:<random-reference>
```

The non-sensitive receipt points at that item and records file size/SHA-256.
History retains earlier files/licenses. `Receipts.association` matches actual
bytes, allowing moved/renamed imports after restart. Older receipts fall back
to existing `media:<ASIN>` keyring entries. A trailing `[ASIN]` filename is a
compatibility fallback only when no fingerprint association exists. New
downloads leave legacy items intact rather than overwriting them. Unprotected
MPEG downloads do not require an AAXC voucher.

Existing legacy data might already have lost a correct voucher through the old
overwrite behavior. The code cannot reconstruct an overwritten key from its
filename. Investigate the actual report before concluding that happened or
requesting a fresh authorized download. **Valid hex and a matching receipt do
not prove cryptographic agreement with the audio.**

### Current secure process transport

- FFprobe uses its file-valued options `-/audible_key` and `-/audible_iv`.
- FFmpeg uses one-file concat input with per-file `option audible_key` and
  `option audible_iv` directives, avoiding unsupported FFmpeg AVOption slash
  syntax. The script lives only in an anonymous Linux memfd.
- Because concat loses child global tags/chapters, source probe metadata is
  supplied in a separate ffmetadata memfd. `-copyts` preserves negative AAC
  priming timestamps. Covers are written with Mutagen rather than duplicated as
  video streams. Compatible AAC remains stream-copied.
- **Latest fix:** all such files use `/proc/self/fd/N` from the child's point of
  view, with explicit Python `pass_fds`. `PrivatePath` retains the descriptors
  needed by the launch. Parent descriptors remain CLOEXEC; unrelated children
  do not inherit them. Contexts keep them alive until processing completes.
- The previous `/proc/<parent-pid>/fd/N` route depended on cross-process access
  permissions. No global security-policy relaxation is needed or acceptable.
- `FFREPORT` is removed from media-child environments to prevent inherited debug
  logging from writing secrets. Keys never enter process argv or disk config.

### Concrete reproduced descriptor defect

Using real FFprobe and genuinely encrypted synthetic AAC on Evo, a disposable
parent was marked non-dumpable with `prctl(PR_SET_DUMPABLE, 0)`. Under the old
parent-PID route, FFprobe returned exit 1 and `Error opening file` / `Error reading
the value for option audible_key`. Its loader omitted the OS errno. A separate
child-read check returned EACCES (13, permission denied). Under the identical
restriction, the same file/license works with inherited child-local descriptors,
including complete conversion/decode and PCM equality against the reference.

This proves a defect in the old transport. **It does not prove the owner's
CachyOS process has that condition.** Confirm the actual failure locally rather
than treating a controlled reproduction as a real-book success.

### Other diagnostic/parser improvements

- `MediaFailure` preserves operation, exit status, classified cause, bounded
  redacted recognized stderr and safe numeric-property evidence.
- Errors distinguish tool startup, option syntax, private-file access, JSON
  parsing, unusable required audio properties, conversion and output decoding.
- Optional `N/A` bitrate/duration fields use valid fallback values. Missing or
  unusable required sample rate/channels/duration still fails inspection.
- Protected results must pass duration/chapter checks and a full FFmpeg decode
  to a null sink with `-xerror` before atomic publication. This matters because
  stream-copy completion alone does not demonstrate playable decrypted audio.

## 7. Your first development session on CachyOS

1. Confirm this is the migrated working tree and inspect Git status/diff. Keep
   the uncommitted and untracked fixes. Follow `MIGRATION.md` for a fresh venv.
2. Confirm native CachyOS tools are selected, not copied `.deps` binaries. Run
   the development wrapper rather than an old installed desktop launcher.
3. Use the same normal user and desktop Secret Service session as the working
   application. Do not run the account diagnostic under root or an isolated
   `dbus-run-session`; that would lose access to the existing desktop keyring.
4. Locate the existing AAXC and collect this read-only report:

```sh
./tools/run-local .venv/bin/python tools/verify-protected.py "/absolute/path/Book.aaxc" --diagnose-only --report aaxc-diagnostics.json
```

The command creates no M4B and makes no login, license or download request. It
generates a tiny temporary public test tone for transport/parser checks, reads
receipts/keyring, inspects the actual source and attempts at most three seconds
of decode-to-null if inspection succeeds. It does not change application state.
The new report is mode 0600 and existing report files are not overwritten.

Look for `diagnostic_revision: 2` and
`private_transport: pass_fds:/proc/self/fd`. Exit zero means report collection
completed, not that all checks or full-book playback succeeded.

Analyze these fields, in order:

- Actual executable paths/versions and `project_bundle` flags.
- `descriptors`: parent dumpability/ptrace scope, legacy-parent read versus
  inherited-child read, and any errno.
- `option_transport_tests`: actual FFprobe/FFmpeg parser and private-file loading.
- `source`: container brand/size, without book names or private paths.
- `license_resolution`: receipt readability, size/SHA-256 match, association mode,
  per-download versus legacy scope, reference/ASIN consistency, keyring result,
  and key/IV format validation. ASIN values and key material are not in the report.
- `protected_inspection`: failing stage, exit status, sanitized stderr and safe
  numeric fields. Do not discard a real tool error in favor of a guess.
- `protected_sample_decode`: whether the actual file decodes with the selected
  license for the initial three seconds. This is not complete verification.

5. Fix the demonstrated real failure, adding a focused regression. Preserve the
   working account/download paths. Do not bypass probing or declare success
   merely because mocked/synthetic tests pass. Keep secrets out of logs, argv,
   docs, fixtures and Git; do not print raw vouchers or raw FFprobe JSON.
6. Once actual inspection works, perform an explicit conversion:

```sh
./tools/run-local .venv/bin/python tools/verify-protected.py "/absolute/path/Book.aaxc" --output "/chosen/output/Book-verified.m4b"
```

Choose a new output path. The tool checks complete decoding, chapter retention,
populated metadata and unchanged source bytes. Then inspect/play the output in
the owner's usual player, including beginning/middle/end and chapter navigation.
Record actual evidence and any limits; a decoder pass is not a listening test.
7. Test both GUI actions using the same book and update progress/documentation.
   Continue the broader roadmap only after this workflow is reliable.

Do not disconnect the account or delete receipts/keyring items as a routine
troubleshooting step: disconnect currently removes application media licenses
as well as authentication. Keep the provisional app ID unchanged so existing
credentials continue to resolve.

## 8. Architecture and navigation

Stack: Python >=3.12, GTK >=4.10, Libadwaita >=1.5, PyGObject, system FFmpeg and
FFprobe, Mutagen, Pillow, HTTPX, audible 0.13.1, SecretStorage. No SQLite is needed
for the current lightweight state. No Electron, embedded web UI or service daemon.

| File | Responsibility |
| --- | --- |
| `src/audiobook_utility/ui.py` | Native pages/dialogs, imports, background work and explicit actions |
| `media.py` | Probing, private FD transport, conversion, merge, chapters, cancellation, verification |
| `audible_service.py` | Browser sign-in adapter, library, licenses, download orchestration, input options |
| `credentials.py` | Secret Service only; no plaintext fallback |
| `receipts.py` | Download fingerprints/history and per-file license association |
| `download.py` | HTTPS streaming, retries, cancellation, length/type/container checks |
| `metadata.py` | MP3/MP4 tags, artwork, transactional saves and locking |
| `files.py` | Safe names, collision choices, same-directory staging/publication |
| `settings.py` | Validated persisted directory/audio preferences |
| `media_diagnostics.py` | Safe structured media failures/redaction |
| `protected_diagnostics.py` | On-device evidence collection without login or M4B output |
| `diagnostics.py` | Bounded redacted local diagnostic log |
| `thumbnails.py` | Bounded image retrieval/cache |
| `tools/verify-protected.py` | Diagnostic mode and explicit full conversion/check command |
| `tools/run-local` | Development launcher; optional Evo runtime override when `.deps` exists |
| `data/`, `meson.build` | Launcher, icon, AppStream and desktop/source installation |

One background operation runs per window. Worker results reach GTK through GLib;
do not access GTK from workers. Media subprocesses use argument arrays and
cancellation watchers. New outputs use verified staging and no-clobber hard-link
publication. Metadata uses a temporary copy, verification, change detection and
an advisory edit lock before atomic replacement. Originals are preserved.

State locations, subject to the normal XDG environment overrides:

```text
~/.config/audiobook-utility/settings.json
~/.local/share/audiobook-utility/downloads.json
~/.local/state/audiobook-utility/diagnostics.log
~/.cache/audiobook-utility/covers/
Secret Service attributes: application=io.github.edjenn1998.AudiobookUtility
```

Default output: `~/Audiobooks/`; downloads: `~/Audiobooks/Downloads/`. Actual
preferences on the rig may differ. Those files/books/keyring are already on
CachyOS and are not included in the migration archive.

## 9. Validation status

Last recorded complete run on Evo: **70 passed, 0 failed, 0 skipped**, 33.67 s,
with 223 upstream PyGObject compatibility/deprecation warnings. Ruff and
`git diff --check` passed. That environment used Python 3.14.4, GTK 4.22.4,
Libadwaita 1.9.1, PyGObject 3.56.2 and FFmpeg/FFprobe 8.0.1. Those results were
recorded before migration; repeat on CachyOS rather than treating them as local
success. No application audio behavior was changed just for packaging.

Tests generate public synthetic tones. Protected tests genuinely encrypt AAC
packets with per-packet AES-CBC/clear trailing bytes and generate an encrypted
voucher processed by the real upstream audible library. They compare complete
decoded PCM, chapters/tags/artwork, and run actual restricted-parent media tools.
Keyring/network behavior is fixture-backed where accounts are required. No
commercial audio, real tokens or real vouchers are part of the tests.

Useful commands, from this checkout after creating its venv:

```sh
xvfb-run -a ./tools/run-local .venv/bin/python -m pytest -q
./tools/run-local .venv/bin/python -m pytest tests/test_media_diagnostics.py -q
.venv/bin/ruff check src tests tools
git diff --check
.venv/bin/python -m build
desktop-file-validate data/io.github.edjenn1998.AudiobookUtility.desktop
appstreamcli validate --no-net data/io.github.edjenn1998.AudiobookUtility.metainfo.xml
```

The full suite includes native tests; use a display/Xvfb for those. Close a
running application with the same app ID before testing, or isolate only the
synthetic test suite in `dbus-run-session`. The real-account diagnostic must
instead retain the owning desktop bus/keyring. Some tests run approximately a
hundred tiny FFmpeg jobs; a short delay is expected. Do not suppress deprecation
warnings to imply they were fixed.

Earlier wheel/sdist builds, installed-wheel startup, staged Meson installation,
desktop entry and AppStream validation passed on Evo. AppStream had a pedantic
informational note about uppercase letters in the conventional app ID, not a
failed validation. Recheck builds/integration on CachyOS after the current changes.

## 10. Remaining product work and acceptance criteria

After fixing/verifying the purchased AAXC workflow:

- Complete actual GNOME/Wayland testing: system light/dark/accent changes,
  keyboard navigation, screen readers, file dialogs, file-manager drops, scaling,
  resizing and responsiveness during long operations.
- Exercise expired sessions, keyring unlock, disconnect and unavailable titles
  without disrupting working account behavior or other applications' secrets.
- Add reliable resumable downloads where supported, validating Range/ETag and
  completeness. Current retries restart; canceled/partial data is removed.
- Resolve multipart Audible parent titles if possible. Newer unsupported DRM or
  license formats must fail clearly and preserve originals; do not invent APIs.
- Evaluate safe compressed-stream merge optimizations. Current merge normalizes
  to 48 kHz stereo PCM, concatenates samples, then encodes once. It is correct for
  tested mixed inputs but uses substantial temporary disk and is not a general
  lossless compressed concat implementation.
- Review source-format tag/art transfer, MP3 player conventions, long summaries,
  chapter timing and cover behavior on actual listening software.
- Improve remaining filename-conflict UX if required: current choices are rename
  or fail, without a destructive conversion-overwrite mode. There is no automatic
  source deletion or retained-intermediate preference. Do not claim these exist.
- Review abrupt interruption/recovery and error paths for low disk, permissions,
  missing dependencies, corrupt files and long queues. Atomic publication
  currently requires a hard-link-capable destination filesystem.
- Finish Arch-compatible installation/reproducibility and evaluate Flatpak only
  after desktop keyring, browser, file access and FFmpeg licensing are validated.
- Maintain tests and documentation as features change; add real evidence without
  committing private account/media data. Keep the interface restrained/native.

The final acceptance checklist remains: native launch; import; MP3/M4B conversion;
multi-file merge; correctly timed M4B chapters; supported metadata and cover edits;
chosen flat output location; originals preserved; responsive operations; safe
errors; passing relevant tests; correct docs/licensing; real user authentication,
purchased-library retrieval and eligible downloads; and separate user-controlled
download/conversion workflows. Mark each passed only with actual appropriate
evidence, or clearly describe a real blocker. The prior claim that development
was fully done was withdrawn; this is a working initial implementation with
unfinished and unverified requirements.

## 11. License and upstream decisions

The application is **AGPL-3.0-only**, not the original suggested plain GPL.
audible 0.13.1 declares AGPL-3.0-only and is used in-process. Mutagen is
GPL-2.0-or-later and can be combined through GPLv3/AGPLv3 provisions. See LICENSE,
THIRD_PARTY.md and architecture.md for the evaluated dependencies and obligations.
Keep notices/source obligations intact. There are no activation keys, paid tiers,
artificial restrictions or proprietary SDK requirements. Audible service terms
and applicable DRM law are separate from software licensing.

OpenAudible, Libation, audible-cli, audible and FFmpeg were researched. Historical
OpenAudible public source identifies itself as 1.1.8 despite pom.xml saying 1.1;
it is not evidence that current commercial releases are open source. No
OpenAudible/Libation application code is copied. audible-cli was used as a
protocol reference; its terminal application framework was not added. Libation/
AAXClean are maintained .NET alternatives but were not pulled into the Python UI.
See architecture.md for concrete source/activity/license findings and links.

Do not upgrade or replace the authentication backend speculatively while fixing
media conversion. Upstream authentication/device-code migration and license
throttling were known concerns; the owner's current sign-in/download path works.
If a backend change becomes justified, isolate it behind the existing adapter.

## 12. Engineering and communication expectations

Write maintainable, professional code consistent with the existing modules.
Use clear names, focused functions and concise comments for non-obvious choices.
Avoid unnecessary frameworks, containers, cloud services and new abstractions.
Use system packages and a venv, never `sudo pip` or externally-managed Python
overrides. Keep work inside this project and avoid modifying unrelated projects
or global system/security settings.

Do not add AI attribution, assistant signatures, artificial authorship claims or
AI-themed styling. Preserve actual third-party attribution. State verified facts,
owner reports, controlled reproductions and remaining unknowns separately.
Report actual test commands/results and fix failures rather than merely listing
them. After real AAXC verification, continue toward a complete useful utility,
not just another diagnostic handoff. Keep `docs/progress.md` current.

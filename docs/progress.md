# Development progress

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

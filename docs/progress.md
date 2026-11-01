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

## Phase 6 — underway

Desktop packaging, license notices, documentation and integration verification.

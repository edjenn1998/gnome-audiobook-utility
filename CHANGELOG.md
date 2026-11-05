# Changelog

## 0.1.1 — 2026-11-04

- Detect protected media by container brands despite misleading extensions and
  fully decode conversion/merge results before publication.
- Recover download receipt/license commits with durable non-secret journals;
  reject corrupt receipts and serialize updates without replacing earlier licenses.
- Retain media licenses on Disconnect; provide separate confirmed Forget Licenses.
- Validate every transfer redirect, bound retries/deadlines and cover-cache growth,
  tolerate nullable library metadata and display external text literally.
- Fix ADTS-first merging, explicit cover removal and temporary-path normalization.
- Coalesce progress, recycle library rows and prepare previews off the GTK thread.
  Prompt before discarding metadata edits and improve keyboard/lifecycle handling.
- Restrict packaged sources to an approved tracked manifest; verify dependency
  versions/integrity, harden launcher diagnostics and add validated CA support.
- Keep maintenance validation active under optimized Python; capture only the
  application widget. Add fresh-state checks and credential-free core/native CI.
- Fix isolated setuptools/editable builds by loading the public-file policy from
  its explicit source path, including when the checkout is absent from `sys.path`.
- See `REMEDIATION_REPORT.md` and `docs/releases/0.1.1.md` for per-finding evidence,
  packaged validation and remaining platform/manual acceptance.

## 0.1.0 — 2026-11-02

First public GitHub release, including the self-contained x86_64 AppImage.

- Add a self-contained x86_64 AppImage build with Python, GTK/Adwaita, WebKit/helper
  processes, FFmpeg, glibc, certificates, fonts, schemas, source and license notices.
  Include packaged media/browser self-tests and a SHA-256 checksum sidecar.
- Use title-only download filenames without an added [ASIN] catalog suffix. Keep
  fingerprint/receipt-based license association and old filename compatibility.
- Fix rejection of valid numeric AAX quality variants such as `AAX_22_64` after a
  granted license. Keep the existing voucher/container path and reject unrelated
  formats. Distinguish a missing offline URL from an unsupported audio format.
- Record owner-confirmed automatic login and a real saved-session `AAX_22_64`
  native-queue download, followed by full M4B decoding of 24.5 hours / 50 chapters.
  Expanded suite: 117 passing tests.

- Replace redirect-URL copying/pasting with an ephemeral native WebKitGTK login
  window using the existing Audible backend's callback/PKCE and keyring storage.
  Add automatic capture, cancellation, timeout and fixed safe error messages.
- Move library selection/download actions outside the list's only scroller, with
  compact native layouts and selection-sensitive controls; keep progress visible.
- Verify automatic callback handling, live public Amazon page rendering, and an
  actual native-toolbar download followed by protected conversion/full decode.
  The owner confirmed automatic login; additional MFA variants and a fresh
  packaged AppImage login remain manual verification steps.

- Verify two purchased AAXC books on native CachyOS: full M4B decoding, chapter
  retention and unchanged originals; also verify actual MP3 conversion and both
  native conversion handlers. Live saved-session library retrieval passes.
- Add strong-ETag/Range-validated retry resume, safe restart fallback and cleanup.
- Preserve original whole-book entries for multipart audiobooks. Roll back the
  automatic AudioPart expansion after reproducing HTTP 404 child-license failures
  while the same parent's complete download succeeds. Verify the corrected native
  queue and explicit conversion against a real multipart audiobook.
- Show actionable license-request HTTP 404 errors and log each queue item's
  failure stack without recording titles, server error payloads or credentials.
- Preserve Audible summary/publisher aliases, save portable long descriptions,
  and provide a multiline native summary editor.
- Fix Adwaita row containers and Metadata-page Ctrl+O; select native development
  tools by default and add isolated project-local checks/native verification.
- Expand the automated suite to 117 passing tests on CachyOS. See
  `docs/cachyos-validation.md` for evidence and remaining manual acceptance checks.

- Reproduce the protected-inspection error with the real FFprobe under a
  non-dumpable parent; replace parent-PID `/proc` paths with explicitly inherited
  child-local descriptors for keys, IVs, concat scripts and ffmetadata.
- Retain failing operation, exit status and bounded redacted media-tool stderr;
  handle optional FFprobe `N/A` bitrate fields without rejecting valid audio.
- Add read-only `--diagnose-only --report` evidence collection for the owner's
  actual executable, descriptor, receipt, keyring and protected-media stages.
  Real purchased-book conversion on CachyOS is now verified as recorded above.

- Resolve protected imports by verified receipt fingerprints, including historical,
  renamed and moved downloads, with compatibility for existing ASIN keyring items.
- Keep new media vouchers per download, validate key/IV values and preserve older
  downloads' licenses without changing account authentication.
- Apply licenses during import inspection and conversion using private FFprobe
  option files and FFmpeg concat demuxer options; no keys appear in process arguments.
- Preserve protected-source chapters, metadata, covers and AAC priming timestamps;
  fully decode converted audio before publishing an output.
- Add genuinely encrypted AAXC/voucher regressions, including native UI import,
  full PCM comparison, private transport and failure cleanup; document a local
  purchased-book verification command and the remaining real-file test blocker.

## Development foundation — 2026-11-01

- Established native GTK4/Libadwaita application with Convert, Merge, Metadata
  and Audible views, persistent preferences and desktop integration.
- Added real FFprobe inspection, cancellable MP3/M4B conversion, compatible AAC
  stream copy and atomic output verification.
- Added mixed-format chapter-file merging, numeric ordering, manual reorder,
  sample-count M4B chapters and merge-time metadata/artwork.
- Added transactional MP3/MP4 tag editing and validated JPEG/PNG cover editing.
- Added isolated audible 0.13.1 browser sign-in, Secret Service persistence,
  paginated library retrieval and verified streaming original-format downloads.
  Live Audible account and protected-media compatibility remains unverified.
- Added synthetic-media, native UI and mocked network tests; documented upstream
  research, licensing, installation, architecture and outstanding manual checks.

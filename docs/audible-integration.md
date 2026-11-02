# Audible.com integration

Current CachyOS results are in [validation](cachyos-validation.md): actual
purchased-book M4B/MP3 conversion, full decode and both native conversion handlers
pass. Investigation sections below retain the historical trace.

## Backend and compatibility

The optional adapter uses **audible 0.13.1**, licensed AGPL-3.0-only, in-process.
This is an independently maintained client for Audible's private API, not an
official supported Amazon SDK. US marketplace only. The API request shapes were
checked against audible-cli's `Library` and `LibraryItem` source on 2026-11-01.
No terminal CLI framework or separate downloaded browser runtime is embedded.
Automatic login uses the system WebKitGTK 6 engine; see
[authentication and layout](authentication-ui.md).

Upstream is actively changing authentication: audible issues #906/#914 and
audible-cli #328 discuss device-code registration; audible #909 reports license
denials/throttling. Pinning a version makes the implemented contract explicit,
but does not freeze Audible's server behavior. Future migration should stay
within `audible_service.py`, leaving GTK and local audio operations independent.

## Sign-in

1. The worker checks that Secret Service is available.
2. `Authenticator.from_login_external(locale="us")` generates the upstream
   browser sign-in URL and PKCE state.
3. A dedicated Adwaita/WebKit login window opens Amazon's actual page in an
   ephemeral browser session. Users complete passwords/MFA/CAPTCHA/approvals on
   that page, never in application password fields.
4. The expected HTTPS maplanding redirect is captured automatically and validated
   against the backend's return destination. There is no URL copying/pasting.
5. The library registers the session; its serialized authenticator is saved
   only in Secret Service. The browser closes and the main window shows Connected.

There is no application password collection, CAPTCHA bypass or clipboard
inspection. Canceled/failed reauthentication keeps saved credentials and media
licenses. The owner confirmed automatic login through the new window, as well as
library retrieval and the earlier download/conversion/playback workflows. The saved
session from that login has now passed actual downloads and protected conversion.
WebKit callback/error/cancellation tests also pass. Additional real MFA/CAPTCHA
edge cases still require interactive testing where applicable.

## Session and local data

The upstream authenticator refreshes tokens as needed; refreshed authentication
is persisted after successful API operations. Unauthorized responses instruct
users to connect again, keeping media licenses. Disconnect removes application session and media
license keyring entries; it does not claim to revoke the remote device registration.
Do not disconnect before converting a protected file whose license you need.

No credentials, cookies, activation bytes or decrypted vouchers go into settings,
download sidecars, diagnostic logs or the repository. FFprobe reads its key/IV
from file-valued options backed by anonymous Linux memfd files. FFmpeg reads
per-file demuxer options from a single-input concat script in another memfd;
its argument parser does not support the same file-valued AVOption syntax.
Neither command line nor persistent files contain the secrets. `FFREPORT` is
removed from child environments to prevent inherited debug reports from recording
demuxer credentials. An unlocked keyring is
required: without one, local audio tools continue working.

Each memfd is explicitly inherited by the child using `pass_fds`, and paths use
`/proc/self/fd/N` in the child. The parent retains CLOEXEC and closes the files
after the child finishes. Parent-PID paths are no longer used: opening
`/proc/<parent>/fd/N` is subject to cross-process permission checks and can be
denied even when the key, IV and tool option names are all correct.

Settings: XDG config. Cover cache: XDG cache. Download receipts: XDG data,
containing ASIN, local path, byte count, SHA-256 and an opaque keyring item reference.
Earlier records for the same ASIN are retained so older files keep their own
licenses. These references are not keys or vouchers. The local-download
indicator is recomputed by verifying those receipts, not trusting filenames.

## Library and downloads

Library retrieval requests active titles in pages of 100, parses author/title,
duration/images and offline rights, and deduplicates ASINs. Refresh detects a
repeated full page rather than looping forever. Library visibility alone is not
authorization: unavailable titles are disabled and the server must grant each
content license before a transfer begins.

For downloads, the adapter follows audible-cli's content license request fields
and iOS device headers. An offline URL and content format are taken from the
granted response. Decrypted media vouchers are validated and kept in separate,
immutable-per-download Secret Service items. A subsequent download never replaces
the license for an earlier file. MPEG is
saved as MP3, supported AAX-family license formats as AAXC, without conversion.
Numeric AAX quality variants (`AAX_<sample-rate>_<bitrate>`) share that same
voucher/container path. In particular, a live `AAX_22_64` title now passes download
and complete conversion; an earlier fixed allowlist incorrectly rejected it.
This does not add support for other DRM families. A granted license missing its
offline URL is reported separately from an unsupported audio format.
No purchase, payment or entitlement changes are made.

The transfer streams HTTPS into private staging files. It requires a known
positive Content-Length, rejects non-audio content types, validates the MP3/MP4
container signature and byte count, and publishes without overwriting. Transport
and transient server failures receive at most three attempts with backoff;
authorization errors require refresh/retry. Canceled and partial transfers are
removed. Interrupted requests resume within the active operation only when a
strong ETag and matching Content-Range/length validate the remaining bytes. Range
rejection or representation changes restart safely; weak/missing validators also
restart. There is no persisted partial-download state across application restarts.
SHA-256 receipts verify subsequent local presence but are not server-supplied
cryptographic authenticity proofs. Transfer success does not prove protected
audio can be decrypted or that every encoded frame is intact.

The UI downloads serially, records completed titles, keeps failures selected for
retry and continues other selected jobs. Multipart audiobooks retain their original
whole-book entry and request its complete license. Automatic child expansion was
rolled back after live AudioPart license requests returned HTTP 404 while the same
parent's complete download succeeded. Child-library offline rights do not prove
that an individual part can use the content-license endpoint. The corrected native
queue and explicit conversion passed on a real multipart audiobook. Per-item queue
failures record their stack separately, and HTTP 404 license errors explain how to
refresh and select a whole-book entry. No imported voucher files
or cross-account license sharing are supported.

## Protected conversion

1. `download_book` decrypts the granted response's voucher through the existing
   audible library, validates a 16-byte hex key and IV, and stores the voucher in
   Secret Service. The completed download's receipt points at that specific item.
2. On import, `input_options` checks the file's byte count and SHA-256 against
   current and historical receipts. This works after restart, rename or moving
   the file. Legacy receipts use their existing `media:ASIN` keyring item. Only
   when no receipt matches is the original trailing `[ASIN]` filename used as a
   compatibility fallback; bracketed text in a title is not mistaken for an ASIN.
3. The same resolver supplies the key and IV to FFprobe during import and again
   during conversion. Protected files show real properties and chapter count,
   rather than bypassing inspection. Missing/malformed vouchers, changed known
   downloads and protected inspection failures produce distinct safe messages.
4. FFprobe uses `-/audible_key` and `-/audible_iv` pointing at RAM files. FFmpeg
   instead opens a one-file concat script whose `option audible_key` and
   `option audible_iv` directives apply the same MOV demuxer options. Script paths
   are quoted and keys are validated; the script never touches persistent storage.
5. Because concat does not export child chapters/global tags, the converter
   supplies the original probe's metadata/chapters through a separate ffmetadata
   RAM input. `-copyts` preserves AAC priming timestamps; covers are transferred
   with Mutagen rather than duplicated as video tracks. Compatible AAC remains
   stream-copied to M4B.
6. Before publication, FFprobe verifies duration, chapter count, timestamps and
   titles, and FFmpeg decodes the complete protected-conversion result to a null
   sink with `-xerror`. Incorrect keys cannot silently yield a successful but
   unplayable stream-copy output. Original files are preserved on every failure.

Legacy AAX uses the connected account's activation bytes through the same private
option transport. AAXC conversion is tested using generated AAC encrypted with
per-packet AES-CBC and clear trailing bytes (the MOV demuxer's AAXC packet layout),
not an unprotected file renamed `.aaxc`. Tests also generate an upstream-compatible
encrypted media voucher and exercise its actual audible-library decryption.

### Diagnosis of the reported failure

The original conversion call already forwarded resolved options into `probe`;
it was not unconditionally probing without a key. However, file association
ignored receipts, parsed the first bracketed string, and reused one mutable
voucher per ASIN. Those paths could lose or misidentify the license on import.
Separately, a genuine encrypted fixture exposed FFmpeg 8 rejecting
`-/audible_key` with “Unrecognized option '/audible_key'”, even though FFprobe
accepted it and both binaries supported the normal MOV demuxer options.
An earlier test used unprotected M4A and exercised only FFprobe, missing that
conversion failure. The new regressions cover encrypted source inspection,
actual conversion and complete decoded audio.

The specific owner's “Cannot inspect audio” failure cannot be conclusively
attributed without their file/license and FFprobe installation. No purchased
audiobook has been converted or listened to in this development environment.

### Follow-up: reproduced descriptor failure and actionable diagnostics

After the owner reported the same error again, a controlled Evo test reproduced
it using correct keys, genuinely encrypted AAC, and the real FFprobe binary.
Only the disposable parent process was marked non-dumpable with
`prctl(PR_SET_DUMPABLE, 0)`; no kernel policy or system configuration was changed.
The old `/proc/<parent>/fd/N` route failed with exit status 1 and **Error opening
file** when FFprobe attempted to open its key file. Its option loader omits the
OS errno; an independent child read returned **EACCES (13, permission denied)**.
These are recorded as distinct observations, not conflated. The same process, file and
license work using inherited `/proc/self/fd/N` descriptors. A separate test
converts and fully decodes the encrypted fixture under the same restriction.

This demonstrates a concrete defect in the prior transport. It does **not** prove
that the owner's CachyOS process has that restriction. The old catch-all handler
also hid nonzero tool exits, malformed JSON, missing required audio properties
and Python numeric-conversion failures behind the same message. Errors now name
the operation (`ffprobe.inspect`, `ffprobe.audio_properties`, `ffmpeg.convert`,
`ffmpeg.verify_audio`), exit status, and a bounded redacted tool error. Optional
bitrate/duration fields containing `N/A` are handled through valid fallback
fields rather than rejected as corrupt audio. Invalid required sample rate,
channel count or duration still fails inspection.

### Collect the actual CachyOS evidence first

Run from the updated source project in the desktop session that owns the keyring:

```sh
./tools/run-local .venv/bin/python tools/verify-protected.py "/absolute/path/Book.aaxc" --diagnose-only --report aaxc-diagnostics.json
```

This is a diagnostic, not automatic M4B conversion. It generates a tiny temporary
public test tone for parser/transport self-tests, reads the existing receipt and
keyring item, inspects the actual source, and attempts up to three seconds of
decode-to-null if inspection succeeds. It does not log in, request new licenses,
download anything or modify the source, receipts, keyring or application settings.
Temporary test media is cleaned up. The new report file has mode 0600 and is not
overwritten if it exists. Exit zero means collection completed; examine each
status field to see which checks passed or failed.

The shareable JSON contains:

- `diagnostic_revision: 2` and `private_transport: pass_fds:/proc/self/fd`, confirming
  that the updated code ran.
- The FFprobe/FFmpeg executables and versions actually selected by the launcher,
  including whether a copied `.deps` runtime is overriding system executables.
- Parent dumpability/ptrace scope and actual child read tests for both the old
  parent-PID path and the new explicitly inherited descriptor.
- Independent FFprobe and FFmpeg private-option loading tests on public media.
  Recognition of `audible_key` alone does not establish that secure file-option
  syntax and descriptor access work.
- Receipt readability, size/SHA-256 match, fingerprint versus legacy-filename
  lookup, per-download versus legacy license scope, keyring lookup result, and
  whether the key/IV are valid 16-byte hex values. If a voucher supplies an ASIN,
  only the boolean comparison with the receipt is included, not the identifiers.
- Protected inspection stage, exit status and redacted stderr, plus a whitelist
  of numeric codec properties where available. These distinguish an exec/loader
  failure, option rejection, descriptor access failure, invalid JSON, unavailable
  optional bitrate and unusable required audio properties.
- The outcome of the short protected decode. This is not full-book verification.

No keys, IVs, tokens, cookies, voucher contents, ASINs, audiobook titles, raw
FFprobe JSON or source paths are included. The executable paths normalize the
home directory to `~`. Send the report rather than raw keyring data, raw tool
stdout/stderr or secret-bearing command lines. A receipt match plus valid hex
does not prove the selected voucher decrypts the audio; the actual inspection
and decode results are needed. No passing mock or synthetic test substitutes for
testing the owner's purchased file.

### Verify an existing download

Restart the updated application and re-import the AAXC file in Convert. Keep the
current keyring and receipts; do not disconnect or delete session data to apply
this fix. If using the Meson-installed launcher, rerun `meson install -C build`
from the activated virtual environment so it uses the updated modules.

For a full conversion/decode check in the desktop session that owns the download:

```sh
./tools/run-local .venv/bin/python tools/verify-protected.py "/absolute/path/Book.aaxc" --output "/absolute/path/Book-verified.m4b"
```

This uses the existing keyring and receipts, refuses to overwrite existing output,
checks complete decode, chapters, populated metadata and original-file integrity,
and prints no keys or voucher contents. After success, open the result in your
usual player to verify audible playback and navigation. No password or key export
is needed. If a legacy file was renamed and its receipt is missing, restore its
original `[ASIN]` suffix. If its old ASIN-level voucher was already replaced by a
different download, that lost association cannot be reconstructed automatically;
a fresh authorized download with its own receipt/license is needed.

## Remaining account-owner tests

- Complete a real US sign-in, with MFA where enabled.
- Restart and refresh from a saved/unlocked keyring session; test expired tokens.
- Compare a real paginated library with the account's purchased title list.
- Download one entitled title, cancel another and retry; compare downloaded size
  with response metadata and check unavailable/multipart behavior.
- Convert eligible AAX/AAXC using the system FFmpeg and verify complete duration,
  chapters, metadata and cover with legally obtained source media.
- Disconnect and verify all application secrets are removed; confirm other
  applications' keyring items are untouched.

Basic sign-in, library retrieval and AAXC download are user-reported working;
the additional cases above and purchased-book conversion remain pending.
Automated account tests use only safe fixtures.
Audible's service terms, regional availability and applicable laws concerning
technical protection measures apply independently of this software's open-source
license. The application makes no legal determination about a user's jurisdiction.

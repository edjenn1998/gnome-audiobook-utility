# CachyOS validation — 2026-11-02

This is the current continuation record. Earlier handoff notes describing
purchased-book conversion as blocked are historical.

For the latest automatic-login and fixed-toolbar changes, see
[authentication/UI verification](authentication-ui.md). The latest suite has 117
passing tests; the dated records below retain earlier results. The owner has
confirmed live automatic login through the new WebKit window. Its saved session
has passed actual downloads and conversion, including a newly supported AAX quality.

## Environment and migration

- Checkout: `/home/edwin/Projects/gnome-audiobook-utility`.
- CachyOS GNOME/Wayland, Python 3.14.8, GTK 4.24.1, Libadwaita 1.10.0,
  native FFmpeg/FFprobe 9.0.2; no Ubuntu runtime override.
- The outer ZIP matches the old committed source. The working folder contains
  newer uncommitted AAXC fixes, tests and handoff. The nested migration archive's
  checksum passed; its 50 project files matched the arrival checkout exactly.
  Git integrity passed. HEAD remains `1aa768b`; no commit or publication made.
- Copied Evo environments/builds were preserved in `dist/evo-runtime-backup/`.
  A fresh `.venv` uses system PyGObject, `requirements.lock` and editable dev
  dependencies. Generated development files stay inside the project.

## Purchased audio: observed results

The existing desktop keyring was already unlocked. Both downloads matched their
receipt SHA-256 fingerprints and resolved their saved licenses: one legacy ASIN
license and one per-download license. No login or new download was needed.

| Check | Result |
| --- | --- |
| Native FFprobe/FFmpeg private-option loading | Passed |
| Both protected sources inspected and initial audio decoded | Passed |
| Book A: 30,019.69 seconds, 48 chapters, M4B | Passed, complete decode and unchanged source hash |
| Book B: 72,980.89 seconds, 138 chapters, M4B | Passed, complete decode and unchanged source hash |
| Book A: native Import → Convert Imported Files | Passed, complete decode, chapters and cover |
| Book A: native Convert Last Download → Convert Imported Files | Passed using the existing download, complete decode and unchanged source |
| Book A: protected-source MP3 at 128 kb/s | Passed, complete decode, duration, summary, publisher, cover and unchanged source |

M4B checks verify source chapter counts, titles and times. Metadata and covers are
present. Final conversions recognize Audible's `©des` and `©pub` fields; initial
conversions exposed that missing mapping, which was then fixed. Actual source
names, ASINs and credentials are absent from this document. Generated private
reports and media remain in ignored `dist/`.

The current code works on these real downloads. This does not establish every
earlier failure's cause: the legacy parent-FD read also succeeded in this desktop
session, so the reproduced dumpability defect cannot be declared this computer's
original root cause. Multiple historical fixes and copied runtimes matter here.

The owner subsequently confirmed successful AAXC-to-M4B conversion and audible
playback. Detailed beginning/middle/end listening and player chapter navigation
have not been explicitly reported. Complete decoding remains technical evidence,
not a substitute for those listening checks.

## Additional completed work

- Download retries retain partial data within the active operation when a strong
  ETag permits Range/If-Range. Content-Range start/end/total, ETag and length must
  agree. Ignored ranges restart from the full response; invalid resumed responses
  and HTTP 416 reset partial state. Weak/missing validators restart. Cancellation
  and final failure clean up. No persistent resume across application restarts.
- Multipart audiobooks retain their original whole-book entry. Automatic AudioPart
  expansion was rolled back after the live regression described below. Whole-book
  downloads and conversion now pass through the native queue. Repeated library
  pages still stop safely; cancellation is checked after responses as well.
- Summary/publisher reads recognize Audible MP4 aliases. Full summaries save to
  both `desc` and `ldes`; editing/removal clears old recognized aliases. The native
  summary editor is multiline and preserves paragraphs.
- Adwaita rows use supported list/group containers, fixing warnings exposed by
  Libadwaita 1.10. Ctrl+O opens metadata files on the Metadata page.
- Session-expiration guidance recommends connecting again, retaining media
  licenses, instead of instructing disconnect and deletion.
- Native tools are the launcher's default; extracted runtimes require explicit
  opt-in. Native tests use independent application instances.
- `tools/verify-native.py` exercises both conversion handlers without another
  login/download. `tools/check-local` isolates generated test state under `dist/`.

## Automated checks

Local suite after the download fix: **90 passed, 0 failed, 0 skipped**, 28.71 seconds,
with 448 upstream
PyGObject asyncio-policy deprecation warnings. Ruff and whitespace checks passed.
See the final entry in `progress.md` for subsequent packaging verification.

Live library refresh with the existing saved session also passed. This check used
a read-only keyring-store adapter: refreshed in-memory authentication was not
persisted, no licenses were requested and no stored account data was changed.

```sh
./tools/check-local
```

Real-account checks need the owning desktop bus and default receipt data. Keep
generated diagnostics, caches and outputs in the checkout:

```sh
TMPDIR="$PWD/dist/tmp" XDG_STATE_HOME="$PWD/dist/state" XDG_CACHE_HOME="$PWD/dist/cache" \
  ./tools/run-local .venv/bin/python tools/verify-protected.py "/path/to/existing.aaxc" \
  --diagnose-only --report dist/new-diagnostic.json

TMPDIR="$PWD/dist/tmp" XDG_STATE_HOME="$PWD/dist/state" XDG_CACHE_HOME="$PWD/dist/cache" \
  ./tools/run-local .venv/bin/python tools/verify-native.py "/path/to/existing.aaxc" \
  --output-directory "$PWD/dist/native-check"
```

Native verification opens its own window and creates two M4Bs using rename-on-
conflict naming. It drives handlers, not native file chooser clicks or a new
download. Do not use an isolated D-Bus session for real-account checks.

## Remaining acceptance work

1. Detailed listening at beginning/middle/end and player chapter navigation; the
   owner has confirmed successful conversion and playback.
2. Actual file-manager drops, native choosers, keyboard-only operation, screen
   readers, fractional scaling and system appearance/accent changes. Native
   workflows and narrow-window tests have run on Wayland.
3. Live expired-session/reconnect, locked-keyring interaction, unavailable titles,
   further multipart titles and CDN resume behavior. Basic sign-in/library/downloads
   and a corrected real multipart queue download now have live evidence.
4. Optional future work: compressed-stream merge optimization, persistent resume/
   recovery and a validated Flatpak. Current mixed-format merging normalizes PCM
   and needs substantial temporary disk. New-file publication requires hard links.

Do not call the application fully accepted until the appropriate desktop/player
checks are recorded. Preserve original media and existing account/licenses.

## Follow-up: confirmed multipart download regression

The owner reported that sign-in/library refresh worked and old AAXC conversion
played correctly, but several new downloads failed. The queue log originally
captured only the final aggregated error, hiding the individual failing stage.

- A fresh single-part download passed with the current transfer code, ruling out
  a universal resume/streaming failure.
- Two AudioPart license requests returned HTTP 404 before any transfer. Requesting
  the original MultiPartBook parent's license succeeded, followed by complete
  transfer, protected inspection and full M4B decode (72,980.89 s / 138 chapters).
- The earlier expansion replaced whole-book entries with their children. The
  account's complete-book entries were still usable; child offline rights were
  insufficient evidence of a supported child-license workflow. This was an
  application regression, not evidence that the owner's login was broken.
- Removed automatic expansion and the parent-download prohibition. Library titles,
  ASINs and rights now stay attached to the original whole-book entries. Added a
  clear HTTP 404 license message and safe per-item queue stack logging.
- Verified the corrected actual native queue: refreshed library → selected original
  multipart book → complete download → Convert Last Download → explicit M4B
  conversion → full decode and all 138 chapters. Test downloads/receipts/outputs
  stay under `dist/download-check/`; temporary diagnostic licenses stayed in memory
  and did not change the real keyring or existing receipts/downloads.
- Regression coverage now exercises single/multipart library → encrypted voucher →
  download → receipt → restart/rename → probe → conversion, and confirms that the
  native queue retains successes, keeps failures selected and safely logs the
  original item's failure stack. Full suite and lint pass as recorded above.

Close/reopen the application and refresh the library to discard old in-memory
AudioPart rows. Fewer displayed entries after this fix represents whole books
instead of separate parts; it does not mean purchased books were removed.

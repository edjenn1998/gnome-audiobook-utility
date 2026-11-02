# Development

## Setup and launch

Follow the Arch setup in the README. Keep the virtual environment inside the
project and use the system PyGObject through `--system-site-packages`.
`requirements.lock` records runtime versions exercised during development;
update it intentionally alongside the test suite. PyGObject/GTK/Libadwaita and
FFmpeg are native distribution dependencies, not pip-built vendored runtimes.

Launch with `./tools/run-local`, or install editable and run
`.venv/bin/audiobook-utility`. Never run the application as root.
Meson installs source and desktop integration, while setuptools provides Python
development packaging and a console entry point. Dependencies must be present
in the interpreter selected by `-Dpython=...`.

## Tests and build checks

```sh
./tools/check-local
TMPDIR="$PWD/dist/tmp" PIP_CACHE_DIR="$PWD/dist/pip-cache" .venv/bin/python -m build
. .venv/bin/activate
meson setup build --prefix="$PWD/dist/install" -Dpython="$VIRTUAL_ENV/bin/python"
meson install -C build
appstreamcli validate --no-net data/io.github.edjenn1998.AudiobookUtility.metainfo.xml
```

On a live GNOME session, Xvfb is optional. For headless checks use
`xvfb-run -a ./tools/check-local`. The check wrapper isolates XDG state and all
temporary media inside `dist/`; native test instances do not attach to an already
running application. Test samples are generated with
FFmpeg's sine source and contain no commercial audiobooks. Tests inspect actual
outputs, chapter timing, signal frequency/order across merge boundaries,
compressed packet integrity during metadata edits, cancellation and cleanup.
Audible tests use in-memory secrets and HTTPX mock transports. The native UI
integration test drives real background conversion, merging and tag editing
while iterating GLib's event loop; it also constructs preferences/about dialogs.

`test_protected_media.py` generates genuinely encrypted AAXC packets and an
encrypted upstream-compatible voucher using only synthetic tones and test-only
identities. It exercises actual upstream voucher decryption, SecretStore JSON
roundtrips with a fake collection, HTTP transfer, persistent receipts, restart,
renamed imports, FFprobe and FFmpeg. The M4B's decoded PCM, chapter timings/titles,
tags and cover are compared with the unencrypted reference. MP3, malformed/missing
vouchers, wrong keys, historical license references, cancellation, private argv
transport, inherited FFREPORT removal and native protected import are covered.

FFprobe and FFmpeg do not share the same parser for file-valued AVOptions.
`private_options(tool="ffprobe")` uses anonymous file-valued options;
`private_options(tool="ffmpeg")` uses a single-file concat script with per-file
options in RAM. Do not replace either with secret-bearing command arguments.
The concat path needs explicit source chapters/global tags and `-copyts` to
preserve AAC priming. Protected conversions must fully decode before publication,
even when AAC was stream-copied. See audible-integration.md for the complete trace
and `tools/verify-protected.py` for account-owner validation without exporting keys.

`test_media_diagnostics.py` also runs a disposable non-dumpable Python parent
against real FFprobe/FFmpeg and encrypted synthetic media. It asserts that the
old parent-PID route produces a redacted permission error, then verifies that
the inherited-descriptor route inspects/converts the identical input correctly.
It separately checks CLOEXEC, explicit inheritance, cleanup, optional `N/A`
properties, operation/exit-status reporting, log redaction and the report CLI.

The previous development host was Ubuntu/Python 3.14 without system GTK4 or FFmpeg.
`tools/local-deps.py` downloads and extracts Ubuntu runtime packages into
`.deps/` without root or system installation. This helper is for Ubuntu CI,
not CachyOS. `tools/run-local` uses those extracted libraries only with
`AUDIOBOOK_USE_BUNDLED_DEPS=1`; native CachyOS executables are the default.
The wheel/sdist and Meson outputs stay under ignored `dist/`, `build/`, `.deps/`.

## Structure

- `ui.py`: native views, file dialogs, accessible labels and serialized workers.
- `media.py`: probe, conversion, PCM-normalized merge, sample-count chapters,
  FFmpeg cancellation and output verification.
- `metadata.py`: container-specific Mutagen field mappings and artwork transactions.
- `files.py`: sanitized names, collisions and atomic file publication.
- `settings.py`: validated XDG configuration.
- `audible_service.py`: replaceable account/library/license adapter.
- `credentials.py`: Secret Service, with no plaintext fallback.
- `download.py`: streaming HTTPS transfer, retry, cancellation, completeness checks.
- `receipts.py`: SHA-256 verified local-download records, separate from credentials.
- `thumbnails.py`: bounded HTTPS image retrieval and XDG cache.
- `diagnostics.py`: redacted local stack-location diagnostics.
- `media_diagnostics.py`: stage-specific media errors and bounded stderr redaction.
- `protected_diagnostics.py`: on-device FD/tool/receipt/license evidence collection.
- `data/`: desktop entry, icon, launcher template and AppStream metadata.

## Reliability decisions

One worker operates at a time per window. GTK widgets are accessed on the main
thread; workers receive frozen input values and GLib-scheduled callbacks. New
outputs are built in private same-directory staging files and atomically linked
without overwriting existing paths. Metadata uses a verified copy and atomic
replacement, checking whether the source changed before publication. Source
audio remains untouched by conversion and merge.

Merges decode inputs in order to consistent PCM, concatenate bytes, and encode
once. Chapter boundaries use decoded sample counts, avoiding estimates from
file-size/bitrate. This trades disk space for mixed-format correctness and
bounded process argument size. AAC stream copy is limited to single-input M4B.
FFmpeg processes have independent cancellation watchers; stderr cannot deadlock
stdout. The watcher escalates terminate to kill after three seconds.

Atomic publication requires a filesystem supporting hard links. On unsupported
filesystems the operation fails safely rather than using a racy overwrite-prone
fallback. Forced process termination/power loss can leave `.audiobook-*` staging
files or `audiobook-*` PCM workspaces. Do not remove them during an active job.
There is no recovery journal or auto-resume in this release.

## Diagnostics and manual checks

Diagnostics go to `$XDG_STATE_HOME/audiobook-utility/diagnostics.log` (default
`~/.local/state/...`) with mode 0600 and bounded rotation. Exception types and
stack locations are recorded without arbitrary exception values or locals.
Structured media failures additionally record their operation, exit status,
safe numeric property summary and bounded redacted recognized stderr lines.
Known secrets, hex data, quoted values, URLs and source paths are removed;
raw FFprobe stdout and media tags are not logged. Protected failures now expose
actionable tool evidence instead of a catch-all message. Avoid enabling HTTP/audible debug
logs, which upstream may populate with secrets.

Manual GNOME checks still needed: Wayland scaling, light/dark and accent changes,
screen-reader announcements, keyboard-only file dialogs, drop behavior through
the desktop file manager, very narrow windows, and cancellation under low disk
space. For account-dependent checks see audible-integration.md. These are not
substituted by the Xvfb UI tests.

### Automatic login and library layout checks

WebKitGTK 6.0 is a native login/test dependency (`webkitgtk-6.0` on Arch/CachyOS),
loaded only on demand by the application. `test_login.py` uses real WebKit with
synthetic redirecting HTML to check callback capture, cancellation, denial,
registration/network failures and a missing browser runtime. No real credentials
or password values are part of those tests. `test_library_layout.py` verifies
toolbar ancestry, actual scroll geometry, compact sizing and selection sensitivity.

On this background GNOME session, Wayland test surfaces sometimes report zero
allocations; use `GDK_BACKEND=x11 ./tools/check-local` to obtain measured native
geometry through Xwayland. Do not silently treat zero-sized windows as successful
resize tests. The owner has confirmed normal automatic login; additional live
MFA/CAPTCHA edge cases remain manual. See
[authentication/UI verification](authentication-ui.md).

## Metadata conventions

MP3 uses TIT2/TPE1/TPE2/TALB/TCON/TPUB/TDRC/TCOP/TLAN, COMM description,
TXXX:SERIES and TXXX:SERIES-PART; TPE2 represents narrator here, although other
players may interpret it as album artist. MP4 uses name/artist/album/genre/date,
description, copyright, `©nrt` narrator, and iTunes freeform SERIES, SERIES-PART,
Publisher and LANGUAGE atoms. Empty supported fields remove their mapped tags.
Artwork uses APIC (front cover) or MP4 covr. Existing unknown tags survive when
Mutagen supports them. Images remain unscaled and unmodified after validation;
the preview uses aspect-preserving containment. JPEG/PNG are accepted up to
20 MiB, 12,000 pixels per side and 40 megapixels.

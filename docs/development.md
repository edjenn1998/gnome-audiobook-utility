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
xvfb-run -a ./tools/run-local .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests tools
.venv/bin/python -m build
. .venv/bin/activate
meson setup build --prefix="$HOME/.local" -Dpython="$VIRTUAL_ENV/bin/python"
meson install -C build --destdir "$PWD/.deps/stage"
appstreamcli validate --no-net data/io.github.edjenn1998.AudiobookUtility.metainfo.xml
```

On a live GNOME session, Xvfb is optional. Test samples are generated with
FFmpeg's sine source and contain no commercial audiobooks. Tests inspect actual
outputs, chapter timing, signal frequency/order across merge boundaries,
compressed packet integrity during metadata edits, cancellation and cleanup.
Audible tests use in-memory secrets and HTTPX mock transports. The native UI
integration test drives real background conversion, merging and tag editing
while iterating GLib's event loop; it also constructs preferences/about dialogs.

This development host is Ubuntu/Python 3.14 without system GTK4 or FFmpeg.
`tools/local-deps.py` downloads and extracts Ubuntu runtime packages into
`.deps/` without root or system installation. This helper is for Ubuntu CI,
not CachyOS. `tools/run-local` uses those extracted libraries only when present.
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
`~/.local/state/...`) with mode 0600 and bounded rotation. Only exception types
and stack locations are recorded, never exception values, locals, tokens or
signed URLs. FFmpeg failures show bounded stderr in the local error dialog;
protected-input failures use a fixed message. Avoid enabling HTTP/audible debug
logs, which upstream may populate with secrets.

Manual GNOME checks still needed: Wayland scaling, light/dark and accent changes,
screen-reader announcements, keyboard-only file dialogs, drop behavior through
the desktop file manager, very narrow windows, and cancellation under low disk
space. For account-dependent checks see audible-integration.md. These are not
substituted by the Xvfb UI tests.

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

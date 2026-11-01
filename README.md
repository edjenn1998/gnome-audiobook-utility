# Audiobook Utility

A native GTK4/Libadwaita application for Linux audiobook tasks:

- Convert local audio to M4B/AAC or MP3, preserving supported tags and covers.
- Combine chapter files into a single audiobook, with natural filename ordering,
  manual ordering, editable chapter titles and verified M4B chapter timestamps.
- Edit MP3/M4A/M4B audiobook metadata and add, replace or remove JPEG/PNG covers.
- Connect an Audible.com US account, browse available titles and download original
  supported media separately from conversion.

Local tools work without an Audible account. This is free software under
**AGPL-3.0-only**, with no activation, paid tiers or application subscription.
Audible's service and purchase requirements are separate.

![Merge view with synthetic chapter files](docs/screenshots/merge.png)

**Validation status:** local audio engines and native UI workflows have been
tested with synthetic media and real FFmpeg. Audible is implemented against
audible 0.13.1 and tested with non-sensitive fixtures; live sign-in, purchased
library retrieval and protected-media downloads/decoding need account-owner
verification. See [progress](docs/progress.md) for the acceptance record.

## Requirements

Python 3.12+, GTK 4.10+, Libadwaita 1.5+, PyGObject, FFmpeg and FFprobe.
A running Secret Service keyring (normally GNOME Keyring) and a system browser
are required only for Audible. Recent FFmpeg (7+ recommended) is needed for
file-valued protected-input options; AAX/AAXC support depends on the build.

## CachyOS / Arch development setup

From the project directory:

```sh
sudo pacman -S --needed python python-pip python-gobject gtk4 libadwaita ffmpeg gnome-keyring
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e '.[dev]'
./tools/run-local
```

The virtual environment uses the distribution's PyGObject. No `sudo pip` or
externally-managed-environment override is needed. On systems naming Python
`python3`, substitute that for `python` when creating the virtual environment.

## Install a desktop launcher

The project must stay at its chosen location because the launcher uses its
virtual-environment interpreter. Installation is per-user, without root:

```sh
. .venv/bin/activate
meson setup build --prefix="$HOME/.local" -Dpython="$VIRTUAL_ENV/bin/python"
meson install -C build
```

If `build/` already exists, use `meson setup build --reconfigure` with the same
options. Launch **Audiobook Utility** from GNOME, or run
`~/.local/bin/audiobook-utility`. The Meson install includes a desktop entry,
SVG icon, AppStream metadata, source modules and license notices. For system
packaging, set a distribution prefix/interpreter and install via `DESTDIR`;
Python dependencies must be supplied separately.

## Use

1. **Preferences:** choose download and converted-output directories. The default
   output is `~/Audiobooks/`, with no automatic author or series folders. Choose
   M4B/MP3 defaults, bitrate, chapter defaults and rename-or-fail conflict behavior.
2. **Convert:** import or drop one or more local audio files, inspect codec,
   duration, bitrate, sample rate, channels, size and chapter count, then convert.
   Compatible AAC-to-M4B uses stream copy. Originals remain in place.
3. **Merge:** import files or a folder. Folder import is non-recursive. Tracks
   start in natural numeric order; use arrows to reorder and edit chapter titles
   directly in the rows. Set the output filename and optionally expand metadata
   and cover controls before merging. M4B is recommended for chapters.
4. **Metadata:** open an MP3/M4A/M4B file. Save changes transactionally, or use
   **Restore from File** to discard unsaved edits, including cover changes.
5. **Audible:** connect in your system browser, complete security checks there,
   and paste the final Amazon maplanding URL into the masked field. Refresh,
   search and select titles, then download. Successful files are verified before
   their status changes. **Convert Last Download** imports the last output into
   the separate conversion workflow.

Cancel operations with the footer button or Escape. Ctrl+O opens file importing.
Use **Open Output Folder** to find the last result. Do not enable upstream HTTP
debug logging or share sign-in URLs, keyring exports or media licenses.

## Limits in this release

- Audible.com US only; authentication is an unofficial upstream integration
  undergoing a device-code transition. Service license throttling can prevent
  downloads. Live account workflows are not yet verified.
- Downloads require HTTPS, a known positive Content-Length and a recognizable
  media container. Failed/canceled transfers restart rather than resume. A
  downloaded protected file is verified for transfer completeness, not decryptability.
- Multipart Audible parent titles are not expanded automatically. Direct legacy
  AAX download selection is not exposed; local AAX conversion is supported when
  account activation and FFmpeg permit it. AAXC conversion needs its downloaded
  filename and keyring license. Disconnect removes saved media licenses too.
- Merging normalizes to 48 kHz stereo PCM and encodes once; it does not currently
  offer a lossless compressed-stream concat path. Temporary space is roughly
  192 KB per second of audio, plus the encoded output and one decoded track.
- Metadata editing targets MP3 and MP4 containers. Other source formats can be
  converted, but their nonstandard tags/artwork may not all transfer. Narrator,
  series and publisher tags are not recognized by every player.
- Conflicts can rename or fail; there is no destructive conversion-overwrite mode.
  Originals are never automatically deleted. Intermediates are always cleaned
  after handled success/failure/cancellation; abrupt process termination can leave
  staging files, which can be removed after confirming no operation is running.
- Flatpak distribution and a real CachyOS/Wayland/accessibility review are pending.

## Development and licensing

```sh
xvfb-run -a ./tools/run-local .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests tools
```

See [development](docs/development.md), [architecture](docs/architecture.md),
[Audible integration](docs/audible-integration.md), [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY.md). The repository has not been published;
the AppStream homepage points to the existing developer profile until a project
homepage is authorized.

# Self-contained x86_64 AppImage

## Run

The executable is created at:

```text
dist/Audiobook_Utility-0.1.0-x86_64.AppImage
```

Download the AppImage and checksum from
[GitHub Releases](https://github.com/edjenn1998/gnome-audiobook-utility/releases/latest).
Local builds are already executable; downloaded files may require
`chmod +x Audiobook_Utility-0.1.0-x86_64.AppImage`. Close any running development copy, then double-click
the AppImage or run it directly. It can be moved to another folder; the project
checkout and `.venv` are not required to run it. Existing XDG preferences,
download receipts and desktop keyring credentials retain their normal locations.
User media stays in the chosen download/output directories, outside the image.

The matching `.AppImage.sha256` file contains the artifact's SHA-256 checksum.
If FUSE mounting is unavailable, the runtime also supports:

```sh
./Audiobook_Utility-0.1.0-x86_64.AppImage --appimage-extract-and-run
```

## Bundled runtime

- CPython and the application's pinned Python dependencies, PyGObject and Cairo.
- GTK4, Libadwaita, GLib/GIO and the required introspection typelibs.
- WebKitGTK 6, its separate browser/network executables, Bubblewrap, D-Bus proxy,
  GStreamer plugins and native image-decoder helpers.
- FFmpeg/FFprobe with their transitive native libraries; the normal AAC/MP3 and
  protected-input code paths are unchanged.
- A matching glibc loader/runtime, TLS modules, Mozilla certificates, locales,
  fonts with their actual Fontconfig alias rules, icons/cursors, keyboard-layout
  and X11 locale data, and GSettings schemas.
- Software rendering libraries so matching host GPU userspace drivers are not
  needed. Native GNOME styling and dark-mode behavior are retained.
- Application source/build files, dependency version manifest and license notices.

There is no package installation, pip invocation or runtime download on launch.
The app still needs normal OS services: an x86_64 Linux kernel with unprivileged
user namespaces, a graphical desktop, and desktop D-Bus/Secret Service for Audible
credentials. Those are desktop/kernel services, not libraries installed by this
bundle. This build is verified on the owner's CachyOS GNOME system; other
distributions/CPU generations have not been independently tested.

## How isolation works

The static `AppRun` launcher starts the bundled Bubblewrap through the bundled
loader, then exposes a read-only private `/usr` and `/etc`. Consequently both
Python and hardcoded WebKit/GStreamer helper paths use the same bundled runtime,
rather than accidentally loading host GTK, WebKit, Python or FFmpeg versions.
The host's user/data directories, display sockets and session bus remain available.
File choosers and opening the output folder use the host desktop portal rather
than trying to execute a host file-manager binary against the bundled libraries.
The outer namespace supplies a filesystem/runtime layout; it is not presented as
a restriction on the user's files. WebKit retains its separate normal sandbox.

Only a few system identity/network files are bound into the private `/etc` at
launch (passwd/group, hosts/resolver, machine ID and local timezone). Build-time
copies do not contain the owner's account, tokens, receipts, personal media,
machine ID or passwords. Package-owned runtime files and an explicit public
source allowlist supply the image.

`usr/share/audiobook-utility/appimage-build.json` inside the image records Python
and native package versions, the source revision/dirty state and the verified
build-tool checksum. `source/` beside it contains the public project source and
build scripts; dependency license files are under `usr/share/licenses/`.

## Rebuild on CachyOS/Arch

Use the existing project venv and installed native runtime packages:

```sh
TMPDIR="$PWD/dist/tmp" .venv/bin/python tools/build-appimage.py
```

The builder copies package-owned runtime files, recursively resolves ELF libraries
and GI typelibs, compiles schemas/module caches, builds a static launcher, includes
source/notices, and creates the AppImage. It never installs system packages. It
downloads a checksum-pinned `go-appimage` build tool into `dist/appimage-tools/`.
Build work, tool extraction/caches, AppDir, manifest and artifacts remain in `dist/`.
The native package set and exact installed versions are recorded, so runtime
changes are visible rather than silently assumed to be bit-for-bit reproducible.

Useful intermediate commands:

```sh
.venv/bin/python tools/build-appimage.py --appdir-only
.venv/bin/python tools/build-appimage.py --package-only
```

The output is unsigned. The builder creates local artifacts; GitHub release
publication is a separate maintainer step. Automatic in-place updates are not
configured; download new versions from the repository's Releases page.

## Verification

```sh
./dist/Audiobook_Utility-0.1.0-x86_64.AppImage --self-test
./dist/Audiobook_Utility-0.1.0-x86_64.AppImage --self-test --network
```

These checks generate public test tones, convert/merge/tag/decode them, load cover
art, start the real native interface, and exercise automatic callback capture in
the bundled ephemeral WebKit browser. The network option additionally verifies
HTTPS/DNS/certificate loading and the public Amazon sign-in form without entering
credentials or registering an account. Runtime assertions check that Python and
application imports come from the private `/usr`.

During development, set `TMPDIR`, the XDG config/data/cache/state paths and
`XDG_RUNTIME_DIR` to project-local test directories. Retain the normal desktop bus
for display/keyring checks. Tests here use `GDK_BACKEND=x11` for allocated native
windows through GNOME/Xwayland; the application itself does not force that backend.

The final verification report is stored with build artifacts under `dist/` and
the latest session results are recorded in `docs/progress.md`. Full interactive
account reauthentication from the packaged browser remains an owner check unless
explicitly recorded as tested; public form loading is not an account login.

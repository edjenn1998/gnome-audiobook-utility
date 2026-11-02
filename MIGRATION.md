# Move development from Evo to CachyOS

The move is complete. Current results and local commands are recorded in
`docs/cachyos-validation.md`. This document retains the original transfer procedure.

## Contents

The migration archive contains one top-level `gnome-audiobook-utility/` directory:

- Current source, tests, documentation, artwork and build definitions.
- **The local `.git` history and uncommitted/untracked fixes.**
- `OPENCODE_HANDOFF.md`, the detailed continuation prompt.
- `MIGRATION_MANIFEST.json`, an ignored generated inventory containing hashes,
  modes, HEAD and expected Git status.

It excludes virtual environments, Evo's Ubuntu `.deps` runtimes, builds, old
archives, caches, installed Python metadata, downloaded audio, vouchers, account
configuration and keyring data. This is a development snapshot, not just a
source distribution of the last commit. No new commit or remote push is needed
to preserve the current work.

## 1. Copy the archive and checksum

On Evo the files are:

```text
/home/edwin/coding/gnome-audiobook-utility/dist/migration/gnome-audiobook-utility-migration.tar.gz
/home/edwin/coding/gnome-audiobook-utility/dist/migration/gnome-audiobook-utility-migration.tar.gz.sha256
```

From a suitable download directory on CachyOS, replacing `EVO_HOST` with your
usual SSH hostname/IP:

```sh
scp edwin@EVO_HOST:/home/edwin/coding/gnome-audiobook-utility/dist/migration/gnome-audiobook-utility-migration.tar.gz .
scp edwin@EVO_HOST:/home/edwin/coding/gnome-audiobook-utility/dist/migration/gnome-audiobook-utility-migration.tar.gz.sha256 .
sha256sum -c gnome-audiobook-utility-migration.tar.gz.sha256
```

## 2. Extract into your actual coding directory

Locate the real coding directory on CachyOS; its absolute path was not provided
to the Evo session. Close the running application. If an older
`gnome-audiobook-utility` directory already exists, keep it as a separately named
backup and preserve any local source edits for comparison. Do not extract over
that old tree: stale `.deps`, `.venv` or Meson files could survive an overlay.

From the chosen coding directory, once the target name is free:

```sh
tar -xzf /absolute/path/to/gnome-audiobook-utility-migration.tar.gz
```

Open a terminal in the extracted project. Check:

```sh
git log --oneline -3
git status --short --untracked-files=all
git fsck --full
```

The last HEAD should be `1aa768b`. A dirty working tree is **expected**: the AAXC
and diagnostic fixes are newer than that commit. Do not reset/clean them away.
Compare against the inventory's `git_status`. The package was verified by
extracting it and checking its content hashes, Git HEAD/status and object store.

Your actual CachyOS books, XDG preferences/receipts and desktop keyring already
exist outside the code directory. Keep those in place. Do not export credentials
or disconnect the account to migrate source. The app ID remains
`io.github.edjenn1998.AudiobookUtility`, preserving its credential namespace.

## 3. Build a fresh CachyOS development environment

Use the normal user, not root, for the application and Python environment.
Install missing native dependencies through the distribution as appropriate:

```sh
sudo pacman -S --needed python python-pip python-gobject gtk4 libadwaita ffmpeg gnome-keyring
python -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install -e '.[dev]'
```

The lock records runtime versions tested on Evo, not proof they have been tested
on this machine. If a dependency cannot install with your Python version, record
the actual error and resolve it deliberately; do not silently remove pins or
modify system Python. PyGObject comes from system packages through
`--system-site-packages`.

**Do not copy Evo's `.venv`, `.deps` or `build` into the new tree.** The archive
deliberately omits them. `tools/run-local` should now use CachyOS system FFmpeg,
FFprobe, GTK and Libadwaita. Run:

```sh
./tools/run-local
```

Use this launcher initially, rather than an old installed desktop launcher with
copied/stale modules or an absolute path to the previous venv.

## 4. Start OpenCode with the handoff prompt

Start the new OpenCode session with the extracted project as its working
directory. Give it this instruction:

> Read `OPENCODE_HANDOFF.md` completely and use it as the continuation prompt.
> Continue this existing project on this CachyOS computer. Preserve the dirty
> working tree and existing account/download state. First diagnose and verify
> the already downloaded AAXC using the local keyring and current report tool;
> then continue completing the application. Follow applicable local AGENTS.md.

The handoff covers current code, exact symptoms, confirmed versus unconfirmed
causes, file/credential association, subprocess transport, tests, constraints,
licensing and the remaining roadmap. No OpenCode global configuration is included
or changed by this migration.

## 5. First local diagnostic and tests

In the actual owning GNOME desktop session, select the existing AAXC path:

```sh
./tools/run-local .venv/bin/python tools/verify-protected.py "/absolute/path/Book.aaxc" --diagnose-only --report aaxc-diagnostics.json
```

This creates no M4B, performs no login/download/license request and does not
change account state. It reads the keyring and produces a redacted report.
Look for `diagnostic_revision: 2` and `pass_fds:/proc/self/fd`. The actual CachyOS
failure has **not** been confirmed solved by Evo's synthetic tests.

For the automated native suite, install Xvfb if needed:

```sh
sudo pacman -S --needed xorg-server-xvfb
xvfb-run -a ./tools/run-local .venv/bin/python -m pytest -q
.venv/bin/ruff check src tests tools
git diff --check
```

Close a running application with the same app ID before testing. An isolated
`dbus-run-session` can help isolate synthetic tests, but do not use an isolated
bus for the real account diagnostic: it needs your existing desktop keyring.

When source launch is confirmed, rebuild desktop integration if wanted:

```sh
. .venv/bin/activate
meson setup build --prefix="$HOME/.local" -Dpython="$VIRTUAL_ENV/bin/python"
meson install -C build
```

Keep the project at that location, since the installed launcher refers to the
chosen virtual-environment interpreter. No AppStream/GitHub publication is part
of this move.

## Regenerate the migration package

`python3 tools/package-migration.py` builds the same kind of portable snapshot
under `dist/migration/` and verifies a temporary restored repository. It uses
only Python's standard library and Git; no account or media access is needed.

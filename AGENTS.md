# Project continuation

- Follow `/home/edwin/Projects/AGENTS.md`. Keep generated files, test media,
  temporary directories, reports, caches and installations inside this project.
- Read `docs/cachyos-validation.md` for the current state. The earlier sections
  of `OPENCODE_HANDOFF.md` and `docs/progress.md` describe historical snapshots.
- Preserve the intentional uncommitted and untracked work. Do not reset or clean
  it. Do not commit or publish without the user's explicit authorization.
- The native CachyOS `.venv` is current. Copied Evo `.venv`, `.deps` and `build`
  are preserved in ignored `dist/evo-runtime-backup/`. Native tools are the
  default; Ubuntu runtime overrides require `AUDIOBOOK_USE_BUNDLED_DEPS=1`.
- Run `./tools/check-local` for the suite, lint and whitespace checks. It isolates
  test configuration, receipts, logs, caches and temporary media inside `dist/`.
  Native tests need a display; use Xvfb only when no display is available.
- For real-account diagnostics retain the owning desktop bus and default XDG data
  location so existing download receipts resolve. Set `TMPDIR`, `XDG_CACHE_HOME`
  and `XDG_STATE_HOME` to project-local directories. Write reports and converted
  output under `dist/`. Do not log vouchers, tokens, keys or raw media metadata.
- Purchased AAXC inspection, complete M4B/MP3 decoding, actual native queue download
  and both conversion handlers have passed on CachyOS. The owner reports successful
  conversion and playback. Detailed player navigation and accessibility checks
  remain. Do not represent automated decoding as a listening test.
- Keep original whole-book library ASINs, including MultiPartBook parents. Automatic
  replacement with AudioPart children caused a confirmed live download regression:
  child licenses returned HTTP 404 while the parent download succeeded. Do not
  reintroduce expansion based only on fixture tests or child offline-rights flags.
- New downloads use title-only filenames without an appended [ASIN]. Keep the
  catalog identifier in receipts/keyring references, with fingerprint-based license
  lookup. Preserve compatibility with older bracketed filenames.
- Keep download and conversion separate. Preserve the working authentication
  backend and original media. Do not disconnect the actual account during tests:
  use only fake keyrings in tests. Ordinary logout now retains media licenses;
  explicit confirmed license forgetting is destructive.
- Automatic login now uses a dedicated ephemeral WebKitGTK 6 window through the
  existing upstream browser callback. Read `docs/authentication-ui.md`. Never
  inspect password fields, log complete callbacks/cookies, or replace the backend
  protocol. The owner confirmed automatic account login. Saved-session downloads
  and conversion have also passed; additional MFA/CAPTCHA edge cases remain manual.
- Accept numeric AAX quality variants such as AAX_22_64. A fixed codec allowlist
  omitted that valid variant and rejected granted licenses before download. Keep
  unknown DRM families rejected, and verify formats with real media as well as tests.
- Audible actions live outside its only scroller. Preserve that structure and
  the original whole-book entries. Layout tests require allocated native surfaces;
  `GDK_BACKEND=x11 ./tools/check-local` works on this GNOME/Xwayland session when
  background Wayland test windows have zero geometry.
- AppImage packaging is in `tools/build-appimage.py` and `tools/appimage/`; read
  `docs/appimage.md`. Keep its bundled native-runtime isolation and WebKit sandbox.
  The final image and checksum live directly in `dist/`; all staging/tool/test
  files remain under `dist/`. Do not package accounts, receipts or real media.

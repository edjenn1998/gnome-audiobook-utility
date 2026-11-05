# AppImage portability checks

The owner authorized the 0.1.1 build and publication. Its candidate passed normal
and extract-and-run checks on CachyOS GNOME/Xwayland, including public-page HTTPS,
and actual CA mount integration through Python, libsoup and WebKit. The existing
0.1.0 artifact is preserved. No compatibility is inferred for distributions or CPU
generations that have not actually run the image. Source CI on Ubuntu 26.04 does
not constitute an AppImage execution test there. See `releases/0.1.1.md`.

## Defined baseline and diagnostics

The current native build mechanism targets x86_64 Arch/CachyOS packages and requires
unprivileged user namespaces for its private runtime. Bundling glibc does not
remove kernel, CPU, desktop-session or policy requirements. FUSE-free extraction
only removes the FUSE requirement, not the namespace requirement.

The updated launcher provides `--diagnose-runtime` before loading Python. It
reports kernel/architecture and probes namespaces in a disposable child. It does
not change host policy or disable WebKit's sandbox. Failed runtime/application
startup points users to that diagnostic. The launcher is verified both through
synthetic fault tests and the actual 0.1.1 candidate runtime.

## Repeatable matrix

Use clean ordinary-user desktop VMs for each proposed supported baseline
(Arch/CachyOS, Ubuntu 24.04+, Debian and
Fedora). Record exact OS/kernel/CPU, Wayland/Xwayland, portals/keyring, namespace
policy, FUSE execution and extraction. Restricted-policy failures must remain clear
unsupported-environment results, not reasons to relax policy or turn off sandboxing.

```sh
GDK_BACKEND=x11 .venv/bin/python tools/check-portability.py \
  --image /absolute/path/to/authorized-candidate.AppImage \
  --output dist/new-xwayland-report.json

GDK_BACKEND=wayland .venv/bin/python tools/check-portability.py \
  --image /absolute/path/to/authorized-candidate.AppImage \
  --output dist/new-wayland-report.json
```

The runner never builds, downloads or installs dependencies and never overwrites
an existing report. It isolates XDG state and temp media, invokes runtime
diagnostics plus both execution modes, records the image hash and cleans up its
own timed-out process group. `--network` additionally checks only the public
Amazon form; it never logs in or uses real credentials. Actual account/MFA and
desktop accessibility checks remain separate owner tests.

## Certificate policy

Bundled public roots remain the default. AppImage 0.1.1 honors an explicit
`SSL_CERT_FILE` as a complete trust-store override, or `AUDIOBOOK_USE_HOST_CA=1`
to select a standard host CA bundle at runtime. These files are read-only mounts,
not build-time copies of host trust configuration. `AUDIOBOOK_EXTRA_CA_CERTS`
adds an explicitly selected public CA file to the default/selected roots. The
bootstrap validates it, creates a private temporary combined PEM for Python/HTTPX,
and removes that file after use; WebKit's PKCS#11 trust sees the same runtime anchor.
Invalid files fail verification; TLS is never disabled. The bootstrap merge and
cleanup have synthetic CA tests. End-to-end runtime mount behavior passed on the
build host with a synthetic local HTTPS server for both additional and replacement
roots, with default rejection and malformed-CA rejection. Repeat these checks on
the proposed supported VM/desktop baselines before extending compatibility claims.

## Build provenance

Python versions must match `requirements.lock`; editable/path-injection layouts
are rejected. Wheel files with RECORD hashes are verified. Distro Python packages
that omit RECORD or strip extensions are checked against their package-manager
mtree. Native collection is checked against package integrity records and the
manifest records exact collected/runtime file hashes. A controlled native package
snapshot is still needed for reproducible release builds; a live rolling host is
not claimed to be bit-for-bit reproducible or vulnerability-free.

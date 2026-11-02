# Architecture and upstream evaluation

Research date: 2026-11-01. GitHub source, repository metadata, open issues and
published Python packages were checked; repository activity alone is not a
guarantee of service compatibility.

## Evaluated implementations

| Project | Evidence and license | Decision |
| --- | --- | --- |
| [OpenAudible](https://github.com/openaudible/openaudible) | Repository has historical Java/SWT source, Maven build and an Apache-2.0 LICENSE.md; recent repository activity 2026-10-30 does not establish that current commercial binaries are open source. | No code incorporated. Historical source is not evidence of current proprietary release licensing. No matching local archive found under the accessible home directory. |
| [Libation](https://github.com/rmcrackan/Libation) | GPL-3.0 repository; pushed 2026-10-27. Full .NET application with maintained Audible client and AAX/AAXC handling. Recent issues #2129/#2130 concern Linux login WebView failure. | Strong alternative, but shipping .NET and an application-scale backend for Python adds packaging and IPC maintenance. |
| [audible](https://github.com/mkb79/audible) | AGPL-3.0; published 0.13.1 inspected. `Authenticator.from_login_external`, refreshable authentication, sync/async clients, voucher decryption. Pushed 2026-10-27. Issues #906/#914 track device-code login migration; #909 reports license throttling. | Pin 0.13.1 behind an adapter. Browser login avoids handling passwords. Future device-code migration belongs in this adapter. Not an official Amazon SDK. |
| [audible-cli](https://github.com/mkb79/audible-cli) | AGPL-3.0; pushed 2026-10-30. Inspected `models.py`, `cmds/cmd_download.py`, downloader tests. Authenticated library pagination, content license requests, offline URLs, MPEG versus AAXC selection and voucher processing. Issue #328 requests testers for upcoming login. | Use as protocol reference rather than adding Click, terminal dialogs and CLI configuration to a GTK application. Request shape follows inspected upstream; no invented API. |
| [FFmpeg](https://ffmpeg.org/legal.html) | LGPL-2.1-or-later default; GPL options and nonfree options change binary redistribution terms. FFprobe inspects containers/codecs; FFmpeg provides AAC/MP3, chapters, concat and AAX input support. | Invoke system executables, no shell. Do not bundle nonfree builds. AAXC support varies by build; unsupported encrypted inputs are preserved and rejected clearly. |

The checked OpenAudible source identifies itself as **1.1.8** in
`desktop/swt/manager/Version.java`, while pom.xml says 1.1. It depends on Java 8,
HtmlUnit 2.23, Gson 2.2.4, SWT 4.6 and a Bintray repository. This concrete source
evidence, rather than recent release tags, establishes that the public source is
historical and unsuitable as a current authentication backend.

Libation's checked `AaxDecrypter.csproj` targets **.NET 10** and references
`AAXClean.Codecs` 3.1.0. Its `AaxcDownloadConvertBase` opens AAX, AAXC and DASH
with AAXClean/Mpeg4Lib, and its AudibleUtilities tree includes Widevine handling
and Google.Protobuf. [AAXClean](https://github.com/Mbucari/AAXClean) and
[AAXClean.Codecs](https://github.com/Mbucari/AAXClean.Codecs) are active GPL-3.0
alternatives (both pushed 2026-10-26). They would warrant a small .NET backend
if FFmpeg becomes insufficient, but add runtime/distribution and IPC obligations.
No Widevine/CDM code or device material is imported into this application.
Newer formats outside the adapter's supported license response are rejected.

Maintainer documentation and implementation references checked include the
[audible documentation](https://audible.readthedocs.io/),
[CLI source](https://github.com/mkb79/audible-cli/tree/master/src/audible_cli),
[Libation download source](https://github.com/rmcrackan/Libation/tree/master/Source/AaxDecrypter),
[FFmpeg formats](https://ffmpeg.org/ffmpeg-formats.html),
[PyGObject guidance](https://pygobject.gnome.org/) and
[Libadwaita API](https://gnome.pages.gitlab.gnome.org/libadwaita/doc/main/).

## Selected design

Python 3.12+, GTK4 4.10+, Libadwaita 1.5+, PyGObject. Presentation is separate
from media operations, metadata, filesystem transactions, settings and Audible.
One cancellable background operation runs at a time per window; worker callbacks
reach GTK only through GLib. No database, media player, network daemon or catalog.
JSON holds non-sensitive preferences in XDG config. Secret Service holds entire
Audible authentication objects and media licenses. No plaintext credential fallback.

Automatic login uses the same upstream external-browser callback contract inside
a dedicated Adwaita window backed by system WebKitGTK 6.0. Its ephemeral browser
captures the generated HTTPS maplanding redirect without clipboard interaction;
registration/token exchange and secure persistence stay in `audible_service.py`.
`login_flow.py` validates and synchronizes callback/cancellation state;
`login_window.py` owns the GTK-thread browser lifetime. See `authentication-ui.md`
for verification, privacy decisions and the pending interactive account check.

The Audible page's header/search/action toolbar is a sibling of its sole list
scroller. The main application progress/status/footer is also outside the list,
so long libraries cannot scroll account, selection or operation controls away.

FFprobe supplies stream information and output verification. Single AAC-to-M4B
conversion uses stream copy when compatible. Merge normalizes each input to PCM
with consistent sample rate/channels, then encodes once. This costs temporary
disk space but avoids concat incompatibility, command-line size limits and repeated
lossy encoding. Source-derived chapter timings use normalized sample counts.
Same-directory temporary outputs and no-clobber hard-link publication prevent
partial results and unintended replacement. Metadata is edited on a temporary
copy with Mutagen and verified before atomic replacement; unknown tags survive.

Protected imports resolve a verified download fingerprint to an immutable
per-download keyring voucher. Receipt history preserves earlier downloads and
allows moved/renamed imports; old ASIN-keyed vouchers remain compatible. No key
material is stored in receipts. Source inspection still goes through FFprobe
with the license applied. FFprobe's file-valued options use memfd storage;
FFmpeg's different parser requires per-file options in a one-input concat script,
also held in memfd. Source chapters/tags are restored through ffmetadata, AAC
priming timestamps are preserved, and the finished protected conversion must
fully decode before publication. Inherited FFREPORT settings are removed.

Private files are referenced as `/proc/self/fd/N` in each child and explicitly
inherited using Python's `pass_fds`, including ffmetadata input descriptors.
Descriptors retain CLOEXEC in the parent and are not inherited by unrelated
children. This replaces parent-PID `/proc` paths, which were dependent on
ptrace/dumpability permission checks and failed under a reproduced restricted
parent process. Media process errors retain bounded redacted stderr, exit status
and operation identifiers. The on-device diagnostic checks actual tool and FD
behavior; it makes no account API requests and creates no converted audiobook.

## Licensing

Application: **AGPL-3.0-only**, chosen instead of plain GPL because the
in-process Audible dependency is AGPL. The installed audible 0.13.1 wheel's
METADATA explicitly declares AGPL-3.0-only; its LICENSE contains the standard
AGPL text (the appendix's example notice is not a separate license grant).
Preserve its license and notices in distributions. No OpenAudible or Libation code is copied.
See THIRD_PARTY.md for direct and transitive dependency obligations.
Distributors must provide corresponding source and licenses; AGPL also covers
modified versions made available over a network. System FFmpeg build licenses
must be checked separately when bundling binaries.

Audible service terms and laws governing technical protection measures are
separate from software licensing. Authorization is required for every download.
Availability, license limits, regional restrictions and account/device changes
may prevent downloads; software cannot promise access to every listed title.
No purchases, subscription bypass or account-security bypass are implemented.

## Packaging and security tradeoffs

System GTK, Libadwaita and FFmpeg avoid vendoring native stacks. Python dependencies
live in a virtual environment, never the managed system Python. A local Ubuntu
package extraction script is only for this headless validation host. Arch is the
documented deployment target. Flatpak is deferred until keyring access, host
browser login, filesystem grants and FFmpeg licensing are tested in a sandbox.
The application ID `io.github.edjenn1998.AudiobookUtility` is provisional and
does not imply publication or registration.

No network debug logging is enabled: upstream debug logs may contain signed URLs
or credentials. User-facing Audible errors are fixed messages. Service objects
are short lived and refreshed credentials are persisted after API operations.

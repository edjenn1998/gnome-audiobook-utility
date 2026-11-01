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

## Selected design

Python 3.12+, GTK4 4.10+, Libadwaita 1.4+, PyGObject. Presentation is separate
from media operations, metadata, filesystem transactions, settings and Audible.
One cancellable background operation runs at a time per window; worker callbacks
reach GTK only through GLib. No database, media player, network daemon or catalog.
JSON holds non-sensitive preferences in XDG config. Secret Service holds entire
Audible authentication objects and media licenses. No plaintext credential fallback.

FFprobe supplies stream information and output verification. Single AAC-to-M4B
conversion uses stream copy when compatible. Merge normalizes each input to PCM
with consistent sample rate/channels, then encodes once. This costs temporary
disk space but avoids concat incompatibility, command-line size limits and repeated
lossy encoding. Source-derived chapter timings use normalized sample counts.
Same-directory temporary outputs and no-clobber hard-link publication prevent
partial results and unintended replacement. Metadata is edited on a temporary
copy with Mutagen and verified before atomic replacement; unknown tags survive.

## Licensing

Application: **AGPL-3.0-or-later**, chosen instead of plain GPL because the
in-process Audible dependency is AGPL. Audible's distribution license grants
version 3 or later (see installed distribution LICENSE); preserve its license
and notices in distributions. No OpenAudible or Libation code is copied.
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

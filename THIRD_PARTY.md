# Third-party components and notices

Audiobook Utility's source and icon are licensed under AGPL-3.0-only (LICENSE).
AppStream metadata is dedicated to the public domain under CC0-1.0.
There are no activation keys, paid tiers or application subscriptions.
Audible's own account and content entitlements are independent of this license.

No upstream application source is vendored. Dependencies retain their original
copyrights and licenses. The following license expressions were checked against
the installed distribution metadata and license files during development:

| Component | Version checked | License / attribution |
| --- | --- | --- |
| audible | 0.13.1 | AGPL-3.0-only; mkb79 and contributors, https://github.com/mkb79/audible |
| Mutagen | 1.48.1 | GPL-2.0-or-later; Mutagen developers, https://mutagen.readthedocs.io/ |
| Pillow | 13.0.0 | MIT-CMU (PIL/Pillow notices and bundled codec notices); https://python-pillow.github.io/ |
| HTTPX / HTTPCore | 0.28.1 / 1.0.9 | BSD-3-Clause; Encode OSS Ltd and contributors |
| SecretStorage | 3.5.0 | BSD-3-Clause; Dmitry Shachnev and contributors |
| Beautiful Soup | 4.14.3 | MIT; Leonard Richardson and contributors |
| pbkdf2 | 1.3 | MIT; Copyright (C) 2007–2011 Dwayne C. Litzenberger |
| pyaes | 1.6.1 | MIT; Richard Moore and contributors |
| pyasn1 | 0.6.3 | BSD-2-Clause; Ilya Etingof and contributors |
| rsa | 4.9.1 | Apache-2.0; Sybren A. Stüvel and contributors |
| certifi | 2026.1.4 | MPL-2.0; Certifi developers; Mozilla CA certificate data |
| idna | 3.11 | BSD-3-Clause; Kim Davies and contributors |
| AnyIO | 4.16.0 | MIT; Alex Grönholm and contributors |
| h11 | 0.16.0 | MIT; Nathaniel J. Smith and contributors |
| Jeepney | 0.9.0 | MIT; Thomas Kluyver and contributors |
| cryptography | 46.0.5 | Apache-2.0 OR BSD-3-Clause; Python Cryptographic Authority; additional OpenSSL/Rust notices in wheels |
| Soup Sieve | 2.8.3 | MIT; Isaac Muse and contributors |
| typing_extensions | 4.16.0 | PSF-2.0; Python Software Foundation |
| PyGObject | 3.56.2 | LGPL-2.1-or-later; PyGObject contributors |
| GTK / GLib / Libadwaita | system | LGPL-2.1-or-later; GNOME contributors (individual files may differ) |
| FFmpeg / FFprobe | system 8.0.1 checked | LGPL-2.1-or-later default, GPL-2.0-or-later or GPL-3.0-or-later depending on enabled components; FFmpeg contributors |

Mutagen may be used under GPLv3, whose section 13 permits combination with
AGPLv3. LGPL, BSD, MIT, MIT-CMU, PSF, Apache-2.0 and MPL-2.0 components above
are compatible with this combination when their individual requirements are met.
MPL retains its file-level source obligations; upstream libraries remain unmodified.

For redistribution, preserve all dependency license files, copyright notices and
wheel-bundled third-party notices. Provide corresponding source for AGPL/GPL
components and any required LGPL relinking/source material. Do not strip
`.dist-info/licenses/` from Python packages. When shipping Pillow, cryptography,
FFmpeg or native GTK runtimes, include their bundled codec/library notices too.
System package licenses are supplied by the distribution; they are not replaced
by this summary. Development-only tools (Pytest MIT, Ruff MIT, Meson Apache-2.0,
setuptools MIT) are not bundled with the application.

Protocol references: audible-cli's AGPL source documents library pagination,
offline content-license request fields, MPEG/AAXC format detection and voucher
handling. Its CLI, authentication files and downloader implementation are not
copied into this project. OpenAudible and Libation were evaluated but no code
from either project is incorporated. Audible, Amazon and GNOME are trademarks
of their respective owners; this project is not affiliated with Audible/Amazon.

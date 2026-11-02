# Automatic sign-in and fixed library actions

## Authentication method

The backend remains `audible==0.13.1` using
`Authenticator.from_login_external(locale="us", login_url_callback=...)`.
The library generates Amazon's real sign-in URL, its PKCE challenge, device serial
and fixed HTTPS `openid.return_to` target. Registration/token exchange and Secret
Service persistence stay in the existing adapter. Existing session reuse, refresh,
whole-book licensing, downloads, AAXC conversion, settings and filenames are kept.

Upstream `audible.login` includes a Playwright browser helper with WebKit support
and automatic `maplanding` request capture. Its URL builder does not expose a
localhost redirect option. We therefore use the same browser-callback contract
with the already-installed GTK4 WebKitGTK 6.0 runtime, rather than changing OAuth
endpoints, installing Playwright browsers or requesting an unsupported localhost
return URL. The application supported Audible US before this change and still
does; no existing marketplace selector was removed.

### Lifecycle and privacy

1. A worker verifies keyring access and asks the existing backend to start login.
2. The GTK thread opens a modal Adwaita window with a fresh ephemeral WebKit
   `NetworkSession`. It uses the upstream browser helper's user agent and temporary
   app-identification cookies. Amazon handles passwords, MFA, CAPTCHA and approvals
   directly in its web page. Application code does not inspect field values,
   passwords, DOM contents or authentication cookies.
3. Navigation-policy and URI notifications capture the expected HTTPS callback
   automatically. Policy interception stops the callback navigation before a
   request to the final error/landing page is needed. Only the host is displayed;
   callback URLs/codes do not enter the address bar, clipboard or diagnostic log.
4. Callback validation checks the exact upstream destination, HTTPS/default port,
   absence of userinfo/fragments, and a single nonempty authorization code. The
   backend retains its own PKCE verifier and performs the actual code exchange.
   The UI does not invent a replacement OAuth state or accept arbitrary redirects.
5. The window shows a completion state while registration/keyring persistence
   runs, then closes. The main window reports Connected. Browser state is
   ephemeral and its web process is terminated on close; persistent credentials
   remain solely in the existing desktop keyring.
6. Cancel/window close, a ten-minute timeout, callback failure, TLS/network failure
   or browser failure releases the waiting worker and closes the login window.
   Cancel is checked after callback capture and registration, before replacing
   saved authentication. Failed/canceled reauthentication retains existing auth
   and media licenses. The user can retry Login without disconnecting.

WebKit is loaded lazily only when Login is used. A missing WebKitGTK 6 runtime
shows a fixed installation hint. Local workflows and saved-session account use
do not depend on opening the browser. Developer tools/console-to-stdout are off;
raw WebKit errors, token responses and full callback URLs are not logged.

## Library layout

The Audible page has no page-wide scroller. A fixed header contains the account
actions, search field and selection/download toolbar. Its sibling
`library_scroll` is the only scrolled region and contains only the clamped book
rows. The existing application header/navigation and bottom progress/status/actions
remain outside that scroller. Other workflow pages retain their current layout.

At compact widths, selection buttons share a row and the download button moves
below them; account buttons similarly use two rows. This uses existing Adwaita
breakpoints, standard GTK boxes and native styling, with no custom CSS or sticky
overlay. The list still has usable height at 400×780.

Select Visible, Clear Selection and Download Selected / Retry keep their existing
search/queue semantics. Clear affects visible eligible selections; hidden selected
titles remain included in downloads. Button sensitivity updates on checkbox,
search, selection, queue and operation changes. The last-download conversion action
is enabled after a download and disabled during another operation. No automatic
download-to-conversion operation was introduced.

## Verification and remaining manual check

- Native tests use actual WebKit and synthetic HTML that navigates to the expected
  callback. They cover success, cancellation, callback denial, registration error,
  network error and missing runtime, while retaining saved auth/media licenses.
- Pure-flow tests reject invalid/wrong-host callbacks, duplicate/empty codes,
  callback errors, timeout and late cancellation, and check secret-safe errors.
- Structural/allocation tests scroll 150 books to the bottom, verify toolbar and
  progress coordinates stay fixed, confirm no scrolled ancestor surrounds the
  toolbar, and exercise a 400×780 layout and selection-sensitive actions.
- The actual public Amazon sign-in page loaded in the production WebKit window.
  A diagnostic checked only form-presence/unsupported-browser booleans before any
  credentials were entered: email/password sign-in fields were present and no
  unsupported-browser message was detected. No account login occurred in that check.
- A real saved-session refresh and multipart-book download passed through the new
  Download Selected / Retry button. Convert Last Download followed by explicit
  conversion passed complete decoding and all 138 chapters (72,980.89 seconds).
  Test licenses stayed in memory; test receipts/media remained under `dist/`.

The owner subsequently confirmed that the automatic login window works. A saved
session from that new login was used to reproduce and fix a separate download
format bug, then complete an actual native-queue `AAX_22_64` download and explicit
M4B conversion: 88,143.88 seconds (about 24.5 hours), 50 chapters, complete output
decoding. The login and fixed toolbar remain in place.

Full suite: **117 passed, 0 failed, 0 skipped**, 31.46 seconds, with 1,519 existing
upstream PyGObject asyncio-policy deprecation warnings; Ruff and whitespace checks
passed. Native allocation and
browser tests were run with `GDK_BACKEND=x11` on CachyOS GNOME/Xwayland: the background
Wayland test surfaces reported zero allocations in this session, so they were not
used to claim real scroll geometry. The public-page check used the same X11 backend.

**Owner-confirmed:** automatic login and relocation of the library buttons. Saved
session reuse has also been exercised by the actual download checks above. No
claim is made that every MFA/CAPTCHA/security variant was exercised. Further
manual checks include those variants where applicable, plus dark mode, keyboard
navigation, scrolling/resizing and accessibility under the owner's Wayland session.

### Follow-up: valid AAX quality rejected before transfer

After automatic login succeeded, the owner reported another download failure. The
log identified the adapter's combined format/URL rejection, rather than a login,
transport or conversion failure. The existing known-good title still downloaded
with the newly saved session. Another root library title returned a granted
license, URL and voucher with format `AAX_22_64`, which the fixed allowlist omitted.

The adapter now accepts bounded numeric AAX sample-rate/bitrate labels through the
same protected-audio path, still validating vouchers and downloaded containers.
Unrecognized DRM families remain unsupported. Missing URLs get a distinct error.
Encrypted end-to-end regressions cover both original and newly observed AAX
quality variants for single/multipart whole-book entries, and unsupported formats
are checked before any license persistence or transfer.

# Audible.com integration

## Backend and compatibility

The optional adapter uses **audible 0.13.1**, licensed AGPL-3.0-only, in-process.
This is an independently maintained client for Audible's private API, not an
official supported Amazon SDK. US marketplace only. The API request shapes were
checked against audible-cli's `Library` and `LibraryItem` source on 2026-11-01.
No terminal CLI framework, browser engine or separate runtime is embedded.

Upstream is actively changing authentication: audible issues #906/#914 and
audible-cli #328 discuss device-code registration; audible #909 reports license
denials/throttling. Pinning a version makes the implemented contract explicit,
but does not freeze Audible's server behavior. Future migration should stay
within `audible_service.py`, leaving GTK and local audio operations independent.

## Sign-in

1. The worker checks that Secret Service is available.
2. `Authenticator.from_login_external(locale="us")` generates the upstream
   browser sign-in URL and PKCE state.
3. The system browser opens the Amazon page. Users enter their password and
   complete MFA/CAPTCHA/approval there, never in application password fields.
4. After sign-in, upstream's maplanding redirect may show an error page. Users
   paste that complete URL into a masked native dialog. The URL must be HTTPS,
   on www.amazon.com or www.audible.com, with the correct path and authorization code.
5. The library registers the session; its serialized authenticator is saved
   only in Secret Service. The temporary redirect field is cleared immediately.

There is no password login fallback, automated CAPTCHA bypass or clipboard
inspection. Users may need to clear a copied redirect URL from their own clipboard.
Browser login is implemented but **has not been verified with a real account**.

## Session and local data

The upstream authenticator refreshes tokens as needed; refreshed authentication
is persisted after successful API operations. Unauthorized responses instruct
users to disconnect/reconnect. Disconnect removes application session and media
license keyring entries; it does not claim to revoke the remote device registration.
Do not disconnect before converting a protected file whose license you need.

No credentials, cookies, activation bytes or decrypted vouchers go into settings,
download sidecars, diagnostic logs or the repository. Sensitive FFmpeg options
are supplied using file-valued options backed by anonymous Linux memfd files,
not secret-bearing command lines or persistent files. An unlocked keyring is
required: without one, local audio tools continue working.

Settings: XDG config. Cover cache: XDG cache. Download receipts: XDG data,
containing ASIN, local path, byte count and SHA-256 only. The local-download
indicator is recomputed by verifying those receipts, not trusting filenames.

## Library and downloads

Library retrieval requests active titles in pages of 100, parses author/title,
duration/images and offline rights, and deduplicates ASINs. Refresh detects a
repeated full page rather than looping forever. Library visibility alone is not
authorization: unavailable titles are disabled and the server must grant each
content license before a transfer begins.

For downloads, the adapter follows audible-cli's content license request fields
and iOS device headers. An offline URL and content format are taken from the
granted response. Decrypted media vouchers are kept in Secret Service. MPEG is
saved as MP3, supported AAX-family license formats as AAXC, without conversion.
No purchase, payment or entitlement changes are made.

The transfer streams HTTPS into private staging files. It requires a known
positive Content-Length, rejects non-audio content types, validates the MP3/MP4
container signature and byte count, and publishes without overwriting. Transport
and transient server failures receive at most three attempts with backoff;
authorization errors require refresh/retry. Canceled and partial transfers are
removed. Resume/Range/ETag handling is not implemented: retry starts over.
SHA-256 receipts verify subsequent local presence but are not server-supplied
cryptographic authenticity proofs. Transfer success does not prove protected
audio can be decrypted or that every encoded frame is intact.

The UI downloads serially, records completed titles, keeps failures selected for
retry and continues other selected jobs. Multipart parents requiring separate
part license requests are not automatically expanded yet; an unsupported service
response is reported rather than labeled downloaded. No imported voucher files
or cross-account license sharing are supported.

## Protected conversion

Downloaded AAXC names include `[ASIN]` to find the keyring media license. FFmpeg
receives that license's key/IV using its supported MOV demuxer options. Local
legacy AAX uses the connected account's activation bytes via upstream. Missing
licenses, unsupported builds or decoder failures leave originals untouched.
Actual AAX/AAXC decoding is **unverified** because no account or licensed samples
were available. Do not infer tested compatibility from the presence of FFmpeg
options alone. Local unprotected conversion is separately tested and usable.

## Remaining account-owner tests

- Complete a real US sign-in, with MFA where enabled.
- Restart and refresh from a saved/unlocked keyring session; test expired tokens.
- Compare a real paginated library with the account's purchased title list.
- Download one entitled title, cancel another and retry; compare downloaded size
  with response metadata and check unavailable/multipart behavior.
- Convert eligible AAX/AAXC using the system FFmpeg and verify complete duration,
  chapters, metadata and cover with legally obtained source media.
- Disconnect and verify all application secrets are removed; confirm other
  applications' keyring items are untouched.

All tests above remain pending. Automated account tests use only safe fixtures.
Audible's service terms, regional availability and applicable laws concerning
technical protection measures apply independently of this software's open-source
license. The application makes no legal determination about a user's jurisdiction.

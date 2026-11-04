# GNOME Audiobook Utility — Code Review

**Review date:** 2026-11-04

**Project:** `/home/edwin/Projects/gnome-audiobook-utility`

**Reviewed revision:** `659d59c4fdfc34e02d0379ae25c1e708101622e9` (`v0.1.0`)

**Mode:** Review only. No fixes applied.

## 1. Executive summary

The application has a solid working foundation: authentication delegates to the
existing Audible backend, secrets use Secret Service, media commands avoid a
shell, protected-input keys use explicitly inherited anonymous descriptors, and
normal output publication is no-clobber and atomic. The existing tests provide
unusually useful real-FFmpeg and genuinely encrypted synthetic-media coverage.

**All 117 existing tests passed during this review.** Nevertheless, additional
isolated checks reproduced significant edge cases that the suite does not cover.
The highest priorities are:

1. An encrypted AAXC file with a different extension can produce a published,
   supposedly successful M4B that does not decode.
2. A completed protected download can lose its application-level license
   association if receipt persistence fails after file publication.
3. AppImage/source packaging can include Git-ignored private files from selected
   source directories, despite a clean Git status.
4. The ordinary Disconnect action immediately deletes the application's media
   licenses, with no destructive-action confirmation.

These findings do **not** mean the working application should be rewritten.
Targeted fixes at the protection-detection, transaction, packaging and credential
lifecycle boundaries are preferable. No confirmed Critical vulnerability was
identified; that is not a guarantee that the application or bundled dependencies
are free of vulnerabilities.

### Severity summary

| Severity | Count | Interpretation |
| --- | ---: | --- |
| Critical | 0 | No confirmed Critical finding in the reviewed scope |
| High | 4 | Important data/license-availability or release-confidentiality risks |
| Medium | 14 | Reproducible bugs, security-policy gaps, responsiveness risks and conditional compatibility issues |
| Low | 6 | Durability, validation-tool, development-tool and GNOME workflow improvements |

Severity describes impact **under the conditions stated in each finding**. A
conditional packaging or compatibility risk is not an assertion that the current
published image contains credentials or fails on the owner's machine.

## 2. Scope, method and preservation

Reviewed all 17 application Python modules, the 11 test modules and their fixtures,
the AppImage C/Python launcher and builder, other development/diagnostic tools,
Meson/setuptools metadata, dependency declarations, desktop integration and the
relevant architecture/validation/licensing documentation.

Evidence labels used below:

- **Reproduced:** observed with synthetic files, in-memory secrets or mocked HTTP.
- **Static-confirmed:** the current control flow directly establishes the behavior.
- **Conditional risk:** a specific deployment/data/environment condition is
  required; it was not exercised against a real account or another distribution.

### Safe execution

The normal `tools/check-local` wrapper was **not** used: it writes to the project's
`dist/` and reuses a pytest base directory that pytest can clear.

Instead, tests ran through Bubblewrap with the project and host data filesystems
read-only, except for this newly created sibling workspace. Standard `/dev` and
`/proc` mounts were provided for subprocess/GUI operation:

```text
/home/edwin/Projects/.audiobook-code-review.7DgT9k1O/
```

Python bytecode and pytest's cache provider were disabled. Test configuration,
data, caches, logs, runtime files, synthetic media and pytest outputs were directed
to that workspace. Native tests used Xwayland. Tests used their existing mocked
account fixtures; no real Audible login, license request, purchased-media
conversion, keyring clearing or GitHub publication was performed for this review.

The effective pytest invocation inside that read-only environment was:

```sh
.venv/bin/python -B -m pytest -p no:cacheprovider -q \
  --basetemp=/home/edwin/Projects/.audiobook-code-review.7DgT9k1O/pytest
```

Environment included `PYTHONDONTWRITEBYTECODE=1`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `GDK_BACKEND=x11`, isolated XDG/TMP directories
and the read-only project `src/` on `PYTHONPATH`.

### Results

| Check | Result |
| --- | --- |
| Existing suite | **117 passed, 0 failed, 0 skipped**, 31.43 seconds |
| Warnings | 1,470 upstream PyGObject asyncio-policy deprecation warnings |
| Ruff, with `--no-cache` | Passed |
| Additional synthetic/mocked checks | Findings detailed below |
| AppImage rebuild, dependency installation, commit, push | Not performed |
| Existing source/artifact snapshot | 71 files recorded; no changes detected after tests/probes |

Snapshot verification compared SHA-256, size, mode and modification time for all
tracked files and the principal existing release artifacts. The AppImage's
baseline SHA-256 is:

```text
83553972578ed8debf0e445043fb7a1cd44d059f43e87e3850bea56ecb9f0791
```

Within the project, the intended new file is this report only. The isolated
evidence workspace contains `pytest.log`, `ruff.log`, reproduction scripts,
`reproduction-results.json` and the preservation snapshot. No source tests were
added or changed.

### Limitations

This was not a new live-account test, penetration test, cross-distribution VM
matrix, long-running heap/FD profiling session, package-CVE database audit or legal
license-compliance determination. Historical owner/live verification is useful
context, but is distinguished from checks actually performed in this review.

## 3. Findings index

| ID | Severity | Finding |
| --- | --- | --- |
| H01 | High | Protection detection depends on filename extension; corrupt output can be published successfully |
| H02 | High | Download/license/receipt state is not committed as one recoverable operation |
| H03 | High | AppImage and source packaging can include Git-ignored private source-directory files |
| H04 | High | Disconnect silently performs destructive media-license deletion |
| M01 | Medium | HTTPS-only download policy is checked after redirects have already been followed |
| M02 | Medium | Valid ADTS AAC as the first merge track fails during metadata transfer |
| M03 | Medium | Merge's Remove Cover action can silently restore the source cover |
| M04 | Medium | External metadata is interpreted as Pango markup in Adwaita rows |
| M05 | Medium | Receipt corruption and concurrent writers can silently discard associations |
| M06 | Medium | The authenticated client context misclassifies local I/O failures as network failures |
| M07 | Medium | Progress delivery can create an unbounded main-loop callback queue |
| M08 | Medium | Full-size artwork decoding and eager list rebuilds remain on the GTK thread |
| M09 | Medium | Thumbnail failures can abort refresh, and thumbnail streaming is not cancellable |
| M10 | Medium | Accepted `~` temporary paths are not expanded when used |
| M11 | Medium | Library parsing conflates missing eligibility with denial and lacks row-level schema tolerance |
| M12 | Medium | AppImage dependency collection does not enforce the lock or reject editable layouts |
| M13 | Medium | The private runtime overrides normal host certificate configuration |
| M14 | Medium | AppImage portability remains coupled to host binaries and mandatory user namespaces |
| L01 | Low | Atomic file publication does not fsync the containing directory |
| L02 | Low | Thumbnail disk cache has no quota, expiry or invalid-entry recovery |
| L03 | Low | Metadata editing lacks unsaved-change lifecycle handling |
| L04 | Low | Optimization can disable package/self-test validation implemented with `assert` |
| L05 | Low | Screenshot utility assumes obsolete runtime paths and can capture the wrong desktop area |
| L06 | Low | Native launcher does not check path truncation/allocation failure and loses reliable errno handling |

## 4. Critical findings

**None confirmed.** In particular, the reviewed media command construction does
not use shell command strings, and no evidence of plaintext application credential
storage or an intentional authentication/TLS bypass was found.

## 5. High findings

### H01 — Protected input can bypass license resolution and decode verification

**Affected:** `src/audiobook_utility/audible_service.py:199-240`;
`src/audiobook_utility/media.py:233-240,247-287`;
`src/audiobook_utility/ui.py:355-377`.

**Evidence: Reproduced.** Protected-input handling is selected by `.aax`/`.aaxc`
suffix in `input_options()`. Conversion decides whether full protected-output
decode is required from the presence of secret option flags, not the actual
container/protection state. A file renamed to `.m4b` therefore gets no options.

Using the existing encrypted synthetic fixture and a valid saved receipt plus
in-memory voucher, copying the same encrypted bytes to a `.m4b` filename produced:

```text
license_options_used: false
conversion_returned_success: true
output_published: true
full_decode_exit_status: 183
```

FFprobe could still obtain container properties; AAC stream copy and structural
verification completed without proving that the audio was decrypted. The output
was only rejected by the independent full-decode check after publication.

**Impact:** A misleadingly renamed/imported protected file can be presented as a
successful conversion even though the M4B is unplayable. The original is retained,
but the success/verification guarantee is wrong, and users may archive a bad result.

**Recommended fix:** Detect protection/container identity independently of the
extension. Resolve the corresponding receipt/license when protection is detected,
and fail clearly if it cannot be resolved. Full-decode verification must not be
skipped merely because the caller omitted options. Keep the existing private-FD
transport and do not solve this by exposing keys or bypassing inspection.

**Missing tests:** Encrypted AAXC bytes renamed to `.m4b`, `.m4a`, `.mp3` and an
unrecognized extension, with and without receipts/licenses. Assert either valid
decryption or a failure before publication. Existing rename tests retain `.aaxc`;
the extension-independent test in `tests/test_reliability.py:27-31` covers FLAC only.

### H02 — A published download can be left without a usable license association

**Affected:** `src/audiobook_utility/audible_service.py:167-181`;
`src/audiobook_utility/download.py:36-110`;
`src/audiobook_utility/receipts.py:10-16,37-52`.

**Evidence: Reproduced fault injection.** The adapter saves a random-reference
keyring voucher, publishes the completed audio, then hashes and persists its
receipt. Receipt hashing remains cancellable after publication. An I/O failure or
cancellation at that point leaves the completed title-only `.aaxc` file behind.

Injecting an ENOSPC receipt failure after a simulated complete transfer left the
file and its in-memory media license present, but a subsequent `input_options()`
could not associate them. No receipt existed and the filename contained no ASIN.

**Impact:** The user sees a failed/canceled operation but retains a protected file
that the application cannot convert through its normal workflow. A key may still
exist in the keyring, but its opaque reference is no longer connected to the file.
Failures before transfer completion also accumulate unused per-download items.

**Recommended fix:** Make file publication, receipt persistence and voucher
reference ownership a recoverable transaction. Compute the digest while streaming
or before publication; prepare durable receipt/journal state before reporting
success. On failure, either roll back only this operation's artifacts/key or keep
explicit recoverable state. Never delete earlier downloads' keys during cleanup.
Define how late cancellation behaves once the commit point has been reached.

**Missing tests:** Cancel during post-download hashing; ENOSPC/permissions failure
writing receipts; abrupt interruption between publication and receipt commit;
retry/recovery without duplicating or orphaning licenses.

### H03 — Source inclusion can publish ignored credentials or personal fixtures

**Affected:** `tools/build-appimage.py:129-130,203-215,262-267`;
`MANIFEST.in:5-9`; `.gitignore:12-29`.

**Evidence: Static-confirmed; non-mutating filter check reproduced.** AppImage
source inclusion recursively copies `src`, `data`, `docs`, `tests` and `tools`,
excluding only bytecode and egg-info patterns. It does not select files from the
reviewed Git tree or apply Git ignore/private-file rules. The runtime application
package is likewise copied by directory. Setuptools' broad `tools/*` source rule
has a related risk.

Fictitious paths `tools/.env`, `tests/private.aaxc` and
`src/audiobook_utility/private.key` are ignored by Git, but none of their names is
excluded by the AppImage copy filter. Those files were **not created** in the
project for this check. Git status can remain clean while an image embeds such
additional files and records `source_dirty: false`.

**Impact:** A future build can silently include an ignored local credential file,
real media fixture or other private data in a distributable binary/source archive.
This is a build confidentiality flaw, not evidence that the present release
actually contains those files.

**Recommended fix:** Package an explicitly reviewed file manifest or clean Git
snapshot, with separately declared public resources. Apply the same policy to
runtime Python files, embedded source and sdist generation. Reject unexpected
private files/symlinks and verify the resulting inventory. Secret-format scanning
alone is not a substitute for selecting the right files.

**Missing tests:** Ignored `.env`, key and media fixtures; untracked files under
source directories; symlinks escaping the approved source root; build provenance
that matches the exact packaged file hashes. Use harmless sentinel fixtures.

### H04 — Disconnect removes all application media licenses without warning

**Affected:** `src/audiobook_utility/ui.py:543,610-615`;
`src/audiobook_utility/audible_service.py:80-81`;
`src/audiobook_utility/credentials.py:44-47`.

**Evidence: Static-confirmed and reproduced with a fake Secret Service collection.**
The button immediately calls `clear()`, which deletes both the session and every
media item for the application's ID. The explanatory label appears only afterward.
The fake-collection check confirmed that auth and media entries are removed while
another application's entry is correctly preserved.

**Impact:** A routine-looking sign-out can remove keys needed to convert existing
protected downloads. If the corresponding content can no longer be re-downloaded,
the lost local capability may be permanent. The behavior is documented, but the
destructive consequence is not communicated at the point of action. The footer
Cancel operation does not make this deletion loop reversible.

**Recommended fix:** Separate authentication logout from explicitly forgetting
download licenses. Require clear destructive confirmation for a full purge and
explain the effect on existing protected files. Retain secure storage; do not add
an automatic plaintext voucher export. Keep reauthentication on the non-purge path.

**Missing tests:** Logout with existing per-download/legacy keys; explicit purge
confirmation/cancellation; partial deletion errors; preservation of other apps'
items. The current auth-state test uses an in-memory store with no media seeded.

## 6. Medium findings

### M01 — Redirect following happens before the HTTPS policy check

**Affected:** `src/audiobook_utility/download.py:29-32,48-56`;
`src/audiobook_utility/thumbnails.py:13,20-30`.

**Evidence: Reproduced with MockTransport.** The downloader follows redirects,
then checks only the final response URL. A mocked `HTTPS → HTTP → HTTPS` chain
requested all three schemes and published the final response. An HTTP final hop
would be rejected only after that insecure request had already occurred.
Thumbnails also follow redirects without checking the final scheme.

**Impact:** The claimed HTTPS-only boundary can be bypassed by an insecure
intermediate hop. This could expose content or signed URL information and permit
tampering when an upstream redirect takes that route. No such live Audible
redirect was tested or asserted here.

**Recommended fix:** Disable automatic following and validate each next URL before
requesting it, or use an equivalent pre-request redirect policy. Bound hop count
and keep legitimate cross-host HTTPS CDN redirects working. Test direct downgrade,
downgrade-and-upgrade chains, loops and normal HTTPS CDN redirects.

### M02 — ADTS AAC first tracks fail a valid merge during tag transfer

**Affected:** `src/audiobook_utility/media.py:360-363`;
`src/audiobook_utility/metadata.py:47-54`; `src/audiobook_utility/ui.py:19`.

**Evidence: Reproduced with generated `.aac` and WAV tones.** Merge selects the
first file's Mutagen tag reader using codec name (`aac`/`mp3`), although AAC can be
in an unsupported metadata container such as ADTS. Decoding/encoding succeeds,
then `read_tags()` raises “Tag editing supports MP3, M4A and M4B containers.”

**Impact:** A supported audio import fails late, wasting processing time and
temporary space. Codec identity is not sufficient to establish metadata support.

**Recommended fix:** Determine supported tag containers independently, or handle
unsupported source metadata as a best-effort transfer with probe-tag fallback.
Do not bypass actual media validation. Add ADTS-first and other codec/container
combination tests, including explicit user-supplied output metadata/artwork.

### M03 — Remove Cover in Merge can reintroduce the first track's cover

**Affected:** `src/audiobook_utility/ui.py:78-80,95-99,491-502`;
`src/audiobook_utility/media.py:360-363`.

**Evidence: Reproduced.** The editor uses `None` to represent removal, but merge
uses `None` to mean “inherit the source artwork.” Clearing the actual merge form's
cover and passing that state to merge resulted in an output that still had a cover.

**Recommended fix:** Represent keep/inherit, replace and remove as distinct states
or use an explicit sentinel/intent parameter. Preserve original cover bytes when
keeping artwork; only thumbnails/previews should be scaled. Add a native test
with a covered first track, Choose/Remove, merge, and output artwork verification.

### M04 — External strings are rendered as Pango markup

**Affected:** `src/audiobook_utility/ui.py:375,466,640-651`.

**Evidence: Reproduced.** `Adw.ActionRow` enables markup by default. A synthetic
title containing `<b>bold</b>` was displayed as styled text rather than literally.
The same row APIs receive API titles/authors and local filenames. Entry-row titles
also contain filenames.

**Impact:** Ordinary `&`/`<` text can render incorrectly or generate GTK parse
warnings; crafted metadata can alter presentation and accessible/visible text
consistency. This is Pango/UI injection, not demonstrated JavaScript execution.

**Recommended fix:** Disable markup for externally supplied row text, or escape
both title and subtitle consistently. Add ampersand, literal angle-bracket, markup
and Unicode filename/title tests; inspect displayed labels and GTK warnings.

### M05 — Receipt corruption and concurrent saves silently lose history

**Affected:** `src/audiobook_utility/receipts.py:24-52,61-77`.

**Evidence: Reproduced.** Invalid/unreadable JSON is treated as an empty store.
A subsequent `record()` overwrote a corrupt fixture without preserving it. Two
synchronized writers that both loaded the original store completed without error
but retained only one of their two records. Atomic replace protects individual
writes, not the read-modify-write transaction. Nested receipt shapes are not
validated either; for example a non-list `previous` value can break iteration.

**Impact:** Losing associations is particularly harmful with title-only filenames
and opaque per-download key references. The normal serial GUI avoids many
concurrent-writer cases, but separate instances/tools share the same state path.

**Recommended fix:** Distinguish missing from corrupt/unreadable stores, refuse
silent destructive replacement, preserve a recovery copy, validate a versioned
schema, and hold a stable sidecar lock across load/modify/publish. Add malformed
JSON/schema, permission and simultaneous-writer tests.

### M06 — Authenticated-client context masks local I/O failures

**Affected:** `src/audiobook_utility/audible_service.py:83-98,136-182`.

**Evidence: Reproduced with fake auth/client objects.** An ENOSPC error raised
inside the `client()` context became a generic “Check your connection” error and
had no explicit original cause. The context wraps all code around `yield`,
including local download/receipt operations, not just authenticated HTTP calls.

It also saves auth on context exit after a download and receipt may already have
succeeded. A late keyring-write failure can therefore make a completed download
look failed and keep it selected for another attempt.

**Recommended fix:** Narrow the authenticated context to the API operations and
persist refreshed auth at a well-defined boundary. Classify HTTP/session, local
storage and post-commit state errors separately. Preserve safe operation/errno/
exception-type evidence without exposing upstream tokens or signed URLs. Add disk
full, unavailable keyring after success, HTTP 429 and timeout classification tests.

### M07 — Worker progress delivery has no queue bound or throttling

**Affected:** `src/audiobook_utility/ui.py:278-282,688-689`;
`src/audiobook_utility/download.py:84-94`.

**Evidence: Static-confirmed.** Each chunk/progress event allocates a new idle
source and closure. The producer has no backpressure or coalescing. Multi-gigabyte
downloads generate many thousands of updates, and a blocked GTK thread cannot
discard obsolete intermediate values.

**Impact:** Queue growth, delayed cancellation/status rendering and allocation
pressure on fast transfers or busy desktops. This is an unbounded-work design
risk; a sustained production memory leak was not measured.

**Recommended fix:** Keep the latest progress snapshot and at most one scheduled
main-loop update, or poll at a bounded rate. Use operation IDs to reject stale
callbacks after completion/cancellation. Add a fast synthetic producer test that
asserts bounded queued callbacks and the correct final state.

### M08 — Expensive cover/list work still runs synchronously on GTK

**Affected:** `src/audiobook_utility/ui.py:86-104,463-474,634-654,691-697`;
`src/audiobook_utility/metadata.py:31-42`.

**Evidence: Static-confirmed.** `set_art()` validates again and creates a texture
on the main thread. Library rendering creates a texture and widgets for every
visible book, and clears/rebuilds them on searches, bulk selections and completed
downloads. A 40-megapixel cover can require roughly 160 MB just for decoded RGBA
pixels despite the small displayed preview. The library retains compressed cover
bytes for every book as well.

**Recommended fix:** Generate appropriately sized preview images off the main
thread, retaining original bytes separately for lossless artwork saves. Reuse a
bounded texture/thumbnail cache and consider a `Gio.ListStore`/`Gtk.ListView`
factory for recycling rows. Keep the fixed toolbar outside the list scroller.
Profile large libraries and large valid covers; test that the GTK loop remains
responsive while preview data is prepared.

### M09 — Thumbnail best-effort behavior is incomplete and not cancellable

**Affected:** `src/audiobook_utility/thumbnails.py:11-32`;
`src/audiobook_utility/ui.py:622-632,201-205`.

**Evidence: Reproduced parsing failure; cancellation risk is static.** A synthetic
URL with an invalid port raised `httpx.InvalidURL` before the helper's `try`, with
zero network calls. That exception can abort the whole refresh, although covers
are intended to be best-effort. There is no cancellation parameter/check while
reading a cover, and the five-second HTTPX timeout is not a total-operation
deadline: a peer can keep supplying small amounts of data within each read timeout.

**Recommended fix:** Validate/parse inside the guarded region, handle URL/type
errors locally, and return an unavailable-cover result without discarding the
library. Pass cancellation through streaming and impose an overall deadline.
Reuse a suitably scoped HTTP client rather than establishing one for every cover.
Test malformed URLs and cancellation during a slow trickle stream.

### M10 — Temporary directory validation and use disagree about `~`

**Affected:** `src/audiobook_utility/settings.py:29-33`;
`src/audiobook_utility/ui.py:495-502`;
`src/audiobook_utility/media.py:314-320`.

**Evidence: Reproduced without creating a directory.**
`Settings(temporary="~/AudiobookTemporary").validate()` succeeds because it expands
the path, but the value is not normalized. The UI passes `Path(settings.temporary)`
to merge without expansion, so merge receives a relative path and can create a
literal `~` directory beneath the launch working directory.

**Recommended fix:** Normalize/store absolute expanded paths, and normalize again
at the core filesystem boundary. Test typed tilde paths and launching from an
unrelated/read-only working directory, not just paths selected by the chooser.

### M11 — Library input parsing is brittle and eligibility has no unknown state

**Affected:** `src/audiobook_utility/audible_service.py:35-43,113-124`;
`src/audiobook_utility/ui.py:640-650`.

**Evidence: Reproduced with synthetic dictionaries.** `authors: null` raises
`TypeError`; `runtime_length_min: "N/A"` raises `ValueError`. A single such item
aborts the page/refresh. Missing offline-rights data and an explicit false value
both become `downloadable=False`, and the UI asserts that offline downloading is
unavailable in both cases.

**Recommended fix:** Validate/normalize row-level data, distinguish absent display
fields from invalid essential IDs, and quarantine/report bad rows without losing
valid entries. Model eligibility as allowed/denied/unknown with an accurate reason
and a supported metadata refresh/check path. Do not turn every unknown into an
assumed entitlement or bypass server licensing. Static review cannot determine
which of the owner's currently disabled titles are actually downloadable.

**Missing tests:** Null/malformed contributors and runtime fields, absent rights,
explicit denial, and mixed valid/invalid pages.

### M12 — Lockfile versions and portable dependency layouts are not enforced

**Affected:** `tools/build-appimage.py:78-87,107-130,245-269`;
`requirements.lock:1-20`.

**Evidence: Static-confirmed.** The builder splits lock lines at `==` and retains
only names, then copies whichever installed distribution metadata returns. It
records the actual version but never compares it with the locked version. An
editable dependency can also contribute a `.pth`/editable loader rather than a
portable installed package. Native binaries are copied from the live host/PATH.

**Impact:** A “pinned” rebuild can silently use different code or depend on a local
checkout; a package-manager update during collection can mix runtime generations.
The current successful build is not evidence that these future cases are guarded.

**Recommended fix:** Enforce expected versions and hashes for Python wheels;
reject editable/out-of-tree layouts; verify collected files and imports inside
the private runtime. Build from a controlled native package snapshot or image,
validate binary provenance/configuration, and record source/build references and
file digests. Keep the existing build-tool checksum verification.

### M13 — AppImage trust configuration can reject legitimate host networks

**Affected:** `tools/build-appimage.py:163-195`;
`tools/appimage/AppRun.c:68-84,107`.

**Evidence: Static-confirmed conditional compatibility risk.** The private `/etc`
does not inherit the host trust store, and `SSL_CERT_FILE` is forcibly replaced
with the bundled certificate file. A legitimate enterprise/local CA or explicit
user trust configuration that works for the source application may therefore be
unavailable in the AppImage. Embedded trust data also only updates with releases.

**Recommended fix:** Define and document the trust policy. Support an explicit,
safe runtime integration of host/additional trust anchors without copying private
machine configuration into a redistributable build. Preserve certificate
verification; do not use `verify=False` or ignore WebKit TLS errors. Add synthetic
CA tests and a repeatable certificate-update process.

### M14 — Cross-distribution compatibility is not established by bundling glibc

**Affected:** `tools/appimage/AppRun.c:47-55,68-78`;
`tools/build-appimage.py:20-30,78-87,235,309-310`;
`docs/appimage.md:42-47`.

**Evidence: Static deployment risk, already partly documented.** All launches,
including local-only workflows, require the outer unprivileged user namespace.
FUSE-free extraction does not remove that requirement. Native libraries and the
static launcher are built/copied on a rolling CachyOS/Arch host; this review did
not establish their minimum CPU/kernel baseline or behavior under other distros'
namespace/AppArmor policies. A failed early `bwrap` launch happens before GTK can
present a useful application error.

**Recommended fix:** Keep the requirements explicit and add clean ordinary-user
VM tests for supported Ubuntu/Debian/Fedora/Arch baselines, namespaces restricted/
available, both display backends and extraction/mount modes. Prefer a defined
portable build baseline and actionable startup diagnostics. Do not solve failures
by globally relaxing security policy or disabling WebKit's sandbox. The outer
mount namespace is correctly documented as a runtime layout, not a security
boundary protecting the user's files.

## 7. Low findings

### L01 — Atomic publication is not fully crash-durable

**Affected:** `src/audiobook_utility/files.py:40-57`.

The temporary file is fsynced, but its directory is not fsynced after link/replace
and temporary-name removal. Atomic visibility is therefore stronger than the
power-loss durability guarantee. This matters particularly for receipt/settings
updates, not just disposable conversion outputs.

**Recommendation:** Fsync the containing directory after the namespace commit and
cleanup on supported filesystems, with explicit error handling. Add filesystem
failure-injection tests. This does not negate the existing no-clobber/atomicity
protection during normal execution.

### L02 — Thumbnail cache grows indefinitely and bad entries stay bad

**Affected:** `src/audiobook_utility/thumbnails.py:15-30`.

There is a per-image byte bound but no total disk quota, age limit or eviction.
An existing invalid cached image causes validation to fail and returns `None`
without removing/refetching the entry, potentially suppressing that cover forever.

**Recommendation:** Add bounded LRU/age cleanup and one-time refetch of invalid
entries. Test corrupt cached data, changing URLs and cache pressure. Keep artwork
source bytes and display thumbnails separate.

### L03 — Unsaved metadata edits can be discarded without a lifecycle prompt

**Affected:** `src/audiobook_utility/ui.py:201-206,520-532`.

The close handler only considers running operations. Opening another file fills
the form again without checking whether the current form has unsaved changes.
Long summaries or artwork edits can therefore disappear without a dirty indicator
or save/discard/cancel decision.

**Recommendation:** Track edit dirtiness and clear it only after a successful
save/explicit restore. Use native Adwaita save/discard handling for close/open
transitions. Add canceled-save and unsaved-open/close tests. Source audio is not
silently rewritten by the current behavior; the loss is of unsaved editing work.

### L04 — Python optimization disables verification assertions

**Affected:** `tools/appimage/self_test.py:18-26,38-42,59,79,89,127`;
`tools/appimage/AppRun.c:120-122`;
`tools/package-migration.py:75-97,134-135`; `meson.build:4-6`.

Important runtime/source/hash checks use `assert`. With Python optimization,
those checks disappear; the HTTP request inside the assertion at self-test line
89 disappears as well. The launcher does not ignore `PYTHONOPTIMIZE`. These are
validation guarantees, not assertions about impossible internal states.

**Recommendation:** Use explicit checks raising a clear exception/nonzero exit
status for build/runtime verification. Test validation with optimization enabled
and intentionally invalid metadata. This is not a claim that all media decoding
or pytest checks are bypassed: subprocess `check=True` and pytest rewriting have
different behavior.

### L05 — Screenshot tool is obsolete and its capture boundary is unsafe

**Affected:** `tools/capture.py:12-20,36-38`.

It requires the old `.deps` directory that is no longer in the active checkout.
If run on a live desktop rather than its documented Xvfb environment, it grabs the
whole screen and crops from `(0, 0)` rather than the actual application bounds.
That can capture unrelated windows/private desktop content into a tracked image.
It also lacks guaranteed window cleanup on intermediate failures.

**Recommendation:** Use an explicit isolated display or application-only capture,
project-local current temp paths and `try/finally` cleanup. Refuse an unsupported
capture context. The utility was not executed during this review.

### L06 — Native launcher startup-error handling needs stronger bounds checks

**Affected:** `tools/appimage/AppRun.c:18-24,39-53,130-132`.

`strdup()` failure is unchecked; `snprintf()` results are not checked for truncated
runtime paths. After `execv()` failure, the code calls `perror()` before using
`errno` to choose the exit status. These are low-probability startup robustness
issues, not a demonstrated buffer overflow or persistent memory leak.

**Recommendation:** Check allocations and formatted-path lengths, fail with an
actionable message, and save errno before diagnostics. Add native tests for deep
extraction paths and injected allocation/exec failures. Direct argv construction
and the existing argument-count check are good practices worth retaining.

## 8. Security and GNOME practices that are already good

- **Backend ownership:** Password/MFA entry remains on the real Amazon page. The
  application does not implement a new OAuth endpoint or collect password fields.
  The existing backend retains its PKCE verifier/registration responsibilities.
- **Callback checks:** `login_flow.py:11-49` validates HTTPS, permitted callback
  hosts, destination/path, port, fragments and a single nonempty code. The browser
  currently permits general HTTPS navigation (`login_window.py:104-126`); consider
  top-level-origin/verification-link policy hardening while preserving legitimate
  Amazon challenge flows. That is not a demonstrated callback/PKCE bypass.
- **Credential storage:** `credentials.py:23-42` uses Secret Service with fixed,
  safe error messages and no plaintext application fallback. Reauthentication
  checks cancellation before replacing auth and preserves earlier media entries.
- **Secret transport:** `media.py:22-91` uses CLOEXEC anonymous files and explicit
  `pass_fds`; no license values need to be added to process arguments or disk
  configuration. `FFREPORT` is removed. Restricted-parent regression tests exist.
- **Subprocess cleanup:** `media.py:191-204` already has a `finally` that kills/
  reaps a remaining child, closes stdout and joins its watcher. It would be wrong
  to report that every exceptional callback leaves an orphan FFmpeg process.
- **Files:** Filename normalization, UTF-8 length bounds, same-directory staging
  and hard-link no-clobber publication avoid common traversal/overwrite errors.
  Metadata saves verify a temporary copy and use an advisory lock/change check.
- **GUI separation:** Long media/download operations generally run outside GTK;
  widget changes are scheduled on the main loop. The fixed library toolbar really
  is outside its only list scroller; footer progress stays outside it as well.
- **Native UI:** Adwaita dialogs, breakpoints, standard appearance, accessible
  button labels and explicit download/conversion actions are appropriate choices.
- **Browser cleanup:** `login_window.py:174-190` removes its poll source,
  disconnects handlers, stops/terminates the view and releases the ephemeral session.
  No persistent GTK/WebKit leak was established by this review.
- **Packaging:** The builder verifies its downloaded tool hash and records native
  and Python inventory. The runtime explicitly keeps WebKit's sandbox enabled and
  uses portals rather than launching a host file manager with foreign libraries.

## 9. Automated coverage and recommended additions

### Existing strengths

- Genuine AES-encrypted AAC fixtures and upstream-compatible voucher processing.
- Library → license → download → receipt → restart/rename → probe → conversion,
  including single/multipart entries and two observed AAX quality variants.
- PCM equality, chapter timing/titles, metadata/artwork round trips and compressed
  audio packet preservation during tag editing.
- Range/If-Range/ETag validation, restart fallback, cancellation and partial cleanup.
- Restricted-parent FD transport, explicit inheritance/closure, FFREPORT removal,
  sanitized failures and diagnostic-report privacy.
- Real native GTK worker integration, automatic synthetic WebKit callbacks,
  reauthentication cancellation, fixed toolbar geometry and selection sensitivity.

### Coverage gaps by priority

| Priority | Add coverage for | Related findings |
| --- | --- | --- |
| First | Protected bytes with misleading extensions; never publish an undecodable result | H01 |
| First | Receipt/keyring persistence failure and late cancellation after completed transfer | H02 |
| First | Ignored/untracked sensitive sentinels in all source/artifact packaging paths | H03 |
| First | Logout versus explicit key purge, cancel, partial deletion and other-app preservation | H04 |
| Next | Every redirect hop, including HTTPS/HTTP/HTTPS | M01 |
| Next | ADTS AAC first track and source-cover removal intent | M02, M03 |
| Next | Literal markup/ampersands/Unicode in external row text | M04 |
| Next | Corrupt/schema-invalid receipts and serialized concurrent updates | M05 |
| Next | Local ENOSPC versus HTTP errors; auth resave failure after a completed operation | M06 |
| Next | Progress queue bounds, large valid previews and large-library rendering | M07, M08 |
| Next | Malformed URLs, slow cover streaming and bounded cancellation/close behavior | M09 |
| Next | Tilde paths, malformed/null API values and unknown eligibility | M10, M11 |
| Release gate | Mismatched/edited dependencies, clean-machine runtime imports, custom CAs and supported OS baseline matrix | M12–M14 |
| Later | Directory durability, cache recovery, edit dirtiness and optimized validation tools | L01–L04 |

There is no checked-in CI workflow in the reviewed tree. Add repeatable CI lanes
for core tests/lint, native integration under an isolated display, and artifact
tests on clean supported systems. Do not require real account credentials in CI;
keep owner-run live verification separate. No coverage percentage was measured.

### Memory/resource and dependency follow-up

The concrete resource concerns are queued progress work, eager decoded textures,
full list recreation and unbounded disk caching. Long-running heap/FD soak tests
should repeatedly refresh/search, import/remove tracks, and open/cancel login.
Do not label normal retained library data or GObject references a leak without
measurements. Explicit D-Bus connection ownership would also make resource
reasoning clearer; an actual Secret Service FD leak was not demonstrated.

No Python dependency was proven unnecessary. Several apparently overlapping
crypto/parsing packages are upstream Audible or SecretStorage dependencies.
The broad native GStreamer/codec/graphics set deserves a tested runtime allowlist
review to reduce size, maintenance and attack surface, but must not be trimmed by
guesswork that breaks CAPTCHA audio, image loading or supported local formats.
Version/license inventories are valuable; they are not a CVE audit or complete
native build/source provenance by themselves.

### Additional GNOME polish

Incremental `Gio.SimpleAction`/shortcut organization, gettext integration, status
announcements and keyboard/screen-reader validation would improve maintainability
and accessibility. `Ctrl+O` currently falls through to conversion importing on the
Audible page (`ui.py:187-193`), and the modal login window has no corresponding
explicit Escape handler even though the main window does. These are lower-priority
workflow checks, not reasons to replace the working UI framework.

## 10. Suggested remediation order

1. Fix H01 and add a failing regression before changing the conversion path.
2. Establish H02's commit/recovery model and harden receipt persistence (M05/M06).
3. Add H03's file-manifest guard before building another public artifact.
4. Clarify and guard the credential logout/purge boundary (H04).
5. Address redirect policy, ADTS/artwork/markup bugs and cancellation behavior.
6. Bound GTK work and caches, then improve dependency reproducibility and the
   supported AppImage platform/trust-store test matrix.

Keep the currently verified authentication backend, original whole-book ASINs,
private descriptor transport, explicit conversion, no-clobber output behavior and
saved account/media data intact while making those focused changes.

## 11. Review deliverable status

This report contains recommendations only. Source code, test code, settings,
credentials, downloaded books, existing test outputs and release artifacts were
not changed by a fix, rebuild or installation. No commit or push was made.

The report is intentionally untracked. If a maintainer later wants it included in
the full-history migration package, note that `tools/package-migration.py:15-19,
39-40` deliberately rejects unexpected root files until their inclusion is
approved; that allowlist was not edited as part of this review.

# Code review remediation

## Scope and safeguards

- Review: `CODE_REVIEW.md`, 2026-11-04, revision `659d59c4fdfc34e02d0379ae25c1e708101622e9`.
- Local branch: `remediation/code-review-2026-11-04`; no merge or publication authorized.
- The original untracked review was preserved byte-for-byte (SHA-256
  `19e7db9cf91c1d78b7d9b5849f28a1b0e910a07c0769add9df7baea7bda866bd`).
- No actual credentials, media licenses, audiobooks, conversion outputs or installed
  application data are used for remediation tests. No live Audible operations.
- Existing AppImage remains unchanged (SHA-256
  `83553972578ed8debf0e445043fb7a1cd44d059f43e87e3850bea56ecb9f0791`).
  No distributable AppImage rebuild or system-package installation is authorized.

## Phase 0 — baseline

Verified branch/revision, clean tracked working tree, structure and all findings in
the complete review. The findings still apply to the reviewed source. Conditional
portability/trust-store observations remain conditions to test, not demonstrated
failures on other distributions. Tests and lint ran using new isolated state in
`dist/remediation/baseline/`, preserving previous test outputs.

- Existing suite: **117 passed**, 31.43 s, 1,702 upstream PyGObject deprecation warnings.
- Ruff: passed. No source modifications before this baseline.

## Phase results

Implementation and per-finding evidence will be recorded below as each phase passes.

| Findings | Status |
| --- | --- |
| H01–H04 | Fixed and Phase 1 validated (details below) |
| M01–M14 | Confirmed/static or conditional as identified in review; pending |
| L01–L06 | Confirmed/static as identified in review; pending |

No fixes are represented as complete until their regression checks and phase gate pass.

## Phase 1 — high-severity findings

- **H01 (reproduced):** ISO-BMFF Audible brands now take precedence over filename
  suffixes; renamed protected inputs resolve the existing receipt/license path.
  Conversion rejects protected inputs without options and fully decodes every
  converted output before atomic publication. Private memfd/pass_fds transport is
  retained. Tests cover misleading `.m4b/.m4a/.mp3/.bin/.aax` and absent licenses.
- **H02 (reproduced):** Added non-secret, durable started/ready journals with
  per-transaction activity locks. The ready fingerprint/license reference is saved
  before file publication. Receipt-commit failures retain a resolvable journal;
  idempotent recovery commits completed files or deletes only this transaction's
  owned orphan key, never user files or earlier license items. Late cancellation
  after publication preserves the completed operation. Fault tests cover journal
  ENOSPC, receipt ENOSPC, canceled transfer, interrupted ready/started states,
  repeated recovery and active-transaction exclusion.
- **H03 (confirmed):** Introduced explicit `PACKAGING_FILES.txt` plus shared
  `package_sources.py` policy for runtime modules, embedded source and setuptools
  sdist/build_py hooks. Git-backed builds require approved tracked files; archive
  builds retain the same manifest. Escaping symlinks and private file types fail.
  Synthetic packaging tests exclude ignored/untracked sentinels; no actual release
  or AppImage was built.
- **H04 (confirmed):** Normal sign-out deletes only auth; explicit media forgetting
  preserves the session, requires a native destructive confirmation, and explains
  loss of conversion capability. Fake-collection and native cancel/confirm tests
  verify media/other-application preservation.
- Shared transaction prerequisites also address **M05** (strict validation,
  corruption rejection, last-valid backup and sidecar-locked updates) and **L01**
  (parent-directory fsync). Additional dedicated checks follow in their phases.
- Changed application files: `media.py`, `files.py`, `receipts.py`,
  `audible_service.py`, `download.py`, `credentials.py`, `ui.py`; packaging policy,
  setuptools hooks, builder, public manifest and high-severity regression tests.
- New regression cases initially failed against the baseline; targeted set now
  **21 passed**. Final Phase 1 gate: **138 passed**, 41.33 s; Ruff/whitespace passed.
- One initial gate aborted inside WebKit when the test runtime socket path was too
  long. Short, private runtime directories under Projects resolved that test
  environment failure; the complete login tests and full gate then passed. No
  WebKit security setting or production login protocol was weakened.

# Security and reliability review

Updated 2026-09-12 following the initial September 10 review and PR #5. The follow-up
resolves the actionable engine, parser, and presentation findings below. Synthetic
fixtures and explicit support boundaries replace unverified claims of universal
compatibility. No personal corpus, credentials, or account exports were used.

## High severity: resolved

1. **Shared scratch storage and overlapping writers.** Unique private directories,
   private files, per-store exclusive locks, and cleanup isolate each ingest. Tests
   verify permissions, same-basename isolation, conflicting writers, and interruption.
   Implementation: `engine/corpus.py`, `Corpus.__init__` and `Corpus.close`.

2. **Readers could publish stale copies over newer data.** Query readers now take a
   private snapshot from a read-only connection, release the source file, and never
   publish. This also avoids Windows replacement conflicts with long-lived readers.
   Coverage/source parsers use read-only URIs. WAL-backed source and byte-preservation
   tests cover these paths. Implementation: `open_readonly`, `Corpus.__init__`, query.py.

3. **Failed atomic publish could truncate the original.** Publishing uses a flushed,
   unique temporary file and atomic replace, without a direct-copy fallback. The
   original survives simulated rename/copy/disk failures, observed external changes,
   and process interruption. Live sidecars reject writes; the 90% item-count shrink
   guard remains. Implementation: `Corpus.sync`.

4. **Messaging sources were opened writable/checkpointed.** iMessage and WhatsApp
   SQLite parsers use read-only connections and close them reliably. They fail on a
   missing input and do not ignore WAL. Consistent SQLite backup guidance replaces
   copying live database files. Implementation: `engine/parsers/exports.py`.

## Medium severity: resolved

5. **Private outputs could be committed or exposed through misunderstood AI privacy.**
   Ignore rules cover private output folders, databases, sidecars, scratch files and
   common secrets. Skills write to `private/` and treat messages/exports as untrusted
   data. Documentation distinguishes local plaintext storage from cloud AI processing.
   The engine has no network calls. This does not promise protection from force-add,
   synced folders, compromised OS accounts, or user-authorized sharing.

6. **Record loss through deduplication and partial writes.** Account-scoped framed
   SHA-256 IDs and full-content variants retain records that share an export-generated
   ID, including same-timestamp Meta messages and different rating/metadata values.
   Repeated imports are idempotent. Delta mode retains old/equal-time arrivals. Items,
   contacts, search rows and watermarks roll back together. Migration preserves row
   IDs/FTS on the private working copy. Counts include retained variants; differing
   versions are evidence, not proof of separate real-world messages.

7. **Country and sender assumptions could merge people or misattribute voice.**
   National phone numbers now stay national. Explicit one-step `--contact-aliases`
   mappings can target known canonical/legacy handles without rewriting history.
   Meta conversations use stable folder identities and scoped group/person handles;
   Slack uses member/channel identifiers; WhatsApp SQLite prefers stable JIDs.
   Gmail matches parsed addresses, Twitter DMs use numeric account IDs, and retweets
   are excluded from original-voice samples. Unknown identity remains explicit.

8. **Parser input could exhaust memory or silently produce empty/incomplete results.**
   CLI preflight rejects special files/symlinks and caps tree size and total bytes.
   Whole documents/mbox messages, text lines and item counts have limits. Twitter
   dispatch no longer buffers records by source. Invalid CSV mappings, typed fields,
   nonfinite numerics and empty recognized sources fail before publication. Results
   report missing timestamps/unknown direction. Tests cover every CLI kind plus
   malformed and over-budget inputs. Unknown layouts are not inferred.

9. **Date/layout defects and aggressive cross-source suppression.** WhatsApp supports
   explicit day/month order, 24-hour seconds, multiline bodies and system notices.
   Google Voice and ISO date parsing retain timezone meaning. Missing evidence cannot
   prove a cross-source duplicate; suppression remains opt-in with a five-minute
   window and full normalized body/contact/direction matching. It is a heuristic.

10. **Opaque presentation runtime and unverified offline behavior.** The 125-slide
    content and fonts are retained, but the embedded React/component loader, iframe
    messaging and remote-resource fallbacks are removed. A small hashed script handles
    navigation; CSP denies network connections. Automated browser checks cover all
    slides, overflow, keyboard/list navigation, URL state, desktop/mobile fit, browser
    errors, offline requests and exactly 125 printed PDF pages. Font licenses are
    retained in `docs/licenses/`. Node dependencies are development-only and pinned.

## Verification

- Python regression suite: **54 tests**, including one contract test exercising all
  **17 CLI kinds twice**, plus a 10,000-record repeat-ingest case.
- Compilation and diff whitespace checks.
- Offline Chromium verification of all 125 slides and 125-page PDF output.
- GitHub Actions matrix: Python 3.11 and 3.14 on Linux, macOS and Windows, plus the
  browser job. The merge is gated operationally on successful runs; no admin bypass.
- Development dependency audit: no reported npm vulnerabilities at review time.

Commands, compatibility decisions, and the exact scope of the tests are in
[VERIFICATION.md](VERIFICATION.md). CI run results and merge status are recorded in
GitHub and the owner's existing tracker rather than duplicated as a competing backlog.

## Limits that cannot be inferred away

Previously discarded/truncated content requires original exports. Country codes,
unknown identities, and historical variants cannot be guessed safely: supply explicit
aliases or rebuild into a new database from retained exports. No historical corpus was
modified during this review. Back up before migration or bulk import.

Only local storage supporting atomic replace/exclusive create is supported for writes.
Third-party concurrent writers and arbitrary network/FUSE mounts are unsupported and
must not be worked around with unsafe copy fallbacks. Windows ACL policy remains the
owner's filesystem boundary; killed processes require inspected stale-lock recovery.
Input limits are not a sandbox for hostile native SQLite files or OS compromise.
Provider export changes and cloud AI behavior remain external boundaries, with
empty-result failures, diagnostics and coverage review to detect gaps.

The security skill provides no framework-specific checklist for this stdlib-only
Python CLI. The review therefore uses repository evidence, synthetic regression tests,
and the documented [Python SQLite APIs](https://docs.python.org/3/library/sqlite3.html)
and [SQLite backup API](https://www.sqlite.org/backup.html). Frontend guidance was
applied to the standalone deck. These checks are not a guarantee of absence of defects.

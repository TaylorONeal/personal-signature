# Security and reliability review

Reviewed 2026-09-10. Scope: Python engine, parsers, public defaults, agent playbooks,
privacy documentation, and a static inspection of the presentation bundle. This is
a local toolkit, not an email-signature editor or hosted service. All test data is
synthetic. No personal corpus, credentials, or pasted personal details were imported.

The main risks were local disclosure and silent database corruption, rather than a
network attack surface. The changes below are implemented locally. No critical
remote-execution vulnerability was demonstrated. This is not a comprehensive audit
of SQLite itself, downstream AI providers, or bundled presentation dependencies.

## High severity, fixed

1. **Shared scratch storage could mix or overwrite separate corpora.** Original
   `engine/corpus.py` selected a predictable shared directory and basename; copies
   were not private or isolated. Writers now use unique private directories, 0600
   database files, exclusive per-store locks, and cleanup on success/error.
   Evidence: `engine/corpus.py:51`; isolation, permissions, and writer-conflict tests.

2. **Queries could overwrite newer data.** Original query helpers opened the writable
   Corpus path and synced a stale copy on close. Query and coverage now use escaped
   read-only SQLite URIs, do not create missing stores, and cannot publish a copy.
   Evidence: `engine/corpus.py:18`, `engine/query.py:87`, `engine/coverage.py:34`;
   concurrent reader/writer, missing-store, and byte-preservation tests.

3. **Failed atomic publish fell back to overwriting the original.** The old sync
   fallback copied directly over the destination after a rename error. Publish now
   uses a unique same-directory temporary file, flushes it, and atomically replaces
   the original or raises. Observed external changes and live sidecars reject writes.
   The existing 90% item-count shrink guard remains. Evidence: `engine/corpus.py:100`;
   simulated rename failure, external change, rollback, and shrink tests.

4. **Source parsers opened private messaging databases writable.** iMessage and
   WhatsApp attempted checkpointing before falling back to reads that ignored WAL.
   They now open read-only, fail on missing sources, and close connections even on
   iteration errors. Consistent backups include committed WAL data. Evidence:
   `engine/parsers/exports.py:110` and `parse_whatsapp_ios`; synthetic source byte
   preservation, missing-file, and WAL tests.

## Medium severity, fixed or bounded

5. **Accidental disclosure protections were incomplete.** Ignored generated private
   outputs, alternate SQLite stores, sidecars, scratch/lock files, and common secret
   files. Profile skills now write under `private/`. Documentation distinguishes
   plaintext local storage from cloud AI processing, and treats export content as
   untrusted data. Verified ignore rules against representative private filenames.
   These rules do not prevent force-add, screenshots, synced folders, or OS access.

6. **Dedup could silently discard different items or accounts.** New framed SHA-256
   IDs include account and full identifying content instead of a 300-character body
   prefix. Version-2 migration preserves SQLite row IDs and FTS, on the working copy.
   Delta mode retains older/equal-timestamp arrivals. Both ingest paths use savepoint
   rollback for items, contacts, FTS, and watermarks. Evidence: `engine/corpus.py:133`,
   `engine/corpus.py:213`, `engine/corpus.py:284`; migration/FTS, account, content,
   delimiter, late-arrival, and failed-generator tests.

7. **Sender attribution could be wrong.** Gmail used substring matching; now it
   compares parsed email addresses. CLI now reads identity.json and requires identity
   for relevant sources, with explicit overrides. Twitter requires a numeric account
   ID for DMs; Slack uses member IDs. Removed personal CLI examples. International
   phone numbers are no longer truncated, and digit-bearing usernames stay intact.

8. **Invalid CLI/input handling and parser defects.** Validate kinds, paths, CSV
   mappings/buckets, and query sample limits before opening a writer. Added `--db` and
   `--identity`. Fixed mbox References returning a list, CSV BOM headers, Twitter DM
   ISO dates, and several unclosed files. Malformed message JSON fails rather than
   reporting a successful partial import. Optional metadata and unrecognized HTML
   layouts still require coverage review.

9. **Cross-source suppression was overly aggressive.** Missing timestamps no longer
   prove duplication. It compares full normalized bodies and requires contacts,
   using a five-minute window instead of 36 hours. This remains an explicit opt-in
   heuristic; it is not an identity proof and is not enabled by default.

## Validation

- `python3 -m unittest discover -s tests -v`: 33 tests passed on Python 3.9.6/macOS.
- `python3 -m compileall -q engine tests`: passed.
- `git diff --check`: passed.
- Plugin/identity JSON parsing and representative git-ignore checks: passed.
- No production data used; no network service or frontend build exists in this repo.

Python's documented read-only URI and backup APIs underpin the storage changes:
[Python sqlite3](https://docs.python.org/3/library/sqlite3.html),
[SQLite backup API](https://www.sqlite.org/backup.html).

## Compatibility and remaining work

- **Back up before migration.** Previously lost or truncated data cannot be recovered
  from hashes; retain raw exports. Changed international normalization can create new
  contact keys when re-ingesting old, already-truncated contacts; reconciliation is
  not automatic. Legacy 10-digit national phone normalization still assumes +1;
  use explicit international numbers pending a country-aware identity migration.
- **Parser coverage is not exhaustive.** All source implementations were read, but
  only representative fixtures are automated. Locale/date variations, synthetic
  Instagram/Facebook IDs at identical timestamps, group-contact identity, optional
  metadata, and changed export layouts need broader versioned fixtures and diagnostics.
- **Large-input limits remain.** Streaming ingest no longer buffers every row, but
  some export parsers and Twitter dispatch load whole documents. No archive extractor,
  hostile-SQLite sandbox, or per-parser resource quotas are implemented.
- **Platform testing remains.** Windows ACLs, network/FUSE filesystems, forced process
  termination, and large-corpus performance are not verified here. Concurrent writes
  through external SQLite clients are unsupported. Stale locks require inspected
  recovery; killed processes may leave private scratch data.
- **Deck verification remains separate.** `docs/deck.html` is an existing bundled
  browser artifact with embedded React/runtime code and iframe messaging. Static
  inspection is not an independent dependency audit, offline network test, or browser
  regression test. Its presentation claims may predate the new delta/storage behavior.
- No deployment, push, or GitHub issue publication was performed. Release status and
  remaining work are tracked in the owner's existing canonical improvement backlog;
  this document is supporting evidence, not a competing backlog.

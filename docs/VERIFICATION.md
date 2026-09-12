# Verification and compatibility

The September 12 follow-up closes the actionable items from the first security pass.
Tests use synthetic records and temporary databases; no real corpus is needed.

## Engine checks

`python -m unittest discover -s tests -v` covers:

- A recognized fixture for **all 17 CLI kinds**, initial ingest and repeated delta ingest.
- Source/account IDs, identical timestamp/thread-title collisions, rating/metadata
  variants, explicit contact aliases, national/international phones, and group identity.
- Missing timestamps, malformed rows, CSV mapping errors, empty-source rejection,
  byte/document/line/tree/item budgets, and symlink rejection.
- Private scratch files, read-only snapshots, WAL-backed source data, future-schema
  rejection, failed-copy/rename recovery, external modifications, shrink guard,
  savepoint rollback, process interruption, and 10,000-record repeated ingestion.
- Sender attribution, WhatsApp day/month order and system notices, source-file
  byte preservation, and excluding retweets from original-voice samples.

GitHub Actions runs this suite on Linux, macOS, and Windows with Python 3.11 and 3.14.
Dependencies for the Python engine remain standard-library only. Use a maintained
Python runtime with SQLite FTS5 and JSON support. Older local Python 3.9 checks are
compatibility evidence, not a recommendation to use an unsupported runtime.

## Deck checks

The deck retains all 125 slides and embedded fonts, with one small inline navigation
script. The previous React/component loader, iframe messaging, remote-resource
fallbacks, and bundled third-party JavaScript are removed. Its CSP permits only the
hashed navigation script, inline presentation styles, and embedded fonts/images;
network connections, forms, and base-URL changes are denied.

The optional development-only browser dependencies are pinned in package-lock.json:

```sh
npm ci --ignore-scripts
npx playwright install chromium
npm run test:deck
```

The browser check loads the deck with networking offline, checks every slide for
layout overflow, desktop/mobile fit, keyboard and slide-list navigation, URL state,
print layout, and exactly 125 PDF pages. It fails on remote requests or browser errors.
It runs in CI as well. After editing the inline script, run
`python scripts/update_deck_csp.py` to refresh its hash; the browser check verifies it.

## Deliberate support boundaries

- Unknown export layouts/locales cannot be inferred reliably. Empty imports fail by
  default; missing timestamp/direction counts are printed. Review coverage. Set the
  WhatsApp `--date-order` explicitly for your export (default is `mdy` for compatibility).
- National numbers stay national. `--contact-aliases private/contact-aliases.json`
  supplies explicit country/account-specific mappings, e.g.
  `{"5551234567": "+15551234567"}`. The mapping applies once, is not recursive, and
  never rewrites existing history. It can target an existing legacy handle to retain
  idempotence. Rebuild from retained exports into a new DB for broad identity corrections;
  never guess a lost country code or silently merge historical people.
- Parser corrections can preserve an additional variant of an old record when its
  thread/contact/metadata has changed. Variants remain searchable and repeated imports
  are idempotent. Previously discarded records require re-ingestion from raw exports.
- Input limits bound ordinary resource use; they are not a sandbox for malicious
  SQLite binaries, native-library vulnerabilities, or files changed by another local
  process during parsing. Use authorized exports and a patched runtime.
- Only local filesystems with exclusive-create and atomic-replace semantics are
  supported for writes. Failed storage operations preserve the original. Network/FUSE
  mounts and simultaneous third-party writers are unsupported, not silently bypassed.
- Windows protects files through the parent directory's ACLs; POSIX mode bits do not
  provide Windows access control. Use a private OS account and directory. Tests verify
  Windows functional behavior, not enterprise/custom ACL policy.
- Abrupt termination can leave a private scratch directory and stale lock. The
  interruption test verifies original-data preservation; inspected recovery is
  documented in SECURITY.md. There is no automatic stale-lock deletion.
- Source acquisition and cloud AI/provider behavior remain external trust boundaries;
  the engine does not enter credentials, extract archives, or upload personal data.

Sender parsing uses a conservative single-mailbox extraction across Python versions; ambiguous headers are unclassified rather than matched against email-like display names.

# Architecture

## Why this shape
The hard problems in a personal-data system are at the edges, not the middle:
- **Acquisition is fragile** (every platform's export UI differs, changes, and gates on auth) and **slow** (async, hours to days).
- **Synthesis is generative** (profile/analysis) and benefits from being *separate* from ingestion so it can re-run cheaply.
- **The middle — a clean store — is stable.** So we make the store the contract and let everything else be independent and replaceable.

Result: a four-stage pipeline where stages communicate ONLY through the local DB. Any stage runs on whatever the previous stage produced. A user with 2 sources and a user with 15 run the same code. (Rendered version of this diagram: [`architecture.svg`](architecture.svg), embedded in the README.)

```
            corpus-acquire        corpus-collect
            (request exports)      (watch email, download)
                   │                      │
                   └──────────┬───────────┘
                              ▼
                         exports/*           ← raw files (kept forever)
                              │
                        corpus-ingest         ← parsers → Item dicts → Corpus.ingest()
                              ▼
                          corpus.db           ← items / contacts / sources  (the contract)
                              │
                 ┌────────────┴────────────┐
                 ▼                          ▼
           corpus-profile             corpus-analyze
        (fast, deterministic)      (heavy, generative, on-demand)
```

## The data model
Three tables. **items** is the spine — one row per atomic thing (a message, post, like, ride, review). Every item has a **bucket**: `communication` | `published` | `signal_in`. **contacts** are the other parties (deduped by normalized handle, with optional relationship/status labels). **sources** is a hint registry; sources auto-register on first ingest.

Dedup is by source, account, and `external_id` when the platform gives one, else a content hash of `(source, account, direction, ts, contact, thread_id, title, body, url)`. Re-ingest is therefore idempotent. Cross-source dedup (e.g. an SMS that also shows in Google Voice) collapses on `(direction, contact, normalized-body)` within a time window.

**Initial vs delta runs:** every ingest records a per-source timestamp watermark. `--mode initial` (the default) parses everything and relies on dedup; `--mode delta` scans all supplied records and deduplicates by stable ID; watermarks are informational, so late arrivals are not lost.

## The Item contract (how to add any source)
A parser is a generator yielding plain dicts. Required: `bucket`, `source`, `direction`. Optional but useful:
```
ts (ISO-8601, sorts lexicographically), ts_raw, external_id,
contact ({"name","handle"} or a bare handle string), thread_id,
title, body, url, rating, lat, lon, meta (dict for source-specific fields)
```
Hand the generator to `Corpus.ingest(source, items, dedupe_against=[...])`. That's the entire extension surface — adding TikTok or LinkedIn is one function.

`identity.json` is how parsers decide `direction`: if the sender matches one of the user's handles, it's `out`/`sent`/`posted`, else `in`/`received`.

## Operational invariants (learned the hard way)
- **Never let a silent copy/restore failure precede a write.** The `Corpus` working-copy step fails loudly; `sync()` refuses to shrink the store below 90% (`CORPUS_ALLOW_SHRINK=1` to override). Back up before bulk runs regardless.
- **SQLite needs a real filesystem.** Working copies are private and temporary. Stores require atomic rename and exclusive file creation; unsupported mounts fail closed. Use a local filesystem.
- **Stream large archives.** Extract only the parse-relevant entries (message JSON, not media).
- **Coverage-first.** `coverage.py` is the contract between "what exists" and "what to claim." Profile/analyze read it and scope themselves.

## Design choices a re-implementer should keep
- One flat `items` table over per-source tables: lets profile/analyze be source-agnostic and makes partial coverage a non-event.
- Buckets over free-form tags: three is enough to drive the three synthesis dimensions (relationships, voice, interests) and keeps queries simple.
- Skills are thin; the engine is the substance. The skills encode *judgment* (which export settings, which traps, how to analyze honestly); the engine encodes *mechanism*.

## Storage lifecycle and failure handling

Writers reserve `<db>.lock` exclusively, create a mode-0700 temporary directory,
and create a mode-0600 working database. Existing stores are copied with SQLite's
backup API. Schema/ID migration happens only on this working copy. Each ingest is
one savepoint: items, contacts, search rows, and watermarks roll back together.
Context-manager exceptions discard the working session. Successful close publishes
a mode-0600 same-directory temporary file using atomic replace. Rename failure
never falls back to truncating the original. The 90% item-count shrink guard remains.
Readers take private SQLite snapshots using escaped `mode=ro` source URIs, then release the source file. They query their snapshot read-only and never initialize schemas or publish copies. This permits writer replacement while readers are active on Windows.

Only one toolkit writer may operate per store. External writers are unsupported:
metadata change detection and sidecar checks reject observed external changes, but
are not a distributed locking protocol. Crash recovery and privacy limits are in
[SECURITY.md](../SECURITY.md). A lock left by a crash is never automatically removed.

The current cross-source suppression is opt-in and heuristic: exact normalized
full body, direction, contact, and a five-minute timestamp window. Missing timestamps
or contacts do not establish a duplicate. Inspect counts before enabling it.

## Follow-up integrity and input rules

Source IDs are claims, not proof of uniqueness. When a matching ID has different
content, the engine retains a deterministic variant using a hash of the full
comparison payload (including ratings, location and metadata). Re-ingest skips exact
matches. No existing records are deleted. Phone normalization never invents a country;
explicit one-step contact aliases can map national handles to known canonical handles.
Parser corrections can create additional historical variants; see VERIFICATION.md.

The CLI inspects input type/tree/bytes before opening a writer and rejects an empty
recognized result by default. Whole-document reads, streamed lines and item counts
are bounded. Twitter's mixed-source records stream through one ingest run rather than
being buffered by source. Watermarks are informational; item IDs decide duplicates.

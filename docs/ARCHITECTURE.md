# Architecture

## Why this shape
The hard problems in a personal-data system are at the edges, not the middle:
- **Acquisition is fragile** (every platform's export UI differs, changes, and gates on auth) and **slow** (async, hours to days).
- **Synthesis is generative** (profile/analysis) and benefits from being *separate* from ingestion so it can re-run cheaply.
- **The middle — a clean store — is stable.** So we make the store the contract and let everything else be independent and replaceable.

Result: a four-stage pipeline where stages communicate ONLY through the local DB. Any stage runs on whatever the previous stage produced. A user with 2 sources and a user with 15 run the same code.

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

Dedup is by `external_id` when the platform gives one, else a content hash of `(source, direction, ts, contact, body[:300])`. Re-ingest is therefore idempotent. Cross-source dedup (e.g. an SMS that also shows in Google Voice) collapses on `(direction, contact, normalized-body)` within a time window.

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
- **SQLite needs a real filesystem.** On FUSE/network mounts, operate on a local working copy (`CORPUS_WORK` on ext4, not tmpfs) and sync bytes back.
- **Stream large archives.** Extract only the parse-relevant entries (message JSON, not media). 
- **Coverage-first.** `coverage.py` is the contract between "what exists" and "what to claim." Profile/analyze read it and scope themselves.

## Design choices a re-implementer should keep
- One flat `items` table over per-source tables: lets profile/analyze be source-agnostic and makes partial coverage a non-event.
- Buckets over free-form tags: three is enough to drive the three synthesis dimensions (relationships, voice, interests) and keeps queries simple.
- Skills are thin; the engine is the substance. The skills encode *judgment* (which export settings, which traps, how to analyze honestly); the engine encodes *mechanism*.

---
name: corpus-ingest
description: Parse whatever export files are present and load them into the unified local corpus database. Use when the user has dropped data exports in the exports/ folder and wants to "ingest", "load my data", "build the corpus", or after corpus-collect pulls in a new file. Auto-detects file types, routes each to the right parser, dedupes, and prints a coverage report. Tolerant of missing sources - runs on whatever exists.
---

# corpus-ingest

Goal: get the files in `exports/` into `corpus.db` cleanly, idempotently, and partial-source-tolerant. Re-running is always safe (content/external-id hashing dedupes).

## How to run
The engine lives in `engine/`. Point it at the DB (default `corpus.db` at project root) and your `identity.json`.

1. **Detect** what's in `exports/` and map each to a parser kind:
   | file / folder | kind |
   |---|---|
   | `chat.db` | imessage |
   | `*.mbox` | mbox (gmail) |
   | `**/messages/inbox/**` | instagram |
   | `**/messages/**/message_*.json` (FB layout) | facebook |
   | `data/tweets.js` (or twitter archive) | twitter |
   | `Google Chat/Groups/*/messages.json` | google_chat |
   | `Voice/Calls/*.html` | googlevoice |
   | `_chat.txt` | whatsapp |
   | Slack export dir | slack |
   | bookmarks `*.html` | bookmarks |
   | Spotify/Netflix/Reddit/Yelp CSV/HTML | csv / table parsers |

2. **Ingest** each via `python engine/run_ingest.py <kind> <path> --me <identity>`. For large local DBs (iMessage), the engine uses a fast bulk path. Pass `--dedupe-against imessage` for SMS/Google Voice so text-forwarding overlap collapses.

3. **Report** coverage: `python engine/coverage.py`.

## Critical operational notes (hard-won)
- **Back up before any bulk run:** `cp corpus.db corpus.db.bak-$(date +%F-%H%M)`. The engine also refuses to overwrite the store with a DB <90% its size (shrink-guard), and fails loudly if its working-copy step fails - but a backup is the real safety net. NEVER let a failed copy/restore proceed silently into a write.
- **Mounts:** SQLite can't run on FUSE/network mounts (no file locking). The engine operates on a local working copy in `$CORPUS_WORK` (use an ext4 path like `/var/tmp`, NOT a small tmpfs like `/dev/shm`) and syncs bytes back.
- **Big zips:** extract only what you need (e.g. for Instagram, only `messages/inbox/**/*.json`, skip the photo folders). Stream; don't unpack 600MB to a 4GB disk.
- **iMessage chat.db:** open with `sqlite3 file:chat.db?immutable=1` (no copy, ignores -wal). Decode `attributedBody` for modern macOS where `text` is NULL.

## The Item contract (for adding a source)
A parser is a generator yielding dicts; only `bucket`, `source`, `direction` are required:
`{bucket: signal_in|communication|published, source, direction, ts (ISO), ts_raw, external_id, contact ({name,handle} or str), thread_id, title, body, url, rating, lat, lon, meta (dict)}`.
Hand them to `Corpus.ingest(source, items, dedupe_against=[...])`. Adding a platform = one generator that yields this shape. Keep raw exports forever; they're the backup of last resort.

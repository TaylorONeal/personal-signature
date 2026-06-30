# personal-corpus

**Turn your scattered personal-data exports into one local, queryable picture of yourself — then let an AI build two things from it: a Content Profile and a Communication Signature.**

Everything runs locally. Your data never leaves your machine. You don't need every source — the whole system is built to work with whatever subset you have and to tell you, honestly, what's thin.

---

## The two goals (read this first)

This project exists to produce **two different portraits of a person**, from two different halves of their data. Keeping them distinct is the core design idea.

### 1. Content Profile — *what you consume and are into*
Built from the things you take **in**: music you save, videos you watch, articles you bookmark, books you read, restaurants you review, places you travel. It answers: *what are this person's tastes, interests, and obsessions? What do their inputs say about them?*
- Fed by the **`signal_in`** bucket (+ the topical side of `published`).
- Sources: Spotify, YouTube, Netflix, browser bookmarks, Yelp, food/orders, travel, podcasts.
- Output: an interest map, taste clusters, a mood/era signature, how interests evolved.

### 2. Communication Signature — *how you write and relate*
Built from the things you put **out** to people: your messages, emails, posts, reviews. It answers: *what is this person's voice, in each context? Who do they talk to, and how?*
- Fed by the **`communication`** bucket (relationships + private voice) and **`published`** (public voice).
- Sources: iMessage, Gmail, Instagram/Facebook DMs, Google Chat, Google Voice, WhatsApp, Slack, X, Yelp reviews, blogs.
- Output: a drop-in **voice block** (write-as-me), a register map (texting vs email vs public), and **relationship dynamics** (who initiates, sent:received balance, how bonds start and end).

> One person, two lenses. The Content Profile is your *inputs*; the Communication Signature is your *outputs*. They cross-check each other — and the interesting findings are usually where they agree or contradict.

---

## How it works

A four-stage pipeline on a shared local SQLite database. Stages talk **only** through the DB, so each one runs on whatever the previous stage produced. Stop at any stage; a missing source never breaks the next one.

```
  ACQUIRE  ─▶  COLLECT  ─▶  INGEST  ─▶  ┌─ PROFILE  ─▶  Content Profile
 (request)    (download)   (parse+store) │              Communication Signature
                              │          └─ ANALYZE  ─▶  deep, on-demand dives
                              ▼
                          corpus.db
                    items · contacts · sources
```

| Stage | Skill | What it does |
|---|---|---|
| 1a. Request | `corpus-acquire` | Drives each platform's export UI with the exact settings that keep exports small + parseable, and the traps that silently bloat them. |
| 1b. Collect | `corpus-collect` | Watches your email for "export ready" notices and files the downloads. Schedulable. |
| 2. Ingest | `corpus-ingest` | Auto-detects export files, parses each, loads to `corpus.db`. Idempotent, deduped, partial-source-tolerant. |
| 3. Profile | `corpus-profile` | Produces the **Content Profile** and the **Communication Signature** (fast, repeatable, coverage-aware). |
| 4. Analyze | `corpus-analyze` | On-demand deep dives — comm patterns, relationship dynamics, interest evolution, timeline. Cited, honest about gaps. |

Under all of them is the **engine** (`engine/`): one schema, the `Corpus` ingest library, a parser registry, and `coverage.py`.

---

## The data model → the two goals

Every item lands in exactly one **bucket**, and the bucket decides which goal it feeds:

| Bucket | Meaning | Feeds |
|---|---|---|
| `signal_in` | things you consumed (likes, plays, watches, bookmarks, ratings, visits) | **Content Profile** |
| `communication` | messages, both directions | **Communication Signature** (relationships + private voice) |
| `published` | your public/long-form output (posts, reviews, tweets, blog) | **both** (voice → Signature; topics → Content Profile) |

`items` is the spine (one row per atomic thing). `contacts` are the other parties (deduped by normalized handle, with optional relationship labels). `sources` is a hint registry; sources auto-register on first ingest.

**Identity:** `identity.json` is how parsers decide direction — if a message's sender matches one of your handles it's `out`/`sent`/`posted` (yours), else `in`/`received`. This is what makes the Communication Signature possible.

**Dedup:** by `external_id` when the platform provides one, else a content hash. Re-ingest is always safe. Cross-source dedup collapses the same message arriving on two platforms (e.g. an SMS that also shows in Google Voice).

---

## Quickstart

```bash
cp identity.example.json identity.json          # fill in your handles/emails
# 1. request exports for the sources you have  (skill: corpus-acquire)
# 2. drop the export files into exports/
python engine/run_ingest.py <kind> <path> --me "<you>"   # or run skill: corpus-ingest
python engine/coverage.py                        # what you have + what'd add most
# 3. build the two portraits  (skill: corpus-profile)
# 4. go deep on anything       (skill: corpus-analyze)
```

A typical first ingest:
```bash
python engine/run_ingest.py imessage   exports/chat.db
python engine/run_ingest.py mbox        exports/Sent.mbox --me you@gmail.com
python engine/run_ingest.py instagram   exports/instagram --me "Your Name"
python engine/run_ingest.py googlechat   exports/"Google Chat" --me you@gmail.com
python engine/run_ingest.py youtube      exports/.../watch-history.html
python engine/run_ingest.py csv          exports/liked.csv --source spotify_liked \
    --bucket signal_in --direction liked --map "title=Track Name,ts=Added At"
```

---

## Supported sources

| Source | kind | Bucket | Goal it feeds |
|---|---|---|---|
| iMessage (`chat.db`) | `imessage` | communication | Signature |
| Gmail (Sent mbox) | `mbox` | communication | Signature (long-form voice) |
| Instagram DMs | `instagram` | communication | Signature |
| Facebook Messenger | `facebook` | communication | Signature |
| Google Chat / Hangouts | `googlechat` | communication | Signature |
| Google Voice | `googlevoice` | communication | Signature |
| WhatsApp | `whatsapp` | communication | Signature |
| Slack | `slack` | communication | Signature |
| X / Twitter | `twitter` | published | both |
| Yelp reviews | `yelp` | published | both |
| Blog / long-form | `mbox`/`jsonl` | published | both |
| YouTube watch history | `youtube` | signal_in | Content Profile |
| Spotify liked | `csv` | signal_in | Content Profile |
| Netflix | `netflix` | signal_in | Content Profile |
| Browser bookmarks | `bookmarks` | signal_in | Content Profile |

Adding one is a single generator that yields the Item dict (see `docs/ARCHITECTURE.md`).

---

## Privacy & safety

- **Local only.** The DB never leaves your machine. No cloud, no telemetry.
- The AI is instructed to **never enter your passwords or 2FA** (it hands those steps to you), **never write sensitive personal/relationship/health detail into persistent memory**, and to keep deep analyses in a clearly-marked local folder.
- **Back up before bulk runs.** The engine fails loud on a bad copy and refuses to overwrite the store with a DB <90% its size (shrink-guard); a timestamped backup is still the real safety net.
- **Keep your raw exports.** They're the backup of last resort.

---

## Repo layout
```
engine/        schema.sql · corpus.py · parsers/ · run_ingest.py · coverage.py
skills/        corpus-acquire · corpus-collect · corpus-ingest · corpus-profile · corpus-analyze
docs/          ARCHITECTURE.md · architecture.svg
identity.example.json
.claude-plugin/ plugin.json · marketplace.json   (installable as a Claude plugin)
```

## Status
v0.1 — engine + 5 skills + 15 source parsers, smoke-tested. Roadmap: a Reddit parser, a `corpus-merge` for unifying a contact across platforms, and a richer Content Profile module. Contributions welcome.

MIT licensed.

# personal-corpus

**You are already being modeled. This builds that model *for you* — on your own machine, from your own data, pointed at your own goals.**

<p align="center"><img src="docs/signal.svg" alt="Reclaim the model: your behavior is the highest-signal data about you that exists. Right now it trains someone else's model of you — to sell to you. personal-corpus builds it for you instead: a Content Profile, a Communication Signature, and a queryable substrate for your own AI apps." width="860"></p>

Everything runs locally. Your data never leaves your machine. You don't need every source — the whole system is built to work with whatever subset you have, and to tell you, honestly, what's thin.

---

## Why this exists

Every platform you touch already keeps a model of you. Spotify models your taste, Google models your interests, Meta models your relationships, every ad network on the internet stitches fragments of your behavior into a profile. Those models are good. They're just not *yours* — their objective function is someone else's revenue. They predict what you'll click, what you'll buy, what keeps you scrolling. The model of you exists; it's simply aimed away from you.

**personal-corpus flips the ownership, not the technique.** The raw material those companies use — what you listen to, watch, save, write, and where you go — is sitting in the data exports you're legally entitled to download. This pulls it onto your own machine, into one clean local database, and builds the model on *your* side of the line, optimized for *your* objective:

- **Recommendations that serve you** — surfaced because they fit your taste, not because they maximize someone's engagement metric.
- **Insight you can't get from inside your own head** — how your relationships actually trend, how your interests have shifted over a decade, what you keep coming back to.
- **An AI that sounds like *you*** — a drop-in "voice block" built from your real sent messages, so any LLM can write and answer in your actual register instead of generic-assistant beige.
- **A substrate for whatever you build next** — `corpus.db` is a plain, queryable SQLite database. It's the personal-context layer that generic AI is missing. Point your own apps, agents, and scripts at it.

> Other companies do this to sell *to* you. There's no reason the same data can't produce far better recommendations, real self-knowledge, and a genuine digital voice — for you.

---

## Why your own data is the highest-signal data there is

Not all data about a person is equal. The exports this system uses are the densest, most honest signal that exists about you — denser than any survey, profile, or thing you'd write in a bio:

- **It's behavioral, not declared.** A questionnaire records what you *say* you like; your library, your watch history, and your sent folder record what you actually *did*. Revealed preference beats stated preference every time.
- **It's longitudinal.** Not a snapshot — years of it. That's what lets the system see eras, drift, and how you changed, instead of just where you are today.
- **It's in your own words.** Your sent messages and posts are the only large body of text that is unambiguously *your voice* — in real contexts, to real people, with real stakes. That's what makes a credible Communication Signature possible at all.
- **It's first-party and complete.** Ad networks reconstruct you from fragments seen through tracking. You have the whole thing, from the inside, with ground truth on who each contact is and which words are yours.
- **It's unperformed.** The 2 a.m. text, the playlist you'd never share, the search you'd never post — the realest signal is exactly the stuff that never makes it into a public persona.

Put differently: the most valuable training set about you in the world is one you can already download. This is the toolkit for using it yourself.

---

## What you get — two portraits and a substrate

The system produces **two different portraits of a person**, from two different halves of their data, plus the raw substrate underneath both. Keeping the two portraits distinct is the core design idea.

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

### 3. The corpus itself — *the personal-context layer for your own AI*
Underneath both portraits is `corpus.db` and `engine/query.py`: one normalized table of everything, with full-text search and ready-made read helpers. This is the part you build *on*. Want a recommender, a "what was I into in 2019" agent, a daily-journal summarizer, a write-as-me email drafter? They all read from the same local store.

> One person, two lenses, one substrate. The Content Profile is your *inputs*; the Communication Signature is your *outputs*. They cross-check each other — and the interesting findings are usually where they agree or contradict.

---

## How it works

A four-stage pipeline on a shared local SQLite database. Stages talk **only** through the DB, so each one runs on whatever the previous stage produced. Stop at any stage; a missing source never breaks the next one.

<p align="center"><img src="docs/architecture.svg" alt="The personal-corpus pipeline: Acquire requests exports, Collect watches your inbox and downloads them, Ingest parses and stores into corpus.db, which feeds a Content Profile, a Communication Signature, and your own apps. Every item lands in one of three buckets: signal_in, communication, or published." width="760"></p>

| Stage | Skill | What it does |
|---|---|---|
| 1a. Request | `corpus-acquire` | Drives each platform's export UI with the exact settings that keep exports small + parseable, and the traps that silently bloat them. |
| 1b. Collect | `corpus-collect` | Watches your email for "export ready" notices and files the downloads. Schedulable. |
| 2. Ingest | `corpus-ingest` | Auto-detects export files, parses each, loads to `corpus.db`. Idempotent, deduped, partial-source-tolerant. |
| 3. Profile | `corpus-profile` | Produces the **Content Profile** and the **Communication Signature** (fast, repeatable, coverage-aware). |
| 4. Analyze | `corpus-analyze` | On-demand deep dives — comm patterns, relationship dynamics, interest evolution, timeline. Cited, honest about gaps. |

Under all of them is the **engine** (`engine/`): one schema, the `Corpus` ingest library, a parser registry, `query.py` read helpers, and `coverage.py`.

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

Then explore the substrate directly:
```bash
python engine/query.py stats            # counts by bucket/source, date range
python engine/query.py top-contacts     # who you talk to most, sent:received
python engine/query.py voice-sample     # your own words, for a voice block
python engine/query.py interests        # what you point attention at
python engine/query.py search "<text>"  # full-text search across everything
```

The database lands at `corpus.db` in the repo root (git-ignored, never committed).

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

This only works because it's local. The whole premise — owning the model instead of renting it from a platform — falls apart the moment the data leaves your machine.

- **Local only.** The DB never leaves your machine. No cloud, no telemetry.
- The AI is instructed to **never enter your passwords or 2FA** (it hands those steps to you), **never write sensitive personal/relationship/health detail into persistent memory**, and to keep deep analyses in a clearly-marked local folder.
- **Back up before bulk runs.** The engine fails loud on a bad copy and refuses to overwrite the store with a DB <90% its size (shrink-guard); a timestamped backup is still the real safety net.
- **Keep your raw exports.** They're the backup of last resort.

---

## Repo layout
```
engine/        schema.sql · corpus.py · parsers/ · run_ingest.py · query.py · coverage.py
skills/        corpus-acquire · corpus-collect · corpus-ingest · corpus-profile · corpus-analyze
docs/          ARCHITECTURE.md · architecture.svg · signal.svg
identity.example.json
.claude-plugin/ plugin.json · marketplace.json   (installable as a Claude plugin)
```

## Status
v0.1 — engine + 5 skills + 15 source parsers, smoke-tested. Roadmap: a Reddit parser, a `corpus-merge` for unifying a contact across platforms, and a richer Content Profile module. Contributions welcome.

MIT licensed.

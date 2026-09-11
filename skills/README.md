# personal-corpus skills

The five skills in this folder drive the personal-corpus pipeline:

```
acquire -> collect -> ingest -> profile/analyze
```

The skills encode the *judgment* of the system (which export settings to use, which traps to avoid, how to analyze honestly); the engine in [`../engine/`](../engine/) encodes the *mechanism*. Full design rationale lives in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Two sets of information, two purposes

Every skill carries two distinct descriptions, and they are kept separate on purpose:

1. **When to use** (the trigger description). A short statement of what the skill covers and the situations that should invoke it. This is what an AI assistant reads to decide *whether* to load the skill, and it mirrors the `description` field in each skill's `SKILL.md` frontmatter.
2. **What it does** (the detailed description). The skill's goal, workflow, settings, and guardrails, condensed from the body of its `SKILL.md`. This is what tells you *what happens* once the skill runs.

Both sets are listed below for human readers. The same information in machine-readable form lives in [`skills.yaml`](skills.yaml), which tools and scripts can parse directly. The authoritative, full working instructions for each skill remain in its own `SKILL.md` file.

## The skills at a glance

| Stage | Skill | When to use it |
|---|---|---|
| 1a. Request | [`corpus-acquire`](corpus-acquire/SKILL.md) | The user wants to pull their data, request their exports, or start building a personal corpus. |
| 1b. Collect | [`corpus-collect`](corpus-collect/SKILL.md) | The user asks whether their exports are ready, wants to collect their data, or wants a recurring check. |
| 2. Ingest | [`corpus-ingest`](corpus-ingest/SKILL.md) | Export files are in `exports/` and the user wants to ingest, load their data, or build the corpus. |
| 3. Profile | [`corpus-profile`](corpus-profile/SKILL.md) | The user wants a profile, a voice signature, or a summary of what their data says about them. |
| 4. Analyze | [`corpus-analyze`](corpus-analyze/SKILL.md) | The user wants to go deeper, find patterns, or ask a specific question of their data. |

---

## corpus-acquire

**Stage 1a. Request** ([`SKILL.md`](corpus-acquire/SKILL.md))

**When to use.** Requests personal-data exports from each platform the user has (Google Takeout, Instagram, Facebook, X/Twitter, Reddit, Slack, Spotify) and copies local sources (iMessage, browser bookmarks). Use when the user wants to pull their data, request their exports, get their Instagram/Gmail/YouTube data, or start building a personal corpus. Drives each export UI with the exact settings that keep exports small and parseable, avoids the traps that silently bloat them, and hands password/2FA steps to the user.

**What it does.** Gets the user's data OUT of each platform and onto disk, configured so it is small and parseable. It first confirms an `exports/` folder and an `identity.json` (copied from `identity.example.json`) exist, so parsers later know which handles are the user's. It then works through a per-source playbook with the exact export settings and the traps that silently bloat archives:

- **Google Takeout** (`takeout.google.com/settings/takeout`): keep products separate so one giant product does not delay the rest. For Gmail Sent, turn OFF the "Include all messages in Mail" default and tick only the "Sent" label. Also covers Google Chat, Google Voice, and YouTube (keep comments, playlists, subscriptions, history; drop video files).
- **Instagram DMs** and **Facebook Messenger**: the customize screen has multiple sections, EACH with its own "Clear all"; clear every section, select **Messages** only, JSON format, All time, lower media quality.
- **X / Twitter**: full archive from Settings (takes ~24h; one archive per handle).
- **Reddit**: GDPR export at `reddit.com/settings/data-request` (CSVs of posts, comments, saved).
- **Slack**: workspace export (admin) or per-DM.
- **Spotify**: fastest via `exportify` (instant CSV of liked songs and playlists), or the official download.
- **Local sources** need no request: copy iMessage's `~/Library/Messages/chat.db` and a browser-bookmarks HTML export into `exports/`.

Hard rule: it never enters the user's password, 2FA code, or payment info; it drives the UI up to the auth step and hands off. Exports generate asynchronously (minutes to ~24h), so it fires them all up front, tells the user each rough ETA, and records what was requested in `exports/_manifest.json` so `corpus-collect` knows what to watch for. Partial coverage is fine; the rest of the pipeline adapts.

## corpus-collect

**Stage 1b. Collect** ([`SKILL.md`](corpus-collect/SKILL.md))

**When to use.** Watches the user's email for export-ready notifications from Google, Meta/Instagram/Facebook, X, Reddit, Spotify, and Slack, then helps download each archive into the `exports/` folder and tracks what is still pending. Use when the user asks whether their exports are ready, wants to collect their data, asks if their Takeout finished, or wants a recurring check. Best run on a schedule (e.g. daily) after `corpus-acquire` fires the requests. Requires an email connector (e.g. Gmail) and runs locally.

**What it does.** The bridge between `corpus-acquire` and `corpus-ingest`, and the stage that keeps running after the first build: it turns "I requested exports" into "the files are on disk" without the user babysitting their inbox. It scans the connected mailbox for export-ready notifications (Google from `noreply-dmrc@google.com`, "Your Google data is ready"; Meta from `security@facebookmail.com`, "Your information is ready to download"; X, "Your X data is ready"; Reddit, "Your Reddit data request"; Spotify/Slack, "your data" / "export"), then surfaces what is ready with platform, date, and download link, verifying the link domain matches the platform and treating email links as untrusted. It helps download each archive (preferring to hand the user the link, or driving the browser with the user present for auth; never entering passwords or 2FA), files it into the correct subfolder (`exports/instagram/`, `exports/google_voice/`, `exports/twitter/`, etc.) with archives left zipped, and updates `exports/_manifest.json` with what has arrived and what is still pending. When a new archive lands it offers to run `corpus-ingest` right away, with `--mode delta` for sources already in the corpus.

On scheduled runs (daily is usually right) it reports only NEW arrivals, stays silent on no-ops, nudges about anything pending past its expected ETA, and flags urgently when a download link is about to lapse (links typically expire in ~4 days). Boundaries: read-only on email (never send, delete, or change settings); downloading a file requires explicit user confirmation of filename, source, and size; if a link or sender domain looks off, it stops and asks.

## corpus-ingest

**Stage 2. Ingest** ([`SKILL.md`](corpus-ingest/SKILL.md))

**When to use.** Parses whatever export files are present in `exports/` and loads them into the unified local corpus database. Use when the user has dropped data exports in the `exports/` folder and wants to ingest, load their data, or build the corpus, or after `corpus-collect` files a new archive. Auto-detects file types, routes each to the right parser, dedupes on re-runs, supports delta mode for ongoing scans, and prints a coverage report. Tolerant of missing sources: runs on whatever exists.

**What it does.** Gets the files in `exports/` into `corpus.db` cleanly, idempotently, and partial-source-tolerant; re-running is always safe because content/external-id hashing dedupes. The engine lives in `engine/`; the DB defaults to `corpus.db` at the project root, with identity from `identity.json`. It works in three steps:

1. **Detect.** Map each file or folder to a parser kind: `imessage` (`chat.db`), `mbox` (Gmail Sent), `gmailjson` (Gmail API threads JSON), `instagram`, `facebook`, `twitter` (`data/tweets.js`), `googlechat`, `googlevoice` (`Voice/Calls/*.html`), `whatsapp` (`_chat.txt`), `whatsapp_ios` (`ChatStorage.sqlite`), `slack`, `bookmarks` (`*.html`), `netflix`, `yelp`, plus generic `csv` and `jsonl` kinds that take `--source`/`--bucket`/`--direction`/`--map` for any tabular export (Spotify, Goodreads, Reddit CSVs).
2. **Ingest.** Initial runs use one command per source: `python engine/run_ingest.py <kind> <path> --me <identity>`, with `--dedupe-against imessage` for SMS-overlapping sources such as Google Voice. Ongoing scans re-run with `--mode delta`, which only adds items newer than the stored per-source watermark; a full re-run is also always safe thanks to dedup, with the same correctness guarantees.
3. **Report.** `python engine/coverage.py` shows what is in the corpus, which dimensions are thin, and which source would add the most next; it is shown after every ingest.

Critical operational notes: back up before any bulk run (`cp corpus.db corpus.db.bak-$(date +%F-%H%M)`); the engine refuses to overwrite the store with a DB under 90% of its original item count and fails loudly on a bad copy; the engine uses private working copies and requires atomic publish support; unsupported mounts fail closed; extract only what is needed from big zips; read a consistent iMessage SQLite backup in read-only mode and decode `attributedBody` on modern macOS. Adding a source is one generator that yields the Item contract (`bucket`, `source`, `direction` required) handed to `Corpus.ingest` (details in `docs/ARCHITECTURE.md`). Keep raw exports forever; they are the backup of last resort.

## corpus-profile

**Stage 3. Profile** ([`SKILL.md`](corpus-profile/SKILL.md))

**When to use.** Builds a one-page signature profile from the corpus: who the person is, how they write (a drop-in voice block), what they're into, their key relationships, and trends over time. Use when the user wants a profile, signature, voice signature, summary of themselves, or asks what their data says about them. Fast and repeatable; coverage-aware: states what's thin and never invents what isn't there.

**What it does.** Produces a tight, honest, one-page synthesis the user can actually use, plus a voice block they can paste into prompts; deterministic where possible, with every claim tracing to a query, not a vibe. Run order: coverage first (`python engine/coverage.py`), noting thin or missing dimensions up top so nothing reads as more complete than it is; then pull structured facts by querying the DB: identity arc (cities and time spans, life chapters), volume and trends (`v_monthly_volume`, peaks and dips by year and bucket), relationships (`v_top_contacts`, sent:received ratio, who initiates, durable vs ended bonds), interests (top domains and keywords from bookmarks, genres and mood from music, categories from reviews and orders, watch and search themes), and voice (per-register samples of the user's OWN words by context, starting from `python engine/query.py voice-sample`).

It writes two artifacts: `private/Signature-Profile.md`, a one-page profile with a one-line read, who-they-are-in-the-data, trends, relationships, voice summary, and coverage caveats, with non-obvious findings marked explicitly; and `private/voice-signature.md`, a drop-in system-prompt block ("Write as \<name\>: ...") plus a register map, tics/tells, do/don't, and light stats, with every trait backed by a verbatim line from the corpus. Principles: coverage-aware (with only IG + bookmarks you can still produce a real profile; just scope the claims), non-obvious over generic (surface cross-source patterns, not horoscope filler), honest (a register missing from the corpus is "pending", never fabricated), private (profile outputs stay local; no personal/relationship/health detail in cross-session memory), and repeatable (re-run anytime new sources land, noting what changed since the last profile).

## corpus-analyze

**Stage 4. Analyze** ([`SKILL.md`](corpus-analyze/SKILL.md))

**When to use.** Runs a deep, on-demand analysis over the corpus: communication patterns, relationship dynamics, interest evolution, life timeline, or open-ended what's-non-obvious-about-me. Use when the user wants to go deeper, analyze their relationships/communication/interests, find patterns, or asks a specific question of their data. Heavier and more generative than `corpus-profile`; every claim is cited to a query, and it is honest about what the data can't show.

**What it does.** Answers a real question of the data with rigor, not flattery: state the pattern, show the numbers, give the strongest alternative reading, and name what would confirm or kill it. Modules (pick what the user asks for):

- **Communication patterns:** per-relationship sent:received ratio, initiation rate (gap-based session starts), message-length asymmetry, late-night share, response cadence; compare relationship types (friend vs family vs partner) and look for inversions across types, which are the real findings.
- **Relationship dynamics:** the arc of a specific bond over time (volume, who-leads drift, how it started/ended); patterns only unless the user asks for specifics, since this can be sensitive.
- **Interest evolution:** how themes shift across years (bookmarks/music/reviews/history); formative layers vs current.
- **Timeline / life chapters:** cross-source events by period (moves, immersions, gaps), the rhythm underneath.
- **Open-ended "non-obvious":** scan for cross-source agreements and contradictions; report what a stranger couldn't guess.

Method for every module: compute, don't intuit (write the query, get the numbers, cite them inline); state the pattern plainly, then lead with the strongest counter-reading (what else could produce these numbers?); caveat the data (sample size, missing directions/sources, eras not captured; a claim resting on a thin slice is flagged, never laundered as a finding); and end with a falsifiable next step, one concrete experiment or query. Guardrails: don't over-pathologize; separate description from prescription; name patterns clearly, even uncomfortable ones, but as hypotheses about behavior, not verdicts about the person; keep sensitive analyses (relationships, health, psychology) in a local, clearly-marked folder and never persist them to cross-session memory; no specifics/names in pattern write-ups unless the user explicitly asks; and if the data genuinely can't answer the question, say so: "not enough signal" is a valid result.

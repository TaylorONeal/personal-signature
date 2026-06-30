---
name: corpus-profile
description: Build a one-page "signature profile" from the corpus - who the person is, how they write (a drop-in voice block), what they're into, their key relationships, and trends over time. Use when the user wants a "profile", "signature", "voice signature", "summary of me", or "what does my data say about me". Fast and repeatable. Coverage-aware - it states what's thin and never invents what isn't there.
---

# corpus-profile

Goal: a tight, honest, one-page synthesis the user can actually use (and a voice block they can paste into prompts). Deterministic where possible: every claim traces to a query, not a vibe.

## Run order
1. **Coverage first.** `python engine/coverage.py`. The profile only claims what the data supports; note thin/missing dimensions up top so nothing reads as more complete than it is.
2. **Pull the structured facts** (queries over the DB, not guesses):
   - Identity arc: cities/time spans (from travel/location/sources), life chapters.
   - Volume + trends: `v_monthly_volume`; peaks and dips by year and bucket.
   - Relationships: `v_top_contacts`; sent:received ratio, who initiates, durable vs ended bonds.
   - Interests: top domains/keywords from bookmarks; genres/mood from music; categories from reviews/orders; watch/search themes.
   - Voice: per-register samples of the user's OWN words (direction in sent/out/posted), by context (texting vs email vs public).
3. **Write two artifacts:**
   - `Signature-Profile.md` - one page: one-line read, who-they-are-in-the-data, trends, relationships, voice summary, coverage caveats. Mark non-obvious findings explicitly.
   - `voice-signature.md` - a drop-in system-prompt block ("Write as <name>: ...") plus register map, tics/tells, do/don't, and light stats. Back every trait with a verbatim line from the corpus.

## Principles
- **Coverage-aware:** with only IG + bookmarks, you can still produce a real profile - just scope the claims. Say "based on X and Y; Z pending."
- **Non-obvious over generic:** surface the cross-source pattern (e.g. "intensity-then-recovery rhythm shows up in both calendar and music"), not horoscope filler.
- **Honest:** if a register (e.g. long-form email) isn't in the corpus, say it's pending, don't fabricate it.
- **Privacy:** profile outputs can contain sensitive inference. Keep them local. Do NOT write personal/relationship/health detail into any cross-session memory.
- Re-run anytime new sources land; note what changed.

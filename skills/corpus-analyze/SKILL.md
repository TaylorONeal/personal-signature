---
name: corpus-analyze
description: "Runs a deep, on-demand analysis over the corpus: communication patterns, relationship dynamics, interest evolution, life timeline, or open-ended what's-non-obvious-about-me. Use when the user wants to go deeper, analyze their relationships/communication/interests, find patterns, or asks a specific question of their data. Heavier and more generative than corpus-profile; every claim is cited to a query, and it is honest about what the data can't show."
---

# corpus-analyze

Stage 4 of the pipeline (acquire → collect → ingest → profile/analyze).

Goal: answer a real question of the data with rigor, not flattery. This is the Popperian layer: state the pattern, show the numbers, give the strongest alternative reading, and name what would confirm or kill it.

## Modules (pick what the user asks for)

- **Communication patterns:** per-relationship sent:received ratio, initiation rate (gap-based session starts), message-length asymmetry, late-night share, response cadence. Compare relationship types (friend vs family vs partner). Look for inversions across types — those are the real findings.
- **Relationship dynamics:** arc of a specific bond over time (volume, who-leads drift, how it started/ended). Patterns only unless the user asks for specifics; this can be sensitive.
- **Interest evolution:** how themes shift across years (bookmarks/music/reviews/history). Formative layers vs current.
- **Timeline / life chapters:** cross-source events by period (moves, immersions, gaps), the rhythm underneath.
- **Open-ended "non-obvious":** scan for cross-source agreements and contradictions; report what a stranger couldn't guess.

## Method (every module)

1. **Compute, don't intuit.** Write the query, get the numbers, cite them inline.
2. **State the pattern plainly**, then **lead with the strongest counter-reading** (what else could produce these numbers?).
3. **Caveat the data:** sample size, missing directions/sources, eras not captured. If a claim rests on a thin slice, say so — don't launder a guess as a finding.
4. **Falsifiable next step:** "if X, this holds; check Y to confirm." Give one concrete experiment or query.

## Guardrails

- Don't over-pathologize. Separate description from prescription. Name patterns clearly, even uncomfortable ones, but as hypotheses about behavior, not verdicts about the person.
- Sensitive analyses (relationships, health, psychology) stay in a local, clearly-marked folder. Never persist them to cross-session memory.
- No specifics/names in pattern write-ups unless the user explicitly asks.
- If the data genuinely can't answer the question, say that. "Not enough signal" is a valid result.

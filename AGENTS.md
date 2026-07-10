# Agent notes for personal-corpus

Guidance for AI agents (and humans) working on this repo. The "Lessons learned" entries come from real mistakes — check your work against them before pushing.

## Repo shape

- `engine/` is the mechanism (schema, `Corpus` ingest library, parsers, `query.py`, `coverage.py`). `skills/` encode judgment (export-UI traps, honest analysis method). Keep that split: don't put mechanism in skills or judgment in the engine.
- Docs live in three places and must agree: `README.md` (user-facing), `docs/ARCHITECTURE.md` (design rationale), `skills/*/SKILL.md` (operational playbooks).

## Lessons learned

### Docs must be verified against the code, not each other
- The single source of truth for CLI kinds and flags is the dispatcher in `engine/run_ingest.py` — not the README, not the skills. We shipped docs saying kind `google_chat` when the CLI accepts `googlechat`; the error survived because docs were checked against other docs. Before documenting any kind, flag, or subcommand, grep it in `engine/run_ingest.py`, `engine/query.py`, or `engine/coverage.py`.
- Counted claims ("16 source parsers") go stale silently. When adding a parser, update: the README status line, the README supported-sources table, and the detect table in `skills/corpus-ingest/SKILL.md`.

### Skill files (SKILL.md)
- Frontmatter is exactly `name` + `description`. Descriptions: double-quoted single-line YAML scalars, third person, state both what the skill does and when to use it, ≤1024 chars. Unquoted multi-clause scalars with embedded quotes parse today but break easily — keep them quoted.
- Shared body structure: pipeline-stage line ("Stage N of the pipeline (acquire → collect → ingest → profile/analyze)"), a one-sentence goal, ordered workflow sections, guardrails, and an explicit handoff naming the next skill. Keep new skills in this shape.
- Cross-skill state lives in `exports/_manifest.json` (written by `corpus-acquire`, updated by `corpus-collect`). If a skill needs to leave state for another, extend that file rather than inventing a new one.
- Document both modes of the pipeline: the initial run AND the ongoing scan (`--mode delta`, scheduled collect). Delta mode existed in the engine for a long time with zero documentation — when adding engine capability, add it to the README and the relevant skill in the same change.

### Diagrams (docs/*.svg)
- SVGs are hand-authored and embedded in the README via `<img>`, so they must be self-contained (no external fonts/resources) and theme-aware. Pattern in use: CSS custom properties on `:root` with a `@media (prefers-color-scheme: dark)` override; all colors go through the variables, including arrowhead `<marker>` paths (give them a class — presentation attributes don't reliably support `var()`).
- Verify visually, in both schemes: render via headless Chromium (`/opt/pw-browsers` + `playwright-core` with `colorScheme: 'light' | 'dark'`) and look at the screenshots. The original diagrams were illegible on GitHub dark mode and no one noticed from the markup alone.

### Operational invariants (don't relax these)
- Never document or automate anything that enters passwords/2FA — skills hand auth steps to the user. Hard rule.
- `corpus.db` is git-ignored and local-only; profile/analysis outputs stay local and out of cross-session memory. Don't add examples that pipe corpus contents to external services.
- Back-up-before-bulk-run and the shrink-guard are load-bearing safety copy — keep them in any rewrite of ingest docs.

# Contributing

Use Python 3.9+ with SQLite FTS5. The engine has no third-party runtime dependencies.
Read AGENTS.md and docs/INDEX.md before changing code. Keep parser mechanisms in engine/
and agent judgment in skills/. Keep README, architecture, and relevant skills consistent.

Run:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q engine tests
git diff --check
```

Use synthetic fixtures only. Test malformed input, repeated imports, account separation,
and source-specific identity rules when adding parsers. Do not add credentials, raw
exports, personal profiles, or user-specific defaults. Use reserved example.com domains.
For security concerns, follow SECURITY.md. See docs/SECURITY_REVIEW.md for known gaps.

# Contributing

Use maintained Python 3.11+ with SQLite FTS5 and JSON support. The engine has no third-party runtime dependencies.
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

The source contract test exercises all 17 CLI kinds. Add a synthetic fixture there
when adding a kind, and add a focused regression for any fixed edge case. CI runs
Python 3.11/3.14 across Linux/macOS/Windows. Browser checks are optional locally but
run in CI; see docs/VERIFICATION.md. Runtime Python code must not depend on npm.

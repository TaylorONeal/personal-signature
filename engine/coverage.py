#!/usr/bin/env python3
"""coverage.py - what's in the corpus, and what would add the most.

The whole system is designed to work with ANY subset of sources. This reports what
you have, flags thin dimensions, and recommends the highest-value next source to add.
Usage: python coverage.py [db_path]
"""
import sys, os, sqlite3, json
from corpus import open_readonly

DB = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "corpus.db")

# Which dimension each bucket/source feeds, for the gap analysis.
DIMENSIONS = {
    "communication": "relationships + texting voice",
    "published": "public/long-form voice",
    "signal_in": "interests + consumption",
}
# Generic, high-leverage sources by dimension (suggested when a dimension is thin/absent).
SUGGESTIONS = {
    "communication": [("imessage", "macOS chat.db - usually the biggest single trove"),
                      ("google_chat", "Takeout - years of DMs if you used Hangouts/Chat"),
                      ("instagram_dm", "IG 'Download your information', Messages only"),
                      ("whatsapp", "per-chat export without media")],
    "published": [("gmail", "Takeout Mail -> Sent label -> mbox: your long-form voice"),
                  ("twitter", "X archive: public voice"),
                  ("reddit", "data request CSVs: comments/posts")],
    "signal_in": [("browser_bookmarks", "one HTML export: instant interest map"),
                  ("spotify_liked", "exportify CSV: taste + mood signature"),
                  ("youtube", "Takeout: watch/search history = interests")],
}


def main():
    if not os.path.exists(DB):
        print(f"No corpus DB at {DB}. Run ingest first."); return
    c = open_readonly(DB)
    total = c.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    print(f"# Corpus coverage  ({total:,} items)\n")

    have_buckets = {}
    print("## Sources")
    for b, s, n, self_n, mn, mx in c.execute(
        "SELECT bucket, source, COUNT(*) AS n, SUM(CASE WHEN direction IN('out','sent','posted') THEN 1 ELSE 0 END),"
        " MIN(ts), MAX(ts) FROM items GROUP BY bucket, source ORDER BY n DESC"):
        have_buckets.setdefault(b, 0)
        have_buckets[b] += n
        span = f"{str(mn)[:10]}..{str(mx)[:10]}" if mn else "no dates"
        print(f"  [{b:13}] {s:20} {n:>8,}  self={self_n or 0:>7,}  {span}")

    self_total = c.execute("SELECT COUNT(*) FROM items WHERE direction IN('out','sent','posted')").fetchone()[0]
    contacts = c.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
    print(f"\nself-authored: {self_total:,}   contacts: {contacts:,}")

    print("\n## Dimensions")
    for b, label in DIMENSIONS.items():
        n = have_buckets.get(b, 0)
        state = "MISSING" if n == 0 else ("thin" if n < 500 else "ok")
        print(f"  {label:32} {state:8} ({n:,} items)")

    print("\n## Recommended next sources (biggest marginal value)")
    recs = []
    have_sources = {r[0] for r in c.execute("SELECT DISTINCT source FROM items")}
    for b, label in DIMENSIONS.items():
        if have_buckets.get(b, 0) < 500:  # missing or thin -> suggest fillers
            for src, why in SUGGESTIONS[b]:
                if not any(src in hs for hs in have_sources):
                    recs.append(f"  + {src:18} ({label}): {why}")
    if recs:
        print("\n".join(recs[:6]))
    else:
        print("  Solid coverage across all three dimensions. Add more only for depth.")
    c.close()


if __name__ == "__main__":
    main()

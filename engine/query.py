#!/usr/bin/env python3
"""
query.py - read-side helpers for the corpus DB. Used by the content-profile and
voice-signature skills, and handy for ad hoc analysis.

CLI:
  python query.py stats
  python query.py top-contacts [N]
  python query.py top-sources
  python query.py monthly
  python query.py voice-sample [N]     # your sent + published text, for voice analysis
  python query.py interests [N]        # saved + published items, for the content profile
  python query.py search "<fts query>"
"""
import sys, os, json, re, collections, argparse
sys.path.insert(0, os.path.dirname(__file__))
from corpus import Corpus

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "corpus.db"))
STOP = set("the a an and or but if then of to in on for with at by from is are was were be been "
           "i you he she it we they me my your his her our their this that these those as so not no "
           "do does did have has had will would can could should just get got im ive dont thats "
           "re fwd hi hey hello thanks thank you on at pm am".split())


def _c():
    return Corpus(DB, readonly=True)


def stats(c):
    d = c.db
    return {
        "items": d.execute("SELECT COUNT(*) FROM items").fetchone()[0],
        "contacts": d.execute("SELECT COUNT(*) FROM contacts").fetchone()[0],
        "by_bucket": {r[0]: r[1] for r in d.execute("SELECT bucket,COUNT(*) FROM items GROUP BY bucket")},
        "by_source": {r[0]: r[1] for r in d.execute("SELECT source,COUNT(*) FROM items GROUP BY source")},
        "date_range": list(d.execute("SELECT MIN(ts),MAX(ts) FROM items WHERE ts IS NOT NULL").fetchone()),
    }


def top_contacts(c, n=20):
    return [dict(r) for r in c.db.execute(
        "SELECT display_name,relationship,total_items,sent,received,source_list,first_ts,last_ts "
        "FROM v_top_contacts LIMIT ?", (n,))]


def top_sources(c):
    return [dict(r) for r in c.db.execute("SELECT * FROM v_sources")]


def monthly(c):
    return [dict(r) for r in c.db.execute("SELECT * FROM v_monthly_volume")]


def voice_sample(c, n=500):
    """Your own words only: sent communications + published content."""
    return [dict(r) for r in c.db.execute(
        "SELECT source,ts,title,body FROM items "
        "WHERE direction IN ('out','sent','posted') AND body IS NOT NULL AND length(body)>3 "
        "ORDER BY ts DESC LIMIT ?", (n,))]


def interests(c, n=1000):
    """Saved + published: what you point attention at."""
    return [dict(r) for r in c.db.execute(
        "SELECT source,ts,title,body,url FROM items "
        "WHERE bucket IN ('signal_in','published') ORDER BY ts DESC LIMIT ?", (n,))]


def keyword_freq(rows, top=40):
    cnt = collections.Counter()
    for r in rows:
        text = ((r.get("title") or "") + " " + (r.get("body") or "")).lower()
        for w in re.findall(r"[a-z']{3,}", text):
            if w not in STOP:
                cnt[w] += 1
    return cnt.most_common(top)


def search(c, q, n=30):
    return [dict(r) for r in c.db.execute(
        "SELECT source,ts,title,substr(body,1,160) AS snippet FROM items "
        "WHERE rowid IN (SELECT rowid FROM items_fts WHERE items_fts MATCH ?) "
        "ORDER BY ts DESC LIMIT ?", (q, n))]


def main():
    ap = argparse.ArgumentParser(description="Read the local corpus without modifying it")
    ap.add_argument("command", nargs="?", default="stats", choices=["stats", "top-contacts", "top-sources", "monthly", "voice-sample", "interests", "search"])
    ap.add_argument("argument", nargs="?")
    ap.add_argument("--db", default=DB)
    a = ap.parse_args()
    n = None
    if a.command in {"top-contacts", "voice-sample", "interests"}:
        try:
            n = int(a.argument or {"top-contacts": 20, "voice-sample": 500, "interests": 1000}[a.command])
            if not 1 <= n <= 10000:
                raise ValueError()
        except ValueError:
            ap.error("Sample size must be between 1 and 10000")
    if a.command == "search" and not a.argument:
        ap.error("search requires a full-text query")
    with Corpus(a.db, readonly=True) as c:
        if a.command == "stats":
            result = stats(c)
        elif a.command == "top-contacts":
            result = top_contacts(c, n)
        elif a.command == "top-sources":
            result = top_sources(c)
        elif a.command == "monthly":
            result = monthly(c)
        elif a.command == "voice-sample":
            result = voice_sample(c, n)
        elif a.command == "interests":
            rows = interests(c, n)
            result = {"count": len(rows), "keywords": keyword_freq(rows)}
        else:
            result = search(c, a.argument)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

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
import sys, os, json, re, collections
sys.path.insert(0, os.path.dirname(__file__))
from corpus import Corpus

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "db", "corpus.db"))
STOP = set("the a an and or but if then of to in on for with at by from is are was were be been "
           "i you he she it we they me my your his her our their this that these those as so not no "
           "do does did have has had will would can could should just get got im ive dont thats "
           "re fwd hi hey hello thanks thank you on at pm am".split())


def _c():
    return Corpus(DB)


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
        "SELECT display_name,total_items,sent,received,source_list,first_ts,last_ts "
        "FROM v_top_contacts LIMIT ?", (n,))]


def top_sources(c):
    return [dict(r) for r in c.db.execute("SELECT * FROM v_top_sources")]


def monthly(c):
    return [dict(r) for r in c.db.execute("SELECT * FROM v_monthly_volume")]


def voice_sample(c, n=500):
    """Your own words only: sent communications + published content."""
    return [dict(r) for r in c.db.execute(
        "SELECT source,ts,title,body FROM items "
        "WHERE (direction IN ('sent','posted','reviewed') ) AND body IS NOT NULL AND length(body)>3 "
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


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    c = _c()
    if cmd == "stats":
        print(json.dumps(stats(c), indent=2))
    elif cmd == "top-contacts":
        print(json.dumps(top_contacts(c, int(arg or 20)), indent=2))
    elif cmd == "top-sources":
        print(json.dumps(top_sources(c), indent=2))
    elif cmd == "monthly":
        print(json.dumps(monthly(c), indent=2))
    elif cmd == "voice-sample":
        print(json.dumps(voice_sample(c, int(arg or 500)), indent=2))
    elif cmd == "interests":
        rows = interests(c, int(arg or 1000))
        print(json.dumps({"count": len(rows), "keywords": keyword_freq(rows)}, indent=2))
    elif cmd == "search":
        print(json.dumps(search(c, arg or ""), indent=2))
    else:
        print("unknown command:", cmd)
    c.close()

#!/usr/bin/env python3
"""
run_ingest.py - dispatch a parser against an export and load it into the corpus DB.

Examples:
  python run_ingest.py mbox      ~/exports/sent.mbox        --me you@example.com
  python run_ingest.py imessage  ~/exports/chat.db
  python run_ingest.py instagram ~/exports/instagram        --me "Your Name"
  python run_ingest.py twitter   ~/exports/twitter/data      --handle 1234567
  python run_ingest.py slack     ~/exports/slack_export      --workspace example --me U012EXAMPLE
  python run_ingest.py bookmarks ~/exports/bookmarks.html
  python run_ingest.py jsonl     ~/exports/spotify_liked.jsonl --source spotify_liked
  python run_ingest.py csv       ~/exports/goodreads.csv     --source goodreads --bucket signal_in \
        --direction liked --map "title=Title,rating=My Rating,ts=Date Added"
All commands accept --mode delta; stable IDs retain late arrivals while skipping duplicates.
"""
import sys, os, json, argparse, sqlite3
from contextlib import closing
from input_safety import inspect_input, json_document, text_lines
sys.path.insert(0, os.path.dirname(__file__))
from corpus import Corpus
from pathlib import Path
from parsers import exports as ex
from parsers import extra as ex2

DB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "corpus.db"))


def jsonl_items(path):
    with closing(text_lines(path)) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["mbox", "imessage", "instagram", "facebook", "twitter", "slack", "gmailjson", "whatsapp", "whatsapp_ios", "bookmarks", "googlevoice", "googlechat", "youtube", "netflix", "yelp", "jsonl", "csv"])
    ap.add_argument("path")
    ap.add_argument("--db", default=DB)
    ap.add_argument("--identity", default=os.path.join(os.path.dirname(DB), "identity.json"))
    ap.add_argument("--me", action="append", default=[])
    ap.add_argument("--handle")
    ap.add_argument("--workspace", default="")
    ap.add_argument("--account", default="")
    ap.add_argument("--contact-aliases", help="JSON mapping of raw handles to explicit canonical handles")
    ap.add_argument("--date-order", choices=["mdy", "dmy"], default="mdy", help="WhatsApp numeric date order")
    ap.add_argument("--thread", help="Stable chat identifier for WhatsApp text exports")
    ap.add_argument("--max-input-mb", type=int, default=1024)
    ap.add_argument("--max-items", type=int, default=1000000)
    ap.add_argument("--allow-empty", action="store_true", help="Permit an intentionally empty export")
    ap.add_argument("--source")
    ap.add_argument("--bucket")
    ap.add_argument("--direction")
    ap.add_argument("--map")
    ap.add_argument("--mode", default="initial", choices=["initial", "delta"])
    ap.add_argument("--dedupe-against", help="comma-separated sources to suppress cross-platform dupes, e.g. imessage")
    a = ap.parse_args()
    if a.max_input_mb < 1 or a.max_items < 1:
        ap.error("Input and item budgets must be positive")
    inspect_input(a.path, max_bytes=a.max_input_mb * 1024 * 1024)
    aliases = json_document(a.contact_aliases) if a.contact_aliases else None
    if not os.path.exists(a.path):
        ap.error("Input path does not exist")
    directory_kinds = {"instagram", "facebook", "twitter", "slack", "googlevoice", "googlechat", "netflix", "yelp"}
    if (a.kind in directory_kinds) != os.path.isdir(a.path):
        ap.error("This kind requires " + ("a directory" if a.kind in directory_kinds else "a file"))
    if a.kind == "csv" and not all((a.source, a.bucket, a.direction, a.map)):
        ap.error("csv requires --source, --bucket, --direction, and --map")
    if a.bucket and a.bucket not in {"communication", "published", "signal_in"}:
        ap.error("Invalid bucket")
    fmap = {}
    if a.map:
        try:
            fmap = dict(kv.split("=", 1) for kv in a.map.split(","))
        except ValueError:
            ap.error("--map must contain comma-separated field=column pairs")
        allowed = {"external_id", "ts", "ts_raw", "contact", "thread_id", "title", "body", "url", "rating", "lat", "lon"}
        if not set(fmap) <= allowed or not all(fmap.values()):
            ap.error("--map contains an unsupported field or empty column")
    if os.path.exists(a.identity):
        try:
            identity = json_document(a.identity)
            handles = identity.get("handles", {})
            key = {"googlechat": "google_chat", "googlevoice": "google_voice"}.get(a.kind, a.kind)
            value = identity.get("emails", []) if a.kind in {"mbox", "gmailjson"} else handles.get(key, [])
            if not a.me:
                a.me = [value] if isinstance(value, str) else value
            if not a.handle:
                a.handle = handles.get("twitter")
            if not isinstance(a.me, list) or not all(isinstance(x, str) and x.strip() for x in a.me):
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            ap.error("Invalid identity JSON; expected an object with emails and handles")
    if a.kind in {"mbox", "gmailjson", "instagram", "facebook", "googlechat", "whatsapp", "slack"} and not a.me:
        ap.error("Supply --me (or identity.json) to identify your own messages")
    if a.kind == "twitter" and os.path.exists(os.path.join(a.path, "direct-messages.js")) and (not isinstance(a.handle, str) or not a.handle.isdigit()):
        ap.error("Twitter DMs require --handle with the numeric account ID")
    against = a.dedupe_against.split(",") if a.dedupe_against else None

    with Corpus(a.db, contact_aliases=aliases, max_items=a.max_items) as c:
        k = a.kind
        if k == "mbox":
            src = a.source or "gmail"
            items = ex.parse_mbox(a.path, a.me, source=src, account=a.account)
            res = c.ingest(src, items, mode=a.mode, account=a.account)
        elif k == "imessage":
            res = c.ingest("imessage", ex.parse_imessage(a.path), mode=a.mode, account=a.account)
        elif k == "instagram":
            res = c.ingest("instagram_dm", ex.parse_instagram_dm(a.path, a.me[0] if a.me else ""), mode=a.mode, account=a.account)
        elif k == "facebook":
            res = c.ingest("facebook_msgr", ex.parse_facebook_messenger(a.path, a.me[0] if a.me else ""), mode=a.mode, account=a.account)
        elif k == "twitter":
            res = c.ingest("twitter", ex.parse_twitter_archive(a.path, a.handle or ""), mode=a.mode, account=a.account)
        elif k == "slack":
            res = c.ingest("slack", ex.parse_slack_export(a.path, a.account or a.workspace, a.me), mode=a.mode, account=a.account or a.workspace)
        elif k == "gmailjson":
            src = a.source or "gmail"
            items = ex.parse_gmail_threads_json(a.path, a.me, source=src, account=a.account)
            res = c.ingest(src, items, mode=a.mode, account=a.account)
        elif k == "whatsapp":
            items = ex.parse_whatsapp(a.path, a.me[0] if a.me else "", contact_hint=a.thread or Path(a.path).stem, date_order=a.date_order)
            res = c.ingest("whatsapp", items, mode=a.mode, account=a.account, dedupe_against=against)
        elif k == "whatsapp_ios":
            # ChatStorage.sqlite extracted from an iPhone backup
            res = c.ingest("whatsapp", ex.parse_whatsapp_ios(a.path, a.me[0] if a.me else "Me"),
                           mode=a.mode, account=a.account, dedupe_against=against)
        elif k == "bookmarks":
            res = c.ingest("browser_bookmarks", ex.parse_bookmarks_html(a.path), mode=a.mode, account=a.account)
        elif k == "googlevoice":
            # Google Voice predates Google Messages and is distinct from iMessage SMS; do NOT
            # dedupe against imessage unless explicitly asked.
            res = c.ingest("google_voice", ex.parse_google_voice(a.path, a.me[0] if a.me else "Me"),
                           mode=a.mode, account=a.account, dedupe_against=against)
        elif k == "googlechat":
            res = c.ingest("google_chat", ex2.parse_google_chat(a.path, a.me[0] if a.me else ""), mode=a.mode, account=a.account)
        elif k == "youtube":
            # watch-history.html; large -> bulk path
            res = c.bulk_ingest("youtube_watch", ex2.parse_youtube_watch(a.path), mode=a.mode, account=a.account)
        elif k == "netflix":
            res = c.ingest("netflix", ex2.parse_netflix(a.path), mode=a.mode, account=a.account)
        elif k == "yelp":
            res = c.ingest("yelp", ex2.parse_yelp(a.path), mode=a.mode, account=a.account)
        elif k == "jsonl":
            src = a.source or "unknown"
            res = c.ingest(src, jsonl_items(a.path), mode=a.mode, account=a.account, dedupe_against=against)
        elif k == "csv":
            items = ex.parse_csv(a.path, a.source, a.bucket, a.direction, fmap)
            res = c.ingest(a.source, items, mode=a.mode, account=a.account, dedupe_against=against)
        else:
            print(f"unknown kind: {k}"); sys.exit(1)

        if not a.allow_empty and res["added"] + res["skipped"] == 0:
            raise ValueError("No records recognized; check export layout and identity, or use --allow-empty for an intentionally empty source")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, TypeError, sqlite3.Error, RuntimeError) as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr)
        sys.exit(1)

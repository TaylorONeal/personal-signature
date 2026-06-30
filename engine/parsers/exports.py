"""
exports.py - format parsers. Each function yields Item dicts (see corpus.py).
Stdlib only. Robust to missing fields; skips rather than crashes on bad rows.
"""
import os, json, csv, glob, html, sqlite3, datetime, re, mailbox
from email.utils import parsedate_to_datetime, getaddresses


def _iso(dt):
    if dt is None:
        return None
    if isinstance(dt, (int, float)):
        try:
            return datetime.datetime.utcfromtimestamp(dt).isoformat()
        except Exception:
            return None
    return dt.replace(microsecond=0).isoformat() if isinstance(dt, datetime.datetime) else str(dt)


# ---------------- email (mbox from Takeout / Thunderbird / etc.) ----------------
def parse_mbox(path, my_addresses, source="gmail", account=""):
    me = {a.lower() for a in my_addresses}
    for msg in mailbox.mbox(path):
        try:
            frm = getaddresses(msg.get_all("from", []))
            tos = getaddresses(msg.get_all("to", []) + msg.get_all("cc", []))
            from_addr = (frm[0][1] if frm else "").lower()
            direction = "sent" if from_addr in me else "received"
            counterpart = tos[0] if direction == "sent" and tos else (frm[0] if frm else ("", ""))
            try:
                ts = _iso(parsedate_to_datetime(msg.get("date")))
            except Exception:
                ts = None
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True) or b""
                        body = body.decode(part.get_content_charset() or "utf-8", "ignore")
                        break
            else:
                pl = msg.get_payload(decode=True)
                body = pl.decode(msg.get_content_charset() or "utf-8", "ignore") if pl else ""
            yield {
                "bucket": "communication", "source": source, "source_account": account,
                "external_id": msg.get("Message-ID"), "direction": direction, "ts": ts,
                "ts_raw": msg.get("date"),
                "contact": {"name": counterpart[0], "handle": counterpart[1]},
                "thread_id": msg.get("In-Reply-To") or msg.get("References", "").split()[:1] or None,
                "title": msg.get("subject"), "body": body[:20000],
                "meta": {"to": [a for _, a in tos]},
            }
        except Exception:
            continue


# ---------------- Gmail search_threads JSON (from the connector, saved to a file) ----------------
def parse_gmail_threads_json(path, my_emails, source="gmail", account=""):
    me = {e.lower() for e in my_emails}
    data = json.load(open(path, encoding="utf-8"))
    for th in data.get("threads", []):
        for m in th.get("messages", []):
            sender = (m.get("sender") or "").lower()
            is_sent = any(e in sender for e in me) and "+cc@" not in sender
            tos = m.get("toRecipients") or []
            if is_sent:
                counterpart = tos[0] if tos else sender
                direction = "sent"
            else:
                counterpart = m.get("sender")
                direction = "received"
            body = html.unescape(m.get("snippet") or "")
            yield {
                "bucket": "communication", "source": source, "source_account": account,
                "external_id": m.get("id"), "direction": direction,
                "ts": m.get("date"), "ts_raw": m.get("date"),
                "contact": counterpart, "thread_id": th.get("id"),
                "title": m.get("subject"), "body": body,
                "meta": {"labels": m.get("labelIds"), "snippet_only": True},
            }


# ---------------- iMessage / SMS (Mac chat.db) ----------------
def _decode_attributedbody(data):
    """Extract plain text from a NSAttributedString 'streamtyped' blob (modern macOS
    stores message text here with a NULL text column). Heuristic, good enough for most."""
    if not data or b"NSString" not in data:
        return None
    try:
        s = data.split(b"NSString", 1)[1][5:]
        if not s:
            return None
        if s[0] == 0x81:                       # 0x81 => next 2 bytes are length (LE)
            length = int.from_bytes(s[1:3], "little"); s = s[3:]
        else:
            length = s[0]; s = s[1:]
        return s[:length].decode("utf-8", "ignore") or None
    except Exception:
        return None


def parse_imessage(chatdb_path):
    # Open read-write on a COPY (the skill copies chat.db first). ro+WAL opens fail on
    # some filesystems; rw lets SQLite merge the -wal cleanly. Never point this at the
    # live ~/Library/Messages/chat.db.
    # Prefer a normal rw open on a local copy (merges the -wal, freshest data). If the
    # filesystem blocks locking (e.g. FUSE mount), fall back to immutable=1 which reads
    # the file in place with no locking and no copy (ignores any -wal sidecar).
    try:
        con = sqlite3.connect(chatdb_path)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        con = sqlite3.connect(f"file:{chatdb_path}?immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    q = """
    SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, m.date, h.id AS handle, c.chat_identifier
    FROM message m
    LEFT JOIN handle h ON m.handle_id = h.ROWID
    LEFT JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
    LEFT JOIN chat c ON c.ROWID = cmj.chat_id
    WHERE (m.text IS NOT NULL AND m.text != '') OR m.attributedBody IS NOT NULL
    """
    APPLE_EPOCH = 978307200  # 2001-01-01
    for r in con.execute(q):
        body = r["text"] or _decode_attributedbody(r["attributedBody"])
        if not body:
            continue
        d = r["date"]
        secs = d / 1e9 if d and d > 1e11 else d  # nanoseconds since 2001 in modern macOS
        ts = _iso((secs or 0) + APPLE_EPOCH) if secs else None
        yield {
            "bucket": "communication", "source": "imessage",
            "external_id": f"imsg-{r['ROWID']}",
            "direction": "sent" if r["is_from_me"] else "received",
            "ts": ts, "contact": r["handle"] or r["chat_identifier"],
            "thread_id": r["chat_identifier"], "body": body,
        }
    con.close()


# ---------------- Instagram DMs (Download Your Information, JSON) ----------------
def parse_instagram_dm(root, my_name):
    for inbox in glob.glob(os.path.join(root, "**", "messages", "inbox", "*"), recursive=True):
        for jf in glob.glob(os.path.join(inbox, "message_*.json")):
            try:
                data = json.load(open(jf, encoding="utf-8"))
            except Exception:
                continue
            thread = data.get("title")
            for m in data.get("messages", []):
                sender = m.get("sender_name", "")
                content = m.get("content")
                if not content:
                    continue
                yield {
                    "bucket": "communication", "source": "instagram_dm",
                    "external_id": f"ig-{thread}-{m.get('timestamp_ms')}",
                    "direction": "sent" if sender == my_name else "received",
                    "ts": _iso((m.get("timestamp_ms") or 0) / 1000),
                    "contact": sender if sender != my_name else thread,
                    "thread_id": thread, "body": content,
                }


# ---------------- Facebook Messenger (DYI JSON, same shape as IG) ----------------
def parse_facebook_messenger(root, my_name):
    for jf in glob.glob(os.path.join(root, "**", "message_*.json"), recursive=True):
        try:
            data = json.load(open(jf, encoding="utf-8"))
        except Exception:
            continue
        thread = data.get("title")
        for m in data.get("messages", []):
            content = m.get("content")
            if not content:
                continue
            sender = m.get("sender_name", "")
            yield {
                "bucket": "communication", "source": "facebook_msgr",
                "external_id": f"fb-{thread}-{m.get('timestamp_ms')}",
                "direction": "sent" if sender == my_name else "received",
                "ts": _iso((m.get("timestamp_ms") or 0) / 1000),
                "contact": sender if sender != my_name else thread,
                "thread_id": thread, "body": content,
            }


# ---------------- Twitter / X archive (data/*.js -> JSON after stripping assignment) ----------------
def _load_twitter_js(path):
    raw = open(path, encoding="utf-8").read()
    raw = raw[raw.find("=") + 1:].strip()
    return json.loads(raw)


def parse_twitter_archive(data_dir, my_handle):
    tw = os.path.join(data_dir, "tweets.js")
    if os.path.exists(tw):
        for o in _load_twitter_js(tw):
            t = o.get("tweet", o)
            yield {
                "bucket": "published", "source": "twitter_posts", "direction": "posted",
                "external_id": t.get("id_str"),
                "ts": _iso(parsedate_to_datetime(t["created_at"])) if t.get("created_at") else None,
                "body": t.get("full_text") or t.get("text"),
                "meta": {"retweet": t.get("full_text", "").startswith("RT @"),
                         "likes": t.get("favorite_count"), "retweets": t.get("retweet_count")},
            }
    lk = os.path.join(data_dir, "like.js")
    if os.path.exists(lk):
        for o in _load_twitter_js(lk):
            l = o.get("like", o)
            yield {
                "bucket": "signal_in", "source": "twitter_likes", "direction": "liked",
                "external_id": l.get("tweetId"), "body": l.get("fullText"),
                "url": l.get("expandedUrl"),
            }
    dm = os.path.join(data_dir, "direct-messages.js")
    if os.path.exists(dm):
        for convo in _load_twitter_js(dm):
            c = convo.get("dmConversation", convo)
            cid = c.get("conversationId", "")
            for msg in c.get("messages", []):
                m = msg.get("messageCreate")
                if not m:
                    continue
                yield {
                    "bucket": "communication", "source": "twitter_dm",
                    "external_id": m.get("id"),
                    "direction": "sent" if m.get("senderId") == my_handle else "received",
                    "ts": _iso(parsedate_to_datetime(m["createdAt"])) if m.get("createdAt") else None,
                    "contact": m.get("recipientId") if m.get("senderId") == my_handle else m.get("senderId"),
                    "thread_id": cid, "body": m.get("text"),
                }


# ---------------- Slack export (per-channel folders of dated JSON) ----------------
def parse_slack_export(root, workspace=""):
    users = {}
    uf = os.path.join(root, "users.json")
    if os.path.exists(uf):
        for u in json.load(open(uf, encoding="utf-8")):
            users[u["id"]] = u.get("real_name") or u.get("name")
    for chan_dir in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(chan_dir):
            continue
        channel = os.path.basename(chan_dir)
        for jf in sorted(glob.glob(os.path.join(chan_dir, "*.json"))):
            try:
                msgs = json.load(open(jf, encoding="utf-8"))
            except Exception:
                continue
            for m in msgs:
                if m.get("type") != "message" or not m.get("text"):
                    continue
                uid = m.get("user")
                yield {
                    "bucket": "communication", "source": "slack", "source_account": workspace,
                    "external_id": f"{channel}-{m.get('ts')}",
                    "direction": None, "ts": _iso(float(m["ts"])) if m.get("ts") else None,
                    "contact": users.get(uid, uid), "thread_id": channel, "body": m["text"],
                }


# ---------------- Browser bookmarks (Netscape HTML export) ----------------
def parse_bookmarks_html(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    for m in re.finditer(r'<A[^>]*HREF="([^"]+)"([^>]*)>(.*?)</A>', text, re.I | re.S):
        url, attrs, title = m.group(1), m.group(2), html.unescape(m.group(3))
        add = re.search(r'ADD_DATE="(\d+)"', attrs)
        yield {
            "bucket": "signal_in", "source": "browser_bookmarks", "direction": "bookmarked",
            "external_id": url, "url": url, "title": title,
            "ts": _iso(int(add.group(1))) if add else None,
        }


# ---------------- Google Voice (Takeout: per-conversation HTML) ----------------
_GV_BLOCK = re.compile(r'<div class="message">(.*?)</div>', re.S)
_GV_DT = re.compile(r'<abbr class="dt" title="([^"]+)"')
_GV_FN = re.compile(r'<(?:span|abbr) class="fn"[^>]*>([^<]*)</(?:span|abbr)>')  # outgoing = <abbr ..>Me</abbr>
_GV_TEL = re.compile(r'href="tel:([^"]+)"')
_GV_Q = re.compile(r'<q>(.*?)</q>', re.S)


def parse_google_voice(root, my_name="Me"):
    """Google Voice Takeout. Conversation partner comes from the FILENAME
    ('<Name> - Text - <ts>.html'); direction from per-message sender fn == my_name.
    Only Text + Voicemail records have a <q> body; Calls folder is real, Spam is junk."""
    for hf in glob.glob(os.path.join(root, "**", "*.html"), recursive=True):
        if os.sep + "Spam" + os.sep in hf:
            continue
        base = os.path.basename(hf)
        parts = base.split(" - ")
        partner = parts[0].strip() if parts else ""
        rectype = parts[1].strip() if len(parts) > 1 else ""
        if rectype not in ("Text", "Voicemail"):
            continue
        try:
            txt = open(hf, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        partner_is_num = partner.startswith("+") or partner.replace(" ", "").isdigit()
        for b in (_GV_BLOCK.findall(txt) or [txt]):
            qm = _GV_Q.search(b)
            if not qm:
                continue
            body = html.unescape(re.sub(r"<[^>]+>", "", qm.group(1))).strip()
            if not body:
                continue
            dtm, fnm, telm = _GV_DT.search(b), _GV_FN.search(b), _GV_TEL.search(b)
            ts = dtm.group(1) if dtm else None
            if ts:
                m2 = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", ts)
                ts = m2.group(1) if m2 else ts
            fn = fnm.group(1).strip() if fnm else ""
            is_me = fn == my_name
            name = None if partner_is_num else partner
            handle = (None if is_me else (telm.group(1) if telm else None)) \
                     or (partner if partner_is_num else None) or name
            contact = {"name": name, "handle": handle} if handle else (name or None)
            yield {
                "bucket": "communication", "source": "google_voice",
                "direction": "out" if is_me else "in",
                "ts": ts, "ts_raw": ts, "contact": contact, "body": body,
                "meta": {"record": rectype.lower(), "partner": partner},
            }


# ---------------- WhatsApp (_chat.txt, iOS + Android) ----------------
_WA_IOS = re.compile(r"^‎?\[(\d{1,2}/\d{1,2}/\d{2,4}),\s+([\d:]+\s*[AP]?M?)\]\s+([^:]+?):\s?(.*)$")
_WA_AND = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}),\s+([\d:]+\s*[AP]?M?)\s-\s([^:]+?):\s?(.*)$")


def _wa_ts(date, time):
    for fmt in ("%m/%d/%y %I:%M:%S %p", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%y %I:%M %p",
                "%m/%d/%Y %I:%M %p", "%m/%d/%y %H:%M", "%m/%d/%Y %H:%M"):
        try:
            return datetime.datetime.strptime(f"{date} {time}".strip(), fmt).replace(microsecond=0).isoformat()
        except ValueError:
            continue
    return None


def parse_whatsapp(path, my_name, contact_hint=None):
    cur = None
    for raw in open(path, encoding="utf-8", errors="ignore"):
        line = raw.rstrip("\n")
        m = _WA_IOS.match(line) or _WA_AND.match(line)
        if m:
            if cur:
                yield cur
            date, time, sender, body = m.groups()
            if ": " not in line and sender.lower().startswith(("messages and calls", "your security code")):
                cur = None
                continue
            cur = {
                "bucket": "communication", "source": "whatsapp",
                "direction": "sent" if sender.strip() == my_name else "received",
                "ts": _wa_ts(date, time), "ts_raw": f"{date} {time}",
                "contact": sender.strip() if sender.strip() != my_name else (contact_hint or "whatsapp"),
                "thread_id": contact_hint, "body": body,
            }
        elif cur is not None and line.strip():
            cur["body"] = (cur["body"] + "\n" + line).strip()
    if cur:
        yield cur


# ---------------- WhatsApp iOS ChatStorage.sqlite (from an iPhone backup) ----------------
def parse_whatsapp_ios(chatstorage_path, my_name="Me"):
    """Parse WhatsApp's iOS ChatStorage.sqlite (ZWAMESSAGE/ZWACHATSESSION).
    Dates are Core Data timestamps (seconds since 2001-01-01)."""
    try:
        con = sqlite3.connect(chatstorage_path)
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError:
        con = sqlite3.connect(f"file:{chatstorage_path}?immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    APPLE_EPOCH = 978307200
    q = """
    SELECT m.ZTEXT AS text, m.ZISFROMME AS fromme, m.ZMESSAGEDATE AS mdate,
           s.ZPARTNERNAME AS partner, s.ZCONTACTJID AS jid
    FROM ZWAMESSAGE m
    LEFT JOIN ZWACHATSESSION s ON m.ZCHATSESSION = s.Z_PK
    WHERE m.ZTEXT IS NOT NULL AND m.ZTEXT != ''
    """
    for r in con.execute(q):
        md = r["mdate"]
        ts = _iso((md or 0) + APPLE_EPOCH) if md else None
        contact = r["partner"] or r["jid"]
        yield {
            "bucket": "communication", "source": "whatsapp",
            "direction": "sent" if r["fromme"] else "received",
            "ts": ts, "contact": contact if not r["fromme"] else contact,
            "thread_id": r["jid"], "body": r["text"],
        }
    con.close()


# ---------------- Generic CSV mapper (Goodreads, Letterboxd, Readwise, Reddit, LinkedIn, exportify) ----------------
def parse_csv(path, source, bucket, direction, field_map):
    """field_map maps item keys -> csv column names, e.g. {'body':'Review','ts':'Date','rating':'Rating'}."""
    with open(path, encoding="utf-8", errors="ignore", newline="") as f:
        for row in csv.DictReader(f):
            it = {"bucket": bucket, "source": source, "direction": direction, "meta": {}}
            for k, col in field_map.items():
                if col in row and row[col] != "":
                    it[k] = row[col]
            if it.get("ts"):
                it["ts_raw"] = it["ts"]
            yield it

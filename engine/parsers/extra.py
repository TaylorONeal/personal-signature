"""extra.py - additional generic parsers (Google Chat, YouTube watch history,
Netflix, Yelp). Each is a generator yielding the standard Item dict; see
docs/ARCHITECTURE.md for the contract. Stdlib only."""
import os, re, html, json, glob, csv, datetime
from contextlib import closing
from pathlib import Path
from input_safety import read_text, json_document, text_lines


def _iso_dt(s, fmts):
    if not s:
        return None
    s = s.replace(" ", " ").replace("\xa0", " ").strip()
    for f in fmts:
        try:
            return datetime.datetime.strptime(s, f).isoformat()
        except ValueError:
            continue
    return None


def _iso_loose(s):
    if not s:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
        return dt.isoformat()
    except ValueError:
        return None


# ------------------------------------------------------- Google Chat / Hangouts
def parse_google_chat(root, me_email):
    """Takeout 'Google Chat/Groups/<group>/messages.json' (+ group_info.json).
    Direction by creator email vs me_email; DM partner from group_info members."""
    me = (me_email or "").lower()
    for mf in glob.glob(os.path.join(root, "**", "Groups", "*", "messages.json"), recursive=True):
        d = os.path.dirname(mf)
        gid = os.path.basename(d)
        pname = pemail = gname = None
        gi = os.path.join(d, "group_info.json")
        if os.path.exists(gi):
            try:
                g = json_document(gi)
                gname = g.get("name")
                for mem in g.get("members", []):
                    if (mem.get("email") or "").lower() != me:
                        pname = pname or mem.get("name")
                        pemail = pemail or mem.get("email")
            except (OSError, ValueError) as exc:
                raise ValueError("Cannot read Google Chat group metadata") from exc
        is_dm = gid.startswith("DM")
        try:
            data = json_document(mf)
        except (OSError, ValueError) as exc:
            raise ValueError("Cannot read Google Chat export JSON") from exc
        for m in data.get("messages", []):
            text = m.get("text")
            if not text:
                continue
            cr = m.get("creator") or {}
            cemail = (cr.get("email") or "").lower()
            out = bool(me) and cemail == me
            if is_dm:
                contact = {"name": pname or (None if out else cr.get("name")),
                           "handle": pemail or (None if out else cemail) or pname}
                thread = "DM:" + (pname or pemail or gid)
            else:
                contact = None if out else {"name": cr.get("name"), "handle": cemail or cr.get("name")}
                thread = "Space:" + (gname or gid)
            yield {"bucket": "communication", "source": "google_chat",
                   "external_id": m.get("message_id") or None,
                   "direction": "out" if out else "in",
                   "ts": _iso_dt(m.get("created_date"),
                                 ("%A, %B %d, %Y at %I:%M:%S %p", "%A, %B %d, %Y at %I:%M %p")),
                   "ts_raw": m.get("created_date"), "contact": contact,
                   "thread_id": thread, "body": text,
                   "meta": {"group_id": gid, "is_dm": is_dm, "space": gname}}


# ------------------------------------------------------- YouTube watch history
_YT = re.compile(
    r'Watched[\s\xa0]+<a href="(https://www\.youtube\.com/watch\?v=([^"&]+)[^"]*)">(.*?)</a>'
    r'(?:<br><a href="[^"]*">(.*?)</a>)?'
    r'<br>([A-Z][a-z]{2} \d{1,2}, \d{4}, [\d:]+[\s\xa0 ]*[AP]M)', re.S)


def parse_youtube_watch(path):
    """Takeout YouTube 'history/watch-history.html'."""
    t = read_text(path, errors="replace")
    for url, vid, title, channel, date in _YT.findall(t):
        yield {"bucket": "signal_in", "source": "youtube_watch", "direction": "watched",
               "external_id": f"{vid}-{date}",
               "ts": _iso_dt(date, ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %I:%M %p")),
               "ts_raw": date, "title": html.unescape(title),
               "body": html.unescape(channel) if channel else None, "url": url,
               "meta": {"video_id": vid, "channel": html.unescape(channel) if channel else None}}


# ------------------------------------------------------- Netflix
def parse_netflix(root):
    """Netflix CSV export dir: ViewingActivity / MyList / Ratings."""
    def rows(name):
        p = os.path.join(root, name)
        if os.path.exists(p):
            with closing(text_lines(p)) as f:
                yield from csv.DictReader(f)
    for r in rows("ViewingActivity.csv"):
        yield {"bucket": "signal_in", "source": "netflix_viewing", "direction": "watched",
               "ts": _iso_loose(r.get("Start Time")), "ts_raw": r.get("Start Time"),
               "title": r.get("Title"),
               "meta": {"duration": r.get("Duration"), "device": r.get("Device Type")}}
    for r in rows("MyList.csv"):
        yield {"bucket": "signal_in", "source": "netflix_list", "direction": "saved",
               "ts": _iso_loose(r.get("Utc Title Add Date")), "title": r.get("Title Name")}
    for r in rows("Ratings.csv"):
        try:
            rating = float(r.get("Thumbs Value") or r.get("Star Value") or "") or None
        except ValueError:
            rating = None
        yield {"bucket": "signal_in", "source": "netflix_ratings", "direction": "rated",
               "ts": _iso_loose(r.get("Event Utc Ts")), "title": r.get("Title Name"),
               "rating": rating, "meta": {"rating_type": r.get("Rating Type")}}


# ------------------------------------------------------- Yelp (HTML tables)
def _yelp_rows(path):
    t = read_text(path, errors="replace")
    hdr = None
    for b in re.findall(r"<tr[^>]*>.*?</tr>", t, flags=re.S):
        cells = [re.sub(r"[ \t]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", c)).strip())
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", b, flags=re.S)]
        if hdr is None:
            hdr = cells
            continue
        if len(cells) >= len(hdr):
            yield dict(zip(hdr, cells))


def parse_yelp(root):
    """Yelp data export dir: user_review.html, check_in.html, message.html."""
    rv = os.path.join(root, "user_review.html")
    if os.path.exists(rv):
        for r in _yelp_rows(rv):
            body = r.get("Comment", "")
            m = re.match(r"Visit:\s*[\d/]+\s*(.*)", body, flags=re.S)
            if m:
                body = m.group(1).strip()
            try:
                rating = float(r.get("Rating"))
            except (TypeError, ValueError):
                rating = None
            yield {"bucket": "published", "source": "yelp_reviews", "direction": "posted",
                   "ts": _iso_loose(r.get("Date")), "title": r.get("Business Name"),
                   "body": body, "rating": rating, "meta": {"status": r.get("Status")}}
    ci = os.path.join(root, "check_in.html")
    if os.path.exists(ci):
        for r in _yelp_rows(ci):
            yield {"bucket": "signal_in", "source": "yelp_checkins", "direction": "checked_in",
                   "ts": _iso_loose(r.get("Date")), "title": r.get("Business Name"),
                   "body": r.get("Comment"),
                   "lat": _f(r.get("Latitude")), "lon": _f(r.get("Longitude"))}
    dm = os.path.join(root, "message.html")
    if os.path.exists(dm):
        for r in _yelp_rows(dm):
            yield {"bucket": "communication", "source": "yelp_dm", "direction": "out",
                   "ts": _iso_loose(r.get("Date")), "contact": r.get("Recipients") or None,
                   "title": r.get("Subject"), "body": r.get("Text")}


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

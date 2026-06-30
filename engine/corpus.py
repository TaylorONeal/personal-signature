"""
corpus.py - core ingest library for the Personal Corpus DB.
Stdlib only. Every parser normalizes its rows into Item dicts and hands them here.

An Item dict uses these keys (all optional except bucket, source, direction):
    bucket, source, source_account, external_id, direction, ts, ts_raw,
    contact (raw handle string or {name, handle}), thread_id, title, body,
    url, rating, lat, lon, meta (dict)

Dedupe: item id = sha1(source | external_id) when external_id present,
otherwise sha1(source | direction | ts | contact | body[:300]).
Re-running an ingest is therefore idempotent.
"""
import sqlite3, hashlib, json, os, datetime, re, shutil, tempfile

SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def _work_dir():
    """Local scratch dir for the live DB. Some mounts (Cowork FUSE) can't host
    SQLite locking, so we always operate on a local copy and sync bytes back."""
    for cand in (os.environ.get("CORPUS_WORK"), "/dev/shm", tempfile.gettempdir()):
        if cand and os.path.isdir(os.path.dirname(cand) or cand):
            d = os.path.join(cand, "corpus_work")
            try:
                os.makedirs(d, exist_ok=True)
                return d
            except OSError:
                continue
    return tempfile.mkdtemp(prefix="corpus_")


def _sha1(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(str(p or "").encode("utf-8", "ignore"))
        h.update(b"\x00")
    return h.hexdigest()


def norm_handle(handle):
    """Normalize an email/username/phone into a comparable key."""
    if not handle:
        return ""
    s = str(handle).strip().lower()
    if "@" in s and "." in s.split("@")[-1]:          # email
        return s
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 10:                              # phone
        return "+" + digits[-11:] if len(digits) >= 11 else "+1" + digits
    return s.lstrip("@")                               # username


class Corpus:
    def __init__(self, db_path):
        # db_path is the canonical/persistent location (may be on a mount).
        # We operate on a local working copy and sync bytes back on close()/sync().
        self.store_path = os.path.abspath(db_path)
        self.work_path = os.path.join(_work_dir(), os.path.basename(self.store_path))
        self._store_bytes_at_open = 0
        if os.path.exists(self.store_path) and self.store_path != self.work_path:
            # CRITICAL: a silently-failed copy here used to leave work empty, and the
            # later sync() would then overwrite a good store with an empty DB. Never
            # swallow this. Verify the copy by byte size and raise on any mismatch.
            src_sz = os.path.getsize(self.store_path)
            self._store_bytes_at_open = src_sz
            last_err = None
            for _ in range(3):
                try:
                    if os.path.exists(self.work_path):
                        os.remove(self.work_path)
                    shutil.copyfile(self.store_path, self.work_path)
                    if os.path.getsize(self.work_path) == src_sz:
                        last_err = None
                        break
                    last_err = OSError(f"copy size mismatch: {os.path.getsize(self.work_path)} != {src_sz}")
                except OSError as e:
                    last_err = e
            if last_err is not None:
                raise RuntimeError(
                    f"Refusing to open corpus: could not copy existing store "
                    f"({src_sz} bytes) to work dir {self.work_path}: {last_err}. "
                    f"Set CORPUS_WORK to a path with space, or operate in place.")
        self.db = sqlite3.connect(self.work_path)
        self.db.row_factory = sqlite3.Row
        self.init_schema()

    def sync(self):
        """Persist the working DB back to its canonical location as bytes."""
        if self.store_path == self.work_path:
            return
        self.db.commit()
        try:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        # Shrink-guard: never let a much-smaller work DB clobber a larger store.
        # A real ingest only ever grows the item count. If work is dramatically
        # smaller than the store on disk, something went wrong (failed copy, wrong
        # work dir) and overwriting would destroy data. Require CORPUS_ALLOW_SHRINK=1.
        if os.path.exists(self.store_path) and os.environ.get("CORPUS_ALLOW_SHRINK") != "1":
            try:
                work_n = self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                sc = sqlite3.connect(f"file:{self.store_path}?immutable=1", uri=True)
                store_n = sc.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                sc.close()
                if work_n < store_n * 0.9:
                    raise RuntimeError(
                        f"Refusing to sync: work DB has {work_n} items but store has "
                        f"{store_n}. This would destroy data. If intentional, set "
                        f"CORPUS_ALLOW_SHRINK=1.")
            except sqlite3.OperationalError:
                pass  # store has no items table yet (fresh) -> fine to write
        tmp = self.store_path + ".tmp"
        try:
            shutil.copyfile(self.work_path, tmp)
            os.replace(tmp, self.store_path)          # atomic on normal disks
        except OSError:
            shutil.copyfile(self.work_path, self.store_path)  # mounts that block rename/unlink

    def init_schema(self):
        with open(os.path.abspath(SCHEMA)) as f:
            self.db.executescript(f.read())
        self.db.commit()

    # ---------- contacts ----------
    def resolve_contact(self, contact):
        if not contact:
            return None
        if isinstance(contact, dict):
            name, handle = contact.get("name"), contact.get("handle") or contact.get("name")
        else:
            name, handle = None, contact
        key = norm_handle(handle)
        if not key:
            return None
        cid = _sha1("contact", key)
        row = self.db.execute("SELECT handles, platforms FROM contacts WHERE id=?", (cid,)).fetchone()
        now = datetime.datetime.utcnow().isoformat()
        if row is None:
            self.db.execute(
                "INSERT INTO contacts(id,display_name,handles,platforms,first_seen,last_seen) "
                "VALUES(?,?,?,?,?,?)",
                (cid, name or handle, json.dumps([key]), json.dumps([]), now, now),
            )
        else:
            handles = set(json.loads(row["handles"] or "[]"))
            handles.add(key)
            self.db.execute(
                "UPDATE contacts SET handles=?, last_seen=?, "
                "display_name=COALESCE(display_name,?) WHERE id=?",
                (json.dumps(sorted(handles)), now, name, cid),
            )
        return cid

    # ---------- runs ----------
    def start_run(self, source, mode):
        run_id = _sha1(source, mode, datetime.datetime.utcnow().isoformat())[:16]
        self.db.execute(
            "INSERT INTO ingest_runs(run_id,source,mode,started_at,status) VALUES(?,?,?,?,?)",
            (run_id, source, mode, datetime.datetime.utcnow().isoformat(), "running"),
        )
        self.db.commit()
        return run_id

    def finish_run(self, run_id, added, skipped, status="ok", note=""):
        self.db.execute(
            "UPDATE ingest_runs SET finished_at=?, items_added=?, items_skipped=?, status=?, note=? WHERE run_id=?",
            (datetime.datetime.utcnow().isoformat(), added, skipped, status, note, run_id),
        )
        self.db.commit()

    # ---------- watermark (delta support) ----------
    def get_watermark(self, source, account=""):
        row = self.db.execute(
            "SELECT last_ts, last_external_id FROM watermarks WHERE source=? AND source_account=?",
            (source, account or ""),
        ).fetchone()
        return dict(row) if row else {"last_ts": None, "last_external_id": None}

    def set_watermark(self, source, account="", last_ts=None, last_external_id=None):
        self.db.execute(
            "INSERT INTO watermarks(source,source_account,last_ts,last_external_id,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(source,source_account) DO UPDATE SET "
            "last_ts=COALESCE(excluded.last_ts,last_ts), "
            "last_external_id=COALESCE(excluded.last_external_id,last_external_id), updated_at=excluded.updated_at",
            (source, account or "", last_ts, last_external_id, datetime.datetime.utcnow().isoformat()),
        )
        self.db.commit()

    # ---------- items ----------
    def _ensure_source(self, name, bucket):
        self.db.execute(
            "INSERT OR IGNORE INTO sources(name,bucket,access_tier,notes) VALUES(?,?,?,?)",
            (name, bucket or "communication", "unknown", "auto-registered on ingest"))

    def add_item(self, it, run_id=None):
        self._ensure_source(it["source"], it.get("bucket"))
        ext = it.get("external_id")
        cid = self.resolve_contact(it.get("contact"))
        if ext:
            iid = _sha1(it["source"], ext)
        else:
            iid = _sha1(it["source"], it.get("direction"), it.get("ts"), cid, (it.get("body") or "")[:300])
        exists = self.db.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone()
        if exists:
            return False
        self.db.execute(
            "INSERT INTO items(id,bucket,source,source_account,external_id,direction,ts,ts_raw,"
            "contact_id,thread_id,title,body,url,rating,lat,lon,meta,run_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, it["bucket"], it["source"], it.get("source_account"), ext, it.get("direction"),
             it.get("ts"), it.get("ts_raw"), cid, it.get("thread_id"), it.get("title"),
             it.get("body"), it.get("url"), it.get("rating"), it.get("lat"), it.get("lon"),
             json.dumps(it.get("meta") or {}), run_id),
        )
        rowid = self.db.execute("SELECT rowid FROM items WHERE id=?", (iid,)).fetchone()[0]
        self.db.execute("INSERT INTO items_fts(rowid,title,body) VALUES(?,?,?)",
                        (rowid, it.get("title") or "", it.get("body") or ""))
        return True

    # ---------- cross-source dedup (e.g. Google Voice/Messages vs iMessage SMS) ----------
    @staticmethod
    def _normbody(s):
        return re.sub(r"\s+", " ", (s or "")).strip().lower()[:200]

    def _build_xsource_index(self, sources):
        """Map (direction, contact_id, normbody) -> sorted list of epoch seconds, for the
        given already-loaded sources. Used to skip the same message arriving from another
        platform (text-forwarding overlap)."""
        idx = {}
        ph = ",".join("?" * len(sources))
        for r in self.db.execute(
            f"SELECT direction, contact_id, body, ts FROM items WHERE source IN ({ph}) AND body IS NOT NULL",
            sources):
            key = (r[0], r[1], self._normbody(r[2]))
            try:
                ep = datetime.datetime.fromisoformat(r[3]).timestamp() if r[3] else None
            except Exception:
                ep = None
            idx.setdefault(key, []).append(ep)
        return idx

    def _is_xsource_dupe(self, idx, it, cid, window_h=36):
        key = (it.get("direction"), cid, self._normbody(it.get("body")))
        cands = idx.get(key)
        if not cands:
            return False
        ts = it.get("ts")
        if not ts:
            return True  # same direction+contact+body, no ts to disambiguate -> treat as dupe
        try:
            ep = datetime.datetime.fromisoformat(ts).timestamp()
        except Exception:
            return True
        win = window_h * 3600
        return any(c is not None and abs(c - ep) <= win for c in cands)

    def ingest(self, source, items, mode="initial", account="", dedupe_against=None):
        """Run a list/generator of Item dicts through dedupe + watermark tracking.
        dedupe_against: list of other source names to suppress cross-platform duplicates."""
        wm = self.get_watermark(source, account)
        floor = wm["last_ts"] if mode == "delta" else None
        run_id = self.start_run(source, mode)
        xidx = self._build_xsource_index(dedupe_against) if dedupe_against else None
        added = skipped = xdup = 0
        max_ts = floor
        for it in items:
            it.setdefault("source", source)
            if floor and it.get("ts") and it["ts"] <= floor:
                skipped += 1
                continue
            if xidx is not None:
                cid = self.resolve_contact(it.get("contact"))
                if self._is_xsource_dupe(xidx, it, cid):
                    xdup += 1
                    skipped += 1
                    continue
            if self.add_item(it, run_id):
                added += 1
                if it.get("ts") and (max_ts is None or it["ts"] > max_ts):
                    max_ts = it["ts"]
            else:
                skipped += 1
        self.db.commit()
        self.set_watermark(source, account, last_ts=max_ts)
        self.finish_run(run_id, added, skipped, note=f"xsource_dupes={xdup}" if xidx is not None else "")
        return {"source": source, "mode": mode, "added": added, "skipped": skipped,
                "cross_source_dupes": xdup, "watermark": max_ts}

    def bulk_ingest(self, source, items, mode="initial", account=""):
        """Fast path for large initial loads (e.g. 75k iMessages). One transaction,
        in-memory contact cache, bulk FTS. Uses INSERT OR IGNORE for dedupe."""
        wm = self.get_watermark(source, account)
        floor = wm["last_ts"] if mode == "delta" else None
        run_id = self.start_run(source, mode)
        d = self.db
        # preload contact handle->id map
        cmap = {}
        for cid, handles in d.execute("SELECT id, handles FROM contacts"):
            for h in json.loads(handles or "[]"):
                cmap[h] = cid
        now = datetime.datetime.utcnow().isoformat()
        new_contacts = {}            # cid -> (name, key)
        rows = []
        max_ts = floor
        seen = 0
        for it in items:
            seen += 1
            it.setdefault("source", source)
            ts = it.get("ts")
            if floor and ts and ts <= floor:
                continue
            # contact
            contact = it.get("contact")
            cid = None
            if contact:
                key = norm_handle(contact if not isinstance(contact, dict)
                                  else contact.get("handle") or contact.get("name"))
                if key:
                    cid = cmap.get(key)
                    if cid is None:
                        cid = _sha1("contact", key)
                        cmap[key] = cid
                        nm = contact.get("name") if isinstance(contact, dict) else None
                        new_contacts.setdefault(cid, (nm or (contact if isinstance(contact, str) else key), key))
            ext = it.get("external_id")
            iid = _sha1(source, ext) if ext else _sha1(source, it.get("direction"), ts, cid, (it.get("body") or "")[:300])
            rows.append((iid, it["bucket"], source, it.get("source_account") or account, ext,
                         it.get("direction"), ts, it.get("ts_raw"), cid, it.get("thread_id"),
                         it.get("title"), it.get("body"), it.get("url"), it.get("rating"),
                         it.get("lat"), it.get("lon"), json.dumps(it.get("meta") or {}), run_id))
            if ts and (max_ts is None or ts > max_ts):
                max_ts = ts
        # batch insert contacts
        d.executemany("INSERT OR IGNORE INTO contacts(id,display_name,handles,platforms,first_seen,last_seen) "
                      "VALUES(?,?,?,?,?,?)",
                      [(cid, nm, json.dumps([key]), "[]", now, now) for cid, (nm, key) in new_contacts.items()])
        if rows:
            self._ensure_source(source, rows[0][1])
        before = d.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        d.executemany(
            "INSERT OR IGNORE INTO items(id,bucket,source,source_account,external_id,direction,ts,ts_raw,"
            "contact_id,thread_id,title,body,url,rating,lat,lon,meta,run_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        after = d.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        added = after - before
        # bulk FTS for the rows just inserted (identified by run_id)
        d.execute("INSERT INTO items_fts(rowid,title,body) "
                  "SELECT rowid,COALESCE(title,''),COALESCE(body,'') FROM items WHERE run_id=?", (run_id,))
        d.commit()
        self.set_watermark(source, account, last_ts=max_ts)
        self.finish_run(run_id, added, seen - added)
        return {"source": source, "mode": mode, "seen": seen, "added": added, "watermark": max_ts}

    def close(self):
        self.db.commit()
        self.sync()
        self.db.close()

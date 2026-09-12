"""
corpus.py - core ingest library for the Personal Corpus DB.
Stdlib only. Every parser normalizes its rows into Item dicts and hands them here.

An Item dict uses these keys (all optional except bucket, source, direction):
    bucket, source, source_account, external_id, direction, ts, ts_raw,
    contact (raw handle string or {name, handle}), thread_id, title, body,
    url, rating, lat, lon, meta (dict)

Dedupe: versioned, account-scoped source/external ID or full identifying content hash.
Re-running an ingest is therefore idempotent.
"""
import sqlite3, hashlib, json, os, datetime, re, shutil, tempfile, math

SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def open_readonly(path):
    """URI escaping prevents filenames containing ?/# from changing open options."""
    from pathlib import Path
    db = sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA trusted_schema=OFF")
    db.execute("PRAGMA query_only=ON")
    return db



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
    if re.fullmatch(r"[+()\d .-]+", s) and len(digits) >= 10:
        # Preserve national numbers without guessing their country.
        return ("+" if s.startswith("+") else "") + digits
    return s.lstrip("@")                               # username


class Corpus:
    def __init__(self, db_path, readonly=False, contact_aliases=None, max_items=1000000):
        self.contact_aliases = contact_aliases or {}
        if not isinstance(self.contact_aliases, dict) or not all(
                isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
                for k, v in self.contact_aliases.items()):
            raise ValueError("Contact aliases must map nonempty handles to canonical handles")
        self.contact_aliases = {norm_handle(k): norm_handle(v) for k, v in self.contact_aliases.items()}
        self.max_items = max_items
        self.store_path = os.path.abspath(db_path)
        self.readonly = readonly
        self._scratch = None
        self._locked = False
        self.db = None
        self.lock_path = self.store_path + ".lock"
        if readonly:
            # Release the source handle before returning (Windows blocks rename of open files).
            # Queries use an isolated snapshot and never publish it back to the store.
            try:
                src = open_readonly(self.store_path)
                try:
                    self._scratch = tempfile.TemporaryDirectory(prefix="corpus-read-", dir=os.environ.get("CORPUS_WORK"))
                    self.work_path = os.path.join(self._scratch.name, "corpus.db")
                    fd = os.open(self.work_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.close(fd)
                    target = sqlite3.connect(self.work_path)
                    try:
                        src.backup(target)
                        target.execute("PRAGMA journal_mode=DELETE")
                    finally:
                        target.close()
                finally:
                    src.close()
                self.db = open_readonly(self.work_path)
            except BaseException:
                self.close(save=False)
                raise
            return
        # A private parent is required: same-user processes are outside this boundary.
        if os.path.islink(self.store_path):
            raise RuntimeError("Refusing to write a symlink database")
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise RuntimeError("Corpus is locked; wait for the writer. See SECURITY.md for crash recovery.") from None
        self._locked = True
        os.close(fd)
        try:
            self._scratch = tempfile.TemporaryDirectory(prefix="corpus-", dir=os.environ.get("CORPUS_WORK"))
            self.work_path = os.path.join(self._scratch.name, "corpus.db")
            fd = os.open(self.work_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(self.work_path)
            self.db.row_factory = sqlite3.Row
            self._original_state = self._store_state()
            if os.path.exists(self.store_path):
                src = open_readonly(self.store_path)
                try:
                    src.backup(self.db)
                finally:
                    src.close()
            self.init_schema()
        except BaseException:
            self.close(save=False)
            raise

    def _store_state(self):
        # Also detect external WAL/journal changes; never replace a live SQLite store.
        result = []
        for path in (self.store_path, self.store_path + "-wal", self.store_path + "-journal"):
            try:
                st = os.stat(path, follow_symlinks=False)
                result.append((st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
            except FileNotFoundError:
                result.append(None)
        return result

    def sync(self):
        """Publish atomically or fail without modifying the original store."""
        if self.readonly:
            return
        self.db.commit()
        if self._store_state() != self._original_state:
            raise RuntimeError("Store changed outside this writer; refusing to overwrite it")
        if any(os.path.exists(self.store_path + suffix) for suffix in ("-wal", "-journal")):
            raise RuntimeError("Store has SQLite sidecars; close external writers before ingest")
        if os.path.exists(self.store_path) and os.environ.get("CORPUS_ALLOW_SHRINK") != "1":
            src = open_readonly(self.store_path)
            try:
                exists = src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='items'").fetchone()
                store_n = src.execute("SELECT COUNT(*) FROM items").fetchone()[0] if exists else 0
            finally:
                src.close()
            work_n = self.db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            if work_n < store_n * 0.9:
                raise RuntimeError("Refusing to sync: item count shrank below 90%; restore or explicitly set CORPUS_ALLOW_SHRINK=1")
        fd, tmp = tempfile.mkstemp(prefix=".corpus-", suffix=".tmp", dir=os.path.dirname(self.store_path))
        try:
            with os.fdopen(fd, "wb") as dest, open(self.work_path, "rb") as src:
                shutil.copyfileobj(src, dest)
                dest.flush()
                os.fsync(dest.fileno())
            if self._store_state() != self._original_state:
                raise RuntimeError("Store changed during sync; refusing to overwrite it")
            os.replace(tmp, self.store_path)
            self._original_state = self._store_state()
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def init_schema(self):
        if self.db.execute("PRAGMA user_version").fetchone()[0] > 2:
            raise ValueError("Corpus schema is newer than this engine; upgrade before writing")
        with open(os.path.abspath(SCHEMA)) as f:
            self.db.executescript(f.read())
        if self.db.execute("PRAGMA user_version").fetchone()[0] < 2:
            for row in self.db.execute("SELECT * FROM items"):
                it = dict(row)
                self.db.execute("UPDATE items SET id=? WHERE rowid=(SELECT rowid FROM items WHERE id=?)",
                                (self.item_id(it, it.get("contact_id")), it["id"]))
            self.db.execute("PRAGMA user_version=2")
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
        key = self.contact_aliases.get(key, key)
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
        return run_id

    def finish_run(self, run_id, added, skipped, status="ok", note=""):
        self.db.execute(
            "UPDATE ingest_runs SET finished_at=?, items_added=?, items_skipped=?, status=?, note=? WHERE run_id=?",
            (datetime.datetime.utcnow().isoformat(), added, skipped, status, note, run_id),
        )

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

    # ---------- items ----------
    def _ensure_source(self, name, bucket):
        self.db.execute(
            "INSERT OR IGNORE INTO sources(name,bucket,access_tier,notes) VALUES(?,?,?,?)",
            (name, bucket or "communication", "unknown", "auto-registered on ingest"))

    @staticmethod
    def item_id(it, cid):
        account = it.get("source_account") or ""
        if it.get("external_id") is not None and it.get("external_id") != "":
            parts = ["v2", it["source"], account, str(it["external_id"])]
        else:
            parts = ["v2", it["source"], account, it.get("direction"), it.get("ts"),
                     cid, it.get("thread_id"), it.get("title"), it.get("body"), it.get("url")]
        # JSON framing prevents embedded delimiters from conflating distinct fields.
        return hashlib.sha256(json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    def add_item(self, it, run_id=None):
        self._ensure_source(it["source"], it.get("bucket"))
        ext = it.get("external_id")
        cid = self.resolve_contact(it.get("contact"))
        iid = self.item_id(it, cid)
        exists = self.db.execute("SELECT * FROM items WHERE id=?", (iid,)).fetchone()
        if exists:
            # Export-generated IDs can collide. Keep differing evidence instead of losing it.
            fields = ("bucket", "direction", "ts", "contact_id", "thread_id", "title", "body", "url", "rating", "lat", "lon")
            incoming = dict(it, contact_id=cid)
            if all(exists[k] == incoming.get(k) for k in fields) and json.loads(exists["meta"] or "{}") == it.get("meta", {}):
                return False
            variant = json.dumps([incoming.get(k) for k in fields] + [it.get("meta", {})],
                                 sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            iid = hashlib.sha256((iid + ":" + variant).encode("utf-8")).hexdigest()
            if self.db.execute("SELECT 1 FROM items WHERE id=?", (iid,)).fetchone():
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
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

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

    def _is_xsource_dupe(self, idx, it, cid, window_h=0.0833333333):
        if not cid or not self._normbody(it.get("body")):
            return False
        key = (it.get("direction"), cid, self._normbody(it.get("body")))
        cands = idx.get(key)
        if not cands:
            return False
        ts = it.get("ts")
        if not ts:
            return False  # Missing timestamps cannot establish a duplicate.
        try:
            ep = datetime.datetime.fromisoformat(ts).timestamp()
        except Exception:
            return False
        win = window_h * 3600
        return any(c is not None and abs(c - ep) <= win for c in cands)

    def ingest(self, source, items, mode="initial", account="", dedupe_against=None):
        """Run a list/generator of Item dicts through dedupe + watermark tracking.
        dedupe_against: list of other source names to suppress cross-platform duplicates."""
        self.db.execute("SAVEPOINT ingest_run")
        try:
            wm = self.get_watermark(source, account)
            run_id = self.start_run(source, mode)
            xidx = self._build_xsource_index(dedupe_against) if dedupe_against else None
            added = skipped = xdup = missing_ts = unknown_direction = 0
            max_ts = wm["last_ts"]
            for row_number, it in enumerate(items, 1):
                if row_number > self.max_items:
                    raise ValueError("Ingest exceeds item budget; split the input or increase --max-items")
                if not isinstance(it, dict):
                    raise ValueError("Each item must be an object")
                it = dict(it)
                it.setdefault("source", source)
                it["source_account"] = it.get("source_account") or account
                if it.get("bucket") not in {"communication", "published", "signal_in"}:
                    raise ValueError("Item bucket must be communication, published, or signal_in")
                if not isinstance(it.get("source"), str) or not it["source"]:
                    raise ValueError("Item source must be a nonempty string")
                for field in ("direction", "ts", "ts_raw", "thread_id", "title", "body", "url", "source_account"):
                    if it.get(field) is not None and not isinstance(it[field], str):
                        raise ValueError(f"Item {row_number}: {field} must be text or null")
                if not isinstance(it.get("meta", {}), dict):
                    raise ValueError(f"Item {row_number}: meta must be an object")
                for field in ("rating", "lat", "lon"):
                    if it.get(field) is not None:
                        try:
                            it[field] = float(it[field])
                            if not math.isfinite(it[field]):
                                raise ValueError()
                        except (TypeError, ValueError):
                            raise ValueError(f"Item {row_number}: {field} must be a finite number") from None
                missing_ts += not bool(it.get("ts"))
                unknown_direction += not bool(it.get("direction"))
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
            self.set_watermark(source, account, last_ts=max_ts)
            self.finish_run(run_id, added, skipped, note=f"xsource_dupes={xdup}" if xidx is not None else "")
            self.db.execute("RELEASE ingest_run")
            return {"source": source, "mode": mode, "added": added, "skipped": skipped,
                    "cross_source_dupes": xdup, "watermark": max_ts,
                    "diagnostics": {"missing_timestamps": missing_ts, "unknown_direction": unknown_direction}}
        except BaseException:
            self.db.execute("ROLLBACK TO ingest_run")
            self.db.execute("RELEASE ingest_run")
            raise

    def bulk_ingest(self, source, items, mode="initial", account=""):
        """Streaming path shares validation and transaction semantics with ingest."""
        result = self.ingest(source, items, mode=mode, account=account)
        result["seen"] = result["added"] + result["skipped"]
        return result

    def close(self, save=True):
        try:
            if self.db is not None:
                if save and not self.readonly:
                    self.sync()
        finally:
            if self.db is not None:
                self.db.close()
                self.db = None
            if self._scratch is not None:
                self._scratch.cleanup()
                self._scratch = None
            if self._locked:
                os.unlink(self.lock_path)
                self._locked = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close(save=exc_type is None)

-- personal-corpus :: unified schema (generic, no personal data)
-- One row per atomic item (a message, post, review, play, ride, visit...).
-- Sources auto-register on first ingest, so the registry below is just a hint.
PRAGMA journal_mode = DELETE;   -- FUSE/network mounts can't host WAL; DELETE is safe to copy.

-- ---------------------------------------------------------------- items
CREATE TABLE IF NOT EXISTS items (
  id           TEXT PRIMARY KEY,         -- v2 account-scoped external ID or full identifying-content hash
  bucket       TEXT NOT NULL,            -- signal_in | communication | published
  source       TEXT NOT NULL,            -- e.g. imessage, gmail, instagram_dm, spotify_liked
  source_account TEXT,                   -- which account (personal vs work), optional
  external_id  TEXT,                     -- platform id when available (best dedupe key)
  direction    TEXT,                     -- in | out | sent | received | posted | liked | watched | ...
  ts           TEXT,                     -- ISO-8601, naive UTC-ish; sorts lexicographically
  ts_raw       TEXT,                     -- original timestamp string as exported
  contact_id   TEXT,                     -- FK -> contacts.id (the other party), nullable
  thread_id    TEXT,
  title        TEXT,                     -- subject / business name / track title / etc.
  body         TEXT,                     -- the text
  url          TEXT,
  rating       REAL,                     -- stars / thumbs, when applicable
  lat          REAL,
  lon          REAL,
  meta         TEXT,                     -- JSON blob for source-specific fields
  run_id       TEXT
);
CREATE INDEX IF NOT EXISTS ix_items_source   ON items(source);
CREATE INDEX IF NOT EXISTS ix_items_bucket   ON items(bucket);
CREATE INDEX IF NOT EXISTS ix_items_ts       ON items(ts);
CREATE INDEX IF NOT EXISTS ix_items_contact  ON items(contact_id);
CREATE INDEX IF NOT EXISTS ix_items_dir      ON items(direction);

-- ---------------------------------------------------------------- contacts
CREATE TABLE IF NOT EXISTS contacts (
  id           TEXT PRIMARY KEY,         -- sha1("contact"|normalized_handle)
  display_name TEXT,
  handles      TEXT,                     -- JSON array of normalized handles (phones/emails/usernames)
  platforms    TEXT,                     -- JSON array
  first_seen   TEXT,
  last_seen    TEXT,
  relationship TEXT,                     -- optional user label: family | friend | partner | colleague ...
  status       TEXT,                     -- optional: active | ended | blocked ...
  status_note  TEXT,
  aliases      TEXT                      -- JSON array of alternate display names
);

-- ---------------------------------------------------------------- source registry (optional hint)
CREATE TABLE IF NOT EXISTS sources (
  name        TEXT PRIMARY KEY,
  bucket      TEXT,
  access_tier TEXT,                      -- manual_export | connector | local | unknown
  notes       TEXT
);
-- A few generic examples. Real rows are auto-added on ingest; edit freely.
INSERT OR IGNORE INTO sources(name,bucket,access_tier,notes) VALUES
  ('imessage',        'communication','local',         'macOS ~/Library/Messages/chat.db (read in place)'),
  ('gmail',           'communication','manual_export',  'Takeout Mail -> Sent label -> mbox'),
  ('instagram_dm',    'communication','manual_export',  'IG "Download your information" -> Messages only, JSON'),
  ('facebook_msgr',   'communication','manual_export',  'FB DYI -> Messages only, JSON'),
  ('twitter',         'published',    'manual_export',  'X archive -> data/tweets.js'),
  ('google_chat',     'communication','manual_export',  'Takeout Google Chat -> Groups/*/messages.json'),
  ('google_voice',    'communication','manual_export',  'Takeout Voice -> Calls/*.html (Text+Voicemail)'),
  ('whatsapp',        'communication','manual_export',  'Export chat (without media) -> _chat.txt'),
  ('slack',           'communication','manual_export',  'Slack workspace export'),
  ('reddit',          'published',    'manual_export',  'reddit.com/settings/data-request CSVs'),
  ('youtube',         'signal_in',    'manual_export',  'Takeout YouTube comments/playlists/history'),
  ('spotify_liked',   'signal_in',    'manual_export',  'exportify or Spotify data export CSV'),
  ('browser_bookmarks','signal_in',   'local',          'browser HTML bookmarks export'),
  ('yelp_reviews',    'published',    'manual_export',  'Yelp data export HTML tables'),
  ('netflix_viewing', 'signal_in',    'manual_export',  'Netflix Viewing Activity CSV');

-- ---------------------------------------------------------------- ingest bookkeeping
CREATE TABLE IF NOT EXISTS watermarks (
  source TEXT, source_account TEXT, last_ts TEXT, last_external_id TEXT, updated_at TEXT,
  PRIMARY KEY (source, source_account)
);
CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id TEXT PRIMARY KEY, source TEXT, mode TEXT, started_at TEXT, finished_at TEXT,
  items_added INTEGER, items_skipped INTEGER, status TEXT, note TEXT
);

-- ---------------------------------------------------------------- full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(title, body, content='');

-- ---------------------------------------------------------------- coverage + read views
DROP VIEW IF EXISTS v_sources;
CREATE VIEW v_sources AS
  SELECT bucket, source, COUNT(*) n,
         SUM(CASE WHEN direction IN ('out','sent','posted') THEN 1 ELSE 0 END) self_authored,
         MIN(ts) first_ts, MAX(ts) last_ts
  FROM items GROUP BY bucket, source ORDER BY n DESC;

DROP VIEW IF EXISTS v_top_contacts;
CREATE VIEW v_top_contacts AS
  SELECT c.display_name, c.relationship, COUNT(*) total_items,
         SUM(CASE WHEN i.direction IN ('out','sent') THEN 1 ELSE 0 END) sent,
         SUM(CASE WHEN i.direction IN ('in','received') THEN 1 ELSE 0 END) received,
         GROUP_CONCAT(DISTINCT i.source) source_list,
         MIN(i.ts) first_ts, MAX(i.ts) last_ts
  FROM items i JOIN contacts c ON i.contact_id=c.id
  WHERE i.bucket='communication' GROUP BY i.contact_id ORDER BY total_items DESC;

DROP VIEW IF EXISTS v_monthly_volume;
CREATE VIEW v_monthly_volume AS
  SELECT substr(ts,1,7) ym, bucket, COUNT(*) n FROM items
  WHERE ts IS NOT NULL GROUP BY ym, bucket ORDER BY ym;

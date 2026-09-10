"""Synthetic-only regression tests. Never open a real personal corpus."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from corpus import Corpus, open_readonly
from parsers.exports import parse_gmail_threads_json, parse_imessage, parse_mbox
from query import search

ROOT = Path(__file__).resolve().parents[1]


def item(**kwargs):
    return dict(bucket='communication', source='test', direction='sent', body='hello', **kwargs)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / 'corpus.db'

    def tearDown(self):
        self.temp.cleanup()

    def seed(self):
        with Corpus(self.path) as c:
            c.ingest('test', [item()])

    def test_readonly_never_creates_database(self):
        with self.assertRaises(sqlite3.OperationalError):
            Corpus(self.path, readonly=True)
        self.assertFalse(self.path.exists())

    def test_reader_cannot_write_and_does_not_overwrite_writer(self):
        self.seed()
        reader = Corpus(self.path, readonly=True)
        with self.assertRaises(sqlite3.OperationalError):
            reader.db.execute('DELETE FROM items')
        with Corpus(self.path) as writer:
            writer.ingest('test', [item(external_id='2')])
        reader.close()
        with Corpus(self.path, readonly=True) as c:
            self.assertEqual(c.db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 2)

    def test_same_basename_isolation_and_permissions(self):
        other = self.root / 'other'
        other.mkdir()
        with Corpus(self.path) as a, Corpus(other / 'corpus.db') as b:
            self.assertNotEqual(a.work_path, b.work_path)
            if os.name == 'posix':
                self.assertEqual(os.stat(a.work_path).st_mode & 0o777, 0o600)
                self.assertEqual(os.stat(Path(a.work_path).parent).st_mode & 0o777, 0o700)
            a.ingest('test', [item()])
        with Corpus(other / 'corpus.db', readonly=True) as b:
            self.assertEqual(b.db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 0)
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_writer_refused(self):
        with Corpus(self.path):
            with self.assertRaisesRegex(RuntimeError, 'locked'):
                Corpus(self.path)
        self.assertFalse(Path(str(self.path) + '.lock').exists())

    def test_failed_replace_preserves_store(self):
        self.seed()
        original = self.path.read_bytes()
        with self.assertRaises(OSError):
            with Corpus(self.path) as c:
                c.ingest('test', [item(external_id='2')])
                with patch('corpus.os.replace', side_effect=OSError('simulated failure')):
                    c.sync()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(list(self.root.glob('.corpus-*.tmp')))

    def test_external_change_is_not_overwritten(self):
        self.seed()
        with self.assertRaisesRegex(RuntimeError, 'changed'):
            with Corpus(self.path) as c:
                with sqlite3.connect(self.path) as other:
                    other.execute("INSERT INTO sources(name) VALUES('external')")
        with open_readonly(self.path) as c:
            self.assertIsNotNone(c.execute("SELECT 1 FROM sources WHERE name='external'").fetchone())

    def test_exception_discards_whole_cli_session(self):
        self.seed()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            with Corpus(self.path) as c:
                c.ingest('test', [item(external_id='2')])
                raise ValueError('failure')
        self.assertEqual(self.path.read_bytes(), original)

    def test_failed_generator_rolls_back_items_contacts_and_runs(self):
        def broken():
            yield item(contact='someone@example.com')
            raise ValueError('bad row')
        with Corpus(self.path) as c:
            with self.assertRaises(ValueError):
                c.ingest('test', broken())
            for table in ('items', 'contacts', 'watermarks', 'ingest_runs'):
                self.assertEqual(c.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_late_and_equal_timestamp_delta_records_survive(self):
        with Corpus(self.path) as c:
            c.ingest('test', [item(external_id='1', ts='2026-01-02')])
            result = c.ingest('test', [item(external_id='2', ts='2026-01-01'), item(external_id='3', ts='2026-01-02')], mode='delta')
            self.assertEqual(result['added'], 2)
            self.assertEqual(result['watermark'], '2026-01-02')

    def test_account_scoped_ids_and_idempotence(self):
        with Corpus(self.path) as c:
            for account in ('one', 'two'):
                self.assertEqual(c.ingest('test', [item(external_id='1')], account=account)['added'], 1)
                self.assertEqual(c.bulk_ingest('test', [item(external_id='1')], account=account)['added'], 0)

    def test_full_body_title_and_url_participate_in_dedup(self):
        rows = [dict(bucket='signal_in', source='test', direction='liked', title='A'),
                dict(bucket='signal_in', source='test', direction='liked', title='B')]
        rows += [dict(bucket='communication', source='test', direction='sent', body='x' * 300 + tail) for tail in ('a', 'b')]
        with Corpus(self.path) as c:
            self.assertEqual(c.bulk_ingest('test', rows)['added'], 4)
            self.assertEqual(c.ingest('test', rows)['added'], 0)

    def test_migration_retains_fts_and_dedup(self):
        self.seed()
        with sqlite3.connect(self.path) as c:
            c.execute("UPDATE items SET id='legacy-id'")
            c.execute('PRAGMA user_version=0')
        with Corpus(self.path) as c:
            self.assertEqual(c.ingest('test', [item()])['added'], 0)
            self.assertEqual(len(search(c, 'hello')), 1)
            self.assertEqual(c.db.execute('PRAGMA user_version').fetchone()[0], 2)

    def test_shrink_guard(self):
        self.seed()
        with self.assertRaisesRegex(RuntimeError, '90%'):
            with Corpus(self.path) as c:
                c.db.execute('DELETE FROM items')
        with Corpus(self.path, readonly=True) as c:
            self.assertEqual(c.db.execute('SELECT COUNT(*) FROM items').fetchone()[0], 1)

    def test_invalid_bucket_rolls_back(self):
        with Corpus(self.path) as c:
            with self.assertRaises(ValueError):
                c.ingest('test', [{'bucket': 'bad'}])

    def test_escaped_uri_filename(self):
        special = self.root / 'corpus?#.db'
        with Corpus(special) as c:
            c.ingest('test', [item()])
        with Corpus(special, readonly=True) as c:
            self.assertEqual(len(search(c, 'hello')), 1)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlinks')
    def test_symlink_destination_rejected(self):
        self.seed()
        link = self.root / 'linked.db'
        link.symlink_to(self.path)
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            Corpus(link)

    def test_input_sqlite_missing_is_not_created(self):
        missing = self.root / 'chat.db'
        with self.assertRaises(sqlite3.OperationalError):
            list(parse_imessage(missing))
        self.assertFalse(missing.exists())

    def test_gmail_identity_exact_address(self):
        path = self.root / 'gmail.json'
        path.write_text(json.dumps({'threads': [{'messages': [
            {'sender': 'you@example.com <attacker@example.net>'},
            {'sender': 'You <you@example.com>'}]}]}))
        self.assertEqual([r['direction'] for r in parse_gmail_threads_json(path, ['you@example.com'])], ['received', 'sent'])

    def test_mbox_references_is_scalar(self):
        path = self.root / 'sent.mbox'
        path.write_text('From sender Thu Jan 1 00:00:00 2026\nFrom: you@example.com\nTo: friend@example.com\nReferences: <first> <second>\n\nHello\n')
        rows = list(parse_mbox(path, ['you@example.com']))
        self.assertEqual(rows[0]['thread_id'], '<first>')
        with Corpus(self.path) as c:
            self.assertEqual(c.ingest('gmail', rows)['added'], 1)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT/'engine/run_ingest.py'), *args, '--db', str(self.path)], capture_output=True, text=True)

    def test_cli_bad_kind_does_not_create_store(self):
        self.assertNotEqual(self.cli('bad', str(self.root)).returncode, 0)
        self.assertFalse(self.path.exists())

    def test_csv_validation_and_bom_import(self):
        csv = self.root/'data.csv'
        csv.write_text('\ufeffTitle\nExample\n')
        self.assertNotEqual(self.cli('csv', str(csv)).returncode, 0)
        self.assertFalse(self.path.exists())
        result = self.cli('csv', str(csv), '--source', 'example', '--bucket', 'signal_in', '--direction', 'liked', '--map', 'title=Title', '--account', 'one')
        self.assertEqual(result.returncode, 0, result.stderr)
        with Corpus(self.path, readonly=True) as c:
            row = c.db.execute('SELECT title,source_account FROM items').fetchone()
            self.assertEqual(tuple(row), ('Example', 'one'))

    def test_cli_failed_jsonl_preserves_store(self):
        self.seed()
        original = self.path.read_bytes()
        path = self.root/'broken.jsonl'
        path.write_text(json.dumps(item(external_id='2'))+'\ninvalid\n')
        self.assertNotEqual(self.cli('jsonl', str(path)).returncode, 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(Path(str(self.path)+'.lock').exists())


class AdditionalRegressionTests(unittest.TestCase):
    setUp = EngineTests.setUp
    tearDown = EngineTests.tearDown
    seed = EngineTests.seed
    cli = EngineTests.cli
    def test_wal_backup_includes_committed_rows(self):
        self.seed()
        src = sqlite3.connect(self.path)
        try:
            src.execute('PRAGMA journal_mode=WAL')
            src.execute("INSERT INTO sources(name) VALUES('wal-visible')")
            src.commit()
            with Corpus(self.path, readonly=True) as reader:
                self.assertIsNotNone(reader.db.execute("SELECT 1 FROM sources WHERE name='wal-visible'").fetchone())
            writer = Corpus(self.path)
            try:
                self.assertIsNotNone(writer.db.execute("SELECT 1 FROM sources WHERE name='wal-visible'").fetchone())
                with self.assertRaisesRegex(RuntimeError, 'sidecars'):
                    writer.sync()
            finally:
                writer.close(save=False)
        finally:
            src.close()

    def test_identity_file_import(self):
        path = self.root / 'gmail.json'
        path.write_text(json.dumps({'threads': [{'messages': [{'id': '1', 'sender': 'You <you@example.com>', 'snippet': 'A message'}]}]}))
        identity = self.root / 'identity.json'
        identity.write_text(json.dumps({'emails': ['you@example.com']}))
        result = self.cli('gmailjson', str(path), '--identity', str(identity))
        self.assertEqual(result.returncode, 0, result.stderr)
        with Corpus(self.path, readonly=True) as c:
            self.assertEqual(c.db.execute('SELECT direction FROM items').fetchone()[0], 'sent')

    def test_international_phone_not_truncated(self):
        from corpus import norm_handle
        self.assertEqual(norm_handle('+62 812 3456 7890'), '+6281234567890')
        self.assertEqual(norm_handle('user123456789012'), 'user123456789012')

    def test_cross_source_missing_evidence_not_suppressed(self):
        with Corpus(self.path) as c:
            c.ingest('first', [dict(bucket='communication', source='first', direction='sent', body='hello', contact='friend')])
            result = c.ingest('second', [dict(bucket='communication', source='second', direction='sent', body='hello', contact='friend')], dedupe_against=['first'])
            self.assertEqual(result['added'], 1)

    def test_field_delimiters_do_not_collide(self):
        a = dict(source='test', source_account='a\0b', external_id='c')
        b = dict(source='test', source_account='a', external_id='b\0c')
        self.assertNotEqual(Corpus.item_id(a, None), Corpus.item_id(b, None))

    def test_zero_external_id_is_stable(self):
        self.assertEqual(Corpus.item_id(dict(source='test', external_id=0), None), Corpus.item_id(dict(source='test', external_id='0'), None))

if __name__ == '__main__':
    unittest.main()

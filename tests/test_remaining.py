"""Security, compatibility, and lifecycle regressions; synthetic data only."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'engine'))
from corpus import Corpus, norm_handle
from input_safety import inspect_input, read_text, text_lines
from parsers.exports import parse_instagram_dm, parse_facebook_messenger, parse_whatsapp


def record(**fields):
    return dict(source='test', bucket='communication', direction='sent', body='hello', **fields)


class RemainingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root/'corpus.db'

    def tearDown(self):
        self.tmp.cleanup()

    def seed(self):
        with Corpus(self.db) as c:
            c.ingest('test', [record(external_id='original')])

    def test_colliding_external_ids_preserve_variants_idempotently(self):
        with Corpus(self.db) as c:
            rows = [record(external_id='same', title='one'), record(external_id='same', title='two')]
            self.assertEqual(c.ingest('test', rows)['added'], 2)
            self.assertEqual(c.ingest('test', reversed(rows))['added'], 0)
            self.assertEqual(c.db.execute('SELECT COUNT(*) FROM items_fts').fetchone()[0], 2)

    def test_national_phone_is_not_assigned_a_country(self):
        self.assertEqual(norm_handle('0812 345 678'), '0812345678')
        self.assertNotEqual(norm_handle('0812345678'), norm_handle('+10812345678'))

    def test_explicit_alias_can_reuse_legacy_contact_without_rewriting_history(self):
        with Corpus(self.db) as c:
            c.ingest('test', [record(contact='+15551234567')])
        with Corpus(self.db, contact_aliases={'5551234567': '+15551234567'}) as c:
            self.assertEqual(c.ingest('test', [record(contact='5551234567')])['added'], 0)
            self.assertEqual(c.db.execute('SELECT COUNT(*) FROM contacts').fetchone()[0], 1)

    def test_alias_validation_before_database_write(self):
        with self.assertRaises(ValueError):
            Corpus(self.db, contact_aliases={'phone': []})
        self.assertFalse(self.db.exists())

    def test_meta_same_timestamp_and_title_different_threads_survive(self):
        for folder in ('thread_one', 'thread_two'):
            path = self.root/folder
            path.mkdir()
            (path/'message_1.json').write_text(json.dumps({'title':'Shared title','participants':[{'name':'Me'},{'name':'Friend'},{'name':'Other'}], 'messages':[{'sender_name':'Me','content':'same words','timestamp_ms':1000}]}))
        for parser in (parse_instagram_dm, parse_facebook_messenger):
            with self.subTest(parser=parser.__name__):
                rows = list(parser(self.root, 'Me'))
                with Corpus(self.root/(parser.__name__+'.db')) as c:
                    self.assertEqual(c.ingest('meta', rows)['added'], 2)
                    self.assertEqual(c.ingest('meta', rows)['added'], 0)
                    self.assertNotEqual(rows[0]['contact']['handle'], rows[1]['contact']['handle'])

    def test_missing_meta_timestamp_is_not_1970(self):
        (self.root/'message_1.json').write_text(json.dumps({'messages':[{'sender_name':'Friend','content':'hello'}]}))
        self.assertIsNone(list(parse_instagram_dm(self.root,'Me'))[0]['ts'])

    def test_whatsapp_dmy_multiline_and_system_notice(self):
        path=self.root/'chat.txt'
        path.write_text('[31/12/2025, 23:59:00] Me: hello\ncontinued\n[01/01/2026, 00:00:00] Messages are encrypted\n[01/01/2026, 00:01:00] Friend: yes\n')
        rows=list(parse_whatsapp(path,'Me','thread',date_order='dmy'))
        self.assertEqual(rows[0]['ts'],'2025-12-31T23:59:00')
        self.assertEqual(rows[0]['body'],'hello\ncontinued')
        self.assertEqual(len(rows),2)

    def test_byte_and_document_limits(self):
        path=self.root/'file.json'
        path.write_bytes(b'x'*20)
        with self.assertRaises(ValueError): inspect_input(path,max_bytes=10)
        with patch('input_safety.MAX_DOCUMENT_BYTES',10):
            with self.assertRaises(ValueError): read_text(path)
        with patch('input_safety.MAX_LINE_BYTES',10):
            with self.assertRaises(ValueError): list(text_lines(path))

    def test_entry_limit(self):
        for i in range(4): (self.root/str(i)).write_text('')
        with self.assertRaises(ValueError): inspect_input(self.root,max_files=2)

    @unittest.skipUnless(os.name=='posix', 'POSIX symlink fixture')
    def test_symlink_input_refused(self):
        source=self.root/'source';source.write_text('')
        (self.root/'link').symlink_to(source)
        with self.assertRaises(ValueError): inspect_input(self.root)

    def test_item_budget_rolls_back(self):
        with Corpus(self.db,max_items=1) as c:
            with self.assertRaises(ValueError): c.ingest('test',[record(external_id='1'),record(external_id='2')])
            self.assertEqual(c.db.execute('SELECT COUNT(*) FROM items').fetchone()[0],0)

    def test_future_schema_refused_without_modifying_store(self):
        self.seed()
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA user_version=99')
        before=self.db.read_bytes()
        with self.assertRaises(ValueError): Corpus(self.db)
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(Path(str(self.db)+'.lock').exists())

    def test_invalid_item_type_diagnostics_do_not_include_body(self):
        with Corpus(self.db) as c:
            with self.assertRaisesRegex(ValueError,'Item 1: ts') as caught:
                c.ingest('test',[record(ts=['secret-value'])])
            self.assertNotIn('secret-value',str(caught.exception))

    def test_empty_cli_source_requires_explicit_override(self):
        path=self.root/'empty.jsonl';path.write_text('')
        args=[sys.executable,str(ROOT/'engine/run_ingest.py'),'jsonl',str(path),'--db',str(self.db)]
        result=subprocess.run(args,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('No records recognized',result.stderr)
        self.assertFalse(self.db.exists())
        self.assertEqual(subprocess.run(args+['--allow-empty'],capture_output=True).returncode,0)

    def test_interrupted_process_preserves_store_and_leaves_lock_for_inspection(self):
        self.seed();before=self.db.read_bytes()
        program='''from corpus import Corpus
import sys,time
c=Corpus(sys.argv[1])
c.ingest('test',[dict(source='test',bucket='communication',direction='sent',body='new')])
print(c.work_path,flush=True)
time.sleep(60)
'''
        env=dict(os.environ,PYTHONPATH=str(ROOT/'engine'),CORPUS_WORK=str(self.root))
        process=subprocess.Popen([sys.executable,'-c',program,str(self.db)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        try:
            work=process.stdout.readline().strip()
            self.assertTrue(Path(work).is_file())
            process.kill();process.wait(timeout=10)
        finally:
            if process.poll() is None: process.kill();process.wait(timeout=10)
            process.stdout.close();process.stderr.close()
        self.assertEqual(self.db.read_bytes(),before)
        with self.assertRaisesRegex(RuntimeError,'locked'): Corpus(self.db)
        if os.name=='posix': self.assertEqual(Path(work).parent.stat().st_mode & 0o777,0o700)

    def test_failed_copy_preserves_original_and_cleans_up(self):
        self.seed();before=self.db.read_bytes()
        with self.assertRaises(OSError):
            with Corpus(self.db) as c:
                c.ingest('test',[record(external_id='new')])
                with patch('corpus.shutil.copyfileobj',side_effect=OSError('disk full')): c.sync()
        self.assertEqual(self.db.read_bytes(),before)
        self.assertFalse(list(self.root.glob('.corpus-*.tmp')))

    def test_streamed_large_ingest_and_repeat(self):
        with Corpus(self.db) as c:
            self.assertEqual(c.bulk_ingest('test',(record(external_id=str(i)) for i in range(10000)))['added'],10000)
            self.assertEqual(c.ingest('test',(record(external_id=str(i)) for i in range(10000)),mode='delta')['added'],0)

class VariantTests(unittest.TestCase):
    def test_ratings_and_metadata_variants_are_not_lost(self):
        with tempfile.TemporaryDirectory() as temp:
            with Corpus(Path(temp)/'corpus.db') as c:
                rows=[dict(source='test',bucket='signal_in',direction='rated',title='Example',rating=n) for n in (1,2,3)]
                self.assertEqual(c.ingest('test',rows)['added'],3)
                self.assertEqual(c.ingest('test',reversed(rows))['added'],0)
                rows=[dict(source='test',bucket='signal_in',direction='liked',external_id='same',meta={'label':n}) for n in ('a','b')]
                self.assertEqual(c.ingest('test',rows)['added'],2)
                self.assertEqual(c.ingest('test',rows)['added'],0)


class VoiceTests(unittest.TestCase):
    def test_retweets_are_not_self_authored_voice(self):
        from query import voice_sample
        with tempfile.TemporaryDirectory() as temp:
            with Corpus(Path(temp)/'corpus.db') as c:
                c.ingest('twitter',[dict(source='twitter_posts',bucket='published',direction='posted',body='RT other words',meta={'retweet':True}),dict(source='twitter_posts',bucket='published',direction='posted',body='My original words')])
                self.assertEqual([r['body'] for r in voice_sample(c)],['My original words'])


class SenderCompatibilityTests(unittest.TestCase):
    def test_ambiguous_sender_is_unclassified(self):
        from parsers.exports import _sender_address
        self.assertEqual(_sender_address('you@example.com <attacker@example.net>'),'attacker@example.net')
        self.assertEqual(_sender_address('"Display Name" <you@example.com>'),'you@example.com')
        self.assertIsNone(_sender_address('you@example.com, attacker@example.net'))
        self.assertIsNone(_sender_address('You <you@example.com>, Other <other@example.com>'))
        self.assertIsNone(_sender_address('you@example.com\r\nBcc: other@example.com'))

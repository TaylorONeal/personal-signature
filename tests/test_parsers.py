"""Representative synthetic export fixtures for source regressions."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine'))
from corpus import Corpus
from parsers.exports import parse_imessage, parse_whatsapp_ios, parse_slack_export, parse_twitter_archive, parse_whatsapp


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_imessage_readonly_fixture(self):
        path = self.root/'chat.db'
        with sqlite3.connect(path) as c:
            c.executescript('''CREATE TABLE message(text,attributedBody,is_from_me,date,handle_id);
            CREATE TABLE handle(id); CREATE TABLE chat(chat_identifier);
            CREATE TABLE chat_message_join(message_id,chat_id);
            INSERT INTO message VALUES('hello',NULL,1,1000000000,1);
            INSERT INTO handle VALUES('friend@example.com');''')
        before = path.read_bytes()
        rows = list(parse_imessage(path))
        self.assertEqual(rows[0]['direction'], 'sent')
        self.assertEqual(path.read_bytes(), before)

    def test_whatsapp_sqlite_readonly_fixture(self):
        path = self.root/'ChatStorage.sqlite'
        with sqlite3.connect(path) as c:
            c.executescript('''CREATE TABLE ZWAMESSAGE(ZTEXT,ZISFROMME,ZMESSAGEDATE,ZCHATSESSION);
            CREATE TABLE ZWACHATSESSION(Z_PK,ZPARTNERNAME,ZCONTACTJID);
            INSERT INTO ZWAMESSAGE VALUES('hello',0,1000000000,1);
            INSERT INTO ZWACHATSESSION VALUES(1,'Friend','friend');''')
        before = path.read_bytes()
        self.assertEqual(list(parse_whatsapp_ios(path))[0]['direction'], 'received')
        self.assertEqual(path.read_bytes(), before)

    def test_slack_sender_id(self):
        channel = self.root/'general'
        channel.mkdir()
        (channel/'day.json').write_text(json.dumps([{'type':'message','user':'U123','ts':'1700000000','text':'hello'}]))
        row = list(parse_slack_export(self.root, 'workspace', ['U123']))[0]
        self.assertEqual(row['direction'], 'sent')
        self.assertEqual(row['source_account'], 'workspace')

    def test_twitter_dm_iso_timestamp(self):
        data = [{'dmConversation': {'conversationId':'thread', 'messages':[{'messageCreate':{'id':'1','senderId':'123','recipientId':'456','createdAt':'2026-01-01T10:00:00.000Z','text':'hello'}}]}}]
        (self.root/'direct-messages.js').write_text('window.YTD.direct_messages.part0 = '+json.dumps(data))
        row = list(parse_twitter_archive(self.root,'123'))[0]
        self.assertEqual(row['ts'],'2026-01-01T10:00:00')
        self.assertEqual(row['direction'],'sent')

    def test_query_cli_is_readonly_and_validates_limits(self):
        path = self.root/'corpus.db'
        with Corpus(path) as c:
            c.ingest('test',[dict(source='test',bucket='communication',direction='sent',body='hello')])
        before = path.read_bytes()
        query = Path(__file__).resolve().parents[1]/'engine/query.py'
        result = subprocess.run([sys.executable,str(query),'stats','--db',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['items'],1)
        result = subprocess.run([sys.executable,str(query),'voice-sample','-1','--db',str(path)],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(path.read_bytes(),before)

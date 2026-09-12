"""One minimal recognized export for every advertised CLI kind, plus repeat ingest."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SourceContractTests(unittest.TestCase):
    def test_all_seventeen_cli_kinds(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def text(name, body):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(body,encoding='utf-8');return path
            def js(name, value): return text(name,json.dumps(value))
            message={'title':'Friend','participants':[{'name':'Me'},{'name':'Friend'}],'messages':[{'sender_name':'Me','content':'hello','timestamp_ms':1700000000000}]}
            ig=js('ig/messages/inbox/thread/message_1.json',message)
            fb=js('fb/messages/thread/message_1.json',message)
            gmail=js('gmail.json',{'threads':[{'id':'thread','messages':[{'id':'1','sender':'you@example.com','snippet':'hello','date':'2026-01-01T00:00:00'}]}]})
            mbox=text('sent.mbox','From sender Thu Jan 1 00:00:00 2026\nFrom: you@example.com\nTo: friend@example.com\nMessage-ID: <one>\n\nHello\n')
            js('twitter/tweets.js',[{'tweet':{'id_str':'1','full_text':'hello'}}])
            js('slack/general/day.json',[{'type':'message','user':'U1','ts':'1700000000','text':'hello'}])
            js('chat/Groups/DM1/messages.json',{'messages':[{'message_id':'1','text':'hello','creator':{'email':'you@example.com'},'created_date':'Monday, January 01, 2024 at 01:00:00 PM'}]})
            text('voice/Friend - Text - date.html','<div class="message"><abbr class="dt" title="2026-01-01T00:00:00Z"></abbr><abbr class="fn">Me</abbr><q>hello</q></div>')
            wa=text('whatsapp.txt','[01/02/2026, 12:01:00] Me: hello\n')
            bookmarks=text('bookmarks.html','<A HREF="https://example.com" ADD_DATE="1700000000">Example</A>')
            youtube=text('youtube.html','Watched <a href="https://www.youtube.com/watch?v=example">Example</a><br>Jan 1, 2026, 1:00:00 PM')
            text('netflix/ViewingActivity.csv','Start Time,Title\n2026-01-01 00:00:00,Example\n')
            text('yelp/user_review.html','<table><tr><th>Comment</th><th>Business Name</th><th>Date</th></tr><tr><td>Nice</td><td>Example</td><td>2026-01-01</td></tr></table>')
            csv=text('generic.csv','Title\nExample\n')
            jsonl=js('generic.jsonl',{'source':'test','bucket':'signal_in','direction':'liked','title':'Example'})
            im=root/'chat.db'
            with closing(sqlite3.connect(im)) as c,c:
                c.executescript("CREATE TABLE message(text,attributedBody,is_from_me,date,handle_id); CREATE TABLE handle(id); CREATE TABLE chat(chat_identifier); CREATE TABLE chat_message_join(message_id,chat_id); INSERT INTO message VALUES('hello',NULL,1,1000000000,1); INSERT INTO handle VALUES('friend@example.com');")
            wi=root/'whatsapp.sqlite'
            with closing(sqlite3.connect(wi)) as c,c:
                c.executescript("CREATE TABLE ZWAMESSAGE(ZTEXT,ZISFROMME,ZMESSAGEDATE,ZCHATSESSION); CREATE TABLE ZWACHATSESSION(Z_PK,ZPARTNERNAME,ZCONTACTJID); INSERT INTO ZWAMESSAGE VALUES('hello',1,1000000000,1); INSERT INTO ZWACHATSESSION VALUES(1,'Friend','friend');")
            cases=[('mbox',mbox,['--me','you@example.com']),('imessage',im,[]),('gmailjson',gmail,['--me','you@example.com']),('instagram',root/'ig',['--me','Me']),('facebook',root/'fb',['--me','Me']),('twitter',root/'twitter',[]),('slack',root/'slack',['--me','U1']),('googlechat',root/'chat',['--me','you@example.com']),('googlevoice',root/'voice',[]),('whatsapp',wa,['--me','Me','--date-order','dmy']),('whatsapp_ios',wi,[]),('bookmarks',bookmarks,[]),('youtube',youtube,[]),('netflix',root/'netflix',[]),('yelp',root/'yelp',[]),('csv',csv,['--source','test','--bucket','signal_in','--direction','liked','--map','title=Title']),('jsonl',jsonl,[])]
            self.assertEqual(len(cases),17)
            for kind,path,options in cases:
                with self.subTest(kind=kind):
                    command=[sys.executable,str(ROOT/'engine/run_ingest.py'),kind,str(path),'--db',str(root/(kind+'-output.db')),*options]
                    result=subprocess.run(command,capture_output=True,text=True)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertGreater(json.loads(result.stdout)['added'],0)
                    again=subprocess.run(command+['--mode','delta'],capture_output=True,text=True)
                    self.assertEqual(again.returncode,0,again.stderr)
                    self.assertEqual(json.loads(again.stdout)['added'],0)

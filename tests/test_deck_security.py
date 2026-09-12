"""Static deck checks also run on platforms without a browser installation."""
import base64
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest


class DeckSecurityTests(unittest.TestCase):
    def test_standalone_deck_script_and_network_policy(self):
        text=(Path(__file__).resolve().parents[1]/'docs/deck.html').read_text(encoding='utf-8')
        scripts=re.findall(r'<script>(.*?)</script>',text,re.S)
        self.assertEqual(len(scripts),1)
        digest=base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
        self.assertIn("script-src 'sha256-"+digest+"'",text)
        self.assertIn("connect-src 'none'",text)
        self.assertNotIn('postMessage',scripts[0])
        self.assertNotIn('innerHTML',scripts[0])
        self.assertNotIn('fetch(',scripts[0])
        self.assertEqual(len(re.findall(r'<section ',text)),125)
        resources=[]
        class Parser(HTMLParser):
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag in {'script','iframe','img','link','object','embed'}:
                    resources.extend([v for k,v in attrs.items() if k in {'src','href','data'}])
        Parser().feed(text)
        self.assertEqual(resources,[])

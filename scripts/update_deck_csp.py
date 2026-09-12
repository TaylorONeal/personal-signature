"""Refresh the hash for the sole inline deck script after editing it."""
from pathlib import Path
import base64
import hashlib
import re


def main():
    path = Path(__file__).resolve().parents[1] / 'docs' / 'deck.html'
    text = path.read_text(encoding='utf-8')
    scripts = re.findall(r'<script>(.*?)</script>', text, re.S)
    if len(scripts) != 1:
        raise ValueError('The standalone deck must contain exactly one inline script')
    digest = base64.b64encode(hashlib.sha256(scripts[0].encode()).digest()).decode()
    text, count = re.subn(r"script-src 'sha256-[^']+'", f"script-src 'sha256-{digest}'", text)
    if count != 1:
        raise ValueError('Expected one script-src hash')
    path.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()

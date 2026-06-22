#!/usr/bin/env python3
"""Submit clawock URLs to IndexNow (Bing / Yandex / Seznam — NOT Google).

Zero-touch indexing accelerator. Reads the IndexNow key from the repo-root
`<key>.txt` file (32-hex), pulls URLs from the live sitemap, and POSTs them.

Google does not consume IndexNow — for Google use GSC "Request Indexing".

Usage:
  python3 scripts/data/indexnow_submit.py            # submit all sitemap URLs
  python3 scripts/data/indexnow_submit.py <url> ...  # submit specific URLs
"""
import glob
import json
import os
import re
import sys
import urllib.request

HOST = "kcnyu.github.io"
SITE = "https://kcnyu.github.io/clawock"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_key():
    for p in glob.glob(os.path.join(ROOT, "*.txt")):
        name = os.path.splitext(os.path.basename(p))[0]
        if re.fullmatch(r"[0-9a-f]{32}", name):
            return name
    raise SystemExit("ERROR: no IndexNow key file (<32-hex>.txt) at repo root")


def sitemap_urls():
    with urllib.request.urlopen(f"{SITE}/sitemap.xml", timeout=20) as r:
        xml = r.read().decode("utf-8", "replace")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def main():
    key = find_key()
    urls = sys.argv[1:] or sitemap_urls()
    if not urls:
        raise SystemExit("ERROR: no URLs to submit")
    payload = {
        "host": HOST,
        "key": key,
        "keyLocation": f"{SITE}/{key}.txt",
        "urlList": urls,
    }
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"IndexNow HTTP {r.status} — submitted {len(urls)} URL(s)")
        body = r.read().decode("utf-8", "replace").strip()
        if body:
            print(body)


if __name__ == "__main__":
    main()

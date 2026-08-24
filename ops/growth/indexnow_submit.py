#!/usr/bin/env python3
"""Submit clawock URLs to IndexNow (Bing / Yandex / Seznam — NOT Google).

Zero-touch indexing accelerator. Reads the IndexNow key from the site-owned
`site/<key>.txt` file (32-hex), pulls URLs from the live sitemap, and POSTs the ones
that are new or whose content actually changed.

Google does not consume IndexNow — for Google use GSC "Request Indexing".

Change detection hashes each page's response body (sha256), recorded per URL
in `logs/indexnow_seen.json` (machine-local, gitignored). A URL-only ledger
would mean an edited brief, a revised weekly, or a `_layouts/` change is never
re-announced — silently, and forever. IndexNow asks publishers to submit on
change, so re-POSTing unchanged URLs daily is equally wrong in the other
direction.

Not an ETag/Last-Modified comparison: GitHub Pages rebuilds every page on each
push to master and stamps the rebuild batch into every ETag prefix, so
validator-based detection saw every URL as changed dozens of times a day and
re-announced the whole sitemap daily (#975). Body hashing costs one GET per
URL per run; that is the price of "actually changed" meaning anything.

Usage:
  python3 ops/growth/indexnow_submit.py             # new + changed URLs
  python3 ops/growth/indexnow_submit.py --all       # every sitemap URL
  python3 ops/growth/indexnow_submit.py <url> ...   # submit specific URLs
  python3 ops/growth/indexnow_submit.py --record-only  # seed ledger, no POST
  python3 ops/growth/indexnow_submit.py --dry-run   # print, do not POST
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

HOST = "kcnyu.github.io"
SITE = "https://kcnyu.github.io/clawock"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SITE_SOURCE = os.path.join(ROOT, "site")
STATE = os.path.join(ROOT, "logs", "indexnow_seen.json")


def find_key():
    for p in glob.glob(os.path.join(SITE_SOURCE, "*.txt")):
        name = os.path.splitext(os.path.basename(p))[0]
        if re.fullmatch(r"[0-9a-f]{32}", name):
            return name
    raise SystemExit("ERROR: no IndexNow key file (site/<32-hex>.txt)")


def sitemap_urls():
    try:
        with urllib.request.urlopen(f"{SITE}/sitemap.xml", timeout=20) as r:
            xml = r.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        raise SystemExit(f"ERROR: cannot fetch {SITE}/sitemap.xml ({e})")
    return re.findall(r"<loc>([^<]+)</loc>", xml)


def digest(url):
    """sha256 of the response body. None if unreachable — an unreachable page
    is skipped rather than guessed at in either direction."""
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return hashlib.sha256(r.read()).hexdigest()
    except (urllib.error.URLError, OSError) as e:
        print(f"WARN: GET {url} failed ({e}) — skipping this URL", file=sys.stderr)
        return None


def load_seen():
    """URL -> body digest. A missing/corrupt ledger degrades to empty: that
    re-submits once, which beats the cron dying on a bad file. The old ETag-era
    key ("validators") is gone by design (#975): reading it back would keep the
    daily full-resubmit alive for one more generation."""
    try:
        with open(STATE, encoding="utf-8") as f:
            data = json.load(f)
        seen = data["digests"]
        if not isinstance(seen, dict):
            raise TypeError("digests is not an object")
        return seen
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"WARN: unreadable {STATE} ({e}) — treating as empty", file=sys.stderr)
        return {}


def save_seen(updates):
    """Merge `updates` into whatever is on disk right now.

    A concurrent run (daily cron overlapping a manual --all) must not clobber
    the other's entries, so this re-reads before writing and uses a
    PID-suffixed temp file — two processes sharing one `.tmp` path can make
    os.replace race into FileNotFoundError.
    """
    merged = load_seen()
    merged.update(updates)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = f"{STATE}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"digests": dict(sorted(merged.items()))}, f, indent=1)
        os.replace(tmp, STATE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def select(args):
    """Return (urls_to_submit, {url: digest} to record on success)."""
    if args.urls:
        return args.urls, {u: d for u in args.urls if (d := digest(u))}
    urls = sitemap_urls()
    if not urls:
        raise SystemExit("ERROR: sitemap returned no URLs")
    seen = load_seen()
    current = {u: d for u in urls if (d := digest(u)) is not None}
    if args.all:
        return urls, current
    changed = [u for u in urls if u in current and current[u] != seen.get(u)]
    return changed, {u: current[u] for u in changed}


def post(key, urls):
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


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("urls", nargs="*", help="submit these URLs instead of the sitemap")
    p.add_argument("--all", action="store_true", help="submit every sitemap URL")
    p.add_argument("--dry-run", action="store_true", help="print, do not POST")
    p.add_argument("--record-only", action="store_true",
                   help="record current digests without submitting "
                        "(seeds the ledger after a manual backfill)")
    args = p.parse_args(argv)
    if args.urls and args.all:
        p.error("--all cannot be combined with explicit URLs")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    # A real submission cannot possibly succeed without the public key. Resolve
    # it before fetching the sitemap and fetching each URL body, so a deleted
    # or unpublished key fails cheaply instead of doing guaranteed-wasted work.
    # Inspection modes deliberately remain useful while the key is being fixed.
    key = None if args.record_only or args.dry_run else find_key()
    urls, record = select(args)
    if args.record_only:
        save_seen(record)
        print(f"IndexNow — recorded {len(record)} digest(s), submitted nothing")
        return
    if not urls:
        print("IndexNow — nothing new or changed to submit")
        return
    if args.dry_run:
        print(f"IndexNow dry-run — would submit {len(urls)} URL(s):")
        print("\n".join(urls))
        return
    post(key, urls)
    # Record only after the POST is accepted, so a failed run retries instead of
    # marking the URLs as done forever.
    save_seen(record)


if __name__ == "__main__":
    main()

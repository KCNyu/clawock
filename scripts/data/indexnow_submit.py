#!/usr/bin/env python3
"""Submit clawock URLs to IndexNow (Bing / Yandex / Seznam — NOT Google).

Zero-touch indexing accelerator. Reads the IndexNow key from the repo-root
`<key>.txt` file (32-hex), pulls URLs from the live sitemap, and POSTs them.

Google does not consume IndexNow — for Google use GSC "Request Indexing".

Default mode is incremental: only URLs never submitted before, plus the pages
that genuinely change every day (dashboard + brief index). IndexNow asks
publishers to submit on change, so re-POSTing every unchanged URL daily is both
wasteful and spam-shaped. Submitted URLs are remembered in
`logs/indexnow_seen.json` (machine-local, gitignored).

Usage:
  python3 scripts/data/indexnow_submit.py            # new URLs + daily-changing pages
  python3 scripts/data/indexnow_submit.py --all      # every sitemap URL (backfill)
  python3 scripts/data/indexnow_submit.py <url> ...  # submit specific URLs
  python3 scripts/data/indexnow_submit.py --dry-run  # print, do not POST
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
STATE = os.path.join(ROOT, "logs", "indexnow_seen.json")

# Pages regenerated daily, so re-submitting them is a genuine "this changed"
# signal rather than spam.
ALWAYS = (f"{SITE}/", f"{SITE}/briefs.html")


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


def load_seen():
    """Previously submitted URLs. A missing/corrupt ledger degrades to empty:
    that re-submits once, which beats the cron dying on a bad file."""
    try:
        with open(STATE, encoding="utf-8") as f:
            data = json.load(f)
        return set(data["urls"])
    except FileNotFoundError:
        return set()
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"WARN: unreadable {STATE} ({e}) — treating as empty", file=sys.stderr)
        return set()


def save_seen(urls):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = f"{STATE}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"urls": sorted(urls)}, f, indent=1)
    os.replace(tmp, STATE)


def select(argv):
    """Return (urls_to_submit, ledger_after_success)."""
    explicit = [a for a in argv if not a.startswith("--")]
    if explicit:
        return explicit, load_seen() | set(explicit)
    urls = sitemap_urls()
    if not urls:
        raise SystemExit("ERROR: sitemap returned no URLs")
    if "--all" in argv:
        return urls, set(urls)
    seen = load_seen()
    fresh = [u for u in urls if u not in seen]
    daily = [u for u in ALWAYS if u in urls and u not in fresh]
    return fresh + daily, seen | set(urls)


def main():
    argv = sys.argv[1:]
    key = find_key()
    urls, ledger = select(argv)
    if not urls:
        print("IndexNow — nothing new to submit")
        return
    if "--dry-run" in argv:
        print(f"IndexNow dry-run — would submit {len(urls)} URL(s):")
        print("\n".join(urls))
        return
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
    # Record only after the POST is accepted, so a failed run retries next time.
    save_seen(ledger)


if __name__ == "__main__":
    main()

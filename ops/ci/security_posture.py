#!/usr/bin/env python3
"""Report which of GitHub's free security features this repository is not using.

Written for #787, where two toggles were found off:

    secret_scanning_non_provider_patterns   disabled
    secret_scanning_validity_checks         disabled

Neither can be turned on from here. `PATCH /repos/{owner}/{repo}` returns 200
and silently ignores both fields — verified by sending a deliberately invalid
value, which was also accepted and also ignored — and the code-security
configurations API is organization-only while this is a user account. They are
web-UI switches.

So the useful thing a script can do is refuse to let them be forgotten. A
finding that requires a human click has a short half-life in a chat log and an
indefinite one in a weekly check.

Why these two matter here specifically: the default secret scanner only knows
patterns with a recognisable provider prefix. Non-provider patterns are what
catch a private key block, a connection string, or a credential pasted into
prose — and this repository commits a great deal of model-written prose under
memory/ and logs/, while holding a deploy key and a .api_keys file whose names
are already explicitly blocked from PRs. That block is on filenames. It cannot
see content. Validity checks answer the only question that matters during an
actual leak: is this credential still live.

Usage:
    security_posture.py            # report; exit 1 if something is off
    security_posture.py --warn     # report; always exit 0 (annotations only)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

REPO = os.environ.get("CLAWOCK_TRAFFIC_REPO", "KCNyu/clawock")

# (field, human name, why it is not decoration here)
EXPECTED = [
    ("secret_scanning", "Secret scanning",
     "the baseline; everything else here is an extension of it"),
    ("secret_scanning_push_protection", "Push protection",
     "blocks the commit rather than reporting it afterwards"),
    ("secret_scanning_non_provider_patterns", "Non-provider patterns",
     "the only thing that sees a private key or connection string pasted into "
     "prose; the PR path policy blocks filenames, not content"),
    ("secret_scanning_validity_checks", "Validity checks",
     "answers 'is this credential still live', which is the first question "
     "during a real leak and the slowest one to answer by hand"),
    ("dependabot_security_updates", "Dependabot security updates",
     "only produces alerts for trees an ecosystem entry makes visible"),
]

SETTINGS_URL = f"https://github.com/{REPO}/settings/security_analysis"


def fetch(token: str) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "clawock-security-posture (+https://github.com/KCNyu/clawock)",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def evaluate(security: dict) -> list[tuple[str, str, str, str]]:
    """Returns (field, name, state, why) for everything not enabled."""
    off = []
    for field, name, why in EXPECTED:
        state = (security.get(field) or {}).get("status", "absent")
        if state != "enabled":
            off.append((field, name, state, why))
    return off


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--warn", action="store_true",
                    help="annotate but never fail the job")
    args = ap.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("::error::GITHUB_TOKEN/GH_TOKEN is unset — the security posture "
              "cannot be read, which is not the same as it being fine",
              file=sys.stderr)
        return 2

    try:
        security = fetch(token).get("security_and_analysis") or {}
    except urllib.error.HTTPError as exc:
        # A fine-grained token without administration:read gets 200 on the repo
        # but no security_and_analysis block. A hard error is different and
        # should say so rather than read as "all clear".
        print(f"::error::cannot read repository settings: HTTP {exc.code}", file=sys.stderr)
        return 2

    if not security:
        print("::warning::the token cannot see security_and_analysis — posture unknown, "
              "not verified")
        return 0 if args.warn else 1

    for field, name, why in EXPECTED:
        state = (security.get(field) or {}).get("status", "absent")
        mark = "✓" if state == "enabled" else "✗"
        print(f"{mark} {name:<32} {state}")

    off = evaluate(security)
    if not off:
        print("\nall of GitHub's free secret-scanning features are on")
        return 0

    print(f"\n{len(off)} feature(s) off. None of these can be enabled from the API — "
          f"`PATCH /repos/{{owner}}/{{repo}}` accepts the field and ignores it "
          f"(#787), so they are web-UI switches:")
    print(f"  {SETTINGS_URL}")
    for _, name, state, why in off:
        print(f"\n  {name} — {state}")
        print(f"    {why}")
        print(f"::warning::{name} is {state}: {why}")

    return 0 if args.warn else 1


if __name__ == "__main__":
    raise SystemExit(main())

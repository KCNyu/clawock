#!/usr/bin/env python3
"""Report which of GitHub's free security features this repository is not using.

Written for #787, where two toggles were found off:

    secret_scanning_non_provider_patterns   disabled
    secret_scanning_validity_checks         disabled

Neither can be turned on at all on this repository, and the reason is not
permissions — it is what kind of repository this is:

  * `PATCH /repos/{owner}/{repo}` returns 200 and silently drops both fields.
    That endpoint does validate what it actually processes (asking it for
    `code_security` returns 422 "Code Security can only be enabled if Advanced
    Security is enabled"), so a silently dropped field never reached the
    handler.
  * Asking for `advanced_security` returns 422 "Advanced security is always
    available for public repos" — it cannot be enabled because it is nominally
    already there.
  * And yet `GET /repos/{owner}/{repo}/secret-scanning/scan-history` answers
    "Advanced Security is disabled on this repository."

"Always available" and "is disabled" hold at the same time. That is the real
state of a public repository: secret scanning itself is free, but the switches
layered on top of it hang off an enablement that exists only for GitHub
Advanced Security customers — a private repo with GHAS, or an organization's
code security configurations. This is a user account, so
`/orgs/{org}/code-security/configurations` 404s.

kcn confirmed on 2026-08-22 that the settings page offers nothing further:
"能开的都开了".

So this script must NOT nag about them. A weekly warning nobody can act on is a
false alarm with a schedule, and it trains people to skim exactly the check that
is supposed to be worth reading. What it reports instead is the distinction that
matters: a feature that is off **and available** is a to-do; a feature that is
off because the platform does not offer it here is a fact, and it only becomes a
to-do again if that changes — the repository going private with GHAS, or moving
under an organization.

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

# Features whose enablement is gated behind GitHub Advanced Security being
# genuinely enabled — which never happens on a public repository (see the module
# docstring). Off is reported as unavailable, not as a to-do.
GHAS_GATED = frozenset({
    "secret_scanning_non_provider_patterns",
    "secret_scanning_validity_checks",
})

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


def evaluate(security: dict, ghas_enabled: bool) -> tuple[list, list]:
    """Split what is off into (actionable, unavailable).

    `ghas_enabled` decides which side the GHAS-gated features land on. Passing
    it in rather than reading it here keeps the classification testable without
    a network call, and keeps the probe honest: unknown must never quietly mean
    "unavailable", which would suppress a real finding forever.
    """
    actionable, unavailable = [], []
    for field, name, why in EXPECTED:
        state = (security.get(field) or {}).get("status", "absent")
        if state == "enabled":
            continue
        row = (field, name, state, why)
        if field in GHAS_GATED and not ghas_enabled:
            unavailable.append(row)
        else:
            actionable.append(row)
    return actionable, unavailable


def ghas_is_enabled(token: str) -> bool:
    """Probe whether the GHAS-gated switches can be set on this repository.

    scan-history is the honest read: it answers "Advanced Security is disabled
    on this repository" for a public repo, while the repository PATCH endpoint
    insists advanced security is "always available". Nothing in
    security_and_analysis distinguishes the two states, so the probe has to be a
    separate endpoint.

    Fails closed toward *actionable*: if the probe cannot tell, the feature is
    reported as a to-do rather than silently written off.
    """
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/secret-scanning/scan-history",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "clawock-security-posture (+https://github.com/KCNyu/clawock)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            body = exc.read().decode("utf-8", "replace")
            if "Advanced Security is disabled" in body:
                return False
        return True
    except Exception:  # noqa: BLE001
        return True


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

    ghas = ghas_is_enabled(token)
    actionable, unavailable = evaluate(security, ghas)
    unavailable_fields = {row[0] for row in unavailable}

    for field, name, why in EXPECTED:
        state = (security.get(field) or {}).get("status", "absent")
        if state == "enabled":
            mark = "✓"
        elif field in unavailable_fields:
            mark = "—"
            state = f"{state} (not offered on this repository)"
        else:
            mark = "✗"
        print(f"{mark} {name:<32} {state}")

    if unavailable:
        print("\nOff because GitHub does not offer them here, not because nobody got "
              "round to it (#787). These switches hang off GitHub Advanced Security "
              "being genuinely enabled, which does not happen on a public repository: "
              "the repo endpoint says advanced security is \"always available for public "
              "repos\" and refuses to enable it, while scan-history answers \"Advanced "
              "Security is disabled on this repository\". Both are true at once. They "
              "become to-dos again only if this repo goes private with GHAS, or moves "
              "under an organization with a code security configuration.")
        for _, name, _, _ in unavailable:
            print(f"  — {name}")

    if not actionable:
        print("\nevery secret-scanning feature this repository can have is on")
        return 0

    print(f"\n{len(actionable)} feature(s) off and enable-able:")
    print(f"  {SETTINGS_URL}")
    for _, name, state, why in actionable:
        print(f"\n  {name} — {state}")
        print(f"    {why}")
        print(f"::warning::{name} is {state}: {why}")

    return 0 if args.warn else 1


if __name__ == "__main__":
    raise SystemExit(main())

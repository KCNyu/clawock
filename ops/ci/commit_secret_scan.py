#!/usr/bin/env python3
"""Scan the lines a commit range adds for credential-shaped values (#2033).

Why this exists: the initial public commit (2026-03-11) carried three market-data
keys in TOOLS.md and four scripts. Nothing on either side could have stopped it:

  * GitHub's secret scanner only knows provider-prefixed patterns; the switches
    that would see a bare random string next to a variable name are GHAS-gated
    and cannot be turned on here (ops/ci/security_posture.py).
  * .githooks/pre-commit scans the staged diff, excludes *.md on purpose (a
    2026-07-15 false positive), and is a manual per-clone install that CI never
    runs.

This is the CI half: every commit in the range a PR (or a code push) brings,
every path including Markdown, only the added lines. The shapes are the ones the
leak actually had — a named assignment, a `token=` URL parameter, a `**Provider**:
value` documentation line — plus the provider prefixes the maintainer already
blocks in the hook. A value must mix letters and digits, so identifiers such as
`api_key = get_finnhub_key` and placeholders such as `YOUR_API_KEY_HERE` are not
reported.

A second tier, STRUCTURAL, holds the shapes that need no variable name beside
them: a PEM private-key header, a service-account key id, fixed-prefix vendor
tokens, a URL carrying a password (#2528). They are the platform's "non-provider
patterns", which this repository cannot switch on (ops/ci/security_posture.py),
so this file is the only content gate that sees them — in prose as well as code.
A whole-tree tier with the same list lived in ops/system_check.py until it was
removed as unreferenced; it belongs here, on the three paths that actually run.

Findings print provider/variable, commit and path — never the value
(.github/SECURITY.md: "never paste a credential ... into" a public place). A
value's length and sha256 prefix are printed so the maintainer can compare it
with the live one without it appearing in the log.

The history that is already public is not re-scanned here: its known residue and
rotation status are recorded in .github/SECURITY.md § Known exposures.

Usage:
    commit_secret_scan.py --range BASE..HEAD
    commit_secret_scan.py --commit SHA [--commit SHA ...]
    (reads a unified diff on stdin with --stdin, for tests)
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass

_VALUE = r"([A-Za-z0-9_:\-]{16,})"

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # FINNHUB_API_KEY = 'abc…', POLYGON_API_KEY: abc…, export X_TOKEN="…"
    ("named assignment", re.compile(
        r"\b([A-Za-z][A-Za-z0-9_]*_(?:API_?KEY|TOKEN|SECRET|APIKEY))\b['\"]?\s*[:=]\s*['\"]?"
        + _VALUE + r"['\"]?(?=\s|$|[,;)&#])", re.IGNORECASE)),
    # api_key = 'abc…' — a bare generic name only counts with a quoted literal.
    ("quoted credential literal", re.compile(
        r"\b(api_?key|apikey|token|secret|access_?token)\s*[:=]\s*['\"]" + _VALUE + r"['\"]",
        re.IGNORECASE)),
    # https://finnhub.io/api/v1/quote?symbol=X&token=abc…
    ("URL credential parameter", re.compile(
        r"[?&]((?:token|api_?key|apikey|access_?key|key))=" + _VALUE, re.IGNORECASE)),
    # - **Finnhub**: abc…   (the TOOLS.md shape)
    ("documented credential line", re.compile(
        r"\*\*([A-Za-z][A-Za-z .]{2,24})\*\*\s*[:：]\s*`?([A-Za-z0-9]{16,})`?\s*$")),
    # Provider prefixes the pre-commit hook already treats as secrets.
    ("provider-prefixed token", re.compile(
        r"\b((?:sk|tp|tvly)-)([A-Za-z0-9]{20,})\b")),
]

_URL_PASSWORD = "URL with a password"

# Shapes that are a credential on their own, wherever they sit. Group 1 names the
# shape's marker and group 2 is the value, like PATTERNS; the letters-and-digits
# test does not apply (a PEM header has no digits). Lengths are floors, not the
# vendor's exact length: a token one character short of today's format is still
# a token.
STRUCTURAL: list[tuple[str, re.Pattern[str]]] = [
    ("PEM private key", re.compile(r"(-----BEGIN )([A-Z ]*PRIVATE KEY-----)")),
    # Keyed on the 40-hex id, not on "type": "service_account", which any setup
    # document may quote.
    ("service-account key id", re.compile(
        r"\"(private_key_id)\"\s*:\s*\"([0-9a-f]{40})\"")),
    # No trailing \b where the charset includes '-' or '_': a key ending in one
    # has no word boundary after it.
    ("Google API key", re.compile(r"\b(AIza)([0-9A-Za-z_-]{35})")),
    ("Telegram bot token", re.compile(r"\b([0-9]{8,10}:AA)([A-Za-z0-9_-]{30,})")),
    ("GitHub token", re.compile(
        r"\b(gh[pousr]_|github_pat_)([A-Za-z0-9_]{30,})")),
    ("AWS access key id", re.compile(r"\b(AKIA)([0-9A-Z]{16})\b")),
    ("Slack token", re.compile(r"\b(xox[baprs]-)([A-Za-z0-9-]{10,})")),
    ("Nostr signing key", re.compile(r"\b(nsec1)([02-9ac-hj-np-z]{58})\b")),
    # A URL whose authority carries a password: the user is the name, the
    # password the value. A template slot in that position is not a finding.
    (_URL_PASSWORD, re.compile(
        r"\b[a-z][a-z0-9+.-]*://([^\s:/@'\"]+):([^\s/@'\"]{6,})@[A-Za-z0-9.\-\[]")),
]

_PLACEHOLDER = re.compile(r"(?i)your|example|placeholder|xxxx|dummy|redacted|changeme")


@dataclass(frozen=True)
class Finding:
    commit: str
    path: str
    kind: str
    name: str
    value: str

    def describe(self) -> str:
        digest = hashlib.sha256(self.value.encode()).hexdigest()[:12]
        return (f"{self.commit[:9]} {self.path}: {self.kind} `{self.name}` "
                f"(len={len(self.value)} sha256:{digest})")


def looks_like_secret(value: str) -> bool:
    """A real key mixes letters and digits; identifiers and placeholders do not."""
    return (bool(re.search(r"[A-Za-z]", value)) and bool(re.search(r"\d", value))
            and not _PLACEHOLDER.search(value))


def _unfilled(value: str) -> bool:
    """A template slot (`${DB_PASSWORD}`, `<password>`, `your-password`), not a value."""
    return bool(re.search(r"[${}<>]", value) or _PLACEHOLDER.search(value))


def scan_line(line: str) -> list[tuple[str, str, str]]:
    hits, seen = [], set()
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(line):
            name, value = match.group(1), match.group(2)
            if looks_like_secret(value) and value not in seen:
                seen.add(value)
                hits.append((kind, name, value))
    for kind, pattern in STRUCTURAL:
        for match in pattern.finditer(line):
            name, value = match.group(1), match.group(2)
            if value not in seen and not (kind == _URL_PASSWORD and _unfilled(value)):
                seen.add(value)
                hits.append((kind, name, value))
    return hits


def scan_diff(text: str) -> list[Finding]:
    """Findings in the added lines of `git log -p --format='commit %H'` output."""
    findings: list[Finding] = []
    commit, path = "", ""
    for line in text.splitlines():
        if line.startswith("commit ") and len(line.split()) == 2:
            commit, path = line.split()[1], ""
        elif line.startswith("+++ "):
            target = line[4:]
            path = target[2:] if target.startswith("b/") else target
        elif line.startswith("+") and not line.startswith("+++"):
            for kind, name, value in scan_line(line[1:]):
                findings.append(Finding(commit, path, kind, name, value))
    return findings


def git_log_patch(args: list[str]) -> str:
    cmd = ["git", "log", "-p", "--no-merges", "--no-color", "--no-ext-diff",
           "-U0", "--format=commit %H", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True,
                          errors="replace").stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--range", dest="range_", help="BASE..HEAD")
    group.add_argument("--commit", action="append", help="one commit (repeatable)")
    group.add_argument("--stdin", action="store_true", help="read a patch on stdin")
    args = parser.parse_args(argv)

    if args.stdin:
        text = sys.stdin.read()
    elif args.range_:
        text = git_log_patch([args.range_])
    else:
        # --root so an initial commit shows its whole tree as added.
        text = "".join(git_log_patch(["--root", "-1", sha]) for sha in args.commit)

    findings = scan_diff(text)
    if not findings:
        print("commit secret scan: no credential-shaped values in the added lines")
        return 0
    for finding in findings:
        print(f"::error::credential-shaped value added: {finding.describe()}")
    print(f"{len(findings)} credential-shaped value(s) in the added lines. Remove the "
          "value, rewrite the branch so it is not in any pushed commit, and rotate it "
          "if it was real — see .github/SECURITY.md.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())

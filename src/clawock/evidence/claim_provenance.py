"""Backtest claims must cite a run card, and the card must still agree.

The gap this closes
-------------------
Three provenance gates already exist and none of them can see a backtest claim:

* `test_numeric_claims` catches report prose quoting magnitudes the harness
  context never contained (#120);
* `clawock.evidence.research_provenance` is fail-closed — for thesis and
  earnings artifacts;
* `test_no_live_numbers_in_static_copy` keeps moving figures out of README.

#234 gave every backtest a run card and #233 cited one from `compute_regime.py`.
Nothing checks that a cited `run_id` exists, or that its metrics still match the
sentence quoting them. The `-95% → -44%` framing survived for months precisely
because no gate could see it — and the failure mode that matters is not a
missing citation but a **stale** one: a claim that points at real evidence which
no longer says what the claim says. That looks maximally credible and is wrong.

What counts as a claim
----------------------
Deliberately narrow, because a fuzzy scanner that cries wolf gets disabled. A
claim is a percentage or p-value on a line that also names a backtest quantity
(`maxDD`, `drawdown`, `CAGR`, `p =`, `improvement`, `totRet`). Prose that merely
discusses a number without asserting it is exempted through the allowlist.

Fail-closed: a scanner error is a red gate, never "no claims found".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
CARDS_DIR = WS / 'memory' / 'backtests'
ALLOWLIST = WS / 'config' / 'claim-allowlist.json'
SURFACES_CONFIG = WS / 'config' / 'claim-provenance.json'

QUANTITY = re.compile(
    r'\b(maxDD|max_drawdown|drawdown|CAGR|totRet|total_return|improvement|'
    r'p\s*[=＝]|p-value)\b', re.I)
# -95%, +3.9pp, 0.92 after "p ="
PERCENT = re.compile(r'([+-]?\d+(?:\.\d+)?)\s*(%|pp)')
PVALUE = re.compile(r'p\s*[=＝]\s*([01](?:\.\d+)?)', re.I)
RUN_ID = re.compile(r'\b([a-z_]+-\d{8}-[0-9a-f]{8})\b')

TOLERANCE = 0.006   # 0.6pp — prose rounds to one decimal


def load_surfaces(path: Path | None = None) -> tuple[str, ...]:
    """Claim-bearing files are workspace policy, not package contents."""
    path = Path(path or SURFACES_CONFIG)
    payload = json.loads(path.read_text(encoding="utf-8"))
    surfaces = payload.get("surfaces") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or payload.get("schema_version") != 1
            or not isinstance(surfaces, list)):
        raise ValueError(f"{path} must declare schema_version 1 and surfaces")
    if not all(
        isinstance(item, str) and item and not Path(item).is_absolute()
        and ".." not in Path(item).parts
        for item in surfaces
    ):
        raise ValueError(f"{path}: surfaces must be relative workspace paths")
    return tuple(surfaces)


def load_cards(cards_dir: Path | None = None) -> dict:
    cards_dir = Path(cards_dir or CARDS_DIR)
    out = {}
    for path in sorted(cards_dir.glob('*.json')):
        card = json.loads(path.read_text())
        out[card['run_id']] = card
    return out


def _numbers_in(node, acc: list) -> list:
    """Every numeric value anywhere in a card's metrics."""
    if isinstance(node, dict):
        for value in node.values():
            _numbers_in(value, acc)
    elif isinstance(node, list):
        for value in node:
            _numbers_in(value, acc)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        acc.append(float(node))
    return acc


def load_allowlist(path: Path | None = None) -> dict:
    path = Path(path or ALLOWLIST)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def scan_text(text: str, *, source: str) -> list[dict]:
    """Numeric backtest claims in one document, with their cited run_ids."""
    cited = RUN_ID.findall(text)
    claims = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if not QUANTITY.search(line):
            continue
        values = []
        for raw, unit in PERCENT.findall(line):
            values.append(float(raw) / 100.0)
        for raw in PVALUE.findall(line):
            values.append(float(raw))
        for value in values:
            claims.append({
                'source': source, 'line': lineno, 'value': value,
                'text': line.strip()[:120], 'cited': cited,
            })
    return claims


def _matches_card(value: float, cards: list[dict]) -> bool:
    for card in cards:
        for number in _numbers_in(card.get('metrics'), []):
            if abs(abs(number) - abs(value)) <= TOLERANCE:
                return True
    return False


def check(root: Path | None = None, cards_dir: Path | None = None,
          allowlist: Path | None = None, scanned=None) -> list[str]:
    root = Path(root or WS)
    scanned = load_surfaces(root / "config" / "claim-provenance.json") \
        if scanned is None else tuple(scanned)
    cards = load_cards(cards_dir)
    allowed = load_allowlist(allowlist)
    problems = []

    for rel in scanned:
        path = root / rel
        if not path.exists():
            problems.append(f'{rel}: declared claim surface is missing')
            continue
        text = path.read_text()
        claims = scan_text(text, source=rel)
        if not claims:
            continue

        exempt = {float(v) for v in (allowed.get(rel) or {}).get('values', [])}
        cited_cards = [cards[rid] for rid in set(
            RUN_ID.findall(text)) if rid in cards]
        unknown = [rid for rid in set(RUN_ID.findall(text)) if rid not in cards]
        for rid in unknown:
            problems.append(f'{rel}: cites run card {rid}, which does not exist')

        for claim in claims:
            if any(abs(claim['value'] - value) <= 1e-9 for value in exempt):
                continue
            if not cited_cards:
                problems.append(
                    f"{rel}:{claim['line']}: claims {claim['value']:+.4f} but the "
                    f"file cites no run card — {claim['text']}")
                continue
            if not _matches_card(claim['value'], cited_cards):
                problems.append(
                    f"{rel}:{claim['line']}: claims {claim['value']:+.4f}, which "
                    f"no cited run card contains — {claim['text']}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--check', action='store_true', help='exit non-zero on problems')
    args = ap.parse_args(argv)

    try:
        scanned = load_surfaces()
        problems = check(scanned=scanned)
    except Exception as exc:  # fail-closed: a broken scanner is a red gate
        print(f'claim provenance scanner failed: {exc!r}', file=sys.stderr)
        return 2

    if problems:
        print(f'❌ {len(problems)} unbacked backtest claim(s):', file=sys.stderr)
        for problem in problems:
            print(f'   · {problem}', file=sys.stderr)
        return 1 if args.check else 0
    print(f'✅ backtest claims in {len(scanned)} file(s) resolve to stored run cards')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Backtest claims must cite a run card, and the card must still agree.

The gap this closes
-------------------
Three provenance gates already exist and none of them can see a backtest claim:

* `test_numeric_claims` catches report prose quoting magnitudes the harness
  context never contained (#120);
* `clawock.provenance` is fail-closed — for thesis and
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

A claim matches a card leaf named for the quantity its line names, within half a
unit of the digit it is printed to (#2193) — not any number anywhere in the card.

Fail-closed: a scanner error is a red gate, never "no claims found".
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root()
CARDS_DIR = WS / 'memory' / 'backtests'
ALLOWLIST = WS / 'config' / 'claim-allowlist.json'
SURFACES_CONFIG = WS / 'config' / 'claim-provenance.json'

# `p =` sits outside the trailing \b: after `=` a word boundary needs a word
# character, so `p = 0.92` (space after the sign) never matched and a p-value
# line with no other quantity word was never checked (#2075).
QUANTITY = re.compile(
    r'\b(?:(?:maxDD|max_drawdown|drawdown|CAGR|totRet|total_return|improvement|'
    r'p-value)\b|p\s*[=＝])', re.I)
# -95%, +3.9pp, 0.92 after "p =" — a standalone `p`, not the tail of `vol_cap=0.50`.
# A table cell writes a series once and puts the unit on its last member
# (`drawdown −1.79 / −2.47 / −3.30 / −5.45%`); every member is a claim, not only
# the one that carries the `%` (#2193).
_NUMBER = r'[+\-−]?\d+(?:\.\d+)?'
PERCENT = re.compile(rf'((?:{_NUMBER}\s*/\s*)*)({_NUMBER})\s*(%|pp)')
# Which card leaves a percentage on a line may be matched against, by the
# quantity the line names. The whole metrics tree used to be one bag: the
# add-side campaign card holds 477 numbers and 393 of 401 possible claims
# between -20% and +20% found one within tolerance (#2193), the percent-side
# twin of #1960's p-value hole.
FAMILIES = (
    (re.compile(r'\b(?:maxDD|max_drawdown|drawdown)\b', re.I),
     re.compile(r'drawdown|max_?dd', re.I)),
    (re.compile(r'\bCAGR\b', re.I), re.compile(r'cagr', re.I)),
    (re.compile(r'\b(?:totRet|total_return)\b', re.I),
     re.compile(r'tot_?ret|total_return', re.I)),
    (re.compile(r'\bimprovement\b', re.I), re.compile(r'improvement', re.I)),
)
PVALUE = re.compile(r'\bp\s*[=＝]\s*([01](?:\.\d+)?)', re.I)
RUN_ID = re.compile(r'\b([a-z_]+-\d{8}-[0-9a-f]{8})\b')

TOLERANCE = 0.006   # 0.6pp — the loosest a claim is ever read


def _tolerance(raw: str, kind: str) -> float:
    """Half a unit of the claim's last printed digit, capped at TOLERANCE.

    `-91.6%` claims a number that rounds to it (±0.05pp), `-95%` one within
    ±0.5pp. A flat 0.6pp let `−1.79%` match anything from -1.19% to -2.39% on
    a card with hundreds of leaves (#2193).
    """
    decimals = len(raw.split('.', 1)[1]) if '.' in raw else 0
    unit = 10.0 ** -decimals / (100.0 if kind == 'percent' else 1.0)
    return min(TOLERANCE, unit / 2 + 1e-6)


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


def _numbers_in(node, acc: list, scale: float = 1.0) -> list:
    """Every numeric value anywhere in a card's metrics, as a fraction.

    Claims are read as fractions (`-14.93%` is -0.1493). The regime cards store
    fractions too, but the add-side cards store percentages under `*_pct*`
    keys (`max_drawdown_pct_of_book: -14.93`), which no claim could match
    until those leaves were scaled (#2185).
    """
    if isinstance(node, dict):
        for key, value in node.items():
            _numbers_in(value, acc, 0.01 if 'pct' in str(key).lower() else scale)
    elif isinstance(node, list):
        for value in node:
            _numbers_in(value, acc, scale)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        acc.append(float(node) * scale)
    return acc


def _keyed_numbers_in(node, key_re, acc: list, scale: float = 1.0,
                      path: str = '') -> list:
    """`_numbers_in`, restricted to leaves whose key path matches `key_re`."""
    if isinstance(node, dict):
        for key, value in node.items():
            _keyed_numbers_in(value, key_re, acc,
                              0.01 if 'pct' in str(key).lower() else scale,
                              f'{path}.{key}')
    elif isinstance(node, list):
        for value in node:
            _keyed_numbers_in(value, key_re, acc, scale, path)
    elif (isinstance(node, (int, float)) and not isinstance(node, bool)
          and key_re.search(path)):
        acc.append(float(node) * scale)
    return acc


def _pvalues_in(node, acc: list) -> list:
    """Only measured p-value leaves, never drawdowns or grid parameters."""
    if isinstance(node, dict):
        for key, value in node.items():
            if re.search(r'p[_-]?value|pval', str(key), re.I):
                _numbers_in(value, acc)
            elif isinstance(value, (dict, list)):
                _pvalues_in(value, acc)
    elif isinstance(node, list):
        for value in node:
            _pvalues_in(value, acc)
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
        for series, last, unit in PERCENT.findall(line):
            for raw in re.findall(_NUMBER, series) + [last]:
                values.append((float(raw.replace('−', '-')) / 100.0, 'percent',
                               _tolerance(raw, 'percent')))
        for raw in PVALUE.findall(line):
            values.append((float(raw), 'pvalue', _tolerance(raw, 'pvalue')))
        keys = [key_re.pattern for word_re, key_re in FAMILIES if word_re.search(line)]
        for value, kind, tolerance in values:
            claims.append({
                'source': source, 'line': lineno, 'value': value, 'kind': kind,
                'tolerance': tolerance,
                'text': line.strip()[:120], 'cited': cited,
                'keys': '|'.join(keys),
            })
    return claims


def _matches_card(value: float, cards: list[dict], kind='percent', keys='',
                  tolerance: float = TOLERANCE) -> bool:
    """A percentage matches only leaves named for a quantity its line names.

    A line with no such word (only `p =`) still reads the whole tree: that is
    the claim shape the scanner accepted before #2193 and narrowing it would
    need a word the line does not have.
    """
    key_re = re.compile(keys, re.I) if keys else None
    for card in cards:
        metrics = card.get('metrics')
        if kind == 'pvalue':
            numbers = _pvalues_in(metrics, [])
        elif key_re is not None:
            numbers = _keyed_numbers_in(metrics, key_re, [])
        else:
            numbers = _numbers_in(metrics, [])
        for number in numbers:
            difference = (abs(number - value) if kind == 'pvalue'
                          else abs(abs(number) - abs(value)))
            if difference <= tolerance:
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
            if not _matches_card(claim['value'], cited_cards, claim['kind'],
                                 claim.get('keys', ''),
                                 claim.get('tolerance', TOLERANCE)):
                problems.append(
                    f"{rel}:{claim['line']}: claims {claim['value']:+.4f}, which "
                    f"no cited run card contains — {claim['text']}")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='clawock claim-provenance', description=__doc__)
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
    # The count, not only the file list: on #2185 six files were "resolved"
    # while the newest surface had one of its 32 numbers read (#2193).
    claims = sum(len(scan_text((WS / rel).read_text(), source=rel)) for rel in scanned)
    print(f'✅ {claims} backtest claim(s) in {len(scanned)} file(s) resolve to '
          f'stored run cards or the allowlist')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

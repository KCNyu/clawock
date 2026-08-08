"""Evidence a backtest actually ran, and against what.

Why this exists
---------------
The three backtests wrote PNGs into `memory/.tmp/` and printed a table. Nothing
durable survived the run. Their conclusions, meanwhile, are quoted as fact in
permanent prose — `compute_regime.py` opens by justifying the production
leverage dial with "-95% to 0%" and "-95% → -44%". Those numbers could not be
re-derived: the scripts refetch a live upstream that has since moved, so a rerun
covers a different window and may not even see the same bars.

That is the static-copy-quoting-live-numbers problem one level down. The copy is
honest about being a backtest; the backtest just left no evidence behind.

A run card records what would otherwise be lost:

* **input identity** — source name, symbols, first/last session, bar count, and
  a digest of the exact series used, so a silently revised upstream is visible;
* **parameters** — the thresholds the run actually used, not the defaults in the
  signature;
* **code identity** — a hash of the backtest script and of any module whose
  behaviour the result depends on;
* **metrics** — the numbers the prose quotes, as JSON rather than as stdout.

What it deliberately does not record
------------------------------------
Raw vendor bars. The card carries derived metrics and source *names* only, which
keeps it publishable under the third-party data boundary. The series digest
identifies the input without republishing it.

One expected asymmetry
----------------------
A card's code digests describe the code **as it ran**. Editing a file afterwards
to cite the card — which is the whole point of having one — changes that file's
digest, so the citing source no longer matches the digest inside the card it
cites. That is not a mismatch to fix; re-running to "correct" it would produce a
new run_id and a new citation, forever. The digest answers "what produced these
metrics", not "what does the repo look like now".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
CARDS_DIR = WS / 'memory' / 'backtests'
SCHEMA_VERSION = 1


def series_digest(series) -> str:
    """Stable digest of a (date, value) series.

    Identifies the input without republishing it: two runs over the same bars
    agree, and a provider revision that changes one close does not.
    """
    hasher = hashlib.sha256()
    for item in series:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            date, value = item[0], item[1]
        elif isinstance(item, dict):
            date, value = item.get('date'), item.get('close')
        else:
            date, value = None, item
        hasher.update(f'{date}|{float(value):.6f}\n'.encode())
    return f'sha256:{hasher.hexdigest()[:16]}'


def file_digest(path) -> str | None:
    path = Path(path)
    if not path.exists():
        return None
    return f'sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:16]}'


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'], cwd=WS,
            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'))


def build_card(name: str, *, params: dict, inputs: list, metrics: dict,
               code_files=(), notes=(), generated_at: str | None = None) -> dict:
    """Assemble the card. Pure — writing is a separate step, so it is testable."""
    code = []
    for path in code_files:
        path = Path(path)
        code.append({'file': path.name, 'digest': file_digest(path)})

    # The reproduction key covers everything that can change the answer:
    # parameters, the exact input series, and the code that consumed them. Two
    # runs sharing it must produce the same metrics; if they do not, the
    # difference is somewhere this card fails to describe.
    reproduction_key = 'sha256:' + hashlib.sha256(_canonical({
        'params': params,
        'inputs': [{k: v for k, v in row.items() if k != 'note'} for row in inputs],
        'code': code,
    }).encode()).hexdigest()[:16]

    stamp = generated_at or datetime.now(timezone.utc).isoformat(timespec='seconds')
    return {
        'schema_version': SCHEMA_VERSION,
        'run_id': f'{name}-{stamp[:10].replace("-", "")}-{reproduction_key[7:15]}',
        'backtest': name,
        'generated_at': stamp,
        'git_commit': _git_commit(),
        'reproduction_key': reproduction_key,
        'params': params,
        'inputs': inputs,
        'code': code,
        'metrics': metrics,
        'notes': list(notes),
        'data_boundary': 'derived metrics and source names only; no raw vendor bars',
    }


def write_card(card: dict, cards_dir: Path | None = None) -> Path:
    """Persist one card. Returns the path written."""
    cards_dir = Path(cards_dir or CARDS_DIR)
    path = cards_dir / f'{card["run_id"]}.json'
    # strict=True: a card is evidence. A non-finite metric in it means the run
    # produced something the card cannot faithfully describe, and silently
    # publishing null would make the evidence lie. Nothing downstream depends on
    # the card existing, so failing here costs nothing but the card.
    safe_write_json(str(path), card, strict=True)
    return path


def record(name: str, *, params: dict, inputs: list, metrics: dict,
           code_files=(), notes=(), cards_dir: Path | None = None) -> Path:
    """Build and write in one call — what the backtest scripts use."""
    return write_card(
        build_card(name, params=params, inputs=inputs, metrics=metrics,
                   code_files=code_files, notes=notes),
        cards_dir=cards_dir)


def load_cards(cards_dir: Path | None = None) -> list[dict]:
    cards_dir = Path(cards_dir or CARDS_DIR)
    if not cards_dir.exists():
        return []
    out = []
    for path in sorted(cards_dir.glob('*.json')):
        try:
            out.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--list', action='store_true', help='list stored run cards')
    ap.add_argument('--run-id', help='print one card')
    args = ap.parse_args(argv)

    cards = load_cards()
    if args.run_id:
        for card in cards:
            if card.get('run_id') == args.run_id:
                print(json.dumps(card, ensure_ascii=False, indent=2))
                return 0
        print(f'no such run card: {args.run_id}', file=sys.stderr)
        return 1

    if not cards:
        print('no run cards stored yet')
        return 0
    for card in cards:
        metrics = card.get('metrics') or {}
        print(f'{card["run_id"]}  {card.get("generated_at", "")}  '
              f'{len(metrics)} metric group(s)  {card.get("git_commit") or "-"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

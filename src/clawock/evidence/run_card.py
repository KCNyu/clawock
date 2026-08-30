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

What the reproduction key did not cover (#1139, schema 2)
---------------------------------------------------------
Its docstring below promises that "two runs sharing it must produce the same
metrics". Three things could break that promise while the key stayed identical:

* **the seeds.** Eight modules held a literal like `random.Random(20260813)`
  inline. They are declared in `clawock.seeds` now and recorded here.
* **the environment.** numpy and scipy are required dependencies and the
  evaluation lane leans on them; a minor release that changes a random stream or
  a linear-algebra path moves the metrics under an unchanged key.
* **the configuration files.** `params` recorded whatever the caller passed
  explicitly. A run that reads `config/factor-universe.json` and reports the
  thresholds it used is describing a file whose *other* contents also changed
  the answer.

All three are in the key from schema 2, which means **every card written before
this stops matching a rerun's key**. That is the intended consequence and not a
migration to paper over: the old keys were asserting a coverage they did not
have. `metrics_digest` is recorded separately so a drift can be detected without
recomputing anything, and `explain_mismatch` says which of the four inputs moved.

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
import time
from datetime import datetime, timezone
from pathlib import Path

from clawock import seeds as seed_registry
from clawock.safe_io import safe_write_json
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
CARDS_DIR = WS / 'memory' / 'backtests'
SCHEMA_VERSION = 2


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


#: The libraries whose version can move a number without any code changing.
#: Recorded by import rather than from metadata so the card describes the
#: interpreter that ran, not what a lockfile said should have.
FINGERPRINTED_MODULES = ('numpy', 'scipy', 'requests')


def environment() -> dict:
    """Interpreter and numeric-library identity for this run."""
    import platform

    versions = {}
    for name in FINGERPRINTED_MODULES:
        try:
            versions[name] = __import__(name).__version__
        except Exception:                                  # noqa: BLE001
            versions[name] = None
    return {
        'python': platform.python_version(),
        'implementation': platform.python_implementation(),
        'platform': platform.system().lower(),
        'libraries': versions,
    }


def config_digests(paths) -> list[dict]:
    """Content hashes of the configuration a run read.

    `params` records the thresholds the caller chose to name. This records the
    files those thresholds came out of, so a change to a weight nobody passed
    explicitly still moves the key.
    """
    out = []
    for path in paths:
        path = Path(path).resolve()
        out.append({
            'file': str(path.relative_to(WS)) if path.is_relative_to(WS) else path.name,
            'digest': file_digest(path),
        })
    return sorted(out, key=lambda row: row['file'])


def metrics_digest(metrics) -> str:
    """Digest of the numbers themselves.

    Lets two cards be compared for drift without either being recomputed, which
    is the only way to notice that a dependency upgrade moved a result: the
    reproduction key answers "were the inputs the same", this answers "was the
    answer the same", and the interesting case is when they disagree.
    """
    return 'sha256:' + hashlib.sha256(
        _canonical(metrics).encode()).hexdigest()[:16]


def _execution(started_at: float | None) -> dict:
    """Wall time and peak memory, where the platform reports them."""
    out = {}
    if started_at is not None:
        out['wall_seconds'] = round(time.monotonic() - started_at, 3)
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes, macOS bytes. Both are stated rather than
        # normalised blindly, because a silently wrong unit in an evidence
        # record is worse than an absent one.
        out['peak_rss_kb'] = int(peak if sys.platform.startswith('linux')
                                 else peak / 1024)
    except (ImportError, OSError):
        pass
    return out


def _canonical(payload) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'))


def build_card(name: str, *, params: dict, inputs: list, metrics: dict,
               code_files=(), notes=(), generated_at: str | None = None,
               config_files=(), seeds=None, started_at: float | None = None) -> dict:
    """Assemble the card. Pure — writing is a separate step, so it is testable."""
    code = []
    for path in code_files:
        path = Path(path)
        code.append({'file': path.name, 'digest': file_digest(path)})
    configs = config_digests(config_files)
    # The whole registry unless the caller narrows it. A run that used three of
    # the seven seeds and recorded only those would still be reproducible, but a
    # later reader could not tell "this seed was not used" from "this seed was
    # not recorded", and the second is the one that matters.
    used_seeds = dict(seeds if seeds is not None else seed_registry.SEEDS)
    env = environment()

    # The reproduction key covers everything that can change the answer:
    # parameters, the exact input series, and the code that consumed them. Two
    # runs sharing it must produce the same metrics; if they do not, the
    # difference is somewhere this card fails to describe.
    reproduction_key = 'sha256:' + hashlib.sha256(_canonical({
        'params': params,
        'inputs': [{k: v for k, v in row.items() if k != 'note'} for row in inputs],
        'code': code,
        'config': configs,
        'seeds': used_seeds,
        # Library versions, not the whole environment: the platform and the
        # interpreter's patch level are recorded on the card for a reader, but
        # putting them in the key would invalidate every card on a routine
        # security update that cannot change a float.
        'libraries': env['libraries'],
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
        'config': configs,
        'seeds': used_seeds,
        'environment': env,
        'execution': _execution(started_at),
        'metrics': metrics,
        'metrics_digest': metrics_digest(metrics),
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
           code_files=(), notes=(), cards_dir: Path | None = None,
           config_files=(), seeds=None, started_at: float | None = None) -> Path:
    """Build and write in one call — what the backtest scripts use."""
    return write_card(
        build_card(name, params=params, inputs=inputs, metrics=metrics,
                   code_files=code_files, notes=notes,
                   config_files=config_files, seeds=seeds, started_at=started_at),
        cards_dir=cards_dir)


def explain_mismatch(card: dict, other: dict) -> dict:
    """Which of the recorded inputs differs between two cards.

    The question a reproduction key raises and cannot answer: the metrics moved,
    so *what* moved. Comparing two cards field by field turns "not reproducible"
    into "scipy went from 1.11 to 1.14 and nothing else changed", which is a
    thing someone can act on.
    """
    def _digests(rows, key='file'):
        return {row.get(key): row.get('digest') for row in rows or []}

    differences = {}
    for field in ('params', 'seeds'):
        if card.get(field) != other.get(field):
            differences[field] = {'card': card.get(field), 'other': other.get(field)}
    for field, key in (('code', 'file'), ('config', 'file'), ('inputs', 'symbol')):
        left, right = _digests(card.get(field), key), _digests(other.get(field), key)
        moved = {name: [left.get(name), right.get(name)]
                 for name in sorted(set(left) | set(right))
                 if left.get(name) != right.get(name)}
        if moved:
            differences[field] = moved
    left_env = (card.get('environment') or {}).get('libraries') or {}
    right_env = (other.get('environment') or {}).get('libraries') or {}
    moved_libraries = {name: [left_env.get(name), right_env.get(name)]
                       for name in sorted(set(left_env) | set(right_env))
                       if left_env.get(name) != right_env.get(name)}
    if moved_libraries:
        differences['libraries'] = moved_libraries
    return {
        'run_ids': [card.get('run_id'), other.get('run_id')],
        'same_reproduction_key': card.get('reproduction_key') == other.get('reproduction_key'),
        'same_metrics': card.get('metrics_digest') == other.get('metrics_digest'),
        'differences': differences,
        # The case worth naming. Identical inputs and different answers means the
        # card does not describe everything that decided the result.
        'unexplained': (card.get('reproduction_key') == other.get('reproduction_key')
                        and card.get('metrics_digest') != other.get('metrics_digest')
                        and not differences),
    }


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
    ap.add_argument('--diff', nargs=2, metavar=('RUN_ID', 'RUN_ID'),
                    help='say which recorded input differs between two cards')
    ap.add_argument('--verify', metavar='RUN_ID',
                    help='compare a card against the environment running now')
    args = ap.parse_args(argv)

    cards = load_cards()
    by_id = {card.get('run_id'): card for card in cards}

    if args.diff:
        missing = [name for name in args.diff if name not in by_id]
        if missing:
            print(f'no such run card: {", ".join(missing)}', file=sys.stderr)
            return 1
        print(json.dumps(explain_mismatch(by_id[args.diff[0]], by_id[args.diff[1]]),
                         ensure_ascii=False, indent=2))
        return 0

    if args.verify:
        card = by_id.get(args.verify)
        if card is None:
            print(f'no such run card: {args.verify}', file=sys.stderr)
            return 1
        now = environment()
        recorded = card.get('environment') or {}
        moved = {name: [(recorded.get('libraries') or {}).get(name), value]
                 for name, value in now['libraries'].items()
                 if (recorded.get('libraries') or {}).get(name) != value}
        print(json.dumps({
            'run_id': args.verify,
            'schema_version': card.get('schema_version'),
            'environment_recorded': recorded,
            'environment_now': now,
            'libraries_moved': moved,
            'reproducible_here': not moved and card.get('schema_version') == SCHEMA_VERSION,
            'note': ('a card written before schema 2 recorded no environment, so '
                     'it cannot be verified against one — rerun to get a card '
                     'that can'),
        }, ensure_ascii=False, indent=2))
        return 0
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

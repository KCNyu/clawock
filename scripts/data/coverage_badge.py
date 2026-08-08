#!/usr/bin/env python3
"""Turn a coverage.py JSON report into the shields.io endpoint badge the READMEs
point at — and fail the run when coverage drops below its floors.

Why a floor and not just a badge: a published number nobody gates on only ever
ratchets down, and the badge would then advertise the decay. The badge is the
readout; `--min-total` / `--min-core` are the part that actually holds.

Why two floors. One aggregate would hide the split that matters here. Roughly a
fifth of `scripts/` is network fetchers (`fetch_*` / `analyze_*`) whose bodies are
vendor HTTP and parsing; they are exercised end-to-end by the live crons, not by
unit tests, and they drag the total down. The modules that settle money — the
ledger, the graders, the risk caps, the registries — are held to a separate,
higher floor so a regression there cannot be papered over by adding tests to a
fetcher.

The badge colour is a constant from the README palette, not a red/amber/green
scale: this repo does not grade itself with a mood ring. A real drop shows up as
a red CI run here, not as a slightly worse shade on the README.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# The checkout root, so `clawock` resolves from the tree this file ships
# in. Reached through the scripts/data/workspace shim until #267 step 3,
# whose only remaining job was inserting this path as a side effect.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from clawock.workspace import workspace_root  # noqa: E402

ROOT = workspace_root(Path(__file__).resolve().parents[2])

# The settlement core: everything whose arithmetic can corrupt the public record.
# Paths are repo-relative and must all be present in the report — see
# _core_summary() for why a missing one is an error rather than a skip.
CORE_MODULES = (
    'src/clawock/decision_v2.py',
    'scripts/data/entry_gate.py',
    'scripts/data/thesis_registry.py',
    'scripts/data/earnings_review.py',
    'scripts/data/research_provenance.py',
    'scripts/data/research_surface.py',
    'scripts/data/preflight_integrity.py',
    'scripts/data/risk_discipline.py',
    'scripts/data/shadow_portfolio.py',
    'src/clawock/instrument_registry.py',
    'scripts/data/recompute_aggregates.py',
    'scripts/data/recompute_realized.py',
    'scripts/data/portfolio_risk_metrics.py',
    'scripts/data/intraday_delta_gate.py',
    'scripts/data/workflow_outcomes.py',
    'src/clawock/safe_io.py',
    'src/clawock/trading_calendar.py',
)

# Floors sit a couple of points under the measured value: enough headroom that a
# legitimate refactor (deleting well-covered dead code raises statements' weight)
# does not false-fail, small enough that a real regression reds the run. Raise
# them deliberately when the suite grows; never lower one to make a PR pass.
DEFAULT_MIN_TOTAL = 52.0
DEFAULT_MIN_CORE = 75.0

# A report that measured almost nothing (mis-scoped `--cov`, an import error that
# aborted collection) can still be internally consistent and score well. Statement
# count is the cheapest tripwire for "this run did not actually measure the tree".
MIN_STATEMENTS = 12000

BADGE_LABEL = 'COVERAGE'
BADGE_COLOR = '738391'  # same muted tone as the TESTS badge in the READMEs


def load_report(path: Path | str) -> dict:
    """Read a coverage.py JSON report, failing loudly on anything unusable."""
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f'coverage report not found: {path}')
    try:
        raw = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise SystemExit(f'coverage report is not valid UTF-8: {path}') from None
    if not raw.strip():
        raise SystemExit(f'coverage report is empty: {path}')
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'coverage report is not valid JSON: {path}: {exc}') from None
    if not isinstance(data, dict) or 'files' not in data or 'totals' not in data:
        raise SystemExit(
            f'{path}: not a coverage.py JSON report (expected "files" and "totals")')
    if not isinstance(data['files'], dict) or not data['files']:
        raise SystemExit(f'{path}: report covers no files at all')
    return data


def _percent(covered: int, statements: int) -> float:
    # coverage.py reports 100% for an empty file set; here an empty set means the
    # measurement failed, so refuse to invent a number.
    if statements <= 0:
        raise SystemExit('coverage report contains zero statements')
    return 100.0 * covered / statements


def total_summary(report: dict) -> tuple[int, int, float]:
    totals = report['totals']
    statements = int(totals.get('num_statements', 0))
    covered = int(totals.get('covered_lines', 0))
    if statements < MIN_STATEMENTS:
        raise SystemExit(
            f'coverage report only measured {statements} statements '
            f'(expected >= {MIN_STATEMENTS}) — the run did not cover scripts/')
    return covered, statements, _percent(covered, statements)


def core_summary(report: dict, modules=CORE_MODULES) -> tuple[int, int, float]:
    """Aggregate the settlement core.

    A module listed here but absent from the report is an error, not a skip: the
    silent-drop path is exactly how a renamed or deleted core module would quietly
    leave the gate while the group percentage went *up*.
    """
    files = report['files']
    missing = [m for m in modules if m not in files]
    if missing:
        raise SystemExit(
            'settlement-core modules missing from the coverage report '
            f'(renamed or deleted? update CORE_MODULES): {", ".join(missing)}')
    statements = sum(int(files[m]['summary']['num_statements']) for m in modules)
    covered = sum(int(files[m]['summary']['covered_lines']) for m in modules)
    return covered, statements, _percent(covered, statements)


def badge_payload(total_pct: float) -> dict:
    """Strict shields.io endpoint schema — no extra keys.

    Detail (core split, statement counts) deliberately stays out of the file:
    shields fetches it directly and unknown fields are not part of the contract.
    The numbers live in the commit message and the job log instead.
    """
    return {
        'schemaVersion': 1,
        'label': BADGE_LABEL,
        'message': f'{total_pct:.0f}%',
        'color': BADGE_COLOR,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Enforce coverage floors and write the shields endpoint badge.')
    parser.add_argument('--report', default='coverage-report.json',
                        help='coverage.py JSON report (coverage json -o ...)')
    parser.add_argument('--out', default='assets/data/coverage.json',
                        help='shields.io endpoint payload to write (omit with --check-only)')
    parser.add_argument('--min-total', type=float, default=DEFAULT_MIN_TOTAL)
    parser.add_argument('--min-core', type=float, default=DEFAULT_MIN_CORE)
    parser.add_argument('--check-only', action='store_true',
                        help='enforce the floors without writing the badge payload')
    args = parser.parse_args(argv)

    report = load_report(args.report)
    total_covered, total_statements, total_pct = total_summary(report)
    core_covered, core_statements, core_pct = core_summary(report)

    print(f'total:           {total_pct:5.1f}%  '
          f'({total_covered}/{total_statements} statements, floor {args.min_total}%)')
    print(f'settlement core: {core_pct:5.1f}%  '
          f'({core_covered}/{core_statements} statements, floor {args.min_core}%)')

    failures = []
    if total_pct < args.min_total:
        failures.append(f'total coverage {total_pct:.1f}% is below its {args.min_total}% floor')
    if core_pct < args.min_core:
        failures.append(
            f'settlement-core coverage {core_pct:.1f}% is below its {args.min_core}% floor')
    if failures:
        for line in failures:
            print(f'::error::{line}', file=sys.stderr)
        return 1

    if args.check_only:
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(badge_payload(total_pct), indent=2) + '\n', encoding='utf-8')
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

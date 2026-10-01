"""Strict stored-plan validation with exact, reviewed legacy monetary exceptions.

The live writer and pre-commit hook always use validate_plan without exceptions.
This audit preserves immutable records that predate the book-total gate: only the
same file and exact book/FX values can retain a reviewed monetary discrepancy.
Decision/schema errors and any changed or newly authored money block still fail.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from clawock.decision import ledger  # noqa: E402
EXCEPTIONS = ROOT / 'ops/ci/legacy_plan_book_values.json'


def book_digest(plan):
    data = {'book': plan.get('book'), 'fx_rate_usdhkd': plan.get('fx_rate_usdhkd')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def validate_stored_plan(plan, path, legacy):
    errors = ledger.validate_plan(plan, path)
    if legacy.get(Path(path).name) == book_digest(plan):
        kept = [e for e in errors if not e.startswith(('book totals mismatch:', 'book inputs invalid:'))]
        return kept, [e for e in errors if e not in kept]
    return errors, []


def main():
    legacy = json.loads(EXCEPTIONS.read_text())['sha256_by_file']
    for path in sorted((ROOT / 'memory').glob('*-plan.json')):
        errors, retained = validate_stored_plan(json.loads(path.read_text()), path, legacy)
        assert not errors, f'{path.name}: {errors}'
        suffix = f'; {len(retained)} reviewed legacy monetary discrepancies retained' if retained else ''
        print(f'{path.name}: schema OK{suffix}')


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Fail-closed review of the public DREAMS.md diary append.

OpenClaw appends raw narrative to DREAMS.md at 03:00 HKT. That file is tracked
and published, but the promotion gate only reviews MEMORY.md markers. This gate
reviews every diary entry appended after its private baseline:

* existing entries are grandfathered once (a one-time bootstrap, no rewrite);
* a new entry must be free of the deterministic contamination rules and have an
  exact hash-bound receipt in memory/.dreams/dreams-approvals.json;
* anything else is removed from DREAMS.md and preserved in the private
  memory/.dreams/dreams-quarantine.jsonl, never silently published.

No network, no model, no repository write beyond DREAMS.md.
"""
from __future__ import annotations

import argparse
from datetime import date
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from review_dreaming import reasons  # noqa: E402

DIARY_START = '<!-- openclaw:dreaming:diary:start -->'
DIARY_END = '<!-- openclaw:dreaming:diary:end -->'
ENTRY = re.compile(
    r'^\*([A-Z][a-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2} [AP]M GMT[+-]\d+)\*\s*$', re.M)
LEDGER_VERSION = 1


def digest(text: str) -> str:
    return hashlib.sha256(re.sub(r'\s+', ' ', text).strip().lower().encode()).hexdigest()


def _strip_block(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'\n+---\s*$', '', raw).strip()
    return raw


def parse(text: str):
    """(entries, region_start, region_end, prefix, suffix) or raise for no diary."""
    start = text.find(DIARY_START)
    end = text.find(DIARY_END)
    if start < 0 or end < 0 or end < start:
        return None
    region_start = start + len(DIARY_START)
    region_end = end
    region = text[region_start:region_end]
    matches = list(ENTRY.finditer(region))
    if not matches:
        return {'entries': [], 'region': region, 'region_start': region_start,
                'region_end': region_end, 'matches': []}
    entries = []
    for i, match in enumerate(matches):
        stop = matches[i + 1].start() if i + 1 < len(matches) else len(region)
        body = _strip_block(region[match.start():stop])
        content = '\n'.join(body.splitlines()[1:]).strip()
        entries.append({'date': match.group(1), 'text': body, 'body': content,
                        'sha256': digest(body)})
    return {'entries': entries, 'region': region, 'region_start': region_start,
            'region_end': region_end, 'matches': matches}


def rebuild(parsed, kept):
    region = parsed['region']
    matches = parsed['matches']
    pre = region[:matches[0].start()].rstrip() if matches else region.rstrip()
    body = '\n\n---\n\n'.join(entry['text'] for entry in kept)
    new_region = pre
    if body:
        new_region = (new_region + '\n\n' if new_region else '') + body + '\n\n'
    elif new_region:
        new_region += '\n\n'
    return parsed['region_start'], parsed['region_end'], new_region


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def valid_receipt(receipt, expected_hash: str) -> bool:
    if not isinstance(receipt, dict):
        return False
    try:
        reviewed_on = date.fromisoformat(receipt['reviewed_on'])
    except (KeyError, TypeError, ValueError):
        return False
    return (receipt.get('sha256') == expected_hash
            and bool(receipt.get('reviewer'))
            and bool(receipt.get('rationale'))
            and receipt.get('durable') is True
            and 0 <= (date.today() - reviewed_on).days <= 30)


def append_quarantine(path: Path, rows) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    if path.is_file():
        for line in path.read_text().splitlines():
            try:
                seen.add(json.loads(line)['sha256'])
            except (ValueError, KeyError):
                continue
    new = [row for row in rows if row['sha256'] not in seen]
    if not new:
        return 0
    with path.open('a') as stream:
        os.fchmod(stream.fileno(), 0o600)
        for row in new:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')
    return len(new)


def review(workspace: Path, check_only: bool = False) -> int:
    dreams_path = workspace / 'DREAMS.md'
    if not dreams_path.is_file():
        print('dreams review: no DREAMS.md')
        return 0
    text = dreams_path.read_text()
    parsed = parse(text)
    if parsed is None:
        raise ValueError('DREAMS.md has no diary markers')
    private = workspace / 'memory/.dreams'
    ledger_path = private / 'dreams-review.json'
    approvals_path = private / 'dreams-approvals.json'
    quarantine_path = private / 'dreams-quarantine.jsonl'
    ledger = load_json(ledger_path, None)
    if ledger is None:
        if check_only:
            raise ValueError('dreams review baseline missing; run review once')
        private.mkdir(parents=True, exist_ok=True)
        entries = {entry['sha256']: {'date': entry['date'], 'status': 'grandfathered'}
                   for entry in parsed['entries']}
        ledger = {'version': LEDGER_VERSION, 'entries': entries}
        atomic_write(ledger_path, json.dumps(ledger, ensure_ascii=False, indent=1) + '\n', True)
        print(f'dreams review: bootstrapped {len(entries)} existing entries; no rewrite')
        return 0
    ledger_entries = ledger.setdefault('entries', {})
    approvals = load_json(approvals_path, {})
    kept, quarantined, report = [], [], []
    for entry in parsed['entries']:
        key = entry['sha256']
        known = ledger_entries.get(key)
        if known and known.get('status') in ('grandfathered', 'approved'):
            kept.append(entry)
            continue
        why = reasons(entry['body'])
        receipt = approvals.get(key)
        if not why and valid_receipt(receipt, key):
            ledger_entries[key] = {'date': entry['date'], 'status': 'approved',
                                   'reviewed_on': receipt['reviewed_on']}
            kept.append(entry)
            report.append({'sha256': key, 'date': entry['date'], 'decision': 'approved'})
        else:
            if not why:
                why = ['unreviewed']
            elif receipt is not None:
                why = [*why, 'receipt_rejected_by_contamination']
            ledger_entries[key] = {'date': entry['date'], 'status': 'quarantined',
                                   'reasons': why}
            quarantined.append({'sha256': key, 'date': entry['date'], 'text': entry['text'],
                                'body': entry['body'],
                                'reasons': why, 'quarantined_at': date.today().isoformat()})
            report.append({'sha256': key, 'date': entry['date'], 'decision': 'quarantined',
                           'reasons': why})
    if check_only:
        pending = [r for r in report if r['decision'] != 'approved']
        if pending or quarantined:
            raise ValueError(f'{len(pending)} unreviewed DREAMS entry(ies) remain')
        print('dreams review: DREAMS has no unreviewed append')
        return 0
    private.mkdir(parents=True, exist_ok=True)
    if quarantined:
        append_quarantine(quarantine_path, quarantined)
    if quarantined:
        start, end, region = rebuild(parsed, kept)
        text = text[:start] + region + text[end:]
        atomic_write(dreams_path, text)
    atomic_write(ledger_path, json.dumps(ledger, ensure_ascii=False, indent=1) + '\n', True)
    print(json.dumps({'decisions': {d: sum(1 for r in report if r['decision'] == d)
                                    for d in ('approved', 'quarantined')},
                      'dreams_sha256': digest(text)}, ensure_ascii=False))
    return 0


def approve(workspace: Path, target: str, reviewer: str, rationale: str) -> int:
    private = workspace / 'memory/.dreams'
    quarantine_path = private / 'dreams-quarantine.jsonl'
    rows = []
    if quarantine_path.is_file():
        for line in quarantine_path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('sha256') == target:
                rows.append(row)
    if not rows:
        raise ValueError(f'no quarantined DREAMS entry {target}')
    row = rows[-1]
    why = reasons(row.get('body', row['text']))
    if why:
        raise ValueError(f'entry still matches contamination rules: {", ".join(why)}')
    approvals_path = private / 'dreams-approvals.json'
    approvals = load_json(approvals_path, {})
    approvals[target] = {'sha256': target, 'reviewer': reviewer,
                         'rationale': rationale, 'durable': True,
                         'reviewed_on': date.today().isoformat()}
    atomic_write(approvals_path, json.dumps(approvals, ensure_ascii=False, indent=1) + '\n', True)
    # Reinsert before the diary end marker; the next review records it as approved.
    dreams_path = workspace / 'DREAMS.md'
    text = dreams_path.read_text()
    if DIARY_END not in text:
        raise ValueError('DREAMS.md has no diary end marker')
    text = text.replace(DIARY_END, f'\n---\n\n{row["text"]}\n\n{DIARY_END}', 1)
    atomic_write(dreams_path, text)
    print(f'dreams review: approved {target}; rerun review to record it')
    return 0


def atomic_write(path: Path, text: str, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.review-tmp')
    with tmp.open('w') as stream:
        if private:
            os.fchmod(stream.fileno(), 0o600)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--approve', metavar='SHA256')
    parser.add_argument('--reviewer')
    parser.add_argument('--rationale')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if args.list:
        path = workspace / 'memory/.dreams/dreams-quarantine.jsonl'
        if not path.is_file():
            return 0
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            print(f"{row['sha256']} {row.get('date', '')} {','.join(row.get('reasons', []))}")
        return 0
    if args.approve:
        if not args.reviewer or not args.rationale:
            parser.error('--approve needs --reviewer and --rationale')
        lock_dir = workspace / 'memory/.dreams'
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = (lock_dir / 'dreams-review.lock').open('a')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            return approve(workspace, args.approve, args.reviewer, args.rationale)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    if args.check:
        return review(workspace, check_only=True)
    lock_dir = workspace / 'memory/.dreams'
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock = (lock_dir / 'dreams-review.lock').open('a')
    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return review(workspace)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f'dreams review: {exc}', file=sys.stderr)
        raise SystemExit(1)

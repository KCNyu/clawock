#!/usr/bin/env python3
"""Fail-closed review of dreaming candidates; never infer approval from score.

Raw candidates and review receipts stay in ignored memory/.dreams. Only a
hash-bound, explicitly reviewed durable conclusion can enter permanent memory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re

SECTION = re.compile(r'^## Promoted From Short-Term Memory \(\d{4}-\d{2}-\d{2}\)\s*$', re.M)
MARKER = re.compile(r'<!-- openclaw-memory-promotion:(memory:([^\n<>]+?):(\d+):(\d+)) -->')
HEADING = '## Reviewed Dreaming Memory'
RULES = {
    'front_matter': r'\b(?:layout|title|description)\s*:',
    'html': r'</?[A-Za-z][^>]*>',
    'dated_fact': r'\d{4}-\d{2}-\d{2}|\b\d{1,2}:\d{2}\b|今天|昨天|昨夜|当天|今晚|当日|目标价|收在|收盘价',
    'price_or_position': r'\d+\.\d+|\d+\s*(?:股|港元|美元)|买入|卖出|加仓|减仓|仓位动作',
    'internal_metadata': r'/root/|/tmp/|/home/|[A-Z]:\\|\b(?:DONE|BLOCKED|session[_ -]?id|task[_ -]?id|run\s*`?\d+)\b|派发|任务\s*id|模型自报|release-\d|[0-9a-f]{8}-[0-9a-f-]{27,}',
    'command_like': r'`clawock[ -]',
}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def reasons(text):
    return [name for name, pattern in RULES.items() if re.search(pattern, text, re.I)]


def extract(text):
    """Remove only dated promotion sections. Reject unknown structure, don't eat prose."""
    entries, spans = [], []
    for section in SECTION.finditer(text):
        end = re.search(r'^## ', text[section.end():], re.M)
        stop = section.end() + end.start() if end else len(text)
        body = text[section.end():stop]
        matches = list(MARKER.finditer(body))
        if not matches or body[:matches[0].start()].strip():
            raise ValueError('unknown promotion section structure')
        for i, match in enumerate(matches):
            raw = body[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(body)].strip()
            if not raw.startswith('- ') or '\n' in raw:
                raise ValueError('unknown promotion entry structure')
            content = re.sub(r' \[score=[^\n]*\]$', '', raw[2:])
            source = match[2]
            if not re.fullmatch(r'memory/[\w./-]+\.md', source) or '..' in Path(source).parts:
                raise ValueError('unsafe promotion source')
            entries.append(dict(key=match[1], source=source, marker=match[0], text=content,
                                sha256=digest(content)))
        spans.append((section.start(), stop))
    for start, stop in reversed(spans):
        text = text[:start] + text[stop:]
    return text, entries


def validate_batch(text):
    _, entries = extract(text)
    violations = {e['key']: reasons(e['text']) for e in entries if reasons(e['text'])}
    counts = Counter(e['source'] for e in entries)
    duplicates = sorted(s for s, n in counts.items() if n > 1)
    if violations or duplicates:
        raise ValueError(json.dumps({'contamination': violations, 'duplicate_sources': duplicates}))


def review(memory, candidates='', approvals=None):
    base, legacy = extract(memory)
    _, queued = extract(candidates)
    entries = {}
    for entry in legacy + queued:
        old = entries.get(entry['key'])
        if old and old['sha256'] != entry['sha256']:
            raise ValueError('same marker has conflicting content')
        entries[entry['key']] = entry
    approvals = approvals or {}
    counts = Counter(e['source'] for e in entries.values())
    accepted_sources = set(re.findall(r'^- Source: (memory/[\w./-]+\.md):', base, re.M))
    additions, report = [], []
    for entry in entries.values():
        key = entry['key']
        if entry['marker'] in base:
            continue
        why = reasons(entry['text'])
        receipt = approvals.get(key)
        status = 'rejected' if why else 'pending'
        if counts[entry['source']] > 1:
            why.append('same_source_not_independent')
        conclusion = ''
        if receipt and status != 'rejected':
            conclusion = receipt.get('conclusion', '')
            if (receipt.get('sha256') != entry['sha256'] or not receipt.get('reviewer')
                    or not receipt.get('rationale') or receipt.get('durable') is not True
                    or not isinstance(conclusion, str) or not conclusion.strip()
                    or '\n' in conclusion or reasons(conclusion)
                    or re.search(r'<!--|^#|`clawock[ -]', conclusion)):
                raise ValueError(f'invalid review receipt: {key}')
            reviewed_on = date.fromisoformat(receipt['reviewed_on'])
            if not 0 <= (date.today() - reviewed_on).days <= 30:
                raise ValueError(f'expired review receipt: {key}')
            if entry['source'] in accepted_sources:
                status = 'pending'
                why.append('source_already_accepted')
            else:
                accepted_sources.add(entry['source'])
                status = 'approved'
                why.append('explicit_hash_bound_durable_review')
        report.append({**entry, 'decision': status, 'reasons': why})
        if status == 'pending':
            continue
        # Preserve original markers as receipts, outside the budget-evicted sections.
        additions.append(entry['marker'] + '\n' + (
            f'- {conclusion}\n- Source: {entry["source"]}:{key.rsplit(":", 2)[1]}-'
            f'{key.rsplit(":", 2)[2]} (reviewed {receipt["reviewed_on"]}; SHA256 {entry["sha256"]})\n'
            if status == 'approved' else '- Rejected candidate; see private review ledger.\n'))
    if additions:
        base = base + '\n\n' + HEADING + '\n\n' + '\n'.join(additions)
    return base, report


def atomic_write(path, text, private=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.review-tmp')
    with tmp.open('w') as stream:
        if private:
            os.fchmod(stream.fileno(), 0o600)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='audit MEMORY without writing')
    args = parser.parse_args()
    ws = args.workspace.resolve()
    lock_dir = ws / 'memory/.dreams'
    if not args.check:
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = (lock_dir / 'promotion-review.lock').open('a')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    memory_path = ws / 'MEMORY.md'
    memory = memory_path.read_text()
    if args.check:
        validate_batch(memory)
        if SECTION.search(memory):
            raise ValueError('unreviewed promotion section remains')
        print('dreaming review: MEMORY has no unreviewed promotion sections')
        return
    private = ws / 'memory/.dreams'
    candidate_path = private / 'promotion-candidates.md'
    candidates = candidate_path.read_text() if candidate_path.exists() else ''
    legacy_path = private / 'legacy-promotion-candidates.md'
    legacy = legacy_path.read_text() if legacy_path.exists() else ''
    if SECTION.search(memory):
        # Save old direct-to-MEMORY candidates before removing any pending entries.
        _, old_entries = extract(memory)
        known = {e['key'] for e in extract(legacy)[1]}
        new_entries = [e for e in old_entries if e['key'] not in known]
        if new_entries:
            legacy += '\n## Promoted From Short-Term Memory (2000-01-01)\n\n' + ''.join(
                e['marker'] + '\n- ' + e['text'] + '\n' for e in new_entries)
            atomic_write(legacy_path, legacy, True)
    candidates += '\n' + legacy
    approvals_path = private / 'promotion-approvals.json'
    approvals = json.loads(approvals_path.read_text()) if approvals_path.exists() else {}
    output, report = review(memory, candidates, approvals)
    # Archive first: interrupted reruns never lose candidates or their original bytes.
    if report:
        archive = private / f'review-{digest(memory + candidates)}.json'
        if not archive.exists():
            atomic_write(archive, json.dumps({'memory_before': memory, 'candidates_before': candidates,
                         'results': report}, ensure_ascii=False, indent=2) + '\n', True)
    # Detect a concurrent writer rather than replacing its changes. Run after dreaming.
    if memory_path.read_text() != memory:
        raise ValueError('MEMORY changed during review; retry after writer finishes')
    if output != memory:
        atomic_write(memory_path, output)
    print(json.dumps({'decisions': Counter(r['decision'] for r in report),
                      'memory_sha256': digest(output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()

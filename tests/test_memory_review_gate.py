"""Review gate, persistence, real-data audit, and the installed-bundle boundary."""
from datetime import date
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops/host'))


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ops/host' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load('review_dreaming')
patch = load('patch_dreaming_review')


def candidate(text, line=1, source='memory/example.md'):
    return (f'## Promoted From Short-Term Memory (2026-10-26)\n\n'
            f'<!-- openclaw-memory-promotion:memory:{source}:{line}:{line} -->\n'
            f'- {text} [score=0.99 source={source}:{line}-{line}]\n')


def receipt(entry):
    return {'sha256': entry['sha256'], 'reviewer': 'test reviewer',
            'rationale': 'Verified reusable lesson against its source', 'durable': True,
            'reviewed_on': date.today().isoformat(),
            'conclusion': 'Read the source before treating a summary as independent evidence.'}


@pytest.mark.parametrize('text,reason', [
    ('layout: default title: brief description: text', 'front_matter'),
    ('今天做什么: <div class="brief-card">', 'html'),
    ('178.1 卖 40 股，恒科昨天收在 4045.91', 'price_or_position'),
    ('今天在 191.7 卖出', 'dated_fact'),
    ('派发任务 id /root/tools/example DONE', 'internal_metadata'),
    ('npm `clawock-dsh@0.4.1`', 'command_like'),
])
def test_contamination_is_rejected_even_with_approval(text, reason):
    raw = candidate(text)
    entry = gate.extract(raw)[1][0]
    with pytest.raises(ValueError):
        gate.validate_batch(raw)
    cleaned, rows = gate.review(raw, approvals={entry['key']: receipt(entry)})
    assert rows[0]['decision'] == 'rejected'
    assert reason in rows[0]['reasons']
    assert text not in cleaned
    assert entry['marker'] in cleaned
    gate.validate_batch(cleaned)


def test_same_source_cannot_supply_two_promotions():
    raw = candidate('Verify source identity.') + candidate('Check independent evidence.', 2)
    with pytest.raises(ValueError, match='duplicate_sources'):
        gate.validate_batch(raw)
    entries = gate.extract(raw)[1]
    clean, rows = gate.review('', raw, {e['key']: receipt(e) for e in entries})
    assert [r['decision'] for r in rows] == ['approved', 'pending']
    assert clean.count('- Source:') == 1
    # A subsequent batch cannot count the same source again either.
    newer = candidate('A different lesson.', 3)
    entry = gate.extract(newer)[1][0]
    clean2, rows = gate.review(clean, newer, {entry['key']: receipt(entry)})
    assert clean2 == clean and rows[0]['decision'] == 'pending'


def test_pending_is_not_approval_and_approved_text_is_permanent():
    manual = '# Memory\n\n## User preferences\nKeep these exact bytes.\n'
    raw = candidate('Verify source identity.')
    clean, rows = gate.review(manual, raw)
    assert clean == manual and rows[0]['decision'] == 'pending'
    entry = rows[0]
    approved, _ = gate.review(manual, raw, {entry['key']: receipt(entry)})
    assert approved.startswith(manual)
    assert not gate.SECTION.search(approved)
    assert 'SHA256 ' + entry['sha256'] in approved
    assert gate.review(approved, raw)[0] == approved
    # Simulate removal of every dated promotion section by upstream budget compaction.
    assert gate.extract(approved + candidate('Unreviewed future data.', 8))[0] == approved


def test_bad_or_stale_receipt_fails_closed():
    raw = candidate('Verify source identity.')
    entry = gate.extract(raw)[1][0]
    for changes in ({'sha256': 'stale'}, {'reviewed_on': '2000-01-01'},
                    {'conclusion': '<div>bad</div>'}, {'durable': False}):
        with pytest.raises(ValueError):
            gate.review('', raw, {entry['key']: {**receipt(entry), **changes}})


def test_legacy_pending_survives_rerun_and_can_be_reviewed(tmp_path):
    path = tmp_path / 'MEMORY.md'
    path.write_text('# Manual\n\n' + candidate('Verify source identity.'))
    command = [sys.executable, str(ROOT / 'ops/host/review_dreaming.py'), '--workspace', str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    assert path.read_text() == '# Manual\n\n'
    pending = (tmp_path / 'memory/.dreams/legacy-promotion-candidates.md').read_text()
    entry = gate.extract(pending)[1][0]
    (tmp_path / 'memory/.dreams/promotion-approvals.json').write_text(json.dumps({entry['key']: receipt(entry)}))
    subprocess.run(command, check=True, capture_output=True)
    once = path.read_text()
    assert receipt(entry)['conclusion'] in once
    subprocess.run(command, check=True, capture_output=True)
    assert path.read_text() == once


def test_unknown_structure_is_not_silently_removed():
    with pytest.raises(ValueError, match='structure'):
        gate.review(candidate('Good.') + '\nUnrelated human paragraph.\n')


def test_patch_executes_with_private_path_and_no_budget_eviction():
    original = (ROOT / 'tests/fixtures/openclaw_promotion.js').read_text()
    modified = patch.patch(original)
    assert patch.patch(modified) == modified
    with pytest.raises(ValueError, match='anchor'):
        patch.patch(original.replace(patch.OLD_PATH, 'changed'))
    script = r'''
const path = {join: (...p) => p.join('/'), dirname: p => p.slice(0,p.lastIndexOf('/'))};
const writes = [];
const fs = {mkdir: async()=>{}, readFile: async()=>'', writeFile: async(p,t)=>writes.push([p,t])};
const resolveMemoryCoreNowMs = () => 0, resolveMemoryCoreTimestamp = () => 'now';
const toFiniteScore = (v,d)=>v??d, toFiniteNonNegativeInt = (v,d)=>v??d;
const DEFAULT_PROMOTION_MIN_SCORE = 0;
const withShortTermLock = async(_,f)=>f();
const readStore = async()=>({entries:{}}), writeStore = async()=>{};
const isContaminatedDreamingSnippet = ()=>false;
const rehydratePromotionCandidate = async(_,c)=>c;
const extractPromotionMarkers = ()=>new Set();
const buildPromotionSection = ()=>'candidate', withTrailingNewline = s=>s;
const compactMemoryForBudget = p=>{
 if(p.budgetChars !== Number.MAX_SAFE_INTEGER) throw Error('pending eviction');
 return {compacted:p.existingMemory,droppedDates:[]};
};
const appendMemoryHostEvent = async()=>{};
await applyShortTermPromotions({workspaceDir:'/isolated',minRecallCount:0,minUniqueQueries:0,
 candidates:[{key:'x',snippet:'text',score:1,signalCount:0,uniqueQueries:0,recallDays:[]}]});
console.log(JSON.stringify(writes));
'''
    result = subprocess.run(['node', '--input-type=module'], input=modified + script,
                            capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == [['/isolated/memory/.dreams/promotion-candidates.md',
                                         '# Long-Term Memory\n\ncandidate']]


def audit_text():
    target = os.environ.get('DREAMING_AUDIT_MEMORY')
    if not target:
        pytest.skip('Set DREAMING_AUDIT_MEMORY for private real-data before/after verification')
    return Path(target).read_text()


def test_real_promotion_sections_have_no_format_or_transient_content():
    assert not [(e['key'], gate.reasons(e['text'])) for e in gate.extract(audit_text())[1]
                if gate.reasons(e['text'])]


def test_real_batch_has_no_duplicate_sources():
    sources = [e['source'] for e in gate.extract(audit_text())[1]]
    assert len(sources) == len(set(sources))


def test_real_upstream_budget_compaction_preserves_reviewed_conclusion():
    raw = candidate('Verify source identity.')
    entry = gate.extract(raw)[1][0]
    permanent, _ = gate.review('# Manual\n', raw, {entry['key']: receipt(entry)})
    original = (ROOT / 'tests/fixtures/openclaw_memory_compaction.js').read_text()
    script = original + '\nconsole.log(JSON.stringify(compactMemoryForBudget(' + json.dumps({
        'existingMemory': permanent + candidate('Old unreviewed content.', 2),
        'newSection': 'x' * 10001, 'budgetChars': 10000,
    }) + ')));'
    result = subprocess.run(['node', '--input-type=module'], input=script,
                            text=True, capture_output=True, check=True)
    compacted = json.loads(result.stdout)
    assert compacted['droppedDates'] == ['2026-10-26']
    assert receipt(entry)['conclusion'] in compacted['compacted']
    assert entry['marker'] in compacted['compacted']
    assert 'Old unreviewed content.' not in compacted['compacted']

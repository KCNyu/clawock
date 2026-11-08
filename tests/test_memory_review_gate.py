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
dreams = load('review_dreams')
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
    assert entry['marker'] not in cleaned
    assert gate.review(cleaned, raw)[0] == cleaned
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



def diary(*entries):
    body = '\n\n---\n\n'.join(
        f'*November {i + 1}, 2026 at 3:00 AM GMT+8*\n\n{text}' for i, text in enumerate(entries))
    return ('# Dream Diary\n\n<!-- openclaw:dreaming:diary:start -->\n\n---\n\n'
            + body + '\n\n<!-- openclaw:dreaming:diary:end -->\n')


def test_dreams_bootstrap_grandfathers_existing_bytes(tmp_path):
    original = diary('Old entry with a price 123.4.', 'Old second entry.')
    path = tmp_path / 'DREAMS.md'
    path.write_text(original)
    command = [sys.executable, str(ROOT / 'ops/host/review_dreams.py'), '--workspace', str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    assert path.read_text() == original
    ledger = json.loads((tmp_path / 'memory/.dreams/dreams-review.json').read_text())
    assert len(ledger['entries']) == 2
    assert {row['status'] for row in ledger['entries'].values()} == {'grandfathered'}
    subprocess.run(command + ['--check'], check=True, capture_output=True)


def test_dreams_new_entry_is_quarantined_until_a_hash_bound_receipt(tmp_path):
    path = tmp_path / 'DREAMS.md'
    path.write_text(diary('Old entry.'))
    command = [sys.executable, str(ROOT / 'ops/host/review_dreams.py'), '--workspace', str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    text = path.read_text().replace(
        '<!-- openclaw:dreaming:diary:end -->',
        '*November 9, 2026 at 3:00 AM GMT+8*\n\nA clean new entry.\n\n'
        '<!-- openclaw:dreaming:diary:end -->')
    path.write_text(text)
    subprocess.run(command, check=True, capture_output=True)
    assert 'A clean new entry.' not in path.read_text()
    rows = [json.loads(line) for line in
            (tmp_path / 'memory/.dreams/dreams-quarantine.jsonl').read_text().splitlines()]
    assert rows[-1]['reasons'] == ['unreviewed']
    subprocess.run(command + ['--check'], check=True, capture_output=True)
    subprocess.run(command + ['--approve', rows[-1]['sha256'], '--reviewer', 'test',
                              '--rationale', 'checked no transient data'],
                   check=True, capture_output=True)
    subprocess.run(command, check=True, capture_output=True)
    assert 'A clean new entry.' in path.read_text()
    subprocess.run(command + ['--check'], check=True, capture_output=True)


def test_dreams_contaminated_entry_cannot_be_approved(tmp_path):
    path = tmp_path / 'DREAMS.md'
    path.write_text(diary('Old entry.'))
    command = [sys.executable, str(ROOT / 'ops/host/review_dreams.py'), '--workspace', str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    path.write_text(path.read_text().replace(
        '<!-- openclaw:dreaming:diary:end -->',
        '*November 9, 2026 at 3:00 AM GMT+8*\n\n今天在 191.7 卖出 40 股。\n\n'
        '<!-- openclaw:dreaming:diary:end -->'))
    subprocess.run(command, check=True, capture_output=True)
    row = json.loads((tmp_path / 'memory/.dreams/dreams-quarantine.jsonl').read_text().splitlines()[-1])
    assert 'price_or_position' in row['reasons'] or 'dated_fact' in row['reasons']
    failed = subprocess.run(command + ['--approve', row['sha256'], '--reviewer', 'test',
                                       '--rationale', 'bad'], capture_output=True, text=True)
    assert failed.returncode != 0
    assert 'contamination' in failed.stderr


def test_unsafe_promotion_source_is_rejected_without_raising():
    raw = candidate('A reusable lesson.').replace('memory/example.md', '../outside.md')
    clean, rows = gate.review('# Memory\n', raw)
    assert clean == '# Memory\n'
    assert rows[0]['decision'] == 'rejected' and 'unsafe_source' in rows[0]['reasons']


def test_commit_dreaming_keeps_dreams_when_memory_review_fails(tmp_path):
    ws = tmp_path / 'ws'
    (ws / 'ops/host').mkdir(parents=True)
    (ws / 'ops/publish').mkdir(parents=True)
    (ws / 'MEMORY.md').write_text('# Memory\n')
    (ws / 'DREAMS.md').write_text('# Dream Diary\n')
    (ws / 'ops/host/promote_dreaming.py').write_text('raise SystemExit(1)\n')
    (ws / 'ops/host/review_dreaming.py').write_text('raise SystemExit(1)\n')
    (ws / 'ops/host/review_dreams.py').write_text('raise SystemExit(0)\n')
    (ws / 'ops/publish/safe_push.sh').write_text('#!/bin/bash\nexit 0\n')
    (ws / 'ops/host/commit_dreaming.sh').write_text(
        (ROOT / 'ops/host/commit_dreaming.sh').read_text())
    subprocess.run(['git', 'init', '-q'], cwd=ws, check=True)
    subprocess.run(['git', 'config', 'user.name', 'test'], cwd=ws, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=ws, check=True)
    proc = subprocess.run(['bash', str(ws / 'ops/host/commit_dreaming.sh')], cwd=ws,
                          env={**os.environ, 'DREAMING_WORKSPACE': str(ws)},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    files = subprocess.run(['git', 'show', '--name-only', '--format=', 'HEAD'], cwd=ws,
                           capture_output=True, text=True, check=True).stdout.split()
    assert files == ['DREAMS.md']

def _git_worktree(tmp_path, files):
    ws = tmp_path / 'ws'
    (ws / 'ops/host').mkdir(parents=True)
    (ws / 'ops/publish').mkdir(parents=True)
    for name, content in files.items():
        path = ws / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    (ws / 'ops/publish/safe_push.sh').write_text('#!/bin/bash\nexit 0\n')
    (ws / 'ops/host/commit_dreaming.sh').write_text(
        (ROOT / 'ops/host/commit_dreaming.sh').read_text())
    subprocess.run(['git', 'init', '-q'], cwd=ws, check=True)
    subprocess.run(['git', 'config', 'user.name', 'test'], cwd=ws, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.invalid'], cwd=ws, check=True)
    return ws


def test_commit_dreaming_keeps_memory_when_dreams_review_fails(tmp_path):
    ws = _git_worktree(tmp_path, {
        'MEMORY.md': '# Memory\n',
        'DREAMS.md': '# Dream Diary\n',
        'ops/host/promote_dreaming.py': (
            'from pathlib import Path\n'
            'Path("MEMORY.md").write_text("# Memory\\n\\n## Promoted\\n")\n'),
        'ops/host/review_dreaming.py': 'raise SystemExit(0)\n',
        'ops/host/review_dreams.py': 'raise SystemExit(1)\n',
    })
    proc = subprocess.run(['bash', str(ws / 'ops/host/commit_dreaming.sh')], cwd=ws,
                          env={**os.environ, 'DREAMING_WORKSPACE': str(ws)},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    files = subprocess.run(['git', 'show', '--name-only', '--format=', 'HEAD'], cwd=ws,
                           capture_output=True, text=True, check=True).stdout.split()
    assert files == ['MEMORY.md']


def test_commit_dreaming_commits_memory_and_dreams_separately(tmp_path):
    ws = _git_worktree(tmp_path, {
        'MEMORY.md': '# Memory\n',
        'DREAMS.md': '# Dream Diary\n',
        'ops/host/promote_dreaming.py': (
            'from pathlib import Path\n'
            'Path("MEMORY.md").write_text("# Memory\\n\\n## Promoted\\n")\n'),
        'ops/host/review_dreaming.py': 'raise SystemExit(0)\n',
        'ops/host/review_dreams.py': (
            'import sys\n'
            'from pathlib import Path\n'
            'if "--check" not in sys.argv:\n'
            '    Path("DREAMS.md").write_text("# Dream Diary\\n\\n- new diary line\\n")\n'),
    })
    proc = subprocess.run(['bash', str(ws / 'ops/host/commit_dreaming.sh')], cwd=ws,
                          env={**os.environ, 'DREAMING_WORKSPACE': str(ws)},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    subjects = subprocess.run(['git', 'log', '--format=%s', '-2'], cwd=ws,
                              capture_output=True, text=True, check=True).stdout.splitlines()
    assert len(subjects) == 2
    newest = subprocess.run(['git', 'show', '--name-only', '--format=', 'HEAD'], cwd=ws,
                            capture_output=True, text=True, check=True).stdout.split()
    previous = subprocess.run(['git', 'show', '--name-only', '--format=', 'HEAD~1'], cwd=ws,
                              capture_output=True, text=True, check=True).stdout.split()
    assert newest == ['DREAMS.md']
    assert previous == ['MEMORY.md']


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


def test_old_rejected_receipts_migrate_privately_and_never_return(tmp_path):
    raw = candidate('今天买入 40 股')
    entry = gate.extract(raw)[1][0]
    manual = '# Memory\n\n## Preferences\nKeep my wording.\n'
    old = manual + '\n' + gate.HEADING + '\n\n' + entry['marker'] + (
        '\n- Rejected candidate; see private review ledger.\n')
    path = tmp_path / 'MEMORY.md'
    path.write_text(old)
    private = tmp_path / 'memory/.dreams'
    private.mkdir(parents=True)
    (private / 'promotion-candidates.md').write_text(raw)
    command = [sys.executable, str(ROOT / 'ops/host/review_dreaming.py'), '--workspace', str(tmp_path)]
    subprocess.run(command, check=True, capture_output=True)
    assert path.read_text() == manual
    archives = list(private.glob('review-*.json'))
    ledger = json.loads(archives[0].read_text())
    assert ledger['memory_before'] == old
    assert ledger['results'][0]['decision'] == 'rejected'
    assert archives[0].stat().st_mode & 0o777 == 0o600
    for _ in range(3):
        subprocess.run(command, check=True, capture_output=True)
        assert path.read_text() == manual
    assert len(list(private.glob('review-*.json'))) == 2
    subprocess.run(command + ['--check'], check=True, capture_output=True)


def test_migration_preserves_approved_and_human_sections():
    raw = candidate('Verify source identity.')
    entry = gate.extract(raw)[1][0]
    approved, _ = gate.review('# Memory\n', raw, {entry['key']: receipt(entry)})
    rejected = gate.extract(candidate('今天买入 40 股', 2))[1][0]
    old = approved + rejected['marker'] + '\n- Rejected candidate; see private review ledger.\n'
    clean = gate.clean_rejected_receipts(old)
    assert clean == approved
    human = '\n## Human notes\n- Rejected candidate; see private review ledger.\n'
    assert gate.clean_rejected_receipts(approved + human) == approved + human
    newer = candidate('Check primary evidence.', 3, 'memory/other.md')
    other = gate.extract(newer)[1][0]
    result, _ = gate.review(clean, newer, {other['key']: receipt(other)})
    assert result.count(gate.HEADING) == 1
    assert result.count('- Source:') == 2


def test_receipt_only_migration_keeps_a_private_before_image(tmp_path):
    entry = gate.extract(candidate('今天买入 40 股'))[1][0]
    original = '# Memory\n\n' + gate.HEADING + '\n\n' + entry['marker'] + (
        '\n- Rejected candidate; see private review ledger.\n')
    path = tmp_path / 'MEMORY.md'
    path.write_text(original)
    command = [sys.executable, str(ROOT / 'ops/host/review_dreaming.py'), '--workspace', str(tmp_path)]
    assert subprocess.run(command + ['--check'], capture_output=True).returncode != 0
    subprocess.run(command, check=True, capture_output=True)
    assert path.read_text() == '# Memory\n'
    archives = list((tmp_path / 'memory/.dreams').glob('review-*.json'))
    assert len(archives) == 1
    assert json.loads(archives[0].read_text())['memory_before'] == original
    subprocess.run(command, check=True, capture_output=True)
    assert len(list((tmp_path / 'memory/.dreams').glob('review-*.json'))) == 1


def test_near_match_is_human_prose_not_a_generated_receipt():
    entry = gate.extract(candidate('今天买入 40 股'))[1][0]
    text = gate.HEADING + '\n\n' + entry['marker'] + (
        '\n- Rejected candidate; see private review ledger. Human annotation.\n')
    assert gate.clean_rejected_receipts(text) == text


def test_commit_dreaming_never_commits_another_writer_staged_file(tmp_path):
    ws = _git_worktree(tmp_path, {
        'MEMORY.md': '# Memory\n',
        'DREAMS.md': '# Dream Diary\n',
        'OTHER.md': 'another writer\n',
        'ops/host/promote_dreaming.py': (
            'from pathlib import Path\n'
            'Path("MEMORY.md").write_text("# Memory\\n\\n## Promoted\\n")\n'),
        'ops/host/review_dreaming.py': 'raise SystemExit(0)\n',
        'ops/host/review_dreams.py': (
            'import sys\n'
            'from pathlib import Path\n'
            'if "--check" not in sys.argv:\n'
            '    Path("DREAMS.md").write_text("# Dream Diary\\n\\n- new diary line\\n")\n'),
    })
    subprocess.run(['git', 'add', 'OTHER.md'], cwd=ws, check=True)
    proc = subprocess.run(['bash', str(ws / 'ops/host/commit_dreaming.sh')], cwd=ws,
                          env={**os.environ, 'DREAMING_WORKSPACE': str(ws)},
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    staged = subprocess.run(['git', 'diff', '--cached', '--name-only'], cwd=ws,
                            capture_output=True, text=True, check=True).stdout.split()
    assert staged == ['OTHER.md']
    committed = subprocess.run(['git', 'log', '--format=', '--name-only', '-2'], cwd=ws,
                               capture_output=True, text=True, check=True).stdout.split()
    assert sorted(committed) == ['DREAMS.md', 'MEMORY.md']


def private_store(tmp_path):
    store = tmp_path / 'store'
    store.mkdir()
    (store / 'project-private.md').write_text(
        '---\nname: project-private\ndescription: "private evidence"\nmetadata:\n'
        '  type: project\n  scope: engineering\n  publish: private\n---\n\n'
        'The private evidence line says this exact sentence is not for publication.\n')
    return store


def test_dreams_new_entry_copying_a_private_topic_is_quarantined(tmp_path):
    store = private_store(tmp_path)
    path = tmp_path / 'DREAMS.md'
    path.write_text(diary('Old entry.'))
    command = [sys.executable, str(ROOT / 'ops/host/review_dreams.py'),
               '--workspace', str(tmp_path), '--store', str(store)]
    subprocess.run(command, check=True, capture_output=True)
    path.write_text(path.read_text().replace(
        '<!-- openclaw:dreaming:diary:end -->',
        '*November 9, 2026 at 3:00 AM GMT+8*\n\nThe private evidence line says this exact '
        'sentence is not for publication.\n\n<!-- openclaw:dreaming:diary:end -->'))
    subprocess.run(command, check=True, capture_output=True)
    assert 'private evidence line' not in path.read_text()
    row = json.loads((tmp_path / 'memory/.dreams/dreams-quarantine.jsonl').read_text().splitlines()[-1])
    assert 'private_topic_copy:project-private' in row['reasons']
    failed = subprocess.run(command + ['--approve', row['sha256'], '--reviewer', 'test',
                                       '--rationale', 'it is only a rule'], capture_output=True, text=True)
    assert failed.returncode != 0
    assert 'private_topic_copy:project-private' in failed.stderr


def test_grandfathered_dreams_bytes_are_not_rewritten_by_the_source_check(tmp_path):
    store = private_store(tmp_path)
    original = diary('The private evidence line says this exact sentence is not for publication.')
    path = tmp_path / 'DREAMS.md'
    path.write_text(original)
    command = [sys.executable, str(ROOT / 'ops/host/review_dreams.py'),
               '--workspace', str(tmp_path), '--store', str(store)]
    subprocess.run(command, check=True, capture_output=True)
    assert path.read_text() == original
    subprocess.run(command + ['--check'], check=True, capture_output=True)

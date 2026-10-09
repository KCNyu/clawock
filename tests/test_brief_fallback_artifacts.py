"""The off-host fallback writes what the host brief writes, and says it did.

Two findings from the 2026-10-09 audit of the LLM cron jobs:

#2817 — the fallback asked its model for "markdown + a plan block" and wrote
only those, while postflight has required the judgment overlay since #1232. A
perfect reply therefore still failed the very next workflow step.

#2818 — the weekly rehearsal decided "the chain produced a brief" from
`pre-open.md` existing, on days the checkout already carries the primary
path's brief.
"""
from __future__ import annotations

import json

import pytest

from clawock.automation import brief_fallback as bf
from clawock.context import brief as brief_context
from clawock.decision import packet as packet_mod
from clawock.harness import brief_postflight

from test_brief_decision_packet import _context

TODAY = '2026-07-28'


def write_generation(root, today=TODAY):
    """A workspace holding one real preflight generation; returns its packet."""
    (root / 'memory' / '.tmp').mkdir(parents=True, exist_ok=True)
    (root / 'skills' / 'daily-deep-brief').mkdir(parents=True, exist_ok=True)
    for name in ('SOUL.md', 'BOOTSTRAP.md', 'skills/daily-deep-brief/SKILL.md'):
        (root / name).write_text('fixture', encoding='utf-8')
    context = _context()
    context['date'] = today
    packet = packet_mod.compile_packet(context, brief_context.compute_generation_id(context))
    brief_context.write_run_bundle(
        context, root / 'memory' / '.tmp' / f'brief-context-{today}.json',
        tool_artifacts={'decision_packet': packet})
    return packet


def model_reply(packet, today=TODAY, *, date=None):
    """What a well-behaved model returns: the template filled in, plus a plan."""
    judgment = packet_mod.judgment_template(packet)
    judgment['portfolio_assessment'] = '组合偏防守，等待确认'
    judgment['portfolio_counterargument'] = '若指数企稳则防守过度'
    for field, value in list(judgment['narrative'].items()):
        if field != 'risk_voice_first':
            judgment['narrative'][field] = ['观察开盘量能'] if isinstance(value, list) else '持仓结构未变'
    for row in judgment['ticker_judgments']:
        for field, value in list(row.items()):
            if value == '':
                row[field] = '维持观察'
    # The model copying the generation hash wrong must not cost the day its brief.
    judgment['context_generation_id'] = 'copied-wrong'
    ticker = next(name for name, row in packet['tickers'].items()
                  if 'hold_and_watch' in row['constraints']['allowed_actions'])
    plan = {'schema_version': 2, 'date': date or today, 'decisions': [{
        'ticker': ticker, 'strategy_id': 'core_position', 'action': 'hold_and_watch',
        'condition': {'type': 'open'}, 'confidence': 0.6, 'driven_by': 'technical'}]}
    return '结果如下：\n```json\n' + json.dumps(
        {'plan': plan, 'judgment': judgment}, ensure_ascii=False) + '\n```'


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    monkeypatch.setenv('TODAY', TODAY)
    return tmp_path


def test_a_good_reply_yields_the_artifacts_postflight_consumes(workspace, monkeypatch):
    packet = write_generation(workspace)
    generation = packet['_meta']['generation_id']
    seen = {}

    def chat(**kwargs):
        seen.update(kwargs)
        return model_reply(packet)

    monkeypatch.setattr(bf, 'chat', chat)
    bf.main([])

    # The single turn was given the packet and the template, not only the manual.
    assert '"brief_decision_packet"' in seen['user'] and '"ticker_judgments"' in seen['user']

    paths = bf.artifact_paths(workspace, TODAY)
    plan = json.loads(paths['plan'].read_text())
    judgment = json.loads(paths['judgment'].read_text())
    assert plan['context_generation_id'] == judgment['context_generation_id'] == generation
    # The report is rendered by the harness from exactly these two files.
    from clawock.harness import brief_render
    issues, body = brief_render.render_from_workspace(workspace, TODAY, write=False)
    assert body.startswith('---') and brief_render.SECTOR_SCAN_MISSING in issues

    # The consumer's own gates, on the files as written.
    read_back = packet_mod.read_packet(
        workspace / 'memory' / '.tmp' / f'brief-context-{TODAY}' / 'manifest.json')
    gaps = brief_postflight._judgment_gap_issues(paths['judgment'], read_back)
    assert gaps == []
    assert packet_mod.validate_plan_constraints(plan, read_back) == []
    assert brief_postflight.categorize(gaps) == 'pass'

    assert bf.main(['--verify-receipt']) == 0


def test_a_failed_model_call_leaves_the_existing_brief_and_no_receipt(workspace, monkeypatch, capsys):
    """#2818's exact case: the primary brief is already in the checkout."""
    write_generation(workspace)
    existing = workspace / 'memory' / f'{TODAY}-pre-open.md'
    existing.write_text('the primary path wrote this\n', encoding='utf-8')

    def chat(**_kwargs):
        raise RuntimeError('all LLM providers failed: minimax[timeout after 233s]')

    monkeypatch.setattr(bf, 'chat', chat)
    with pytest.raises(RuntimeError):
        bf.main([])

    assert existing.read_text(encoding='utf-8') == 'the primary path wrote this\n'
    assert bf.main(['--verify-receipt']) == 1
    assert 'did not generate' in capsys.readouterr().out


def test_a_receipt_stops_vouching_once_a_file_is_replaced(workspace, monkeypatch):
    packet = write_generation(workspace)
    monkeypatch.setattr(bf, 'chat', lambda **_kw: model_reply(packet))
    bf.main([])
    assert bf.verify_receipt(workspace, TODAY)[0]

    bf.artifact_paths(workspace, TODAY)['judgment'].write_text('{"someone": "else"}\n')
    ok, message = bf.verify_receipt(workspace, TODAY)
    assert not ok and 'judgment' in message


@pytest.mark.parametrize('reply', [
    '只有散文，没有 JSON。',
    '```json\n{"schema_version": 2, "decisions": []}\n```',      # the old plan-only shape
    '```json\n{"plan": {"decisions": []}, "judgment": "见上文"}\n```',
])
def test_a_reply_without_both_objects_writes_nothing(workspace, monkeypatch, reply):
    write_generation(workspace)
    monkeypatch.setattr(bf, 'chat', lambda **_kw: reply)
    with pytest.raises(SystemExit):
        bf.main([])
    paths = bf.artifact_paths(workspace, TODAY)
    assert not any(path.exists() for path in paths.values())
    assert not bf.receipt_path(workspace, TODAY).exists()


def test_a_context_without_its_packet_is_refused_before_the_model_is_called(workspace, monkeypatch):
    (workspace / 'memory' / '.tmp').mkdir(parents=True)
    for name in ('SOUL.md', 'BOOTSTRAP.md'):
        (workspace / name).write_text('fixture')
    (workspace / 'memory' / '.tmp' / f'brief-context-{TODAY}.json').write_text(json.dumps(
        {'portfolio': {'portfolios': {'hk_stocks': {}, 'us_stocks': {}}}}))
    monkeypatch.setattr(bf, 'chat', lambda **_kw: pytest.fail('model called without a packet'))
    with pytest.raises(SystemExit, match='decision packet unavailable'):
        bf.main([])


def test_one_rejected_reply_gets_one_repair_turn_naming_what_failed(workspace, monkeypatch):
    """The first real run of the plan + judgment contract (rehearsal 2026-10-09)
    returned a well-formed reply whose ninth decision was an `add` without its
    setup fields, and the whole brief was discarded. The host brief gets a fix-
    and-rerun from postflight; the single turn gets exactly one."""
    packet = write_generation(workspace)
    good = model_reply(packet)
    bad = json.loads(good[good.index('{'):good.rindex('}') + 1])
    bad['plan']['decisions'][0]['action'] = 'add_only_on_trigger'
    prompts = []

    def chat(**kwargs):
        prompts.append(kwargs)
        return json.dumps(bad, ensure_ascii=False) if len(prompts) == 1 else good

    monkeypatch.setattr(bf, 'chat', chat)
    bf.main([])

    assert len(prompts) == 2
    repair = prompts[1]['user']
    assert prompts[0]['user'] in repair and json.dumps(bad, ensure_ascii=False) in repair
    reason = repair.split('它没有通过写盘前的校验')[1]
    ticker = bad['plan']['decisions'][0]['ticker']
    assert f'decision[0] is {ticker} add_only_on_trigger: packet allowed_actions=' in reason
    assert 'technical.setups' in reason
    assert prompts[1]['deadline_seconds'] <= bf.BRIEF_LLM_TIMEOUT_SECONDS
    assert bf.main(['--verify-receipt']) == 0


def test_rejections_past_the_repair_turns_write_nothing(workspace, monkeypatch):
    packet = write_generation(workspace)
    good = model_reply(packet)
    bad = json.loads(good[good.index('{'):good.rindex('}') + 1])
    bad['plan']['decisions'][0]['action'] = 'add_only_on_trigger'
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return json.dumps(bad, ensure_ascii=False)

    monkeypatch.setattr(bf, 'chat', chat)
    with pytest.raises(SystemExit, match='repair turn'):
        bf.main([])
    assert len(calls) == 1 + bf.MAX_REPAIR_TURNS
    assert not any(path.exists() for path in bf.artifact_paths(workspace, TODAY).values())
    assert bf.main(['--verify-receipt']) == 1


def test_no_repair_turn_is_started_without_budget_left(workspace, monkeypatch):
    """Two full provider budgets do not fit the job: the repair turn spends
    what the first call left, and is skipped when that is too little."""
    packet = write_generation(workspace)
    monkeypatch.setenv(bf.DEADLINE_ENV, str(bf.REPAIR_MIN_SECONDS - 1))
    calls = []
    monkeypatch.setattr(bf, 'chat', lambda **kw: calls.append(kw) or '没有 JSON')
    with pytest.raises(SystemExit, match='no repair turn'):
        bf.main([])
    assert len(calls) == 1 and packet


def test_a_decision_on_a_name_outside_the_book_is_told_so(workspace, monkeypatch):
    packet = write_generation(workspace)
    good = model_reply(packet)
    bad = json.loads(good[good.index('{'):good.rindex('}') + 1])
    bad['plan']['decisions'].append({**bad['plan']['decisions'][0], 'ticker': 'NVDA',
                                     'action': 'add_only_on_trigger'})
    with pytest.raises(bf.ReplyRejected, match='NVDA add_only_on_trigger: not a holding'):
        bf.checked_reply(json.dumps(bad, ensure_ascii=False), TODAY, packet)

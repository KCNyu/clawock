"""Mode 6 gets an exact prose budget before the model starts writing."""
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))
import _harness_common as common  # noqa: E402
import report_preflight as preflight  # noqa: E402
import report_postflight as postflight  # noqa: E402


def test_budget_arithmetic_matches_the_assembled_message_boundaries():
    title = 'T' * 28
    raw = 'R' * 1_596

    budget = common.report_prose_budget(title, raw, market='us')

    assert budget == {
        'assembled_target_chars': 2_800,
        'title_chars': 28,
        'raw_block_chars': 1_596,
        'separator_chars': 4,
        'fixed_chars': 1_628,
        'prose_target_chars': 1_172,
        'prose_soft_limit_chars': 1_372,
        'prose_hard_limit_chars': 1_872,
    }
    at_soft = 'P' * budget['prose_soft_limit_chars']
    over_soft = at_soft + 'P'
    ctx = {'market': 'us', 'title': title, 'raw_wechat_block': raw}
    assert len(postflight.assemble_message(ctx, at_soft)) == 3_000
    assert len(postflight.assemble_message(ctx, over_soft)) == 3_001


def test_small_hk_block_gets_more_prose_room_but_the_same_assembled_limits():
    budget = common.report_prose_budget('T' * 25, 'R' * 664, market='hk')

    assert budget['prose_target_chars'] == 2_107
    assert budget['prose_soft_limit_chars'] == 2_307
    assert budget['prose_hard_limit_chars'] == 2_807


def test_retained_us_runs_would_have_received_feasible_earlier_targets():
    observed = (
        # phase, title chars, raw chars, prose chars
        ('open', 28, 1_596, 1_587),
        ('close', 19, 1_520, 1_740),
    )
    for phase, title_chars, raw_chars, prose_chars in observed:
        budget = common.report_prose_budget(
            'T' * title_chars, 'R' * raw_chars, market='us')
        assert 1_000 <= budget['prose_target_chars'] < prose_chars, phase
        assert budget['prose_target_chars'] < budget['prose_soft_limit_chars'], phase


def test_successful_preflight_publishes_the_budget_in_its_context(
        tmp_path, monkeypatch, capsys):
    raw = 'R' * 1_596
    monkeypatch.setattr(preflight, 'TMP', tmp_path)
    monkeypatch.setattr(preflight, '_market_closed_reason', lambda *_: None)
    monkeypatch.setattr(preflight, 'run_analyze', lambda _market: (0, raw, ''))
    monkeypatch.setattr(
        preflight, 'parse_signals', lambda _raw: {'watch': 0, 'stop': 0, 'trim': 0})
    monkeypatch.setattr(preflight, 'parse_anomalies', lambda _raw: [])
    monkeypatch.setattr(preflight, 'collect_peers', lambda _market: {})
    monkeypatch.setattr(
        preflight.research_surface, 'movers_thesis_context', lambda _tickers: {})
    monkeypatch.setattr(preflight.mover_news, 'probe', lambda *_a, **_k: {})
    monkeypatch.setattr(
        preflight.plan_surface, 'open_decisions_context', lambda **_k: {})
    monkeypatch.setattr(
        preflight.workflow_outcomes, 'job_for', lambda *_: '美股开盘报告')
    monkeypatch.setattr(
        preflight.workflow_outcomes, 'slot_for_job', lambda _job: 'slot')
    monkeypatch.setattr(
        preflight.workflow_outcomes, 'record_stage', lambda *_a, **_k: {})
    monkeypatch.setattr(
        sys, 'argv', ['report_preflight.py', '--market', 'us', '--phase', 'open'])

    assert preflight.main() == 0

    announced = capsys.readouterr().out.strip().splitlines()[-1]
    context = Path(announced.split('context_path: ', 1)[1])
    result = json.loads(context.read_text())
    assert result['size_budget'] == common.report_prose_budget(
        result['title'], result['raw_wechat_block'], market='us')
    assert result['size_budget']['prose_target_chars'] < 1_587


def test_postflight_uses_the_same_shared_limits_as_preflight_budget():
    assert postflight.CHAR_LIMITS is common.REPORT_CHAR_LIMITS


def test_us_and_hk_skills_require_dynamic_budget_check_without_content_deletion():
    for skill_name in ('us-stock-analysis', 'hk-stock-analysis'):
        text = (ROOT / 'skills' / skill_name / 'SKILL.md').read_text(
            encoding='utf-8')
        mode6 = text.split('### Mode 6', 1)[1].split('### Mode 5', 1)[0]
        assert 'prose_target_chars' in mode6
        assert 'prose_soft_limit_chars' in mode6
        assert 'wc -m' in mode6
        assert '禁止' in mode6 and '删除' in mode6
        for required in ('异动归因', '计划对账', '风险提示'):
            assert required in mode6

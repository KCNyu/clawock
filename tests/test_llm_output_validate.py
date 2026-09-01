"""Output-side gate for the four LLM call sites (#1257/#1262/#1263/#1264/#1265).

Two directions matter equally here:

- a broken reply must be refused (that is the bug: an empty body, a stub, or
  prose instead of the requested markdown was published verbatim);
- a *real* reply must still pass. Anchors that are too strict fail closed on
  good output, which costs a whole day's brief, so every anchor set is pinned
  against a committed artifact of that kind rather than against a hand-written
  sample: `memory/2026-07-16-pre-open.md` is the last brief the fallback
  actually authored, and `memory/weekly/2026-W34.md` a real weekly review.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from clawock.automation import brief_fallback, news_digest, weekly_review
from clawock.automation.output_validate import (
    LLMOutputError,
    coerce_scored_items,
    validate_sections,
)
from clawock.workspace import workspace_root

WS = workspace_root()


def _read(relative):
    path = WS / relative
    if not path.exists():
        pytest.skip(f'{relative} not present in this checkout')
    return path.read_text()


# ── markdown gate ────────────────────────────────────────────────────────────

def test_empty_and_stub_replies_are_refused():
    for body in ('', '   \n\n', None):
        with pytest.raises(LLMOutputError, match='empty reply'):
            validate_sections(body, label='x', required=('A',), min_chars=10)
    with pytest.raises(LLMOutputError, match='below the'):
        validate_sections('# A\n', label='x', required=('A',), min_chars=100)


def test_missing_section_names_the_missing_ones():
    body = 'x' * 200 + '\n## 本周净值\n'
    with pytest.raises(LLMOutputError) as excinfo:
        validate_sections(body, label='weekly review',
                          required=weekly_review.WEEKLY_REQUIRED_SECTIONS,
                          min_chars=100)
    message = str(excinfo.value)
    assert '决策兑现' in message and '风险演变' in message and '下周关注' in message
    assert '本周净值' not in message


def test_weak_anchor_does_not_wave_through_a_sectionless_digest():
    # `Top` alone matched "stop-loss" anywhere in the prose.
    body = 'stop-loss 与 laptop 的散文 ' * 40 + '\n## Per-ticker 简报\n'
    with pytest.raises(LLMOutputError, match='移动信号'):
        validate_sections(body, label='news digest',
                          required=news_digest.DIGEST_REQUIRED_SECTIONS,
                          min_chars=100)


def test_anchor_match_is_case_insensitive_and_substring():
    # The live digest answers `## 风险 Watch` to a prompt asking for `风险 watch`,
    # and the fallback brief writes `## ▎仓位明细 (HK)` for `仓位明细`.
    body = 'y' * 200 + '\n## ▎Per-TICKER 简报\n## Top 移动信号\n'
    assert validate_sections(body, label='news digest',
                             required=news_digest.DIGEST_REQUIRED_SECTIONS,
                             min_chars=100) is body


def test_real_committed_artifacts_pass_their_own_anchors():
    """Regression guard against over-strict anchors — the expensive direction."""
    brief = _read('memory/2026-07-16-pre-open.md')      # last fallback-authored brief
    validate_sections(brief, label='brief markdown',
                      required=brief_fallback.BRIEF_REQUIRED_SECTIONS,
                      min_chars=2000)

    review = _read('memory/weekly/2026-W34.md')
    validate_sections(review, label='weekly review',
                      required=weekly_review.WEEKLY_REQUIRED_SECTIONS,
                      min_chars=1000)

    digest_path = WS / 'assets' / 'data' / 'us_news_digest.json'
    if digest_path.exists():
        digest = (json.loads(digest_path.read_text()).get('digest_markdown') or '')
        if digest.strip():                    # empty on a no-material-news day
            validate_sections(digest, label='news digest',
                              required=news_digest.DIGEST_REQUIRED_SECTIONS,
                              min_chars=300)


def test_call_sites_validate_before_they_write():
    """The gate is worthless if it runs after the artifact is on disk (the
    2026-07-16 lesson that put plan validation ahead of the write)."""
    for module, write_marker in (
        (brief_fallback, "Path(f'memory/{today}-pre-open.md').write_text"),
        (weekly_review, 'path.write_text'),
        (news_digest, '_write_artifact(tickers, raw, source_status, digest='),
    ):
        source = Path(module.__file__).read_text()
        gate = source.index('validate_sections(')
        # first write that follows the chat() call, not an earlier fail-closed one
        after_chat = source.index('= chat(')
        write = source.index(write_marker, after_chat)
        assert gate < write, f'{module.__name__} writes before it validates'


# ── influencer structured gate ───────────────────────────────────────────────

def _item(**over):
    base = {'idx': 0, 'tickers': ['PLTR'], 'held': ['PLTR'], 'new_ideas': [],
            'sectors': ['AI'], 'sector_holdings': [], 'stance': 'endorse',
            'relevance': 80, 'summary_cn': 'x'}
    base.update(over)
    return base


def test_one_bad_idx_no_longer_loses_the_whole_batch():
    """`{int(it['idx']): it for it in items}` raised on the first non-int idx,
    and llm_filter's except turned that into `{}` — every scored item lost."""
    scored = coerce_scored_items(
        {'items': [_item(idx='not_a_number'), _item(idx=1), _item(idx=2)]},
        report_to=None)
    assert sorted(scored) == [1, 2]


def test_unknown_stance_degrades_and_relevance_is_clamped():
    scored = coerce_scored_items(
        {'items': [_item(idx=1, stance='BULLISH', relevance=150),
                   _item(idx=2, stance='Attack', relevance=-5),
                   _item(idx=3, relevance='high')]},
        report_to=None)
    assert scored[1]['stance'] == 'neutral'     # not in the prompt's enum
    assert scored[1]['relevance'] == 100        # was outranking every honest 95
    assert scored[2]['stance'] == 'attack'      # case is not a violation
    assert scored[2]['relevance'] == 0
    assert scored[3]['relevance'] is None       # unscored, not 0


def test_hallucinated_fields_do_not_reach_the_artifact():
    scored = coerce_scored_items(
        {'items': [_item(idx=1, hallucinated_field='x', nested={'a': 1})]},
        report_to=None)
    assert set(scored[1]) == {
        'idx', 'tickers', 'held', 'new_ideas', 'sectors', 'sector_holdings',
        'stance', 'relevance', 'summary_cn'}


def test_top_level_shape_still_raises_so_the_caller_retries():
    for payload in (['items'], {'items': 'nope'}):
        with pytest.raises(LLMOutputError):
            coerce_scored_items(payload, report_to=None)


def test_coercion_problems_are_reported_not_silent(capsys):
    coerce_scored_items({'items': [_item(idx='x'), _item(idx=1, stance='BULLISH')]})
    err = capsys.readouterr().err
    assert 'bad_idx=1' in err and 'unknown_stance=1' in err


def test_influencer_does_not_retry_a_dead_provider_chain(monkeypatch):
    """#1260: a second attempt spends the same chain budget against providers
    that just reported total failure; the 8-minute job has room for one."""
    from clawock.automation import influencer

    calls = []

    def _dead(**kwargs):
        calls.append(1)
        raise RuntimeError('all LLM providers failed: minimax[x] | opencode[y]')

    monkeypatch.setenv('MINIMAX_API_KEY', 'k')
    monkeypatch.setattr('clawock.automation.llm.chat', _dead)
    assert influencer.llm_filter([{'author': 'Trump', 'text': 'hi'}], []) == {}
    assert len(calls) == 1

    calls.clear()

    def _bad_json(**kwargs):
        calls.append(1)
        return 'not json'

    monkeypatch.setattr('clawock.automation.llm.chat', _bad_json)
    assert influencer.llm_filter([{'author': 'Trump', 'text': 'hi'}], []) == {}
    assert len(calls) == 2, 'a parse failure is still worth one retry'


# ── digest regex visibility (#1258) ──────────────────────────────────────────

def test_unmatched_digest_bullets_are_counted(capsys, monkeypatch):
    from clawock.evidence import news_evidence_graph as graph

    payload = {'generated_at': '2026-09-01T00:00:00+00:00', 'digest_markdown': (
        '## Top 移动信号\n'
        '- **PLTR**: 合约落地\n'          # matches
        '- PLTR: 没有 bold\n'             # drift the regex cannot read
        '- **HOOD** - dash 不是 colon\n'  # ditto
        '普通散文行\n'                     # not a bullet: legitimately skipped
    )}
    policy = graph.load_policy()          # before _load is stubbed: it uses it too
    monkeypatch.setattr(graph, '_load', lambda *a, **k: payload)
    events = graph.collect_us_news_events(policy, {})
    assert len(events) == 1
    err = capsys.readouterr().err
    assert re.search(r'2 bullet line\(s\) did not match', err)

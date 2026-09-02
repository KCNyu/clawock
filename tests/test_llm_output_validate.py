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

import ast
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


# ── call-site coverage (#1273) ───────────────────────────────────────────────
#
# The gate lives at the call sites, not inside `llm.chat()` (see
# output_validate's docstring: chat() is transport and does not know what its
# caller asked the model for). That placement buys enforcement per call site
# and costs the one thing a gate inside chat() would have given for free —
# **coverage**. A fifth call site added next month gets no gate and nothing
# fails; today's three-module string-index check could not have noticed,
# because it only looked at the modules it already knew about.
#
# So the check is inverted here: enumerate every `chat()` call in the tree by
# AST, and assert each one is a call site this table knows is gated. Adding a
# call site now fails this test until it is either gated or listed.
SOURCE_ROOTS = ('src/clawock', 'ops')
GATED_CALL_SITES = {
    ('src/clawock/automation/brief_fallback.py', 'main'): 'validate_sections',
    ('src/clawock/automation/weekly_review.py', 'main'): 'validate_sections',
    ('src/clawock/automation/news_digest.py', 'main'): 'validate_sections',
    ('src/clawock/automation/influencer.py', 'llm_filter'): 'coerce_scored_items',
}
# Anything that puts the model's words somewhere another job will read them.
WRITE_CALLS = {'write_text', 'write_bytes', '_write_artifact', 'dump', 'dumps'}

ROOT = Path(__file__).resolve().parents[1]


def _called_names(node):
    """Every function name called anywhere under `node`, with its line."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            yield func.id, child.lineno
        elif isinstance(func, ast.Attribute):
            yield func.attr, child.lineno


def _functions(tree):
    """Top-level and nested function definitions, outermost first."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _chat_call_sites():
    """`{(relative path, enclosing function): [line, ...]}` for every chat()."""
    sites = {}
    for root in SOURCE_ROOTS:
        for path in sorted((ROOT / root).rglob('*.py')):
            relative = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for function in _functions(tree):
                lines = [line for name, line in _called_names(function)
                         if name == 'chat']
                if lines:
                    sites.setdefault((relative, function.name), []).extend(lines)
    return sites


def test_every_llm_call_site_is_one_the_gate_covers():
    """A new `chat()` caller must not reach an artifact ungated.

    This is the coverage half of #1265: the gate is per call site, so the only
    thing that can keep it complete is a check that counts the call sites.
    """
    found = _chat_call_sites()

    assert set(found) == set(GATED_CALL_SITES), (
        'ungated chat() call site(s): '
        f'{sorted(set(found) - set(GATED_CALL_SITES))}; '
        'gate the output through clawock.automation.output_validate and list '
        'it in GATED_CALL_SITES (or, if it is gone, drop it from the table)'
    )
    # `chat()` is imported from exactly one module, so the AST name cannot be
    # some other project's chat().
    for relative, _ in found:
        source = (ROOT / relative).read_text(encoding='utf-8')
        assert 'from clawock.automation.llm import chat' in source, relative


@pytest.mark.parametrize('site', sorted(GATED_CALL_SITES))
def test_the_call_site_validates_between_the_reply_and_the_write(site):
    """The gate is worthless if it runs after the artifact is on disk (the
    2026-07-16 lesson that put plan validation ahead of the write).

    Line order inside the calling function is the assertion, which is why this
    reads the AST rather than `str.index`: the old string search scanned the
    whole module, so a gate call in an unrelated function would have satisfied
    it, and it could say nothing at all about influencer (whose gate guards a
    return value, not a write).
    """
    relative, function_name = site
    gate = GATED_CALL_SITES[site]
    tree = ast.parse((ROOT / relative).read_text(encoding='utf-8'))
    function = next(f for f in _functions(tree) if f.name == function_name)
    calls = list(_called_names(function))

    chat_line = min(line for name, line in calls if name == 'chat')
    gate_lines = [line for name, line in calls if name == gate]
    assert gate_lines, f'{relative}:{function_name} never calls {gate}()'
    assert min(gate_lines) > chat_line, (
        f'{relative}:{function_name} validates before it has a reply')

    writes = [line for name, line in calls
              if name in WRITE_CALLS and line > chat_line]
    if writes:
        assert min(gate_lines) < min(writes), (
            f'{relative}:{function_name} writes before it validates')


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

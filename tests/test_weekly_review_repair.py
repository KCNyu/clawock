"""The weekly review gets one repair turn before a rejected reply costs the week.

2026-09-13 (run 34770674373): MiniMax answered in 44s with 5,487 tokens,
`stop=end_turn`, and no `下周关注` section. The gate refused it — correctly —
and the job exited. Nothing re-runs a scheduled workflow, so 2026-W37 is simply
missing from memory/weekly/. The chain deadline had ~650s left.
"""
from __future__ import annotations

import pytest

from clawock.automation import weekly_review as weekly
from clawock.automation.output_validate import LLMOutputError, validate_sections

FILLER = '归因与数据说明。' * 150


def _review(*names):
    return '\n\n'.join(f'## {i}. {name}\n{FILLER}' for i, name in enumerate(names, 1))


GOOD = _review(*weekly.WEEKLY_REQUIRED_SECTIONS)
# The 09-13 shape: a real-length review whose headings lack `下周关注` (what the
# model wrote instead was not logged — _log_rejection now records it).
NO_NEXT_WEEK = _review('本周净值', '决策兑现', '风险演变', '下周 Watchlist')


class FakeChat:
    def __init__(self, *replies, clock=None, seconds_per_call=0.0):
        self.replies = list(replies)
        self.calls = []
        self.clock = clock
        self.seconds_per_call = seconds_per_call

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self.clock is not None:
            self.clock.now += self.seconds_per_call
        return self.replies.pop(0)


class FakeClock:
    now = 1000.0

    def __call__(self):
        return self.now


def test_prompt_demands_the_exact_headings_both_gates_look_for(tmp_path):
    from clawock.publish.artifacts import validate_weekly_review

    prompt = weekly.build_user_prompt({'week': '2026-W37'})
    for heading in weekly.WEEKLY_SECTION_HEADINGS:
        assert heading in prompt

    # A reply that follows the prompt literally passes the in-process gate and
    # the workflow's sidecar validator — the two must not disagree.
    body = '\n\n'.join(f'{h}\n{FILLER}' for h in weekly.WEEKLY_SECTION_HEADINGS)
    validate_sections(body, label='weekly review',
                      required=weekly.WEEKLY_REQUIRED_SECTIONS, min_chars=1000)
    path = tmp_path / 'memory' / 'weekly' / '2026-W37.md'
    path.parent.mkdir(parents=True)
    path.write_text('---\nlayout: default\ntitle: 周复盘 · 2026-W37\n---\n\n' + body,
                    encoding='utf-8')
    validate_weekly_review(path)


def test_a_rejected_reply_gets_one_repair_turn_that_sees_its_own_reply(monkeypatch):
    fake = FakeChat(NO_NEXT_WEEK, GOOD)
    monkeypatch.setattr(weekly, 'chat', fake)
    monkeypatch.setenv('CLAWOCK_LLM_DEADLINE_SECONDS', '700')

    assert weekly.generate_review('sys', 'user') == GOOD

    assert len(fake.calls) == 2
    repair = fake.calls[1]['messages']
    assert repair[:2] == fake.calls[0]['messages']
    assert repair[2] == {'role': 'assistant', 'content': NO_NEXT_WEEK}
    assert repair[3]['role'] == 'user' and '下周关注' in repair[3]['content']


def test_a_good_first_reply_costs_exactly_one_call(monkeypatch):
    fake = FakeChat(GOOD)
    monkeypatch.setattr(weekly, 'chat', fake)

    assert weekly.generate_review('sys', 'user') == GOOD
    assert len(fake.calls) == 1


def test_a_repair_that_still_misses_is_refused_not_published(monkeypatch):
    fake = FakeChat(NO_NEXT_WEEK, NO_NEXT_WEEK)
    monkeypatch.setattr(weekly, 'chat', fake)
    monkeypatch.setenv('CLAWOCK_LLM_DEADLINE_SECONDS', '700')

    with pytest.raises(LLMOutputError, match='下周关注'):
        weekly.generate_review('sys', 'user')
    assert len(fake.calls) == 2


def test_repair_spends_only_what_is_left_of_the_one_chain_deadline(monkeypatch):
    # The workflow contract counts this job as ONE chain of 700s inside a 15 min
    # job; a repair that restarted the clock would break that arithmetic.
    clock = FakeClock()
    fake = FakeChat(NO_NEXT_WEEK, GOOD, clock=clock, seconds_per_call=250)
    monkeypatch.setattr(weekly, 'chat', fake)
    monkeypatch.setenv('CLAWOCK_LLM_DEADLINE_SECONDS', '700')

    weekly.generate_review('sys', 'user', clock=clock)

    assert fake.calls[1]['deadline_seconds'] == pytest.approx(450)


def test_no_repair_when_too_little_of_the_deadline_is_left(monkeypatch):
    clock = FakeClock()
    fake = FakeChat(NO_NEXT_WEEK, GOOD, clock=clock, seconds_per_call=650)
    monkeypatch.setattr(weekly, 'chat', fake)
    monkeypatch.setenv('CLAWOCK_LLM_DEADLINE_SECONDS', '700')

    with pytest.raises(LLMOutputError, match='下周关注'):
        weekly.generate_review('sys', 'user', clock=clock)
    assert len(fake.calls) == 1


def test_a_failed_repair_call_still_reports_the_original_rejection(monkeypatch):
    def chat(**kwargs):
        if 'deadline_seconds' in kwargs and len(kwargs['messages']) > 2:
            raise RuntimeError('all LLM providers failed: minimax[timeout]')
        return NO_NEXT_WEEK

    monkeypatch.setattr(weekly, 'chat', chat)
    monkeypatch.setenv('CLAWOCK_LLM_DEADLINE_SECONDS', '700')

    with pytest.raises(LLMOutputError, match='下周关注'):
        weekly.generate_review('sys', 'user')


def test_rejection_logs_the_headings_the_model_actually_wrote(monkeypatch, capsys):
    monkeypatch.setattr(weekly, 'chat', FakeChat(NO_NEXT_WEEK, GOOD))
    monkeypatch.setenv('CLAWOCK_LLM_DEADLINE_SECONDS', '700')

    weekly.generate_review('sys', 'user')

    assert '## 4. 下周 Watchlist' in capsys.readouterr().err

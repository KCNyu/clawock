"""The fallback provider has to be reachable inside the job that calls it.

2026-08-17, release run 31985473431: brief_fallback calls chat() with
timeout=900 and MAX_RETRIES is 3, so MiniMax alone may spend 45 minutes — inside
a job whose `timeout-minutes` is 15. MiniMax hit RemoteDisconnected, began
retrying, and the runner killed the job. opencode-go was never asked. Every
manual dispatch of brief-fallback failed exactly this way, which is why a
backstop that had never once produced output looked untested rather than broken.

A per-attempt timeout cannot express "the chain must finish in time". Only a
budget can, and only if the primary is forbidden from spending all of it.
"""
from __future__ import annotations

import time

import pytest

from clawock.automation import llm


class _Boom(Exception):
    pass


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "x")
    monkeypatch.setenv("OPENCODE_API_KEY", "y")
    monkeypatch.delenv(llm.DEADLINE_ENV, raising=False)


def _record(monkeypatch, primary_delay: float):
    """Primary burns `primary_delay` per attempt and always fails; fallback answers."""
    seen: dict = {"primary_attempts": 0, "fallback_called": False,
                  "primary_timeouts": [], "fallback_timeout": None}

    def fake_primary(label, base_url, api_key, model, messages, max_tokens,
                     temperature, json_response, thinking, timeout=None, deadline=None):
        while True:
            per = llm._attempt_timeout(timeout, deadline, label)
            if per is None:
                break
            seen["primary_attempts"] += 1
            seen["primary_timeouts"].append(per)
            # A real attempt cannot outlive the timeout it was given; requests
            # enforces that. The fake has to model it or it is testing a
            # provider that ignores its own deadline.
            time.sleep(min(primary_delay, per))
            if seen["primary_attempts"] >= llm.MAX_RETRIES:
                break
        raise RuntimeError("primary exhausted")

    # Mirrors _call_provider_openai_compatible AFTER C-F4 dropped its dead
    # `thinking` parameter — keep in sync when the leg signature moves.
    def fake_fallback(label, base_url, api_key, model, messages, max_tokens,
                      temperature, json_response, timeout=None, deadline=None):
        seen["fallback_called"] = True
        seen["fallback_timeout"] = llm._attempt_timeout(timeout, deadline, label)
        return "fallback answered"

    monkeypatch.setattr(llm, "_call_provider", fake_primary)
    monkeypatch.setattr(llm, "_call_provider_openai_compatible", fake_fallback)
    return seen


def test_a_slow_primary_cannot_spend_the_whole_budget(keys, monkeypatch):
    """The regression itself: without a budget the primary's retry ladder
    outlives the job and the fallback is unreachable code."""
    seen = _record(monkeypatch, primary_delay=30.0)  # a primary that would hang forever
    assert llm.chat(user="hi", timeout=900, deadline_seconds=6.0) == "fallback answered"
    assert seen["fallback_called"], "the fallback must still get its turn"
    assert seen["fallback_timeout"] is not None and seen["fallback_timeout"] >= 1


def test_the_primary_is_capped_at_its_declared_share(keys, monkeypatch):
    seen = _record(monkeypatch, primary_delay=0)
    llm.chat(user="hi", timeout=900, deadline_seconds=10.0)
    # Each attempt is clamped to what is left of the primary's slice, never to
    # the caller's optimistic 900s.
    assert seen["primary_timeouts"], "the primary must have been tried"
    assert max(seen["primary_timeouts"]) <= 10.0 * llm.PRIMARY_BUDGET_SHARE + 1


def test_the_budget_can_come_from_the_environment(keys, monkeypatch):
    """The workflow is the thing that knows its own job budget, and it can only
    speak to the script through the environment."""
    monkeypatch.setenv(llm.DEADLINE_ENV, "10")
    seen = _record(monkeypatch, primary_delay=0)
    llm.chat(user="hi", timeout=900)
    assert max(seen["primary_timeouts"]) <= 10.0 * llm.PRIMARY_BUDGET_SHARE + 1


def test_a_junk_budget_is_ignored_loudly_and_never_shortens_a_call(keys, monkeypatch, capsys):
    monkeypatch.setenv(llm.DEADLINE_ENV, "soon")
    seen = _record(monkeypatch, primary_delay=0)
    llm.chat(user="hi", timeout=900)
    assert "not a number" in capsys.readouterr().err
    assert seen["primary_timeouts"] == [900] * llm.MAX_RETRIES


def test_no_budget_keeps_the_historical_behaviour_exactly(keys, monkeypatch):
    seen = _record(monkeypatch, primary_delay=0)
    llm.chat(user="hi", timeout=900)
    assert seen["primary_timeouts"] == [900] * llm.MAX_RETRIES


def test_an_exhausted_budget_yields_instead_of_burning_the_last_seconds():
    assert llm._attempt_timeout(900, time.monotonic() - 5, "x") is None
    assert llm._attempt_timeout(900, None, "x") == 900
    clamped = llm._attempt_timeout(900, time.monotonic() + 30, "x")
    assert 25 <= clamped <= 30


def test_both_provider_legs_reuse_one_session(monkeypatch):
    """C-F2: retry chains used to open a fresh TCP+TLS handshake per attempt;
    both legs must go through the module-level Session pool instead."""
    calls = []

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    class _FakeSession:
        def post(self, url, **kwargs):
            calls.append(url)
            return _FakeResponse()

    monkeypatch.setattr(llm, "_SESSION", _FakeSession())

    out = llm._call_provider(
        label="primary", base_url="https://p.example", api_key="k",
        model="m", messages=[{"role": "user", "content": "hi"}],
        max_tokens=8, timeout=5, temperature=0.5,
        json_response=False, thinking=None)
    assert out == "ok"
    assert calls == ["https://p.example/v1/messages"]


def _fake_session(statuses):
    """Session double handing out one response per post, then repeating last."""
    calls = []

    class R:
        def __init__(self, code):
            self.status_code = code
            self.text = "body"

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}]}

    class S:
        def post(self, url, **kw):
            calls.append((url, kw.get("timeout")))
            code = statuses.pop(0) if len(statuses) > 1 else statuses[0]
            return R(code)

    return S(), calls


def test_rate_limit_429_sleeps_then_succeeds(monkeypatch):
    """429 must sleep its linear wait and retry WITHOUT the generic backoff
    stacking on top; the next attempt gets the full remaining budget."""
    sleeps = []
    session, calls = _fake_session([429, 200])
    monkeypatch.setattr(llm, "_SESSION", session)
    monkeypatch.setattr(llm.time, "sleep", lambda s: sleeps.append(s))

    out = llm._call_provider(
        label="primary", base_url="https://p.example", api_key="k",
        model="m", messages=[{"role": "user", "content": "hi"}],
        max_tokens=8, timeout=30, temperature=0.5,
        json_response=False, thinking=None)

    assert out == "ok"
    assert len(calls) == 2
    assert sleeps == [5]


def test_budget_exhausted_before_any_attempt_names_the_cause(monkeypatch):
    """When the chain budget dies before attempt #1 can run, the error says
    so instead of pretending MAX_RETRIES attempts happened."""
    session, calls = _fake_session([200])
    monkeypatch.setattr(llm, "_SESSION", session)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm, "_attempt_timeout",
                        lambda timeout, deadline, label: None)

    import pytest
    with pytest.raises(RuntimeError, match="budget exhausted"):
        llm._call_provider(
            label="primary", base_url="https://p.example", api_key="k",
            model="m", messages=[{"role": "user", "content": "hi"}],
            max_tokens=8, timeout=30, temperature=0.5,
            json_response=False, thinking=None)
    assert calls == []   # no request was ever fired


def test_stats_out_records_leg_outcomes_and_attempts(keys, monkeypatch):
    """C-F3a: the job log used to show only per-attempt token lines — nothing
    about which leg won or what each cost. stats_out now carries per-leg
    {provider, ok, attempts, wall_s} for whoever prints or ships it."""
    seen = {"primary_attempts": 0}

    def fake_primary(label, base_url, api_key, model, messages, max_tokens,
                     temperature, json_response, thinking, timeout=None,
                     deadline=None, attempts_sink=None):
        for attempt in range(1, llm.MAX_RETRIES + 1):
            per = llm._attempt_timeout(timeout, deadline, label)
            if per is None:
                break
            seen["primary_attempts"] += 1
            time.sleep(0.01)
            if attempts_sink is not None:
                attempts_sink.append(attempt)   # model the real leg's reporting
        raise RuntimeError("primary exhausted")

    def fake_fallback(label, base_url, api_key, model, messages, max_tokens,
                      temperature, json_response, timeout=None, deadline=None,
                      attempts_sink=None):
        if attempts_sink is not None:
            attempts_sink.append(1)
        return "fallback answered"

    monkeypatch.setattr(llm, "_call_provider", fake_primary)
    monkeypatch.setattr(llm, "_call_provider_openai_compatible", fake_fallback)

    stats = {}
    out = llm.chat(user="hi", timeout=30, deadline_seconds=20.0,
                   stats_out=stats)

    assert out == "fallback answered"
    legs = {leg["provider"]: leg for leg in stats["legs"]}
    assert legs["minimax"]["ok"] is False and legs["minimax"]["attempts"] == 3
    assert legs["opencode"]["ok"] is True and legs["opencode"]["attempts"] == 1
    assert legs["minimax"]["wall_s"] >= 0 and "error" in legs["minimax"]


def test_stats_out_over_the_real_provider_signature(keys, monkeypatch):
    """J-P0-1 regression: the stats plumbing once called the real provider
    functions with attempts_sink while neither accepted it — TypeError before
    any request, killing exactly the fallback path that runs when things are
    already broken. The earlier test's fake had quietly grown the parameter;
    this one fakes only the wire."""
    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "ok"},
                                 "finish_reason": "stop"}], "usage": {}}

    class S:
        def post(self, url, **kw):
            assert "attempts_sink" not in kw, "sink must not reach wire kwargs"
            return R()

    monkeypatch.setattr(llm, "_SESSION", S())

    stats = {}
    llm.chat(user="hi", timeout=10, temperature=0.5, fallback=False,
             stats_out=stats)

    leg = stats["legs"][0]
    assert leg == {"provider": "minimax", "ok": True, "attempts": 1,
                   "wall_s": leg["wall_s"]}

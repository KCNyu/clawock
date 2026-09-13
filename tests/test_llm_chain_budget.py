"""The LLM call has to finish inside the job that makes it.

2026-08-17, release run 31985473431: brief_fallback calls chat() with
timeout=900 and MAX_RETRIES is 3, so MiniMax alone may spend 45 minutes — inside
a job whose `timeout-minutes` is 15. MiniMax hit RemoteDisconnected, began
retrying, and the runner killed the job before anything was written.

A per-attempt timeout cannot express "the call must finish in time". Only a
budget can. Since 2026-09-13 there is one provider (the OpenCode fallback leg
was removed — its wallet had been empty for weeks), so the whole budget is the
provider's.
"""
from __future__ import annotations

import time

import pytest

from clawock.automation import llm


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "x")
    monkeypatch.delenv(llm.DEADLINE_ENV, raising=False)


def _record(monkeypatch, delay: float):
    """The provider burns `delay` per attempt and always fails."""
    seen: dict = {"attempts": 0, "timeouts": []}

    def fake_provider(label, base_url, api_key, model, messages, max_tokens,
                      temperature, json_response, thinking, timeout=None, deadline=None):
        while True:
            per = llm._attempt_timeout(timeout, deadline, label)
            if per is None:
                break
            seen["attempts"] += 1
            seen["timeouts"].append(per)
            # A real attempt cannot outlive the timeout it was given; requests
            # enforces that, so the fake models it too.
            time.sleep(min(delay, per))
            if seen["attempts"] >= llm.MAX_RETRIES:
                break
        raise RuntimeError("provider exhausted")

    monkeypatch.setattr(llm, "_call_provider", fake_provider)
    return seen


def test_a_slow_provider_gives_up_inside_the_budget(keys, monkeypatch):
    """The regression itself: without a budget the retry ladder outlives the job."""
    _record(monkeypatch, delay=30.0)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="all LLM providers failed"):
        llm.chat(user="hi", timeout=900, deadline_seconds=4.0)
    assert time.monotonic() - started < 4.0 + 3, "the call outlived its own budget"


def test_each_attempt_is_clamped_to_the_whole_budget(keys, monkeypatch):
    seen = _record(monkeypatch, delay=0)
    with pytest.raises(RuntimeError):
        llm.chat(user="hi", timeout=900, deadline_seconds=10.0)
    # Clamped to what is left of the budget, never to the caller's optimistic 900s
    # — and no longer to a 60% slice reserved for a fallback that does not exist.
    assert seen["timeouts"], "the provider must have been tried"
    assert max(seen["timeouts"]) <= 10.0 + 1
    assert max(seen["timeouts"]) > 10.0 * 0.6, "a share reserved for a removed leg is back"


def test_the_budget_can_come_from_the_environment(keys, monkeypatch):
    """The workflow is the thing that knows its own job budget, and it can only
    speak to the script through the environment."""
    monkeypatch.setenv(llm.DEADLINE_ENV, "10")
    seen = _record(monkeypatch, delay=0)
    with pytest.raises(RuntimeError):
        llm.chat(user="hi", timeout=900)
    assert max(seen["timeouts"]) <= 10.0 + 1


def test_a_junk_budget_is_ignored_loudly_and_never_shortens_a_call(keys, monkeypatch, capsys):
    monkeypatch.setenv(llm.DEADLINE_ENV, "soon")
    seen = _record(monkeypatch, delay=0)
    with pytest.raises(RuntimeError):
        llm.chat(user="hi", timeout=900)
    assert "not a number" in capsys.readouterr().err
    assert seen["timeouts"] == [900] * llm.MAX_RETRIES


def test_no_budget_keeps_the_historical_behaviour_exactly(keys, monkeypatch):
    seen = _record(monkeypatch, delay=0)
    with pytest.raises(RuntimeError):
        llm.chat(user="hi", timeout=900)
    assert seen["timeouts"] == [900] * llm.MAX_RETRIES


def test_a_missing_key_fails_with_the_prefix_callers_match(monkeypatch):
    """influencer.llm_filter stops retrying on this exact prefix."""
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match=r"^all LLM providers failed: minimax\[no MINIMAX_API_KEY\]"):
        llm.chat(user="hi")


def test_no_paid_fallback_leg_remains():
    """kcn 2026-09-13: no OpenCode / DeepSeek pay-as-you-go leg in this client."""
    source = open(llm.__file__, encoding="utf-8").read()
    code = source.split('"""', 2)[2]          # past the module docstring's history
    for dead in ("opencode", "OPENCODE", "deepseek", "_call_provider_openai_compatible",
                 "PRIMARY_BUDGET_SHARE"):
        assert dead not in code, f"{dead!r} is back in llm.py"


def test_an_exhausted_budget_yields_instead_of_burning_the_last_seconds():
    assert llm._attempt_timeout(900, time.monotonic() - 5, "x") is None
    assert llm._attempt_timeout(900, None, "x") == 900
    clamped = llm._attempt_timeout(900, time.monotonic() + 30, "x")
    assert 25 <= clamped <= 30


def test_the_provider_reuses_one_session(monkeypatch):
    """C-F2: retry chains used to open a fresh TCP+TLS handshake per attempt."""
    calls = []

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 1, "output_tokens": 1}}

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
    """When the budget dies before attempt #1 can run, the error says so
    instead of pretending MAX_RETRIES attempts happened."""
    session, calls = _fake_session([200])
    monkeypatch.setattr(llm, "_SESSION", session)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm, "_attempt_timeout",
                        lambda timeout, deadline, label: None)

    with pytest.raises(RuntimeError, match="budget exhausted"):
        llm._call_provider(
            label="primary", base_url="https://p.example", api_key="k",
            model="m", messages=[{"role": "user", "content": "hi"}],
            max_tokens=8, timeout=30, temperature=0.5,
            json_response=False, thinking=None)
    assert calls == []   # no request was ever fired


def test_stats_out_records_a_failed_call(keys, monkeypatch):
    """C-F3a: stats_out carries {provider, ok, attempts, wall_s, error} for
    whoever prints or ships it — including when the call fails."""
    def fake_provider(label, base_url, api_key, model, messages, max_tokens,
                      temperature, json_response, thinking, timeout=None,
                      deadline=None, attempts_sink=None):
        if attempts_sink is not None:
            attempts_sink.append(llm.MAX_RETRIES)
        raise RuntimeError("provider exhausted")

    monkeypatch.setattr(llm, "_call_provider", fake_provider)
    stats = {}
    with pytest.raises(RuntimeError):
        llm.chat(user="hi", timeout=30, deadline_seconds=20.0, stats_out=stats)

    (leg,) = stats["legs"]
    assert leg["provider"] == "minimax" and leg["ok"] is False
    assert leg["attempts"] == llm.MAX_RETRIES and "error" in leg


def test_stats_out_over_the_real_provider_signature(keys, monkeypatch):
    """J-P0-1 regression: the stats plumbing once called the real provider
    function with attempts_sink while it did not accept it — TypeError before
    any request. This fakes only the wire."""
    class R:
        status_code = 200

        def json(self):
            return {"content": [{"type": "text", "text": "ok"}], "usage": {}}

    class S:
        def post(self, url, **kw):
            assert "attempts_sink" not in kw, "sink must not reach wire kwargs"
            return R()

    monkeypatch.setattr(llm, "_SESSION", S())

    stats = {}
    assert llm.chat(user="hi", timeout=10, temperature=0.5, stats_out=stats) == "ok"

    leg = stats["legs"][0]
    assert leg == {"provider": "minimax", "ok": True, "attempts": 1,
                   "wall_s": leg["wall_s"]}

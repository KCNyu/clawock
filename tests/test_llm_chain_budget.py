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

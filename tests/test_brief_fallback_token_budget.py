"""The brief's output budget must fit the brief that is actually published.

2026-08-11: the call site asked for max_tokens=32000 — mimo-v2.5-pro's cap, left
behind when MiniMax M3 became primary. Thinking takes its reserve out of the same
allowance, so only ~16K remained for prose against a ~33KB brief. The run ended
`stop=max_tokens` with the trailing plan.json block never emitted.
"""
import json

from clawock.automation import brief_fallback, llm


# The largest published pre-open.md observed to date, in bytes. Mostly CJK, which
# is ~1 token per 3-byte character, so this is a deliberately generous token proxy.
OBSERVED_BRIEF_BYTES = 33005
THINKING_RESERVE = 16000  # _call_provider's cap on budget_tokens


def _thinking_reserve(max_tokens):
    return max(1024, min(max_tokens - 1024, THINKING_RESERVE))


def test_prose_budget_survives_the_thinking_reserve_at_the_observed_brief_size():
    prose_budget = brief_fallback.BRIEF_MAX_TOKENS - _thinking_reserve(
        brief_fallback.BRIEF_MAX_TOKENS)

    assert prose_budget > OBSERVED_BRIEF_BYTES, (
        "output budget minus the thinking reserve must exceed the real brief size; "
        "this is the exact arithmetic that failed on 2026-08-11"
    )


def test_the_old_32000_budget_would_still_fail_this_check():
    """Pins the direction: the guard must reject the value that broke production."""
    prose_budget = 32000 - _thinking_reserve(32000)

    assert prose_budget < OBSERVED_BRIEF_BYTES


def test_budget_stays_within_minimax_capacity():
    assert brief_fallback.BRIEF_MAX_TOKENS <= llm.MINIMAX_MAX_TOKENS


def _capture_provider_calls(monkeypatch):
    seen = []

    def fake_call(label, base_url, api_key, model, messages, max_tokens, *args, **kw):
        seen.append({"label": label, "max_tokens": max_tokens})
        raise RuntimeError("forced fallback")

    monkeypatch.setattr(llm, "_call_provider", fake_call)
    monkeypatch.setattr(llm, "_call_provider_openai_compatible", fake_call)
    return seen


def test_each_provider_is_clamped_to_its_own_cap(monkeypatch):
    """Raising the caller's budget must not hand a provider a value it cannot serve."""
    seen = _capture_provider_calls(monkeypatch)
    monkeypatch.setenv("MINIMAX_API_KEY", "mm")
    monkeypatch.setenv("OPENCODE_API_KEY", "oc")

    try:
        llm.chat(user="hi", max_tokens=brief_fallback.BRIEF_MAX_TOKENS)
    except RuntimeError:
        pass

    by_label = {c["label"]: c["max_tokens"] for c in seen}
    assert by_label["minimax"] == brief_fallback.BRIEF_MAX_TOKENS
    assert by_label["opencode"] == llm.OPENCODE_MAX_TOKENS
    assert llm.OPENCODE_MAX_TOKENS < brief_fallback.BRIEF_MAX_TOKENS


def test_brief_fallback_asks_for_the_module_budget_not_a_literal(monkeypatch):
    """The regression was a hardcoded number at the call site; keep it out."""
    source = (brief_fallback.__file__)
    with open(source) as fh:
        body = fh.read()

    call = body.split("out = chat(", 1)[1].split(")", 1)[0]
    assert "BRIEF_MAX_TOKENS" in call
    assert "32000" not in call

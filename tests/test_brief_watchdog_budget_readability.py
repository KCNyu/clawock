"""`retry_budget_note`'s silence rule, pinned (#1214).

#1214 read the bare `except Exception` here as a fifth silent failure in the
observability chain and proposed making an unreadable budget say so. It is not
one, and the change was not made: the module docstring records why, out of
incident history rather than principle — "it stays silent when the budget is
healthy or unreadable: a missing brief has other causes, and pointing at this
one when it is not the cause is how the last three diagnoses went wrong."

What #1214 did find is that the rule had no test. Three call paths returned the
empty string for three different reasons and nothing pinned any of them, so the
rule was one refactor away from being changed by accident — which is how a
deliberate silence turns into an undocumented one.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from clawock.harness import brief_watchdog  # noqa: E402


class _Budget:
    def __init__(self, exhausted):
        self.exhausted = exhausted
        self.raisable, self.cap_needed = True, 7

    def describe(self):
        return "consecutiveErrors=6 / maxAttempts=5"


def test_a_healthy_budget_says_nothing(monkeypatch):
    monkeypatch.setattr(brief_watchdog, 'brief_cron_job_state', lambda: {'id': 'x'})
    monkeypatch.setattr(brief_watchdog, 'cron_retry_budget',
                        lambda job: _Budget(False))
    assert brief_watchdog.retry_budget_note() == ''


def test_an_unknown_budget_says_nothing(monkeypatch):
    """`exhausted is None` — the counter or the cap could not be read.

    Distinct from healthy, and deliberately reported the same way: unknown is
    not evidence, and this line only exists to name a proven cause.
    """
    monkeypatch.setattr(brief_watchdog, 'brief_cron_job_state', lambda: {'id': 'x'})
    monkeypatch.setattr(brief_watchdog, 'cron_retry_budget',
                        lambda job: _Budget(None))
    assert brief_watchdog.retry_budget_note() == ''


def test_no_such_job_says_nothing(monkeypatch):
    monkeypatch.setattr(brief_watchdog, 'brief_cron_job_state', lambda: None)
    assert brief_watchdog.retry_budget_note() == ''


def test_a_gateway_that_will_not_answer_says_nothing_and_does_not_raise(
        monkeypatch):
    """The alert is the last notification that reaches a human that morning.

    Reading the budget is a `cron list` round trip through the gateway — the
    component a bad morning may have taken down. Nothing here may cost the
    alert, so this stays fail-open, and the silence is the documented rule
    rather than an oversight.
    """
    def _down():
        raise TimeoutError('gateway did not answer')

    monkeypatch.setattr(brief_watchdog, 'brief_cron_job_state', _down)
    assert brief_watchdog.retry_budget_note() == ''


def test_an_exhausted_budget_is_the_one_case_that_speaks(monkeypatch):
    """Otherwise the rule above would be indistinguishable from a dead function."""
    budget = _Budget(True)
    monkeypatch.setattr(brief_watchdog, 'brief_cron_job_state', lambda: {'id': 'x'})
    monkeypatch.setattr(brief_watchdog, 'cron_retry_budget', lambda job: budget)

    note = brief_watchdog.retry_budget_note()
    assert note and 'maxAttempts' in note and '7' in note, note

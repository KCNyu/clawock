"""cron_runs.py must report what was delivered, not what the run record guessed.

2026-08-17: openclaw records `FallbackSummaryError` when its own *run-summary*
LLM call fails — which happens after postflight has already written and
delivered the report. `cron_runs.py` printed those runs as 🔴, identical to a
run that produced nothing, while the receipt on disk said
`sent_ok: true, delivery_state: delivered`. The report was in kcn's WeChat and
the tool said it had failed twice.
"""
import importlib.util
import json
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'ops' / 'host' / 'cron_runs.py'


def _load(monkeypatch, workspace):
    """Import cron_runs.py bound to a throwaway workspace.

    `monkeypatch` (not `os.environ[...] = ...`) because CLAWOCK_WORKSPACE is
    read by the whole tree: leaking it out of this module points every later
    test in the same pytest process at a tmp dir. That is not hypothetical —
    the first version of this file did exactly that and turned 19 dashboard /
    sidecar tests red on CI while passing in isolation.
    """
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(workspace))
    spec = importlib.util.spec_from_file_location('cron_runs_under_test', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def desk(tmp_path):
    (tmp_path / 'memory' / '.tmp').mkdir(parents=True)
    return tmp_path


RUN_TS = 1786930333675 + 30_000       # run recorded 30s after the receipt
RUN_DURATION = 5 * 60 * 1000          # 5-minute run, so the receipt is inside it


def _receipt(desk, name, **fields):
    doc = {'ts': 1786930333675, 'sent_ok': True, 'delivery_state': 'delivered'}
    doc.update(fields)
    (desk / 'memory' / '.tmp' / name).write_text(json.dumps(doc))


def test_delivered_report_with_failed_summary_is_not_a_red(monkeypatch, desk):
    mod = _load(monkeypatch, desk)
    _receipt(desk, 'report-sent-hk-open-2026-08-17.json')
    entry = {'status': 'error', 'error': 'FallbackSummaryError: All models failed (3): ...'}

    receipt = mod.delivered_receipt('港股开盘报告', RUN_TS, RUN_DURATION)
    assert receipt is not None, 'the receipt for this job/date must be found'
    assert mod.status_glyph('error', receipt) == '⚠️', 'a delivered report is not a red'
    assert '已投递' in mod.summarize(entry, receipt=receipt)


def test_a_genuinely_undelivered_run_stays_red(monkeypatch, desk):
    mod = _load(monkeypatch, desk)
    # No receipt written: this is the real failure shape (盘前深度简报, 2026-08-17).
    entry = {'status': 'error', 'error': 'FallbackSummaryError: All models failed (3): ...'}

    receipt = mod.delivered_receipt('盘前深度简报', RUN_TS, RUN_DURATION)
    assert receipt is None
    assert mod.status_glyph('error', receipt) == '🔴', 'no receipt means no delivery — stay red'
    assert mod.summarize(entry, receipt=receipt).startswith('ERR:')


def test_a_receipt_that_did_not_send_is_not_treated_as_delivered(monkeypatch, desk):
    mod = _load(monkeypatch, desk)
    _receipt(desk, 'report-sent-hk-open-2026-08-17.json', sent_ok=False, delivery_state='failed')

    assert mod.delivered_receipt('港股开盘报告', RUN_TS, RUN_DURATION) is None
    assert mod.status_glyph('error', None) == '🔴'


def test_receipts_are_read_from_the_live_workspace_not_the_checkout(monkeypatch, desk):
    """Run out of an interactive worktree, a location-derived path finds nothing."""
    mod = _load(monkeypatch, desk)
    assert mod.WS == desk, 'CLAWOCK_WORKSPACE decides where receipts are read from'
    assert mod.TMP == desk / 'memory' / '.tmp'


def test_every_delivering_job_has_a_receipt_pattern(monkeypatch, desk):
    """A job that delivers but is missing from the map silently stays red."""
    mod = _load(monkeypatch, desk)
    for job in ('港股开盘报告', '港股午盘报告', '港股午后快报', '港股收盘报告',
                '美股开盘报告', '美股收盘报告', '盘前深度简报'):
        assert job in mod.RECEIPT_BY_JOB, f'{job} delivers — it needs a receipt pattern'


def test_a_receipt_from_a_later_run_does_not_vindicate_an_earlier_failure(desk, monkeypatch):
    """Matching on job+date alone turns the fix into its own mirror image.

    On 2026-08-17 the brief failed at 08:03 / 08:33 / 09:11, produced nothing at
    10:15, and only delivered at 10:39. Keyed on the date, that single receipt
    made all four earlier runs display 已投递 — a false green traded for the
    false red this module exists to remove. The receipt has to belong to the run
    that is being rendered.
    """
    mod = _load(monkeypatch, desk)
    delivered_at = 1786930333675
    _receipt(desk, 'brief-sent-2026-08-17.json', ts=delivered_at)

    # The run that actually delivered: the receipt falls inside its window.
    assert mod.delivered_receipt('盘前深度简报', delivered_at + 20_000, 8 * 60 * 1000) is not None

    # Runs that ended hours before it. Same job, same date, no delivery.
    for hours_before in (1, 2, 3):
        earlier_end = delivered_at - hours_before * 3600 * 1000
        assert mod.delivered_receipt('盘前深度简报', earlier_end, 6 * 60 * 1000) is None, (
            f'a run ending {hours_before}h before the delivery did not deliver'
        )

    # And a run that started after it (a retry the idempotency gate blocked)
    # also did not deliver — it only regenerated the prose.
    later_end = delivered_at + 20 * 60 * 1000
    assert mod.delivered_receipt('盘前深度简报', later_end, 3 * 60 * 1000) is None


def test_a_run_without_a_duration_still_matches_its_own_receipt(desk, monkeypatch):
    """durationMs is not always present; a receipt at the run timestamp must
    still be attributed rather than silently dropped."""
    mod = _load(monkeypatch, desk)
    _receipt(desk, 'report-sent-hk-open-2026-08-17.json', ts=1786930333675)
    assert mod.delivered_receipt('港股开盘报告', 1786930333675, None) is not None

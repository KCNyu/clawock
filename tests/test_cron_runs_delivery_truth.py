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


def _receipt(desk, name, **fields):
    doc = {'ts': 1786930333675, 'sent_ok': True, 'delivery_state': 'delivered'}
    doc.update(fields)
    (desk / 'memory' / '.tmp' / name).write_text(json.dumps(doc))


def test_delivered_report_with_failed_summary_is_not_a_red(monkeypatch, desk):
    mod = _load(monkeypatch, desk)
    _receipt(desk, 'report-sent-hk-open-2026-08-17.json')
    entry = {'status': 'error', 'error': 'FallbackSummaryError: All models failed (3): ...'}

    receipt = mod.delivered_receipt('港股开盘报告', 1786930333675)
    assert receipt is not None, 'the receipt for this job/date must be found'
    assert mod.status_glyph('error', receipt) == '⚠️', 'a delivered report is not a red'
    assert '已投递' in mod.summarize(entry, receipt=receipt)


def test_a_genuinely_undelivered_run_stays_red(monkeypatch, desk):
    mod = _load(monkeypatch, desk)
    # No receipt written: this is the real failure shape (盘前深度简报, 2026-08-17).
    entry = {'status': 'error', 'error': 'FallbackSummaryError: All models failed (3): ...'}

    receipt = mod.delivered_receipt('盘前深度简报', 1786930333675)
    assert receipt is None
    assert mod.status_glyph('error', receipt) == '🔴', 'no receipt means no delivery — stay red'
    assert mod.summarize(entry, receipt=receipt).startswith('ERR:')


def test_a_receipt_that_did_not_send_is_not_treated_as_delivered(monkeypatch, desk):
    mod = _load(monkeypatch, desk)
    _receipt(desk, 'report-sent-hk-open-2026-08-17.json', sent_ok=False, delivery_state='failed')

    assert mod.delivered_receipt('港股开盘报告', 1786930333675) is None
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

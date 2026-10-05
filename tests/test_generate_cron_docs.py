"""Tests for resilient cron schedule documentation rendering."""
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops' / 'host'))

from generate_cron_docs import render, watchdog_text  # noqa: E402


def test_watchdog_text_flags_non_list_extras_without_crashing():
    text = watchdog_text({'extra_watchdogs': {'schedule': {}}})

    assert text == '⚠ malformed extra_watchdogs: expected a list'


def test_watchdog_text_flags_extra_entry_missing_schedule():
    text = watchdog_text({'extra_watchdogs': [{'purpose': 'broken'}]})

    assert text == '⚠ malformed extra watchdog 1: missing schedule'


def test_watchdog_text_preserves_declared_empty_primary():
    text = watchdog_text({'watchdog': {}})

    assert text == '⚠ malformed primary watchdog: missing schedule'


def test_real_brief_primary_and_0905_extra_watchdogs_render():
    contract = json.loads((ROOT / 'config' / 'cron-schedules.json').read_text())
    brief = next(job for job in contract['jobs'] if job['name'] == '盘前深度简报')

    text = watchdog_text(brief)

    assert '`36 8 * * 1-5` · Asia/Hong_Kong' in text
    assert '`5 9 * * 1-5` · Asia/Hong_Kong' in text
    assert 'miss-detector: brief never written' in text


def test_the_job_count_invariant_is_counted_from_the_contract():
    """#2614: it was a literal — 11 enabled while OpenClaw's scheduler ran 10 —
    and disabling a job left the generated page byte-identical."""
    from clawock.scheduling import runtime_enabled

    contract = json.loads((ROOT / 'config' / 'cron-schedules.json').read_text())
    enabled = sum(runtime_enabled(job) for job in contract['jobs'])
    page = render(contract)
    assert f"exactly {enabled} enabled in OpenClaw's own scheduler" in page

    report = next(job for job in contract['jobs'] if job['name'] == '港股开盘报告')
    report['enabled'] = False
    changed = render(contract)
    assert f"exactly {enabled - 1} enabled in OpenClaw's own scheduler" in changed
    assert '<br>disabled |' in changed and '<br>disabled |' not in page

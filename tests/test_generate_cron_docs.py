"""Tests for resilient cron schedule documentation rendering."""
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops' / 'host'))

from generate_cron_docs import watchdog_text  # noqa: E402


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

    assert '`33 8 * * 1-5` · Asia/Hong_Kong' in text
    assert '`5 9 * * 1-5` · Asia/Hong_Kong' in text
    assert 'miss-detector: brief never written' in text

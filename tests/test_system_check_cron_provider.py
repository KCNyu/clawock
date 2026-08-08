"""The host health gate must be runnable without the KCNyu distribution.

The installed watchdogs need that repository-only adapter, but `system_check`
is an operator tool backed by the core OpenClaw provider. Importing the old
`scripts/harness/_watchdog_common` alias made the live system Python report cron
state unreadable even though the provider and runtime were healthy.
"""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_system_check_reads_cron_state_only_through_the_core_provider():
    source = (ROOT / "ops" / "system_check.py").read_text()

    assert "read_jobs as openclaw_read_jobs" in source
    assert "openclaw_read_jobs()" in source
    assert "_watchdog_common" not in source
    assert "scripts' / 'harness" not in source
    assert "len(job.get('extra_watchdogs') or [])" in source

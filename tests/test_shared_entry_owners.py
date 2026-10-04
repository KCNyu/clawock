from datetime import datetime, timezone
import pytest
from clawock import scheduling
from clawock.harness import intraday_watchdog, report_watchdog, _watchdog_common
from workflow_contract_helpers import logical_commit_commands


def test_fallback_formatter_has_one_owner():
    assert intraday_watchdog.deterministic_fallback is report_watchdog.deterministic_fallback is _watchdog_common.deterministic_fallback


@pytest.mark.parametrize('value', ['2026-01-01T00:00:00', '2026-01-01T00:00:00Z', '2026-01-01T08:00:00+08:00'])
def test_audit_timestamp_supports_naive_and_aware_values(value):
    assert scheduling.parse_at(value) == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_multiline_publication_command_keeps_all_paths():
    raw = 'bash ops/publish/gha_commit_push.sh \\\n assets/data/a.json \\\n assets/data/b.json\n'
    assert logical_commit_commands(raw) == ['bash ops/publish/gha_commit_push.sh assets/data/a.json assets/data/b.json']

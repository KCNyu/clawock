"""The input fingerprint gate for `dashboard-build --skip-if-unchanged` (#846)."""
from pathlib import Path

from clawock.publish.dashboard import (
    FINGERPRINT_CACHE,
    _read_fingerprint_cache,
    _write_fingerprint_cache,
    dashboard_input_fingerprint,
)


def _desk(tmp_path: Path) -> Path:
    (tmp_path / 'memory' / 'bars').mkdir(parents=True)
    (tmp_path / 'memory' / 'snapshots').mkdir()
    (tmp_path / 'memory' / 'weekly').mkdir()
    (tmp_path / 'memory' / '.tmp').mkdir()
    (tmp_path / 'portfolio.json').write_text('{}')
    (tmp_path / 'memory' / 'decisions.jsonl').write_text('')
    (tmp_path / 'memory' / 'fx-rates.jsonl').write_text('')
    (tmp_path / 'assets' / 'data').mkdir(parents=True)
    (tmp_path / 'assets' / 'data' / 'risk.json').write_text('{}')
    return tmp_path


def test_fingerprint_is_stable_for_an_unchanged_desk(tmp_path):
    ws = _desk(tmp_path)
    assert dashboard_input_fingerprint(ws) == dashboard_input_fingerprint(ws)


def test_fingerprint_moves_on_every_input_class(tmp_path):
    ws = _desk(tmp_path)
    before = dashboard_input_fingerprint(ws)

    (ws / 'portfolio.json').write_text('{"x": 1}')
    assert dashboard_input_fingerprint(ws) != before, 'portfolio.json must move it'

    before = dashboard_input_fingerprint(ws)
    (ws / 'memory' / 'bars' / '00700.json').write_text('{"bars": {}}')
    assert dashboard_input_fingerprint(ws) != before, 'a new bar file must move it'

    before = dashboard_input_fingerprint(ws)
    (ws / 'memory' / '2026-08-01-plan.json').write_text('{}')
    assert dashboard_input_fingerprint(ws) != before, 'a new plan file must move it'

    before = dashboard_input_fingerprint(ws)
    (ws / 'memory' / '.tmp' / 'sector_scan.json').write_text('{}')
    assert dashboard_input_fingerprint(ws) != before, 'a .tmp sidecar must move it'


def test_fingerprint_moves_when_a_tracked_file_goes_missing(tmp_path):
    ws = _desk(tmp_path)
    before = dashboard_input_fingerprint(ws)
    (ws / 'memory' / 'fx-rates.jsonl').unlink()
    assert dashboard_input_fingerprint(ws) != before, 'a deleted input must move it'


def test_fingerprint_cache_round_trips(tmp_path):
    ws = _desk(tmp_path)
    assert _read_fingerprint_cache(ws) is None, 'no cache file yet'
    _write_fingerprint_cache(ws, 'abc123')
    assert _read_fingerprint_cache(ws) == 'abc123'
    assert (ws / FINGERPRINT_CACHE).exists()
    # A torn cache must read as absent, never raise.
    (ws / FINGERPRINT_CACHE).write_text('not json')
    assert _read_fingerprint_cache(ws) is None


def test_snapshot_filter_and_the_1040_roller_cannot_drift_apart():
    """#1040: 滚动窗口把冷快照挪进 _archive/ 的前提是「dashboard 本来就不读它」。

    这个前提靠两条定义完全一致来保证——所以直接断言同一个对象，而不是两份
    各自维护、迟早漂移的正则字符串。
    """
    from clawock import history_store
    from clawock.publish.dashboard import SNAPSHOT_FNAME_RE

    assert SNAPSHOT_FNAME_RE is history_store.DATED_FILE_RE

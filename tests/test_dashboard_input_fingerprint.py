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


# ── the drift that #846 shipped and #1217 found ─────────────────────────────

def _data_plane_reads(monkeypatch) -> set[str]:
    """Filenames under assets/data/ that a real projection actually touches.

    Recorded rather than listed. A grep for `_embed(...)` would miss the reads
    that spell the path out inline — `lev_regime.json`, `macro.json` and the
    workflow ledger are all read that way — and those were three of the files
    the fingerprint was missing, so a source-scanning gate would have passed
    while the bug was live.
    """
    import os
    import pathlib

    from clawock.publish import dashboard

    seen: set[str] = set()
    # String comparison, not `Path.resolve()`: resolve() calls stat(), which is
    # one of the methods patched below, and the recursion is immediate.
    root = os.path.abspath(dashboard.WS_ROOT / 'assets' / 'data')

    def _note(path):
        text = os.path.abspath(str(path))
        if os.path.dirname(text) == root:
            seen.add(os.path.basename(text))

    for name in ('read_text', 'read_bytes', 'open', 'exists', 'stat'):
        original = getattr(pathlib.Path, name)

        def wrapper(self, *args, _original=original, **kwargs):
            _note(self)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(pathlib.Path, name, wrapper)

    dashboard.build_projection()
    return seen


def test_fingerprint_covers_every_data_plane_file_the_build_reads(monkeypatch):
    """The gate that keeps #1217 from happening again.

    `--skip-if-unchanged` is only safe while the fingerprint sees everything the
    build reads. It did not: of the data plane the projection embeds, exactly
    `risk.json` was fingerprinted, so a scheduled scan pushing a new
    `sentiment.json` left the fingerprint byte-identical and the publisher
    skipped the rebuild. This runs a real projection, records what it read, and
    fails on any input the fingerprint cannot see.
    """
    from clawock.publish import dashboard

    covered = {
        name.split('/')[-1] for name in dashboard.FINGERPRINT_FILES
        if name.startswith('assets/data/')
    }
    # The build's own four outputs are read as the previous generation, never as
    # an input; fingerprinting them would make every build invalidate the next
    # tick's gate.
    outputs = {'dashboard.json', 'overview.json', 'decision_audit.json',
               'shadow_portfolio.json'}

    read = _data_plane_reads(monkeypatch)
    assert read, 'the instrumented projection recorded no data-plane read at all'
    # .jsonl too: the gate was `.json` only, so `guardrail_history.jsonl` could
    # have been wired into the projection (#1252) without this noticing.
    uncovered = {name for name in read
                 if name.endswith(('.json', '.jsonl'))} - covered - outputs
    assert not uncovered, (
        f'the projection reads {sorted(uncovered)} and the fingerprint cannot '
        f'see them: --skip-if-unchanged would keep publishing a stale embed of '
        f'each until an unrelated input happened to move')


def test_a_scheduled_scan_alone_moves_the_fingerprint(tmp_path):
    """The concrete case that was silent: overnight, a scan is the only writer.

    Every other input class already had a test here. This one — the data plane —
    did not, which is why the omission survived from #846 to #1217.
    """
    ws = _desk(tmp_path)
    data = ws / 'assets' / 'data'
    for name in ('sentiment.json', 'macro.json', 'lev_regime.json',
                 'workflow-outcomes.json'):
        (data / name).write_text('{"v": 1}')

    before = dashboard_input_fingerprint(ws)
    for name in ('sentiment.json', 'macro.json', 'lev_regime.json',
                 'workflow-outcomes.json'):
        (data / name).write_text('{"v": 2}')
    assert dashboard_input_fingerprint(ws) != before, (
        'a scheduled scan rewriting the embedded data plane must move it')


def test_an_unchanged_portfolio_does_not_move_the_snapshot(tmp_path, monkeypatch):
    """The write that would have made the harness gate unfireable (#1217).

    `refresh_today_snapshot` runs immediately before the fingerprint is taken
    and used to copy `portfolio.json` over today's snapshot unconditionally, so
    every weekday postflight moved `memory/snapshots/` whether or not the desk
    had. Nothing reads a snapshot's mtime, so the write bought nothing and cost
    the gate its only chance to fire.
    """
    from datetime import datetime

    from clawock.harness import _harness_common as harness

    ws = _desk(tmp_path)
    (ws / 'portfolio.json').write_text('{"holdings": []}')

    class _Weekday(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 8, 31, 12, 0)   # a Monday

    monkeypatch.setattr('datetime.datetime', _Weekday)

    ok, name = harness.refresh_today_snapshot(ws)
    assert ok, name
    snap = ws / 'memory' / 'snapshots' / name
    before = snap.stat().st_mtime_ns
    fingerprint = dashboard_input_fingerprint(ws)

    ok, _ = harness.refresh_today_snapshot(ws)
    assert ok
    assert snap.stat().st_mtime_ns == before, (
        'an unchanged portfolio rewrote the snapshot, which moves the '
        'fingerprint and leaves --skip-if-unchanged permanently unfireable')
    assert dashboard_input_fingerprint(ws) == fingerprint

    (ws / 'portfolio.json').write_text('{"holdings": [1]}')
    ok, _ = harness.refresh_today_snapshot(ws)
    assert ok
    assert snap.read_text() == '{"holdings": [1]}', 'a real change must still land'
    assert dashboard_input_fingerprint(ws) != fingerprint


def test_the_builds_own_telemetry_does_not_move_the_fingerprint(tmp_path, monkeypatch):
    """#1247: the second self-writer, found because the gate never fired once.

    `record_preservation` appends a line to memory/.tmp on every build, and
    memory/.tmp is fingerprinted — so build N moved the fingerprint that build
    N+1's gate compares against, and `--skip-if-unchanged` was structurally
    unfireable on both the publisher (72x/day) and harness (~19x/day) paths.
    Measured before the fix: three consecutive builds against a desk with zero
    input change all rebuilt, each writing a different fingerprint.

    Driven through `record_preservation` itself rather than by writing the
    filename here, so renaming the telemetry file fails this test instead of
    silently re-opening the hole.
    """
    from clawock.publish import dashboard

    ws = _desk(tmp_path)
    monkeypatch.setattr(dashboard, 'WS_ROOT', ws)

    before = dashboard_input_fingerprint(ws)
    for _ in range(3):
        dashboard.record_preservation(
            presence={'insights': True}, taken=[], source=None,
            out_file=ws / 'assets' / 'data' / 'dashboard.json')
    written = list((ws / 'memory' / '.tmp').glob('preserve-absent-*.jsonl'))
    assert written and written[0].read_text().count('\n') == 3, (
        'the telemetry was not written, so this test proves nothing')
    assert dashboard_input_fingerprint(ws) == before, (
        "the build's own telemetry moved the fingerprint: every build "
        'invalidates the next one and --skip-if-unchanged can never fire')


def test_a_real_tmp_sidecar_still_moves_the_fingerprint(tmp_path):
    """The exclusion must stay a prefix, not become "ignore memory/.tmp".

    brief-context / insights / intraday-insights / sector-scan are embedded in
    the projection, so making the gate blind to them would swap #1247's stall
    for #1217's staleness.
    """
    from clawock.publish.dashboard import PRESERVE_ABSENT_PREFIX

    ws = _desk(tmp_path)
    tmp = ws / 'memory' / '.tmp'
    for name in ('brief-context-2026-09-01.json', 'insights-2026-09-01.json',
                 'intraday-insights-2026-09-01.json', 'sector-scan-2026-09-01.json'):
        before = dashboard_input_fingerprint(ws)
        assert not name.startswith(PRESERVE_ABSENT_PREFIX)
        (tmp / name).write_text('{"v": 1}')
        assert dashboard_input_fingerprint(ws) != before, f'{name} must move it'

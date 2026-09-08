"""A hung remote must be a diagnosis, not a traceback.

2026-09-07: every data-plane failure that day reached the log as a raw
`subprocess.TimeoutExpired` traceback from `publish_data_branch.py` /
`fetch_data_plane.py`. Both scripts handle `CalledProcessError` carefully — the
#370 handler even preserves both streams so a hook's refusal is not hidden — but
`TimeoutExpired` is a sibling of that class, so it fell through every handler.

A traceback in a cron log is the state nothing downstream can read: it has no
`✗ data-plane:` line for the health surfaces to key on, and it tells the reader
where Python was rather than what the remote did.
"""
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT / "ops" / "publish" / "publish_data_branch.py",
    ROOT / "ops" / "pages" / "fetch_data_plane.py",
)


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_a_timeout_is_caught_and_named(path):
    source = path.read_text()

    assert "except subprocess.TimeoutExpired" in source, (
        f"{path.name} still lets a hung remote escape as a traceback")


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_the_timeout_handler_precedes_the_called_process_one(path):
    """Order is not cosmetic here: they are siblings, so a reader who assumes
    subclassing would put the general one first and silently keep the bug."""
    source = path.read_text()

    timeout_at = source.index("except subprocess.TimeoutExpired")
    called_at = source.index("except subprocess.CalledProcessError")
    assert timeout_at < called_at


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_the_handler_reports_a_failure_not_a_success(path):
    """It must return non-zero and print the `✗ data-plane:` marker the rest of
    the pipeline reads — a timeout that exits 0 would publish nothing and say so
    to nobody."""
    source = path.read_text()
    body = source[source.index("except subprocess.TimeoutExpired"):]
    body = body[:body.index("except subprocess.CalledProcessError")]

    assert "✗ data-plane:" in body
    assert re.search(r"\breturn 1\b", body)
    assert "file=sys.stderr" in body


def _run_publisher_with(monkeypatch, tmp_path, failure):
    """Drive `publish_data_branch.main()` to one failure, in a scratch workspace."""
    import importlib.util

    # Import against the real checkout: module scope resolves the output list
    # from `config/`, which a scratch workspace does not have. A second call in
    # one test would otherwise import with the env already pointed at tmp_path.
    monkeypatch.delenv('CLAWOCK_WORKSPACE', raising=False)
    spec = importlib.util.spec_from_file_location(
        'pdb_under_test', ROOT / 'ops' / 'publish' / 'publish_data_branch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # After the import: module scope resolves the real checkout's output list,
    # while the ledger this test reads is resolved per call.
    monkeypatch.setenv('CLAWOCK_WORKSPACE', str(tmp_path))
    for name in module.DATA_PLANE_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}\n')

    class Store:
        def __init__(self, *a, **k):
            pass

        def publish(self, files, label=None):
            raise failure

    monkeypatch.setattr(module, 'GitBranchStore', Store)
    monkeypatch.setattr(
        'sys.argv', ['publish_data_branch.py', '--root', str(tmp_path)])
    assert module.main() == 1
    return module


def _degradations(tmp_path):
    import json

    return json.loads(
        (tmp_path / 'memory' / '.tmp' / 'workflow-outcomes.json').read_text()
    )['degradations']


def test_a_failed_publish_is_countable_afterwards(monkeypatch, tmp_path):
    """A tick that failed and repaired itself used to leave nothing dated.

    `logs/publish_dashboard.log` gets one undated line and
    `logs/dashboard_build_status.json` is a snapshot the next tick overwrites —
    so on 2026-09-08 the log held exactly one `✗ data-plane:` and there was no
    way to say when it happened or whether that rate was one a day or one a
    week. Same shape as the refused bars in #1146, same answer: append it where
    it accrues a count and a first/last timestamp.
    """
    import json
    import subprocess as sp

    from clawock.automation import workflow_outcomes

    _run_publisher_with(
        monkeypatch, tmp_path,
        sp.TimeoutExpired(cmd=['git', 'push'], timeout=120))

    rows = _degradations(tmp_path)
    assert [r['kind'] for r in rows] == ['data_plane_publish_failed']
    assert rows[0]['first_at'] and rows[0]['last_at']


def test_two_incidents_of_one_class_are_a_count_not_two_rows(monkeypatch, tmp_path):
    """The detail is the aggregation key, so it must name the class.

    Carrying the incident's own text — a sha, git's wording, the command line —
    would write a new row each time and leave every count at 1, which is the
    number that made the log unreadable in the first place.
    """
    import json
    import subprocess as sp

    _run_publisher_with(monkeypatch, tmp_path,
                        sp.TimeoutExpired(cmd=['git', 'push'], timeout=120))
    _run_publisher_with(monkeypatch, tmp_path,
                        sp.TimeoutExpired(cmd=['git', 'fetch', 'other'],
                                          timeout=120))

    rows = _degradations(tmp_path)
    assert len(rows) == 1, rows
    assert rows[0]['count'] == 2


def test_recording_a_failure_can_never_be_the_failure(monkeypatch, tmp_path):
    """A publisher that crashed while writing down that it failed would be
    strictly worse than one that failed quietly."""
    import subprocess as sp

    import clawock.automation.workflow_outcomes as outcomes

    def boom(*a, **k):
        raise RuntimeError('the ledger is unwritable')

    monkeypatch.setattr(outcomes, 'note_degradation', boom)
    # Still exits 1 from the real failure, not from this one.
    _run_publisher_with(monkeypatch, tmp_path,
                        sp.TimeoutExpired(cmd=['git', 'push'], timeout=120))

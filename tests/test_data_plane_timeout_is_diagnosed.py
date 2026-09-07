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

"""factor-snapshots must be verbatim, dated, and idempotent (#936).

The live sidecars (sentiment.json / macro.json) are overwritten in place by
their scan workflows; any backtest reading them after the fact sees today's
file instead of what a past day actually looked like. The snapshotter archives
a byte-exact copy per UTC date before the overwrite cycle continues.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))

import importlib.util


def _load():
    spec = importlib.util.spec_from_file_location(
        "snapshot_factor_sidecar", ROOT / "ops" / "ci" / "snapshot_factor_sidecar.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snap = _load()


def _write_source(tmp_path, body):
    src = tmp_path / "sentiment.json"
    src.write_bytes(body)
    return src


def test_first_run_creates_a_verbatim_dated_copy(tmp_path):
    src = _write_source(tmp_path, b'{"tickers": {"AAPL": {}}}')
    root = tmp_path / "snaps"

    action = snap.snapshot(src, "sentiment", "2026-08-25", root=root)

    assert action == "created"
    target = root / "sentiment" / "2026-08-25.json"
    assert target.read_bytes() == src.read_bytes()  # byte-exact, not re-dumped


def test_rerun_with_identical_content_is_a_noop(tmp_path):
    """Workflow retries must not churn the archive."""
    src = _write_source(tmp_path, b'{"v": 1}')
    root = tmp_path / "snaps"
    snap.snapshot(src, "sentiment", "2026-08-25", root=root)

    action = snap.snapshot(src, "sentiment", "2026-08-25", root=root)

    assert action == "unchanged"


def test_same_date_different_content_wins_as_final_version(tmp_path):
    """A drifted rerun legitimately overwrites that day's row — the archive
    keeps one final version per date, like the ledger's last-write rule."""
    src = _write_source(tmp_path, b'{"v": 1}')
    root = tmp_path / "snaps"
    snap.snapshot(src, "macro", "2026-08-25", root=root)

    src.write_bytes(b'{"v": 2}')
    action = snap.snapshot(src, "macro", "2026-08-25", root=root)

    assert action == "updated"
    assert (root / "macro" / "2026-08-25.json").read_bytes() == b'{"v": 2}'


def test_missing_source_fails_loudly_not_silently(tmp_path):
    """A scan job whose sidecar vanished must not green-light a night with no
    archived data — exit non-zero so the workflow shows it."""
    rc = snap.main(["--source", str(tmp_path / "absent.json"),
                    "--bucket", "sentiment"])
    assert rc == 1

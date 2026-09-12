"""`logs/dashboard_build_status.json` must never be readable as half a file.

It is the only evidence `cron_health_check.check_dashboard_build` has about the
data plane, and an unparseable status file is graded `failed` — a red line about
a dashboard that may be perfectly healthy, produced by nothing but the writing.

Five writers touch it: brief / report / intraday postflight, the host
publisher's `0,20,40 * * * *` tick, and the off-host brief fallback. A plain
`Path.write_text` truncates the file and writes after, so a reader landing in
that window gets an empty or partial file. `safe_io.safe_write_json` writes a
temp file in the same directory and `os.replace`s it: the worst case becomes
"the old status or the new status" (#1455).
"""
import ast
import json
import threading
from pathlib import Path

import pytest

from clawock.harness import _harness_common

SRC = Path(__file__).resolve().parents[1] / "src"
MODULE = SRC / "clawock/harness/_harness_common.py"
WRITER = "_record_dashboard_build"
ATOMIC_WRITERS = {"safe_write_json", "safe_write_text"}


def _writer_fn():
    tree = ast.parse(MODULE.read_text())
    fns = [n for n in ast.walk(tree)
           if isinstance(n, ast.FunctionDef) and n.name == WRITER]
    assert len(fns) == 1, f"{WRITER} is gone or duplicated — this gate is pointed at nothing"
    return fns[0]


def test_status_writer_goes_through_an_atomic_writer():
    fn = _writer_fn()
    src = ast.unparse(fn)
    assert "DASHBOARD_BUILD_STATUS" in src, (
        f"{WRITER} no longer names the status file; the write moved and this "
        f"gate must be pointed at wherever it went"
    )
    calls = {node.func.attr if isinstance(node.func, ast.Attribute)
             else getattr(node.func, "id", None)
             for node in ast.walk(fn) if isinstance(node, ast.Call)}
    assert calls & ATOMIC_WRITERS, (
        f"{WRITER} writes the status file without an atomic writer "
        f"({' / '.join(sorted(ATOMIC_WRITERS))})"
    )
    assert "write_text" not in calls and "write_bytes" not in calls, (
        f"{WRITER} still has a non-atomic write; a reader can catch the file "
        f"between truncate and write"
    )


def test_a_reader_never_catches_a_half_written_status(tmp_path):
    """The behavioural half: hammer the real writer while parsing the file.

    On a plain `write_text` this fails within a few hundred iterations (the
    reader sees a 0-byte file). Through `os.replace` there is no window at all,
    so this is deterministic rather than lucky.
    """
    (tmp_path / "logs").mkdir()
    path = tmp_path / _harness_common.DASHBOARD_BUILD_STATUS
    # A payload the size of a real one: `tail` alone is capped at 4000 chars.
    output = "warn: section degraded\n" + ("x" * 4000)
    stop = threading.Event()
    failures = []

    def write():
        i = 0
        while not stop.is_set() and i < 400:
            _harness_common._record_dashboard_build(
                True, True, output, ws=tmp_path, timings={"dashboard_build": i}
            )
            i += 1

    writer = threading.Thread(target=write)
    writer.start()
    try:
        reads = 0
        while writer.is_alive() and reads < 4000:
            try:
                text = path.read_text()
            except FileNotFoundError:
                continue
            reads += 1
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                failures.append(f"{exc} — {len(text)} bytes: {text[:80]!r}")
                break
    finally:
        stop.set()
        writer.join(timeout=30)

    assert not failures, (
        "cron_health_check would grade this read as `failed`: " + failures[0]
    )
    assert path.exists() and json.loads(path.read_text())["ok"] is True


def test_no_temp_files_are_left_behind(tmp_path):
    """`os.replace` writes a sibling temp file; it must not survive the write."""
    (tmp_path / "logs").mkdir()
    _harness_common._record_dashboard_build(True, True, "", ws=tmp_path)
    leftovers = [p.name for p in (tmp_path / "logs").iterdir()
                 if p.name.startswith(".tmp-")]
    assert not leftovers, f"temp files left in logs/: {leftovers}"

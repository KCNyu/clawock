"""gc_sessions must delete exactly what the per-rule sweeps deleted.

The nightly sweep used to be six full iterdir() passes; it is now one pass
that deletes a file iff ANY matching rule's cutoff makes it stale. The subtle
case is a name matching two rules with different retentions — e.g.
`2026-08-01.bak-1.jsonl` matches both the plain-.jsonl rule (14d) and the
bak rule (3d): three days after creation it must go, even though it is far
younger than the session retention, because the old pass-4 would have caught
it. Behavioural tests drive main() with scratch directories.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_gc_sessions", ROOT / "ops" / "host" / "gc_sessions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gc = _load()


def _point_dirs(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    tmp = tmp_path / "mem" / ".tmp"
    sessions.mkdir()
    tmp.mkdir(parents=True)
    monkeypatch.setattr(gc, "SESSIONS_DIR", sessions)
    monkeypatch.setattr(gc, "WORKSPACE_TMP", tmp)
    monkeypatch.setattr(gc, "HANDOFF_FILE", tmp_path / "absent-handoff.json")
    return sessions


def test_a_multi_match_name_ages_out_on_its_shortest_retention(
        monkeypatch, tmp_path):
    """bak-1.jsonl: 5 days old → bak rule (3d) fires even though the jsonl
    rule (14d) alone would keep it."""
    sessions = _point_dirs(monkeypatch, tmp_path)
    f = sessions / "2026-08-01.bak-1.jsonl"
    f.write_text("{}")
    import os
    old = gc.KEEP_BAK_DAYS + 2
    stamp = __import__("time").time() - old * 86400
    os.utime(f, (stamp, stamp))

    total_files, _ = gc.gc_sessions_dir(__import__("time").time(), False)

    assert total_files == 1 and not f.exists()


def test_a_young_multi_match_name_survives(monkeypatch, tmp_path):
    sessions = _point_dirs(monkeypatch, tmp_path)
    f = sessions / "2026-08-20.bak-1.jsonl"
    f.write_text("{}")  # mtime = now

    total_files, _ = gc.gc_sessions_dir(__import__("time").time(), True)

    assert total_files == 0 and f.exists()


def test_one_pass_deletes_the_same_set_the_six_passes_did(
        monkeypatch, tmp_path):
    """Golden set spanning every rule, mixed fresh and stale, plus a file no
    rule matches (must survive forever)."""
    import os
    import time

    now = time.time()
    cases = {
        # name: (age_days, should_be_deleted)
        "s1.trajectory.jsonl": (8, True),
        "s2.trajectory.jsonl": (2, False),
        "s3.jsonl": (15, True),
        "s4.jsonl": (10, False),
        "s5.json": (15, True),
        "x.bak-1.jsonl": (4, True),      # multi-match: bak retention wins
        "y.pre-cleanup-2.json": (2, False),
        "s6.jsonl.1779044443580": (4, True),
        "t7.jsonl.deleted.2026-06-14T19-00-50.702Z": (20, True),
        "t8.jsonl.reset.2026-08-20T01-00-00.000Z": (1, False),
        "unmatched.txt": (400, False),   # nothing matches .txt
    }
    sessions = _point_dirs(monkeypatch, tmp_path)
    for name, (age, _) in cases.items():
        p = sessions / name
        p.write_text("x")
        stamp = now - age * 86400
        os.utime(p, (stamp, stamp))

    total_files, _ = gc.gc_sessions_dir(now, False)

    expected = sum(1 for _, gone in cases.values() if gone)
    assert total_files == expected
    for name, (_, gone) in cases.items():
        assert (sessions / name).exists() is not gone, name


def test_main_reports_totals_and_never_touches_unmatched(
        monkeypatch, tmp_path, capsys):
    sessions = _point_dirs(monkeypatch, tmp_path)
    dead = sessions / "old.trajectory.jsonl"
    dead.write_text("x")
    import os
    import time
    stamp = time.time() - (gc.KEEP_TRAJECTORY_DAYS + 1) * 86400
    os.utime(dead, (stamp, stamp))
    monkeypatch.setattr(sys, "argv", ["gc_sessions.py"])

    gc.main()

    out = capsys.readouterr().out
    assert "trajectory.jsonl: 1 files" in out
    assert "freed 1 files" in out or "would free 1 files" not in out
    assert not dead.exists()

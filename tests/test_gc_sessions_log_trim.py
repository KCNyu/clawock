"""The nightly sweep must cap the append-only logs without breaking a writer.

`logs/` had no rotation of any kind: `publish_dashboard.log` was 10,484 lines
and `logs/watchdog.jsonl` 99 days of delivery evidence, both still growing
(#1324). The sweep that already prunes sessions/ and memory/.tmp now trims them
back to a tail — which is the only retention that fits a single ever-growing
file, since an age cutoff on one would delete all of it or none of it.

Two properties matter more than the trimming itself:

* the inode survives, because the cron lines redirect with `>>` and a running
  job holds an O_APPEND descriptor on it;
* state files sharing the directory (`brief_postflight_status.json`) are not
  logs and must come through untouched.
"""
import importlib.util
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    for path in (ROOT, ROOT / "src"):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    spec = importlib.util.spec_from_file_location(
        "kcnyu_gc_sessions_logs", ROOT / "ops" / "host" / "gc_sessions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gc = _load()
OLD = time.time() - 3600


def _logs_dir(tmp_path, files):
    logs = tmp_path / "logs"
    logs.mkdir()
    for name, text in files.items():
        path = logs / name
        path.write_text(text, encoding="utf-8")
        import os
        os.utime(path, (OLD, OLD))
    return logs


def _fat(marker="line", lines=50000):
    return "".join(f"{marker} {i}\n" for i in range(lines))


def test_an_oversized_log_keeps_its_tail_and_loses_its_head(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 100)
    logs = _logs_dir(tmp_path, {"publish_dashboard.log": _fat()})

    gc.trim_logs(time.time(), dry_run=False, dirpath=logs)

    kept = (logs / "publish_dashboard.log").read_text().splitlines()
    assert len(kept) == 100
    assert kept[-1] == "line 49999", "the newest line must survive"
    assert "line 0" not in kept, "the head must be gone"


def test_the_inode_survives_so_a_running_cron_keeps_writing(tmp_path, monkeypatch):
    """`>>` in crontab means a live job holds a descriptor on this file."""
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 10)
    logs = _logs_dir(tmp_path, {"watchdog.jsonl": _fat("{}")})
    log = logs / "watchdog.jsonl"
    before = log.stat().st_ino

    with log.open("a", encoding="utf-8") as appending_job:
        gc.trim_logs(time.time(), dry_run=False, dirpath=logs)
        appending_job.write("after the trim\n")

    assert log.stat().st_ino == before, "renaming would strand the open writer"
    assert log.read_text().endswith("after the trim\n")


def test_a_state_file_in_the_same_directory_is_not_a_log(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 10)
    state = '{"sent_ok": true, "padding": "' + "x" * 200000 + '"}'
    logs = _logs_dir(tmp_path, {"brief_postflight_status.json": state})

    gc.trim_logs(time.time(), dry_run=False, dirpath=logs)

    assert (logs / "brief_postflight_status.json").read_text() == state, (
        "a status file read whole was cut in half")


def test_a_log_still_being_written_this_minute_is_left_alone(tmp_path, monkeypatch):
    """Racing an appender for a few KB is not worth a torn line."""
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 10)
    logs = _logs_dir(tmp_path, {"gold_dca.log": _fat()})
    fresh = logs / "gold_dca.log"
    now = time.time()
    import os
    os.utime(fresh, (now, now))

    gc.trim_logs(now, dry_run=False, dirpath=logs)

    assert len(fresh.read_text().splitlines()) == 50000


def test_a_log_under_the_thresholds_is_untouched(tmp_path, monkeypatch):
    """Hysteresis: a log five times the tail is what gets rewritten, not any log."""
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 2000)
    logs = _logs_dir(tmp_path, {"dst-sync.log": _fat(lines=9000)})

    files, _ = gc.trim_logs(time.time(), dry_run=False, dirpath=logs)

    assert files == 0
    assert len((logs / "dst-sync.log").read_text().splitlines()) == 9000


def test_one_pathological_line_still_trips_the_byte_cap(tmp_path, monkeypatch):
    """A line count cannot see a single multi-megabyte line."""
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 2)
    monkeypatch.setattr(gc, "KEEP_LOG_MB", 0.2)
    logs = _logs_dir(tmp_path, {"gitgc.log": "x" * 300000 + "\ntail one\ntail two\n"})

    files, freed = gc.trim_logs(time.time(), dry_run=False, dirpath=logs)

    assert files == 1 and freed > 250000
    assert (logs / "gitgc.log").read_text() == "tail one\ntail two\n"


def test_dry_run_reports_without_cutting(tmp_path, monkeypatch):
    monkeypatch.setattr(gc, "KEEP_LOG_LINES", 10)
    logs = _logs_dir(tmp_path, {"nostr_broadcast.log": _fat()})

    files, freed = gc.trim_logs(time.time(), dry_run=True, dirpath=logs)

    assert files == 1 and freed > 0
    assert len((logs / "nostr_broadcast.log").read_text().splitlines()) == 50000

"""Throwaway CI diagnostics: per-test timings, and an optional wait after collection."""
import json
import os
import time

ROWS = []
_TRAVEL = None


def pytest_configure(config):
    global _TRAVEL
    at = os.environ.get("DIAG_AT")
    if at and _TRAVEL is None:
        import datetime
        import time_machine
        dest = datetime.datetime.strptime(at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.timezone.utc)
        _TRAVEL = time_machine.travel(dest, tick=True)
        _TRAVEL.start()


def pytest_collection_finish(session):
    delay = float(os.environ.get("DIAG_LATE") or 0)
    if delay and hasattr(session.config, "workerinput"):
        time.sleep(delay)


def pytest_runtest_logreport(report):
    ROWS.append({
        "id": report.nodeid, "when": report.when, "d": report.duration,
        "w": getattr(report, "worker_id", None) or "main",
        "start": getattr(report, "start", None), "stop": getattr(report, "stop", None),
        "outcome": report.outcome,
    })


def pytest_sessionfinish(session):
    if hasattr(session.config, "workerinput"):
        return
    out = os.environ.get("DIAG_OUT")
    if out:
        with open(out, "w") as handle:
            for row in ROWS:
                handle.write(json.dumps(row) + "\n")

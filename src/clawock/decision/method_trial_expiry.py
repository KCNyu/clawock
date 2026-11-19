"""Produce local, descriptive reports for expired frozen trials."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from clawock import code_identity
from clawock.decision.method_trials import ARMS, _digest, _evaluator_version, _registration, _write_once

_FINGERPRINTS = {
    "clawock.decision.ledger": "decision/ledger.py",
    "clawock.decision.shadow": "decision/shadow.py",
    "clawock.costs": "costs.py",
    "method_trials": "decision/method_trials.py",
}


def _replay_registered(workspace, trial, now):
    """Run only the registered source from trusted local history."""
    trial_id = trial["trial_id"]
    if trial["evaluator_version"] == _evaluator_version():
        from clawock.decision.method_trials import replay
        return replay(workspace, trial_id, now=now)

    source = Path(__file__).resolve().parents[3]
    revision = trial.get("evaluator", {}).get("code") or ""
    if not re.fullmatch(r"[0-9a-f]{7,40}", revision):
        raise ValueError("registration lacks a usable evaluator commit")

    def git(*args):
        return subprocess.check_output(["git", "-C", str(source), *args], timeout=15,
                                       stderr=subprocess.DEVNULL)

    commit = git("rev-parse", "--verify", f"{revision}^{{commit}}").decode().strip()
    git("merge-base", "--is-ancestor", commit, "HEAD")
    archive = git("archive", commit, "src/clawock")
    scratch = workspace / "memory/.tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="method-evaluator-", dir=scratch) as folder:
        with tarfile.open(fileobj=io.BytesIO(archive)) as files:
            files.extractall(folder, filter="data")
        src = Path(folder) / "src"
        fingerprints = {key: code_identity.file_digest(src / "clawock" / path)
                        for key, path in _FINGERPRINTS.items()}
        if fingerprints != trial["evaluator_version"]:
            raise ValueError("registered evaluator source fingerprint mismatch")
        script = (
            "import json, sys; from datetime import datetime;"
            "from clawock.decision.method_trials import replay;"
            "print(json.dumps(replay(sys.argv[1], sys.argv[2], now=datetime.fromisoformat(sys.argv[3]))))"
        )
        result = subprocess.check_output(
            [sys.executable, "-c", script, str(workspace), trial_id, now.isoformat()],
            cwd=folder, timeout=90,
            env={**os.environ, "PYTHONPATH": str(src), "CLAWOCK_WORKSPACE": str(workspace)})
    return json.loads(result)


def _summary(report, report_path):
    arms = {}
    for name in ARMS:
        arm = report["arms"][name]
        currencies = {}
        for currency, metrics in arm.get("metrics", {}).items():
            simulation = arm["simulation"]["curves"][currency]
            charges = simulation["net"].get("charges") or []
            currencies[currency] = {
                **{key: metrics.get(key) for key in ("status", "net_benefit", "missed_gain",
                                                     "max_drawdown", "upside_capture", "missing_marks")},
                "modeled_cost_charged": round(sum(charge["total"] for charge in charges), 4),
            }
        arms[name] = {"status": arm["status"], "proposed": arm["proposed"], "currencies": currencies}
    return {"trial_id": report["trial_id"], "as_of": report["as_of"], "status": "descriptive",
            "report": report_path, "arms": arms, "automatic_selection": False,
            "next_step": "human review before any expansion or method selection"}


def report_due(workspace, *, now=None):
    workspace = Path(workspace).resolve()
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(timezone.utc).date().isoformat()
    failures, generated = [], []
    for path in sorted((workspace / "memory/method-trials").glob("trial-*/registration.json")):
        trial_id = path.parent.name
        try:
            trial = _registration(workspace, trial_id)
            if trial["trial_id"] != trial_id:
                raise ValueError("registration identity mismatch")
            if trial["end_date"] >= today:
                continue
            summary_path = path.with_name("expiry-summary.json")
            if summary_path.exists():
                continue
            report = _replay_registered(workspace, trial, now.astimezone(timezone.utc))
            if report["status"] != "descriptive" or report["as_of"] != trial["end_date"]:
                raise ValueError("registered evaluator did not reach expiry")
            report_name = f"report-{_digest(report)[:16]}.json"
            if not path.with_name(report_name).is_file():
                raise ValueError("registered evaluator did not write its report")
            _write_once(summary_path, _summary(report, report_name))
            generated.append(trial_id)
        except (OSError, ValueError, TypeError, KeyError, tarfile.TarError, subprocess.SubprocessError) as exc:
            failures.append({"trial_id": trial_id, "error": str(exc)})
    return {"generated": generated, "failures": failures}

"""Every off-host LLM workflow must give its provider chain a deadline.

brief-fallback learned this on 2026-08-17: MiniMax hit RemoteDisconnected,
started retrying inside a per-attempt timeout=900 x MAX_RETRIES=3 budget, and
the runner killed the 15-minute job before opencode-go was ever asked. The
chain deadline (`CLAWOCK_LLM_DEADLINE_SECONDS`) is opt-in — a workflow that
forgets it silently re-creates that failure mode. This file exists so the next
new workflow cannot forget.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DEADLINE_KEY = "CLAWOCK_LLM_DEADLINE_SECONDS"

# (workflow file, job id) for every job that invokes an LLM provider chain.
LLM_JOBS = [
    ("brief-fallback.yml", "fallback"),
    ("news-digest.yml", "digest"),
    ("influencer-scan.yml", "scan"),
    ("weekly-review.yml", "review"),
]


def _workflow(name):
    return yaml.safe_load(
        (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    )


def _deadline_seconds(job):
    """The chain budget wherever the workflow declares it: job-level env or any
    step-level env."""
    scopes = [job.get("env") or {}]
    scopes += [step.get("env") or {} for step in job.get("steps", [])]
    values = [s[DEADLINE_KEY] for s in scopes if DEADLINE_KEY in s]
    assert values, (
        f"{DEADLINE_KEY} missing — without a chain deadline a hung primary "
        f"makes the fallback provider unreachable (2026-08-17 defect class)"
    )
    return float(values[0])


@pytest.mark.parametrize("workflow_name,job_id", LLM_JOBS)
def test_the_provider_chain_fits_inside_the_job(workflow_name, job_id):
    job = _workflow(workflow_name)["jobs"][job_id]

    budget = _deadline_seconds(job)
    job_seconds = float(job["timeout-minutes"]) * 60

    assert budget < job_seconds, (
        f"{workflow_name}: the LLM budget must fit inside the job, or the "
        f"second provider is unreachable code rather than a fallback"
    )
    assert job_seconds - budget >= 60, (
        f"{workflow_name}: setup, validation and commit still have to fit in "
        f"what is left of the job"
    )

"""Every off-host LLM workflow must give its provider chain a deadline.

brief-fallback learned this on 2026-08-17: MiniMax hit RemoteDisconnected,
started retrying inside a per-attempt timeout=900 x MAX_RETRIES=3 budget, and
the runner killed the 15-minute job before opencode-go was ever asked. The
chain deadline (`CLAWOCK_LLM_DEADLINE_SECONDS`) is opt-in — a workflow that
forgets it silently re-creates that failure mode. This file exists so the next
new workflow cannot forget.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
import yaml

from clawock.automation import llm

ROOT = Path(__file__).resolve().parents[1]
DEADLINE_KEY = "CLAWOCK_LLM_DEADLINE_SECONDS"

# (workflow file, job id) for every job that invokes an LLM provider chain.
# CHAINS: how many independent provider chains the job can run (influencer
# scans twice daily in one workflow — two dispatch invocations, but one chain
# per RUN). A job that legitimately chains N provider calls back-to-back must
# declare a deadline covering the aggregate, not one leg (E-P2④).
LLM_JOBS = [
    ("brief-fallback.yml", "fallback", 1),
    ("news-digest.yml", "digest", 1),
    # 2, not 1: score_items() wraps its chat() in `for attempt in (1, 2)` and
    # retries an empty batch, so one run can open two chains back to back. The
    # table used to say 1 and read "two dispatch invocations, one chain per
    # RUN" -- which is about the schedule, not about this loop.
    ("influencer-scan.yml", "scan", 2),
    ("weekly-review.yml", "review", 1),
]

# Where each job enters the provider chain. The timeout is read from the call
# site itself, not from this table -- the table only says which file to open.
CALL_SITES = {
    ("brief-fallback.yml", "fallback"): "src/clawock/automation/brief_fallback.py",
    ("news-digest.yml", "digest"): "src/clawock/automation/news_digest.py",
    ("influencer-scan.yml", "scan"): "src/clawock/automation/influencer.py",
    ("weekly-review.yml", "review"): "src/clawock/automation/weekly_review.py",
}

# llm.py calls chat() in its own `__main__` sanity CLI; that one runs by hand,
# not on a schedule, so it has no workflow to fit inside.
CHAT_CALL_EXEMPT = {"src/clawock/automation/llm.py"}


def _chat_calls(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "chat"
    ]


def _call_site_timeout(rel_path: str) -> float:
    """The per-attempt seconds the caller in `rel_path` actually asks for.

    A call site that passes no `timeout=` gets llm.TIMEOUT, so that is what the
    invariant has to be measured against -- the defect this file guards was an
    omission, and an omission has a value.
    """
    path = ROOT / rel_path
    calls = _chat_calls(path)
    assert calls, f"{rel_path}: no chat() call site found"
    seen = set()
    for call in calls:
        kwarg = next((k for k in call.keywords if k.arg == "timeout"), None)
        if kwarg is None:
            seen.add(float(llm.TIMEOUT))
            continue
        node = kwarg.value
        if isinstance(node, ast.Constant):
            seen.add(float(node.value))
        elif isinstance(node, ast.Name):
            module = importlib.import_module(
                rel_path.removeprefix("src/").removesuffix(".py").replace("/", ".")
            )
            value = getattr(module, node.id, None)
            assert isinstance(value, (int, float)), (
                f"{rel_path}: chat(timeout={node.id}) is not a module-level "
                f"number the contract can read"
            )
            seen.add(float(value))
        else:  # pragma: no cover - keeps the failure legible if one appears
            pytest.fail(f"{rel_path}: chat(timeout=...) is not a literal or a name")
    assert len(seen) == 1, f"{rel_path}: chat() call sites disagree on timeout: {seen}"
    return seen.pop()


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


@pytest.mark.parametrize("workflow_name,job_id,chains", LLM_JOBS)
def test_the_provider_chain_fits_inside_the_job(workflow_name, job_id, chains):
    job = _workflow(workflow_name)["jobs"][job_id]

    budget = _deadline_seconds(job) * chains
    job_seconds = float(job["timeout-minutes"]) * 60

    assert budget < job_seconds, (
        f"{workflow_name}: {chains} chain(s) x deadline must fit inside the "
        f"job, or the second provider is unreachable code rather than a "
        f"fallback"
    )
    assert job_seconds - budget >= 60, (
        f"{workflow_name}: setup, validation and commit still have to fit in "
        f"what is left of the job"
    )


def test_every_chat_call_site_belongs_to_a_declared_job():
    """A new caller must join the table above, not inherit the 180s default.

    The two tests below only cover what CALL_SITES lists, so without this the
    gate's own coverage silently drops the moment someone adds a fifth caller.
    """
    found = {
        str(path.relative_to(ROOT))
        for path in sorted((ROOT / "src").rglob("*.py"))
        if _chat_calls(path)
    } - CHAT_CALL_EXEMPT
    assert found == set(CALL_SITES.values()), (
        "chat() call sites and the declared LLM jobs have drifted apart: "
        f"undeclared={sorted(found - set(CALL_SITES.values()))} "
        f"missing={sorted(set(CALL_SITES.values()) - found)}"
    )


@pytest.mark.parametrize("workflow_name,job_id,chains", LLM_JOBS)
def test_one_attempt_can_use_the_primarys_whole_share(workflow_name, job_id, chains):
    """A per-attempt timeout below the primary's budget share is unspendable.

    `_attempt_timeout` clamps each attempt to min(timeout, budget left), so a
    timeout smaller than the share cuts that share into slices -- and a
    generation that needs more than one slice cannot be finished by adding
    attempts, however many seconds remain. The weekly review ran with the 180s
    default against a 360s share and lost 2026-W33 (run 31952091127) and
    2026-W35 (run 33326401496) to three identical `timeout after 180s` lines,
    with the whole budget spent and the answer never once given room to land.
    """
    job = _workflow(workflow_name)["jobs"][job_id]
    share = _deadline_seconds(job) * llm.PRIMARY_BUDGET_SHARE
    timeout = _call_site_timeout(CALL_SITES[(workflow_name, job_id)])

    assert timeout >= share, (
        f"{workflow_name}: chat(timeout={timeout:.0f}) is smaller than the "
        f"primary's own share of the deadline ({share:.0f}s), so the ladder "
        f"spends that share on {llm.MAX_RETRIES} attempts that are each too "
        f"short to finish the generation"
    )

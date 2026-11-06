"""`why` is one bounded page: facts, not prompts/log bodies/secrets; history can filter attention."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
OPS = ROOT / "ops/host/task_queue_ops.py"
TS = "2026-01-01 00:00:00"
UUID = "11111111-2222-3333-4444-555555555555"
ORIGIN = "agent:main:wechat:direct:o9cq80-secret-peer"


def run(tasks, *args):
    env = {**os.environ, "AGENT_DISPATCH_TASKS_DIR": str(tasks)}
    r = subprocess.run([sys.executable, str(OPS), *args], env=env, capture_output=True, text=True, timeout=60)
    return r


@pytest.fixture
def q(tmp_path):
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    d = tasks / "why-task-20260101-000000"
    d.mkdir()
    (d / "meta.env").write_text(
        f"ID={d.name}\nAGENT=codex\nNAME=why-task\nCWD=/root\nPARENT_TASK_ID=parent-1\n"
        "ANSWER_OF=''\nMODEL=gpt-6.1-sol\nEFFORT=medium\nNOTIFY=weixin,telegram\n"
        f"ORIGIN_SESSION={ORIGIN}\nWAKE_DEPTH=1\nCREATED='{TS}'\n")
    (d / "result.env").write_text(
        "STATE=ok\nOUTCOME=DONE\nSTARTED='2026-01-01 00:01:00'\nFINISHED_EPOCH=1767225660.0\n"
        f"SESSION={UUID}\nATTEMPTS=2\nMAX_ATTEMPTS=3\nQUOTA_RESUMES_USED=1\nLATER_USED=1\n"
        "MODEL_USED=gpt-6.1-sol\nEFFORT_USED=medium\nNEEDS=none\nNEED_SUMMARY=none\n"
        "ATTENTION=person\nSTAGE=person/review\nRESTART=''\nSTOP_REASON=completed\n"
        "NOTIFIED=weixin,telegram\nNOTIFY_FAILED=''\nNOTIFY_AT='2026-01-01 00:10:00'\nNOTICE=attempted\n")
    (d / "mandate.json").write_text(json.dumps({
        "actions": {"gateway.restart": "deny", "live.refresh": "allow"},
        "source": {"kind": "chat", "id": ORIGIN}, "strength": "explicit",
        "policy_version": "dispatch-test", "scope": {"cwd": "/root"}}))
    (d / "free-pool-selection.json").write_text(json.dumps({
        "mode": "automatic", "models": ["opencode/free-a", "opencode/free-b"],
        "reasons": {"opencode/free-a": "seed priority 1", "opencode/free-b": "exploration slot"}}))
    (d / "attempt1.env").write_text(
        "RUN_NO=1\nKIND=task\nSTARTED_EPOCH=1767225660.0\nENDED_EPOCH=1767225720.0\nRC=0\nAKIND=ok\n")
    (d / "attempt2.env").write_text("RUN_NO=2\nKIND=append\nSTARTED_EPOCH=''\n")
    (d / "run.log").write_text(
        f"---- {TS} attempt 1/3 (task) cap=300s session={UUID} model=gpt-6.1-sol/medium\n"
        f"---- {TS} attempt 2/3 (append) cap=300s session={UUID} model=gpt-6.1-sol/medium\n")
    (d / "runner-summary.txt").write_text("第一行结论\nPROMPT-SECRET\n")
    (d / "prompt.md").write_text("PROMPT-SECRET-BODY\n")
    (d / "wake-end.json").write_text(json.dumps({"state": "acknowledged", "attempts": 1}))
    (d / "question.json").write_text(json.dumps({
        "state": "open", "key": "pick", "title": "选一个", "options": ["甲", "乙"], "recommend": 0}))
    (d / "answer.json").write_text(json.dumps({
        "state": "answered", "choice": 2, "choice_text": "乙", "answered_by": ORIGIN,
        "answered_at": TS, "resume_task_id": "why-task-answer"}))
    (d / "later.json").write_text(json.dumps({
        "state": "waiting", "at": "2026-01-02T00:00:00+08:00", "key": "ci-check",
        "about": "查 CI", "attempt": 2}))
    (d / "later-1.json").write_text(json.dumps({
        "state": "waiting", "at": "2026-01-01T12:00:00+08:00", "key": "old", "attempt": 1}))
    (d / "audit.log").write_text(
        f"{TS}\tsource=cli\taction=cancel\tsession={UUID} token=supersecret\topps=1\n")
    inbox = d / "inbox"
    (inbox / "delivered").mkdir(parents=True)
    (inbox / "delivered" / "20260101-010101-1-now.md").write_text("delivered\n")
    (inbox / "delivered" / "20260101-010101-1-now.md.run").write_text("2\n")
    (inbox / "20260101-020202-2-now.md").write_text("pending\n")
    _task(tasks, "quiet-task-20260101-000000", "none")
    return tasks, d


def _task(tasks, tid, attention):
    d = tasks / tid
    d.mkdir()
    (d / "meta.env").write_text(f"ID={tid}\nAGENT=codex\nNAME={tid}\nCREATED='{TS}'\n")
    (d / "result.env").write_text(f"STATE=ok\nOUTCOME=DONE\nATTENTION={attention}\n")


def test_why_is_one_page_without_prompt_or_secrets(q):
    tasks, d = q
    r = run(tasks, "--json", "why", d.name)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["task"]["state"] == "ok" and out["task"]["outcome"] == "DONE"
    assert out["dispatch"] == {"origin": "agent:main:wechat:direct:…", "parent": "parent-1",
                               "answer_of": "", "wake_depth": 1}
    assert out["mandate"]["actions"]["gateway.restart"] == "deny"
    assert out["mandate"]["source_id"] == "agent:main:wechat:direct:…"
    assert out["models"]["free_pool"]["models"] == ["opencode/free-a", "opencode/free-b"]
    assert [run["run_no"] for run in out["runs"]] == [1, 2]
    assert out["runs"][0]["model"] == "gpt-6.1-sol/medium" and out["runs"][0]["duration_sec"] == 60
    assert [a["disposition"] for a in out["appends"]] == ["taken_not_started", "not_delivered"]
    assert out["wake"]["end"]["state"] == "acknowledged"
    assert out["notify"]["sent"] == "weixin,telegram"
    assert out["question"]["state"] == "answered" and out["question"]["title"] == "选一个"
    assert out["answer"]["text"] == "乙" and out["answer"]["resume_task_id"] == "why-task-answer"
    assert out["later"]["key"] == "ci-check" and out["later_history"][0]["key"] == "old"
    assert out["report_first_line"] == "第一行结论"
    text = json.dumps(out, ensure_ascii=False)
    assert "PROMPT-SECRET" not in text and "supersecret" not in text
    assert ORIGIN not in text and UUID not in text


def test_why_text_is_readable_and_history_filters_attention(q):
    tasks, d = q
    r = run(tasks, "why", d.name)
    assert r.returncode == 0, r.stderr
    assert "task: why-task-20260101-000000" in r.stdout
    assert "runs: 2" in r.stdout and "1. kind=task" in r.stdout
    assert "question: answered key=pick" in r.stdout
    assert "later: waiting" in r.stdout
    assert "PROMPT-SECRET" not in r.stdout and "supersecret" not in r.stdout
    assert ORIGIN not in r.stdout and UUID not in r.stdout
    r = run(tasks, "--json", "history", "--attention", "person")
    rows = json.loads(r.stdout)["tasks"]
    assert [row["id"] for row in rows] == ["why-task-20260101-000000"]
    r = run(tasks, "--json", "history", "--attention", "none")
    assert [row["id"] for row in json.loads(r.stdout)["tasks"]] == ["quiet-task-20260101-000000"]


def test_unknown_task_is_4(q):
    tasks, _ = q
    r = run(tasks, "why", "no-such-task")
    assert r.returncode == 4

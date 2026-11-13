"""Dispatch/task intake: raw words are queued privately, a model distils them, and
only a screened one-line conclusion reaches the store."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "ops/host/shared-memory/scripts/intake.py"
PUBLISH = ROOT / "ops/host/shared-memory/scripts/publish.py"


def write_topic(path, slug, description, body, *, publish="public", order=1, separator="false"):
    path.write_text(f"""---
name: {slug}
description: "{description}"
metadata:
  type: feedback
  updated: 2026-11-13
  scope: engineering
  salience: high
  status: verified
  tags: "issues, dispatch"
  publish: {publish}
  agent: rick
  order: {order}
  separator: {separator}
---

{body}
""")


def make_store(root):
    store = root / "store"
    (store / "indexes").mkdir(parents=True)
    (store / "archive").mkdir()
    (store / "indexes/MEMORY-host.md").write_text("# Host\n\n- a rule\n")
    (store / "indexes/routes.tsv").write_text("*\tindexes/MEMORY-host.md\n")
    (store / "indexes/redirects.tsv").write_text("# old\tnew\n")
    (store / "MEMORY.md").write_text("# Index\n\n- `indexes/MEMORY-host.md` — host\n")
    write_topic(store / "feedback-issue-handling-sop.md", "feedback-issue-handling-sop",
                "派 agent 处理 issues 时必须带 kcn 的原话：不要信任 issue 描述，独立复现或反证后再修或关",
                "# SOP\n\n不要信任 issue 描述，先独立复现。", order=1)
    return store


def make_repo(root, store):
    repo = root / "repo"
    repo.mkdir()
    (repo / "ops/host/shared-memory").mkdir(parents=True)
    env = env_for(root, store, repo)
    subprocess.run([sys.executable, str(PUBLISH), "--write", "--repo", str(repo),
                    "--store", str(store)], env=env, check=True, capture_output=True, text=True)
    return repo


def env_for(root, store, repo):
    return {**os.environ,
            "SHARED_MEMORY_DIR": str(store),
            "SHARED_MEMORY_STATE": str(root / "state"),
            "SHARED_MEMORY_HISTORY": "0",
            "MEMORY_LLM_MODEL": "test/model",
            "OPENCLAW_WORKSPACE": str(repo)}


def prompt(task, words, extra=""):
    task.mkdir(parents=True)
    (task / "prompt.md").write_text(
        f"【kcn 的原话】（唯一需求来源，逐字）\n\n「{words}」\n\n{extra}"
        "【事实线索】\n- material\n\n---\n【派发约定】这是无人值守的独立任务。\n")


def run(env, root, store, repo, *args):
    return subprocess.run([sys.executable, str(INTAKE), "--store", str(store),
                           "--repo", str(repo), *args], env=env, capture_output=True, text=True,
                          timeout=60)


def capture(env, task, stage="dispatch"):
    result = subprocess.run([sys.executable, str(INTAKE), "capture", "--task-dir", str(task),
                             "--stage", stage], env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def queue_item(root, name):
    path = root / "state/intake/queue" / name
    return json.loads(path.read_text())


def test_capture_keeps_the_owners_words_and_drops_the_contract(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-20261113-211235"
    prompt(task, "以后派 agent 处理 issues 时，不要完全信任 issue 的描述，先独立复现。")
    result = capture(env, task)
    item = queue_item(tmp_path, "verify-issues-20261113-211235-dispatch.json")
    assert "不要完全信任 issue 的描述" in item["user_words"]
    assert "无人值守" not in item["user_words"]
    assert item["task_id"] == "verify-issues-20261113-211235"
    assert result["queued"].endswith(".json")


def test_a_repeat_is_skipped_by_the_existing_topic_not_written_again(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-2"
    prompt(task, "以后派 agent 处理 issues 时，不要完全信任 issue 的描述，先独立复现。")
    capture(env, task)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({
        "store": True, "kind": "rule", "summary": "处理 issue 前先独立复现",
        "conclusion": "处理 issue 前先独立复现或反证，不照描述直接改代码",
        "slug": "feedback-reproduce-issue-claims", "scope": "engineering",
        "salience": "high", "publish": "private", "tags": ["issues"],
        "confidence": 0.9, "reason": "重复出现", "existing_topic": "feedback-issue-handling-sop"}))
    result = run(env, tmp_path, store, repo, "run", "--limit", "1", "--llm-response", str(reply))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["skipped"] == 1 and summary["written"] == 0
    assert summary["results"][0]["existing_topic"] == "feedback-issue-handling-sop"
    assert not (store / "feedback-reproduce-issue-claims.md").exists()
    assert not (tmp_path / "state/intake/queue/verify-issues-2-dispatch.json").exists()


def test_a_rephrased_repeat_is_caught_without_the_models_help(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-2b"
    prompt(task, "以后派 agent 处理 issues 时，不要完全信任 issue 的描述，先独立复现。")
    capture(env, task)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({
        "store": True, "kind": "rule", "summary": "处理 issue 前先独立复现",
        "conclusion": "派 agent 处理 issues 时不要信任 issue 描述，先独立复现再修",
        "slug": "feedback-issue-claims", "scope": "engineering", "salience": "high",
        "publish": "private", "tags": [], "confidence": 0.9, "reason": "重复",
        "existing_topic": None}))
    result = run(env, tmp_path, store, repo, "run", "--limit", "1", "--llm-response", str(reply))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["skipped"] == 1 and summary["written"] == 0
    assert summary["results"][0]["existing_topic"] == "feedback-issue-handling-sop"


def test_new_rule_is_written_without_the_raw_quote(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-3"
    words = "以后新增 host 脚本的时候，安装器清单和 --check 要一起改。"
    prompt(task, words)
    capture(env, task)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({
        "store": True, "kind": "preference", "summary": "新增 host 脚本要同步安装器清单",
        "conclusion": "新增 host 脚本时必须同步更新安装器清单和对应的自检",
        "slug": "feedback-host-script-installer", "scope": "engineering",
        "salience": "high", "publish": "private", "tags": ["host", "installer"],
        "confidence": 0.9, "reason": "明确要求", "existing_topic": None}))
    result = run(env, tmp_path, store, repo, "run", "--limit", "1", "--llm-response", str(reply))
    assert result.returncode == 0, result.stderr
    topic = (store / "feedback-host-script-installer.md").read_text(encoding="utf-8")
    assert "新增 host 脚本时必须同步更新安装器清单" in topic
    assert "安装器清单和 --check 要一起改" not in topic
    assert "publish: private" in topic and "scope: engineering" in topic
    assert "salience: high" in topic and "status: verified" in topic


def test_a_price_or_date_in_the_conclusion_is_rejected(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-4"
    prompt(task, "记住 RKLX 今天收盘 12.34 美元，减仓一半。")
    capture(env, task)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({
        "store": True, "kind": "rule", "summary": "RKLX 减仓",
        "conclusion": "2026-11-13 RKLX 收盘 12.34 美元，减仓一半",
        "slug": "feedback-rklx", "scope": "investment", "salience": "high",
        "publish": "private", "tags": [], "confidence": 0.9, "reason": "x",
        "existing_topic": None}))
    result = run(env, tmp_path, store, repo, "run", "--limit", "1", "--llm-response", str(reply))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["failed"] == 1 and summary["written"] == 0
    assert "contamination" in summary["results"][0]["error"]
    assert not (store / "feedback-rklx.md").exists()
    pending = queue_item(tmp_path, "verify-issues-4-dispatch.json")
    assert pending["attempts"] == 1 and "contamination" in pending["last_error"]


def test_a_public_rule_is_projected_immediately_and_capped_to_private_on_failure(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-5"
    prompt(task, "派活之前先查一遍共享记忆，有重复的规则就别再让我说一遍。")
    capture(env, task)
    reply = tmp_path / "reply.json"
    reply.write_text(json.dumps({
        "store": True, "kind": "rule", "summary": "派活前先查共享记忆",
        "conclusion": "派发任务前先查共享记忆里的既有规则，避免让 kcn 重复同一要求",
        "slug": "feedback-check-memory-before-dispatch", "scope": "engineering",
        "salience": "high", "publish": "public", "tags": ["dispatch", "memory"],
        "confidence": 0.95, "reason": "kcn 明确要求", "existing_topic": None}))
    result = run(env, tmp_path, store, repo, "run", "--limit", "1", "--llm-response", str(reply))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["written"] == 1 and summary["results"][0]["publish"] == "public"
    assert "派活前先查共享记忆" in (repo / "MEMORY.md").read_text(encoding="utf-8")
    check = subprocess.run([sys.executable, str(PUBLISH), "--check", "--repo", str(repo),
                            "--store", str(store)], env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr

    # A missing projection target cannot leave a public topic behind: the write is
    # downgraded to private and the topic stays searchable.
    task2 = tmp_path / "tasks/verify-issues-6"
    prompt(task2, "以后写发布脚本前先跑一遍 dry run。")
    capture(env, task2)
    reply2 = tmp_path / "reply2.json"
    reply2.write_text(json.dumps({
        "store": True, "kind": "rule", "summary": "发布前先 dry run",
        "conclusion": "写发布脚本前先跑一遍 dry run，再改真实输出",
        "slug": "feedback-dry-run-before-publish", "scope": "engineering",
        "salience": "high", "publish": "public", "tags": ["release"],
        "confidence": 0.95, "reason": "kcn 明确要求", "existing_topic": None}))
    no_repo = tmp_path / "no-repo"
    no_repo.write_text("not a directory", encoding="utf-8")
    result = run(env, tmp_path, store, no_repo, "run", "--limit", "1",
                 "--llm-response", str(reply2))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["written"] == 1 and summary["results"][0]["publish"] == "private"
    assert "projection_error" in summary["results"][0]
    topic = (store / "feedback-dry-run-before-publish.md").read_text(encoding="utf-8")
    assert "publish: private" in topic


def test_outcome_capture_includes_appended_instructions_and_the_report(tmp_path):
    store = make_store(tmp_path)
    repo = make_repo(tmp_path, store)
    env = env_for(tmp_path, store, repo)
    task = tmp_path / "tasks/verify-issues-7"
    prompt(task, "把 issues 都处理一下。")
    (task / "attempt1.prompt").write_text(
        "【追加指令 11-13 21:23】\n\n「不要信任 issue 本身的描述」\n", encoding="utf-8")
    (task / "result.env").write_text("STATE=ok\nOUTCOME=DONE\nNEEDS=none\n", encoding="utf-8")
    (task / "runner-summary.txt").write_text("修了 16 条，关了 2 条，证据在 PR 里。", encoding="utf-8")
    capture(env, task, "outcome")
    item = queue_item(tmp_path, "verify-issues-7-outcome.json")
    assert "把 issues 都处理一下" in item["user_words"]
    assert "不要信任 issue 本身的描述" in item["user_words"]
    assert item["result"]["OUTCOME"] == "DONE"
    assert "修了 16 条" in item["result"]["report"]

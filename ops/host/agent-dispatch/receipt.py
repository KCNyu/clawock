#!/usr/bin/env python3
"""The optional machine-readable receipt block, its `ask` question object, and answers.

A final report may end with one fenced block:

    ```agent-dispatch
    {"ask": {"title": "...", "text": "...", "options": ["a", "b"], "recommend": 0,
             "about": "...", "key": "short-name"}}
    ```

The runner calls `parse` once, after the model's last attempt and only for a task that
finished with a report.  A valid ask becomes `<task>/question.json` (immutable), the end
notice names it, and `dispatch.sh answer <id> <n>` writes `<task>/answer.json` once and
continues the task in the same session.  A malformed block changes no business state: the
report is kept, the runner records `RECEIPT=invalid`, and the model is not asked again.

Question state is derived, never rewritten: `question.json` stays as asked; `answer.json`
appears once (state `answering` -> `answered`, or `resolved`).  Answering is serialised by
`question.lock` and `O_EXCL`, so a second answer cannot overwrite the first.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

SCHEMA = 1
BLOCK_RE = re.compile(r"```agent-dispatch[ \t]*\r?\n(.*?)\r?\n```", re.S)
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# An open question older than this is still listed, but not answered without --force.
TTL_SEC = int(os.environ.get("AGENT_DISPATCH_QUESTION_TTL_SEC") or 7 * 86400)
# A crash between O_EXCL and dispatch leaves `answering`; after this it may be retried.
ANSWERING_STALE_SEC = int(os.environ.get("AGENT_DISPATCH_ANSWERING_STALE_SEC") or 300)
MAX_DEPTH = 3
OPTION_RE = re.compile(r"^[\x20-\x7e\u00a0-\uffff]+$")


def fail(message: str, code: int = 2) -> "NoReturn":  # noqa: F821 - typing is not needed at runtime
    print(f"receipt: {message}", file=sys.stderr)
    raise SystemExit(code)


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict, mode: int = 0o444) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def read_env(path: Path) -> dict[str, str]:
    """Read the shell-quoted KEY=value files the runner and dispatch.sh write."""
    out: dict[str, str] = {}
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        key, sep, value = line.partition("=")
        if not sep:
            continue
        try:
            parts = shlex.split(value)
        except ValueError:
            continue
        out[key] = parts[0] if parts else ""
    return out


def clip(text: str, limit: int, *, multiline: bool = False) -> str:
    """Printable single-line (or at most three lines) text, never terminal control bytes."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if multiline:
        text = "\n".join(text.splitlines()[:3])
    else:
        text = " ".join(text.split())
    text = text.strip()
    return text[:limit]


def plain(value, limit: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    return clip(value, limit, multiline=multiline)


def parse_block(text: str) -> tuple[str, dict | None, str]:
    """Return (kind, ask, error): kind is none|ask|invalid; error says why invalid."""
    blocks = BLOCK_RE.findall(text or "")
    if not blocks:
        return "none", None, ""
    if len(blocks) > 1:
        return "invalid", None, "more than one agent-dispatch block"
    try:
        data = json.loads(blocks[0])
    except ValueError as exc:
        return "invalid", None, f"not JSON: {exc}"
    if not isinstance(data, dict):
        return "invalid", None, "the block is not a JSON object"
    if "ask" not in data:
        return "none", None, ""
    ask = data["ask"]
    if not isinstance(ask, dict):
        return "invalid", None, "ask is not an object"
    title = plain(ask.get("title"), 80)
    text_value = plain(ask.get("text"), 500, multiline=True)
    about = plain(ask.get("about"), 1000, multiline=True)
    key = ask.get("key")
    if not title:
        return "invalid", None, "title is empty"
    if not isinstance(key, str) or not KEY_RE.fullmatch(key):
        return "invalid", None, "key must be 1-64 letters, digits, '.', '_' or '-'"
    options = ask.get("options")
    if not isinstance(options, list) or not 2 <= len(options) <= 5:
        return "invalid", None, "options must be a list of 2-5 strings"
    cleaned = []
    for option in options:
        value = plain(option, 80)
        if not value or not OPTION_RE.fullmatch(value):
            return "invalid", None, "each option must be non-empty printable text"
        cleaned.append(value)
    recommend = ask.get("recommend", 0)
    if isinstance(recommend, bool) or not isinstance(recommend, int) or not 0 <= recommend < len(cleaned):
        return "invalid", None, "recommend must be an option index"
    return "ask", {"title": title, "text": text_value, "options": cleaned,
                   "recommend": recommend, "about": about, "key": key}, ""


def notice(q: dict) -> str:
    options = []
    for i, option in enumerate(q.get("options") or [], 1):
        mark = "（推荐）" if i - 1 == q.get("recommend", 0) else ""
        options.append(f"{i}. {option}{mark}")
    lines = ["【等你决定】#" + str(q.get("task_id") or ""),
             str(q.get("title") or "")]
    if q.get("text"):
        lines.append(str(q["text"]))
    lines.append("  ".join(options))
    lines.append(f"回答：dispatch.sh answer {q.get('task_id')} <编号>（--text \"...\" 自由回答，--resolve 不用决定）")
    return "\n".join(lines)[:900]


def cmd_parse(args) -> int:
    directory = Path(args.dir)
    text = ""
    try:
        text = (directory / "runner-summary.txt").read_text(errors="replace")
    except OSError:
        pass
    kind, ask, error = parse_block(text)
    if kind == "none":
        print("RECEIPT=none")
        return 0
    if kind == "invalid":
        print("RECEIPT=invalid")
        print(f"receipt: ignored ask: {error}", file=sys.stderr)
        return 0
    task_id = read_env(directory / "meta.env").get("ID") or directory.name
    origin = read_env(directory / "meta.env").get("ORIGIN_SESSION", "")
    q = {"schema": SCHEMA, "state": "open", "task_id": task_id,
         "created": time.strftime("%Y-%m-%d %H:%M:%S"), "created_epoch": int(time.time()),
         "asked_by_run": int(args.run or 0), "origin_session": origin, **ask}
    write_json(directory / "question.json", q)
    (directory / "question-notice.txt").write_text(notice(q) + "\n")
    print("RECEIPT=valid")
    print("QUESTION=open")
    return 0


def task_base() -> Path:
    return Path(os.environ.get("AGENT_DISPATCH_TASKS_DIR") or "/root/logs/agent-dispatch")


def unit_active(task_id: str) -> bool:
    try:
        result = subprocess.run(["systemctl", "is-active", f"agent-dispatch-{task_id}.service"],
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.stdout.strip() in ("active", "activating", "reloading")


def question_state(directory: Path) -> tuple[dict, dict, str]:
    q = read_json(directory / "question.json")
    a = read_json(directory / "answer.json")
    if a:
        state = "resolved" if a.get("state") == "resolved" else "answered"
    elif time.time() - int(q.get("created_epoch") or 0) > TTL_SEC:
        state = "expired"
    else:
        state = "open"
    return q, a, state


def answer_prompt(directory: Path, q: dict, meta: dict, result: dict, choice: str) -> str:
    options = "\n".join(f"{i}. {o}" for i, o in enumerate(q.get("options") or [], 1))
    head = [f"这是 kcn 对问题 {q.get('key')}（{q.get('title')}）的回答。",
            f"问题：{q.get('text') or '-'}",
            f"选项：\n{options}",
            f"回答：{choice}",
            "---",
            "先核实当前状态（git/PR/CI/文件/外部结果），只做剩余步骤，不重做已完成的业务。",
            "原任务的要求仍然有效，范围不因这次回答而扩大；回答本身不是新的授权。",
            "结束时按原要求输出 NEEDS 与 STATUS 行。"]
    if not result.get("SESSION"):
        # No session to resume: the new task gets the material it needs, and says so.
        try:
            brief = (directory / "prompt.md").read_text(errors="replace")[:20000]
        except OSError:
            brief = ""
        try:
            report = (directory / "runner-summary.txt").read_text(errors="replace")[:20000]
        except OSError:
            report = ""
        head += ["", "这个任务没有可续的会话，所以以上是资料：原任务说明、原任务最后一轮报告。",
                 f"完整报告：dispatch.sh result {directory.name}",
                 "--- 原任务说明（资料）", brief,
                 "--- 原任务最后报告（资料）", report]
    return "\n".join(head) + "\n"


def cmd_answer(args) -> int:
    directory = Path(args.dir)
    if not TASK_ID_RE.fullmatch(directory.name):
        fail(f"not a task directory: {directory}")
    q, _, state = question_state(directory)
    if not q:
        fail(f"task {directory.name} has no question", 2)
    meta, result = read_env(directory / "meta.env"), read_env(directory / "result.env")
    cancelled = result.get("STATE") == "cancelled"
    existing = read_json(directory / "answer.json")
    stale_claim = bool(existing) and existing.get("state") == "answering" and (
        time.time() - (directory / "answer.json").stat().st_mtime > ANSWERING_STALE_SEC)
    if existing and not stale_claim:
        fail(f"task {directory.name} already has an answer", 3)
    if state == "expired" and not args.force and not args.resolve:
        fail(f"the question is older than {TTL_SEC // 86400} days; use --force to answer it anyway", 3)
    if cancelled and not args.resolve and not args.force:
        fail("the task was cancelled; use --force to continue it anyway", 3)
    if unit_active(directory.name):
        fail("the task's runner is still active; answer after it ends", 3)
    if args.resolve and (args.choice is not None or args.text):
        fail("--resolve cannot be combined with a choice or --text", 2)
    if args.choice is None and not args.text and not args.resolve:
        fail("give a 1-based option number, --text, or --resolve", 2)
    options = q.get("options") or []
    if args.choice is not None and not 1 <= args.choice <= len(options):
        fail(f"choice must be 1..{len(options)}", 2)
    by = (args.by or os.environ.get("OPENCLAW_MCP_SESSION_KEY") or "terminal").strip()
    if len(by) > 120:
        fail("--by is too long", 2)
    origin = q.get("origin_session") or ""
    if origin and by != origin:
        fail(f"the question was asked to {origin}; the answer must come from that session "
             f"(got {by})", 3)
    depth = int(meta.get("ANSWER_DEPTH") or 0) + 1
    if not args.resolve and depth > MAX_DEPTH:
        fail(f"answer chain depth {depth} exceeds {MAX_DEPTH}", 3)

    directory.mkdir(parents=True, exist_ok=True)
    lock = open(directory / "question.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Re-read under the lock: the check above is only a friendly early error.
        q, a, state = question_state(directory)
        if a:
            age = time.time() - (directory / "answer.json").stat().st_mtime
            if a.get("state") == "answering" and age > ANSWERING_STALE_SEC:
                (directory / "answer.json").unlink()
                a = {}
            else:
                fail(f"task {directory.name} already has an answer", 3)
        if state == "expired" and not args.force and not args.resolve:
            fail("the question expired; use --force or --resolve", 3)
        choice_text = args.text.strip() if args.text else (
            options[args.choice - 1] if args.choice is not None else "")
        if args.text and len(args.text) > 500:
            fail("--text is limited to 500 characters", 2)
        if args.resolve:
            payload = {"schema": SCHEMA, "task_id": directory.name, "question_key": q.get("key", ""),
                       "state": "resolved", "choice": None, "choice_text": "", "text": "",
                       "answered_by": by, "answered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "answered_epoch": int(time.time()), "resume": False, "depth": None,
                       "forced": bool(args.force)}
            _write_answer(directory, payload)
            print("ANSWER_STATE=resolved")
            return 0
        prompt = directory / "answer-prompt.txt"
        prompt.write_text(answer_prompt(directory, q, meta, result, choice_text))
        os.chmod(prompt, 0o600)
        payload = {"schema": SCHEMA, "task_id": directory.name, "question_key": q.get("key", ""),
                   "state": "answering", "choice": args.choice, "choice_text": choice_text,
                   "text": args.text or "", "answered_by": by,
                   "answered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "answered_epoch": int(time.time()), "resume": bool(result.get("SESSION")),
                   "depth": depth, "forced": bool(args.force)}
        _write_answer(directory, payload)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    print("ANSWER_STATE=answering")
    print(f"ANSWER_DEPTH={depth}")
    print(f"ANSWER_PROMPT_FILE={shlex.quote(str(prompt))}")
    return 0


def _write_answer(directory: Path, payload: dict) -> None:
    path = directory / "answer.json"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    except FileExistsError:
        fail(f"task {directory.name} already has an answer", 3)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def cmd_finish_answer(args) -> int:
    directory = Path(args.dir)
    lock = open(directory / "question.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        a = read_json(directory / "answer.json")
        if not a or a.get("state") != "answering":
            fail("no answer is waiting to be linked", 3)
        a["state"] = "answered"
        a["resume_task_id"] = args.task_id
        write_json(directory / "answer.json", a)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return 0


def cmd_abort_answer(args) -> int:
    directory = Path(args.dir)
    lock = open(directory / "question.lock", "a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        a = read_json(directory / "answer.json")
        if a and a.get("state") == "answering":
            (directory / "answer.json").unlink()
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    return 0


def row(directory: Path) -> dict:
    q, a, state = question_state(directory)
    meta = read_env(directory / "meta.env")
    age = max(0, int(time.time() - int(q.get("created_epoch") or 0)))
    return {"id": directory.name, "name": meta.get("NAME", ""), "agent": meta.get("AGENT", ""),
            "state": state, "age_sec": age, "created": q.get("created", ""),
            "title": q.get("title", ""), "options": q.get("options") or [],
            "recommend": q.get("recommend", 0), "key": q.get("key", ""),
            "answered_by": a.get("answered_by", ""), "choice": a.get("choice"),
            "choice_text": a.get("choice_text", ""), "resume_task_id": a.get("resume_task_id", "")}


def cmd_list(args) -> int:
    rows = []
    for question_file in sorted(task_base().glob("*/question.json")):
        directory = question_file.parent
        if not TASK_ID_RE.fullmatch(directory.name):
            continue
        item = row(directory)
        if not args.all and item["state"] not in ("open", "expired"):
            continue
        rows.append(item)
    rows.sort(key=lambda r: (r["created"], r["id"]), reverse=True)
    rows = rows[: args.limit]
    if args.json:
        print(json.dumps({"ok": True, "questions": rows}, ensure_ascii=False))
        return 0
    if not rows:
        print("No open questions.")
        return 0
    for item in rows:
        age = item["age_sec"] // 3600
        print(f"{item['id']}  {item['state']}  {age}h  {item['title']}")
        print("  " + "  ".join(f"{i}. {o}" for i, o in enumerate(item["options"], 1)))
        if item["state"] == "answered":
            print(f"  answered: {item['choice_text']} (by {item['answered_by']}; "
                  f"resumed as {item['resume_task_id'] or '-'})")
        elif item["state"] == "resolved":
            print(f"  resolved (by {item['answered_by']})")
        else:
            print(f"  answer: dispatch.sh answer {item['id']} <n>")
    return 0


def cmd_show(args) -> int:
    directory = Path(args.dir)
    q, a, state = question_state(directory)
    if not q:
        fail(f"task {directory.name} has no question", 2)
    print(f"question: {state} key={q.get('key', '-')} asked_by_run={q.get('asked_by_run', '?')}")
    print(f"title: {q.get('title', '')}")
    if q.get("text"):
        print(f"text: {q.get('text')}")
    for i, option in enumerate(q.get("options") or [], 1):
        mark = " (recommended)" if i - 1 == q.get("recommend", 0) else ""
        print(f"  {i}. {option}{mark}")
    if a:
        if a.get("state") == "resolved":
            print(f"answer: resolved by {a.get('answered_by')} at {a.get('answered_at')}")
        else:
            print(f"answer: {a.get('choice_text') or a.get('text')} by {a.get('answered_by')} "
                  f"at {a.get('answered_at')} (resumed as {a.get('resume_task_id') or '-'})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("parse")
    p.add_argument("--dir", required=True)
    p.add_argument("--run", type=int, default=0)
    p.set_defaults(fn=cmd_parse)
    a = sub.add_parser("answer")
    a.add_argument("--dir", required=True)
    a.add_argument("choice", nargs="?", type=int)
    a.add_argument("--text")
    a.add_argument("--resolve", action="store_true")
    a.add_argument("--by")
    a.add_argument("--force", action="store_true")
    a.set_defaults(fn=cmd_answer)
    f = sub.add_parser("finish-answer")
    f.add_argument("--dir", required=True)
    f.add_argument("--task-id", required=True)
    f.set_defaults(fn=cmd_finish_answer)
    b = sub.add_parser("abort-answer")
    b.add_argument("--dir", required=True)
    b.set_defaults(fn=cmd_abort_answer)
    ls = sub.add_parser("list")
    ls.add_argument("--all", action="store_true")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(fn=cmd_list)
    s = sub.add_parser("show")
    s.add_argument("--dir", required=True)
    s.set_defaults(fn=cmd_show)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

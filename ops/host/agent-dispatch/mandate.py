#!/usr/bin/env python3
"""Machine-readable authorization for one dispatched task.

A dispatch creates ``<task dir>/mandate.json`` once, before the runner starts.  It
records the task's policy version, scope, source and the host actions the task may
take.  Host scripts that act outside the task directory (``ops/host/refresh_live.sh``,
``ops/host/restart_gateway.sh``) ask this file first; a denial is appended to
``<task dir>/mandate-violations.jsonl`` and the script exits non-zero.  The file is
an audit record and a guard for the host scripts we own, not a sandbox: a task that
runs an arbitrary program by absolute path is still outside it, exactly as the
external prototype documents for its own wrappers.

Usage:
  mandate.py create --dir DIR --task-id ID --name NAME --agent AGENT --cwd DIR \\
      --policy-version V --source-kind chat|terminal|task|patrol [--source-id ID] \\
      [--notify weixin,telegram] [--deny-restart] [--root /root]
  mandate.py show --file mandate.json
  mandate.py check --file mandate.json --action gateway.restart [--task-dir DIR] \\
      [--source refresh_live.sh] [--json]
  mandate.py violations --file mandate.json

Exit codes for check: 0 allowed, 3 denied (and recorded), 2 unreadable or invalid
mandate (never treated as allowed).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NoReturn

SCHEMA = 1
ACTIONS = ("gateway.restart", "live.refresh")
ACTION_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
SOURCE_KINDS = ("chat", "terminal", "task", "patrol")
STRENGTH = {"chat": "explicit", "terminal": "explicit", "task": "explicit", "patrol": "inferred"}
CONTRACT = "docs/architecture/task-queue.md#mandate"


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def fail(message: str, code: int = 2) -> NoReturn:
    print(f"mandate: {message}", file=sys.stderr)
    raise SystemExit(code)


def write_json(path: Path, payload: dict, mode: int = 0o444) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        fail(f"cannot read {path}: {exc}")
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        fail(f"{path}: unsupported mandate schema")
    actions = data.get("actions")
    if not isinstance(actions, dict) or any(
            not isinstance(k, str) or v not in ("allow", "deny") for k, v in actions.items()):
        fail(f"{path}: actions must map action names to allow|deny")
    return data


def cmd_create(args: argparse.Namespace) -> int:
    if args.source_kind not in SOURCE_KINDS:
        fail(f"--source-kind takes {', '.join(SOURCE_KINDS)}")
    directory = Path(args.dir)
    if not directory.is_dir():
        fail(f"--dir is not a directory: {directory}")
    path = directory / "mandate.json"
    if path.exists():
        fail(f"{path} already exists; a mandate is immutable (create a new task)")
    actions = {action: "allow" for action in ACTIONS}
    if args.deny_restart:
        actions["gateway.restart"] = "deny"
    notify = [part.strip().lower() for part in args.notify.split(",") if part.strip()]
    notify = [part for part in notify if part != "none"]
    payload = {
        "schema": SCHEMA,
        "task_id": args.task_id,
        "name": args.name,
        "agent": args.agent,
        "created": now(),
        "policy_version": args.policy_version,
        "strength": STRENGTH[args.source_kind],
        "source": {"kind": args.source_kind, "id": args.source_id or ""},
        "scope": {"cwd": args.cwd, "root": args.root, "repos": []},
        "actions": actions,
        "notify": {"on": "human-action", "channels": notify},
        "contract": CONTRACT,
    }
    write_json(path, payload)
    print(json.dumps({"ok": True, "file": str(path), "actions": actions}, sort_keys=True))
    return 0


def record_violation(directory: Path, data: dict, action: str, source: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "mandate-violations.jsonl"
    entry = {
        "at": now(),
        "task_id": data.get("task_id", ""),
        "policy_version": data.get("policy_version", ""),
        "action": action,
        "decision": "deny",
        "source": source,
        "pid": os.getpid(),
        "cwd": os.getcwd(),
    }
    line = json.dumps(entry, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)
    return path


def cmd_check(args: argparse.Namespace) -> int:
    if not ACTION_RE.fullmatch(args.action):
        fail(f"--action is not a known action name: {args.action!r}", 2)
    path = Path(args.file)
    data = load(path)
    decision = data["actions"].get(args.action, "deny")
    allowed = decision == "allow"
    violation = None
    if not allowed:
        directory = Path(args.task_dir) if args.task_dir else path.parent
        violation = record_violation(directory, data, args.action, args.source)
        print(f"mandate: deny {args.action} for {data.get('task_id') or path} "
              f"(source {args.source}); recorded in {violation}", file=sys.stderr)
    if args.json:
        print(json.dumps({
            "ok": True,
            "allow": allowed,
            "decision": decision,
            "action": args.action,
            "task_id": data.get("task_id", ""),
            "policy_version": data.get("policy_version", ""),
            "violation": str(violation) if violation else None,
        }, sort_keys=True))
    else:
        print("allow" if allowed else "deny")
    return 0 if allowed else 3


def cmd_show(args: argparse.Namespace) -> int:
    data = load(Path(args.file))
    print(json.dumps(data, indent=2, sort_keys=True))
    return 0


def cmd_violations(args: argparse.Namespace) -> int:
    path = Path(args.file).parent / "mandate-violations.jsonl"
    try:
        print(path.read_text(), end="")
    except FileNotFoundError:
        return 0
    except OSError as exc:
        fail(f"cannot read {path}: {exc}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="write the immutable mandate for a new task")
    create.add_argument("--dir", required=True)
    create.add_argument("--task-id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--agent", required=True)
    create.add_argument("--cwd", required=True)
    create.add_argument("--policy-version", required=True)
    create.add_argument("--source-kind", required=True)
    create.add_argument("--source-id", default="")
    create.add_argument("--notify", default="")
    create.add_argument("--deny-restart", action="store_true")
    create.add_argument("--root", default="/root")
    create.set_defaults(func=cmd_create)

    show = sub.add_parser("show", help="print a mandate")
    show.add_argument("--file", required=True)
    show.set_defaults(func=cmd_show)

    check = sub.add_parser("check", help="allow or deny one action, recording a denial")
    check.add_argument("--file", required=True)
    check.add_argument("--action", required=True)
    check.add_argument("--task-dir", default="")
    check.add_argument("--source", default="mandate.py")
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

    violations = sub.add_parser("violations", help="print recorded denials")
    violations.add_argument("--file", required=True)
    violations.set_defaults(func=cmd_violations)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

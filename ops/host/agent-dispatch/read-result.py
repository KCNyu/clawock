#!/usr/bin/env python3
"""Read the latest attempt's final report without dumping its transcript."""
import argparse
import json
import shlex
import re
import sys
from pathlib import Path


def read_result(directory: Path, run: int | None = None) -> str:
    attempts = []
    for path in directory.glob("attempt*.*"):
        match = re.fullmatch(r"attempt(\d+)\.(json|jsonl)", path.name)
        if match and (run is None or int(match[1]) == run):
            attempts.append((int(match[1]), path))
    if not attempts:
        raise ValueError("No attempt has produced a report yet.")
    _, path = max(attempts, key=lambda pair: pair[0])
    if path.suffix == ".json":
        # An interrupted Claude JSON file may be incomplete. Never fall back to
        # an earlier successful attempt and present it as the latest outcome.
        result = json.loads(path.read_text()).get("result")
        if isinstance(result, str) and result.strip():
            return result
    else:
        messages = {}
        last = None
        completed = False
        for line in path.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    last = item.get("text", "")
            elif event.get("type") == "text":
                part = event.get("part", {})
                mid = part.get("messageID", "")
                messages.setdefault(mid, []).append(part.get("text", ""))
                last = "".join(messages[mid])
            elif event.get("type") == "turn.completed":
                completed = True
            elif event.get("type") == "step_finish" and event.get("part", {}).get("reason") == "stop":
                completed = True
        if completed and last and last.strip():
            return last
    raise ValueError("The latest attempt has no report; inspect status for running/error state.")


def read_env(path: Path) -> dict:
    """Read scalar shell-quoted metadata without executing it."""
    result = {}
    try:
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep:
                try:
                    parts = shlex.split(value)
                    result[key] = parts[0] if parts else ""
                except ValueError:
                    pass
    except OSError:
        pass
    return result


def notification(meta: dict, state: dict) -> str:
    if meta.get("NOTIFY") == "none":
        return "disabled"
    sent, failed = state.get("NOTIFIED", ""), state.get("NOTIFY_FAILED", "")
    if failed:
        return f"{'partial_failure' if sent else 'failed'} (sent={sent or '-'} failed={failed})"
    if sent:
        return f"send_succeeded ({sent}; receipt/read not confirmed)"
    return "unknown"


def report(directory: Path, run: int | None = None) -> str:
    meta, state = read_env(directory / "meta.env"), read_env(directory / "result.env")
    if run is None and state.get("STATE") in ("running", "queued", "waiting"):
        raise ValueError("Task has no terminal result yet; use status if needed.")
    latest = max((int(m[1]) for p in directory.glob("attempt*.*")
                  if (m := re.fullmatch(r"attempt(\d+)\.(json|jsonl)", p.name))), default=0)
    lines = [f"task_id: {directory.name}", f"run_no: {run if run is not None else latest}",
             f"task_state: {state.get('STATE', 'unknown')} / outcome: {state.get('OUTCOME') or 'unknown'}",
             f"attempt_budget_used: {state.get('ATTEMPTS', '?')}/{state.get('MAX_ATTEMPTS', '?')}",
             f"quota_waits_scheduled: {state.get('QUOTA_RESUMES_USED', '?')}/{state.get('QUOTA_RESUMES', '?')}",
             f"deadline_epoch: {state.get('DEADLINE_EPOCH', meta.get('DEADLINE_EPOCH', '?'))}",
             f"stop_reason: {state.get('STOP_REASON') or state.get('FAILURE_REASON') or 'unknown'}",
             f"finished_epoch: {state.get('FINISHED_EPOCH') or 'unknown'}",
             f"parent_task_id: {meta.get('PARENT_TASK_ID') or '-'}",
             f"notification: {notification(meta, state)}",
             f"notification_latest_at: {state.get('NOTIFY_AT') or 'unknown'}"]
    for event in ("quota", "end"):
        try:
            wake = json.loads((directory / f"wake-{event}.json").read_text())
            lines.append(f"wake_{event}: {json.dumps(wake, ensure_ascii=False)}")
        except (OSError, ValueError):
            pass
    if run is not None:
        lines.append("Historical model report; fields above describe the task's latest state.")
    model_text = ""
    try:
        model_text = read_result(directory, run)
    except (OSError, ValueError) as error:
        if run is not None:
            raise
        lines.append(f"model_report_unavailable: {error}")
    if run is None and (directory / "runner-summary.txt").exists():
        summary = (directory / "runner-summary.txt").read_text()
        if summary.strip() != model_text.strip():
            lines += ["--- runner summary", summary]
    if model_text:
        lines += ["--- model report", model_text]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--run", type=int)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.task_id):
        parser.error("invalid task id")
    directory = Path("/root/logs/agent-dispatch") / args.task_id
    try:
        if not directory.is_dir():
            raise ValueError("No such task.")
        print(report(directory, args.run))
    except (OSError, ValueError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()

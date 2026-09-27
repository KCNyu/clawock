#!/usr/bin/env python3
"""Read the latest attempt's final report without dumping its transcript."""
import json
import re
import sys
from pathlib import Path


def read_result(directory: Path) -> str:
    attempts = []
    for path in directory.glob("attempt*.*"):
        match = re.fullmatch(r"attempt(\d+)\.(json|jsonl)", path.name)
        if match:
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


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", sys.argv[1]):
        sys.exit("usage: dispatch.sh result <task-id>")
    directory = Path("/root/logs/agent-dispatch") / sys.argv[1]
    try:
        # The state file may say 'running' after a crash. Refuse rather than
        # accidentally treat an intermediate assistant message as a final report.
        state = (directory / "result.env").read_text()
        if re.search(r"^STATE=(running|queued|waiting)$", state, re.M):
            raise ValueError("Task has no terminal result yet; use status if needed.")
        print(read_result(directory))
    except (OSError, ValueError) as error:
        sys.exit(str(error))


if __name__ == "__main__":
    main()

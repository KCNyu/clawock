#!/usr/bin/env python3
"""Find a Claude Code session that dispatch did not start, for `dispatch.sh adopt`.

    claude-session.py resolve <ref> --agents-json <file>

<ref> is a native background session's short id (what `claude --bg` prints), a session id, or
an unambiguous session-id prefix of at least 8 characters. <file> holds the output of
`claude agents --json` (every live interactive, headless and background claude process); an
empty or unreadable file means nobody could tell, and the session is not adopted.

Prints shell assignments for dispatch.sh, or one line on stderr and exit 2:

    SESSION  CWD  TRANSCRIPT       the session, the directory to resume it from, its record
    BG_ID  BG_STATE  BG_DETAIL     the background job, when the session is one
    LIVE_KIND  LIVE_PID  LIVE_STATE  a process that has the session open now
    LIMIT_TEXT  LIMIT_AT           the usage-limit refusal the session last stopped on, if any
    ACTION                         resume | stop-then-resume

Why adopting at all (claude 2.1.303, docs/architecture/task-queue.md § Native background
sessions): the CLI's own "continuing automatically at <reset>" only runs in a live interactive
process that is not a background session, and the daemon retires a settled background session
when memory is low. A session stopped by its usage limit is resumed at the reset only by the
runner's quota wait, so a session started outside dispatch needs to be handed to it.
"""
import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path


class Refused(Exception):
    pass


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or "/root/.claude")


def project_key(cwd: str) -> str:
    # How Claude Code names a project's transcript directory: /root/.openclaw/workspace is
    # projects/-root--openclaw-workspace.
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


def read_jobs(home: Path) -> list[dict]:
    jobs = []
    for path in sorted(home.glob("jobs/*/state.json")):
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(state, dict) and state.get("sessionId"):
            jobs.append({**state, "_id": state.get("daemonShort") or path.parent.name})
    return jobs


def find_session(ref: str, home: Path, jobs: list[dict]) -> tuple[str, dict | None]:
    if not re.fullmatch(r"[0-9a-f-]{8,36}", ref):
        raise Refused(f"'{ref}' is not a background session id or a session id")
    matches = {job["sessionId"] for job in jobs if ref in (job["_id"], job["sessionId"])}
    if not matches:
        matches = {p.stem for p in home.glob(f"projects/*/{ref}*.jsonl")}
    if not matches:
        raise Refused(f"no claude session or background session '{ref}' on this host")
    if len(matches) > 1:
        raise Refused(f"'{ref}' matches {len(matches)} sessions; give the whole session id")
    sid = matches.pop()
    job = next((j for j in jobs if j["sessionId"] == sid), None)
    return sid, job


def scan_transcript(path: Path) -> tuple[list[str], str, str]:
    """The directories the session was in, in order, and the usage-limit refusal it stopped on."""
    cwds, limit_text, limit_at = [], "", ""
    with path.open(errors="replace") as fh:
        for line in fh:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            cwd = event.get("cwd")
            if isinstance(cwd, str) and cwd and cwd not in cwds:
                cwds.append(cwd)
            if event.get("type") != "assistant":
                continue
            # Only the latest assistant entry counts: a refusal followed by real work is history.
            limit_text = limit_at = ""
            if event.get("isApiErrorMessage") and event.get("error") == "rate_limit":
                content = (event.get("message") or {}).get("content") or []
                texts = [c.get("text", "") for c in content if isinstance(c, dict)]
                limit_text = " ".join(t for t in texts if t).strip()
                limit_at = event.get("timestamp") or ""
    return cwds, limit_text, limit_at


def resolve(ref: str, agents_json: Path) -> dict:
    home = claude_home()
    jobs = read_jobs(home)
    sid, job = find_session(ref, home, jobs)
    transcripts = sorted(home.glob(f"projects/*/{sid}.jsonl"))
    if not transcripts:
        raise Refused(f"session {sid} has no transcript yet; there is nothing to resume")
    if len(transcripts) > 1:
        raise Refused(f"session {sid} has transcripts in {len(transcripts)} projects; resume it by hand")
    transcript = transcripts[0]
    cwds, limit_text, limit_at = scan_transcript(transcript)
    # `claude --resume` finds a session through the directory it runs in, and a transcript's
    # cwd field follows the session's shell (`cd` into a worktree), so the directory is the
    # recorded one whose name is the transcript's project.
    candidates = ([job["cwd"]] if job and job.get("cwd") else []) + cwds
    cwd = next((c for c in candidates if project_key(c) == transcript.parent.name), None)
    if cwd is None:
        raise Refused(f"cannot tell which directory session {sid} was started in ({transcript.parent.name})")
    if not Path(cwd).is_dir():
        raise Refused(f"session {sid} was started in {cwd}, which no longer exists")

    try:
        agents = json.loads(agents_json.read_text())
        if not isinstance(agents, list):
            raise ValueError
    except (OSError, ValueError):
        raise Refused("`claude agents --json` gave no answer, so nobody can tell whether the session is open somewhere")
    live = next((a for a in agents if isinstance(a, dict) and a.get("sessionId") == sid and a.get("pid")), None)

    out = {
        "SESSION": sid, "CWD": cwd, "TRANSCRIPT": str(transcript),
        "BG_ID": job["_id"] if job else "", "BG_STATE": (job or {}).get("state") or "",
        "BG_DETAIL": (job or {}).get("detail") or "",
        "LIVE_KIND": "", "LIVE_PID": "", "LIVE_STATE": "",
        "LIMIT_TEXT": limit_text, "LIMIT_AT": limit_at, "ACTION": "resume",
    }
    if live:
        out.update(LIVE_KIND=live.get("kind") or "", LIVE_PID=str(live.get("pid")),
                   LIVE_STATE=live.get("state") or live.get("status") or "")
        if live.get("kind") != "background":
            # An interactive terminal, or the headless `claude -p` of a dispatched task: two
            # writers on one transcript. Stopping somebody's terminal is not this command's call.
            raise Refused(f"session {sid} is open in a running claude process (pid {live.get('pid')}, "
                          f"{live.get('kind') or 'unknown kind'}); exit it first, or append to its task")
        if live.get("state") == "working":
            raise Refused(f"background session {out['BG_ID'] or live.get('id')} is still working; "
                          "adopt it once it is blocked, idle or stopped")
        if not out["BG_ID"]:
            out["BG_ID"] = live.get("id") or ""
        if not out["BG_ID"]:
            raise Refused(f"session {sid} runs in the background under an unknown id")
        out["ACTION"] = "stop-then-resume"
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    res = sub.add_parser("resolve")
    res.add_argument("ref")
    res.add_argument("--agents-json", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        out = resolve(args.ref, args.agents_json)
    except Refused as exc:
        print(f"adopt: {exc}", file=sys.stderr)
        return 2
    for key, value in out.items():
        print(f"{key}={shlex.quote(value)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

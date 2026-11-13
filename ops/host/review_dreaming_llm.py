#!/usr/bin/env python3
"""Model reviewer for the 03:20 dreaming gate.

`review_dreaming.py` is the authority: it is deterministic, hash-bound and fails
closed. It will not approve anything by itself — that was the missing half, so every
night since 2026-11-08 produced approved=0. This script reads the same private
candidates and writes the receipt the gate already understands.

It can only make the gate stricter, never looser:

  * a candidate the deterministic rules reject is never sent to the model;
  * a receipt is bound to the exact candidate SHA256;
  * the model's conclusion is re-screened with the same contamination rules and a
    malformed/unsafe conclusion is dropped, leaving the candidate pending;
  * a source is still accepted at most once (the gate re-checks this);
  * every receipt says `llm:<model>`; a model outage writes nothing.

The model sees public-source candidate text and existing public topic descriptions,
not the private store.
"""
from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import sys

HOST = Path(__file__).resolve().parent
sys.path.insert(0, str(HOST))
sys.path.insert(0, str(HOST / "shared-memory" / "scripts"))

import review_dreaming as gate  # noqa: E402
import llm_json  # noqa: E402

DEFAULT_STORE = Path(os.environ.get("SHARED_MEMORY_DIR", "~/.shared-memory")).expanduser()
SCOPES = ("engineering", "investment", "persona", "memory")
SALIENCE = ("high", "normal")


class ReviewError(RuntimeError):
    pass


def load_candidates(workspace: Path, approvals: dict) -> tuple[list[dict], list[dict]]:
    private = workspace / "memory/.dreams"
    candidates = ""
    for name in ("promotion-candidates.md", "legacy-promotion-candidates.md"):
        path = private / name
        if path.exists():
            candidates += path.read_text(encoding="utf-8") + "\n"
    memory = (workspace / "MEMORY.md").read_text(encoding="utf-8")
    _, report = gate.review(memory, candidates, approvals)
    pending = []
    seen_sources = set()
    for entry in report:
        if entry["decision"] != "pending" or entry["key"] in approvals:
            continue
        if entry.get("invalid") or gate.reasons(entry["text"]):
            continue
        if "source_already_accepted" in entry.get("reasons", []):
            continue
        # The gate accepts one conclusion per source. Review the first candidate
        # from each source; the rest stay pending behind source_already_accepted.
        if entry["source"] in seen_sources:
            continue
        seen_sources.add(entry["source"])
        pending.append(entry)
    return pending, report


def topic_catalogue(store: Path) -> str:
    rows = []
    if not store.is_dir():
        return ""
    for path in sorted(store.glob("*.md")):
        if path.name == "MEMORY.md":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        match = re.match(r"^---\n([\s\S]*?)\n---\n?", text)
        head = match.group(1) if match else ""
        description = ""
        publish = "private"
        for line in head.splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "description":
                description = value.strip().strip("'\"")
            elif key.strip() == "publish":
                publish = value.strip().strip("'\"")
        if description and publish == "public":
            rows.append(f"- {path.stem}: {description[:180]}")
    return "\n".join(rows[:80])


def prompt_for(entries: list[dict], catalogue: str) -> str:
    payload = [{"key": entry["key"], "source": entry["source"],
                "text": entry["text"][:900]} for entry in entries]
    return f"""你是 Rick 的 dreaming 审阅者。下面是 03:00 dreaming 产出的候选结论。每条都来自公开工作区里的简报/日记；确定性过滤器已经拒绝了含 HTML、价格/仓位、日期、路径或任务元数据的条目。现在只判断：它是否包含一条**跨日期可复用、会改变未来行为**的结论。

通过的标准：
- 是一条规则、偏好、定义或可复用教训，不是某一天的行情/判断/流水账；
- 去掉日期和上下文后仍然自足；
- 不与现有 topic 重复；
- 不包含价格、仓位动作、HTML、文件路径、task/session id。

拒绝掉：一次性任务、当天的市场判断、某次运行的状态、含糊的口号、只是在复述简报。

现有 public topic：
{catalogue or '(none)'}

候选（JSON）：
{json.dumps(payload, ensure_ascii=False)}

只输出一个 JSON 数组，每个候选一个对象，顺序不限：
[{{"key":"...", "decision":"approve|reject", "conclusion":"一行中文结论，<=200字，不含日期/价格/路径/HTML", "scope":"engineering|investment|persona|memory", "salience":"high|normal", "reason":"一句话说明为什么可复用"}}]
不要输出 Markdown。"""


def validate(reply, entries: list[dict]) -> dict[str, dict]:
    if not isinstance(reply, list):
        raise ReviewError("model reply is not an array")
    by_key = {entry["key"]: entry for entry in entries}
    accepted: dict[str, dict] = {}
    for item in reply:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "")
        entry = by_key.get(key)
        if entry is None or key in accepted:
            continue
        if str(item.get("decision")).lower() != "approve":
            continue
        conclusion = str(item.get("conclusion") or "").strip()
        reason = str(item.get("reason") or "").strip()
        scope = str(item.get("scope") or "").lower()
        salience = str(item.get("salience") or "normal").lower()
        if (not conclusion or len(conclusion) > 240 or "\n" in conclusion
                or gate.reasons(conclusion) or "<!--" in conclusion
                or conclusion.startswith("#") or "`clawock" in conclusion):
            continue
        if scope not in SCOPES or salience not in SALIENCE or not reason:
            continue
        accepted[key] = {
            "sha256": entry["sha256"],
            "reviewer": f"llm:{llm_json.model()}",
            "reviewed_on": date.today().isoformat(),
            "rationale": reason[:300],
            "durable": True,
            "conclusion": conclusion,
            "scope": scope,
            "salience": salience,
        }
    return accepted


def write_approvals(path: Path, approvals: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(json.dumps(approvals, ensure_ascii=False, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--check", action="store_true", help="report only; write no receipts")
    parser.add_argument("--llm-response", type=Path, help="read one fake model reply (tests)")
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    store = args.store.expanduser().resolve()
    approvals_path = workspace / "memory/.dreams/promotion-approvals.json"
    approvals = json.loads(approvals_path.read_text(encoding="utf-8")) if approvals_path.exists() else {}
    if not isinstance(approvals, dict):
        raise ReviewError("promotion-approvals.json must be an object")
    pending, report = load_candidates(workspace, approvals)
    chosen = pending[:max(0, args.limit)]
    summary = {"pending": len(pending), "sent": len(chosen), "approved": 0, "rejected": 0,
               "already_approved": sum(1 for entry in report if entry["decision"] == "approved")}
    if not chosen:
        print(json.dumps({**summary, "decisions": []}, ensure_ascii=False))
        return 0
    text = (args.llm_response.read_text(encoding="utf-8") if args.llm_response
            else llm_json.run_model(prompt_for(chosen, topic_catalogue(store))))
    accepted = validate(llm_json.extract_json(text), chosen)
    summary["approved"] = len(accepted)
    summary["rejected"] = len(chosen) - len(accepted)
    if args.check:
        print(json.dumps({**summary, "decisions": [
            {"key": key, "conclusion": value["conclusion"], "scope": value["scope"],
             "salience": value["salience"]} for key, value in accepted.items()]}, ensure_ascii=False))
        return 0
    if accepted:
        approvals.update(accepted)
        write_approvals(approvals_path, approvals)
    print(json.dumps({**summary, "keys": sorted(accepted)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReviewError, llm_json.LLMError, OSError, ValueError) as exc:
        print(f"review_dreaming_llm: {exc}", file=sys.stderr)
        raise SystemExit(1)

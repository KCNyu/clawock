#!/usr/bin/env python3
"""What patrol learned from its own issues, rendered into the next round's prompt (2026-10-01).

  patrol_intel.py brief --axis <axis> [--since '<YYYY-MM-DD HH:MM:SS>']
      prints the round prompt's「反馈与提报」block and rewrites feedback.json (the categories the
      gate demotes). The supervisor runs it before every dispatch; failure leaves a one-line note.
  patrol_intel.py round-yield --task <task id>
      prints what one round routed, e.g. `P1#2240 P2#2241 +1 digest +1 comment`, for rounds.tsv.

Three loops, each borrowed from a tool that already runs one:
- precision per detector (CodeQL query precision + dismissal reasons): every lens's recent issues
  counted as fixed / noise (closed not planned, or labelled patrol:noise/duplicate/invalid/
  wontfix); an (area, kind) pair closed as noise 3+ times in 14 days is classified as P3
  by the gate until it stops being closed that way;
- regression detection (Sentry's resolved → regressed): a fixed patrol issue kept its RED-CHECK
  in the draft; when a commit in the recent window touches a file that issue cited, the recent
  round is told to re-run that exact check (it must stay green);
- filing history: recent severity counts and legacy pending entries, without count ceilings.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage  # noqa: E402

LOGDIR = Path(os.environ.get("PATROL_STATE", "/root/logs/clawock-patrol"))
WORK = Path(os.environ.get("PATROL_WORKTREE", "/root/wt-patrol"))
REPO = "KCNyu/clawock"
WINDOW_S = 14 * 86400
RED_BLOCK = re.compile(r"<!--\s*RED-CHECK\s*\n(.*?)\n\s*-->", re.S)
FILE_REF = re.compile(r"((?:[\w.\-]+/)+[\w.\-]+\.(?:py|js|ts|json|jsonl|ya?ml|sh|md|css|html|toml))[:：]\d+")


def _ts(iso):
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (TypeError, ValueError):
        return 0


def _local_ts(stamp):
    try:
        return time.mktime(time.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError):
        return time.time()


def load_issues(path=None):
    """Patrol issues with labels and close reasons (a file for tests, else gh)."""
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    r = subprocess.run(["gh", "issue", "list", "-R", REPO, "--state", "all", "--limit", "400",
                        "--search", "\"[patrol]\" in:title sort:created-desc",
                        "--json", "number,title,state,stateReason,labels,createdAt,closedAt"],
                       capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[-200:])
    return json.loads(r.stdout)


def task_by_issue():
    """issue number → (task id, draft name) from created.tsv (every gated issue since 09-17)."""
    out = {}
    try:
        for line in (LOGDIR / "filed" / "created.tsv").read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            m = re.search(r"/issues/(\d+)", f[3]) if len(f) > 4 else None
            if m:
                out[int(m.group(1))] = (f[4], f[1])
    except OSError:
        pass
    return out


def classify(issue, tasks):
    labels = {l["name"] if isinstance(l, dict) else l for l in issue.get("labels") or []}
    pick = lambda prefix: next((l.split(":", 1)[1] for l in labels if l.startswith(prefix + ":")), "")
    guess = triage.infer(issue.get("title", ""), "")
    lens = pick("lens") or triage.lens_of(tasks.get(issue["number"], ("", ""))[0])
    noise = (issue.get("stateReason") in triage.NOISE_REASONS) or bool(labels & triage.NOISE_LABELS)
    return {
        "number": issue["number"], "title": issue.get("title", ""), "lens": lens,
        "area": pick("area") or guess["area"], "kind": pick("kind") or guess["kind"],
        "severity": pick("severity") or "", "digest": triage.DIGEST_LABEL in labels,
        "labelled": bool(pick("area") and pick("kind")),
        "state": issue.get("state"), "noise": noise, "fixed": issue.get("state") == "CLOSED" and not noise,
        "created": _ts(issue.get("createdAt")), "closed": _ts(issue.get("closedAt")),
    }


def feedback(rows, now):
    recent = [r for r in rows if now - r["created"] < WINDOW_S and not r["digest"]]
    per_lens = defaultdict(Counter)
    for r in recent:
        c = per_lens[r["lens"]]
        c["filed"] += 1
        c["fixed"] += r["fixed"]
        c["noise"] += r["noise"]
        c["open"] += r["state"] == "OPEN"
    # Only labelled issues count toward a demotion: the keyword guess is good enough to describe
    # history, not to silence a category (an inferred `ops/bug` is where every unknown lands).
    noise_pairs = Counter((r["area"], r["kind"]) for r in rows
                          if r["noise"] and r["labelled"] and now - r["closed"] < WINDOW_S)
    noisy = sorted(pair for pair, n in noise_pairs.items() if n >= 3)
    lessons = sorted((r for r in rows if r["noise"] and now - r["closed"] < WINDOW_S), key=lambda r: -r["closed"])[:6]
    return per_lens, noisy, lessons


def filing_line(now):
    index = triage.read_jsonl(LOGDIR / "filed" / "index.jsonl")
    day = [r for r in index if r.get("route") == "issue" and now - r.get("ts", 0) < 86400]
    by = Counter(r.get("severity") for r in day)
    pending = len(triage.read_jsonl(LOGDIR / "digest" / "pending.jsonl"))
    return (f"- 24 小时内单独开了 {len(day)} 条（P0 {by['P0']} / P1 {by['P1']} / "
            f"P2 {by['P2']} / P3 {by['P3']}）；提报数量不限。"
            "各级发现都按证据和严重度提报，同根因补充到已有 issue；功能提案没有周数量上限。"
            f"旧汇总待发 {pending} 条，下次收尾立即提报，不等待数量或年龄门槛。")


def regression_watch(rows, since, tasks, limit=6):
    """Fixed issues whose cited files changed in the recent window, with their saved RED-CHECK."""
    if not since:
        return []
    r = subprocess.run(["git", "-C", str(WORK), "log", f"--since={since}", "--first-parent", "--name-only",
                        "--format=@%h", "origin/master"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return []
    touched, sha = {}, ""
    for line in r.stdout.splitlines():
        if line.startswith("@"):
            sha = line[1:]
        # Runtime data commits and test edits cannot undo a fix (a test change is the fix's own guard
        # being edited; the recent round reviews that diff anyway), so they do not trigger a re-run.
        elif line.strip() and not line.startswith(("assets/data/", "memory/", "tests/")):
            touched.setdefault(line.strip(), sha)
    if not touched:
        return []
    regress = LOGDIR / "regress"
    out = []
    # Fixes merged inside the window are the recent round's own subject (hunting-patterns「recent 轮」);
    # the watch is for older fixes that a later commit may have undone.
    cut = _local_ts(since)
    fixed = sorted((x for x in rows if x["fixed"] and x["closed"] < cut),
                   key=lambda x: (x["severity"] or "P2", -x["closed"]))
    for issue in fixed:
        task, draft = tasks.get(issue["number"], ("", ""))
        path = LOGDIR / "filed" / draft if draft else None
        if not path or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        red = RED_BLOCK.search(text)
        hit = next((f for f in dict.fromkeys(FILE_REF.findall(text)) if f in touched), None)
        if not red or not hit:
            continue
        regress.mkdir(parents=True, exist_ok=True)
        script = regress / f"{issue['number']}.sh"
        script.write_text(red.group(1).strip() + "\n", encoding="utf-8")
        out.append(f"- #{issue['number']}（{issue['severity'] or '未分级'}，已修）{hit} 被 {touched[hit]} 改过："
                   f"`cd /root/wt-patrol && env -u CLAWOCK_WORKSPACE PYTHONPATH=src bash {script}`")
        if len(out) >= limit:
            break
    return out


def brief(axis, since, issues_path=None, now=None):
    now = now or time.time()
    lines = [f"（自动生成 {time.strftime('%m-%d %H:%M')}；分级规则见 issue-format.md「分级」）", filing_line(now)]
    try:
        tasks = task_by_issue()
        rows = [classify(i, tasks) for i in load_issues(issues_path)]
    except Exception as e:  # the round still runs; it just goes without the history
        lines.append(f"- 读不到 issue 历史（{e}），本轮没有反馈数据。")
        return "\n".join(lines), None
    per_lens, noisy, lessons = feedback(rows, now)
    mine = per_lens.get(axis, Counter())
    total = sum(per_lens.values(), Counter())
    lines.append(f"- 近 14 天本范围（{axis}）单独开 {mine['filed']} 条：修了 {mine['fixed']}、判误报/不值得修 "
                 f"{mine['noise']}、仍 open {mine['open']}；全部范围 {total['filed']} 条、误报 {total['noise']}。")
    if lessons:
        lines.append("- 最近被判误报/不值得修（同形态别再提，拿不准先 `gh issue view <N> -R KCNyu/clawock --comments` 看关闭理由）：")
        lines += [f"  - #{r['number']} `{r['area']}/{r['kind']}` {r['title'][9:90]}" for r in lessons]
    if noisy:
        lines.append("- 降权中（闸会把这些类别压到 P3 进汇总，直到不再被这样关）："
                     + "、".join(f"{a}/{k}" for a, k in noisy))
    if axis == "recent":
        watch = regression_watch(rows, since, task_by_issue())
        if watch:
            lines.append("- 回归观察：本窗口的提交碰过这些已修 issue 引用的文件。逐条复跑它当时的判据——"
                         "修好后它应当是绿的（exit 0）。只有断言式的红（AssertionError / SystemExit 并打印出说明）才是回归候选，"
                         "照常反证后按 `类型: regression` + `关联: #N` 提；AttributeError/ImportError/找不到文件说明判据跟着代码"
                         "改名过时了，不算回归，顺着新名字看一眼修复还在不在即可：")
            lines += watch
    return "\n".join(lines), noisy


def round_yield(task):
    rows = [r for r in triage.read_jsonl(LOGDIR / "filed" / "index.jsonl") if r.get("task") == task]
    parts = [f"{r.get('severity')}#{r.get('number')}" for r in rows if r.get("route") == "issue"]
    digest = sum(r.get("route") == "digest" for r in rows)
    comment = sum(r.get("route") == "comment" for r in rows)
    if digest:
        parts.append(f"+{digest} digest")
    if comment:
        parts.append(f"+{comment} comment")
    return " ".join(parts)


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("brief")
    b.add_argument("--axis", required=True)
    b.add_argument("--since", default="")
    b.add_argument("--issues", default=None, help="a saved gh issue list JSON (tests)")
    y = sub.add_parser("round-yield")
    y.add_argument("--task", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "round-yield":
        print(round_yield(args.task))
        return 0
    text, noisy = brief(args.axis, args.since, args.issues)
    try:
        if noisy is None:  # no history this time: keep the last demotions rather than clearing them
            raise OSError
        (LOGDIR / "feedback.json").write_text(json.dumps({"generated": int(time.time()), "noisy": noisy}),
                                              encoding="utf-8")
    except OSError:
        pass
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

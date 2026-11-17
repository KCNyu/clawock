#!/usr/bin/env python3
"""What patrol learned from its own issues, rendered into the next round's prompt (2026-10-01).

  patrol_intel.py brief --axis <axis> [--since '<YYYY-MM-DD HH:MM:SS>']
      prints the round prompt's「反馈与提报」block and rewrites feedback.json (the categories the
      gate demotes). The supervisor runs it before every dispatch; failure leaves a one-line note.
  patrol_intel.py round-yield --task <task id>
      prints what one round routed, e.g. `P1#2240 P2#2241 +1 comment +2 candidate`, for rounds.tsv.
  patrol_intel.py regress-verdict <source N> suppressed|tracked|fixed|reset ...
      adjudicate one saved regression check (see below).
  patrol_intel.py regress-status
      print the saved checks and their verdicts.
  patrol_intel.py regress-refresh <source N>
      rewrite regress/<N>.sh from the draft's GREEN-CHECK (preferred) or RED-CHECK.

Three loops, each borrowed from a tool that already runs one:
- precision per detector (CodeQL query precision + dismissal reasons): every lens's recent issues
  counted as fixed / noise (closed not planned, or labelled patrol:noise/duplicate/invalid/
  wontfix); an (area, kind) pair closed as noise 3+ times in 14 days, and at least as often as
  it was fixed, has its P2 findings lowered to P3 by the gate until that stops (P0/P1 are never
  touched: they carry today's real artifact);
- regression detection (Sentry's resolved → regressed): a fixed patrol issue kept its RED-CHECK
  in the draft; when a commit in the recent window touches a file that issue cited, the recent
  round is told to re-run that exact check (it must stay green). A RED-CHECK may intentionally
  keep reproducing a frozen historical artifact (the 2026-10-21 brief and #3134/#3490): such a
  draft must also carry a GREEN-CHECK that asserts the fixed *current* behaviour. The watch
  prefers GREEN-CHECK; a check whose red was adjudicated as not actionable is suppressed here
  and the gate refuses to re-file its RED-CHECK. `regress/state.json` is the host-local ledger
  of those verdicts; scripts carry their source, digest and adjudication command in a header.
- filing history: recent severity counts and legacy pending entries, without count ceilings.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import shlex
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
GREEN_BLOCK = re.compile(r"<!--\s*GREEN-CHECK\s*\n(.*?)\n\s*-->", re.S)
FILE_REF = re.compile(r"((?:[\w.\-]+/)+[\w.\-]+\.(?:py|js|ts|json|jsonl|ya?ml|sh|md|css|html|toml))[:：]\d+")
# A RED-CHECK that reads a dated published brief reproduces a frozen record: the repository keeps
# history and discloses the right number in the projection/timeline (#3134/#3490). Such a check
# cannot go green without rewriting history, so it is a repro, never a post-fix guard.
FROZEN_BRIEF = re.compile(r"memory/\d{4}-\d{2}-\d{2}-pre-open\.md")
SUPPRESSING_VERDICTS = {"suppressed", "broken"}


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
    closed = [r for r in rows if r["labelled"] and r["closed"] and now - r["closed"] < WINDOW_S]
    noise_pairs = Counter((r["area"], r["kind"]) for r in closed if r["noise"])
    fixed_pairs = Counter((r["area"], r["kind"]) for r in closed if r["fixed"])
    # A rate, not a count: the categories that carry the money path are also the busiest, so
    # three rejected drafts among thirty fixes (data/bug on 10-11: 4 against 22) say nothing
    # about the category. It is noisy when rejections are at least as common as fixes.
    noisy = sorted(pair for pair, n in noise_pairs.items() if n >= 3 and n >= fixed_pairs[pair])
    lessons = sorted((r for r in rows if r["noise"] and now - r["closed"] < WINDOW_S), key=lambda r: -r["closed"])[:6]
    return per_lens, noisy, lessons


def filing_line(now):
    index = triage.read_jsonl(LOGDIR / "filed" / "index.jsonl")
    day = [r for r in index if r.get("route") == "issue" and now - r.get("ts", 0) < 86400]
    by = Counter(r.get("severity") for r in day)
    pending = len(triage.read_jsonl(LOGDIR / "digest" / "pending.jsonl"))
    back = sum(r.get("route") == "candidate" and now - r.get("ts", 0) < 86400 for r in index)
    return (f"- 24 小时内单独开了 {len(day)} 条（P0 {by['P0']} / P1 {by['P1']} / "
            f"P2 {by['P2']} / P3 {by['P3']}），另有 {back} 条 P3 因没写不修的代价退回候选。"
            "各级提报数量不限，同根因补充到已有 issue；要提高的是 P0/P1 在其中的比例。"
            + (f"旧汇总待发 {pending} 条，下次收尾提报。" if pending else ""))


def _regress_state_path():
    return LOGDIR / "regress" / "state.json"


def _load_regress_state():
    """The host-local verdict ledger. A missing or torn file must not stop a round."""
    try:
        data = json.loads(_regress_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "checks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("checks"), dict):
        return {"version": 1, "checks": {}}
    return data


def _save_regress_state(state):
    path = _regress_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".state.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _check_blocks(text):
    """(RED-CHECK, GREEN-CHECK) bodies as written. Either may be empty."""
    red = RED_BLOCK.search(text)
    green = GREEN_BLOCK.search(text)
    return ((red.group(1).strip() if red else ""), (green.group(1).strip() if green else ""))


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_syntax(check):
    """Check shell syntax and literal Python -c payloads without executing them.

    shlex removes shell quoting, so a quote-truncated payload is validated as
    Python will receive it. Dynamic expansions are left to execution-time checks.
    """
    shell = subprocess.run(['bash', '-n'], input=check, text=True, capture_output=True)
    if shell.returncode:
        return shell.stderr.strip()
    if "<<" in check:
        return None
    try:
        lexer = shlex.shlex(check, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
        for i, token in enumerate(tokens[:-2]):
            if not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', Path(token).name):
                continue
            j = i + 1
            while j < len(tokens):
                option = tokens[j]
                if option == '-c' and j + 1 < len(tokens):
                    payload = tokens[j + 1]
                    if '$' not in payload and '`' not in payload:
                        ast.parse(payload)
                    break
                if option in ('-m', '--') or not option.startswith('-'):
                    break
                # These options consume a value; it is not a script path.
                j += 2 if option in ('-W', '-X', '--check-hash-based-pycs') else 1
    except (SyntaxError, ValueError) as exc:
        return f'Python/shell syntax: {exc}'
    return None


def _regress_script(number, check, kind, digest, source, commit, emitted):
    """The saved check with enough provenance to review and adjudicate it without this file."""
    generated = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(emitted))
    header = [
        "#!/usr/bin/env bash",
        f"# clawock-patrol regression check for #{number} (kind={kind})",
        f"# source: {source}",
        f"# digest: sha256:{digest}",
        f"# generated: {generated} at {commit or 'unknown'}",
        "#",
        "# kind=green asserts the fixed behaviour and must exit 0.",
        "# kind=red is the original reproduction. If its only red is a frozen historical",
        "# artifact, do not file a regression; adjudicate the check instead:",
        f"#   python3 /root/tools/clawock-patrol/patrol_intel.py regress-verdict {number} suppressed --reason ...",
        "",
    ]
    return "\n".join(header) + check.strip() + "\n"


def _regress_links(index_rows):
    """Index rows by the source issue they name and by the check text they filed."""
    by_related, by_digest = defaultdict(list), defaultdict(list)
    for row in index_rows:
        if row.get("route") != "issue" or not row.get("number"):
            continue
        for n in row.get("related") or []:
            try:
                by_related[int(n)].append(row)
            except (TypeError, ValueError):
                continue
        for d in (row.get("red_digest"), row.get("green_digest"), row.get("digest")):
            if d:
                by_digest[d].append(row)
    return by_related, by_digest


def _linked_issue(number, digests, by_related, by_digest, rows_by_number, since=0):
    """The newest filed issue for this source number, or for the same check text.

    `since` bounds the look-back to the current check text: a regression issue filed before a
    draft rewrote its check does not adjudicate the rewritten one.
    """
    candidates = list(by_related.get(int(number), []))
    for d in digests:
        candidates += by_digest.get(d, [])
    best = None
    for row in candidates:
        if row.get("number") == number:      # the source issue itself, not a regression report
            continue
        if since and row.get("ts", 0) < since:
            continue
        issue = rows_by_number.get(row.get("number"))
        if issue and (best is None or row.get("ts", 0) > best[0]):
            best = (row.get("ts", 0), issue)
    return best[1] if best else None


def _resolve_regress_entry(entry, number, digests, by_related, by_digest, rows_by_number, now):
    """Link a check to the issue it already produced and keep the verdict honest.

    `tracked` suppresses while that issue is open; if it closes as noise/not planned the
    check becomes `suppressed` (the closure reason applies to this same check), and if it
    closes as fixed the verdict is cleared so a later touch can re-run the now-guarding check.
    """
    if entry.get("verdict") == "tracked":
        issue = rows_by_number.get(entry.get("issue"))
        if issue and issue["state"] == "CLOSED":
            entry["verdict"] = "suppressed" if issue["noise"] else ""
            entry["reason"] = "已按误报/不修关闭" if issue["noise"] else ""
            entry["issue"] = issue["number"] if issue["noise"] else None
            entry["updated"] = now
        return entry
    if entry.get("verdict") in SUPPRESSING_VERDICTS:
        issue = rows_by_number.get(entry.get("issue"))
        if issue and issue["state"] == "OPEN":      # reopened: it is tracked again, not settled
            entry["verdict"] = "tracked"
            entry["reason"] = "还 open"
            entry["updated"] = now
        return entry
    issue = _linked_issue(number, digests, by_related, by_digest, rows_by_number,
                          since=int(entry.get("check_since") or 0))
    if issue:
        entry["verdict"] = "tracked" if issue["state"] == "OPEN" else ("suppressed" if issue["noise"] else "")
        entry["issue"] = issue["number"]
        entry["reason"] = ("还 open" if entry["verdict"] == "tracked"
                           else "已按误报/不修关闭" if entry["verdict"] == "suppressed"
                           else "")
        entry["updated"] = now
    return entry


def regression_watch(rows, since, tasks, limit=6):
    """Fixed issues whose cited files changed, with a forward guard where the draft has one.

    Returns (notices, skipped). `notices` are commands for the round; `skipped` says why a
    known check was not offered again (already open, or adjudicated not actionable). The
    saved `regress/<N>.sh` is the check itself plus a provenance header.
    """
    if not since:
        return [], []
    r = subprocess.run(["git", "-C", str(WORK), "log", f"--since={since}", "--first-parent", "--name-only",
                        "--format=@%h", "origin/master"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return [], []
    touched, sha = {}, ""
    for line in r.stdout.splitlines():
        if line.startswith("@"):
            sha = line[1:]
        # Runtime data commits and test edits cannot undo a fix (a test change is the fix's own guard
        # being edited; the recent round reviews that diff anyway), so they do not trigger a re-run.
        elif line.strip() and not line.startswith(("assets/data/", "memory/", "tests/")):
            touched.setdefault(line.strip(), sha)
    if not touched:
        return [], []
    regress = LOGDIR / "regress"
    out, skipped = [], []
    index_rows = triage.read_jsonl(LOGDIR / "filed" / "index.jsonl")
    by_related, by_digest = _regress_links(index_rows)
    rows_by_number = {x["number"]: x for x in rows}
    state = _load_regress_state()
    now = int(time.time())
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
        red, green = _check_blocks(text)
        check, kind = (green, "green") if green else (red, "red")
        hit = next((f for f in dict.fromkeys(FILE_REF.findall(text)) if f in touched), None)
        if not check or not hit:
            continue
        number = issue["number"]
        digest = _digest(check)
        red_digest = _digest(red) if red else ""
        entry = state["checks"].get(str(number), {})
        if entry.get("digest") != digest:
            # The check text changed: a verdict about the old text does not bind the new one,
            # and only issues filed after the rewrite may adjudicate it.
            for key in ("verdict", "reason", "issue"):
                entry.pop(key, None)
            entry["check_since"] = now if entry.get("digest") else 0
        entry.update({"digest": digest, "red_digest": red_digest, "kind": kind,
                      "source": f"filed/{draft}"})
        entry = _resolve_regress_entry(entry, number, {digest, red_digest} - {""},
                                       by_related, by_digest, rows_by_number, now)
        if entry.get("verdict") in SUPPRESSING_VERDICTS:
            linked = f"#{entry['issue']} " if entry.get("issue") else ""
            skipped.append(f"#{number}（{entry.get('verdict')}，{linked}{entry.get('reason') or ''}）")
            state["checks"][str(number)] = entry
            continue
        if entry.get("verdict") == "tracked":
            skipped.append(f"#{number} 已由 #{entry.get('issue')} 跟踪（open）")
            state["checks"][str(number)] = entry
            continue
        error = check_syntax(check)
        if error:
            entry.update({'verdict': 'broken', 'reason': error, 'updated': now})
            state['checks'][str(number)] = entry
            skipped.append(f"#{number}（broken，{error}）")
            continue
        regress.mkdir(parents=True, exist_ok=True)
        script = regress / f"{number}.sh"
        entry["first_emitted"] = entry.get("first_emitted") or now
        entry["last_emitted"] = now
        entry["last_commit"] = touched[hit]
        script.write_text(_regress_script(number, check, kind, digest, f"filed/{draft}",
                                          touched[hit], now), encoding="utf-8")
        state["checks"][str(number)] = entry
        hint = ("forward guard（修好后应为绿）" if kind == "green"
                else "原始 repro，红不等于代码回归" if FROZEN_BRIEF.search(check)
                else "原始 repro，先确认它断言当前行为")
        out.append(f"- #{number}（{issue['severity'] or '未分级'}，已修）{hit} 被 {touched[hit]} 改过："
                   f"`cd /root/wt-patrol && env -u CLAWOCK_WORKSPACE PYTHONPATH=src bash {script}`"
                   f"——{hint}")
        if len(out) >= limit:
            break
    _save_regress_state(state)
    return out, skipped


def _draft_path(number):
    task, draft = task_by_issue().get(int(number), ("", ""))
    path = LOGDIR / "filed" / draft if draft else None
    return path if path and path.is_file() else None


def _sync_entry(entry, number, path, now):
    """Refresh digest/source from the draft; clear a verdict that bound the old check text."""
    text = path.read_text(encoding="utf-8", errors="replace")
    red, green = _check_blocks(text)
    check, kind = (green, "green") if green else (red, "red")
    if not check:
        raise SystemExit(f"#{number}: {path.name} has neither GREEN-CHECK nor RED-CHECK")
    digest = _digest(check)
    if entry.get("digest") != digest:
        for key in ("verdict", "reason", "issue"):
            entry.pop(key, None)
        entry["check_since"] = int(now) if entry.get("digest") else 0
    entry.update({"digest": digest, "red_digest": _digest(red) if red else "", "kind": kind,
                  "source": f"filed/{path.name}"})
    return check, kind, digest


def regress_verdict(number, verdict, linked=None, reason="", now=None):
    """Adjudicate one saved check. `fixed` clears a verdict; `reset` clears it and its history."""
    number = int(number)
    path = _draft_path(number)
    if not path:
        raise SystemExit(f"#{number}: no filed draft; cannot read its check")
    state = _load_regress_state()
    entry = state["checks"].get(str(number), {})
    check, kind, digest = _sync_entry(entry, number, path, int(now or time.time()))
    now = int(now or time.time())
    if verdict == "reset":
        # Keep the check's identity but move its horizon forward: a regression issue filed
        # before the reset must not immediately re-suppress the check it adjudicated.
        for key in ("verdict", "reason", "issue"):
            entry.pop(key, None)
        entry.update({"check_since": now, "updated": now, "first_emitted": entry.get("first_emitted") or now})
        state["checks"][str(number)] = entry
        _save_regress_state(state)
        print(f"#{number}: verdict cleared; the next touch emits its check again")
        return
    if verdict in {"suppressed", "broken"}:
        if not reason.strip():
            raise SystemExit("suppressed needs --reason (why this check cannot prove a new regression)")
        entry.update({"verdict": verdict, "reason": reason.strip(), "issue": linked, "updated": now})
    elif verdict == "tracked":
        if not linked:
            raise SystemExit("tracked needs --issue N")
        entry.update({"verdict": "tracked", "reason": reason.strip() or "还 open",
                      "issue": linked, "updated": now})
    elif verdict == "fixed":
        entry.update({"verdict": "", "reason": "", "issue": None, "updated": now})
    else:
        raise SystemExit(f"unknown verdict {verdict!r}")
    entry["first_emitted"] = entry.get("first_emitted") or now
    state["checks"][str(number)] = entry
    _save_regress_state(state)
    print(json.dumps({"number": number, "kind": kind, "digest": digest,
                      "verdict": entry.get("verdict") or "active", "issue": entry.get("issue"),
                      "reason": entry.get("reason") or ""}, ensure_ascii=False))


def regress_refresh(number, now=None):
    """Rewrite regress/<N>.sh from the current draft (GREEN-CHECK preferred)."""
    number = int(number)
    path = _draft_path(number)
    if not path:
        raise SystemExit(f"#{number}: no filed draft; cannot rewrite its check")
    state = _load_regress_state()
    entry = state["checks"].get(str(number), {})
    check, kind, digest = _sync_entry(entry, number, path, int(now or time.time()))
    now = int(now or time.time())
    error = check_syntax(check)
    if error:
        entry.update({'verdict': 'broken', 'reason': error, 'updated': now})
        state['checks'][str(number)] = entry
        _save_regress_state(state)
        raise SystemExit(f'#{number}: broken check, not emitted: {error}')
    entry["first_emitted"] = entry.get("first_emitted") or now
    entry["last_emitted"] = now
    script = LOGDIR / "regress" / f"{number}.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(_regress_script(number, check, kind, digest, f"filed/{path.name}",
                                      entry.get("last_commit", ""), now), encoding="utf-8")
    state["checks"][str(number)] = entry
    _save_regress_state(state)
    print(f"#{number}: wrote {script} ({kind}, sha256:{digest[:12]})")


def regress_status():
    state = _load_regress_state()
    rows = []
    for key, entry in sorted(state["checks"].items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
        stamp = entry.get("updated") or entry.get("last_emitted") or 0
        rows.append("\t".join([
            f"#{key}", entry.get("verdict") or "active",
            f"#{entry['issue']}" if entry.get("issue") else "-", entry.get("kind") or "?",
            time.strftime("%Y-%m-%d %H:%M", time.localtime(stamp)) if stamp else "-",
            (entry.get("reason") or "")[:120]]))
    print("\n".join(rows) if rows else "(no saved regression checks)")


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
        lines.append("- 降权中（这些类别最近被关成误报的不少于修掉的；闸会把其中的 P2 压到 P3，"
                     "带今天真实产物的 P0/P1 不受影响）：" + "、".join(f"{a}/{k}" for a, k in noisy))
    if axis == "recent":
        watch, skipped = regression_watch(rows, since, task_by_issue())
        if watch:
            lines.append("- 回归观察：本窗口的提交碰过这些已修 issue 引用的文件。逐条复跑它当时的判据——"
                         "`forward guard`（GREEN-CHECK）修好后必须是绿的；`原始 repro` 只是当时的复现，"
                         "红不等于代码回归，先确认它断言的是当前行为。只有断言式的红（AssertionError / SystemExit 并打印出说明）"
                         "才是回归候选，照常反证后按 `类型: regression` + `关联: #N` 提；AttributeError/ImportError/找不到文件"
                         "说明判据跟着代码改名过时了，不算回归，顺着新名字看一眼修复还在不在即可。"
                         "若红只来自已发布历史/冻结产物（仓库不改写历史），不要改写它，也不要提报："
                         "`python3 /root/tools/clawock-patrol/patrol_intel.py regress-verdict <N> suppressed --reason '<为什么>'` 记账：")
            lines += watch
        if skipped:
            lines.append("  （已裁定跳过，同一判据不再重复提报：" + "；".join(skipped[:3])
                         + ("…" if len(skipped) > 3 else "") + "）")
    return "\n".join(lines), noisy


def round_yield(task):
    rows = [r for r in triage.read_jsonl(LOGDIR / "filed" / "index.jsonl") if r.get("task") == task]
    parts = [f"{r.get('severity')}#{r.get('number')}" for r in rows if r.get("route") == "issue"]
    digest = sum(r.get("route") == "digest" for r in rows)
    comment = sum(r.get("route") == "comment" for r in rows)
    back = sum(r.get("route") == "candidate" for r in rows)
    if digest:
        parts.append(f"+{digest} digest")
    if comment:
        parts.append(f"+{comment} comment")
    if back:
        parts.append(f"+{back} candidate")
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
    v = sub.add_parser("regress-verdict")
    v.add_argument("number", type=int, help="the fixed patrol issue whose check is being adjudicated")
    v.add_argument("verdict", choices=["suppressed", "broken", "tracked", "fixed", "reset"])
    v.add_argument("--issue", type=int, dest="linked", default=None,
                   help="the regression issue this check produced (for tracked/suppressed)")
    v.add_argument("--reason", default="", help="why the check cannot prove a new regression")
    r = sub.add_parser("regress-refresh")
    r.add_argument("number", type=int)
    sub.add_parser("regress-status")
    args = ap.parse_args(argv)
    if args.cmd == "round-yield":
        print(round_yield(args.task))
        return 0
    if args.cmd == "regress-verdict":
        regress_verdict(args.number, args.verdict, args.linked, args.reason)
        return 0
    if args.cmd == "regress-refresh":
        regress_refresh(args.number)
        return 0
    if args.cmd == "regress-status":
        regress_status()
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

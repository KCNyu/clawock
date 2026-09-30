#!/usr/bin/env python3
"""The side-effect half of patrol filing: labels, the digest issue, the Telegram line.

`gate_issue.py` decides and `triage.py` classifies; everything here talks to GitHub or the
delivery provider. It is a module (the gate imports it) and a small CLI the supervisor calls
after each round, so a digest that is due gets filed even on a day no new finding arrives:

  filing.py flush-digest [--force]   # file the pending digest when due (8 items or 3 days)
  filing.py ensure-labels            # create every label of the taxonomy that is missing
  filing.py backfill [--dry-run]     # label open [patrol] issues that have no severity label yet,
                                     # and give every gated patrol issue its source + lens label
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triage  # noqa: E402

LOGDIR = Path(os.environ.get("PATROL_STATE", "/root/logs/clawock-patrol"))
WORK = Path(os.environ.get("PATROL_WORKTREE", "/root/wt-patrol"))
TOOL = Path(__file__).resolve().parent
REPO = "KCNyu/clawock"
INDEX = LOGDIR / "filed" / "index.jsonl"
DIGEST_PENDING = LOGDIR / "digest" / "pending.jsonl"
NOTIFY_ENV = Path(os.environ.get("PATROL_NOTIFY_ENV", "/root/tools/agent-dispatch/notify.env"))


def gh(*args, timeout=60):
    return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)


def ensure_labels(names):
    """Create the labels a filing needs, once; a missing label would fail `gh issue create`."""
    known_path = LOGDIR / "labels-known.json"
    try:
        known = set(json.loads(known_path.read_text(encoding="utf-8")))
    except Exception:
        known = set()
    missing = [n for n in names if n not in known]
    if not missing:
        return []
    r = gh("label", "list", "-R", REPO, "--limit", "500", "--json", "name", "-q", ".[].name")
    if r.returncode == 0:
        known |= set(r.stdout.split("\n"))
    tax = triage.label_taxonomy(triage.lenses_from_axes(TOOL / "axes.tsv"))
    created = []
    for n in names:
        if n in known:
            continue
        color, desc = tax.get(n, ("ededed", "clawock-patrol"))
        if gh("label", "create", n, "-R", REPO, "--color", color, "--description", desc, "--force").returncode == 0:
            known.add(n)
            created.append(n)
    known_path.write_text(json.dumps(sorted(k for k in known if k)), encoding="utf-8")
    return created


def telegram(text):
    """One short Telegram line (kcn 2026-09-26: patrol traffic is Telegram-only; WeChat drops
    silently on a cold session). A failed send is reported, never silent (review 2026-09-26),
    and never changes a verdict. It goes through clawock's delivery provider, which sets the
    runtime's PATH and gateway timeout and honours CLAWOCK_DELIVERY_DISABLED; this file is
    installed outside any checkout, so clawock comes from the patrol's own worktree."""
    try:
        _CHECKOUT = WORK
        sys.path.insert(0, str(_CHECKOUT))
        sys.path.insert(0, str(_CHECKOUT / "src"))
        conf = dict(l.split("=", 1) for l in NOTIFY_ENV.read_text().splitlines()
                    if "=" in l and not l.lstrip().startswith("#"))
        target = conf.get("TELEGRAM_TARGET", "").strip().strip("'\"")
        if not target:
            print("gate: notify skipped (TELEGRAM_TARGET not configured)", file=sys.stderr)
            return
        from clawock.providers.delivery import OpenClawDelivery
        sent = OpenClawDelivery(timeout=60).send(
            conf.get("TELEGRAM_CHANNEL", "telegram").strip().strip("'\"") or "telegram", target, text)
        if sent.status == "failed":
            print(f"gate: notify failed ({sent.detail[-200:]})", file=sys.stderr)
    except Exception as e:
        print(f"gate: notify failed ({e})", file=sys.stderr)


def flush_digest(force=False, task="-"):
    """File the pending digest as one issue when it is due (triage.should_flush); the items stay
    pending when filing fails, so nothing is lost."""
    pending = triage.read_jsonl(DIGEST_PENDING)
    if not pending or not (force or triage.should_flush(pending)):
        return None
    title, body, labels = triage.render_digest(pending, time.strftime("%Y-%m-%d"))
    body += f"\n\n<!-- patrol-gate: passed digest items={len(pending)} -->\n"
    out = LOGDIR / "digest" / f"digest-{int(time.time())}.md"
    out.write_text(body, encoding="utf-8")
    ensure_labels(labels)
    args = ["issue", "create", "-R", REPO, "--title", title, "--body-file", str(out)]
    for lab in labels:
        args += ["--label", lab]
    r = gh(*args, timeout=120)
    if r.returncode != 0:
        print(f"gate: digest filing failed, items stay pending: {(r.stdout + r.stderr)[-300:]}", file=sys.stderr)
        return None
    url = r.stdout.strip().splitlines()[-1]
    DIGEST_PENDING.rename(DIGEST_PENDING.with_name(f"flushed-{int(time.time())}.jsonl"))
    m = re.search(r"/issues/(\d+)", url)
    triage.append_jsonl(INDEX, {"ts": int(time.time()), "route": "digest-issue", "number": int(m.group(1)) if m else None,
                                "url": url, "title": title, "items": len(pending), "task": task})
    print(f"gate: digest filed {url} ({len(pending)} items)", file=sys.stderr)
    telegram(f"🧺 clawock 巡检汇总：{len(pending)} 条低优先级发现合成一条 issue\n{url}")
    return url


def backfill(dry_run=False):
    """Open patrol issues get severity/area/kind (inferred from title and body, the same rules the
    gate applies to a draft without `## 分级`); every issue the gate filed gets `patrol` and its
    `lens:` label, which is exact (created.tsv names the round). Closed issues keep their state."""
    lenses = triage.lenses_from_axes(TOOL / "axes.tsv")
    r = gh("issue", "list", "-R", REPO, "--state", "all", "--limit", "500", "--search", "\"[patrol]\" in:title",
           "--json", "number,title,state,labels,body", timeout=120)
    if r.returncode != 0:
        raise SystemExit(r.stderr)
    tasks = {}
    try:
        for line in (LOGDIR / "filed" / "created.tsv").read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            m = re.search(r"/issues/(\d+)", f[3]) if len(f) > 4 else None
            if m:
                tasks[int(m.group(1))] = f[4]
    except OSError:
        pass
    surfaces = json.loads((TOOL / "surfaces.json").read_text(encoding="utf-8"))
    plan = []
    for issue in json.loads(r.stdout):
        if not issue["title"].startswith("[patrol]"):
            continue
        have = {l["name"] for l in issue["labels"]}
        want = {triage.SOURCE_LABEL}
        lens = triage.lens_of(tasks.get(issue["number"], ""))
        if lens in lenses and issue["number"] in tasks:
            want.add(f"lens:{lens}")
        if issue["state"] == "OPEN" and not any(l.startswith("severity:") for l in have) \
                and triage.DIGEST_LABEL not in have:
            body = issue.get("body") or ""
            m = re.search(r"SURFACE\s*[:：]\s*(.+)", body)
            surface = m.group(1).strip().strip("`*") if m else ""
            refs = re.findall(r"((?:[\w.\-]+/)+[\w.\-]+\.\w+)[:：](\d+)", body)
            v = triage.assess(title=issue["title"], body=body, surface=surface, infra_label=surfaces["infra_label"],
                              refs=refs, red=body, lens=lens)
            want |= set(v.labels()) - {f"lens:{lens}"} if lens not in lenses else set(v.labels())
        add = sorted(want - have)
        if add:
            plan.append((issue["number"], issue["state"], add))
    for number, state, add in plan:
        print(f"#{number} [{state}] + {' '.join(add)}")
        if dry_run:
            continue
        ensure_labels(add)
        gh("issue", "edit", str(number), "-R", REPO, *sum((["--add-label", a] for a in add), []))
    return plan


def main(argv):
    if argv[:1] == ["flush-digest"]:
        url = flush_digest(force="--force" in argv, task=os.environ.get("AGENT_DISPATCH_TASK_ID", "supervisor"))
        print(url or f"digest not due ({len(triage.read_jsonl(DIGEST_PENDING))} pending)")
        return 0
    if argv[:1] == ["ensure-labels"]:
        names = list(triage.label_taxonomy(triage.lenses_from_axes(TOOL / "axes.tsv")))
        created = ensure_labels(names)
        print(f"{len(names)} labels in the taxonomy; created {len(created)}: {' '.join(created) or '-'}")
        return 0
    if argv[:1] == ["backfill"]:
        plan = backfill(dry_run="--dry-run" in argv)
        print(f"{len(plan)} issues {'would be ' if '--dry-run' in argv else ''}labelled")
        return 0
    print(__doc__.strip().split("\n\n")[-1], file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

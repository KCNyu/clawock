"""clawock-patrol triage (2026-10-01): severity is backed by evidence, P3 and over-budget
findings go to the digest instead of the void, one root cause is one issue, and the round's
yield is readable by the dsh panel. Unit tests on the pure half plus one gate dry run."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "ops/host/clawock-patrol"
sys.path.insert(0, str(TOOL))

import patrol_intel  # noqa: E402
import triage  # noqa: E402

INFRA = "无（基础设施）"


def assess(title="[patrol] x", body="", surface="面板", refs=(("src/clawock/a.py", "3"),), red="", lens="logic", noisy=None):
    return triage.assess(title=title, body=body, surface=surface, infra_label=INFRA, refs=list(refs), red=red,
                         lens=lens, noisy=noisy)


def test_declared_levels_hold_only_with_todays_artifacts():
    body = "## 分级\n严重度: P0\n领域: data\n类型: bug\n关联: 无\n"
    v = assess(body=body, red="python3 -c \"import json; d=json.load(open('assets/data/dashboard.json'))\"")
    assert (v.severity, v.area, v.kind) == ("P0", "data", "bug") and not v.notes
    # the same claim read only from source: a P0 nobody showed in real output becomes P2
    v = assess(body=body, red="grep -n total src/clawock/a.py")
    assert v.severity == "P2" and "真实产物" in v.notes[0]
    # P0 is kept for money/decision/delivery/leaks
    v = assess(body=body.replace("data", "dashboard"), red="cat assets/data/x.json")
    assert v.severity == "P1"


def test_nits_are_p3_whatever_the_draft_says():
    v = assess(body="严重度: P1\n领域: docs\n类型: drift\n", refs=[("README.md", "12")], red="grep memory/ README.md")
    assert v.severity == "P3"
    v = assess(title="[patrol] 卡片 hover 对比度只有 2.1:1", body="严重度: P2\n领域: dashboard\n类型: bug\n",
               refs=[("site/assets/css/dashboard.css", "40")])
    assert v.severity == "P3"
    # colour that carries the money reading is not a nit
    v = assess(title="[patrol] 涨跌颜色反了：下跌印成绿色", body="严重度: P2\n领域: dashboard\n类型: bug\n",
               refs=[("site/assets/css/dashboard.css", "40")])
    assert v.severity == "P2"
    v = assess(body="严重度: P1\n领域: ops\n类型: gate-gap\n", surface=INFRA, red="cat logs/x.json")
    assert v.severity == "P2"


def test_missing_fields_are_inferred_and_features_are_capped():
    v = assess(title="[patrol] README 仍写「六个产物」", body="", refs=[("README.md", "3")])
    assert v.area == "docs" and v.kind == "drift" and v.severity == "P3" and set(v.inferred) == {"severity", "area", "kind"}
    v = assess(body="严重度: P1\n领域: delivery\n类型: feature\n", red="cat memory/x.md", lens="peers")
    assert v.severity == "P2"


def test_noise_feedback_demotes_the_category():
    v = assess(body="严重度: P2\n领域: dashboard\n类型: bug\n", noisy={("dashboard", "bug")})
    assert v.severity == "P3" and "反馈回路" in v.notes[-1]


def test_budget_sends_overflow_to_the_digest_never_drops_p0():
    now = time.time()
    rows = [{"route": "issue", "ts": now - 60, "severity": "P2", "kind": "bug"} for _ in range(5)]
    v = triage.Verdict("P2", "data", "bug", "logic")
    assert triage.route(v, rows, now)[0] == "digest"
    assert triage.route(triage.Verdict("P1", "data", "bug", "logic"), rows, now)[0] == "issue"
    rows += [{"route": "issue", "ts": now - 60, "severity": "P1", "kind": "bug"} for _ in range(5)]
    assert triage.route(triage.Verdict("P1", "data", "bug", "logic"), rows, now)[0] == "digest"
    assert triage.route(triage.Verdict("P0", "data", "bug", "logic"), rows, now)[0] == "issue"
    assert triage.route(triage.Verdict("P3", "docs", "drift", "docs"), [], now)[0] == "digest"
    week = [{"route": "issue", "ts": now - 86400 * 3, "severity": "P2", "kind": "feature"}] * 2
    assert triage.route(triage.Verdict("P2", "delivery", "feature", "peers"), week, now)[0] == "digest"


def test_fingerprint_groups_by_enclosing_function(tmp_path):
    src = tmp_path / "src/clawock/x.py"
    src.parent.mkdir(parents=True)
    src.write_text("import os\n\ndef alpha(v):\n    a = 1\n    return a\n\nclass B:\n    def beta(self):\n        return 2\n")
    assert triage.fingerprint([("README.md", "1"), ("src/clawock/x.py", "5")], tmp_path) == "src/clawock/x.py::alpha"
    assert triage.fingerprint([("src/clawock/x.py", "9")], tmp_path) == "src/clawock/x.py::beta"
    assert triage.fingerprint([("src/clawock/x.py", "1")], tmp_path) == "src/clawock/x.py::<module>"
    js = tmp_path / "site/a.js"
    js.parent.mkdir()
    js.write_text("const x = 1\nexport function renderRow(r) {\n  return r\n}\nconst fmt = (v) => {\n  return v\n}\n")
    assert triage.fingerprint([("site/a.js", "3")], tmp_path) == "site/a.js::renderRow"
    assert triage.fingerprint([("site/a.js", "6")], tmp_path) == "site/a.js::fmt"
    now = time.time()
    index = [{"route": "issue", "fingerprint": "src/clawock/x.py::alpha", "area": "data", "number": 7, "ts": now - 100}]
    assert triage.cluster_target(index, "src/clawock/x.py::alpha", "data", {7}, now) == 7
    assert triage.cluster_target(index, "src/clawock/x.py::alpha", "data", set(), now) is None   # closed
    assert triage.cluster_target(index, "src/clawock/x.py::alpha", "risk", {7}, now) is None


def test_digest_flush_and_render_stay_under_githubs_body_cap():
    now = time.time()
    pending = [{"ts": now - 10, "title": f"[patrol] 小问题 {i}", "severity": "P3", "area": "docs", "kind": "drift",
                "lens": "docs", "body": "x" * 20000} for i in range(9)]
    assert triage.should_flush(pending, now)
    assert not triage.should_flush(pending[:2], now)
    assert triage.should_flush([dict(pending[0], ts=now - 73 * 3600)], now)
    title, body, labels = triage.render_digest(pending, "2026-10-01")
    assert title.startswith("[patrol] ") and "9 条" in title
    assert len(body) < 65536 and body.count("- [ ] **小问题") == 9
    assert {"patrol", "patrol:digest", "severity:P3", "area:docs"} <= set(labels)


def test_taxonomy_covers_every_label_a_verdict_can_carry():
    lenses = triage.lenses_from_axes(TOOL / "axes.tsv")
    assert {"money", "peers", "recent", "manual"} <= set(lenses)
    tax = triage.label_taxonomy(lenses)
    for sev in triage.SEVERITIES:
        for area in triage.AREAS:
            for kind in triage.KINDS:
                assert set(triage.Verdict(sev, area, kind, "peers").labels()) <= set(tax)
    assert all(len(desc) <= 100 for _, desc in tax.values())   # GitHub's label description limit
    rotation = open(TOOL / "rotation").read()
    names = [w for line in rotation.splitlines() for w in line.split("#")[0].split()]
    assert set(names) <= set(lenses) and names.count("peers") == 1


def test_feedback_counts_only_labelled_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(patrol_intel, "LOGDIR", tmp_path)
    now = time.time()
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    issues = [{"number": n, "title": "[patrol] 面板某卡显示错", "state": "CLOSED", "stateReason": "NOT_PLANNED",
               "labels": [{"name": "area:dashboard"}, {"name": "kind:bug"}, {"name": "lens:render"}],
               "createdAt": iso, "closedAt": iso} for n in (1, 2, 3)]
    issues.append({"number": 4, "title": "[patrol] CI lane 漏了", "state": "CLOSED", "stateReason": "NOT_PLANNED",
                   "labels": [], "createdAt": iso, "closedAt": iso})
    saved = tmp_path / "issues.json"
    saved.write_text(json.dumps(issues))
    text, noisy = patrol_intel.brief("render", "", str(saved), now)
    assert noisy == [("dashboard", "bug")]
    assert "本范围（render）单独开 3 条" in text and "#4" in text


def test_round_yield_is_a_slash_free_field(tmp_path, monkeypatch):
    monkeypatch.setattr(patrol_intel, "LOGDIR", tmp_path)
    for row in ({"task": "t1", "route": "issue", "severity": "P1", "number": 2240},
                {"task": "t1", "route": "digest"}, {"task": "t1", "route": "digest"},
                {"task": "t1", "route": "comment", "number": 2100}, {"task": "t2", "route": "issue"}):
        triage.append_jsonl(tmp_path / "filed/index.jsonl", row)
    assert patrol_intel.round_yield("t1") == "P1#2240 +2 digest +1 comment"
    assert patrol_intel.round_yield("nobody") == ""


def _gate(tmp_path, draft_text, env_extra=None, name="a"):
    tmp_path = tmp_path / name
    wt = tmp_path / "wt"
    (wt / "src/clawock").mkdir(parents=True)
    (wt / "assets/data").mkdir(parents=True)
    (wt / "src/clawock/money.py").write_text("def total(rows):\n" + "    x = 1\n" * 30 + "    return x\n")
    (wt / "assets/data/dashboard.json").write_text('{"total": 3}')
    state = tmp_path / "state"
    (state / "filed").mkdir(parents=True)
    draft = state / "R1-x.md"
    draft.write_text(draft_text)
    env = {k: v for k, v in os.environ.items() if k != "CLAWOCK_WORKSPACE"}
    env.update({"PATROL_STATE": str(state), "PATROL_WORKTREE": str(wt), "GATE_DRY_RUN": "1",
                "AGENT_DISPATCH_TASK_ID": "patrol-money-20261001-010203", **(env_extra or {})})
    return subprocess.run([sys.executable, str(TOOL / "gate_issue.py"), str(draft)], env=env,
                          capture_output=True, text=True, timeout=120)


DRAFT = """# [patrol] 面板总市值少算一行：total() 只加第一条

## 现象
src/clawock/money.py:31 `return x` 只返回常数；assets/data/dashboard.json:1 今天是 3。

## 为什么是问题
调用链：publish → total()，面板印的总市值来自这里，今天的产物与持仓逐行相加不一致。

## 分级
严重度: {sev}
领域: data
类型: bug
关联: 无

## 用户能看到的差别
SURFACE: 面板
现在: 面板总市值印 3，少算了其余持仓
修完: 面板总市值等于持仓逐行相加

## 反证自查
全仓搜索: git grep -n 'def total' 命中 1 处 src/clawock/money.py
历史: git log -S total 显示 abc1234 引入，无修复
设计意图: 附近注释没有解释为什么只取常数
量化: 今天 1 个数字错，差 2 行
对照已关: 无同形态

## 建议修法
逐行相加，并加一条对照持仓的测试。

<!-- RED-CHECK
python3 -c "
import json
d = json.load(open('assets/data/dashboard.json'))
src = open('src/clawock/money.py').read()
print('total', d['total'])
assert d['total'] == 5, 'total is %s' % d['total']
"
-->
"""


def test_gate_dry_run_reports_triage_and_route(tmp_path):
    r = _gate(tmp_path, DRAFT.format(sev="P0"))
    assert r.returncode == 0, r.stderr
    assert "triage P0 area:data kind:bug lens:money → issue" in r.stderr
    assert "labels: patrol severity:P0 area:data kind:bug lens:money" in r.stderr
    r = _gate(tmp_path, DRAFT.format(sev="P3"), name="b")
    assert r.returncode == 0, r.stderr
    assert "→ digest" in r.stderr and "放进汇总" in r.stderr


def test_gate_refuses_a_feature_outside_the_peers_lens(tmp_path):
    r = _gate(tmp_path, DRAFT.format(sev="P2").replace("类型: bug", "类型: feature"))
    assert r.returncode == 2 and "只在 peers" in r.stderr

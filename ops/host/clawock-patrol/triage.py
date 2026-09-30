#!/usr/bin/env python3
"""Triage for clawock-patrol findings: severity, labels, routing (2026-10-01).

The filing gate (`gate_issue.py`) proves a finding is *true*. This module decides what it is
*worth*: how severe it is, which labels it carries, and whether it becomes its own issue, a
comment on an issue that already holds the same root cause, or one line in the periodic digest.

Why (issue history 09-21 → 09-30, 245 `[patrol]` issues; details in README.md § 分级与路由):
only ~5% were closed as untrue, so the gate works — the problem was volume and value. About a
third were documentation drift, style/contrast nits or CI hygiene, each filed and fixed as its
own issue; 19 were a second or third issue on a root cause that an earlier issue had already
named ("#2171 只修了一处" → #2179). 57 issues in one day is more than anyone reads.

Borrowed shapes, and from where:
- labels as prefixed dimensions (`kind/`, `area/`, `priority/`): Kubernetes prow triage;
- one severity scale with evidence behind the higher levels, plus a precision feedback per
  detector: CodeQL (`security-severity`, query `@precision`, dismissal reasons);
- grouping by the innermost in-app frame (file + enclosing function): Sentry fingerprinting;
- a rolling "dashboard" issue instead of one issue per low-value item, and per-day limits:
  Renovate's Dependency Dashboard and `prHourlyLimit`/`prConcurrentLimit`;
- a lower-severity alert on a root cause already alerting is folded into it: Alertmanager
  grouping/inhibition.

Pure functions only, plus small JSONL stores under the patrol state directory. No network here:
the gate owns every `gh` call.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

SEVERITIES = ("P0", "P1", "P2", "P3")

# What each level means, in kcn's terms (feedback-review-user-facing-value: "报告不漏发、数字不错").
SEVERITY_TEXT = {
    "P0": "kcn 今天看到/收到的钱、仓位、决策数字是错的，或成品丢了/发重了/发不出去，或公开泄露凭证",
    "P1": "会放过 P0 的闸/检测/watchdog 在真实数据上失明或 fail-open，或让人学会忽略告警的假红",
    "P2": "看得到但不改变决策：标签/格式错、非金额的陈旧文案、CI 触发盲区、真实数据里还没出现的边界崩溃",
    "P3": "文档错字/顺序、样式与对比度、无害的标签不一致、内部卫生 —— 进周期汇总，不单独开 issue",
}

AREAS = {
    "data": "行情、持仓、汇率、账本等数字的生产与计算",
    "risk": "风控、加仓侧、决策与策略闸",
    "delivery": "简报/盘中/复盘的生成与投递、watchdog、cron",
    "dashboard": "站点面板、公开页面的数据投影与渲染/样式",
    "dsh": "DSH 插件",
    "harness": "LLM 上下文与产出闸（preflight/postflight/validation）",
    "ops": "CI、发布、主机脚本、调度（含巡检自身）",
    "security": "凭证、隐私、注入",
    "docs": "README、docs/、--help 与实现的一致性",
}

KINDS = {
    "bug": "现有功能今天产出错误结果",
    "drift": "文档/文案/两份实现与真源分叉",
    "false-alarm": "告警或健康判定报了不存在的问题（假红）",
    "gate-gap": "闸/检测在真实数据上够不着或放行（假绿）",
    "regression": "已修 issue 的同根因在别处或再次出现",
    "feature": "对标开源同类后的功能提案（只来自 peers 轮）",
}

# Surfaces a person reads (surfaces.json) → the area a finding there most likely belongs to.
SURFACE_AREA = {
    "面板": "dashboard", "站点静态页": "dashboard", "decimap": "dashboard",
    "简报": "delivery", "投递": "delivery",
    "决策台账": "risk", "DSH 插件": "dsh", "CLI": "data",
}

# Evidence taken from what the system produced today, not from reading source. A P0/P1 claim
# about money or delivery has to show the real artifact (hunting-patterns.md「别改掉的长处」).
RUNTIME_EVIDENCE = re.compile(
    r"assets/data/|memory/|portfolio\.json|logs/|data-plane|workflow-outcomes|"
    r"kcnyu\.github\.io|raw\.githubusercontent\.com|\.openclaw/cron|/root/logs/")
STYLE_ONLY_EXT = (".css", ".scss", ".html", ".svg", ".png", ".webmanifest", ".ico")
MONEY_WORDS = re.compile(r"涨跌|红绿|方向反|金额|盈亏|仓位|价格|报价|\$|HKD|USD|已实现|成本|股数")
DOC_EXT = (".md", ".txt")

# Out of the product boundary (closed-lessons 8; competitor-port 08-28/29: 31 of 55 closed
# not planned, the closures all on product shape — no execution engine, no crypto, no regtech).
OUT_OF_SCOPE = re.compile(
    r"下单|自动交易|实盘交易|执行引擎|OMS|券商接口|broker|做市|高频|HFT|加密货币|crypto|DeFi|"
    r"KYC|AML|MiFID|合规报送|参数搜索|超参|因子挖掘平台", re.I)

DIGEST_LABEL = "patrol:digest"
NOISE_LABEL = "patrol:noise"
SOURCE_LABEL = "patrol"
NOISE_REASONS = {"NOT_PLANNED"}
NOISE_LABELS = {NOISE_LABEL, "duplicate", "invalid", "wontfix"}

# Per rolling 24h. P0 is never held back; everything over budget still goes to the digest.
BUDGET = {"individual": 10, "P2": 5, "feature_7d": 2}
DIGEST_FLUSH_ITEMS = 8
DIGEST_FLUSH_AGE_S = 72 * 3600
CLUSTER_WINDOW_S = 14 * 86400


def label_taxonomy(lenses):
    """Every label patrol applies: name → (color, description)."""
    out = {
        SOURCE_LABEL: ("5319e7", "clawock-patrol 巡检经闸提报"),
        DIGEST_LABEL: ("c5def5", "巡检周期汇总：P3 与超预算的发现，一条一行"),
        NOISE_LABEL: ("eeeeee", "巡检误报/不值得修：关闭时加上，巡检据此给该类发现降权"),
    }
    colors = {"P0": "b60205", "P1": "d93f0b", "P2": "fbca04", "P3": "c2e0c6"}
    for sev in SEVERITIES:
        out[f"severity:{sev}"] = (colors[sev], f"{sev}：{SEVERITY_TEXT[sev]}"[:100])
    for area, text in AREAS.items():
        out[f"area:{area}"] = ("0e8a16", text[:100])
    for kind, text in KINDS.items():
        out[f"kind:{kind}"] = ("1d76db", text[:100])
    for lens in lenses:
        out[f"lens:{lens}"] = ("bfd4f2", f"巡检轮次范围 {lens}（axes.tsv）")
    return out


def lenses_from_axes(path):
    names = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                names.append(line.split("\t", 1)[0].strip())
    except OSError:
        pass
    return names + ["manual"]


def lens_of(task_id):
    m = re.match(r"patrol-([a-z]+)-\d{8}-\d{6}$", task_id or "")
    return m.group(1) if m else "manual"


# ── the draft's own triage block ────────────────────────────────────────────────────────────
def _field(body, names):
    for name in names:
        m = re.search(r"^\s*(?:[-*]\s*)?(?:\*\*)?" + name + r"(?:\*\*)?\s*[:：]\s*(.+?)\s*$", body, re.M)
        if m:
            return m.group(1).strip().strip("`*")
    return ""


def parse_declared(body):
    """`## 分级` fields as written; any may be empty (older drafts have none)."""
    sev = _field(body, ["严重度", "severity"]).upper()[:2]
    area = _field(body, ["领域", "area"]).lower().split()[0:1]
    kind = _field(body, ["类型", "kind"]).lower().split()[0:1]
    related = [int(n) for n in re.findall(r"#(\d{1,6})", _field(body, ["关联", "related"]))]
    return {
        "severity": sev if sev in SEVERITIES else "",
        "area": area[0] if area and area[0] in AREAS else "",
        "kind": kind[0] if kind and kind[0] in KINDS else "",
        "related": related,
    }


# ── inference when a field is missing (keyword rules fitted on the 09-21..30 history) ───────
_KIND_RULES = [
    ("false-alarm", r"误报|假红|判成.{0,12}(红|missing|失败)|报成 ?MISMATCH|false positive|误杀"),
    ("drift", r"文档|README|docstring|--help|FAQ|docs/|文案|写反|仍写|还写着|停在|口径"),
    ("gate-gap", r"闸|门控|检测|校验|watchdog|看不见|失明|零覆盖|不可达|放行|绕过|漏检|fail-open|够不着"),
]
_AREA_RULES = [
    ("security", r"转义|innerHTML|onclick|javascript:|API key|密钥|凭证|泄露|绝对路径|CVE|注入|token"),
    ("docs", r"文档|README|docstring|--help|FAQ|docs/|llms\.txt"),
    ("delivery", r"微信|投递|送达|watchdog|补发|补投|Telegram|WeChat|cron|简报|盘中|槽位|推送"),
    ("dsh", r"DSH|dsh|插件|Decision Mind"),
    ("harness", r"postflight|preflight|context|模型|LLM|敷衍词|字段名闸"),
    ("risk", r"风控|加仓|减仓|左侧|breach|止损|决策|thesis|策略"),
    ("data", r"行情|报价|价格|汇率|fx|持仓|仓位|账本|盈亏|成本|股数|shares|bars|收盘"),
    ("ops", r"CI|lane|workflow|release|pipefail|set -e|push|refresh_live|巡检|runner"),
    ("dashboard", r"面板|dashboard|卡片|页面|站点|CSS|对比度|主题"),
]


def infer(title, surface):
    text = title
    kind = next((k for k, pat in _KIND_RULES if re.search(pat, text, re.I)), "bug")
    area = next((a for a, pat in _AREA_RULES if re.search(pat, text, re.I)), "")
    area = area or SURFACE_AREA.get(surface, "ops")
    if kind == "drift" and area not in ("docs", "security"):
        # "两份实现不一致" is drift too, but a doc-shaped title is the common case.
        area = "docs" if re.search(r"文档|README|docstring|--help|FAQ|docs/", text) else area
    sev = "P2"
    if area == "docs" or kind == "drift":
        sev = "P3"
    return {"severity": sev, "area": area, "kind": kind}


# ── the verdict ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Verdict:
    severity: str
    area: str
    kind: str
    lens: str
    related: list = field(default_factory=list)
    notes: list = field(default_factory=list)   # why a declared level moved, printed and filed
    inferred: list = field(default_factory=list)

    def labels(self):
        return [SOURCE_LABEL, f"severity:{self.severity}", f"area:{self.area}", f"kind:{self.kind}",
                f"lens:{self.lens}"]


def _cap(current, cap):
    return cap if SEVERITIES.index(current) < SEVERITIES.index(cap) else current


def assess(*, title, body, surface, infra_label, refs, red, lens, noisy=None):
    """Decide severity/area/kind. Never rejects: a level the evidence does not carry is lowered,
    with the reason recorded. `noisy` is {(area, kind)} with repeated noise closures lately."""
    declared = parse_declared(body)
    guess = infer(title, surface)
    v = Verdict(severity=declared["severity"] or guess["severity"], area=declared["area"] or guess["area"],
                kind=declared["kind"] or guess["kind"], lens=lens, related=declared["related"])
    v.inferred = [k for k in ("severity", "area", "kind") if not declared[k]]
    paths = [p for p, _ in refs]
    evidence = " ".join(paths) + "\n" + (red or "")

    def lower(cap, why):
        before = v.severity
        v.severity = _cap(v.severity, cap)
        if v.severity != before:
            v.notes.append(f"{before}→{v.severity}：{why}")

    if v.kind == "feature":
        lower("P2", "功能提案最高 P2（它不是今天坏掉的东西）")
    if v.area == "docs" or (v.kind == "drift" and paths and all(p.endswith(DOC_EXT) for p in paths)):
        lower("P3", "文档/文案漂移进汇总")
    if paths and all(p.endswith(STYLE_ONLY_EXT) for p in paths) and not MONEY_WORDS.search(title):
        lower("P3", "只涉及样式/静态资源、不涉及数字或涨跌语义")
    if surface == infra_label and v.area != "security":
        lower("P2", "SURFACE 是基础设施：没有人会在任何面上看到差别")
    if SEVERITIES.index(v.severity) <= 1 and not RUNTIME_EVIDENCE.search(evidence):
        lower("P2", "P0/P1 要拿今天的真实产物作证（assets/data、memory、portfolio.json、logs、线上 URL），"
                    "判据和 文件:行 里一处都没有")
    if v.severity == "P0" and v.area not in ("data", "risk", "delivery", "security"):
        lower("P1", "P0 只留给钱/决策数字、投递与泄露")
    if noisy and (v.area, v.kind) in noisy:
        lower("P3", f"最近 14 天 {v.area}/{v.kind} 类被多次按误报/不值得修关闭（反馈回路）")
    return v


# ── grouping (Sentry-style: innermost in-app frame) ─────────────────────────────────────────
_DEF = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)|^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*(\w+)|"
                  r"^\s*(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>")


def enclosing(path, line):
    """The function/class a line sits in ('' at module level or when unreadable)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for text in reversed(lines[:max(0, min(line, len(lines)))]):
        m = _DEF.match(text)
        if m:
            return next(g for g in m.groups() if g)
    return ""


def fingerprint(refs, worktree):
    """`path::function` of the first cited code location; '' when nothing code-like is cited."""
    for path, line in refs:
        if path.endswith(DOC_EXT + STYLE_ONLY_EXT) or path.endswith(".json"):
            continue
        full = Path(worktree) / path
        if not full.is_file():
            continue
        return f"{path}::{enclosing(full, int(line)) or '<module>'}"
    return ""


# ── stores ───────────────────────────────────────────────────────────────────────────────────
def read_jsonl(path):
    rows = []
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return rows


def append_jsonl(path, row):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def cluster_target(index_rows, fp, area, open_numbers, now=None):
    """An open patrol issue filed in the last 14 days on the same frame and area, or None."""
    if not fp:
        return None
    now = now or time.time()
    for row in reversed(index_rows):
        if (row.get("route") == "issue" and row.get("fingerprint") == fp and row.get("area") == area
                and row.get("number") in open_numbers and now - row.get("ts", 0) < CLUSTER_WINDOW_S):
            return row["number"]
    return None


def route(v, index_rows, now=None):
    """'issue' or 'digest' (with the reason) under the severity and the rolling budgets."""
    now = now or time.time()
    if v.severity == "P3":
        return "digest", "P3 进汇总"
    if v.severity == "P0":
        return "issue", ""
    day = [r for r in index_rows if r.get("route") == "issue" and now - r.get("ts", 0) < 86400
           and r.get("severity") != "P0"]
    if v.kind == "feature":
        week = [r for r in index_rows if r.get("route") == "issue" and r.get("kind") == "feature"
                and now - r.get("ts", 0) < 7 * 86400]
        if len(week) >= BUDGET["feature_7d"]:
            return "digest", f"7 天内已开 {len(week)} 条功能提案（上限 {BUDGET['feature_7d']}）"
    if len(day) >= BUDGET["individual"]:
        return "digest", f"24 小时内已单独开 {len(day)} 条 P1/P2（上限 {BUDGET['individual']}）"
    if v.severity == "P2" and sum(r.get("severity") == "P2" for r in day) >= BUDGET["P2"]:
        return "digest", f"24 小时内已开 {BUDGET['P2']} 条 P2"
    return "issue", ""


# ── digest (Renovate's dashboard issue, for findings) ───────────────────────────────────────
def should_flush(pending, now=None):
    now = now or time.time()
    if not pending:
        return False
    return len(pending) >= DIGEST_FLUSH_ITEMS or now - min(r.get("ts", now) for r in pending) >= DIGEST_FLUSH_AGE_S


def render_digest(pending, today):
    by_sev = {}
    for row in pending:
        by_sev.setdefault(row.get("severity", "P3"), []).append(row)
    title = f"[patrol] 巡检汇总 {today}：{len(pending)} 条低优先级发现"
    lines = [
        "巡检把 P3（文档/样式/无害不一致）和超出当日预算的发现攒在这里，一条一行，不各开 issue。",
        "每条都过了同一道闸（文件:行可解析、RED-CHECK 实跑为红、查重），证据在折叠块里。",
        "处理方式：可以一个 PR 批量修，勾掉已修的；不成立的写一句原因后勾掉。整条汇总不值得修就以 not planned 关闭。",
        "",
    ]
    for sev in sorted(by_sev):
        lines.append(f"## {sev}（{len(by_sev[sev])}）")
        for row in by_sev[sev]:
            why = f" — {row['why']}" if row.get("why") else ""
            lines.append(f"- [ ] **{row['title'].removeprefix('[patrol] ')}** "
                         f"`area:{row.get('area')}` `kind:{row.get('kind')}` `lens:{row.get('lens')}`{why}")
        lines.append("")
    # GitHub caps an issue body at 65,536 characters; share what is left between the items.
    room = max(1500, (60000 - sum(len(x) + 1 for x in lines)) // max(1, len(pending)) - 200)
    for row in pending:
        body = row.get("body", "")
        if len(body) > room:
            body = body[:room] + "\n…（截断，完整草稿在巡检状态目录 " + row.get("draft", "") + "）"
        lines += [f"<details><summary>{row['title'].removeprefix('[patrol] ')}</summary>", "", body, "", "</details>", ""]
    top = min((r.get("severity", "P3") for r in pending), key=SEVERITIES.index)
    labels = sorted({SOURCE_LABEL, DIGEST_LABEL, f"severity:{top}"}
                    | {f"area:{r.get('area')}" for r in pending if r.get("area")})
    return title, "\n".join(lines), labels

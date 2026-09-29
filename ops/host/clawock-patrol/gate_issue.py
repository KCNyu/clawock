#!/usr/bin/env python3
"""Filing gate for clawock-patrol (ported 2026-09-17 from the 09-05 syscheck loop gate,
/root/logs/syscheck-loop/gate_issue.py, whose history the notes below keep).

2026-09-05: the 09-05 free-tier round filed 22 issues. One carried a real
finding; five were verbatim duplicate pairs; the rest asserted numbers that do
not exist in the repository (#1288 named three `timeout` values that
`grep` cannot find in the file it names; #1292 gave two pixel heights with no
selector; #1297 listed five "blind spots" with no file:line at all).

Every one of those was already forbidden by the loop's own iron rules. Writing
the rules a third time does not help — a rule the model cannot be made to obey
is not a rule, it is a hope. So the rules move here, where they are decided by
running something rather than by reading something:

  1. the draft must name a file:line that RESOLVES (file exists, line exists);
  2. the draft must carry a RED-CHECK block, and that block must actually EXIT
     NON-ZERO when run today — "今天跑是红的" stops being a claim and becomes
     an observation;
  3. the draft must not restate an issue that already exists in any state.

A draft that passes is filed with a footer recording the red-check, its exit
code and its output, so a reader can re-run the evidence.
"""

import fnmatch
import json
import os
import re
import subprocess
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

LOGDIR = Path(os.environ.get("PATROL_STATE", "/root/logs/clawock-patrol"))
WORK = Path(os.environ.get("PATROL_WORKTREE", "/root/wt-patrol"))
TOOL = Path("/root/tools/clawock-patrol")
PREFIX = "[patrol]"
# Round prompts ask for at most two issues; this caps a model that ignores it.
DAILY_CAP = int(os.environ.get("PATROL_DAILY_CAP", "999"))
CREATED = LOGDIR / "filed" / "created.tsv"
SNAPSHOT = LOGDIR / "issue_snapshot.json"
REJECTIONS = LOGDIR / "gate-rejections.log"
REPO = "KCNyu/clawock"
RED_TIMEOUT = int(os.environ.get("RED_CHECK_TIMEOUT", "240"))

# A red-check runs unsandboxed as root. It is meant to read the worktree and
# exit non-zero; it is not meant to touch the live runtime or the outside world.
FORBIDDEN = [
    r"/root/\.openclaw/workspace",
    r"\bgh\s+(issue|pr)\s+(create|comment|close|merge|edit)\b",
    r"\bgit\s+(push|commit|checkout|reset|stash|rebase|merge)\b",
    r"\brm\s+-[rf]",
    r"\bcrontab\b",
    r"\bsystemctl\b",
    r"\bpip\s+install\b",
    r"\bnpm\s+(i|install|ci)\b",
    r">\s*/root/(?!logs/clawock-patrol)",
    # Axis L (面板性能/交互) must not measure by rendering. This box runs at
    # ~200MB available with 1.5G of swap in use, its headless rAF is ~9fps, and
    # anything timed under that load is not evidence (memory:
    # load-invalidates-perf-measurements, clawock-verdict-deck-v6). A red-check
    # that boots a browser produces a number nobody can trust and may thrash the
    # host while a live cron slot is due. Rendered proof belongs in CI's spec
    # files; here the criterion has to be static — bytes, AST, CSS, attributes.
    r"\b(playwright|puppeteer|chromium|google-chrome|headless)\b",
    r"\bhttp\.server\b|\bhttp-server\b",
]

# The leading `\b` used to eat the dot of a dotfile path: `.github/workflows/ci.yml:479`
# matched as `github/workflows/ci.yml`, which does not exist, so a correctly written
# reference was rejected as "编的数字" (R148, 2026-09-05). Anchor on a non-path char
# instead of a word boundary so a path may legally start with a dot.
# 扩展名白名单。2026-09-05 深夜实测：原来的列表没有 css / html / jsonl / tsx，
# 于是 `site/assets/css/dashboard.css:412` 与 `site/index.html:88` 这类引用**根本
# 不被识别**——L 维（面板）最该引的两种文件引不了，闸会回一句「草稿里没有任何
# 文件:行」。#1339（dashboard.css 的 transition 不尊重 prefers-reduced-motion）
# 就是靠别的文件的 文件:行 混过来的，证据锚点指向了别处。
# 与 09-05 下午那个 `\b` 吃掉 dotfile 点的 bug 同一族：**一道拦假阳性的闸，自己的
# 假阳性最贵——它拒掉的东西没人复核。**
_EXT = r"py|pyi|js|mjs|cjs|jsx|ts|tsx|json|jsonl|ya?ml|sh|md|toml|css|scss|html?|txt|cfg|ini|sql"
FILE_LINE = re.compile(
    r"(?:^|[^\w./\-])((?:[\w.\-]+/)+[\w.\-]+\.(?:" + _EXT + r")"
    r"|[\w\-][\w.\-]*\.(?:" + _EXT + r"))[:：](\d{1,6})\b",
    re.M)
RED_BLOCK = re.compile(r"<!--\s*RED-CHECK\s*\n(.*?)\n\s*-->", re.S)


def die(reason, detail=""):
    msg = f"GATE REJECT: {reason}"
    print(msg, file=sys.stderr)
    if detail:
        print(detail.rstrip()[:4000], file=sys.stderr)
    try:
        with REJECTIONS.open("a", encoding="utf-8") as f:
            f.write(f"[{subprocess.run(['date','+%F %T'],capture_output=True,text=True).stdout.strip()}] "
                    f"{DRAFT.name}: {reason}\n")
            if detail:
                f.write("    " + detail.rstrip()[:1500].replace("\n", "\n    ") + "\n")
    except Exception:
        pass
    sys.exit(2)


def normalise(text):
    text = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^a-z0-9一-鿿]+", " ", text).strip()


def tokens(text):
    t = normalise(text)
    # CJK has no spaces; use bigrams for it and words for the rest.
    words = set(re.findall(r"[a-z0-9_]{3,}", t))
    cjk = re.findall(r"[一-鿿]+", t)
    for run in cjk:
        words.update(run[i:i + 2] for i in range(len(run) - 1))
    return words


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── 0. the draft ─────────────────────────────────────────────────────────────
if len(sys.argv) != 2:
    print("usage: file_issue.sh <draft.md>", file=sys.stderr)
    sys.exit(64)

DRAFT = Path(sys.argv[1]).resolve()
if not DRAFT.is_file():
    die(f"草稿不存在：{DRAFT}")
body = DRAFT.read_text(encoding="utf-8")

title_match = re.search(r"^#{1,3}\s+(.+?)\s*$", body, re.M)
if not title_match:
    die(f"草稿没有标题行。第一个 `#`/`##` 标题必须是 `{PREFIX} …`。")
title = title_match.group(1).strip()
if not title.startswith(PREFIX + " "):
    die(f"标题必须以 `{PREFIX} ` 开头，现在是：{title}")

# ── 0.5 daily cap ────────────────────────────────────────────────────────────
import time
_recent = 0
if CREATED.is_file():
    for _line in CREATED.read_text(encoding="utf-8").splitlines():
        _ts = _line.split("\t", 1)[0]
        if _ts.isdigit() and time.time() - int(_ts) < 86400:
            _recent += 1
if _recent >= DAILY_CAP and not os.environ.get("GATE_DRY_RUN"):
    die(f"过去 24 小时已经开了 {_recent} 条 patrol issue（上限 {DAILY_CAP}）。"
        "这条先写进 ledger.md 的「候选」里，配额空出来的轮次再提。")

if len(body) < 600:
    die(f"草稿只有 {len(body)} 个字符，太短——六段/三段格式写不下。")

# ── 0.7 shapes that were closed again and again (closed-lessons.md) ─────────
# 2026-09-17: of 239 loop issues since 08-25, 90 were closed without a PR. The shapes below
# were never worth scheduling, or were false because the consumer lived outside the grep.
LESSONS = "/root/tools/clawock-patrol/closed-lessons.md"
_head_text = title + "\n" + body[:1500]
NEVER = re.compile(r"拆分|拆成|拆出|行数过多|函数过长|模块过大|职责过多|单一职责|god (?:module|function)|eager import|"
                   r"import 耗时|顶层 import|magic number|魔法数|散落|注册表|统一常量|抽成常量|重构", re.I)
_m = NEVER.search(_head_text)
if _m:
    # kcn 2026-09-17 wants coupling and structure looked at too, so these are not refused outright;
    # but every past one without a real consequence was closed, so a real consequence is required.
    _pm = re.search(r"^\s*(?:[-*]\s*)?(?:\*\*)?先例(?:\*\*)?\s*[:：]\s*(.+?)\s*$", body, re.M)
    _nums = re.findall(r"#(\d{1,6})", _pm.group(1)) if _pm else []
    _real = []
    for _n in _nums[:3]:
        _r = subprocess.run(["gh", "api", f"repos/{REPO}/issues/{_n}", "-q", ".title"],
                            capture_output=True, text=True, timeout=60)
        if _r.returncode == 0 and _r.stdout.strip():
            _real.append(_n)
    if not _real:
        die(f"草稿是重构/拆分/耦合/散落类（匹配「{_m.group(0)}」）。这类以前没有真实后果的全被关了"
            f"（#1318 #1319 #1322 #1326 #1346 #1359 #1456 #1481，见 {LESSONS} 第 3、4 条）。"
            "要提就加一行 `先例: #N`，N 是这个耦合/结构**真实引发过**的 bug issue 或修复 PR，并在正文说清因果。")
NO_CONSUMER = re.compile(r"无人消费|没人读|无人读取|未被(?:使用|消费|读取|调用)|从未被|没有(?:任何)?(?:消费|调用|清理|校验|测试)|"
                         r"0 ?(?:个)?消费者|never (?:used|read|consumed|called)|unused|no consumer|dead code|死代码", re.I)
_m = NO_CONSUMER.search(_head_text)
_red_for_shape = RED_BLOCK.search(body)
if _m:
    _red_txt = _red_for_shape.group(1) if _red_for_shape else ""
    # shell `git grep …` or subprocess ["git", "grep", …]; a `--` pathspec limits it to some directories
    _whole = [l for l in _red_txt.splitlines()
              if re.search(r"git['\",\s]+grep", l) and not re.search(r"grep\b[^\n]*?['\"\s]--['\"\s]", l)]
    if not _whole:
        die(f"草稿声称「{_m.group(0)}」。这是被关得最多的形态：消费者/清理器/测试在 src 以外（ops/、skills/、site/js、tests、*_bundle），"
            "只是没搜到（#1320 #1445 #1447 #1469 #1095）。RED-CHECK 里必须有一条**不带路径限制**的 "
            "`git grep` 搜整个仓库，并由它的结果得出红。见 " + LESSONS + " 第 1 条。")

# ── 0.8 the draft must show it tried to refute itself ────────────────────────
REFUTE = re.compile(r"^#{1,4}\s*反证自查\s*$", re.M)
def _field(name):
    m = re.search(r"^\s*(?:[-*]\s*)?(?:\*\*)?" + name + r"(?:\*\*)?\s*[:：]\s*(.+?)\s*$", body, re.M)
    return m.group(1).strip() if m else ""
if not REFUTE.search(body):
    die("草稿缺 `## 反证自查` 一节。五行，缺一不可（以前 90 条 issue 就是缺了这一步被关的，见 " + LESSONS + "）：\n"
        "  全仓搜索: <git grep 命令 + 命中几处、在哪些目录>\n"
        "  历史: <git log -S / blame 结论，或相关 issue/PR 号：这段何时为何写成这样、是否修过>\n"
        "  设计意图: <附近注释/文档有没有解释这个取舍；有的话为什么仍是缺陷>\n"
        "  量化: <影响的实测数字：次数/字节/秒/条数>\n"
        "  对照已关: <最像的已关 issue 号及为什么这条不同；或「无同形态」>")
_missing = []
_search = _field("全仓搜索")
if "grep" not in _search:
    _missing.append("`全仓搜索:` 要写出实际跑过的 git grep 命令和命中情况")
_hist = _field("历史")
if not re.search(r"git (?:log|blame)|#\d+|\b[0-9a-f]{7,40}\b", _hist):
    _missing.append("`历史:` 要有 git log/blame 的结论、commit 或 issue/PR 号")
if len(_field("设计意图")) < 8:
    _missing.append("`设计意图:` 要写清附近注释/文档怎么说")
if not re.search(r"\d", _field("量化")):
    _missing.append("`量化:` 要有实测数字")
_closed = _field("对照已关")
if not (re.search(r"#\d+", _closed) or "无同形态" in _closed):
    _missing.append("`对照已关:` 要写最像的已关 issue 号，或「无同形态」")
if _missing:
    die("`## 反证自查` 不完整：\n  " + "\n  ".join(_missing))

# ── 1. file:line must resolve ────────────────────────────────────────────────
refs = FILE_LINE.findall(body)
if not refs:
    die("草稿里没有任何 `文件:行`。铁律第一条：写不出 文件:行 不许开 issue。")

_SKIP = {".git", "node_modules", "__pycache__", ".venv", "dist", "lib"}


def _candidates(path):
    """Resolve a reference. A bare basename (`theses.py:14`) is how the drafts
    actually write it, and punishing that would only stop real findings from
    being filed — so search the tree for it."""
    direct = WORK / path
    if direct.is_file():
        return [direct]
    if "/" in path:
        return []
    found = []
    for p in WORK.rglob(path):
        if any(part in _SKIP for part in p.relative_to(WORK).parts):
            continue
        if p.is_file():
            found.append(p)
        if len(found) > 12:
            break
    return found


bad = []
good = 0
for path, line in refs:
    cands = _candidates(path)
    if not cands:
        bad.append(f"{path}:{line} — 这个文件在 {WORK} 里根本不存在")
        continue
    lines = []
    for c in cands:
        try:
            lines.append(sum(1 for _ in c.open("rb")))
        except OSError:
            lines.append(0)
    if int(line) > max(lines):
        where = cands[lines.index(max(lines))].relative_to(WORK)
        bad.append(f"{path}:{line} — {where} 只有 {max(lines)} 行")
        continue
    good += 1
if bad:
    die("草稿引的 文件:行 有对不上的（这就是 #1288 那类「数字是编的」的形状）：",
        "\n".join(bad))
if good == 0:
    die("没有一个 文件:行 能解析。")

# ── 1.5 the draft must name a surface a person actually looks at ─────────────
#
# 2026-09-05 深夜关掉的 #1344 / #1345 / #1346 / #1347：四条的「现状」都是量出来的
# （闸做到了它答应的事），四条的「影响」都是自己推的——一条把测试文件的 docstring
# 当现状，一条把 `rename` 当回收，一条把 import 时间当运行时间，一条要拿 0.5s/天
# 换一类正确性风险。任务书 §0.2(5)「纯内部卫生不排期」当时已经写着了。
#
# 一条模型不会遵守的规则不是规则，是愿望。所以它搬到这里：
#   - 面是**封闭集合**（surfaces.json，手维护——从没有过生成器；
#     tests/test_patrol_surfaces.py 对着站点实际公开的文件求差集兜住，#2149）；
#   - 声称某个面，就得**看过那个面上的东西**——它的路径要在你的 文件:行 或
#     RED-CHECK 里出现过。只翻了 `src/` 的结构却说「kcn 会看到差别」，当场拒。
#   - 真的只是基础设施，写 `SURFACE: 无（基础设施）` 走逃生口，但要付**先例**：
#     一个本仓真实存在的 issue/PR 编号，说明这类问题真的害到过人。
#
# 这道闸买到的是「你至少看过一个人会看到的东西」，**不是**「这条值得做」——
# 后者仍要人复核（#1345 引了 `memory/*-pre-open.md` 也能过这一关）。
SURFACES_JSON = TOOL / "surfaces.json"
SURFACE_SECTION = re.compile(r"^#{1,4}\s*用户能看到的差别\s*$", re.M)
SURFACE_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?SURFACE(?:\*\*)?\s*[:：]\s*(.+?)\s*$", re.M)
NOW_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?现在(?:\*\*)?\s*[:：]\s*(.+?)\s*$", re.M)
AFTER_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?修完(?:\*\*)?\s*[:：]\s*(.+?)\s*$", re.M)
PRECEDENT_LINE = re.compile(r"^\s*(?:[-*]\s*)?(?:\*\*)?先例(?:\*\*)?\s*[:：]\s*(.+?)\s*$", re.M)
# 任何看起来像仓内路径的 token，用来核「你有没有碰过那个面」
PATHISH = re.compile(r"[\w.\-]*(?:/[\w.\-*]+)+|[\w\-][\w.\-]*\.(?:json|jsonl|md|css|js|html|txt|webmanifest)")

try:
    _surf = json.loads(SURFACES_JSON.read_text(encoding="utf-8"))
    SURFACE_MAP = _surf["surfaces"]
    INFRA_LABEL = _surf["infra_label"]
except Exception as e:
    die(f"读不到 {SURFACES_JSON}（{e}）。这道闸的封闭集合就在那份文件里，缺了它闸不能放行。")

if not SURFACE_SECTION.search(body):
    die("草稿缺 `## 用户能看到的差别` 一节。三行，缺一不可：\n"
        f"  SURFACE: <{' / '.join(SURFACE_MAP)} / {INFRA_LABEL}>\n"
        "  现在: <今天 kcn 打开它看到什么>\n"
        "  修完: <改完他看到什么，必须和上一行不同>\n"
        "面的清单与每个面的路径见 /root/tools/clawock-patrol/surfaces.json。")

_sm = SURFACE_LINE.search(body)
if not _sm:
    die("`## 用户能看到的差别` 里没有 `SURFACE:` 行。")
surface = _sm.group(1).strip().strip("`*")
_now = NOW_LINE.search(body)
_after = AFTER_LINE.search(body)
if not _now or not _after:
    die("`## 用户能看到的差别` 里缺 `现在:` 或 `修完:` 行。这两行是这条 issue 的产品判断，"
        "不是复述 §1 的现象。")
now_txt, after_txt = _now.group(1).strip(), _after.group(1).strip()
if len(now_txt) < 8 or len(after_txt) < 8:
    die(f"`现在:`/`修完:` 太短（{len(now_txt)}/{len(after_txt)} 字符）——"
        "写清楚一个人在那个面上看到的差别。")
if normalise(now_txt) == normalise(after_txt):
    die("`现在:` 和 `修完:` 是同一句话。说不出差别，就是没有差别。")

if surface == INFRA_LABEL:
    _pm = PRECEDENT_LINE.search(body)
    nums = re.findall(r"#(\d{1,6})", _pm.group(1)) if _pm else []
    if not nums:
        die(f"`SURFACE: {INFRA_LABEL}` 是逃生口，要付先例：加一行 `先例: #N`，"
            "N 是本仓一条真实的 issue/PR，说明这类问题**真的害到过**。"
            "（2026-09-05 那四条全栽在这里：内部卫生的影响是推出来的，不是发生过的。）")
    ok_nums = []
    for n in nums[:3]:
        r = subprocess.run(["gh", "api", f"repos/{REPO}/issues/{n}",
                            "-q", ".title"], capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and r.stdout.strip():
            ok_nums.append(f"#{n} {r.stdout.strip()[:60]}")
    if not ok_nums:
        die(f"`先例:` 给的编号（{', '.join('#' + n for n in nums[:3])}）在 {REPO} 里都查不到。")
    print(f"gate: SURFACE={INFRA_LABEL}（逃生口）先例={' | '.join(ok_nums)}", file=sys.stderr)
    with (LOGDIR / "infra-escape.log").open("a", encoding="utf-8") as f:
        f.write(f"{DRAFT.name}\t{title}\t{'|'.join(ok_nums)}\n")
elif surface not in SURFACE_MAP:
    die(f"`SURFACE: {surface}` 不在清单里。只能填这几个之一："
        f"{' / '.join(SURFACE_MAP)} / {INFRA_LABEL}。见 /root/tools/clawock-patrol/surfaces.json。")
else:
    _red_m = RED_BLOCK.search(body)
    haystack = " ".join([p for p, _ in refs] + ([_red_m.group(1)] if _red_m else []))
    seen_paths = set(PATHISH.findall(haystack))
    pats = SURFACE_MAP[surface]["patterns"]
    hit = next((f"{p} ~ {pat}" for p in sorted(seen_paths) for pat in pats
                if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat.rstrip("/*") + "/*")
                or p == pat), None)
    if not hit:
        die(f"你写的是 `SURFACE: {surface}`（{SURFACE_MAP[surface]['who']}），"
            f"但你的 文件:行 和 RED-CHECK 里没有一处碰到这个面：\n"
            f"  这个面的路径：{' , '.join(pats)}\n"
            f"  你看过的路径：{' , '.join(sorted(seen_paths)[:12]) or '(一个都没有)'}\n"
            "声称一个人会看到差别，就得看过那个人看的东西。真的只是基础设施，"
            f"就写 `SURFACE: {INFRA_LABEL}` 并付先例。")
    print(f"gate: SURFACE={surface}（命中 {hit}）", file=sys.stderr)

# ── 2. the red-check must actually be red ────────────────────────────────────
m = RED_BLOCK.search(body)
if not m:
    die("草稿没有 RED-CHECK 块。铁律第三条要求「今天跑是红的、修完会绿」的可执行判据；"
        "现在它必须是机器能跑的，格式：\n"
        "<!-- RED-CHECK\n"
        "cd /root/wt-patrol && PYTHONPATH=src python3 -c '...; assert False'\n"
        "-->\n"
        "它必须以非零退出码结束（红），否则这条发现不成立。")
red = m.group(1).strip()
if not red:
    die("RED-CHECK 块是空的。")
for pat in FORBIDDEN:
    if re.search(pat, red):
        if "playwright" in pat or "http.server" in pat:
            die(f"RED-CHECK 里起了浏览器/服务器（匹配 /{pat}/）。**不是嫌慢，是这台机器上"
                "渲染出来的数字不可信**：available 内存 ~200MB、swap 已用 1.5G、headless rAF 只有 ~9fps，"
                "而且它可能在一个 live cron 槽位到点时把主机拖进换页。\n"
                "面板类判据只能是静态/解析式的：字节数、选择器计数、CSS 规则、HTML 属性、AST、"
                "ECharts option 对象、grep 出来的调用点。渲染证据交给 CI 的 tests/*.spec.js。\n")
        die(f"RED-CHECK 里有禁止的操作（匹配 /{pat}/）。判据只能读，不许写 live、不许推、不许改环境。")

print(f"gate: running RED-CHECK ({RED_TIMEOUT}s budget) …", file=sys.stderr)
env = dict(os.environ)
env.pop("CLAWOCK_WORKSPACE", None)
env["PYTHONPATH"] = f"{WORK}/src"
try:
    proc = subprocess.run(["bash", "-c", red], cwd=str(WORK), env=env,
                          capture_output=True, text=True, timeout=RED_TIMEOUT)
except subprocess.TimeoutExpired:
    die(f"RED-CHECK 超过 {RED_TIMEOUT}s 没跑完。判据必须是能当场跑完的，不是一次审计。")
out = (proc.stdout + proc.stderr).strip()
if proc.returncode == 0:
    die("RED-CHECK 跑出来是**绿的**（exit 0）。你说它今天是坏的，但判据说它今天是好的——"
        "这条发现不成立，把证伪结果写进 ledger.md 就好。",
        out or "(判据没有任何输出)")
if not out:
    die(f"RED-CHECK 以 exit {proc.returncode} 结束但**没有任何输出**。"
        "红必须能被人读懂：把断言信息/差集/数字打出来。")

# 「exit≠0 且有输出」区分不了两件事：判据跑出来是红的，和判据自己跑不起来。
# #1332 就是从这个洞进来的——块里是裸 Python，闸用 bash 跑它，
# `import re` ⇒ "bash: import: command not found" ⇒ exit 2 + stderr 有输出 ⇒ 放行。
# 下面这些是「解释器/shell 在抱怨，判据一行都没执行」的无歧义信号。
# AssertionError / SystemExit / FileNotFoundError 不在其中：那些是判据自己在说话。
# 「exit≠0 且有输出」区分不了两件事：判据跑出来是红的，和判据自己跑不起来。
# 这个洞补过两次，两次都是**黑名单**，两次都漏：
#   #1332 裸 Python ⇒ bash 报 "import: command not found"  → 加了 command not found
#   #1344 裸 Python ⇒ bash 报 "syntax error near unexpected token" → 加了 bash 语法错
#   #1354 判据里正则写错 ⇒ `re.error: unbalanced parenthesis` → **又漏了**
# 每次都是「再想一个可能的异常名」，而可能的异常名是无穷的。所以这里反过来：
#
#   **白名单**——只有 AssertionError 和 SystemExit 算「判据自己得出的结论」。
#
# 判据本来就该写成 `assert ...` 或 `sys.exit(1)`；别的异常从 traceback 里冒出来，
# 说明它在算出结论之前就死了，红的是判据不是仓库。
CRITERION_EXCEPTIONS = ("AssertionError", "SystemExit")
# traceback 的最后一行长成 `SomeError: message` 或 `re.error: message`（小写也有），
# 所以只取第一个冒号前那个带点的标识符，别去猜后缀。
TRACEBACK_LAST = re.compile(r"^([A-Za-z_][\w.]*)\s*(?::|$)")

if proc.returncode == 127:
    die("RED-CHECK 以 exit 127 结束：命令不存在，判据从没跑起来。"
        "红必须是判据自己得出的结论，不是 shell 在抱怨。", out)

_shell_complaints = [
    (r"command not found", "块里是裸 Python，但闸是用 bash 跑的。"
                           "把它包进 `python3 -c \"...\"` 或写成 shell。"),
    (r": not found", "命令不存在——判据一行都没执行。"),
    (r"syntax error near unexpected token", "bash 在报语法错——块里多半是裸 Python。"),
    (r"syntax error: unexpected end of file", "bash 语法没闭合，判据一行都没执行。"),
    (r"unexpected EOF while looking for matching", "引号/括号没闭合，判据一行都没执行。"),
    (r"^bash: -c: line \d+:", "bash 在抱怨这个块本身，不是判据在说话。"),
]
for pat, hint in _shell_complaints:
    if re.search(pat, proc.stderr, re.MULTILINE):
        die(f"RED-CHECK **没有真正执行**（stderr 匹配 /{pat}/）。{hint} "
            "「exit≠0」只说明它失败了，不说明它测过什么——"
            "红必须是判据自己得出的结论。", out)

# Python 侧：看 traceback 最后那个异常是什么。
if "Traceback (most recent call last)" in proc.stderr:
    raised = TRACEBACK_LAST.findall(proc.stderr.rstrip().splitlines()[-1].strip())
    name = raised[0] if raised else "(读不出异常名)"
    if name.rsplit(".", 1)[-1] not in CRITERION_EXCEPTIONS:
        die(f"RED-CHECK 抛的是 **{name}**，不是 AssertionError/SystemExit —— "
            "判据在算出结论之前就崩了，红的是判据本身不是仓库。"
            "把断言写成 `assert <条件>, '<说明>'` 或 `sys.exit(1)`；"
            "崩溃不是发现。（#1354 就是判据里的正则写错，"
            "`re.error: unbalanced parenthesis`，闸当时放行了。）", out)

# ── 2.9 the red-check has to look at the thing you say is broken ─────────────
#
# #1355 的判据是完整的一行：
#     python3 -c "import os; print('Schema drift confirmed'); sys.exit(1)"
# 没打开任何文件、没 grep、没断言——**只是打印一句话然后退 1**。它符合前面每一道检查：
# 有 文件:行（解析得开）、exit≠0、有输出、异常是 SystemExit（判据自己在说话）。
#
# 缺的是最朴素的一条：**你说坏掉的那个文件，你的判据到底有没有碰过它。**
_red_paths = set(PATHISH.findall(red))
_named = {p for p, _ in refs}
if _named and not (_red_paths & _named):
    _bare = {Path(p).name for p in _named}
    if not any(b in red for b in _bare):
        die("RED-CHECK **没有碰过你点名的任何一个文件**。\n"
            f"  你写的 文件:行：{' , '.join(sorted(_named)[:8])}\n"
            f"  判据里出现的路径：{' , '.join(sorted(_red_paths)[:8]) or '(一个都没有)'}\n"
            "判据要读你说坏掉的那个东西，然后由它得出红——"
            "「打印一句话再 sys.exit(1)」满足前面每一道检查，却什么都没测（#1355 就是这么进来的）。",
            red[:600])

# ── 3. dedup against every issue in every state ──────────────────────────────
existing = []
if SNAPSHOT.is_file():
    try:
        snap = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        existing += snap.get("all") or []
    except Exception as e:
        print(f"gate: warn: issue_snapshot.json unreadable ({e}) — 查重降级为只比草稿",
              file=sys.stderr)

head = body[:1200]
mine_t = tokens(title)
mine_h = tokens(head)
hits = []
for issue in existing:
    other = issue.get("title") or ""
    jt = jaccard(mine_t, tokens(other))
    ratio = SequenceMatcher(None, normalise(title), normalise(other)).ratio()
    if jt >= 0.55 or ratio >= 0.72:
        hits.append(f"#{issue.get('number')} [{issue.get('state')}] {other}  "
                    f"(题名 jaccard={jt:.2f} ratio={ratio:.2f})")

for prior in sorted((LOGDIR / "filed").glob("*.md")):
    if prior.resolve() == DRAFT:
        continue
    try:
        ptext = prior.read_text(encoding="utf-8")
    except Exception:
        continue
    pt = re.search(r"^#\s+(.+?)\s*$", ptext, re.M)
    jt = jaccard(mine_t, tokens(pt.group(1))) if pt else 0.0
    jh = jaccard(mine_h, tokens(ptext[:1200]))
    if jt >= 0.6 or jh >= 0.72:
        hits.append(f"草稿 {prior.name} (题名 jaccard={jt:.2f} 正文 jaccard={jh:.2f})")

if hits:
    die("查重不过——这条和已经存在的东西太像了（09-05 那轮开了 5 对逐字重复）：",
        "\n".join(hits[:8]) + "\n\n要么补证据到原 issue，要么写清楚新载体在哪、"
        "并让标题不再是同一句话。")

# ── 4. file it ───────────────────────────────────────────────────────────────
footer = (
    "\n\n---\n\n"
    "<details><summary>patrol-gate: RED-CHECK 实测（exit "
    f"{proc.returncode}）</summary>\n\n"
    "```\n" + red + "\n```\n\n"
    "```\n" + out[-3000:] + "\n```\n\n</details>\n"
    "<!-- patrol-gate: passed file_line_refs=" + str(good) +
    f" red_exit={proc.returncode} -->\n"
)
final = LOGDIR / "filed" / (DRAFT.name + ".body")
final.parent.mkdir(parents=True, exist_ok=True)
final.write_text(body[title_match.end():].lstrip() + footer, encoding="utf-8")

if os.environ.get("GATE_DRY_RUN"):
    print(f"gate: DRY RUN — 会提的标题是：{title}\n  body: {final}", file=sys.stderr)
    sys.exit(0)

r = subprocess.run(["gh", "issue", "create", "-R", REPO,
                    "--title", title, "--body-file", str(final)],
                   capture_output=True, text=True)
if r.returncode != 0:
    die("gh issue create 失败", r.stdout + r.stderr)
url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "(no url)"
print(f"gate: PASS — filed {url}")
(LOGDIR / "filed" / DRAFT.name).write_text(body, encoding="utf-8")   # later drafts dedupe against it
with CREATED.open("a", encoding="utf-8") as f:
    f.write(f"{int(time.time())}\t{DRAFT.name}\t{title}\t{url}\t{os.environ.get('AGENT_DISPATCH_TASK_ID', '-')}\n")
# One short Telegram line per filed issue (kcn 2026-09-26: patrol traffic is Telegram-only;
# WeChat drops silently on a cold session); the daily cap bounds how many that can be.
# A failed send is reported, never silent (review 2026-09-26: the return code was ignored, so a
# missing TELEGRAM_TARGET or a gateway error looked like a delivered alert). The issue is filed
# either way; the notification never changes the gate's verdict. The send goes through
# clawock's delivery provider, which sets the runtime's PATH and gateway timeout and honours
# CLAWOCK_DELIVERY_DISABLED. This file is installed outside any checkout, so it imports clawock
# from the patrol's own worktree (origin/master), not from whatever python3 happens to find.
try:
    _CHECKOUT = WORK
    sys.path.insert(0, str(_CHECKOUT))
    sys.path.insert(0, str(_CHECKOUT / "src"))
    conf = dict(l.split("=", 1) for l in Path("/root/tools/agent-dispatch/notify.env").read_text().splitlines()
                if "=" in l and not l.lstrip().startswith("#"))
    target = conf.get("TELEGRAM_TARGET", "").strip().strip("'\"")
    if not target:
        print("gate: notify skipped (TELEGRAM_TARGET not configured)", file=sys.stderr)
    else:
        from clawock.providers.delivery import OpenClawDelivery
        sent = OpenClawDelivery(timeout=60).send(
            conf.get("TELEGRAM_CHANNEL", "telegram").strip().strip("'\"") or "telegram", target,
            f"🔎 clawock 巡检开了 issue：{title}\n{url}")
        if sent.status == "failed":
            print(f"gate: notify failed ({sent.detail[-200:]})", file=sys.stderr)
except Exception as e:
    print(f"gate: notify failed ({e})", file=sys.stderr)

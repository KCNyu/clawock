"""EN/ZH README structural parity + house-style guards.

The two READMEs translate meaning, not syntax, so we cannot compare text — but
their skeleton (section count, collapsibles, embedded assets, primary links) must
stay identical so the versions cannot quietly drift. We also lock in the redesign
decisions: no decorative emoji in headings (the "AI-generated README" tell), and no
live/changing numbers hard-coded into evergreen copy.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / "README.md").read_text(encoding="utf-8")
ZH = (ROOT / "README.zh.md").read_text(encoding="utf-8")

# Pictographic emoji codepoints (symbols, pictographs, flags, dingbats, variation
# selector), checked as explicit ranges instead of a regex character class — it reads
# clearly and avoids flagging the wide unicode ranges as a suspicious regex range.
# Deliberately excludes the arrow block (←↑→ are legitimate typography used in the
# schedule and repo-layout blocks) and the CJK range (Chinese prose is fine).
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF), (0x2600, 0x27BF), (0x1F1E6, 0x1F1FF),
    (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F),
)


def _first_emoji(text):
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _EMOJI_RANGES):
            return ch
    return None

EN_H2 = [
    "What this is", "How it works", "The information layer", "How it decides",
    "The debate", "The public scorecard", "What we tested, and what failed",
    "What the code enforces", "Daily rhythm", "Run it on your own book",
    "Explore the system", "Scope, disclaimer, and license",
]
ZH_H2 = [
    "这是什么", "怎么跑的", "信息层", "怎么做决策", "辩论", "公开战绩",
    "测了什么，什么没通过", "代码强制执行的规矩", "每日节奏",
    "在你自己的账本上跑", "逛一逛这套系统", "范围、免责与许可",
]


def _h2(md):
    return [ln for ln in md.splitlines() if ln.startswith("## ")]


def _details(md):
    return md.count("<summary>")


def _assets(md):
    return sorted(set(re.findall(r"(?:site/)?assets/[\w./-]+\.(?:svg|png|gif)", md)))


def test_section_count_matches():
    assert len(_h2(EN)) == len(_h2(ZH)) > 0


def test_details_count_matches():
    assert _details(EN) == _details(ZH) > 0


def test_embedded_assets_match():
    # Same image assets, in both files, and each one exists on disk.
    assert _assets(EN) == _assets(ZH)
    for rel in _assets(EN):
        assert (ROOT / rel).exists(), f"README references missing asset {rel}"


def test_primary_links_present_in_both():
    for target in (
        "https://kcnyu.github.io/clawock/",
        "https://kcnyu.github.io/clawock/briefs.html",
        "docs/operations/cron-schedules.md",
        "docs/legal/third-party-data.md",
        "LICENSE",
    ):
        assert target in EN and target in ZH, f"{target} missing from a README"


def test_language_switch_links_cross():
    assert "README.zh.md" in EN
    assert "README.md" in ZH


def test_research_surfaces_stay_in_both_languages():
    assert "### Research surfaces" in EN
    assert "### 研究入口" in ZH
    for target in (
        "skills/us-stock-analysis/SKILL.md",
        "skills/hk-stock-analysis/SKILL.md",
        "skills/portfolio-risk-review/SKILL.md",
        "skills/portfolio-swarm-review/SKILL.md",
        "skills/serenity-skill/SKILL.md",
        "skills/earnings-review/SKILL.md",
        "skills/entry-gate/SKILL.md",
    ):
        assert target in EN and target in ZH, f"{target} missing from a README"


def test_per_run_context_layers_documented_in_both_languages():
    """The layered view must stay honest about counts: it claims a block count per
    run, and those come from the preflights' own context dicts."""
    import re

    assert "### What each run actually receives" in EN
    assert "### 每种运行实际拿到什么" in ZH

    root = Path(__file__).resolve().parents[1]
    counts = {}
    for name, path in (
        ("brief", "instances/kcnyu/src/clawock_kcnyu/harness/brief_preflight.py"),
        ("report", "instances/kcnyu/src/clawock_kcnyu/harness/report_preflight.py"),
        ("intraday", "instances/kcnyu/src/clawock_kcnyu/harness/intraday_preflight.py"),
    ):
        source = (root / path).read_text()
        block = re.search(r"\n    (?:context|result) = \{(.*?)\n    \}", source, re.S)
        assert block, name
        counts[name] = len(re.findall(r"'([a-z_0-9]+)':", block.group(1)))

    for md, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        row = next(line for line in md.splitlines()
                   if line.startswith("| **Blocks**") or line.startswith("| **块数**"))
        # split, not a shared-delimiter regex: `| 36 | 15 | 18 |` consumes the
        # middle pipe and silently drops a column
        stated = [int(cell.strip()) for cell in row.split("|")
                  if cell.strip().isdigit()]
        assert stated == [counts["brief"], counts["report"], counts["intraday"]], (
            f"{name} block counts drifted from the preflights: {stated} vs {counts}"
        )


def test_the_information_layer_table_adds_up_in_both_languages():
    """The one structural number in the README that nothing was checking.

    Everything else with a count behind it is pinned — the per-run block counts
    read the preflights' own context dicts, the section and asset lists are
    compared across languages. The information-layer table was prose: a headline
    ("N fetch and compute modules across M layers") sitting above a table whose
    rows carry the per-layer counts, in two languages, with nothing tying the
    four numbers together. Editing one row and forgetting the headline is a
    silent, plausible edit, and so is fixing it in one language only.

    What this does NOT prove, stated so nobody reads more into a green: it does
    not verify the modules exist or that the taxonomy still matches the package.
    That mapping has no artifact behind it — the layers were drawn when these
    were files under `scripts/data/`, which #429 deleted — so a test claiming to
    check it would be encoding a guess as truth. This checks the four numbers
    agree; grounding the taxonomy is separate work.
    """
    seen = {}
    for md, name, pattern in (
        (EN, "README.md", r"\*\*(\d+) fetch and compute modules across (\d+) layers\*\*"),
        (ZH, "README.zh.md", r"\*\*(\d+) 层、(\d+) 个抓取与计算模块\*\*"),
    ):
        headline = re.search(pattern, md)
        assert headline, f"{name}: the information-layer headline changed shape"
        # ZH states layers first, EN states modules first.
        modules, layers = (headline.group(1), headline.group(2))
        if name.endswith("zh.md"):
            layers, modules = modules, layers

        rows = [ln for ln in md.splitlines() if re.match(r"^\| \d+ · ", ln)]
        assert len(rows) == int(layers), (
            f"{name}: headline says {layers} layers, table has {len(rows)} rows")

        per_layer = [int(ln.split("|")[2].strip()) for ln in rows]
        assert sum(per_layer) == int(modules), (
            f"{name}: rows sum to {sum(per_layer)}, headline says {modules}")

        seen[name] = per_layer

    # The rows must also be the same rows in both languages, or the two READMEs
    # describe different systems while each stays internally self-consistent.
    assert seen["README.md"] == seen["README.zh.md"], (
        f"layer counts differ between languages: {seen}")


def test_explicit_h2_sequences():
    # Lock both languages' section order (and their 1:1 correspondence by position),
    # not just the count — so a section can't be added/reordered in one language only.
    assert [h[3:].strip() for h in _h2(EN)] == EN_H2
    assert [h[3:].strip() for h in _h2(ZH)] == ZH_H2


def test_emoji_only_in_the_hhi_bucket_row():
    # The single place emoji are allowed is the HHI concentration row, where the
    # ✅🟡🟠🔴 markers mirror the dashboard's actual bucket colors. Nowhere else — no
    # decorative heading emoji, no ⚠️ leaking into prose. Whole-document scan.
    for md, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        for i, line in enumerate(md.splitlines(), 1):
            if "HHI" in line and "0.15" in line:
                continue  # the allowed bucket legend
            ch = _first_emoji(line)
            assert ch is None, f"emoji outside the HHI row at {name}:{i}: {ch!r}"


def test_zh_uses_benchmark_vendor_not_official_bars():
    # Iron rule: settlement bars come from a canonical VENDOR feed (Tencent/etc.),
    # never an exchange/official feed. ZH must not resurrect the 官方 phrasings.
    for banned in ("官方行情", "官方源", "官方不复权", "官方逐日"):
        assert banned not in ZH, f"disallowed official-market-data claim in ZH: {banned!r}"


def test_no_live_numbers_in_evergreen_copy():
    # Policy constants (35%, -18%, x2/x3, HHI bucket thresholds) are static config and
    # allowed. What must never appear is a hard-coded live result: a win rate, a P&L
    # figure, or a sample size — those drift and go stale. Guard the phrasings that
    # would carry one.
    banned = [
        r"win rate of \d", r"\d+%\s*win", r"n\s*=\s*\d",   # sample sizes / rates
        r"[-+]?\$\d[\d,]*\s*(?:profit|loss|P&L|pnl)",       # money results
        r"胜率\s*\d", r"样本\s*\d", r"n\s*=\s*\d+\s*条",
    ]
    for md, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        for pat in banned:
            m = re.search(pat, md, re.IGNORECASE)
            assert not m, f"live number in evergreen copy ({name}): {m.group(0)!r}"

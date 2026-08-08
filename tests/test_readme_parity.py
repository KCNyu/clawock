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
    "What clawock is", "Why this layer exists", "Installation status",
    "Quickstart", "What ships in the workflow",
    "Bounded improvement, not autonomous self-rewriting", "Architecture",
    "OpenClaw is the first production adapter", "The KCNyu live proof",
    "Current boundary — no inflated claims", "Development", "License and risk",
]
ZH_H2 = [
    "clawock 是什么", "为什么需要这一层", "安装状态", "快速开始",
    "workflow 里有什么", "有边界的改进，不是自主改写自己", "架构",
    "OpenClaw 是第一个生产 adapter", "KCNyu 实盘证明",
    "当前边界：不夸大", "开发", "License 与风险",
]


def _h2(md):
    return [ln for ln in md.splitlines() if ln.startswith("## ")]


def _details(md):
    return md.count("<summary>")


def _assets(md):
    return sorted(set(re.findall(r"assets/[\w./-]+\.(?:svg|png|gif)", md)))


def test_section_count_matches():
    assert len(_h2(EN)) == len(_h2(ZH)) > 0


def test_details_count_matches():
    assert _details(EN) == _details(ZH)


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


def test_portable_workflow_surface_stays_in_both_languages():
    for target in (
        "clawock workflow install investment-decision",
        "clawock run prepare",
        "clawock run publish",
        "src/clawock/",
    ):
        assert target in EN and target in ZH, f"{target} missing from a README"


def test_runtime_boundary_is_explicit_in_both_languages():
    for md in (EN, ZH):
        for owner in ("model", "memory", "tools", "permissions"):
            assert owner in md
        assert "scripts/harness/" in md
        assert "#380" in md and "#381" in md


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

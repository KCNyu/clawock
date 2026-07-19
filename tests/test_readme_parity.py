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

# Emoji-ish codepoints (pictographs, symbols, flags, dingbats). Deliberately does
# NOT include the CJK range, so Chinese text is fine.
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF️]"
)


def _h2(md):
    return [ln for ln in md.splitlines() if ln.startswith("## ")]


def _details(md):
    return md.count("<summary>")


def _assets(md):
    return sorted(set(re.findall(r"assets/[\w./-]+\.(?:svg|png|gif)", md)))


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
        "CRON_SCHEDULES.md",
        "THIRD_PARTY_DATA.md",
        "LICENSE",
    ):
        assert target in EN and target in ZH, f"{target} missing from a README"


def test_language_switch_links_cross():
    assert "README.zh.md" in EN
    assert "README.md" in ZH


def test_no_decorative_emoji_in_headings():
    # Headings stay clean in both languages (the redesign killed one-emoji-per-H2).
    for md, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        for line in _h2(md):
            assert not EMOJI.search(line), f"decorative emoji in heading: {line!r} ({name})"


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

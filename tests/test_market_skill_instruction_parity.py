"""The two market skills share their runtime prose rules instead of copying them (#3503).

The paragraphs used to be byte-identical in both files and hand-mirrored. They
now live in `skills/_shared/` and each skill routes to the same file. This guard
keeps a future edit from quietly forking them again: a long instruction
paragraph appearing in both files fails, and both skills must name the shared
file their Mode 6 and interactive reads use.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HK = (ROOT / "skills/hk-stock-analysis/SKILL.md").read_text(encoding="utf-8")
US = (ROOT / "skills/us-stock-analysis/SKILL.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["report-prose-rules.md", "interactive-mode-reads.md"])
def test_both_market_skills_route_to_the_shared_file(name):
    route = f"../_shared/{name}"
    assert route in HK, f"{route} is not named by the HK market skill"
    assert route in US, f"{route} is not named by the US market skill"


def test_the_shared_files_carry_the_rules_they_replaced():
    report = (ROOT / "skills/_shared/report-prose-rules.md").read_text(encoding="utf-8")
    assert "signal_count" in report and "异动归因" in report
    assert "读者只看得到这条微信" in report and "长度由你自己判断" in report
    intro = (ROOT / "skills/_shared/interactive-mode-reads.md").read_text(encoding="utf-8")
    assert "For interactive questions (Modes 1-5)" in intro


def test_no_long_instruction_paragraph_is_hand_mirrored():
    paragraphs = lambda text: [p for p in text.split("\n\n") if len(p.strip()) > 200]
    common = [p for p in paragraphs(HK) if p in US]
    assert not common, (
        f"{len(common)} long instruction paragraph(s) are byte-identical in both "
        f"market skills again; move the text to skills/_shared/ and route both"
    )

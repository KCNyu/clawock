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


def test_mode6_news_is_inline_and_distinguishes_confirmed_sources():
    text = (ROOT / 'skills/_shared/report-prose-rules.md').read_text()
    sentiment = text.split('**▎情绪面**', 1)[1].split('**▎技术面**', 1)[0]
    for field in ('anomalies', 'mover_news.halts', 'tier=primary', 'signal=interrupt',
                  'tier=supporting', 'source_class', 'live_information.summary',
                  'live_information.degraded', 'mover_thesis', 'known_catalysts'):
        assert f'`{field}`' in sentiment
    assert '出处和时点嵌在对应句子里' in sentiment
    assert '**▎证据**' not in text and '**▎异动归因**' not in text


def test_shared_prose_routes_numeric_facts_to_the_available_surface():
    prose = (ROOT / 'src/clawock/trading-prose.md').read_text()
    interactive = (ROOT / 'skills/_shared/interactive-mode-reads.md').read_text()
    risk = (ROOT / 'skills/portfolio-risk-review/SKILL.md').read_text()
    assert '直聊和手写表格' in prose and '本次 compute 回执' in prose
    assert '来源、场次和单位' in interactive
    assert '手写表格时填入核过的行情和盈亏' in risk

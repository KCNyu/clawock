"""The README GIF photographs exactly the views the dashboard has.

#1465 added a Growth tab and bumped the shooter to seven tabs; #1472 removed the
tab from the page and left both GIF tools at seven, so the weekly screenshot job
would click a tab that no longer exists. The count lives in two files and the
page, so all three are compared here.

The six-tab strip is a picker now (a trigger that opens a menu), so the page
side of the comparison reads `.view-picker-item` rather than `.tab-btn`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _page_tabs() -> list[str]:
    html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    buttons = re.findall(r'<button\b[^>]*>', html)
    return [re.search(r'data-tab="([a-z]+)"', tag).group(1)
            for tag in buttons
            if re.search(r'class="view-picker-item\b', tag) and 'data-tab="' in tag]


def test_shooter_tabs_match_the_page():
    js = (ROOT / "site" / "tools" / "shoot_dashboard.js").read_text(encoding="utf-8")
    match = re.search(r"const TABS = \[([^\]]*)\]", js)
    assert match, "shoot_dashboard.js no longer declares `const TABS = [...]`"
    shooter = re.findall(r"'([a-z]+)'", match.group(1))
    assert shooter == _page_tabs()


def test_assembler_tab_count_matches_the_page():
    py = (ROOT / "site" / "tools" / "assemble_dashboard_gif.py").read_text(encoding="utf-8")
    match = re.search(r"^TAB_COUNT = (\d+)$", py, re.M)
    assert match, "assemble_dashboard_gif.py no longer declares TAB_COUNT"
    assert int(match.group(1)) == len(_page_tabs())

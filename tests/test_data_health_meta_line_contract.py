"""「数据健康」读数行的折行契约。

2026-09-12：`crawl_visibility` 那四个事实挤成一个 `.dh-meta-bit`（`nowrap`），
390px 手机实测把整块牌顶宽 158px、还把「逐项」按钮推出卡外（按钮右边缘
531px vs 卡右 374px）。抓到它的是浏览器契约——但 master 的纯数据提交不跑 UI
lane，所以这块牌一直红在**每一个** UI PR 的 validate 上（本地用
`ops/pages/fetch_data_plane.py` 拉真数据后同样复现）。

修法：复合读数交给 `dashboard.core.js` 的 `metaBits()` 按分隔点（` · `）拆短，
`nowrap` 的前提「每一段都比屏幕窄」由代码保证；`.hero-health-head` 的子项加
`min-width: 0`，让按钮位置不再取决于别人写了多长的一句话。

这条闸盯的是**两个渲染端**：首屏走 `dashboard.hero.js`，详情 tab 走
`dashboard.render.js`，历史上一份改了另一份没改的漂移在这个仓库里反复出现
（见 tests/test_dashboard_bundle_parity.py）。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "site" / "assets" / "js"
CORE = JS / "dashboard.core.js"
RENDERERS = (JS / "dashboard.hero.js", JS / "dashboard.render.js")
CSS = ROOT / "site" / "assets" / "css" / "dashboard.css"


def _meta_block(path: Path) -> str:
    """`if (metaEl) {` … 组装 `.dh-meta-bit` 之间的那段源码。

    只在这里断言"没有绕过拆分器"是有意的：整份文件里别的 `bits` 数组（成品
    状态、落地计数）本来就该自由 push，它们不印在 `nowrap` 的行里。
    """
    src = path.read_text(encoding="utf-8")
    start = src.index("if (metaEl) {")
    end = src.index("metaEl.innerHTML = bits.map", start)
    return src[start:end]


def test_the_splitter_lives_in_the_shared_core():
    src = CORE.read_text(encoding="utf-8")
    assert "const metaBits = " in src, (
        "dashboard.core.js 里没有 metaBits —— 两个渲染端会各自拼长句，"
        "下一次数据加一栏就又把手机顶宽")
    assert '.split(" · ")' in src, "metaBits 必须在分隔点（ · ）上拆，而不是硬切字符"


def test_both_data_health_renderers_go_through_the_splitter():
    for path in RENDERERS:
        block = _meta_block(path)
        assert "metaBits(" in block, (
            f"{path.name}: 数据健康读数行没走 metaBits() —— 一段比手机宽的 "
            "nowrap 文字会把整块牌顶出屏幕（2026-09-12 实测 158px）")
        assert "push(" not in block, (
            f"{path.name}: 这段直接 push 了一个 bit 到 nowrap 的行里；"
            "长读数必须过 metaBits() 拆短，否则 390px 手机会被顶宽")


def test_the_header_can_shrink_so_the_toggle_stays_on_card():
    css = CSS.read_text(encoding="utf-8")
    assert ".hero-health-head > :first-child { min-width: 0; }" in css, (
        "flex 子项的 min-width:auto 会让读数行按 min-content 撑开，"
        "把「逐项」按钮推出卡外；这条 min-width:0 是它的护栏")

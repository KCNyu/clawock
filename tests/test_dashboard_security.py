from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sort_headers_never_reinterpret_dom_text_as_html():
    renderer = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()
    # 持仓表合并后（#875），排序接线在 renderBook 里，后面紧跟的不再是
    # renderShadowPortfolioCard，所以用成对的标记注释精确圈出这段。
    sort_headers = renderer.split("// Wire sort headers", 1)[1].split(
        "// end sort headers", 1
    )[0]

    assert ".innerHTML" not in sort_headers
    assert "x.replaceChildren()" in sort_headers
    assert "x.append(label)" in sort_headers
    assert 'document.createElement("span")' in sort_headers
    assert "arrow.textContent" in sort_headers

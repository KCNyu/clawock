from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sort_headers_never_reinterpret_dom_text_as_html():
    renderer = (ROOT / "site" / "assets" / "js" / "dashboard.render.js").read_text()
    sort_headers = renderer.split("// Wire sort headers", 1)[1].split(
        "function renderShadowPortfolioCard", 1
    )[0]

    assert ".innerHTML" not in sort_headers
    assert "x.replaceChildren()" in sort_headers
    assert "x.append(label)" in sort_headers
    assert 'document.createElement("span")' in sort_headers
    assert "arrow.textContent" in sort_headers

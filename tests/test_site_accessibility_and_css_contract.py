"""The dashboard's first Tab reaches content, and one selector has one owner."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_both_page_templates_offer_a_skip_link_to_main():
    for relative in ("site/index.html", "site/_layouts/default.html"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert 'class="skip-link" href="#main"' in text, relative
        assert '<main id="main">' in text, relative


def test_skip_link_is_hidden_until_focused():
    css = (ROOT / "site/assets/css/dashboard.css").read_text(encoding="utf-8")
    assert ".skip-link {" in css
    assert ".skip-link:focus {" in css


def test_br_point_has_one_declaration_and_hl_chip_comment_matches_its_fill():
    css = (ROOT / "site/assets/css/dashboard.css").read_text(encoding="utf-8")
    assert css.count("  .br-point {") == 1
    assert "底色用不透明 --fill-inset" in css
    assert "底色用不透明 --card-2" not in css

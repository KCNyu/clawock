"""Session and time-zone labels on the dashboard's first screen."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / "site/assets/js/dashboard.render.js"
HERO = ROOT / "site/assets/js/dashboard.hero.js"


def test_macro_index_cells_name_the_close_they_quote():
    body = RENDER.read_text(encoding="utf-8")
    start = body.index("function renderMacro()")
    end = body.index("function renderSentimentDrill", start)
    macro = body[start:end]
    for field in ("spx", "nasdaq", "hsi", "hstech"):
        assert f"closeNote(m.{field}.as_of)" in macro, field
    assert "收盘" in macro


def test_fx_timestamp_is_stamped_in_hkt_not_bare_utc():
    hero = HERO.read_text(encoding="utf-8")
    start = hero.index('document.getElementById("fx-rate-usd")')
    end = hero.index("segs", start) if "segs" in hero[start:] else start + 2000
    block = hero[start:end]
    assert 'toISOString().replace("T", " ").slice(0, 16) + "Z"' not in block
    assert 'timeZone: "Asia/Hong_Kong"' in block
    assert '" HKT"' in block

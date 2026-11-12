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


def _body(src, name):
    lines = src.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"  function {name}("))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "  }")
    return "\n".join(lines[start:end + 1])


def test_market_snapshot_names_each_cells_session_and_ranges_the_asof():
    block = _body(HERO.read_text(encoding="utf-8"), "renderMarketSnapshot")
    assert "r.session.slice(5)" in block, "each cell must print its own session"
    assert "sessions.length > 1" in block, "the as-of line must print a range"
    assert "sessions[0].slice(5)} ~ " in block, "the as-of line must print both ends"


def test_movers_name_their_session_and_stop_saying_today_when_mixed():
    hero = HERO.read_text(encoding="utf-8")
    block = _body(hero, "renderTodayHighlights")
    assert "String(x.session).slice(5)" in block and "hl-mv-s" in block
    label = _body(hero, "moversHeadLabel")
    assert "sessions.length > 1" in label
    assert "异动 · 最近收盘" in label


def test_sentiment_names_a_failed_reddit_source_instead_of_dropping_it():
    body = RENDER.read_text(encoding="utf-8")
    macro = _body(body, "renderMacro")
    assert "source_status" in macro and "源失败" in macro
    drill = _body(body, "renderSentimentDrill")
    assert "reddit_status" in drill and "— 源失败" in drill

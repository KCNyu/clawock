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
    # #3479: one session on a weekend / Monday morning is still not today.
    # The old 20-hour rule compared generated_at with last_updated, both of
    # which belong to this artifact, so it could never see that.
    assert "sessions[0] === dhHktDay(generated)" in label
    # A legacy projection with no per-row session keeps the artifact-age rule.
    assert "20 * 3600" in label


def test_hero_today_kicker_requires_the_leg_session_to_be_today():
    """#3479 comment: both legs carrying a percentage does not make the
    percentage today's; the weekend payload carried Friday's for both."""
    block = _body(HERO.read_text(encoding="utf-8"), "renderCommandDeck")
    assert "d.session_date === generatedHktDay" in block
    assert "legIsToday(legDelta.us) && legIsToday(legDelta.hk)" in block
    assert "legName" in block and "!legIsToday(d)" in block


def test_hero_spark_keeps_the_last_session_date():
    """#3478: moving the headline value onto the tail must not invent a
    non-trading date from the generation's HKT day."""
    block = _body(HERO.read_text(encoding="utf-8"), "renderHeroSpark")
    assert "latest.v = currentProfit" in block
    assert "pts.push(" not in block


def test_latest_brief_card_uses_the_projection_generated_at():
    """#3481: 08:03 is the slot, not the send time of the brief on screen."""
    import subprocess
    block = _body((ROOT / "site/assets/js/dashboard.ui.js").read_text(encoding="utf-8"),
                  "briefCardStamp")
    js = """
const assert = require('node:assert/strict');
""" + block + """
assert.equal(briefCardStamp('2026-11-13T08:05:21.894196+08:00'), '08:05');
assert.equal(briefCardStamp('2026-11-13T10:39:00+08:00'), '10:39');
assert.equal(briefCardStamp(''), '08:03');
assert.equal(briefCardStamp('not a date'), '08:03');
"""
    subprocess.run(['node', '-e', js], check=True)
    ui = (ROOT / "site/assets/js/dashboard.ui.js").read_text(encoding="utf-8")
    assert "· 08:03 HKT" not in ui
    assert "briefCardStamp(brief.generated_at)" in ui


def test_sentiment_names_a_failed_reddit_source_instead_of_dropping_it():
    body = RENDER.read_text(encoding="utf-8")
    macro = _body(body, "renderMacro")
    assert "source_status" in macro and "redditSourceNote(" in macro
    note = _body(body, "redditSourceNote")
    # One vocabulary for the macro cell and the per-ticker row; #3446 added the
    # throttled half beside the original failed word.
    assert "源失败" in note and "源限流" in note
    drill = _body(body, "renderSentimentDrill")
    assert "reddit_status" in drill and "redditSourceNote(" in drill

"""Gold history details stay out of routine CLI and brief output."""
import json

import pytest

from clawock.harness import brief_render
from clawock.market_data.gold import fetch as gold
from clawock.publish.dashboard import _gold_card


SUMMARY = "伦敦金历史使用 COMEX 期货补位 · 美元兑人民币历史沿用上次数据"
ADVISORY = (
    "伦敦金历史校验：沿用 1 个已结算点；最大新旧偏差 1.45%"
    "（2026-07-01，源 eastmoney_gc00y_fallback）；USDCNY 历史抓取失败，沿用上次 7 个参考点"
)


def test_cli_prints_summary_and_logs_full_diagnostics_once(tmp_path, monkeypatch, capsys):
    days = [f"2026-07-{i:02}" for i in range(1, 8)]
    old_xau = [(day, 100) for day in days]
    old_fx = [(day, 7) for day in days]
    fresh = [(days[0], 101.45), *old_xau[1:]]
    book = {"gold_dca": dict(
        gold.SEED, start_date=days[0], reconciled_date=days[0],
        london={"hist_series": old_xau, "fx_hist_series": old_fx},
    )}
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(book))
    monkeypatch.setattr(gold, "PORTFOLIO", str(path))
    monkeypatch.setattr(gold, "fetch_nav_history", lambda *a, **k: [(day, 3, 0) for day in days])
    monkeypatch.setattr(gold, "fetch_realtime", lambda _: None)
    monkeypatch.setattr(gold, "fetch_au9999_daily", lambda _: None)
    monkeypatch.setattr(gold, "fetch_london_spot", lambda: {"xau_usd": 100, "date": days[-1]})
    monkeypatch.setattr(gold, "fetch_usdcny", lambda _: (7, {}))
    monkeypatch.setattr(gold, "fetch_xau_history", lambda _: (
        fresh, {"name": gold.XAU_FALLBACK_SOURCE, "points": len(fresh)},
    ))

    assert gold.main(["--dry-run"]) == 0
    captured = capsys.readouterr()
    assert [line.strip() for line in captured.out.splitlines() if SUMMARY in line] == [f"↳ {SUMMARY}"]
    assert "1.45%" not in captured.out
    assert captured.err.count(ADVISORY) == 1


def test_dashboard_projection_adds_summary_to_legacy_portfolio_with_details():
    london = {
        "hist_source": {"name": gold.XAU_FALLBACK_SOURCE, "points": 200},
        "fx_hist_source": {"name": "frankfurter_usdcny", "points": 0},
        "fx_hist_series": [["2026-07-01", 7]],
        "hist_advisory": ADVISORY,
    }

    projected = _gold_card({"gold_dca": {"london": london}})["london"]
    assert projected["hist_summary"] == SUMMARY
    assert projected["hist_advisory"] == ADVISORY
    assert "fx_hist_series" not in projected
    assert "hist_summary" not in london


def test_dashboard_uses_retained_label_for_legacy_empty_fallback():
    london = {
        "hist_source": {"name": gold.XAU_FALLBACK_SOURCE, "points": 0},
        "hist_series": [["2026-07-01", 100]],
    }
    assert _gold_card({"gold_dca": {"london": london}})["london"]["hist_summary"] == (
        "伦敦金历史沿用上次数据"
    )


@pytest.mark.parametrize(("simulation", "notice"), [
    ({"stale": False, "as_of": "2026-07-01"}, None),
    ({"stale": True, "as_of": "2026-07-01"}, "伦敦金定投沿用上次模拟结果（截至 2026-07-01）"),
    ({"stale": True}, "伦敦金定投沿用上次模拟结果（估值日期未记录）"),
    (None, "伦敦金定投模拟暂无足够的参考数据"),
])
def test_brief_page_and_card_only_show_a_simulation_notice_when_degraded(simulation, notice):
    london = {"dca_equiv": simulation, "hist_advisory": ADVISORY}
    context = {"portfolio": {"gold_dca": {"london": london}}}

    for output in (brief_render.data_holes_section(context, {}),
                   brief_render.render_card(context, {}, {})):
        assert ADVISORY not in output
        if notice:
            assert notice in output
        else:
            assert "伦敦金" not in output

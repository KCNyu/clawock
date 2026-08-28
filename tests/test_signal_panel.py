"""Per-source measurement must survive the ways this kind of table lies.

The question the panel exists for — "does the news layer carry weight, does the
technical layer" — is one the decision-level attribution cannot answer: measured
on the live ledger, `information_overlay` has zero eligible decisions lifetime
and `sizing.contributors` has never fired, because both are conditioned on a
`tactical_entry` add carrying a v1 packet and there have been none. A source we
never traded on scores nothing there, not zero.

Measuring the cross-section instead removes that dependency and introduces three
new ways to be wrong, which is what these tests pin: repeated intraday snapshots
silently reweighting a session, a forward return that starts on a bar the
snapshot already contained, and an interval whose width counts rows rather than
sessions.
"""
import json

import pytest

from clawock.evaluation import signal_panel as sp


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    data = tmp_path / "assets" / "data"
    data.mkdir(parents=True)
    bars = tmp_path / "memory" / "bars"
    bars.mkdir(parents=True)
    monkeypatch.setattr(sp, "DATA", data)
    return tmp_path


def write_history(workspace, name, payloads):
    path = workspace / "assets" / "data" / name
    path.write_text("".join(json.dumps(p) + "\n" for p in payloads), encoding="utf-8")


def write_bars(workspace, monkeypatch, series):
    """series = {ticker: {session: close}} — one leg, US."""
    store = {ticker: {day: {"close": close} for day, close in days.items()}
             for ticker, days in series.items()}
    sessions = sorted({day for days in series.values() for day in days})
    monkeypatch.setattr(sp, "load_ticker_bars", lambda t: store.get(t, {}))
    monkeypatch.setattr(sp, "leg_sessions", lambda leg: sessions)


MANIFEST = {"AAA": {"leg": "US"}, "BBB": {"leg": "US"}, "CCC": {"leg": "US"}}


def test_forward_return_starts_on_the_first_bar_the_snapshot_could_not_see(
        workspace, monkeypatch):
    write_bars(workspace, monkeypatch, {"AAA": {
        "2026-08-03": 100.0, "2026-08-04": 110.0, "2026-08-05": 121.0}})

    forward = sp.forward_returns("AAA", "US", "2026-08-03", horizons=(1,))

    assert forward == {"t1": 10.0}, (
        "entry is 08-04's close, the first the 08-03 snapshot could not contain")


def test_a_ticker_with_no_canonical_bars_is_unscorable_not_zero(
        workspace, monkeypatch):
    write_history(workspace, "quant_signals_history.jsonl", [
        {"as_of": "2026-08-03", "rows": {"ZZZ": {"rsi14": 70.0}}}])
    write_bars(workspace, monkeypatch, {"AAA": {"2026-08-03": 1.0}})

    assert sp.build_panel(workspace / "assets" / "data", MANIFEST) == []


def test_repeated_intraday_snapshots_do_not_reweight_a_session(
        workspace, monkeypatch):
    """The bug this caught on live data.

    `t0_setups_history` writes ~14 snapshots a day. Without one row per
    (session, ticker, signal), a name enters that day's cross-section fourteen
    times and the session's IC becomes partly a ranking of sampling frequency.
    On the real panel this moved `setup.range_pos` from 11,327 rows to 760 — and
    moved its t5 interval across zero.
    """
    write_history(workspace, "t0_setups_history.jsonl", [
        {"as_of": "2026-08-03", "rows": {"AAA": {"range_pos": 10.0}}},
        {"as_of": "2026-08-03", "rows": {"AAA": {"range_pos": 20.0}}},
        {"as_of": "2026-08-03", "rows": {"AAA": {"range_pos": 30.0}}},
    ])
    write_bars(workspace, monkeypatch, {
        "AAA": {"2026-08-03": 100.0, "2026-08-04": 100.0, "2026-08-05": 105.0}})

    panel = sp.build_panel(workspace / "assets" / "data", MANIFEST)

    assert len(panel) == 1
    assert panel[0]["value"] == 30.0, "the last snapshot is the one T+1 follows"


def test_a_flat_cross_section_ranks_nothing_and_is_reported_as_such():
    """An event count is zero for every name most days; that is not an IC of 0."""
    rows = [{"as_of": "2026-08-03", "ticker": t, "signal": "news.actionable_count",
             "value": 0.0, "t1": r}
            for t, r in (("AAA", 1.0), ("BBB", -1.0), ("CCC", 2.0))]

    scored = sp.score_signal(rows, "t1")

    assert scored["n_sessions"] == 0 and scored["mean_ic"] is None
    assert scored["flat_sessions"] == 1, (
        "a day with no ranking must be visible, or the signal reads as broken")
    assert scored["status"] == "collecting"


def test_the_ic_recovers_a_planted_ranking_with_its_sign():
    rows = []
    for day in range(1, 21):
        as_of = f"2026-08-{day:02d}"
        for ticker, value, forward in (("AAA", 3.0, 3.0), ("BBB", 2.0, 2.0),
                                       ("CCC", 1.0, 1.0)):
            rows.append({"as_of": as_of, "ticker": ticker, "signal": "quant.mom_1m",
                         "value": value, "t1": forward})

    scored = sp.score_signal(rows, "t1")

    assert scored["mean_ic"] == 1.0
    assert scored["ic_cluster_ci95"] == [1.0, 1.0]
    assert scored["status"] == "diagnostic" and scored["ic_clears_zero"]

    for row in rows:
        row["t1"] = -row["t1"]
    assert sp.score_signal(rows, "t1")["mean_ic"] == -1.0, (
        "the sign is the finding: an inverted signal must report as inverted")


def test_status_counts_sessions_not_rows():
    """500 rows over six days is six samples, and the floor has to say so."""
    rows = [{"as_of": f"2026-08-0{day}", "ticker": f"T{i}", "signal": "quant.rsi14",
             "value": float(i), "t1": float(i)}
            for day in range(1, 7) for i in range(1, 21)]

    scored = sp.score_signal(rows, "t1")

    assert scored["n_observations"] == 120 and scored["n_sessions"] == 6
    assert scored["status"] == "collecting", (
        "clearing the row floor alone must not promote a six-day sample")


def test_a_hit_rate_is_reported_only_where_the_direction_was_registered():
    """A hit rate under a direction learned from the data is a search result."""
    def rows(signal):
        return [{"as_of": f"2026-08-{d:02d}", "ticker": "AAA", "signal": signal,
                 "value": 1.0, "t1": 1.0} for d in range(1, 15)]

    assert "directional_hit_rate" in sp.score_signal(rows("news.signed_score"), "t1")
    assert "directional_hit_rate" not in sp.score_signal(rows("quant.rsi14"), "t1")
    assert "quant.rsi14" not in sp.DIRECTIONAL, (
        "a high RSI is momentum or exhaustion depending on the answer; that "
        "cannot be declared in advance, so only the IC speaks for it")


def test_nothing_can_reach_validated():
    rows = [{"as_of": f"2026-08-{d:02d}", "ticker": t, "signal": "news.signed_score",
             "value": v, "t1": v}
            for d in range(1, 21)
            for t, v in (("AAA", 3.0), ("BBB", 2.0), ("CCC", 1.0))]

    scored = sp.score_signal(rows, "t1")

    assert scored["status"] in ("collecting", "diagnostic")
    assert scored["ic_clears_zero"] is True, "a perfect signal may still clear zero"
    assert "validated" not in json.dumps(scored), (
        "validation requires pre-registration, which no measurement here performs")


def test_selection_refuses_an_unbalanced_panel_and_names_what_it_dropped():
    """A signal registered for five sessions would void every split it enters."""
    panel = [{"as_of": f"2026-08-{d:02d}", "ticker": t, "signal": s, "value": v,
              "t1": v}
             for d in range(1, 4)
             for s in ("quant.rsi14", "news.signed_score", "factor.composite_score")
             for t, v in (("AAA", 3.0), ("BBB", 1.0))]

    result = sp.selection_pbo(panel, "t1")

    assert result["status"] == "insufficient_sample" and result["pbo"] is None
    assert "cannot fill" in result["reason"]


def test_selection_reports_pbo_over_the_signals_a_chooser_could_choose_between():
    """One real ranker among three that rotate against the forward returns.

    The forward return belongs to (session, ticker), not to the signal — every
    signal on a given day is scored against the same outcomes, which is what
    makes the ranking between them meaningful.
    """
    panel = []
    rotations = [("AAA", "BBB", "CCC"), ("BBB", "CCC", "AAA"), ("CCC", "AAA", "BBB")]
    fixed = {"AAA": 3.0, "BBB": 2.0, "CCC": 1.0}
    for day in range(1, 41):
        as_of = f"2026-08-{day:02d}" if day < 32 else f"2026-09-{day - 31:02d}"
        order = rotations[day % 3]
        forward = {ticker: 3.0 - index for index, ticker in enumerate(order)}
        for ticker in ("AAA", "BBB", "CCC"):
            for signal in ("quant.rsi14", "factor.composite_score", "setup.range_pos"):
                panel.append({"as_of": as_of, "ticker": ticker, "signal": signal,
                              "value": fixed[ticker], "t1": forward[ticker]})
            panel.append({"as_of": as_of, "ticker": ticker,
                          "signal": "news.signed_score",
                          "value": forward[ticker], "t1": forward[ticker]})

    result = sp.selection_pbo(panel, "t1")

    assert result["status"] == "measured"
    assert result["shared_sessions"] >= 16
    assert result["pbo"] <= 0.2, "one signal ranks every session; that is not a search"
    assert result["selected_signals"].get("news.signed_score", 0) == result["n_splits"]

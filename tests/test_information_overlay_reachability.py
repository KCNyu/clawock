"""An empty cohort has to say *why* it is empty (#1132).

`information_overlay` is the only prospective, decision-time attribution of the
information layer in the system, and it has read `warming_up` with zero eligible
decisions for its whole life. That word is a promise: wait and it fills. It does
not fill. The cohort is an intersection of two conditions, and on the live
ledger each side occurs on its own while the intersection never does — 7
tactical-entry adds, all older than packet emission; 120 v1 packets, all riding
on `hold_and_watch` or `cut`.

These tests hold the metric to the distinction: an intersection whose two sides
both occur and never meet is `unreachable_cohort`, and a genuinely early one is
still `warming_up`. The third test is the one the issue asked for by name — the
status can never look populated on an empty cohort.
"""
import json

from clawock.decision import ledger


def _row(**overrides):
    row = {
        "plan_date": "2026-08-28",
        "ticker": "TEST",
        "action": "hold_and_watch",
        "strategy_id": "core_position",
        "episode_id": "ep-1",
        "evaluation": {"outcome": "win", "benefit_t1_pct": 1.0,
                       "benefit_t5_pct": 1.0, "benefit_t20_pct": 1.0},
    }
    row.update(overrides)
    return row


def _packet(usable=False, contributors=None, progress=None):
    return {
        "schema_version": 1,
        "information": {
            "usable_for_decisions": usable,
            "activation_blockers": [] if usable else ["history_dates"],
            "activation_progress": progress or ({} if usable else {"history_dates": [11, 24]}),
        },
        "sizing": {"contributors": list(contributors or []),
                   "sizing_active": bool(contributors)},
    }


def _overlay(rows, **kwargs):
    return ledger.compute_metrics(rows, cutoff="2000-01-01", **kwargs)["information_overlay"]


def test_two_sides_that_never_meet_are_not_warming_up():
    """The live shape: adds without packets, packets without adds."""
    rows = [_row(strategy_id="tactical_entry", action="add_on_breakout", plan_date="2026-01-05",
                 episode_id=f"add-{index}") for index in range(7)]
    rows += [_row(signal_provenance=_packet(), episode_id=f"pkt-{index}")
             for index in range(120)]
    overlay = _overlay(rows)
    assert overlay["status"] == "unreachable_cohort"
    assert overlay["n_eligible_decisions"] == 0
    reach = overlay["reachability"]
    assert reach["tactical_entry_adds"] == 7
    assert reach["rows_with_v1_packet"] == 120
    assert reach["in_both"] == 0
    assert "does not fill by waiting" in reach["verdict"]


def test_a_genuinely_early_cohort_is_still_warming_up():
    """One side has never happened at all; that one really does fill by waiting."""
    rows = [_row(signal_provenance=_packet(), episode_id=f"pkt-{index}")
            for index in range(5)]
    overlay = _overlay(rows)
    assert overlay["status"] == "warming_up"
    assert overlay["reachability"]["tactical_entry_adds"] == 0


def test_a_populated_cohort_reports_collecting():
    rows = [_row(strategy_id="tactical_entry", action="add_on_breakout",
                 signal_provenance=_packet(usable=True, contributors=["news"]),
                 episode_id=f"both-{index}") for index in range(3)]
    overlay = _overlay(rows)
    assert overlay["status"] == "collecting"
    assert overlay["n_eligible_decisions"] == 3
    assert overlay["reachability"]["in_both"] == 3
    assert overlay["reachability"]["decisions_with_sizing_contributors"] == 3


def test_the_status_can_never_look_populated_on_an_empty_cohort():
    """The regression the issue asked for by name.

    Whatever the mix of rows, a status of `collecting` and a count of zero must
    not co-occur — that is the pairing that told the dashboard to render
    progress against nothing.
    """
    mixes = [
        [],
        [_row(strategy_id="tactical_entry", action="add_on_breakout", episode_id="a")],
        [_row(signal_provenance=_packet(), episode_id="p")],
        [_row(strategy_id="tactical_entry", action="add_on_breakout", episode_id="a"),
         _row(signal_provenance=_packet(), episode_id="p")],
    ]
    for rows in mixes:
        overlay = _overlay(rows)
        assert not (overlay["status"] == "collecting"
                    and overlay["n_eligible_decisions"] == 0), overlay["status"]
        assert overlay["reachability"]["in_both"] == overlay["n_eligible_decisions"]


def test_reachability_is_measured_over_the_whole_ledger_not_the_window():
    """The window is what hid this.

    The seven tactical adds are all older than thirty days, so inside the
    rolling window the first count is zero and `warming_up` reads as true. The
    counts have to be lifetime or the metric goes on lying by a different route.
    """
    rows = [_row(strategy_id="tactical_entry", action="add_on_breakout",
                 plan_date="2020-01-05", episode_id=f"old-{index}")
            for index in range(7)]
    rows += [_row(signal_provenance=_packet(), episode_id=f"pkt-{index}")
             for index in range(10)]
    overlay = ledger.compute_metrics(rows, cutoff="2026-08-01")["information_overlay"]
    assert overlay["reachability"]["tactical_entry_adds"] == 7
    assert overlay["status"] == "unreachable_cohort"


def test_the_second_gate_publishes_how_far_off_it_is():
    """"What would flip it", not just "it is blocked"."""
    rows = [_row(signal_provenance=_packet(progress={"history_dates": [11, 24]}),
                 episode_id=f"p-{index}") for index in range(4)]
    rows += [_row(strategy_id="tactical_entry", action="add_on_breakout", episode_id="a")]
    reach = _overlay(rows)["reachability"]
    assert reach["information_activation_progress"] == {"history_dates": [11, 24]}
    assert reach["information_activation_blockers"] == ["history_dates"]
    assert reach["packets_with_usable_information"] == 0


def test_the_population_that_does_occur_is_reported_under_its_own_name():
    """Acceptance 2, without pretending it is the prospective cohort.

    Every packet-carrying decision, split by the action actually taken. It is a
    different claim — what happened after a decision that saw the information
    layer — and it must never be reachable by reading the cohort keys.
    """
    rows = [_row(signal_provenance=_packet(), action="cut", episode_id=f"c-{i}")
            for i in range(6)]
    rows += [_row(signal_provenance=_packet(), action="hold_and_watch",
                  episode_id=f"h-{i}") for i in range(9)]
    overlay = _overlay(rows)
    population = overlay["packet_carrying_population"]["t5"]
    assert sorted(population) == ["cut", "hold_and_watch"]
    assert population["cut"]["n_decisions"] == 6
    assert population["hold_and_watch"]["n_decisions"] == 9
    # And it is not smuggled into the cohort that stayed empty.
    assert overlay["n_eligible_decisions"] == 0
    assert set(overlay["horizons"]["t5"]["cohorts"]) == {
        "setup_only", "overlay_active_neutral", "setup_plus_information"}


def test_the_metric_still_serialises():
    rows = [_row(signal_provenance=_packet(), episode_id="p")]
    json.dumps(_overlay(rows))

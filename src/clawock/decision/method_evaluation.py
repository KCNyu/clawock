"""Did a method earn its keep? Return distributions by method and by whether
the registered policy agreed (#2844).

The calibrator answers "how often is a call of this action / driver /
condition / regime right". Three questions it cannot answer are answered here:

* by **method** — proposals carry `method_version`, a hash of how the model
  said it reached the call, so a change of method is a change of group;
* by **policy group** — `policy_agreed` and `policy_objected` describe
  observed proposals, not independently generated experiment arms. Selection
  probabilities are unknown, so their difference is not a causal estimate.
  Benefit is measured against not acting; that reference is zero by
  construction. Prospective three-arm trials live in `method_trials`;
* in **money terms** — mean, median, tails and payoff ratio of the net
  benefit, next to the hit rate and never folded into it.

Every group reports its denominators: how many were proposed, refused,
filed, triggered, settled and followed. A group with too little behind it
reads `insufficient`; nothing here promotes, demotes or sizes anything.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from collections import defaultdict

from clawock.decision import ledger
from clawock.decision.actions import ACTIVE_ACTIONS, SELL_ACTIONS

SCHEMA_VERSION = 1
#: Declared before any result was read, and the same floor the calibrator uses.
MIN_EPISODES = ledger.PAYOFF_MIN_EPISODES
MIN_DATES = ledger.CALIBRATION_MIN_PRIOR_DATES
MAX_METHOD_ROWS = 12
UNKNOWN = "unknown"
ARMS = ("policy_agreed", "policy_objected", "unreviewed")


def arm_of(row: dict) -> str:
    """Which arm a decision or proposal belongs to."""
    review = row.get("policy_review")
    agrees = (review.get("agrees_with_policy") if isinstance(review, dict)
              else row.get("agrees_with_policy") if "objections" in row else None)
    if agrees is None:
        # Filed before decisions were reviewed against the policy at all.
        return "unreviewed"
    return "policy_agreed" if agrees else "policy_objected"


def cost_pct(row: dict, model) -> float:
    """What acting cost, in percent of the notional, under the registered cost
    model: commission plus the share of the spread a crossing order pays, per
    filled leg. A T trade is two legs. The minimum commission applies when the
    decision's capital is known."""
    leg = str(row.get("leg") or "").lower()
    rate = float((model.assumed_commission_bps or {}).get(leg, 0.0))
    spread = float((model.spread_bps_by_leg or {}).get(leg, 0.0)) * float(model.spread_share)
    per_leg = (rate + spread) / 100
    capital = ledger._float((row.get("evaluation") or {}).get("capital"))
    minimum = float((model.assumed_minimum_commission or {}).get(leg, 0.0))
    if capital and capital > 0 and minimum:
        per_leg = max(rate / 100, minimum / capital * 100) + spread / 100
    return round(per_leg * (2 if row.get("action") == "t_only" else 1), 4)


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _payoff(rows: list[dict]) -> dict:
    """The return distribution of settled episodes, net of assumed costs."""
    net = [row["_net"] for row in rows]
    dates = {row.get("plan_date") for row in rows}
    if not net:
        return {"reading": "insufficient", "n": 0, "dates": 0}
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    mean = sum(net) / len(net)
    ci = ledger._cluster_ci(rows, lambda row: row["_net"])
    enough = len(net) >= MIN_EPISODES and len(dates) >= MIN_DATES and ci is not None
    reading = ("insufficient" if not enough
               else "positive_expectancy" if ci[0] > 0
               else "negative_expectancy" if ci[1] < 0 else "inconclusive")
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return {
        "reading": reading,
        "n": len(net),
        "dates": len(dates),
        "mean_net_benefit_pct": round(mean, 4),
        "mean_gross_benefit_pct": round(sum(row["_gross"] for row in rows) / len(rows), 4),
        "mean_cost_pct": round(sum(row["_cost"] for row in rows) / len(rows), 4),
        "cluster_ci95": ci,
        "median_net_benefit_pct": round(statistics.median(net), 4),
        "p05_net_benefit_pct": round(_quantile(net, 0.05), 4),
        "p95_net_benefit_pct": round(_quantile(net, 0.95), 4),
        "worst_net_benefit_pct": round(min(net), 4),
        "avg_win_pct": round(avg_win, 4) if avg_win is not None else None,
        "avg_loss_pct": round(avg_loss, 4) if avg_loss is not None else None,
        "payoff_ratio": (round(avg_win / abs(avg_loss), 4)
                         if avg_win is not None and avg_loss else None),
    }


def _hit_rate(rows: list[dict]) -> dict:
    wins = sum(row["_net"] > 0 for row in rows)
    return {"n": len(rows), "wins": wins,
            "rate": round(wins / len(rows), 4) if rows else None,
            "ci95": ledger.wilson_ci(wins, len(rows))}


def score_forecast(row: dict, *, bar=None, sessions_from=None) -> dict | None:
    """A decision's forecast against the bar at its horizon, or why it has none.

    The horizon counts sessions from the plan date, which is session 1 when the
    market trades that day: a brief written before the open that says "within
    5 sessions" is scored on the close of the fifth session including today.
    A forecast in words only cannot be scored by the bars and is counted as
    such; one whose horizon has not closed is pending.
    """
    forecast = row.get("forecast")
    if not isinstance(forecast, dict):
        return None
    if forecast.get("metric") not in ledger.FORECAST_METRICS:
        return {"status": "unscoreable"}
    horizon = int(forecast["horizon_sessions"])
    leg, plan_date = str(row.get("leg") or ""), str(row.get("plan_date") or "")
    try:
        sessions = (sessions_from or _sessions_from)(leg, plan_date, horizon)
    except ValueError:
        return {"status": "unscoreable"}
    if len(sessions) < horizon:
        return {"status": "pending"}
    close = ledger._float(((bar or ledger.bar)(str(row.get("ticker")), sessions[-1])
                           or {}).get("close"))
    if close is None:
        return {"status": "pending"}
    happened = (close > forecast["level"] if forecast["metric"] == "close_above"
                else close < forecast["level"])
    probability = float(forecast["probability"])
    return {"status": "scored", "session": sessions[-1], "close": close,
            "outcome": int(happened), "brier": round((probability - int(happened)) ** 2, 4)}


def _sessions_from(leg: str, plan_date: str, count: int) -> list[str]:
    first = [plan_date] if ledger.is_session(leg, plan_date) else []
    return (first + ledger.next_sessions(leg, plan_date, count))[:count]


def _forecasts(rows: list[dict], scorer) -> dict:
    tally = {"stated": 0, "scored": 0, "pending": 0, "unscoreable": 0}
    briers, base = [], []
    for row in rows:
        result = scorer(row)
        if result is None:
            continue
        tally["stated"] += 1
        tally[result["status"]] += 1
        if result["status"] == "scored":
            briers.append(result["brier"])
            base.append(result["outcome"])
    out = dict(tally)
    if briers:
        rate = sum(base) / len(base)
        out["brier"] = round(sum(briers) / len(briers), 4)
        # What always answering one half would have scored on the same events.
        out["coin_brier"] = 0.25
        out["event_rate"] = round(rate, 4)
    return out


def _denominators(decisions: list[dict], proposed: list[dict]) -> dict:
    def count(rows, test):
        return sum(1 for row in rows if test(row))

    evaluation = lambda row: row.get("evaluation") or {}  # noqa: E731
    execution = lambda row: (row.get("execution") or {}).get("status")  # noqa: E731
    return {
        "proposed": len(proposed),
        "refused": count(proposed, lambda row: row.get("status") == "refused"),
        "in_unpublished_plan": count(
            proposed, lambda row: row.get("status") == "filed"
            and row.get("plan_status") == "fail"),
        "filed": len(decisions),
        "triggered": count(decisions, lambda row: evaluation(row).get("triggered") is True),
        "not_triggered": count(decisions, lambda row: evaluation(row).get("triggered") is False),
        "awaiting_trigger_or_evidence": count(
            decisions, lambda row: evaluation(row).get("triggered") is None),
        "settled": count(decisions, lambda row: evaluation(row).get("outcome")
                         in ("win", "loss", "flat")),
        "followed": count(decisions, lambda row: execution(row) == "followed"),
        "not_followed": count(decisions, lambda row: execution(row) == "not_followed"),
        "execution_unknown": count(decisions, lambda row: execution(row)
                                   not in ("followed", "not_followed")),
    }


def _group(decisions, reps, proposed, scorer) -> dict:
    return {
        "denominators": _denominators(decisions, proposed),
        "hit_rate": _hit_rate(reps),
        "payoff": _payoff(reps),
        "by_side": {
            side: {"n": len(rows), "mean_net_benefit_pct": (
                round(sum(row["_net"] for row in rows) / len(rows), 4) if rows else None)}
            for side, rows in (
                ("sell", [row for row in reps if row.get("action") in SELL_ACTIONS]),
                ("buy", [row for row in reps if row.get("action") not in SELL_ACTIONS]))
        },
        "forecasts": _forecasts(decisions, scorer),
    }


def evaluate(decisions: list[dict], proposed: list[dict] | None = None, *,
             cost_model=None, scorer=None) -> dict:
    """The report. `decisions` is the ledger; `proposed` the proposals log."""
    from clawock import costs  # noqa: PLC0415

    model = cost_model or costs.CostModel.load()
    scorer = scorer or score_forecast
    active = [row for row in decisions
              if row.get("schema_version") == ledger.SCHEMA_VERSION
              and row.get("action") in ACTIVE_ACTIONS]
    proposed = [row for row in (proposed or []) if row.get("action") in ACTIVE_ACTIONS]
    def representatives(rows):
        reps = ledger.episode_representatives(rows, "t1")
        costs_by_episode = defaultdict(list)
        for row in ledger._episode_settled(rows, "benefit_t1_pct"):
            costs_by_episode[row.get("episode_id")].append(cost_pct(row, model))
        for row in reps:
            gross = ledger._float((row.get("evaluation") or {}).get("benefit_t1_pct")) or 0.0
            # Minimum commissions are nonlinear in capital. Charge each call
            # before taking the same episode mean used for gross benefit.
            cost = statistics.mean(costs_by_episode[row.get("episode_id")])
            row["_gross"], row["_cost"], row["_net"] = gross, cost, gross - cost
        return reps

    def split(key_fn, proposal_key_fn):
        buckets = defaultdict(lambda: ([], [], []))
        for row in active:
            buckets[key_fn(row)][0].append(row)
        for row in proposed:
            buckets[proposal_key_fn(row)][2].append(row)
        # Deduplicate inside the population being described. Method returns
        # stay separate, but their representatives are not independent samples
        # that can be concatenated into the overall or policy-group report.
        for decisions, reps, _ in buckets.values():
            reps.extend(representatives(decisions))
        return buckets

    arms = split(arm_of, arm_of)
    methods = split(lambda row: row.get("method_version") or UNKNOWN,
                    lambda row: row.get("method_version") or UNKNOWN)
    texts = {}
    for row in [*active, *proposed]:
        if row.get("method"):
            texts.setdefault(row.get("method_version") or UNKNOWN, row["method"])
    ranked = sorted(methods, key=lambda key: (-len(methods[key][1]), -len(methods[key][0]), key))
    return {
        "schema_version": SCHEMA_VERSION,
        "selection_bias": "observational groups; unknown selection probabilities; no causal claim",
        "realized_returns": "not computed here; execution flags are not broker fills",
        "benefit": ("benefit_t1_pct of one representative per episode: the action's return "
                    "against not acting, so the hold reference is zero by construction"),
        "cost_model": model.as_dict(),
        "protocol": {
            "min_episodes": MIN_EPISODES,
            "min_dates": MIN_DATES,
            "reading": ("insufficient below either floor; otherwise the date-clustered "
                        "95% interval on the mean net benefit decides positive, negative "
                        "or inconclusive"),
            "groups_compared": len(arms) + len(methods),
            "note": ("many groups are read at once and none was pre-selected, so a single "
                     "positive reading is not a finding; this report promotes, demotes and "
                     "sizes nothing"),
        },
        "overall": _group(active, representatives(active), proposed, scorer),
        "arms": {arm: _group(*arms[arm], scorer) for arm in ARMS if arm in arms},
        "methods": [
            {"method_version": key, "method": texts.get(key),
             **_group(*methods[key], scorer)}
            for key in ranked[:MAX_METHOD_ROWS]
        ],
        "methods_not_shown": max(0, len(ranked) - MAX_METHOD_ROWS),
    }


def brief_view(report: dict) -> dict:
    """What the brief's calibration bundle carries: readings and denominators."""
    def slim(group):
        payoff = group.get("payoff") or {}
        return {
            "denominators": group.get("denominators"),
            "hit_rate": group.get("hit_rate"),
            "payoff": {key: payoff.get(key) for key in (
                "reading", "n", "dates", "mean_net_benefit_pct", "cluster_ci95",
                "median_net_benefit_pct", "p05_net_benefit_pct", "payoff_ratio")},
            "forecasts": group.get("forecasts"),
        }

    return {
        "protocol": report.get("protocol"),
        "overall": slim(report.get("overall") or {}),
        "arms": {arm: slim(group) for arm, group in (report.get("arms") or {}).items()},
        "methods": [{"method_version": row.get("method_version"), "method": row.get("method"),
                     **slim(row)} for row in (report.get("methods") or [])[:6]],
    }


def main(argv=None) -> int:
    import argparse  # noqa: PLC0415

    from clawock.decision import proposals  # noqa: PLC0415
    from clawock.workspace import workspace_root  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="clawock evaluate-methods", description=__doc__)
    parser.add_argument("--brief", action="store_true",
                        help="print the trimmed view the brief context carries")
    parser.add_argument("--register", metavar="SPEC", help="freeze a prospective trial from JSON")
    parser.add_argument("--trial", help="trial id to submit to or replay")
    parser.add_argument("--arm", choices=("old_policy", "observations_only", "policy_reference"))
    parser.add_argument("--submission", metavar="JSON", help="freeze an arm response before the start date")
    parser.add_argument("--as-of", help="replay through this completed date")
    args = parser.parse_args(argv)
    if args.register or args.trial:
        from clawock.decision import method_trials
        if args.register:
            report = method_trials.register(workspace_root(), json.loads(
                Path(args.register).read_text()))
        elif args.arm and not args.submission:
            report = method_trials.inputs(workspace_root(), args.trial, args.arm)
        elif args.submission:
            report = method_trials.submit(workspace_root(), args.trial, args.arm, json.loads(
                Path(args.submission).read_text()))
        else:
            report = method_trials.replay(workspace_root(), args.trial, as_of=args.as_of)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    report = evaluate(ledger.load_decisions(), proposals.load(workspace_root()))
    print(json.dumps(brief_view(report) if args.brief else report,
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

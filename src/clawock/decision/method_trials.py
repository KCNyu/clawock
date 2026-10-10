"""Frozen prospective method trials, separate from the live execution ledger.

Registration and all arm submissions close before the UTC start date. The
operator supplies three independently generated responses to the same frozen
observations, using the registered prompts; this module never calls a model or
changes capital authority. Failed and absent arms remain in the denominator.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from clawock import code_identity, costs
from clawock.decision import ledger, proposals, shadow
from clawock.safe_io import safe_write_json, temp_dir_lock

ARMS = ("old_policy", "observations_only", "policy_reference")
PROTOCOL = {
    "version": 1,
    "objective": "upside participation with visible opportunity cost and downside tails",
    "primary": "net shadow equity relative to the same initial buy-and-hold book",
    "secondary": ["upside_capture", "missed_gain", "max_drawdown", "turnover", "idle_cash"],
    "selection": "human review only; no automatic promotion, sizing or capital authority",
    "inference": "paired descriptive comparison; no unbiased causal or superiority claim",
    "missing": "missing bars, failed arms and refusals stay visible; never impute zero returns",
}


def _today(now=None):
    return (now or datetime.now(timezone.utc)).date().isoformat()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _directory(workspace, trial_id):
    if not re.fullmatch(r"trial-[0-9a-f]{16}", trial_id or ""):
        raise ValueError("invalid trial id")
    return Path(workspace) / "memory" / "method-trials" / trial_id


def _write_once(path, body):
    with temp_dir_lock(path, "methodtrials"):
        if path.exists():
            if json.loads(path.read_text()) == body:
                return
            raise ValueError(f"frozen artifact already exists: {path.name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_write_json(path, body)


def _evaluator_version():
    return {module.__name__: code_identity.file_digest(Path(module.__file__))
            for module in (ledger, shadow, costs)} | {
                "method_trials": code_identity.file_digest(Path(__file__))}


def register(workspace, spec, *, now=None):
    """Freeze capital, observations, prompts, methods, costs and horizon together.

    `observations` contains measured inputs only; `policy_reference` is the
    separate opinion layer. Each arm declares its method, model and exact prompt.
    A future start prevents registration after seeing that session's outcome.
    """
    start, end = spec.get("start_date"), spec.get("end_date")
    if not start or not end or date.fromisoformat(start) <= date.fromisoformat(_today(now)):
        raise ValueError("start_date must be after today's UTC date")
    if date.fromisoformat(end) < date.fromisoformat(start):
        raise ValueError("end_date precedes start_date")
    if not spec.get("portfolio", {}).get("portfolios") or not spec.get("observations"):
        raise ValueError("freeze an initial portfolio and observation snapshot")
    if not spec.get("policy_reference"):
        raise ValueError("freeze the old policy reference separately from observations")
    leg_config = spec.get("leg_config")
    if not leg_config:
        leg_config = shadow.load_leg_config(Path(workspace) / "config" / "portfolio-derivations.json")
        leg_config = {leg: cfg for leg, cfg in leg_config.items()
                      if cfg["portfolio_key"] in spec["portfolio"]["portfolios"]}
    if not leg_config:
        raise ValueError("declare the experiment's currency books")
    for leg in leg_config:
        seed = shadow.reconstruct_initial_book(spec["portfolio"], leg, start, leg_config)
        if not seed["cash_known"] or seed["negative_inventory_reconstruction"]:
            raise ValueError("initial cash and inventory must be known")
    arms = spec.get("arms") or {}
    if set(arms) != set(ARMS):
        raise ValueError("all three arms must be registered together")
    for arm in arms.values():
        if any(not isinstance(arm.get(key), str) or not arm[key].strip()
               for key in ("method", "model", "prompt")):
            raise ValueError("each arm needs its method, model and exact prompt")
    # The protocol and cost model belong to the evaluator, not the response.
    body = {"protocol": PROTOCOL, "start_date": start, "end_date": end,
            "portfolio": spec["portfolio"], "observations": spec["observations"],
            "policy_reference": spec["policy_reference"], "arms": arms,
            "cost_model": asdict(costs.CostModel.load()),
            "leg_config": leg_config, "evaluator_version": _evaluator_version(),
            "registered_date": _today(now),
            "evaluator": proposals.authorship(workspace)}
    trial_id = "trial-" + _digest(body)[:16]
    body = {"trial_id": trial_id, **body}
    _write_once(_directory(workspace, trial_id) / "registration.json", body)
    return body


def _registration(workspace, trial_id):
    body = json.loads((_directory(workspace, trial_id) / "registration.json").read_text())
    payload = {k: v for k, v in body.items() if k != "trial_id"}
    if "trial-" + _digest(payload)[:16] != trial_id:
        raise ValueError("registration digest mismatch")
    return body


def inputs(workspace, trial_id, arm):
    """Return the exact input for one worker; direct-read arm sees no policy."""
    trial = _registration(workspace, trial_id)
    if arm not in ARMS:
        raise ValueError("unknown arm")
    return {"observations": trial["observations"], "portfolio": trial["portfolio"],
            "start_date": trial["start_date"], "end_date": trial["end_date"],
            **trial["arms"][arm],
            **({"policy_reference": trial["policy_reference"]}
               if arm != "observations_only" else {})}


def submit(workspace, trial_id, arm, submission, *, now=None):
    trial = _registration(workspace, trial_id)
    if arm not in ARMS or _today(now) >= trial["start_date"]:
        raise ValueError("unknown arm or prospective submission window closed")
    if submission.get("status") not in ("ok", "failed", "refused"):
        raise ValueError("submission needs status ok, failed or refused")
    if not isinstance(submission.get("raw_response"), str):
        raise ValueError("preserve the raw response (or failure description)")
    plan = submission.get("plan") or {}
    if submission["status"] == "ok":
        if plan.get("date") != trial["start_date"] or not isinstance(plan.get("decisions"), list):
            raise ValueError("plan must contain decisions and the registered start date")
    # Keep the raw response alongside normalization, so invalid proposals and
    # model omissions are auditable even when no executable plan exists.
    normalized = ledger.normalize_authored_plan(plan, Path(workspace) / "nonexistent-trial-ledger")
    if submission["status"] == "ok" and normalized.get("decisions"):
        errors = ledger.validate_plan(normalized, check_book=False)
        if errors:
            raise ValueError("invalid trial plan: " + "; ".join(errors))
    for row in normalized.get("decisions") or []:
        row["method"] = trial["arms"][arm]["method"]
        row["method_version"] = proposals.method_version(row["method"])
        row["execution"] = {"status": "unknown"}
        row["evaluation"] = {}
    body = {"trial_id": trial_id, "arm": arm, "submitted_date": _today(now),
            "input_digest": _digest(inputs(workspace, trial_id, arm)),
            "status": submission["status"], "raw_response": submission["raw_response"],
            "tool_receipts": submission.get("tool_receipts") or [],
            "plan": normalized}
    body["response_digest"] = _digest(body)
    _write_once(_directory(workspace, trial_id) / f"{arm}.json", body)
    return body


def _metrics(curve):
    points = (curve.get("net") or {}).get("curve") or []
    missing = (curve.get("mark_coverage") or {}).get("skipped_dates") or []
    valid = [p for p in points if p.get("followed_sim") is not None
             and p.get("buy_and_hold") is not None]
    if not valid or missing:
        # Dropping a missing final mark would present an earlier payoff as the
        # trial result; interior gaps also hide drawdowns and upside moves.
        # Keep the partial curve in simulation, withhold comparable metrics.
        return {"status": "missing_marks", "missing_marks": missing}
    peak = valid[0]["followed_sim"]
    drawdown = 0.0
    gains, captured = 0.0, 0.0
    for previous, point in zip(valid, valid[1:]):
        peak = max(peak, point["followed_sim"])
        if peak > 0:
            drawdown = min(drawdown, point["followed_sim"] / peak - 1)
        change = point["buy_and_hold"] - previous["buy_and_hold"]
        if change > 0:
            gains += change
            captured += point["followed_sim"] - previous["followed_sim"]
    charges = (curve.get("net") or {}).get("charges") or []
    initial = valid[0]["buy_and_hold"]
    diff = valid[-1]["followed_sim"] - valid[-1]["buy_and_hold"]
    return {"status": "descriptive", "net_benefit": round(diff, 4),
            "missed_gain": round(max(0, -diff), 4),
            "upside_capture": captured / gains if gains > 0 else None,
            "max_drawdown": drawdown,
            "turnover": sum(c.get("notional", 0) for c in charges) / initial if initial > 0 else None,
            "idle_cash": [p.get("followed_cash") for p in valid],
            "missing_marks": missing}


def replay(workspace, trial_id, *, as_of=None, now=None):
    """Reuse settlement and the cash/inventory simulator without touching live rows."""
    trial = _registration(workspace, trial_id)
    if trial["evaluator_version"] != _evaluator_version():
        raise ValueError("replay with the registered evaluator revision")
    yesterday = (date.fromisoformat(_today(now)) - timedelta(days=1)).isoformat()
    as_of = min(as_of or yesterday, trial["end_date"])
    if as_of >= _today(now):
        raise ValueError("cannot evaluate future outcomes")
    result = {"trial_id": trial_id, "protocol": trial["protocol"], "as_of": as_of,
              "status": "pending" if as_of < trial["end_date"] else "descriptive",
              "realized_returns": None, "automatic_selection": False, "arms": {}}
    for arm in ARMS:
        path = _directory(workspace, trial_id) / f"{arm}.json"
        if not path.exists():
            result["arms"][arm] = {"status": "missing", "proposed": 0}
            continue
        saved = json.loads(path.read_text())
        if saved.get("response_digest") != _digest({
                k: v for k, v in saved.items() if k != "response_digest"}):
            raise ValueError("frozen response digest mismatch")
        if saved["input_digest"] != _digest(inputs(workspace, trial_id, arm)):
            raise ValueError("arm input digest mismatch")
        rows = copy.deepcopy(saved["plan"].get("decisions") or [])
        summary = {"status": saved["status"], "proposed": len(rows)}
        result["arms"][arm] = summary
        if saved["status"] != "ok" or as_of < trial["start_date"]:
            continue
        ledger.settle_decisions(rows, now_date=(
            date.fromisoformat(as_of) + timedelta(days=1)).isoformat())
        simulation = shadow.build_shadow_portfolio(
            trial["portfolio"], rows, as_of=as_of + "T23:59:59+00:00",
            start_dates={leg: trial["start_date"] for leg in trial["leg_config"]},
            leg_config=trial["leg_config"],
            bar_loader=ledger.bar, bar_map_loader=ledger.load_ticker_bars,
            matched={}, cost_model=costs.CostModel(**trial["cost_model"]), include_idle=True)
        summary.update(simulation=simulation,
                       metrics={ccy: _metrics(curve) for ccy, curve in simulation["curves"].items()},
                       decisions=rows)
        if not simulation["curves"]:
            summary["status"] = "no_triggered_actions_or_missing_marks"
    tickers = {str(row.get("ticker")) for book in trial["portfolio"]["portfolios"].values()
               for row in book.get("holdings", []) if row.get("ticker")}
    for arm in result["arms"].values():
        tickers.update(str(row["ticker"]) for row in arm.get("decisions", []) if row.get("ticker"))
    result["settlement_bars"] = {
        ticker: {day: bar for day, bar in ledger.load_ticker_bars(ticker).items() if day <= as_of}
        for ticker in sorted(tickers)}
    result["registered_trials"] = len(list((Path(workspace) / "memory" / "method-trials").glob(
        "trial-*/registration.json")))
    # Reports are content-addressed; replays after a bar repair retain the old
    # report and show a new hash rather than rewriting the previous result.
    _write_once(_directory(workspace, trial_id) / ("report-" + _digest(result)[:16] + ".json"), result)
    return result

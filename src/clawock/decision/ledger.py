"""clawock decision ledger v2.

The legacy scorecard treated every plan row as an independent prediction and
added percentage points across positions.  V2 keeps the raw decision events but
scores one representative per strategy episode, only after its condition
actually fired.  That representative carries the episode's mean benefit rather
than an elected member, because the choice of member moves the answer across the
50% line on its own (see ``episode_representatives``).  Multiple decisions for
one ticker/day remain valid when they belong to different strategies (core
position, intraday T, risk rebalance, …).

Authoritative persisted store: ``memory/decisions.jsonl``.
Plan contract: ``schema_version=2`` + top-level ``decisions``.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import re
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from clawock.market_data import sessions as _cal
from clawock.decision.actions import (
    ACTIVE_ACTIONS,
    ADD_ACTIONS,
    PASSIVE_ACTIONS,
    SELL_ACTIONS,
)
from clawock.workspace import workspace_root

# Installed package code resolves user state from the caller's workspace, never
# from site-packages or a source checkout path.
WS = workspace_root(Path.cwd())
LEDGER = WS / "memory" / "decisions.jsonl"
SNAP_DIR = WS / "memory" / "snapshots"

SCHEMA_VERSION = 2
# Bumped when the meaning of an evaluation changes, so a stale row is identifiable.
EVAL_SCHEMA_VERSION = 5
# Snapshots and plan_dates are both named on the HK calendar day; comparing them
# against a UTC "today" slips a day for the eight hours after HK midnight.
HKT = timezone(timedelta(hours=8))
ACTIONS = {
    "cut", "trim_on_rebound", "hold_and_watch", "t_only",
    "add_only_on_trigger", "add_on_breakout", "watch",
}
CONDITION_TYPES = {
    "open", "price_above", "price_below", "index_breakdown",
    "event", "manual", "always",
}
DRIVERS = {"technical", "catalyst", "sentiment", "influencer", "macro", "peer", "risk_rule"}
REGIMES = {"risk_on", "neutral", "risk_off", "unknown"}
STRATEGIES = {
    "core_position", "risk_rebalance", "intraday_t", "event_trade",
    "tactical_entry", "legacy_unknown",
}
AUDIT_SCHEMA_VERSION = 1

# How long after plan_date an execution verdict is allowed to still be pending.
# Sitting still is verifiable the next day; acting gets a working day to reach
# the book. Same reason as PASSIVE_ACTIONS above: this used to live inline in
# `brief_preflight._detect_followed`, and _exec_rate needs the identical rule to
# tell "not verifiable yet" from "will never be verified". Two copies of a rule
# nobody looks at drift, and the drift is invisible — the first measurement for
# #294 read `bucket` instead of `action`, got the wrong window for every passive
# row, and produced a plausible answer that was wrong by 6 points.
SAME_DAY_STANCES = {"hold_and_watch", "watch", "t_only"}


def verification_window_days(
    action: str | None, *, plan_date: str | None = None,
    leg: str | None = None, valid_for_sessions: int | None = None,
) -> int:
    """Calendar span before an unresolved execution is permanent.

    Multi-session adds are converted from their own leg's trading calendar.
    The fallback remains deliberately conservative for legacy callers that do
    not carry a leg/condition yet.
    """
    action = (action or "").lower()
    if action in SAME_DAY_STANCES:
        return 1
    if action in ADD_ACTIONS:
        if plan_date and leg and valid_for_sessions:
            try:
                market_leg = leg.upper()
                start = plan_date
                if not is_session(market_leg, start):
                    starts = next_sessions(market_leg, start, 1)
                    start = starts[0] if starts else start
                remaining = max(0, min(9, int(valid_for_sessions) - 1))
                sessions = next_sessions(market_leg, start, remaining) if remaining else []
                end = sessions[-1] if sessions else start
                if end:
                    return max(
                        1,
                        (date.fromisoformat(end)
                         - date.fromisoformat(plan_date)).days,
                    )
            except (TypeError, ValueError):
                pass
        # Legacy add rows did not persist the session window or leg.
        return 9
    return 2

# Confidence is calibrated prospectively over strategy episodes, never by fitting
# and scoring the same row. Sparse leaves borrow pseudo-observations from their
# parent rather than pretending a 1/1 subgroup is a stable 100% signal.
CALIBRATION_PARENT_STRENGTH = 8.0
CALIBRATION_MIN_PRIOR_EPISODES = 12
CALIBRATION_MIN_PRIOR_DATES = 5
CALIBRATION_MAX_CI_WIDTH = 0.45


def _slug(value: object, fallback: str = "unknown") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return s or fallback


def _stable_id(prefix: str, *parts: object, size: int = 12) -> str:
    raw = "\x1f".join(str(p or "") for p in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode()).hexdigest()[:size]}"


def _float(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value):
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def infer_strategy(action: dict) -> str:
    """Best-effort legacy classifier. New plans must state strategy_id."""
    bucket = action.get("action") or action.get("bucket") or ""
    text = " ".join(str(action.get(k) or "") for k in ("rationale", "size_note", "trigger_condition")).lower()
    if bucket == "t_only" or "日内" in text or "做t" in text:
        return "intraday_t"
    risk_words = ("硬止损", "止损", "breach", "cap", "上限", "降杠杆", "换仓", "再平衡", "single_name", "regime")
    if any(w in text for w in risk_words):
        return "risk_rebalance"
    if action.get("driven_by") == "catalyst" or action.get("trigger_type") == "event":
        return "event_trade"
    if bucket in ("add_only_on_trigger", "add_on_breakout"):
        return "tactical_entry"
    return "core_position"


def legacy_action_to_decision(action: dict, plan_date: str, ordinal: int = 0) -> dict:
    ticker = str(action.get("ticker") or "").strip()
    act = action.get("action") or action.get("bucket") or "watch"
    act = {"sell": "cut", "buy": "add_only_on_trigger", "hold": "hold_and_watch"}.get(act, act)
    strategy = action.get("strategy_id") or infer_strategy(action)
    authored_condition = action.get("condition") if isinstance(action.get("condition"), dict) else {}
    authored_size = action.get("size") if isinstance(action.get("size"), dict) else {}
    condition_type = authored_condition.get("type") or action.get("trigger_type") or "manual"
    condition_price = _float(authored_condition.get("price"))
    if condition_price is None:
        condition_price = _float(action.get("trigger_price"))
    if condition_type not in CONDITION_TYPES:
        condition_type = "manual"
    if condition_type in ("price_above", "price_below") and condition_price is None:
        condition_type = "manual"  # legacy row had an unscorable price condition
    decision_id = action.get("decision_id") or _stable_id(
        "dec", plan_date, ticker, strategy, act, condition_type, condition_price, ordinal
    )
    thesis_id = action.get("thesis_id") or f"{_slug(ticker)}-{strategy}"
    created_at = action.get("created_at") or f"{plan_date}T08:00:00+08:00"
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "episode_id": action.get("episode_id"),
        "decision_group_id": action.get("decision_group_id") or f"{plan_date}:{ticker}",
        "plan_date": plan_date,
        "created_at": created_at,
        "ticker": ticker,
        "name": action.get("name") or "",
        "leg": action.get("leg") or ("HK" if ticker.isdigit() else "US"),
        "strategy_id": strategy,
        "thesis_id": thesis_id,
        "action": act,
        "condition": {
            "type": condition_type,
            "price": condition_price,
            "description": authored_condition.get("description") or action.get("trigger_condition") or "",
            "valid_for_sessions": _int(
                authored_condition.get("valid_for_sessions")
            ) or 1,
        },
        "size": {
            "shares": _int(authored_size.get("shares")) if authored_size else _int(action.get("size_shares")),
            "pct": _float(authored_size.get("pct")) if authored_size else _float(action.get("size_pct")),
            "note": authored_size.get("note") or action.get("size_note") or "",
        },
        "confidence": _float(action.get("confidence")),
        "driven_by": action.get("driven_by") or "technical",
        "evidence_event_id": action.get("evidence_event_id"),
        "regime": action.get("regime") if action.get("regime") in REGIMES else "unknown",
        "rationale": action.get("rationale") or "",
        "technical_setup_id": action.get("technical_setup_id"),
        "technical_campaign_id": action.get("technical_campaign_id"),
        "invalidation_price": _float(action.get("invalidation_price")),
        "tranche_number": _int(action.get("tranche_number")),
        # Additive contract marker: pre-2026-08 plans remain valid/readable, while
        # every newly normalized plan is subject to the technical trace rules.
        "technical_trace_version": 1,
        # Written by postflight from the generation-pinned decision packet.
        # A model-authored value is replaced before validation and ledger upsert.
        "signal_provenance": action.get("signal_provenance"),
        "simulated_entry_price": _float(action.get("simulated_entry_price")),
        "horizon_sessions": int(action.get("horizon_sessions") or 1),
        "override": action.get("override") or {
            "status": "none", "reason": "", "expires_on": None, "revisit_condition": ""
        },
        "evaluation": action.get("evaluation") or {
            "status": "pending", "triggered": None, "trigger_session": None,
            "execution_price": None, "underlying_return_t1_pct": None,
            "benefit_t1_pct": None, "benefit_t5_pct": None, "outcome": "pending",
            "capital": None,
        },
        "execution": action.get("execution") or {
            "status": "unknown", "detected_at": None, "source": None,
        },
        "migration": action.get("migration") or {"source": "plan_v1"},
    }


def assign_episode_ids(decisions: list[dict]) -> list[dict]:
    """Assign episodes across consecutive reaffirmations of the same strategy/action.

    An episode is tracked per (ticker, strategy, ACTION), so each standing view
    keeps its own thread and they may overlap. Before 2026-07-15 the thread was
    per (ticker, strategy) and *any* later decision overwrote it, which meant one
    interleaved hold_and_watch silently shattered a running cut thesis: 00100
    said cut 05-18, hold 05-19, cut 05-20 and scored as two independent cut bets.
    That happened at 20 boundaries and is v1's disease — reaffirmations inflating
    n — surviving inside v2 through a mechanism nobody checked. The model shouts
    cut for two months while wobbling into hold on the quiet days; that is one
    opinion it never got two independent chances to be right about.

    A gap over four calendar days still starts a new episode. Different
    strategy_id values never collide, so a core HOLD and a risk-rebalance TRIM
    can coexist on the same ticker/day.

    Condition, trigger price, confidence and size are deliberately NOT in the
    key, and 2026-07-15 is why: adding them looks more precise and quietly
    rebuilds v1's disease. 00100 spent 06-17..07-15 restating one "trim into any
    bounce" thesis while walking its trigger 460 -> 265 down a crash and drifting
    price_above/open/manual. Keying on those fields split that single thesis into
    8-10 episodes and booked each restatement as its own settled winning bet —
    +4,419 HKD conjured out of one call. A reaffirmation is a reaffirmation even
    when it is re-anchored to where the stock has since moved.
    """
    ordered = sorted(enumerate(decisions), key=lambda x: (x[1].get("plan_date", ""), x[0]))
    state: dict[tuple[str, str, str], dict] = {}
    for _, d in ordered:
        key = (d.get("ticker", ""), d.get("strategy_id", "legacy_unknown"), d.get("action"))
        cur_date = datetime.strptime(d["plan_date"], "%Y-%m-%d").date()
        if d.get("episode_id"):
            state[key] = {"date": cur_date, "episode_id": d.get("episode_id")}
            continue
        prev = state.get(key)
        continue_episode = False
        if prev:
            gap = (cur_date - prev["date"]).days
            continue_episode = 0 <= gap <= 4
        if continue_episode:
            episode_id = prev["episode_id"]
        else:
            episode_id = _stable_id(
                "ep", d.get("ticker"), d.get("strategy_id"), d.get("action"), d.get("plan_date"), d.get("decision_id")
            )
        d["episode_id"] = episode_id
        state[key] = {"date": cur_date, "episode_id": episode_id}
    return decisions


def validate_decision(d: dict) -> list[str]:
    # Decision-mind conversation records (docs/decision-mind-ledger.md) are a
    # deliberate second ledger row type: they carry mind/emotion instead of the
    # plan-decision fields below, and are validated by their own rules.
    if d.get("schema_version") == 0 and d.get("source") == "conversation":
        from clawock.decision.record import validate_mind_record
        return validate_mind_record(d)
    errors = []
    for key in ("decision_id", "episode_id", "plan_date", "created_at", "ticker", "strategy_id", "action", "condition"):
        if d.get(key) in (None, ""):
            errors.append(f"missing {key}")
    if d.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be 2")
    if d.get("action") not in ACTIONS:
        errors.append(f"bad action {d.get('action')!r}")
    if d.get("strategy_id") not in STRATEGIES:
        errors.append(f"bad strategy_id {d.get('strategy_id')!r}")
    condition = d.get("condition") or {}
    if condition.get("type") not in CONDITION_TYPES:
        errors.append(f"bad condition.type {condition.get('type')!r}")
    if condition.get("type") in ("price_above", "price_below") and _float(condition.get("price")) is None:
        errors.append("price condition requires condition.price")
    valid_for_sessions = _int(condition.get("valid_for_sessions")) or 1
    if not 1 <= valid_for_sessions <= 10:
        errors.append("condition.valid_for_sessions must be in [1,10]")
    conf = _float(d.get("confidence"))
    if conf is None or not 0 <= conf <= 1:
        errors.append("confidence must be in [0,1]")
    if d.get("driven_by") not in DRIVERS:
        errors.append(f"bad driven_by {d.get('driven_by')!r}")
    evidence_event_id = d.get("evidence_event_id")
    if (evidence_event_id is not None
            and (not isinstance(evidence_event_id, str)
                 or not evidence_event_id.startswith("evt_"))):
        errors.append("evidence_event_id must be null or an evt_ id")
    setup_id = d.get("technical_setup_id")
    campaign_id = d.get("technical_campaign_id")
    trace_version = d.get("technical_trace_version")
    if trace_version not in (None, 1):
        errors.append("technical_trace_version must be 1 when present")
    if setup_id is not None and (not isinstance(setup_id, str) or not setup_id):
        errors.append("technical_setup_id must be null or non-empty text")
    if trace_version == 1 and d.get("action") in ADD_ACTIONS:
        prefix = "technical add" if d.get("driven_by") == "technical" else "add"
        if not setup_id:
            errors.append(f"{prefix} requires technical_setup_id")
        if not isinstance(campaign_id, str) or not campaign_id:
            errors.append(f"{prefix} requires technical_campaign_id")
        if _float(d.get("invalidation_price")) is None:
            errors.append(f"{prefix} requires invalidation_price")
        if (_int(d.get("tranche_number")) or 0) < 1:
            errors.append(f"{prefix} requires tranche_number >= 1")
    if d.get("regime", "unknown") not in REGIMES:
        errors.append(f"bad regime {d.get('regime')!r}")
    override = d.get("override") or {}
    if override.get("status", "none") not in ("none", "active", "expired", "revoked"):
        errors.append(f"bad override.status {override.get('status')!r}")
    return errors


def missing_size_warnings(decisions: list[dict]) -> list[str]:
    """Active calls with no share count. A warning, never an error.

    Without shares there is no capital, so the call can be scored for direction
    but never priced — it silently vanishes from the only chart that answers
    "what did listening to it cost me?". Migrated v1 rows often lack it and must
    not be rejected retroactively, so this stays advisory and is reported by
    postflight against newly authored plans.
    """
    out = []
    for d in decisions:
        if d.get("action") in ACTIVE_ACTIONS and _int((d.get("size") or {}).get("shares")) is None:
            out.append(f"{d.get('ticker')} {d.get('action')}: size.shares missing → unpriceable")
    return out


def missing_regime_warnings(decisions: list[dict]) -> list[str]:
    """Prospective plans need an authored regime; legacy rows remain readable."""
    missing = [
        f"{d.get('ticker')}/{d.get('strategy_id')}"
        for d in decisions if d.get("regime", "unknown") == "unknown"
    ]
    return (
        ["regime missing/unknown for " + ", ".join(missing)]
        if missing else []
    )


def validate_plan(plan: dict, path: str | Path | None = None) -> list[str]:
    """Validate an authored plan. Pass ``path`` to also enforce date == filename.

    2026-06-01-plan.json once shipped with date="2026-06-02". Every id downstream
    is derived from that field, so both days minted the same decision_ids: six
    collided, the later day's thesis was silently dropped, and the survivors were
    graded against the wrong session. Nothing caught it for six weeks — the rows
    were individually valid. Callers holding a filename must pass it.
    """
    errors = []
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append("top-level schema_version must be 2")
    if not plan.get("date"):
        errors.append("missing date")
    if path is not None:
        expected = Path(path).name[:10]
        if plan.get("date") and plan.get("date") != expected:
            errors.append(f"date {plan.get('date')!r} must match filename ({expected!r})")
    if "actions" in plan:
        errors.append("v1 actions field is forbidden")
    decisions = plan.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        errors.append("decisions must be a non-empty list")
        return errors
    seen = set()
    for i, d in enumerate(decisions):
        for err in validate_decision(d):
            errors.append(f"decision[{i}] {err}")
        did = d.get("decision_id")
        if did in seen:
            errors.append(f"duplicate decision_id {did}")
        seen.add(did)
    return errors


def normalize_authored_plan(plan: dict, ledger_path: Path = LEDGER) -> dict:
    """Fill deterministic v2 ids/defaults before postflight validation."""
    plan_date = plan.get("date") or datetime.now().date().isoformat()
    source = plan.get("decisions") or []
    normalized = [legacy_action_to_decision(item, plan_date, i) for i, item in enumerate(source)]
    existing = load_decisions(ledger_path)
    assign_episode_ids(existing + normalized)
    out = {k: v for k, v in plan.items() if k != "actions"}
    out["schema_version"] = SCHEMA_VERSION
    out["decisions"] = normalized
    return out


def load_decisions(path: Path = LEDGER) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{path}:{n}: {e}") from e
    return out


def write_decisions(decisions: list[dict], path: Path = LEDGER) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(d, ensure_ascii=False, sort_keys=True) + "\n" for d in decisions)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def upsert_plan_decisions(plan: dict, path: Path = LEDGER) -> tuple[int, int]:
    existing = load_decisions(path)
    by_id = {d.get("decision_id"): d for d in existing}
    inserted = updated = 0
    for d in plan.get("decisions") or []:
        did = d.get("decision_id")
        if did in by_id:
            old = by_id[did]
            # Preserve live evaluation/execution while refreshing authored fields.
            evaluation = old.get("evaluation")
            execution = old.get("execution")
            old.update(d)
            if evaluation:
                old["evaluation"] = evaluation
            if execution:
                old["execution"] = execution
            updated += 1
        else:
            existing.append(d)
            by_id[did] = d
            inserted += 1
    assign_episode_ids(existing)
    write_decisions(existing, path)
    return inserted, updated


_SNAP_CACHE: dict[str, dict | None] = {}


def snapshot_dates() -> list[str]:
    return sorted(p.stem for p in SNAP_DIR.glob("20*.json"))


def load_snapshot(day: str) -> dict | None:
    if day not in _SNAP_CACHE:
        p = SNAP_DIR / f"{day}.json"
        try:
            _SNAP_CACHE[day] = json.loads(p.read_text()) if p.exists() else None
        except Exception:
            _SNAP_CACHE[day] = None
    return _SNAP_CACHE[day]


def holding_from_snapshot(snapshot: dict | None, ticker: str) -> dict | None:
    for region in ("hk_stocks", "us_stocks"):
        for h in (snapshot or {}).get("portfolios", {}).get(region, {}).get("holdings", []):
            if str(h.get("ticker")) == str(ticker):
                return h
    return None


def _price(snapshot: dict | None, ticker: str, field: str = "current_price"):
    return _float((holding_from_snapshot(snapshot, ticker) or {}).get(field))


# ---------------------------------------------------------------------------
# Canonical bars — the only thing allowed to decide whether a condition fired.
#
# Settlement used to read `memory/snapshots/{date}.json`, a *portfolio* file whose
# prices carry the vintage of whatever cron fetched them. Measured on 00100 across
# 15 snapshots, `current_price` was the previous close 7 times, that day's close 3
# times, and an intraday print 5 times — so "T+1" was really "the next snapshot's
# quote". Worse, `day_high`/`day_low` are carried forward for live positions: 00100
# showed the identical (738.0, 744.5, 731.0) on four consecutive sessions. Judging
# `price_above` against that invented triggers that never fired (07226 2026-05-27
# read a stored high of 4.192 against a real 3.96) and discarded ones that did
# (00100 2026-05-18 read 744.5 against a real 827.5, dropping a winner).
#
# `memory/bars/` is session-dated, unadjusted, and never contains an unfinished
# session. The workspace bar writer owns the store's refresh contract.
# ---------------------------------------------------------------------------

BARS_DIR = WS / "memory" / "bars"
_BAR_CACHE: dict[str, dict] = {}
_SESSION_CACHE: dict[str, list[str]] = {}


def load_ticker_bars(ticker: str) -> dict:
    """{date: {open, high, low, close, ...}} for one ticker. Empty if unknown."""
    if ticker not in _BAR_CACHE:
        p = BARS_DIR / f"{ticker}.json"
        try:
            _BAR_CACHE[ticker] = (json.loads(p.read_text()).get("bars") or {}) if p.exists() else {}
        except Exception:
            _BAR_CACHE[ticker] = {}
    return _BAR_CACHE[ticker]


def bar(ticker: str, day: str) -> dict | None:
    return load_ticker_bars(ticker).get(day)


def ticker_retired(ticker: str) -> bool:
    """Whether the store *declares* this instrument retired — never an inference.

    This has to be a fact someone wrote down (fetch_daily_bars' MANIFEST), because
    the obvious shortcut — "the session we want is past this ticker's newest bar" —
    cannot tell a retired line apart from a writer that stopped running for it. Under
    that shortcut a frozen active ticker had its decisions filed as
    instrument_inactive and quietly left the denominator, which is the same
    silent-shrinkage failure `leg_sessions` above refuses to commit.
    """
    p = BARS_DIR / f"{ticker}.json"
    try:
        return bool(json.loads(p.read_text()).get("retired", False)) if p.exists() else False
    except Exception:
        return False


def leg_sessions(leg: str) -> list[str]:
    """Sessions this leg's bar store actually holds data for.

    NB this answers "do we have the data", never "was the market open" — those are
    different questions and conflating them is a bug: on 2026-07-15 the US market is
    open and simply has not closed yet, so no bar exists. Reading that absence as a
    holiday would file 10 live decisions as "market_closed" and quietly drop them
    from the denominator. `trading_calendar` is the authority on open/closed.
    """
    if leg not in _SESSION_CACHE:
        days: set[str] = set()
        for p in BARS_DIR.glob("*.json"):
            try:
                doc = json.loads(p.read_text())
            except Exception:
                continue
            if doc.get("leg") == leg:
                days.update(doc.get("bars") or {})
        _SESSION_CACHE[leg] = sorted(days)
    return _SESSION_CACHE[leg]


def is_session(leg: str, day: str) -> bool:
    """Was this market open on this date? Calendar only — never inferred from data."""
    try:
        return _cal.is_trading_day(leg.lower(), date.fromisoformat(day))
    except Exception:
        return False


def next_sessions(leg: str, after: str, count: int = 1) -> list[str]:
    """The next ``count`` trading sessions strictly after ``after``, per the calendar.

    Counting sessions rather than calendar days is what makes T+1 mean T+1 across a
    weekend or a holiday — and a leg never borrows the other leg's calendar.
    """
    out: list[str] = []
    d = date.fromisoformat(after)
    for _ in range(40):
        d += timedelta(days=1)
        iso = d.isoformat()
        if is_session(leg, iso):
            out.append(iso)
            if len(out) == count:
                break
    return out


def last_closed_session(leg: str) -> str | None:
    """Newest session whose bar we would expect to exist by now."""
    sess = leg_sessions(leg)
    return sess[-1] if sess else None


def evaluation_session(decision: dict) -> tuple[str | None, str]:
    """Which session actually grades this decision, and why.

    The brief is authored 08:00 HKT, before HK opens (09:30 HKT) and long before the
    US does (09:30 ET) — so on a normal trading day both legs are graded by
    `plan_date`'s own session.

    Three things break that:

    * **Weekend briefs.** 15 decisions carry a Sunday plan_date (2026-05-17 and
      2026-05-31); they were written for the Monday and there is no Sunday session.
      They map forward to the next session explicitly.
    * **Weekday holidays.** A weekday with no session is NOT rolled forward. Rolling
      would re-point ROBN's 2026-07-03 call (US shut for Independence Day) at 07-06
      and grade it against three days of information its author never had.
    * **Corrupt authoring timestamps.** 10 decisions claim `plan_date=2026-06-01`
      but were written `2026-06-02T08:00`. They cannot be graded on 06-01 (the
      author had not written them yet) and must not be moved to 06-02 either, where
      a real 06-02 brief already exists and would be double-counted.
    """
    pd = decision.get("plan_date")
    leg = decision.get("leg") or ("HK" if str(decision.get("ticker", "")).isdigit() else "US")
    if not pd:
        return None, "no_plan_date"
    try:
        date.fromisoformat(pd)
    except ValueError:
        return None, "bad_plan_date"

    created = (decision.get("created_at") or "")[:10]
    if created and created > pd:
        return None, "invalid_authored_timestamp"

    if not is_session(leg, pd):
        if date.fromisoformat(pd).weekday() >= 5:
            nxt = next_sessions(leg, pd, 1)
            return (nxt[0], "weekend_brief_graded_next_session") if nxt else (None, "no_session_after_weekend")
        return None, "market_closed"
    return pd, "plan_date"


def condition_execution(decision: dict, day_bar: dict | None) -> tuple[bool | None, float | None, str]:
    """(fired, fill_price, reason) for one decision against one canonical bar.

    Fills are gap-aware. A stop at 100 that gaps open to 92 does not fill at 100 —
    assuming it did would hand every gapped trigger a free 8%. So a crossing inside
    the session fills at the trigger, and a gap straight through it fills at the
    open. Still assumes zero slippage and available liquidity, which is why the
    evaluation records ``fill_assumed``.
    """
    cond = decision.get("condition") or {}
    ctype = cond.get("type") or "manual"
    action = decision.get("action")
    if day_bar is None:
        return None, None, "no_bar"

    o, h, l = day_bar["open"], day_bar["high"], day_bar["low"]

    # hold/watch take no action. There is no fill: the position is simply carried,
    # so the open is a *reference* price, not an execution. Their `condition` is
    # normally an exit/invalidation level rather than an entry trigger, and it is
    # deliberately NOT evaluated here — grading a stop as if it were an entry is
    # what let `by_condition` mix two opposite meanings.
    if action in PASSIVE_ACTIONS:
        return True, o, "stance_at_open"
    if ctype in ("always", "open"):
        return True, o, "session_open"

    trigger = _float(cond.get("price"))
    if ctype == "price_above" and trigger is not None:
        if h < trigger:
            return False, None, "high_below_trigger"
        return True, max(o, trigger), ("gap_through" if o >= trigger else "intraday_cross")
    if ctype == "price_below" and trigger is not None:
        if l > trigger:
            return False, None, "low_above_trigger"
        return True, min(o, trigger), ("gap_through" if o <= trigger else "intraday_cross")

    # event / manual / index need human evidence; never fabricate a trigger.
    return None, None, "needs_human_evidence"


def _benefit(action: str, entry: float | None, later: float | None) -> tuple[float | None, float | None]:
    if not entry or later is None:
        return None, None
    underlying = (later - entry) / entry * 100
    advantage = -underlying if action in SELL_ACTIONS else underlying
    return round(underlying, 4), round(advantage, 4)


def _outcome(benefit: float | None) -> str:
    """win / loss / flat.

    Zero used to fall through to "loss", and the value was rounded to 4dp before the
    comparison — so a call that moved nothing, or moved less than 0.00005%, was
    recorded as wrong. Exact-zero is its own thing.
    """
    if benefit is None:
        return "pending"
    if benefit > 0:
        return "win"
    if benefit < 0:
        return "loss"
    return "flat"


def settle_decisions(decisions: list[dict], now_date: str | None = None) -> int:
    """Recompute trigger and T+1/T+5 outcomes from canonical bars, in place.

    Every price here is a session-dated close from `memory/bars/`. An unfinished
    session is never in that store, so today cannot score anything — the intraday
    cron rewriting today's snapshot used to flip settled calls between win and loss
    on nothing but the tape.

    Preserves `episode_id`, `execution` and `override`: this recomputes the
    evaluation only. Mixing an episode-rule change into the same pass would make the
    resulting metric shift impossible to attribute.
    """
    today = now_date or datetime.now(HKT).date().isoformat()
    changed = 0
    for d in decisions:
        plan_date = d.get("plan_date")
        if not plan_date or plan_date > today:
            continue
        before = json.dumps(d.get("evaluation"), sort_keys=True)
        ticker = d.get("ticker")
        leg = d.get("leg") or ("HK" if str(ticker or "").isdigit() else "US")
        ev = d.setdefault("evaluation", {})
        # Wipe derived fields so a stale value can never survive a rule change.
        for k in ("triggered", "trigger_session", "execution_price", "capital", "status",
                  "outcome", "underlying_return_t1_pct", "benefit_t1_pct", "benefit_t5_pct",
                  "benefit_t20_pct",
                  "fill_reason", "fill_assumed", "fill_model", "session_reason",
                  "not_evaluable_reason", "mark_t1_session", "mark_t5_session",
                  "mark_t20_session",
                  "evaluation_mode", "reference_price", "reference_reason",
                  "condition_role", "pending_reason", "mark_horizon",
                  "evaluation_schema_version"):
            ev.pop(k, None)

        sess, sess_reason = evaluation_session(d)
        ev["session_reason"] = sess_reason
        if sess is None:
            ev.update({"triggered": None, "status": "not_evaluable", "outcome": "unknown",
                       "not_evaluable_reason": sess_reason})
            if json.dumps(ev, sort_keys=True) != before:
                changed += 1
            continue

        condition = d.get("condition") or {}
        window = max(1, min(10, _int(condition.get("valid_for_sessions")) or 1))
        candidate_sessions = [sess]
        if window > 1:
            candidate_sessions += next_sessions(leg, sess, window - 1)
        evaluated = []
        fired = fill = fill_reason = None
        trigger_session = None
        pending_session = None
        missing_session = None
        invalidated_session = None
        invalidation = _float(d.get("invalidation_price"))
        for candidate in candidate_sessions:
            day_bar = bar(ticker, candidate)
            if day_bar is None:
                if candidate >= today or candidate > (last_closed_session(leg) or ""):
                    pending_session = candidate
                    break
                missing_session = candidate
                break
            evaluated.append(candidate)
            # An authorised add is cancelled as soon as its risk line trades.
            # We intentionally treat an ambiguous same-day low-below/high-above
            # bar as invalidated: daily OHLC cannot prove the trigger happened
            # first, and optimism here would be lookahead by assumption.
            if (
                d.get("action") in ADD_ACTIONS
                and invalidation is not None
                and day_bar["low"] <= invalidation
            ):
                invalidated_session = candidate
                fired, fill, fill_reason = False, None, "invalidation_traded"
                break
            fired, fill, fill_reason = condition_execution(d, day_bar)
            if fired is True or fired is None:
                trigger_session = candidate if fired is True else None
                break
        if missing_session is not None:
            inactive = ticker_retired(ticker)
            ev.update({
                "triggered": None,
                "status": "not_evaluable",
                "outcome": "unknown",
                "not_evaluable_reason": (
                    "instrument_inactive" if inactive else "bar_missing"
                ),
                "trigger_session": missing_session,
            })
            if json.dumps(ev, sort_keys=True) != before:
                changed += 1
            continue
        if not evaluated and pending_session:
            # The market WAS open (the calendar said so) but we have no bar. Either
            # the session has not closed yet — which is pending, not unevaluable —
            # or this instrument genuinely did not trade (not yet listed, halted, or
            # retired — an instrument declared `retired` in fetch_daily_bars' MANIFEST).
            last = last_closed_session(leg) or ""
            if pending_session > last:
                ev.update({"triggered": None, "status": "pending", "outcome": "pending",
                           "pending_reason": "session_not_final", "trigger_session": pending_session})
            else:
                inactive = ticker_retired(ticker)
                ev.update({"triggered": None, "status": "not_evaluable", "outcome": "unknown",
                           "not_evaluable_reason": "instrument_inactive" if inactive else "bar_missing",
                           "trigger_session": pending_session})
            if json.dumps(ev, sort_keys=True) != before:
                changed += 1
            continue

        shares = _int((d.get("size") or {}).get("shares"))
        passive = d.get("action") in PASSIVE_ACTIONS
        ev["evaluation_schema_version"] = EVAL_SCHEMA_VERSION
        if passive:
            # No trade happened, so nothing may look like one. `reference_price` is
            # the first tradable price after publication; execution_price/fill_model
            # stay absent so a stance can never be counted as a fill.
            ev.update({
                "triggered": True,
                "trigger_session": trigger_session or sess,
                "evaluation_mode": "passive_stance",
                "reference_price": fill,
                "reference_reason": "first_tradable_price_after_publication",
                "condition_role": "invalidation",
                "fill_assumed": False,
            })
        else:
            ev.update({
                "triggered": fired,
                "trigger_session": trigger_session if fired else None,
                "evaluation_mode": "active_fill",
                "condition_role": "entry",
                "execution_price": fill,
                "capital": round(fill * shares, 2) if fill and shares else None,
                "fill_reason": fill_reason,
                "fill_assumed": bool(fired),
                "fill_model": "daily_ohlc_gap_aware_v1" if fired else None,
            })
        if fired is False:
            if invalidated_session:
                ev.update({
                    "status": "not_triggered", "outcome": "not_triggered",
                    "not_evaluable_reason": "campaign_invalidated",
                    "trigger_session": invalidated_session,
                })
            elif pending_session and len(evaluated) < window:
                ev.update({
                    "status": "pending", "outcome": "pending",
                    "pending_reason": "confirmation_window_open",
                    "trigger_session": pending_session,
                })
            else:
                ev.update({"status": "not_triggered", "outcome": "not_triggered"})
        elif fired is None:
            ev.update({"status": "not_evaluable", "outcome": "unknown",
                       "not_evaluable_reason": fill_reason})
        else:
            entry = fill
            fill_session = trigger_session or sess
            marks = next_sessions(leg, fill_session, 20)
            b1 = b5 = b20 = u1 = None
            m1 = m5 = m20 = None
            reason = None
            if marks:
                m1 = marks[0]
                nb = bar(ticker, m1)
                if m1 >= today:
                    # Belt and braces: the bar store never holds an unfinished
                    # session, but a mark dated today must not score regardless of
                    # where the price came from. This is the defect that let a
                    # settled call flip win/loss with the intraday tape.
                    reason = "session_not_final"
                elif nb is None:
                    # "Has not closed yet" vs "this instrument had no bar for a
                    # session that did happen" are different facts.
                    reason = ("mark_pending" if m1 > (last_closed_session(leg) or "")
                              else "mark_bar_missing")
                else:
                    u1, b1 = _benefit(d.get("action"), entry, nb["close"])
            if len(marks) >= 5:
                m5 = marks[4]
                nb5 = bar(ticker, m5)
                if nb5 is not None and m5 < today:
                    _, b5 = _benefit(d.get("action"), entry, nb5["close"])
            if len(marks) >= 20:
                m20 = marks[19]
                nb20 = bar(ticker, m20)
                if nb20 is not None and m20 < today:
                    _, b20 = _benefit(d.get("action"), entry, nb20["close"])
            ev.update({
                "status": "settled" if b1 is not None else "pending",
                "outcome": _outcome(b1),
                "underlying_return_t1_pct": u1,
                "benefit_t1_pct": b1,
                "benefit_t5_pct": b5,
                "benefit_t20_pct": b20,
                "mark_t1_session": m1 if b1 is not None else None,
                "mark_t5_session": m5 if b5 is not None else None,
                "mark_t20_session": m20 if b20 is not None else None,
                "mark_horizon": "open_of_session_to_close_of_next_session",
            })
            if b1 is None and reason:
                ev["pending_reason"] = reason
        if json.dumps(ev, sort_keys=True) != before:
            changed += 1
    return changed


def _portfolio_trades(portfolio: dict) -> list[dict]:
    """Flatten the broker-truth trade ledger with stable in-document identities."""
    out = []
    for region, leg in (("hk_stocks", "HK"), ("us_stocks", "US")):
        holdings = ((portfolio.get("portfolios") or {}).get(region) or {}).get("holdings") or []
        for holding_index, holding in enumerate(holdings):
            ticker = str(holding.get("ticker") or holding.get("code") or "")
            for trade_index, trade in enumerate(holding.get("trades") or []):
                row = copy.deepcopy(trade)
                row.update({
                    "ticker": ticker,
                    "leg": leg,
                    "_trade_id": f"{region}:{holding_index}:{trade_index}",
                })
                out.append(row)
    return out


def match_real_executions(decisions: list[dict], portfolio: dict) -> dict[str, dict]:
    """Strict one-to-one ledger matches for actual fills.

    A match requires same ticker, session date, direction and share count.  If one
    trade could satisfy several decisions (or vice versa), no fill is attributed:
    without a transaction/group id, choosing one would be hindsight fabrication.
    """
    trades = _portfolio_trades(portfolio)
    candidates: dict[str, list[dict]] = {}
    reverse: dict[str, list[str]] = defaultdict(list)
    for decision in decisions:
        did = decision.get("decision_id")
        ev = decision.get("evaluation") or {}
        execution = decision.get("execution") or {}
        shares = _int((decision.get("size") or {}).get("shares"))
        if (not did or execution.get("status") != "followed"
                or ev.get("triggered") is not True or not shares
                or decision.get("action") not in ACTIVE_ACTIONS):
            continue
        direction = "sell" if decision.get("action") in SELL_ACTIONS else "buy"
        session = ev.get("trigger_session")
        rows = [
            t for t in trades
            if t.get("ticker") == decision.get("ticker")
            and t.get("date") == session
            and str(t.get("action") or "").lower() == direction
            and _int(t.get("shares")) == shares
            and _float(t.get("price")) is not None
        ]
        candidates[did] = rows
        for trade in rows:
            reverse[trade["_trade_id"]].append(did)

    matched = {}
    for did, rows in candidates.items():
        if len(rows) == 1 and len(reverse[rows[0]["_trade_id"]]) == 1:
            matched[did] = rows[0]
    return matched


def _audit_path(decision: dict, max_sessions: int = 6) -> tuple[list[dict], dict]:
    """Canonical post-authoring OHLC path, never a portfolio snapshot."""
    ev = decision.get("evaluation") or {}
    start = ev.get("trigger_session")
    if not start:
        start, _ = evaluation_session(decision)
    bars = load_ticker_bars(str(decision.get("ticker") or ""))
    dates = [day for day in sorted(bars) if start and day >= start]
    end = ev.get("mark_t5_session")
    if end:
        dates = [day for day in dates if day <= end]
    dates = dates[:max_sessions]
    path = []
    for day in dates:
        raw = bars[day]
        path.append({
            "session": day,
            "open": _float(raw.get("open")),
            "high": _float(raw.get("high")),
            "low": _float(raw.get("low")),
            "close": _float(raw.get("close")),
        })
    expected = max_sessions if start else 0
    coverage = {
        "canonical_only": True,
        "adjustment": "raw",
        "path_points": len(path),
        "expected_points": expected,
        "path_complete": bool(path) and (bool(end) or len(path) >= expected),
        "start_session": start,
        "end_session": path[-1]["session"] if path else None,
    }
    return path, coverage


def _event_quantiles(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)

    def q(frac):
        pos = frac * (len(ordered) - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return ordered[lo]
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)

    return {
        "min": round(ordered[0], 2),
        "p10": round(q(.10), 2),
        "p25": round(q(.25), 2),
        "median": round(statistics.median(ordered), 2),
        "p75": round(q(.75), 2),
        "p90": round(q(.90), 2),
        "max": round(ordered[-1], 2),
    }


def _paired_block_ci(events: list[dict], samples: int = 2000) -> list[float] | None:
    """Paired bootstrap of median bps over ticker/date/episode blocks."""
    groups: dict[tuple, list[float]] = defaultdict(list)
    for event in events:
        groups[(
            event.get("ticker"), event.get("session"), event.get("episode_id")
        )].append(float(event["improvement_bps"]))
    blocks = sorted(groups)
    if len(blocks) < 3:
        return None
    rnd = random.Random(20260717)
    draws = []
    for _ in range(samples):
        values = []
        for _ in blocks:
            values.extend(groups[rnd.choice(blocks)])
        draws.append(statistics.median(values))
    draws.sort()
    return [
        round(draws[int(.025 * (len(draws) - 1))], 2),
        round(draws[int(.975 * (len(draws) - 1))], 2),
    ]


def compute_timing_diagnostic(decisions: list[dict], portfolio: dict,
                              matched: dict[str, dict] | None = None) -> dict:
    """Single-event close benchmark for uniquely matched real executions.

    Sell: shares × (actual fill − same-day close)
    Buy:  shares × (same-day close − actual fill)

    Different tickers are never paired as a swap.  HKD and USD are never summed.
    """
    matched = matched if matched is not None else match_real_executions(decisions, portfolio)
    events = []
    for decision in decisions:
        trade = matched.get(decision.get("decision_id"))
        if not trade:
            continue
        ev = decision.get("evaluation") or {}
        session = ev.get("trigger_session")
        close_bar = bar(str(decision.get("ticker") or ""), session) if session else None
        close = _float((close_bar or {}).get("close"))
        price = _float(trade.get("price"))
        shares = _int(trade.get("shares"))
        if close is None or close <= 0 or price is None or not shares:
            continue
        sell = decision.get("action") in SELL_ACTIONS
        per_share = (price - close) if sell else (close - price)
        currency = "HKD" if decision.get("leg") == "HK" else "USD"
        events.append({
            "decision_id": decision.get("decision_id"),
            "episode_id": decision.get("episode_id"),
            "ticker": decision.get("ticker"),
            "session": session,
            "direction": "sell" if sell else "buy",
            "shares": shares,
            "ai_execution_price": price,
            "same_day_close": close,
            "improvement_amount": round(shares * per_share, 2),
            "currency": currency,
            "improvement_bps": round(per_share / close * 10000, 2),
            "pair_key": {
                "ticker": decision.get("ticker"),
                "date": session,
                "episode_id": decision.get("episode_id"),
                "direction": "sell" if sell else "buy",
                "shares": shares,
            },
        })

    by_currency = {}
    for currency in ("HKD", "USD"):
        rows = [row for row in events if row["currency"] == currency]
        blocks = {
            (row["ticker"], row["session"], row["episode_id"])
            for row in rows
        }
        by_currency[currency] = {
            "n_events": len(rows),
            "n_blocks": len(blocks),
            "median_bps": (
                round(statistics.median(row["improvement_bps"] for row in rows), 2)
                if rows else None
            ),
            "paired_ci95_bps": _paired_block_ci(rows),
            "distribution_bps": _event_quantiles(
                [row["improvement_bps"] for row in rows]),
            "events": rows,
        }
    return {
        "method": "same_ticker_same_day_same_direction_same_shares_close_benchmark",
        "claim": "触发价 vs 同日收盘执行好多少",
        "ci_method": "paired block bootstrap by ticker/date/episode",
        "cross_ticker_swaps_excluded": True,
        "swap_pairing_requires_transaction_group_id": True,
        "by_currency": by_currency,
    }


def build_audit_sidecar(decisions: list[dict], portfolio: dict,
                        as_of: str | None = None,
                        include_records: bool = True) -> dict:
    """Immutable-authorship audit view keyed by decision_id, with all states.

    ``records`` is the full per-decision audit trail (~700KB). It is a pure
    derivation of ``decisions`` — recomputed on every build — so it is fully
    reversible and does not need to be shipped. The published dashboard sidecar
    passes ``include_records=False``: the dashboard only reads
    ``timing_diagnostic``, so sending the whole trail to every visitor was dead
    weight. Callers that actually want the trail (tests, ad-hoc recompute) keep
    the default and get it back with no recomputation cost.
    """
    matched = match_real_executions(decisions, portfolio)
    records = []
    for decision in sorted(
            decisions, key=lambda d: (d.get("plan_date", ""), d.get("decision_id", "")),
            reverse=True):
        ev = decision.get("evaluation") or {}
        trade = matched.get(decision.get("decision_id"))
        path, coverage = _audit_path(decision)
        actual = {
            "status": (decision.get("execution") or {}).get("status", "unknown"),
            "matched": bool(trade),
            "price": _float((trade or {}).get("price")),
            "shares": _int((trade or {}).get("shares")),
            "session": (trade or {}).get("date"),
            "source": "portfolio.trades" if trade else None,
        }
        records.append({
            "decision_id": decision.get("decision_id"),
            "episode_id": decision.get("episode_id"),
            "plan_date": decision.get("plan_date"),
            "ticker": decision.get("ticker"),
            "leg": decision.get("leg"),
            "action": decision.get("action"),
            "authored": {
                "created_at": decision.get("created_at"),
                "condition": copy.deepcopy(decision.get("condition") or {}),
                "rationale": decision.get("rationale") or "",
                "size": copy.deepcopy(decision.get("size") or {}),
                "confidence": _float(decision.get("confidence")),
                "driven_by": decision.get("driven_by"),
                "regime": decision.get("regime", "unknown"),
                "strategy_id": decision.get("strategy_id"),
            },
            "state": ev.get("status") or "pending",
            "outcome": ev.get("outcome"),
            "execution": {
                "actual": actual,
                "ohlc_assumption": {
                    "price": _float(ev.get("execution_price")),
                    "fill_assumed": bool(ev.get("fill_assumed")),
                    "fill_reason": ev.get("fill_reason"),
                    "fill_model": ev.get("fill_model"),
                },
            },
            "path": path,
            "coverage": {
                **coverage,
                "execution_match": (
                    "unique_exact" if trade else
                    "unmatched_or_ambiguous"
                ),
            },
            "fill_model": (
                "real_portfolio_trade" if trade else
                ev.get("fill_model") or "none"
            ),
            "mark_session": {
                "trigger": ev.get("trigger_session"),
                "t1": ev.get("mark_t1_session"),
                "t5": ev.get("mark_t5_session"),
                "right_censored": ev.get("status") == "pending",
                "horizon": ev.get("mark_horizon"),
            },
        })
    out = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "as_of": as_of or datetime.now(HKT).isoformat(timespec="seconds"),
        "primary_key": "decision_id",
        "episode_role": "grouping_only",
        "price_source": "memory/bars canonical raw OHLC only",
        "state_counts": dict(Counter(row["state"] for row in records)),
        "timing_diagnostic": compute_timing_diagnostic(
            decisions, portfolio, matched=matched),
    }
    if include_records:
        out["records"] = records
    return out


def _episode_settled(rows: list[dict], benefit_key: str) -> list[dict]:
    """The calls in an episode that actually fired and have a settled number."""
    return [d for d in rows
            if (d.get("evaluation") or {}).get("triggered") is True
            and _float((d.get("evaluation") or {}).get(benefit_key)) is not None]


def episode_representatives(decisions: list[dict], horizon: str = "t1") -> list[dict]:
    """One synthetic representative per episode, carrying the episode's MEAN benefit.

    Reaffirmations must not add n — that was v1's disease. But electing a single
    member to speak for the episode discards the others, and the choice of member
    silently decides the answer: on 2026-07-15, first-vs-last member moved the
    active win rate 51.4% -> 48.6%, across the 50% line, and "first" flatters by
    ~3pp under every merge rule tried. 53 of 135 episodes had several settled
    calls; 29 of those disagreed with themselves. Neither "first" nor "last" has
    a statistical claim on being right.

    Averaging has one: it spends every settled call in the episode while still
    contributing exactly one sample, which is the entire point of an episode.
    The rep is a copy — the ledger keeps the real per-decision numbers.
    """
    benefit_key = "benefit_t1_pct" if horizon == "t1" else "benefit_t5_pct"
    groups = defaultdict(list)
    for d in decisions:
        groups[d.get("episode_id")].append(d)
    reps = []
    for _, rows in groups.items():
        rows.sort(key=lambda x: (x.get("created_at", ""), x.get("decision_id", "")))
        settled = _episode_settled(rows, benefit_key)
        if not settled:
            continue
        rep = copy.deepcopy(settled[0])
        ev = rep.setdefault("evaluation", {})
        benefits = [_float(d["evaluation"][benefit_key]) for d in settled]
        caps = [c for c in (_float((d.get("evaluation") or {}).get("capital")) for d in settled) if c]
        mean_benefit = sum(benefits) / len(benefits)
        ev[benefit_key] = round(mean_benefit, 4)
        # Money asks the same question of the same episode, so it rides the same
        # average: the capital an average call in this episode put at risk.
        ev["capital"] = round(sum(caps) / len(caps), 2) if caps else None
        # mean(capital) x mean(benefit) is not mean(capital x benefit) once the
        # size moves mid-episode — worth 159 HKD on one 00100 episode alone. Money
        # gets the average of the real per-call products, not a product of averages.
        priced = [(c, b) for c, b in
                  ((_float((d.get("evaluation") or {}).get("capital")),
                    _float(d["evaluation"][benefit_key])) for d in settled) if c]
        ev["episode_mean_money"] = (round(sum(c * b / 100 for c, b in priced) / len(priced), 4)
                                    if priced else None)
        # Consumers read outcome, not the number — keep them the same fact.
        # Reuse the per-decision contract so an exact-zero episode is `flat`, not a
        # loss: _outcome already fixed that fall-through once; the episode layer must
        # not quietly reintroduce it.
        ev["outcome"] = _outcome(mean_benefit)
        ev["episode_n_settled"] = len(settled)
        # Calibration may predict this episode on its first plan date, but its
        # mean outcome is not knowable until the last member's T+1 mark closes.
        # Persist that availability boundary so a prequential run cannot train
        # on later episode members as though they were known on day one.
        mark_dates = [
            str((d.get("evaluation") or {}).get("mark_t1_session"))
            for d in settled
            if (d.get("evaluation") or {}).get("mark_t1_session")
        ]
        ev["episode_outcome_available_date"] = (
            max(mark_dates)
            if mark_dates
            else max(str(d.get("plan_date") or "") for d in settled)
        )
        ev["episode_last_plan_date"] = max(
            str(d.get("plan_date") or "") for d in settled)
        reps.append(rep)
    reps.sort(key=lambda x: (x.get("plan_date", ""), x.get("decision_id", "")))
    return reps


def _cluster_ci(rows: list[dict], value_fn, samples: int = 1000) -> list[float] | None:
    """Deterministic date-cluster bootstrap CI; repeated same-day calls move together."""
    groups = defaultdict(list)
    for r in rows:
        v = value_fn(r)
        if v is not None:
            groups[r.get("plan_date")].append(float(v))
    dates = sorted(groups)
    if len(dates) < 3:
        return None
    rnd = random.Random(20260714)
    stats = []
    for _ in range(samples):
        vals = []
        for _ in dates:
            vals.extend(groups[rnd.choice(dates)])
        if vals:
            stats.append(sum(vals) / len(vals))
    stats.sort()
    return [round(stats[int(0.025 * (len(stats) - 1))], 4),
            round(stats[int(0.975 * (len(stats) - 1))], 4)]


def _aggregate(rows: list[dict], benefit_key: str) -> dict:
    vals = [(_float((r.get("evaluation") or {}).get(benefit_key)),
             _float((r.get("evaluation") or {}).get("capital"))) for r in rows]
    vals = [(v, c) for v, c in vals if v is not None]
    if not vals:
        return {"n_episodes": 0, "win_rate": None, "avg_benefit_pct": None,
                "capital_weighted_benefit_pct": None, "cluster_ci95": None}
    plain = [v for v, _ in vals]
    weighted = [(v, c) for v, c in vals if c and c > 0]
    cw = sum(v * c for v, c in weighted) / sum(c for _, c in weighted) if weighted else None
    return {
        "n_episodes": len(vals),
        "win_rate": round(sum(v > 0 for v in plain) / len(plain), 4),
        "avg_benefit_pct": round(sum(plain) / len(plain), 4),
        "capital_weighted_benefit_pct": round(cw, 4) if cw is not None else None,
        "capital_coverage_pct": round(100 * len(weighted) / len(vals), 1),
        "cluster_ci95": _cluster_ci(rows, lambda r: _float((r.get("evaluation") or {}).get(benefit_key))),
    }


def _breakdown(rows: list[dict], field_getter, benefit_key: str) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[field_getter(r) or "unknown"].append(r)
    out = {}
    for key, rs in sorted(groups.items()):
        agg = _aggregate(rs, benefit_key)
        ci = agg.get("cluster_ci95")
        agg["edge_significant"] = bool(ci and ci[0] > 0)
        out[key] = agg
    return out


def _compounded_curve(rows: list[dict], benefit_key: str) -> list[dict]:
    """Compound one capital-weighted portfolio-of-decisions return per plan date."""
    by_date = defaultdict(list)
    for r in rows:
        v = _float((r.get("evaluation") or {}).get(benefit_key))
        c = _float((r.get("evaluation") or {}).get("capital"))
        if v is not None:
            by_date[r.get("plan_date")].append((v, c))
    curve = []
    equity = 1.0
    for day in sorted(by_date):
        values = by_date[day]
        weighted = [(v, c) for v, c in values if c and c > 0]
        day_ret = (sum(v * c for v, c in weighted) / sum(c for _, c in weighted)
                   if weighted else sum(v for v, _ in values) / len(values))
        equity *= 1 + day_ret / 100
        curve.append({"date": day, "daily_benefit_pct": round(day_ret, 4),
                      "compounded_benefit_pct": round((equity - 1) * 100, 4)})
    return curve


def _cumulative_win_rate_curve(rows: list[dict], benefit_key: str) -> list[dict]:
    """Cumulative episode hit rate by plan date, for a true win-rate chart."""
    by_date = defaultdict(list)
    for r in rows:
        value = _float((r.get("evaluation") or {}).get(benefit_key))
        if value is not None:
            by_date[r.get("plan_date")].append(value)
    curve = []
    wins = total = 0
    for day in sorted(by_date):
        values = by_date[day]
        wins += sum(v > 0 for v in values)
        total += len(values)
        curve.append({"date": day, "wins": wins, "n_episodes": total,
                      "win_rate": round(wins / total, 4)})
    return curve


def _exec_rate(rows: list[dict], today: date | None = None) -> dict:
    """Follow-through over rows whose execution is actually known.

    ``unknown`` stays out of the denominator, but it is two different things
    wearing one label, and only one of them is temporary:

    * ``pending`` — the verification window has not closed, so the next
      preflight can still resolve it. A genuine gap in the record.
    * ``stranded`` — the window closed days ago and ``_detect_followed`` returns
      ``unknown`` on every retry. It never resolves. `_shares_at_date` answers
      ``None`` when the ticker is in no ``holdings`` list, which is what a plan
      naming a spot ticker held through a 2x ETF looks like (PLTR/MSFT vs
      PLTU/MSFU, #162). Those rows are **not a random sample**: a plan that was
      never acted on is exactly the kind whose ticker never enters the book, so
      dropping them biases the rate upward.

    This docstring used to assert that "every unknown row is from the last three
    days". On 2026-08-04 that was false — 37 of 42 unknown rows were stranded,
    the oldest from 2026-07-13, and on the passive leg *nothing* was pending:
    98.8% was computed on 83 of 97 rows, against a floor of 84.5%. The claim had
    silently expired, which is why the counts are emitted instead of argued.

    Emitting both is the whole fix. The rate is unchanged and no verdict moves;
    what changes is that the censoring is now a number a reader can see.
    """
    today = today or date.today()
    c = Counter((r.get("execution") or {}).get("status", "unknown") for r in rows)
    known = c["followed"] + c["not_followed"]
    pending = 0
    for row in rows:
        if (row.get("execution") or {}).get("status", "unknown") != "unknown":
            continue
        try:
            planned = date.fromisoformat(row.get("plan_date") or "")
        except ValueError:
            # No usable plan_date, so the window cannot be said to be open.
            # Counting it as pending would let an unparseable row hide forever
            # in the bucket that means "wait and it will resolve".
            continue
        condition = row.get("condition") or {}
        window_days = verification_window_days(
            row.get("action"),
            plan_date=row.get("plan_date"),
            leg=row.get("leg"),
            valid_for_sessions=_int(condition.get("valid_for_sessions")),
        )
        if planned + timedelta(days=window_days) > today:
            pending += 1
    return {
        "n": len(rows),
        "followed": c["followed"],
        "not_followed": c["not_followed"],
        "unknown": c["unknown"],
        "pending": pending,
        "stranded": c["unknown"] - pending,
        "known": known,
        "rate": round(c["followed"] / known, 4) if known else None,
    }


def _calibration_dimensions(row: dict) -> dict[str, str]:
    """Immutable decision dimensions used by the confidence calibrator."""
    regime = row.get("regime")
    return {
        "action": str(row.get("action") or "unknown"),
        "driver": str(row.get("driven_by") or "unknown"),
        "condition": str((row.get("condition") or {}).get("type") or "unknown"),
        "regime": str(regime if regime in REGIMES else "unknown"),
    }


def _calibration_keys(row: dict) -> list[tuple[str, tuple[str, ...]]]:
    d = _calibration_dimensions(row)
    return [
        ("global", ()),
        ("action", (d["action"],)),
        ("action_driver", (d["action"], d["driver"])),
        ("action_driver_condition",
         (d["action"], d["driver"], d["condition"])),
        ("action_driver_condition_regime",
         (d["action"], d["driver"], d["condition"], d["regime"])),
    ]


def _beta_interval(alpha: float, beta: float, seed: str,
                   samples: int = 2000) -> list[float]:
    """Deterministic posterior interval without a scipy runtime dependency."""
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    rnd = random.Random(int(digest[:16], 16))
    draws = sorted(rnd.betavariate(alpha, beta) for _ in range(samples))
    return [
        round(draws[int(0.025 * (samples - 1))], 4),
        round(draws[int(0.975 * (samples - 1))], 4),
    ]


def _hierarchical_posterior(
        row: dict,
        counts: dict[tuple[str, tuple[str, ...]], list[int]],
) -> tuple[float, float, str, int, dict[str, int]]:
    """Beta-binomial posterior, shrinking each sparse child to sibling evidence.

    Each observation enters once. At every branch, sibling observations update
    the incoming prior, then the selected child updates that prior. Re-adding the
    same child's wins at action, driver, condition and regime would manufacture
    four observations from one episode.
    """
    keys = _calibration_keys(row)
    global_n, global_wins = counts.get(keys[0], [0, 0])
    alpha = 1.0 + global_wins
    beta = 1.0 + global_n - global_wins
    resolved_level = "global"
    resolved_n = global_n
    support = {"global": global_n}
    incoming_prior_mean = 0.5
    for index, (level, key) in enumerate(keys[1:], 1):
        n, wins = counts.get((level, key), [0, 0])
        support[level] = n
        if not n:
            continue
        parent_n, parent_wins = counts.get(keys[index - 1], [0, 0])
        sibling_n = max(0, parent_n - n)
        sibling_wins = max(0, parent_wins - wins)
        branch_prior_mean = (
            incoming_prior_mean * CALIBRATION_PARENT_STRENGTH + sibling_wins
        ) / (CALIBRATION_PARENT_STRENGTH + sibling_n)
        alpha = branch_prior_mean * CALIBRATION_PARENT_STRENGTH + wins
        beta = (
            (1.0 - branch_prior_mean) * CALIBRATION_PARENT_STRENGTH
            + n - wins
        )
        resolved_level = level
        resolved_n = n
        # The next branch must inherit the prior *before* this child's own data;
        # otherwise the same episode is counted again at the next dimension.
        incoming_prior_mean = branch_prior_mean
    return alpha, beta, resolved_level, resolved_n, support


def _calibration_prediction(
        row: dict,
        counts: dict[tuple[str, tuple[str, ...]], list[int]],
        prior_dates: set[str],
        seed_suffix: str,
) -> dict:
    alpha, beta, level, level_n, support = _hierarchical_posterior(row, counts)
    probability = alpha / (alpha + beta)
    ci = _beta_interval(alpha, beta, seed_suffix)
    global_n = support["global"]
    width = ci[1] - ci[0]
    if global_n < CALIBRATION_MIN_PRIOR_EPISODES:
        abstain_reason = (
            f"prior_episodes<{CALIBRATION_MIN_PRIOR_EPISODES}")
    elif len(prior_dates) < CALIBRATION_MIN_PRIOR_DATES:
        abstain_reason = f"prior_dates<{CALIBRATION_MIN_PRIOR_DATES}"
    elif width > CALIBRATION_MAX_CI_WIDTH:
        abstain_reason = f"ci_width>{CALIBRATION_MAX_CI_WIDTH}"
    else:
        abstain_reason = None
    abstain = abstain_reason is not None
    edge_supported = not abstain and ci[0] > 0.5
    size_multiplier = (
        min(1.0, max(0.0, (ci[0] - 0.5) / 0.2))
        if edge_supported else 0.0
    )
    return {
        "calibrated_probability": round(probability, 4),
        "ci95": ci,
        "posterior_alpha": round(alpha, 4),
        "posterior_beta": round(beta, 4),
        "resolved_level": level,
        "resolved_level_n": level_n,
        "support_by_level": support,
        "prior_episodes": global_n,
        "prior_dates": len(prior_dates),
        "evidence_sufficient": not abstain,
        "abstain": abstain,
        "abstain_reason": abstain_reason,
        "edge_supported": edge_supported,
        "signal_size_multiplier": round(size_multiplier, 3),
        "sizing_status": (
            "abstain_insufficient_evidence" if abstain
            else "edge_supported" if edge_supported
            else "no_positive_edge"
        ),
    }


def hierarchical_prequential_calibration(rows: list[dict]) -> dict:
    """Strictly prequential hierarchical confidence calibration.

    Every episode on a plan date is predicted from earlier dates only. Outcomes
    from the whole date are added after all predictions for that date, preventing
    the first same-day call from leaking into the second. The original authored
    confidence remains an audit comparator; sizing uses the posterior lower bound.
    """
    eligible = [
        r for r in rows
        if (r.get("evaluation") or {}).get("outcome") in ("win", "loss", "flat")
    ]
    by_date: dict[str, list[dict]] = defaultdict(list)
    updates_by_date: dict[str, list[dict]] = defaultdict(list)
    for row in eligible:
        plan_date = str(row.get("plan_date") or "unknown")
        by_date[plan_date].append(row)
        evaluation = row.get("evaluation") or {}
        available_date = str(
            evaluation.get("episode_outcome_available_date")
            or evaluation.get("mark_t1_session")
            or plan_date
        )
        updates_by_date[available_date].append(row)

    counts: dict[tuple[str, tuple[str, ...]], list[int]] = {}
    prior_dates: set[str] = set()
    traces = []
    timeline = sorted(set(by_date) | set(updates_by_date))
    for plan_date in timeline:
        day_rows = sorted(
            by_date[plan_date],
            key=lambda r: (str(r.get("decision_id") or ""),
                           str(r.get("episode_id") or "")),
        )
        for row in day_rows:
            dimensions = _calibration_dimensions(row)
            pred = _calibration_prediction(
                row, counts, prior_dates,
                f"prequential:{plan_date}:"
                f"{'|'.join(dimensions.values())}",
            )
            global_n, global_wins = counts.get(("global", ()), [0, 0])
            outcome = 1 if (row.get("evaluation") or {}).get("outcome") == "win" else 0
            traces.append({
                "plan_date": plan_date,
                "decision_id": row.get("decision_id"),
                "episode_id": row.get("episode_id"),
                **dimensions,
                "raw_confidence": _float(row.get("confidence")),
                "outcome": outcome,
                "outcome_available_date": (
                    (row.get("evaluation") or {}).get(
                        "episode_outcome_available_date")
                    or (row.get("evaluation") or {}).get("mark_t1_session")
                    or plan_date
                ),
                "prequential_constant_probability": round(
                    (1 + global_wins) / (2 + global_n), 4),
                **pred,
            })
        # Update only outcomes observable by this date, and only after the entire
        # date has been predicted. A T+1 close on date D cannot inform a plan
        # authored before that close on D.
        for row in updates_by_date[plan_date]:
            outcome = 1 if (row.get("evaluation") or {}).get("outcome") == "win" else 0
            for key in _calibration_keys(row):
                current = counts.setdefault(key, [0, 0])
                current[0] += 1
                current[1] += outcome
            prior_dates.add(str(row.get("plan_date") or "unknown"))

    def _score(scored: list[dict]) -> dict:
        if not scored:
            return {
                "n": 0, "calibrated_brier": None, "raw_brier": None,
                "prequential_constant_brier": None,
            }
        n = len(scored)
        calibrated = sum(
            (r["calibrated_probability"] - r["outcome"]) ** 2 for r in scored
        ) / n
        raw_rows = [r for r in scored if r["raw_confidence"] is not None]
        raw = (
            sum((r["raw_confidence"] - r["outcome"]) ** 2 for r in raw_rows)
            / len(raw_rows) if raw_rows else None
        )
        baseline = sum(
            (r["prequential_constant_probability"] - r["outcome"]) ** 2
            for r in scored
        ) / n
        return {
            "n": n,
            "calibrated_brier": round(calibrated, 4),
            "raw_brier": round(raw, 4) if raw is not None else None,
            "prequential_constant_brier": round(baseline, 4),
            # Verdicts compare the same precision that is published; reporting
            # 0.2593 vs 0.2593 and then claiming a microscopic "win" is false
            # precision.
            "calibrated_beats_raw": (
                round(calibrated, 4) < round(raw, 4)
                if raw is not None else None
            ),
            "calibrated_beats_constant": (
                round(calibrated, 4) < round(baseline, 4)),
        }

    current_groups = []
    observed_triplets = {
        (
            _calibration_dimensions(row)["action"],
            _calibration_dimensions(row)["driver"],
            _calibration_dimensions(row)["condition"],
        )
        for row in eligible
    }
    # Historical rows predate regime authorship and live in `unknown`. Emit every
    # actionable regime for each observed action/driver/condition triple so a new
    # plan can still match a row and transparently fall back to the condition
    # parent until its own regime leaf accumulates evidence.
    dimensions = {
        (action, driver, condition, regime): {
            "action": action, "driver": driver,
            "condition": condition, "regime": regime,
        }
        for action, driver, condition in observed_triplets
        for regime in ("risk_on", "neutral", "risk_off")
    }
    all_dates = {
        str(row.get("plan_date") or "unknown") for row in eligible
    }
    for values, dims in sorted(dimensions.items()):
        probe = {
            "action": dims["action"],
            "driven_by": dims["driver"],
            "condition": {"type": dims["condition"]},
            "regime": dims["regime"],
        }
        pred = _calibration_prediction(
            probe, counts, all_dates, f"current:{'|'.join(values)}")
        current_groups.append({**dims, **pred})

    scored_after_warmup = [r for r in traces if r["evidence_sufficient"]]
    return {
        "method": (
            "strictly prequential by plan_date and outcome availability; "
            "same-date outcomes update after predictions; beta-binomial hierarchy "
            "global→action→driver→condition→regime; sparse children shrink "
            f"to {CALIBRATION_PARENT_STRENGTH:g} parent pseudo-observations"
        ),
        "hierarchy": [
            "global", "action", "action_driver",
            "action_driver_condition", "action_driver_condition_regime",
        ],
        "abstain_rule": {
            "min_prior_episodes": CALIBRATION_MIN_PRIOR_EPISODES,
            "min_prior_dates": CALIBRATION_MIN_PRIOR_DATES,
            "max_ci95_width": CALIBRATION_MAX_CI_WIDTH,
        },
        "sizing_rule": (
            "signal_size_multiplier=max(0,(ci95.lower-0.5)/0.2), capped at 1; "
            "zero when evidence is insufficient or positive edge is unsupported"
        ),
        "all_predictions": _score(traces),
        "after_warmup": _score(scored_after_warmup),
        "abstained_predictions": sum(r["abstain"] for r in traces),
        "edge_supported_predictions": sum(r["edge_supported"] for r in traces),
        "current_group_calibrators": current_groups,
        "prequential_predictions": traces,
    }


def compute_metrics(decisions: list[dict], window_days: int = 30) -> dict:
    """The scorecard the UI labels "30d" — so every field here must BE 30d.

    ``execution`` and the override count used to be tallied over the whole
    ledger while the win rates beside them were windowed, which rendered an
    all-time follow-through rate under a card headed "Plan Review (last 30d)".
    Episodes are still built from the full ledger and filtered afterwards: an
    episode that straddles the cutoff keeps its real mean, and the window only
    decides membership. The lifetime record lives in the money and win-rate
    curves, which are deliberately unwindowed.
    """
    cutoff = (datetime.now(HKT).date() - timedelta(days=window_days)).isoformat()
    in_window = [d for d in decisions if (d.get("plan_date") or "") >= cutoff]
    lifetime_reps = episode_representatives(decisions, "t1")
    reps = [r for r in lifetime_reps if r.get("plan_date", "") >= cutoff]
    def _calib(rows: list[dict]) -> dict:
        """Brier + the baselines that make it readable, over one population.

        Kept separate for active vs passive: a HOLD's confidence is a claim about
        carrying a position, an active call's is a claim about a trade firing. Mixing
        them into one score answers neither question.
        """
        cr = [r for r in rows if _float(r.get("confidence")) is not None
              and (r.get("evaluation") or {}).get("outcome") in ("win", "loss", "flat")]
        if not cr:
            # Same key set as the populated branch below — the caller reads every
            # baseline unconditionally, so a branch that drops one aborts the whole
            # dashboard build rather than degrading a card (#309). An empty
            # population is not an error: a fresh workspace, or a window in which
            # nothing settled, has no Brier score to report and says so with None.
            return {"n": 0, "brier": None, "baseline_loo": None,
                    "baseline_constant": None, "baseline_coinflip": None,
                    "base_rate": None, "mean_confidence": None,
                    "beats_baseline": None, "high_confidence": None}
        ys = [1 if (r.get("evaluation") or {}).get("outcome") == "win" else 0 for r in cr]
        ps = [float(r["confidence"]) for r in cr]
        n = len(ys)
        br = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
        base = sum(ys) / n
        loo = (sum(((sum(ys) - y) / (n - 1) - y) ** 2 for y in ys) / n) if n > 1 else None
        hi = [(p, y) for p, y in zip(ps, ys) if p >= 0.60]
        return {
            "n": n,
            "brier": round(br, 4),
            "baseline_loo": round(loo, 4) if loo is not None else None,
            "baseline_constant": round(base * (1 - base), 4),
            "baseline_coinflip": round(sum((0.5 - y) ** 2 for y in ys) / n, 4),
            "base_rate": round(base, 4),
            "mean_confidence": round(sum(ps) / n, 4),
            "beats_baseline": (br < loo) if loo is not None else None,
            "high_confidence": ({"threshold": 0.60, "n": len(hi), "wins": sum(y for _, y in hi),
                                 "win_rate": round(sum(y for _, y in hi) / len(hi), 4)} if hi else None),
        }

    active_reps = [r for r in reps if r.get("action") in ACTIVE_ACTIONS]
    passive_reps = [r for r in reps if r.get("action") in PASSIVE_ACTIONS]
    cal_active = _calib(active_reps)
    cal_passive = _calib(passive_reps)
    cal_all = _calib(reps)
    hierarchical_calibration = hierarchical_prequential_calibration(
        [r for r in lifetime_reps if r.get("action") in ACTIVE_ACTIONS])
    # The brief needs current lookup rows and score summaries, not a 47-row audit
    # trace that consumes tens of thousands of prompt tokens every morning. The
    # public calibrator function still returns the complete trace for tests and
    # ad-hoc audits.
    hierarchical_calibration["prequential_prediction_count"] = len(
        hierarchical_calibration.get("prequential_predictions") or [])
    hierarchical_calibration.pop("prequential_predictions", None)
    execution = Counter((r.get("execution") or {}).get("status", "unknown") for r in in_window)
    overrides = [r for r in in_window if (r.get("override") or {}).get("status") == "active"]
    active, passive = active_reps, passive_reps

    def _coverage(rows: list[dict]) -> dict:
        """How much of the record the headline rate can actually see.

        The rate's denominator is episodes, so coverage is counted in episodes too.
        Publishing it next to the rate is the point: 30 of these are unresolvable
        because the market was shut or the condition needs human evidence, and
        silently dropping them is how a scorecard gets prettier for free.
        """
        by_ep = defaultdict(list)
        for d in rows:
            if d.get("episode_id"):
                by_ep[d["episode_id"]].append(d)
        graded = partial = unresolved = 0
        for members in by_ep.values():
            ok = [r for r in members if _float((r.get("evaluation") or {}).get("benefit_t1_pct")) is not None]
            bad = [r for r in members if (r.get("evaluation") or {}).get("status") == "not_evaluable"]
            if not ok:
                unresolved += 1
            elif bad:
                partial += 1
            else:
                graded += 1
        total = len(by_ep)
        return {"episodes_total": total, "episodes_graded": graded,
                "episodes_partial": partial, "episodes_unresolved": unresolved,
                "graded_pct": round(100 * (graded + partial) / total, 1) if total else None,
                "unresolved_reasons": dict(Counter(
                    reason
                    for members in by_ep.values()
                    for reason in {
                        (d.get("evaluation") or {}).get("not_evaluable_reason")
                        for d in members
                        if (d.get("evaluation") or {}).get("status") == "not_evaluable"
                    }))}

    coverage_active = _coverage([d for d in in_window if d.get("action") in ACTIVE_ACTIONS])

    def _prospective_overlay_metrics(rows: list[dict]) -> dict:
        """Forward attribution from immutable, decision-time signal snapshots.

        This is intentionally per decision rather than episode elected/averaged:
        every tactical tranche has its own packet, multiplier and forward path.
        Date-cluster intervals keep a busy news day from pretending to be many
        independent samples. Empty cohorts are evidence of warm-up, not success.
        """
        eligible = [
            row for row in rows
            if row.get("strategy_id") == "tactical_entry"
            and row.get("action") in ADD_ACTIONS
            and isinstance(row.get("signal_provenance"), dict)
            and (row.get("signal_provenance") or {}).get("schema_version") == 1
        ]

        def cohort(row):
            sizing = ((row.get("signal_provenance") or {}).get("sizing") or {})
            contributors = sizing.get("contributors") or []
            if contributors:
                return "setup_plus_information"
            if sizing.get("sizing_active"):
                return "overlay_active_neutral"
            return "setup_only"

        def bucket(group: list[dict], key: str) -> dict:
            values = [
                _float((row.get("evaluation") or {}).get(key))
                for row in group
            ]
            values = [value for value in values if value is not None]
            return {
                "n_decisions": len(group),
                "n_settled": len(values),
                "n_dates": len({
                    row.get("plan_date") for row in group
                    if _float((row.get("evaluation") or {}).get(key)) is not None
                }),
                "win_rate": (
                    round(sum(value > 0 for value in values) / len(values), 4)
                    if values else None
                ),
                "avg_benefit_pct": (
                    round(statistics.fmean(values), 4) if values else None
                ),
                "cluster_ci95": _cluster_ci(
                    group,
                    lambda row: _float((row.get("evaluation") or {}).get(key)),
                ),
            }

        by_cohort = defaultdict(list)
        by_contributor = defaultdict(list)
        for row in eligible:
            by_cohort[cohort(row)].append(row)
            sizing = ((row.get("signal_provenance") or {}).get("sizing") or {})
            for contributor in sizing.get("contributors") or []:
                by_contributor[str(contributor)].append(row)
        horizons = {}
        for horizon, key in (
            ("t1", "benefit_t1_pct"),
            ("t5", "benefit_t5_pct"),
            ("t20", "benefit_t20_pct"),
        ):
            horizons[horizon] = {
                "cohorts": {
                    name: bucket(by_cohort.get(name, []), key)
                    for name in (
                        "setup_only", "overlay_active_neutral",
                        "setup_plus_information",
                    )
                },
                "contributors": {
                    name: bucket(group, key)
                    for name, group in sorted(by_contributor.items())
                },
            }
        return {
            "status": "collecting" if eligible else "warming_up",
            "n_eligible_decisions": len(eligible),
            "method": (
                "prospective tactical-entry decisions only; immutable packet-time "
                "snapshots; date-cluster CI; no retrospective reconstruction"
            ),
            "horizons": horizons,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "method": "episode-level; triggered-only; date-cluster bootstrap; capital-weighted where size exists",
        "window_days": window_days,
        "raw_decisions": len(in_window),
        "episodes": len({d.get("episode_id") for d in in_window}),
        "settled_episodes": len(reps),
        # Headline calibration = ACTIVE only. A HOLD's confidence is a different
        # claim and used to be averaged in, which is how 191 passive stances ended up
        # grading the model's ability to call a trade.
        "brier": cal_active["brier"],
        "brier_baseline_loo": cal_active["baseline_loo"],
        "brier_baseline_constant": cal_active["baseline_constant"],
        "brier_baseline_coinflip": cal_active["baseline_coinflip"],
        "base_rate": cal_active["base_rate"],
        "mean_confidence": cal_active["mean_confidence"],
        "brier_beats_baseline": cal_active["beats_baseline"],
        "high_confidence": cal_active["high_confidence"],
        "calibration": {"active": cal_active, "passive": cal_passive, "all": cal_all},
        "hierarchical_calibration": hierarchical_calibration,
        "coverage_active": coverage_active,
        # The headline "followed rate" averaged two populations that mean opposite
        # things: acting on a cut/trim/add is a decision, while "following" a hold
        # is just not moving — it scores itself. Averaged they produced a ~50% that
        # described nobody. Split, so the only real number (did kcn act when told
        # to act) can be shown on its own.
        "execution_by_kind": {
            "active": _exec_rate([d for d in in_window if d.get("action") in ACTIVE_ACTIONS]),
            "passive": _exec_rate([d for d in in_window if d.get("action") in PASSIVE_ACTIONS]),
        },
        "active": _aggregate(active, "benefit_t1_pct"),
        "passive": _aggregate(passive, "benefit_t1_pct"),
        "by_action": _breakdown(reps, lambda r: r.get("action"), "benefit_t1_pct"),
        "by_strategy": _breakdown(reps, lambda r: r.get("strategy_id"), "benefit_t1_pct"),
        "by_driver": _breakdown(reps, lambda r: r.get("driven_by"), "benefit_t1_pct"),
        "by_condition": _breakdown(reps, lambda r: (r.get("condition") or {}).get("type"), "benefit_t1_pct"),
        "by_technical_setup": _breakdown(
            reps, lambda r: r.get("technical_setup_id"), "benefit_t1_pct"
        ),
        "information_overlay": _prospective_overlay_metrics(in_window),
        "execution": dict(execution),
        "active_overrides": len(overrides),
    }


def compute_money_impact(decisions: list[dict], horizon: str = "t1") -> dict:
    """NOT PUBLISHED — kept only for the rebuild. Do not put this on a dashboard.

    This used to be the headline, described as "what following the AI was worth".
    It is not, and the claim did not survive review:

    - it sums every active call, but 110 of 113 were never executed — the trades
      it prices did not happen;
    - ``execution_price`` is the *trigger* price, assumed filled the moment a
      snapshot's day range crosses it — and those ranges carry across sessions,
      which has both invented fills and missed real ones;
    - the later mark is "the next snapshot's quote", whose vintage drifts between
      the prior close, that day's close, and an intraday print;
    - per-episode means are added across episodes, which is not the cumulative
      cash of any real sequence of trades.

    The algebra (capital x benefit == shares x (entry - later)) is sound; the
    economic meaning is not. Answering "what did listening earn" needs immutable
    per-session bars, real fills, and a parallel sell-at-close book to difference
    against. Until then this stays out of ``dashboard.json`` — publishing the
    number while retiring the chart would just move it one fetch away.
    """
    reps = episode_representatives(decisions, horizon)
    key = "benefit_t1_pct" if horizon == "t1" else "benefit_t5_pct"
    active = [r for r in reps if r.get("action") in ACTIVE_ACTIONS]

    def _priced(rows):
        return [r for r in rows
                if _float((r.get("evaluation") or {}).get("capital"))
                and _float((r.get("evaluation") or {}).get(key)) is not None]

    def _money(r):
        # Averaged per-call products when the rep carries them (see
        # episode_representatives); the plain product is the single-call case.
        pre = _float((r.get("evaluation") or {}).get("episode_mean_money"))
        if pre is not None:
            return pre
        return _float(r["evaluation"]["capital"]) * _float(r["evaluation"][key]) / 100

    def bucket(rows):
        priced = _priced(rows)
        return {
            "money": round(sum(_money(r) for r in priced), 2),
            "n_episodes": len(rows),
            "n_priced": len(priced),
            "capital_at_risk": round(sum(_float(r["evaluation"]["capital"]) for r in priced), 2),
        }

    def curve(rows):
        """Cumulative money, added — never compounded.

        Each call is an independent one-shot bet that is entered and settled, not
        a reinvested balance, so compounding them (as the benefit curve does)
        invents growth that no capital ever experienced. Addition is the honest
        operator here, and it keeps the y-axis in currency.
        """
        by_date = defaultdict(float)
        for r in _priced(rows):
            by_date[r.get("plan_date")] += _money(r)
        out, total = [], 0.0
        for day in sorted(by_date):
            total += by_date[day]
            out.append({"date": day, "daily_money": round(by_date[day], 2),
                        "cumulative_money": round(total, 2)})
        return out

    legs = {}
    for leg, currency in (("US", "USD"), ("HK", "HKD")):
        rows = [r for r in active if (r.get("leg") or "") == leg]
        if not rows:
            continue
        followed = [r for r in rows if (r.get("execution") or {}).get("status") == "followed"]
        not_followed = [r for r in rows if (r.get("execution") or {}).get("status") == "not_followed"]
        agg = bucket(rows)
        legs[leg] = {
            "currency": currency,
            "all_active": agg,
            # Already reflected in the real P&L curve — kcn acted on these.
            "followed": bucket(followed),
            # The live counterfactual: what ignoring the AI cost or saved.
            "not_followed": bucket(not_followed),
            "coverage_pct": round(100 * agg["n_priced"] / len(rows), 1) if rows else None,
            "curve": curve(rows),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "horizon": horizon,
        "method": ("capital x benefit per triggered active episode, summed in native currency; "
                   "positive = following the AI beat not acting"),
        "legs": legs,
    }


def compute_backtest(decisions: list[dict]) -> dict:
    horizons = {}
    for horizon, key in (("t1", "benefit_t1_pct"), ("t5", "benefit_t5_pct")):
        reps = episode_representatives(decisions, horizon)
        active = [r for r in reps if r.get("action") in ACTIVE_ACTIONS]
        followed = [r for r in reps if (r.get("execution") or {}).get("status") == "followed"]
        horizons[horizon] = {
            # Keep the complete AI track record, including HOLD/WATCH episodes.
            # This is the v2 continuation of the migrated v1 "all calls" line;
            # `active` remains separate so passive market beta cannot masquerade
            # as evidence that cut/trim/add timing has alpha.
            "all": _aggregate(reps, key),
            "active": _aggregate(active, key),
            "followed": _aggregate(followed, key),
            "by_strategy": _breakdown(reps, lambda r: r.get("strategy_id"), key),
            "all_curve": _compounded_curve(reps, key),
            "active_curve": _compounded_curve(active, key),
            "followed_curve": _compounded_curve(followed, key),
            "all_win_rate_curve": _cumulative_win_rate_curve(reps, key),
            "active_win_rate_curve": _cumulative_win_rate_curve(active, key),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "method": ("one synthetic representative per strategy episode carrying that episode's mean benefit; "
                   "an episode is consecutive reaffirmations of the same (ticker, strategy, action) within a "
                   "4-calendar-day gap — a moved trigger or changed condition does NOT start a new episode; "
                   "daily capital-weighted benefit is compounded, never arithmetically summed across calls"),
        "horizons": horizons,
    }


def recent_decisions(decisions: list[dict], limit: int = 20) -> list[dict]:
    out = []
    for d in sorted(decisions, key=lambda x: (x.get("created_at", ""), x.get("decision_id", "")), reverse=True)[:limit]:
        ev = d.get("evaluation") or {}
        out.append({
            "date": d.get("plan_date"), "decision_id": d.get("decision_id"),
            "episode_id": d.get("episode_id"), "ticker": d.get("ticker"),
            "strategy_id": d.get("strategy_id"), "action": d.get("action"),
            "condition": d.get("condition"), "confidence": d.get("confidence"),
            "driven_by": d.get("driven_by"),
            "regime": d.get("regime", "unknown"), "status": ev.get("status"),
            "outcome": ev.get("outcome"), "benefit_t1_pct": ev.get("benefit_t1_pct"),
            "execution": (d.get("execution") or {}).get("status", "unknown"),
            "override": d.get("override"),
        })
    return out


def decision_delta(decisions: list[dict]) -> dict:
    dates = sorted({d.get("plan_date") for d in decisions if d.get("plan_date")})
    if not dates:
        return {"as_of": None, "new": [], "changed": [], "triggered": [], "active_overrides": []}
    latest = dates[-1]
    previous = dates[-2] if len(dates) > 1 else None
    cur = [d for d in decisions if d.get("plan_date") == latest]
    prev = [d for d in decisions if d.get("plan_date") == previous]
    prev_by_key = {(d.get("ticker"), d.get("strategy_id")): d for d in prev}
    new, changed = [], []
    for d in cur:
        compact = {"ticker": d.get("ticker"), "strategy_id": d.get("strategy_id"),
                   "action": d.get("action"), "condition": d.get("condition"),
                   "decision_id": d.get("decision_id")}
        old = prev_by_key.get((d.get("ticker"), d.get("strategy_id")))
        if not old:
            new.append(compact)
        elif old.get("action") != d.get("action") or old.get("condition") != d.get("condition"):
            compact["from_action"] = old.get("action")
            changed.append(compact)
    triggered = [{"ticker": d.get("ticker"), "strategy_id": d.get("strategy_id"), "action": d.get("action")}
                 for d in cur if (d.get("evaluation") or {}).get("triggered") is True]
    overrides = [{"ticker": d.get("ticker"), "strategy_id": d.get("strategy_id"),
                  "reason": (d.get("override") or {}).get("reason"),
                  "expires_on": (d.get("override") or {}).get("expires_on")}
                 for d in decisions if (d.get("override") or {}).get("status") == "active"]
    return {"as_of": latest, "previous": previous, "new": new, "changed": changed,
            "triggered": triggered, "active_overrides": overrides,
            "has_material_change": bool(new or changed or triggered or overrides)}

"""What the recurring paths need to know about the research lifecycle.

The entry gate, earnings ledger and thesis registry each own an artifact
directory. This module is the single place that reads all three, so the daily
brief preflight, `system_check.py` and the `validate` workflow ask exactly the
same questions:

* is every artifact on disk still valid (schema, and for a gate, does its stated
  verdict still match the computed one)?
* is an earnings review due — a reported earnings date with no artifact after it?
* has a management promise gone past its due date without a result?
* is a position held that no entry gate ever cleared?

Invalid artifacts are an integrity failure and fail closed. Due reviews, overdue
promises and ungated positions are work items, not corruption: they surface in the
brief context and as a warning, and never block a publish.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from clawock import earnings_review, entry_gate, thesis_registry
from clawock.portfolio import instruments as instrument_registry
from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
THESIS_DIR = WS / "memory" / "theses"
EARNINGS_DIR = WS / "memory" / "earnings"
ENTRY_GATE_DIR = WS / "memory" / "entry-gates"
PORTFOLIO = WS / "portfolio.json"
CATALYSTS = WS / "assets" / "data" / "catalysts.json"

POLICY_FILE = WS / "config" / "research-governance.json"


def load_policy(path: Path = POLICY_FILE) -> dict:
    """Load deployment cadence without baking one desk's cutover date into code."""
    defaults = {
        "gate_required_from": "0001-01-01",
        "default_review_window_days": 14,
        "max_review_window_days": 45,
        "stale_ledger_factor": 1.6,
        "hk_results_notice_window_days": 45,
    }
    if not path.exists():
        return defaults
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError(f"{path} must declare schema_version 1")
    merged = {**defaults, **{key: payload[key] for key in defaults if key in payload}}
    date.fromisoformat(str(merged["gate_required_from"]))
    for key in (
        "default_review_window_days", "max_review_window_days",
        "hk_results_notice_window_days",
    ):
        if not isinstance(merged[key], int) or merged[key] < 1:
            raise ValueError(f"{path}: {key} must be a positive integer")
    if not isinstance(merged["stale_ledger_factor"], (int, float)) \
            or merged["stale_ledger_factor"] <= 0:
        raise ValueError(f"{path}: stale_ledger_factor must be positive")
    return merged


POLICY = load_policy()
GATE_REQUIRED_FROM = date.fromisoformat(POLICY["gate_required_from"])
# Cadence, decided deliberately (see docs/operations/research-cadence.md):
#
# * `reviews_due` is detected from `assets/data/catalysts.json`, which the brief
#   preflight refreshes every morning over a rotating window. Detection therefore
#   cannot outlive that window, so the review window is clamped to it instead of
#   pretending to a longer guarantee. A fresh miss shows up the next morning.
# * `stale_ledgers` is the durable half of the same question and needs no feed at
#   all: it compares the newest artifact's period end against the issuer's own
#   reporting cadence, so a ledger left behind for a whole period keeps surfacing
#   long after the catalyst rotated out.
DEFAULT_REVIEW_WINDOW_DAYS = POLICY["default_review_window_days"]
MAX_REVIEW_WINDOW_DAYS = POLICY["max_review_window_days"]
CADENCE_DAYS = {"quarterly": 92, "semiannual": 183, "annual": 366}
# 1.6 periods: one full period late is a miss, but a late filing inside the normal
# reporting lag must not be called stale.
STALE_LEDGER_FACTOR = float(POLICY["stale_ledger_factor"])

# `fetch_catalysts` currently sources the earnings calendar for US-listed
# issuers. Calendar dates and BMO/AMC labels therefore belong to New York time,
# even though the recurring jobs and `today` run in HKT.
US_EARNINGS_TZ = ZoneInfo("America/New_York")
US_MARKET_OPEN = time(9, 30)
# An AMC label promises only "after close", not a precise release minute.
# Waiting 15 minutes avoids creating work at the closing bell itself.
US_AFTER_CLOSE_MATURE = time(16, 15)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text()), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name}: {exc}"


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def load_earnings_artifacts(root: Path = EARNINGS_DIR, *, now=None):
    """Every earnings artifact, newest period last per ticker, plus errors."""
    by_ticker: dict[str, list[dict]] = {}
    errors: list[str] = []
    if not root.exists():
        return by_ticker, errors
    for path in sorted(root.glob("*/*.json")):
        doc, error = _load_json(path)
        if error:
            errors.append(f"earnings/{path.parent.name}: {error}")
            continue
        found = earnings_review.validate_artifact(doc, now=now)
        if found:
            errors.extend(f"earnings/{path.parent.name}/{path.name}: {e}" for e in found)
            continue
        if doc["ticker"] != path.parent.name:
            errors.append(
                f"earnings/{path.parent.name}/{path.name}: ticker {doc['ticker']!r} "
                "does not match its directory"
            )
            continue
        by_ticker.setdefault(doc["ticker"], []).append(doc)
    for docs in by_ticker.values():
        docs.sort(key=lambda doc: doc["period"]["end_date"])
    return by_ticker, errors


def load_entry_gates(root: Path = ENTRY_GATE_DIR, *, now=None):
    """Every entry-gate artifact, newest assessment last per ticker, plus errors."""
    by_ticker: dict[str, list[dict]] = {}
    errors: list[str] = []
    if not root.exists():
        return by_ticker, errors
    for path in sorted(root.glob("*.json")):
        doc, error = _load_json(path)
        if error:
            errors.append(f"entry-gates: {error}")
            continue
        found = entry_gate.validate_artifact(doc, now=now)
        if found:
            errors.extend(f"entry-gates/{path.name}: {e}" for e in found)
            continue
        by_ticker.setdefault(doc["ticker"], []).append(doc)
    for docs in by_ticker.values():
        docs.sort(key=lambda doc: doc["assessed_at"])
    return by_ticker, errors


def active_positions(portfolio: dict) -> list[dict]:
    """Held tickers with the date they were first bought, from the trade ledger."""
    out = []
    for region in ("us_stocks", "hk_stocks"):
        leg = (portfolio.get("portfolios") or {}).get(region) or {}
        for holding in leg.get("holdings") or []:
            if (holding.get("shares") or 0) <= 0:
                continue
            buys = [
                _parse_date(trade.get("date"))
                for trade in holding.get("trades") or []
                if trade.get("action") == "buy"
            ]
            buys = [day for day in buys if day]
            out.append({
                "ticker": holding.get("ticker"),
                "region": region,
                "first_buy": min(buys).isoformat() if buys else None,
            })
    return out


def review_window_days(catalysts) -> int:
    """Detection can only reach as far back as the catalyst feed's own window."""
    window = (catalysts or {}).get("lookback_window_days")
    if not isinstance(window, int) or window <= 0:
        return DEFAULT_REVIEW_WINDOW_DAYS
    return min(window, MAX_REVIEW_WINDOW_DAYS)


def earnings_issuers(positions) -> dict:
    """Held ticker → the issuer whose earnings moves it.

    A catalyst can arrive under an issuer's name while the held position is a fund
    that tracks it. Matching on the held ticker alone silently misses every
    earnings review for the leveraged sleeve.
    """
    out = {}
    for position in positions:
        ticker = position["ticker"]
        issuer = instrument_registry.issuer_for(ticker) or ticker
        if issuer:
            out[ticker] = issuer
    return out


def earnings_event_mature(event: dict, *, now: datetime) -> bool:
    """Whether a scheduled US earnings event can truthfully be called reported."""
    reported = _parse_date(event.get("date"))
    if reported is None:
        return False
    # A populated actual is stronger evidence than a coarse calendar label.
    if event.get("eps_actual") is not None:
        return True
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    local_now = now.astimezone(US_EARNINGS_TZ)
    session = str(event.get("time") or "unknown").strip().lower()
    if session == "bmo":
        mature_at = datetime.combine(reported, US_MARKET_OPEN, US_EARNINGS_TZ)
    elif session in {"amc", "dmh"}:
        mature_at = datetime.combine(reported, US_AFTER_CLOSE_MATURE, US_EARNINGS_TZ)
    else:
        mature_at = datetime.combine(
            reported + timedelta(days=1), time.min, US_EARNINGS_TZ
        )
    return local_now >= mature_at


def earnings_reviews_due(
    positions, catalysts, artifacts, today: date, *, now: datetime | None = None
) -> list[dict]:
    """A matured earnings event with no artifact published after it."""
    now = now or datetime.now(timezone.utc)
    issuers = earnings_issuers(positions)
    held = set(issuers.values()) | {position["ticker"] for position in positions}
    via = {issuer: ticker for ticker, issuer in issuers.items() if issuer != ticker}
    window = review_window_days(catalysts)
    due = []
    for event in (catalysts or {}).get("earnings") or []:
        ticker = event.get("ticker")
        reported = _parse_date(event.get("date"))
        if ticker not in held or reported is None:
            continue
        if not 0 <= (today - reported).days <= window:
            continue
        if not earnings_event_mature(event, now=now):
            continue
        published = [
            _parse_date(doc.get("published_at")) for doc in artifacts.get(ticker) or []
        ]
        if any(day and day >= reported for day in published):
            continue
        row = {
            "ticker": ticker,
            "reported_on": reported.isoformat(),
            "days_since": (today - reported).days,
            "reason": "earnings reported with no primary-source artifact covering it",
        }
        if ticker in via:
            row["held_via"] = via[ticker]      # we hold the fund, it reports
        due.append(row)
    return sorted(due, key=lambda row: (row["ticker"], row["reported_on"]))


# Some HK issuers announce a board meeting before publishing results. The notice
# carries no reliable release date, so this says "results are near", never a date.
HK_BOARD_MEETING_PATTERN = "董事会会议"
HK_RESULTS_NOTICE_WINDOW_DAYS = POLICY["hk_results_notice_window_days"]


def hk_results_expected(positions, today: date, *, artifacts=None, fetch=None) -> list[dict]:
    """HK holdings whose board-meeting notice is not yet answered by an artifact."""
    artifacts = artifacts or {}
    hk = [p for p in positions if p.get("region") == "hk_stocks"]
    if not hk:
        return []
    if fetch is None:
        return []
    out = []
    for position in hk:
        ticker = position["ticker"]
        try:
            rows = fetch(ticker) or []
        except Exception as exc:  # noqa: BLE001 — a feed hiccup is not a finding
            out.append({"ticker": ticker, "status": "unknown",
                        "reason": f"notice feed unavailable: {type(exc).__name__}"})
            continue
        notices = []
        for row in rows:
            if HK_BOARD_MEETING_PATTERN not in str(row.get("title") or ""):
                continue
            announced = _parse_date(str(row.get("time") or "")[:10])
            if announced and 0 <= (today - announced).days <= HK_RESULTS_NOTICE_WINDOW_DAYS:
                notices.append(announced)
        if not notices:
            continue
        announced = max(notices)
        published = [
            _parse_date(doc.get("published_at")) for doc in artifacts.get(ticker) or []
        ]
        if any(day and day >= announced for day in published):
            continue
        out.append({
            "ticker": ticker,
            "status": "expected",
            "notice_date": announced.isoformat(),
            "days_since_notice": (today - announced).days,
            "reason": "board-meeting notice published; results follow, date is in the "
                      "announcement document and not in any free feed",
        })
    return sorted(out, key=lambda row: row["ticker"])


def stale_ledgers(positions, artifacts, today: date) -> list[dict]:
    """Artifacts left behind by more than the issuer's own reporting cadence."""
    held = {position["ticker"] for position in positions}
    out = []
    for ticker, docs in artifacts.items():
        if ticker not in held or not docs:
            continue
        latest = docs[-1]
        period_end = _parse_date(latest["period"]["end_date"])
        cadence_days = CADENCE_DAYS.get(latest.get("cadence"))
        if period_end is None or cadence_days is None:
            continue
        behind = (today - period_end).days
        if behind <= cadence_days * STALE_LEDGER_FACTOR:
            continue
        out.append({
            "ticker": ticker,
            "latest_period": latest["period"]["label"],
            "days_behind": behind,
            "cadence": latest["cadence"],
            "reason": "no artifact for a full reporting period past the last one",
        })
    return sorted(out, key=lambda row: (-row["days_behind"], row["ticker"]))


def overdue_commitments(artifacts, today: date) -> list[dict]:
    """Promises whose due date has passed with no reported result."""
    out = []
    for ticker, docs in artifacts.items():
        if not docs:
            continue
        latest = docs[-1]
        for commitment in latest.get("management_commitments") or []:
            due = _parse_date(commitment.get("due_date"))
            if due is None or due > today:
                continue
            if commitment.get("status") in earnings_review.TERMINAL_COMMITMENT_STATUSES:
                continue
            out.append({
                "ticker": ticker,
                "commitment_id": commitment.get("commitment_id"),
                "due_date": due.isoformat(),
                "days_overdue": (today - due).days,
                "status": commitment.get("status"),
                "target_metric": commitment.get("target_metric"),
                "from_artifact": latest.get("artifact_id"),
            })
    return sorted(out, key=lambda row: (-row["days_overdue"], row["ticker"]))


def ungated_positions(positions, gates) -> list[dict]:
    """Positions opened after the gate shipped with no gate, or held after a reject."""
    out = []
    for position in positions:
        ticker = position["ticker"]
        docs = gates.get(ticker) or []
        first_buy = _parse_date(position.get("first_buy"))
        if docs:
            verdict = docs[-1]["verdict"]
            if verdict == "reject":
                out.append({
                    "ticker": ticker,
                    "issue": "held after a reject verdict",
                    "gate_id": docs[-1]["gate_id"],
                })
            continue
        if first_buy is None or first_buy < GATE_REQUIRED_FROM:
            continue
        out.append({
            "ticker": ticker,
            "issue": "opened after the gate shipped with no entry-gate artifact",
            "first_buy": first_buy.isoformat(),
        })
    return sorted(out, key=lambda row: row["ticker"])


def movers_thesis_context(tickers, *, now=None, thesis_dir=THESIS_DIR,
                          entry_gate_dir=ENTRY_GATE_DIR) -> dict:
    """Thesis and gate state for the names a slot already flagged.

    Built for the intraday and report preflights: local JSON only, scoped to the
    tickers passed in, and silent when nothing moved. What comes back is
    attribution context — a red line explains *why* a move matters and what the
    thesis said to do about it. It is not a catalyst: the catalyst gate still
    decides whether a discretionary action is allowed at all.

    A missing or unreadable baseline reads `unknown`. Nothing here may raise, or a
    research artifact could take down a market-reporting cron.
    """
    wanted = [str(ticker) for ticker in tickers or [] if ticker]
    if not wanted:
        return {}
    try:
        theses, thesis_errors = thesis_registry.load_registry(thesis_dir)
        gates, gate_errors = load_entry_gates(entry_gate_dir, now=now)
    except Exception as exc:  # noqa: BLE001 — last-resort guard, not the main path
        # Malformed artifacts are already absorbed by the loaders above (they
        # collect errors instead of raising), so this catches only the
        # unexpected — a permissions error, a corrupt directory. A research
        # artifact must never be able to take down a market-reporting cron.
        return {ticker: {"status": "unknown", "reason": f"registry unreadable: {exc}"}
                for ticker in wanted}
    by_ticker = {doc["ticker"]: doc for doc in theses}
    invalid = bool(thesis_errors or gate_errors)
    out = {}
    for ticker in wanted:
        doc = by_ticker.get(ticker)
        gate_docs = gates.get(ticker) or []
        entry = {}
        if doc is None:
            entry = {
                "status": "unknown",
                "reason": "no canonical thesis baseline"
                          + (" (some artifacts are invalid)" if invalid else ""),
            }
        else:
            red_lines = [
                {
                    "id": line.get("id"),
                    "status": line.get("status"),
                    "severity": line.get("severity"),
                    "required_action": line.get("required_action"),
                }
                for line in doc.get("red_lines") or []
                if line.get("status") in {"triggered", "watch"}
            ]
            entry = {
                "status": "resolved",
                "thesis_id": doc["thesis_id"],
                "state": doc["state"],
                "checked_at": doc["checked_at"],
                "red_lines": sorted(red_lines, key=lambda row: str(row["id"])),
                "next_review_trigger": doc["next_review_trigger"],
            }
        if gate_docs and gate_docs[-1]["verdict"] == "reject":
            entry["entry_gate"] = {
                "verdict": "reject", "gate_id": gate_docs[-1]["gate_id"],
            }
        out[ticker] = entry
    return out


def summarize(*, portfolio=None, catalysts=None, today=None, now=None,
              thesis_dir=THESIS_DIR, earnings_dir=EARNINGS_DIR,
              entry_gate_dir=ENTRY_GATE_DIR, hk_watch=False,
              hk_results_fetch=None) -> dict:
    """The compact block the daily brief context carries."""
    now = now or datetime.now(timezone.utc)
    today = today or now.date()
    if portfolio is None:
        portfolio, _ = _load_json(PORTFOLIO)
    if catalysts is None:
        catalysts, _ = _load_json(CATALYSTS)
    portfolio = portfolio or {}
    positions = active_positions(portfolio)

    earnings, earnings_errors = load_earnings_artifacts(earnings_dir, now=now)
    gates, gate_errors = load_entry_gates(entry_gate_dir, now=now)
    theses, thesis_errors = thesis_registry.load_registry(thesis_dir)
    errors = earnings_errors + gate_errors + [f"theses: {e}" for e in thesis_errors]

    due = earnings_reviews_due(positions, catalysts, earnings, today, now=now)
    stale = stale_ledgers(positions, earnings, today)
    hk_expected = (
        hk_results_expected(
            positions, today, artifacts=earnings, fetch=hk_results_fetch
        ) if hk_watch else []
    )
    overdue = overdue_commitments(earnings, today)
    ungated = ungated_positions(positions, gates)
    verdicts: dict[str, int] = {}
    for docs in gates.values():
        if docs:
            verdicts[docs[-1]["verdict"]] = verdicts.get(docs[-1]["verdict"], 0) + 1
    open_questions = [
        {"ticker": docs[-1]["ticker"], "question": item["question"],
         "where_to_look": item["where_to_look"]}
        for docs in gates.values() if docs
        for item in (docs[-1].get("next_evidence") or [])
        if docs[-1]["verdict"] == "gray_needs_evidence"
    ]
    return {
        "status": "invalid" if errors else "ready",
        "as_of": today.isoformat(),
        "earnings": {
            "artifacts": {ticker: len(docs) for ticker, docs in sorted(earnings.items())},
            "latest_period": {
                ticker: docs[-1]["period"]["label"]
                for ticker, docs in sorted(earnings.items()) if docs
            },
            "reviews_due": due,
            "detection_window_days": review_window_days(catalysts),
            "stale_ledgers": stale,
            "hk_results_expected": hk_expected,
            "overdue_commitments": overdue,
        },
        "entry_gates": {
            "verdicts": dict(sorted(verdicts.items())),
            "open_questions": open_questions,
            "ungated_positions": ungated,
        },
        "theses": {"count": len(theses)},
        "errors": errors,
    }


def check(*, now=None, **kwargs) -> dict:
    """Integrity view for `system_check.py` and the `validate` workflow.

    Invalid artifacts fail closed. Work items warn: a due review is the human's
    queue, not a corrupt repository, and must never block a data publish.
    """
    surface = summarize(now=now, **kwargs)
    warnings = (
        [f"earnings review due: {row['ticker']} ({row['reported_on']})"
         for row in surface["earnings"]["reviews_due"]]
        + [f"HK results expected: {row['ticker']} (notice {row.get('notice_date')})"
           for row in surface["earnings"]["hk_results_expected"]
           if row.get("status") == "expected"]
        + [f"earnings ledger {row['days_behind']}d behind: {row['ticker']} "
           f"(last {row['latest_period']})"
           for row in surface["earnings"]["stale_ledgers"]]
        + [f"promise overdue {row['days_overdue']}d: {row['ticker']}/{row['commitment_id']}"
           for row in surface["earnings"]["overdue_commitments"]]
        + [f"ungated position: {row['ticker']} — {row['issue']}"
           for row in surface["entry_gates"]["ungated_positions"]]
    )
    return {
        "status": "fail" if surface["errors"] else ("warn" if warnings else "pass"),
        "errors": surface["errors"],
        "warnings": warnings,
        "counts": {
            "earnings_artifacts": sum(surface["earnings"]["artifacts"].values()),
            "entry_gates": sum(surface["entry_gates"]["verdicts"].values()),
            "theses": surface["theses"]["count"],
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="integrity only: exit 1 when an artifact is invalid")
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    result = check(now=now) if args.check else summarize(now=now)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.check:
        return 1 if result["status"] == "fail" else 0
    return 1 if result["status"] == "invalid" else 0


if __name__ == "__main__":
    sys.exit(main())

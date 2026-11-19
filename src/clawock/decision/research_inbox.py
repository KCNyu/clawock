"""Durable research queue; explicit human dispositions never grant trade authority."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from clawock.safe_io import file_lock, safe_write_json
from clawock.workspace import workspace_root

STATES = {"pending": "待看", "researching": "研究中", "deferred": "暂缓", "rejected": "已否决"}
MAX_ROWS = 2000
WEEKLY_LIMIT = 4


def _date(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return parsed


def _path(workspace):
    return Path(workspace) / ".cache" / "research-inbox.json"


def _key(market, ticker):
    if not isinstance(market, str) or not isinstance(ticker, str):
        raise ValueError("invalid market/ticker")
    market, ticker = market.upper(), ticker.upper().strip()
    pattern = r"[0-9]{5}" if market == "HK" else r"[A-Z]{1,5}(?:[.-][A-Z])?"
    if market not in {"US", "HK"} or not re.fullmatch(pattern, ticker):
        raise ValueError("invalid market/ticker")
    return f"{market}:{ticker}"


def _load(path):
    if not path.exists():
        return {"schema_version": 1, "rows": {}}
    doc = json.loads(path.read_text())
    if not isinstance(doc, dict) or doc.get("schema_version") != 1 or not isinstance(doc.get("rows"), dict):
        raise ValueError("invalid research inbox; refusing to overwrite")
    if len(doc["rows"]) > MAX_ROWS:
        raise ValueError("research inbox exceeds capacity")
    for key, row in doc["rows"].items():
        if (not isinstance(row, dict) or key != _key(row.get("market", ""), row.get("ticker", ""))
                or row.get("status") not in STATES):
            raise ValueError("invalid research inbox row")
        for field in ("first_seen", "last_seen"):
            _date(row[field])
        if row.get("review_on"):
            _date(row["review_on"])
    return doc


def ingest(workspace, candidates, *, today):
    """Short locked merge; never stores quotes, infers a disposition, or resets it."""
    _date(today)
    path = _path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(str(path)):
        doc = _load(path)
        for candidate in candidates:
            market, ticker = candidate["market"], candidate["ticker"]
            key = _key(market, ticker)
            row = doc["rows"].get(key)
            if row is None:
                if len(doc["rows"]) >= MAX_ROWS:
                    raise ValueError("research inbox full; existing rows preserved")
                row = {"ticker": ticker, "market": market, "first_seen": today,
                       "status": "pending", "reason": "", "review_on": None}
                doc["rows"][key] = row
            row.update({k: str(candidate.get(k) or "")[:160]
                        for k in ("name", "sector_label")})
            row["last_seen"] = today
        safe_write_json(str(path), doc)
    return doc


def set_status(workspace, market, ticker, status, *, reason, review_on=None,
               assessment=None, today=None):
    key = _key(market, ticker)
    if status not in STATES or not reason.strip() or len(reason) > 1000:
        raise ValueError("a known status and a reason (1..1000 characters) are required")
    if review_on:
        _date(review_on)
    if status == "deferred" and not review_on:
        raise ValueError("deferred requires --review-on")
    path = _path(workspace)
    if not path.exists():
        raise ValueError("candidate not in inbox; run research-inbox collect first")
    with file_lock(str(path)):
        doc = _load(path)
        if key not in doc["rows"]:
            raise ValueError("candidate not in inbox")
        row = doc["rows"][key]
        if assessment is not None:
            today = today or _today()
            _validate_assessment(assessment, status, today, review_on, market)
            if today < row["first_seen"]:
                raise ValueError("assessment predates discovery")
            history = row.setdefault("assessments", {})
            week = _week_start(today)
            if week not in history and _processed(doc, week) >= WEEKLY_LIMIT:
                raise ValueError("weekly research limit reached")
            row.setdefault("first_processed_on", today)
            history[week] = {"on": today, "status": status, "reason": reason.strip(),
                             "review_on": review_on, **assessment}
        row.update(status=status, reason=reason.strip(), review_on=review_on,
                   updated_at=datetime.now(timezone.utc).isoformat())
        safe_write_json(str(path), doc)
    return doc["rows"][key]


def _today():
    from clawock.sessions import hkt_today
    return hkt_today().isoformat()


def _week_start(today):
    day = _date(today)
    return (day - timedelta(days=day.weekday())).isoformat()


def _processed(doc, week):
    return sum(week in row.get("assessments", {}) for row in doc["rows"].values())


def _validate_assessment(assessment, status, today, review_on, market):
    fields = {"thesis", "counterevidence", "primary_sources", "completed"}
    if not isinstance(assessment, dict) or not fields <= assessment.keys() or (
            assessment.keys() - fields - {"benchmark"}):
        raise ValueError("assessment needs thesis, counterevidence, primary_sources and completed")
    if status == "pending" or not review_on or review_on <= today:
        raise ValueError("assessment needs a disposition and future review date")
    for field in ("thesis", "counterevidence"):
        value = assessment[field]
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 1000:
            raise ValueError(f"assessment needs {field} (1..1000 characters)")
    sources = assessment["primary_sources"]
    if not isinstance(sources, list) or not 1 <= len(sources) <= 5 or not all(
            isinstance(url, str) and len(url) <= 500 and urlsplit(url).scheme == "https"
            and urlsplit(url).hostname and not urlsplit(url).username for url in sources):
        raise ValueError("supply 1..5 primary disclosure HTTPS links")
    if type(assessment["completed"]) is not bool:
        raise ValueError("completed must be a boolean")
    benchmark = assessment.get("benchmark")
    if benchmark is not None and benchmark != ("HSI" if market.upper() == "HK" else "SPY"):
        raise ValueError("benchmark must be the market's HSI or SPY, or null when unavailable")


def weekly(workspace, *, today):
    """Review one bounded queue and its dispositions without refreshing discovery."""
    doc = _load(_path(workspace))
    week = _week_start(today)
    processed, due, recent, backlog = [], [], [], []
    for key, row in doc["rows"].items():
        if row["first_seen"] > today:
            continue
        receipt = row.get("assessments", {}).get(week)
        if receipt and receipt["on"] <= today:
            processed.append({"candidate": key, **receipt, "first_processing_days":
                              (_date(row["first_processed_on"]) - _date(row["first_seen"])).days})
            continue
        if row.get("review_on") and row["review_on"] <= today:
            due.append((row["review_on"], key))
        elif row["status"] == "pending":
            (recent if row["first_seen"] >= week else backlog).append((row["first_seen"], key))
    ordered = [key for _, key in sorted(due)]
    # Give both fresh discoveries and the oldest unprocessed rows a turn.
    pairs = zip(sorted(recent), sorted(backlog))
    ordered.extend(key for pair in pairs for _, key in pair)
    shared = min(len(recent), len(backlog))
    ordered.extend(key for _, key in sorted(recent)[shared:] + sorted(backlog)[shared:])
    remaining = max(0, WEEKLY_LIMIT - len(processed))
    completed = sum(row["completed"] for row in processed)
    return {"week_start": week, "as_of": today, "capacity": WEEKLY_LIMIT,
            "queue": [{"ticker": doc["rows"][key]["ticker"], "market": doc["rows"][key]["market"],
                       "first_seen": doc["rows"][key]["first_seen"], "review_on": doc["rows"][key]["review_on"]}
                      for key in ordered[:remaining]],
            "processed": sorted(processed, key=lambda row: row["candidate"]),
            "completed": completed, "completion_rate": completed / len(processed) if processed else None,
            "followup": _proposal_followup(workspace, today, doc)}


def _proposal_followup(workspace, today, doc):
    from . import ledger
    from .actions import ADD_ACTIONS

    workspace = Path(workspace)
    decisions = []
    for row in ledger.load_decisions(workspace / "memory/decisions.jsonl"):
        candidate = doc["rows"].get(f'{row.get("leg")}:{row.get("ticker")}') or {}
        first = candidate.get("first_processed_on")
        day = row.get("plan_date") or ""
        if (not first or not first < day <= today or row.get("strategy_id") != "tactical_entry"
                or row.get("action") not in ADD_ACTIONS or not row.get("decision_id")):
            continue
        # One published call per pair here. The normal scorecard averages calls by episode.
        evaluation = row.get("evaluation") or {}
        mark = evaluation.get("mark_t1_session") or ""
        decisions.append({**row, "episode_id": row["decision_id"],
                          "evaluation": evaluation if mark and mark <= today else {}})
    if not decisions:
        return []
    try:
        benchmark = json.loads((workspace / "assets/data/benchmark.json").read_text())
    except (OSError, ValueError):
        benchmark = {}
    reps = [{"episode_id": row["episode_id"]} for row in decisions]
    ledger._benchmark_pairs(decisions, reps, "t1", benchmark if isinstance(benchmark, dict) else {})
    return [{"decision_id": row["decision_id"], "ticker": row["ticker"], "market": row["leg"],
             "plan_date": row["plan_date"], "t1_benchmark": rep["benchmark_pair"]}
            for row, rep in list(zip(decisions, reps))[-WEEKLY_LIMIT:]]


def _published_gates(workspace):
    """Link only committed artifacts, pinned to the fetched public source ref."""
    import subprocess
    from urllib.parse import quote
    try:
        def git(*args):
            return subprocess.check_output(["git", "-C", str(workspace), *args],
                                           text=True, stderr=subprocess.DEVNULL, timeout=3).strip()
        remote = git("remote", "get-url", "origin")
        match = re.fullmatch(r"(?:https://github.com/|git@github.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?", remote)
        if not match:
            return {}
        commit = git("rev-parse", "origin/master")
        paths = git("ls-tree", "-r", "--name-only", commit, "--", "memory/entry-gates").splitlines()
        changed = set(git("diff", "--name-only", commit, "--", "memory/entry-gates").splitlines())
        return {path: f"https://github.com/{match[1]}/blob/{commit}/{quote(path, safe='/')}"
                for path in paths if path not in changed}
    except (OSError, subprocess.SubprocessError):
        return {}


def _gates(workspace, today):
    from clawock.decision.entry import proposal_authorizations
    gates = proposal_authorizations(workspace, today=today)
    paths = {}
    for path in sorted((Path(workspace) / "memory/entry-gates").glob("*.json")):
        try:
            doc = json.loads(path.read_text())
            gate = gates.get(doc.get("ticker"), {})
            if doc.get("gate_id") and doc.get("gate_id") == gate.get("gate_id"):
                paths[doc["ticker"]] = str(path.relative_to(workspace))
        except (OSError, ValueError, AttributeError):
            continue
    return gates, paths


def view(workspace, *, today, limit=12, highlights_only=False):
    _date(today)
    doc = _load(_path(workspace))
    gates, paths = _gates(workspace, today)
    published = _published_gates(workspace) if paths else {}
    rows = []
    for stored in doc["rows"].values():
        row = dict(stored)
        row["due"] = bool(row.get("review_on") and row["review_on"] <= today)
        row["new"] = row["first_seen"] == today
        if highlights_only and not (row["due"] or (row["new"] and row["status"] == "pending")):
            continue
        row["status_label"] = STATES[row["status"]]
        row["gate_draft_command"] = f"clawock research-inbox draft {row['ticker']} --market {row['market']}"
        gate = gates.get(row["ticker"]) or {}
        row["gate"] = {k: gate[k] for k in ("gate_id", "cleared", "verdict", "assessed_at") if k in gate}
        row["gate_artifact"] = paths.get(row["ticker"])
        row["gate_url"] = published.get(row["gate_artifact"])
        rows.append(row)
    rows.sort(key=lambda r: (not r["due"], r.get("review_on") or "", r["first_seen"], r["market"], r["ticker"]))
    return {"status": "ok", "as_of": today, "total": len(doc["rows"]), "matching": len(rows),
            "rows": rows[:limit], "has_more": len(rows) > limit, "research_only": True}


def attach(workspace, discovery, *, today):
    """An optional queue failure cannot erase fresh candidates or fail the brief."""
    result = dict(discovery)
    try:
        ingest(workspace, discovery.get("candidates") or [], today=today)
        result["inbox"] = view(workspace, today=today, highlights_only=True)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result["inbox"] = {"status": "unavailable", "reason": type(exc).__name__, "rows": []}
    return result


def draft(workspace, market, ticker):
    """Use a stored candidate or discover it now; never write authorization artifacts."""
    from .entry_draft import build

    key = _key(market, ticker)
    row = _load(_path(workspace))["rows"].get(key)
    if row is None:
        from clawock.market_data.stock_discovery import collect
        found = collect(workspace, market=market)
        row = next((r for r in found.get("candidates", []) if _key(r["market"], r["ticker"]) == key), None)
        if row is None:
            raise ValueError("not a stored or current candidate; discovery status=" + found["status"])
    return build(row, workspace=Path(workspace))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="clawock research-inbox", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("collect", help="discover candidates and merge into the local inbox")
    listing = sub.add_parser("list")
    listing.add_argument("--highlights", action="store_true")
    listing.add_argument("--limit", type=int, default=50)
    sub.add_parser("weekly", help="show the bounded weekly research queue and dispositions")
    drafting = sub.add_parser("draft", help="emit an unassessed entry-gate JSON template; does not clear the gate")
    drafting.add_argument("ticker")
    drafting.add_argument("--market", required=True, choices=["US", "HK"])
    setting = sub.add_parser("set")
    setting.add_argument("ticker")
    setting.add_argument("--market", required=True, choices=["US", "HK"])
    setting.add_argument("--status", required=True, choices=sorted(STATES))
    setting.add_argument("--reason", required=True)
    setting.add_argument("--review-on")
    setting.add_argument("--assessment", type=Path, help="record a sourced weekly assessment JSON")
    args = parser.parse_args(argv)
    today = _today()
    try:
        if args.command == "collect":
            from clawock.market_data.stock_discovery import collect
            result = attach(workspace_root(), collect(workspace_root(), market="all"), today=today)
        elif args.command == "draft":
            result = draft(workspace_root(), args.market, args.ticker)
        elif args.command == "set":
            result = set_status(workspace_root(), args.market, args.ticker, args.status,
                                reason=args.reason, review_on=args.review_on,
                                assessment=json.loads(args.assessment.read_text()) if args.assessment else None,
                                today=today)
        elif args.command == "weekly":
            result = weekly(workspace_root(), today=today)
        else:
            if not 1 <= args.limit <= MAX_ROWS:
                raise ValueError("limit must be 1..2000")
            result = view(workspace_root(), today=today, limit=args.limit, highlights_only=args.highlights)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"research inbox unavailable: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

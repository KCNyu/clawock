"""What an intraday anomaly means for the add side — read, not authorization.

kcn, 2026-08-17: "我的诉求就是盘中能捕捉到因为情绪消息异动/股价异动分析出来的加仓信号."

Everything this needs was already computed and already in the intraday packet, and
none of it reached the message: `opportunity_radar` (a technical approach to the
20-day high), `early_trend_candidates`, `anomalies` (the price move), `mover_news`
(what filed, already triaged into interrupt/context) and `mover_thesis` (whether a
red line is live). The prose template named the first three of those nowhere, so a
+6.4% move with three near-breakout rows beside it produced a report about
holdings and open orders and nothing about adding (#755).

This module only **joins** those answers and states a disposition in the vocabulary
the rest of the desk already uses (`candidate` / `wait` / `reject`, as in
`active_information.scan`). It invents no threshold, computes no size, and copies
every number from its inputs — the rules below are the ones already written down:

* **Discipline first.** A live thesis breach or an unexecuted `risk_rule` action
  makes it `reject`: while a stop or a trim is outstanding, adding is not a
  question the desk asks.
* **Only a primary disclosure can promote.** `candidate` requires an
  `interrupt`-class primary filing *and* a technical state that is at or near the
  breakout. This is the existing catalyst gate: soft news and sentiment are colour,
  never an active-operation reason.
* **Everything else is `wait`, with what would change it.** A price anomaly with no
  primary catalyst is the common case (02208 +6.4% on 2026-08-17), and the useful
  output there is the falsifier — the level or the session that would settle it —
  not a shrug.

Deliberately absent: the daily `sentiment.json` scan. It carries no intraday
threshold, so feeding it in would mean inventing one here; soft news already
reaches these rows through `mover_news`, where it can raise a `wait` and cannot
promote. Adding sentiment as a trigger is a decision for kcn, not a default.
"""
from __future__ import annotations

VERDICTS = ("candidate", "wait", "reject")

# The technical states `opportunity_radar` emits that mean "the breakout is in
# play". Anything else (a name deep inside its range) is not an add-side read at
# all and produces no row.
IN_PLAY_STATES = ("breakout", "near_breakout", "at_high")


def _radar_index(radar):
    """holdings ticker -> radar row. A row can cover several holdings (an index
    proxy: HSTECH covers 07226), so both the label and every holding map to it."""
    index = {}
    for row in (radar or {}).get("rows", []) or []:
        if row.get("state") not in IN_PLAY_STATES:
            continue
        for key in [row.get("label"), *(row.get("holdings") or [])]:
            if key:
                index.setdefault(key, row)
    return index


def _level(levels, ticker):
    """The plain 20-day level for a name the radar does not carry (#759).

    `opportunity_radar` only keeps in-play states, so in a selloff every row it
    would have carried disappears — exactly when a `wait` most needs to say
    where the question gets settled. `levels` is the same pass's arithmetic for
    every name, so the falsifier survives the sell-off. It is a sentence source,
    never a promotion input: see `read_rows`, where a level cannot add a trigger
    or a technical `state`.
    """
    row = (levels or {}).get(ticker) or {}
    return row if row.get("prior_20d_high") is not None else None


def _needs_level(row):
    """The one wording for 'what would settle it', used by radar and level alike."""
    return f"站上 {row.get('prior_20d_high')}(现距高 {row.get('pct_from_high')}%)"


def _primary_interrupt(news, ticker):
    """The one item class the catalyst gate lets promote a read."""
    entry = ((news or {}).get("tickers") or {}).get(ticker) or {}
    for item in entry.get("items") or []:
        if item.get("signal") == "interrupt" and item.get("tier") == "primary":
            return item
    return None


def _soft_news(news, ticker):
    entry = ((news or {}).get("tickers") or {}).get(ticker) or {}
    items = entry.get("items") or []
    soft = [i for i in items if i.get("signal") != "interrupt"
            or i.get("tier") != "primary"]
    return soft[0] if soft else None


def _breach(thesis, ticker):
    row = (thesis or {}).get(ticker) or {}
    if row.get("status") in ("triggered", "breached"):
        return row.get("reason") or row.get("status")
    for line in row.get("triggered") or []:
        if isinstance(line, dict):
            return line.get("required_action") or line.get("label") or "thesis red line"
        if line:
            return str(line)
    return None


def _open_risk_action(plan_context, ticker):
    for row in (plan_context or {}).get("open", []) or []:
        if row.get("ticker") != ticker:
            continue
        if row.get("driven_by") == "risk_rule":
            return row
    return None


def read_rows(*, anomalies=None, radar=None, levels=None, early_trend=None,
              mover_news=None, mover_thesis=None, plan_context=None):
    """Join the packet's own answers into add-side reads, most acute first.

    Every field is copied from an input; nothing here is derived arithmetic, so a
    number that appears in a row can always be pointed at in the context.
    """
    radar_by_ticker = _radar_index(radar)
    rows = []
    seen = set()

    def add(ticker, triggers, evidence):
        if not ticker or ticker in seen:
            return
        seen.add(ticker)
        breach = _breach(mover_thesis, ticker)
        risk_action = _open_risk_action(plan_context, ticker)
        primary = _primary_interrupt(mover_news, ticker)
        soft = _soft_news(mover_news, ticker)
        radar_row = radar_by_ticker.get(ticker)

        if breach or risk_action:
            verdict = "reject"
            if risk_action:
                why = (f"纪律动作未了结:{risk_action.get('action')} "
                       f"{risk_action.get('shares')} 股(driven_by=risk_rule)")
            else:
                why = f"thesis 红线在触发状态:{breach}"
            needs = "先把纪律动作走完,再谈加仓"
        elif primary and radar_row:
            verdict = "candidate"
            why = (f"一手公告 + 技术面{radar_row.get('state_zh') or radar_row.get('state')}"
                   f":{primary.get('title') or primary.get('headline') or 'primary filing'}")
            needs = f"站上 {radar_row.get('prior_20d_high')} 并守住"
        else:
            verdict = "wait"
            missing = []
            if not primary:
                missing.append("窗口内无一手公告" if soft is None else "只有软消息/情绪面")
            if not radar_row:
                missing.append("技术面未接近突破")
            why = "、".join(missing) or "条件不齐"
            level = radar_row or _level(levels, ticker)
            # #759: a level the radar dropped still answers "跌到哪才算机会".
            # Only the wording changes — `verdict`, `triggers` and
            # `evidence["state"]` are decided above and stay untouched, so a far
            # level can never read as an approach.
            needs = (_needs_level(level) if level
                     else "等一手催化或技术面进入突破区")
            if level and evidence.get("prior_20d_high") is None:
                # The number quoted in `needs` has to be pointable-at in the
                # packet, not only inside a sentence (数字只能引用 context).
                evidence = {**evidence,
                            "prior_20d_high": level.get("prior_20d_high"),
                            "pct_from_high": level.get("pct_from_high")}

        rows.append({
            "ticker": ticker,
            "triggers": triggers,
            "verdict": verdict,
            "why": why,
            "needs": needs,
            "evidence": {k: v for k, v in evidence.items() if v is not None},
            # Stated, not implied: this lane never sizes or authorises. The desk's
            # add decisions stay with kcn; #755 asked for visibility, not a trader.
            "authorization": None,
        })

    for anomaly in anomalies or []:
        ticker = anomaly.get("ticker")
        radar_row = radar_by_ticker.get(ticker)
        triggers = ["price_anomaly"]
        if _soft_news(mover_news, ticker) is not None:
            triggers.append("news")
        if radar_row:
            triggers.append("near_breakout")
        add(ticker, triggers, {
            "move_pct": anomaly.get("move_pct"),
            "severity": anomaly.get("severity"),
            "state": (radar_row or {}).get("state"),
            "pct_from_high": (radar_row or {}).get("pct_from_high"),
            "prior_20d_high": (radar_row or {}).get("prior_20d_high"),
        })

    for row in (early_trend or {}).get("rows", []) or []:
        add(row.get("label"), ["early_trend"], {
            "state": row.get("state"),
            "disposition": row.get("disposition"),
        })

    for ticker, radar_row in radar_by_ticker.items():
        # Holdings-only: the radar also carries index labels (HSTECH) whose
        # holdings row is the tradable one, and it was already added above.
        if ticker in seen or ticker not in (radar_row.get("holdings") or []):
            continue
        add(ticker, ["near_breakout"], {
            "state": radar_row.get("state"),
            "pct_from_high": radar_row.get("pct_from_high"),
            "prior_20d_high": radar_row.get("prior_20d_high"),
        })

    order = {"candidate": 0, "reject": 1, "wait": 2}
    rows.sort(key=lambda r: (order[r["verdict"]],
                             -abs(r["evidence"].get("move_pct") or 0)))
    return {
        "rows": rows,
        "candidate_count": sum(r["verdict"] == "candidate" for r in rows),
        "wait_count": sum(r["verdict"] == "wait" for r in rows),
        "reject_count": sum(r["verdict"] == "reject" for r in rows),
        "policy": ("一手披露才可能促成 candidate;软消息/情绪只能停在 wait;"
                   "纪律动作未了结一律 reject。三态都不是下单授权。"),
    }

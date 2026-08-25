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
* **A confirmed technical breakout can promote on its own; a primary
  filing upgrades the wording.** `candidate` requires a radar row in the
  `breakout` state (close > prior 20-day high, not overheated) — the one add
  shape the 8-month bars backtest (#819) measured with a positive edge at every
  horizon (T+1/5/10/20 hit 52.5/54.0/52.5/55.9%, avg fwd +16.25% at T+20; HK
  T+20 59.4%). This module only ever runs in the intraday slot, where "close"
  is the live print and the close itself is still pending — rows say so
  explicitly, and the backtest numbers are quoted as close-confirmed. Near-
  breakout/at-high without a primary filing stay `wait`
  (no standalone edge). Soft news and sentiment remain colour, never an
  active-operation reason.
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

# Marks a radar row reached through a proxy label (an index standing in for the
# tradable product). Private to this module: it never reaches a row's evidence,
# which carries `proxy_label` instead.
PROXY_KEY = "_proxy_label"

# The technical states `opportunity_radar` emits that mean "the breakout is in
# play". Anything else (a name deep inside its range) is not an add-side read at
# all and produces no row.
IN_PLAY_STATES = ("breakout", "near_breakout", "at_high")

# States that get a row at all (#819). `wait_rebreak` — an uptrend pulling
# back — is NOT in play: it stays out of the promotion gate below, but it is a
# real read (unlike a name deep inside its range), and before this split it was
# dropped wholesale, so the desk never collected a single sample to test
# whether "buy the dip inside an uptrend" holds. It now produces `wait` rows
# with their state logged; whether it ever joins IN_PLAY_STATES is a
# measurement decision, not a naming one.
ROW_STATES = IN_PLAY_STATES + ("wait_rebreak",)


def _radar_index(radar):
    """holdings ticker -> radar row. A row can cover several holdings (an index
    proxy: HSTECH covers 07226), so both the label and every holding map to it.

    #761: the mapping stays — 07226 *is* the 2x HSTECH product, so the index
    approaching its high is real information about it. What must not survive the
    hop is the *attribution* of the numbers: 4948.5 is a Hang Seng Tech index
    level, and 07226 trades near 3.5 HKD. Rows reached through a proxy are
    tagged here, and every place that renders a number checks the tag.
    """
    rows = [row for row in (radar or {}).get("rows", []) or []
            if row.get("state") in ROW_STATES]
    index = {}
    # Two passes, and the order matters: a name that has a row of its own must
    # win over any proxy that also covers it, whatever order the radar sorted
    # its rows into (it sorts by `pct_from_high`, so a single pass would decide
    # attribution by today's prices). Nothing in the universe hits this today —
    # 07226 and SPCH have no rows of their own — but "which numbers this ticker
    # gets" must not be a function of the sort order the day one appears.
    for row in rows:
        if row.get("label"):
            index.setdefault(row["label"], row)
    for row in rows:
        label = row.get("label")
        for key in row.get("holdings") or []:
            if key:
                index.setdefault(key, row if key == label
                                 else {**row, PROXY_KEY: label})
    return index


def _proxy_of(radar_row):
    """The label a row was reached through, or None when it is the row's own."""
    return (radar_row or {}).get(PROXY_KEY)


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
    """The one wording for 'what would settle it', used by radar and level alike.

    A proxy row names the thing the level belongs to, because the bare sentence
    reads as the holding's own price and the two are not in the same scale
    (#761).
    """
    proxy = _proxy_of(row)
    lead = f"{proxy} 站上 " if proxy else "站上 "
    return (f"{lead}{row.get('prior_20d_high')}"
            f"(现距高 {row.get('pct_from_high')}%)")


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
        elif radar_row and radar_row.get("state") in IN_PLAY_STATES and (
                radar_row.get("state") == "breakout" or primary):
            # #819: the breakout state alone carries the measured edge
            # (8-month bars backtest: hit >50% at T+1/5/10/20, avg fwd positive;
            # deep-dip adds failed all four horizons — the original 逢低 assumption).
            # Promotion shape: breakout promotes by itself; a primary filing is
            # the promotion key only for near_breakout/at_high, where it never
            # substitutes for the level — the ask stays "get above prior_20d_high".
            verdict = "candidate"
            if primary:
                why = (f"一手公告 + 技术面{radar_row.get('state_zh') or radar_row.get('state')}"
                       f":{primary.get('title') or primary.get('headline') or 'primary filing'}")
                if radar_row.get("state") == "breakout":
                    lead = f"{_proxy_of(radar_row)} 守住 " if _proxy_of(radar_row) else "守住 "
                    needs = f"{lead}{radar_row.get('prior_20d_high')}(回踩不破再谈加仓)"
                else:
                    # near_breakout/at_high with a primary filing: the price is
                    # still below the level, so the ask is to get above it.
                    lead = f"{_proxy_of(radar_row)} 站上 " if _proxy_of(radar_row) else "站上 "
                    needs = f"{lead}{radar_row.get('prior_20d_high')} 并守住"
            else:
                state_zh = radar_row.get('state_zh') or radar_row.get('state')
                # 本模块只在盘中档运行（intraday_preflight）：雷达的 close 是
                # 实时价，收盘未确认——#819 回测度量的是收盘确认的突破，文案
                # 不得把现价触发说成已确认的收盘事实。
                why = (f"技术面{state_zh}:现价站上前 20 日高且未过热(盘中、收盘未确认;"
                       f"回测口径为收盘确认:四个周期命中率均>50%)")
                lead = f"{_proxy_of(radar_row)} 守住 " if _proxy_of(radar_row) else "守住 "
                needs = f"{lead}{radar_row.get('prior_20d_high')}(回踩不破再谈加仓)"
        else:
            verdict = "wait"
            missing = []
            if not primary:
                missing.append("窗口内无一手公告" if soft is None else "只有软消息/情绪面")
            if not radar_row:
                missing.append("技术面未接近突破")
            elif radar_row.get("state") not in IN_PLAY_STATES:
                # #819: wait_rebreak rows now exist and say what they are —
                # an uptrend pulling back, logged as state, not a silent drop.
                missing.append(f"技术面{radar_row.get('state_zh') or radar_row.get('state')}")
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
                            "close": level.get("close"),
                            "pct_from_high": level.get("pct_from_high")}

        proxy = _proxy_of(radar_row)
        if proxy:
            # #761: the level came from the proxy, so it must not sit under the
            # bare key the template is told to copy («数字照抄 evidence 的
            # prior_20d_high»). The relationship is kept — the row exists, its
            # `state` still feeds the promotion gate — only the numbers are
            # re-attributed to the thing they actually measure.
            evidence = {**evidence, "proxy_label": proxy}
            for key in ("prior_20d_high", "pct_from_high", "close", "zscore20"):
                if evidence.get(key) is not None:
                    evidence[f"proxy_{key}"] = evidence.pop(key)

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
            "close": (radar_row or {}).get("close"),
            "zscore20": (radar_row or {}).get("zscore20"),
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
            "close": radar_row.get("close"),
            "zscore20": radar_row.get("zscore20"),
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
        "policy": ("技术突破(现价站上前 20 日高且未过热,盘中读数、收盘未确认)即 candidate,"
                   "一手公告升级措辞;软消息/情绪只能停在 wait;"
                   "纪律动作未了结一律 reject。三态都不是下单授权。"),
    }

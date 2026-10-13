"""User-authorized, bounded prospective entries before a breakout.

This is a decision policy, not a change to the quant/factor measurements or to
historical left-side experiments. Campaign ids do not roll daily. Two filled
tranches exhaust a policy version; renewed capital needs an explicit new policy.
"""
from __future__ import annotations

import sys

import json
from clawock.safe_io import to_strict_finite_number as number
from clawock.workspace import workspace_root
from clawock.plugin_host import live as live_plugins

SETUP_ID = "preposition_scale_in"
TIER = "user_experiment"


def load_policy():
    try:
        return json.loads((workspace_root() / "config/preposition-policy.json").read_text())
    except (OSError, ValueError):
        return {}


def setup(row, information, policy, *, ticker, leg, usage, cost_basis=None,
          leveraged=False, thesis_state="unknown", hard_stop_pct=None):
    """Own-instrument levels only; never use an underlying's price for a 2x ETF."""
    if not policy.get("enabled") or row.get("status") != "fresh":
        return None
    if thesis_state in {"broken", "damaged", "weakening"}:
        return None
    close, atr_pct, high = (number(row.get(k)) for k in
                            ("close", "atr14_pct", "prior_20d_high"))
    if not close or close <= 0 or not atr_pct or atr_pct <= 0:
        return None
    atr = close * atr_pct / 100
    depth = (high - close) / atr if high else 0
    positive = (information.get("usable_for_decisions") is True
                and information.get("sizing_tilt") == "positive")
    if information.get("usable_for_decisions") and information.get("sizing_tilt") == "negative":
        return None
    if depth < policy["min_depth_atr"] and not positive:
        return None
    campaign = f"{leg}:{ticker}:preposition:{policy['version']}"
    used = int(usage.get(campaign) or 0)
    if used >= policy["max_tranches"]:
        return None
    # First tranche rests at the last close; the next asks for one more ATR.
    # Repriced daily, with one-session validity; not a permanent limit order.
    entry = close - used * policy["rung_spacing_atr"] * atr
    stop = entry - policy["invalidation_atr"] * atr
    if leveraged:
        cost = number(cost_basis)
        if not cost or cost <= 0:
            return None
        # Independent of any holding-strategy exemption: this experimental
        # lane never adds beyond the retained product hard-stop line.
        hard_stop_pct = number(hard_stop_pct)
        if hard_stop_pct is None or not -100 < hard_stop_pct < 0:
            return None
        stop = max(stop, cost * (1 + hard_stop_pct / 100))
    if not 0 < stop < entry:
        return None
    return {
        "setup_id": SETUP_ID, "campaign_id": campaign,
        "label": "提前埋点/左侧分档（前瞻试验）",
        "entry_type": "price_below", "entry_price": round(entry, 4),
        "invalidation_price": round(stop, 4),
        **live_plugins.service('add_policy').tier_terms({}, TIER, experiment_policy=policy),
        "valid_for_sessions": policy["valid_for_sessions"],
        "signal_date": row.get("row_as_of"), "authority_tier": TIER,
        "authority_sources": ["explicit_user_authorization"],
        "evidence_families": (["information_surprise"] if positive else [])
                             + (["technical_weakness"] if depth >= policy["min_depth_atr"] else []),
        "evidence_strength": policy["evidence"],
        "detail": "每档按当前持仓比例×已激活 sizing_tilt；现金/整手/未成交单/硬止损优先。两档成交后耗尽，不因换日重置；无择时优势声明。",
    }


def measurements(workspace, portfolio, *, at=None):
    """Read the traded instruments' archived OHLC, never proxy price levels.

    Reuses the existing signal calculator without writing its production output.
    Missing/stale/conflicted archives remain explicit unavailable inputs.
    """
    from pathlib import Path
    from clawock.sessions import latest_completed_session
    from clawock.market_data.integrity import check_bar

    result = {}
    for key, book in portfolio.get("portfolios", {}).items():
        leg = "HK" if key == "hk_stocks" else "US"
        expected = latest_completed_session(leg.lower(), at=at)
        for holding in book.get("holdings") or []:
            if (number(holding.get("shares")) or 0) <= 0:
                continue
            ticker = holding["ticker"]
            unavailable = {"status": "unavailable", "reason": "missing_or_stale_own_instrument_bars"}
            result[ticker] = unavailable
            try:
                doc = json.loads((Path(workspace) / "memory/bars" / f"{ticker}.json").read_text())
                bars = doc.get("bars") or {}
                if doc.get("retired") or not bars or expected is None or max(bars) != expected.isoformat():
                    continue
                rows = [{"date": d, **bars[d]} for d in sorted(bars)[-220:]]
                if any(r.get("implausible_move") or r.get("degenerate")
                       or check_bar(r)["fatal"] or check_bar(r)["flags"] for r in rows[-30:]):
                    unavailable["reason"] = "suspect_own_instrument_bars"
                    continue
                computed = live_plugins.service('factors').signals(rows)
                if computed:
                    result[ticker] = {k: computed.get(k) for k in
                                     ("close", "atr14_pct", "prior_20d_high")}
                    result[ticker].update(status="fresh", row_as_of=max(bars))
            except (OSError, ValueError, TypeError, KeyError):
                continue
    return result


name = 'preposition'


inject = ('add_policy', 'factors')


SIGNAL_SOURCE = {'id': 'preposition',
 'family': 'technical',
 'summary': 'Own-instrument factor projection for the preposition policy; setups apply '
            'declared policy, not new measured alpha.',
 'inputs': [{'name': 'bars',
             'what': 'latest completed session OHLC for active holdings',
             'source': 'workspace memory/bars, raw; current portfolio identities; factors '
                       'service'},
            {'name': 'policy and information',
             'what': 'authorized policy, activated information direction, tranche usage, '
                     'thesis state and cost_basis',
             'source': 'caller and config/preposition-policy.json'}],
 'outputs': [{'field': 'measurements.<ticker>.close',
              'unit': 'quote-currency price',
              'window': 'latest completed session',
              'missing': 'omitted with unavailable status/reason'},
             {'field': 'measurements.<ticker>.atr14_pct',
              'unit': 'percent of close',
              'window': '14 sessions Wilder ATR on up to 220 bars',
              'missing': 'null if factors cannot measure; setup refused'},
             {'field': 'measurements.<ticker>.prior_20d_high',
              'unit': 'quote-currency price',
              'window': '20 sessions excluding latest',
              'missing': 'null if not measurable'},
             {'field': 'measurements.<ticker>.status / reason / row_as_of',
              'unit': 'fresh or unavailable; text reason; ISO session date',
              'window': 'this read',
              'missing': 'unavailable with reason, date omitted'},
             {'field': 'setup.entry_price / invalidation_price',
              'unit': 'quote-currency price rounded to 4 decimals',
              'window': 'policy valid_for_sessions; current tranche',
              'missing': 'whole setup null if missing/blocked inputs'},
             {'field': 'setup',
              'unit': 'identity/text: setup_id,campaign_id,label,entry_type,detail,authority_tier; '
                      'text lists: authority_sources,evidence_families; evidence_strength: label; '
                      'signal_date: ISO session; valid_for_sessions/max_tranches/target_tranche_level: '
                      'counts; tranche_pct_of_position: fraction (0.1 is 10%)',
              'window': 'policy version and configured session validity',
              'missing': 'null when no eligible setup'}],
 'missing': {'policy': 'omitted',
             'detail': 'Missing/stale/suspect bars produce unavailable reason and no '
                       'measurements; no previous row reused. Ineligible setup returns null.',
             'serves_stale': False}}


def apply(ctx, config):
    """Mount this module as the `preposition` service."""
    ctx.provide('preposition', sys.modules[__name__])

"""What the shadow book would have paid to trade, and why it is an assumption.

The gap this closes
-------------------
Every performance number this repository publishes is **gross**.
`decision.shadow` fills at `qty * price` (`shadow.py`, `_execute_buy`), and
`decision.ledger.condition_execution` says so in its own docstring — "still
assumes zero slippage and available liquidity" — and records `fill_assumed`
beside every fill. So the assumption is known, it is written down, and it has
never been *priced*. A simulated timing alpha quoted without costs is the number
a sceptical reader discounts first, and `signal_panel` already says the same
thing about turnover in one paragraph: an edge quoted without it is gross.

What this is not
----------------
Not a TCA platform, not a matching engine, not smart order routing. Those need
an order book, a venue and a fill feed, none of which exist here, and porting
them would mean validating a model against synthetic data. This is one thing:
a **stated, pre-registered haircut** so that "gross" and "net" are two numbers
on the page instead of one number and a silence.

It lives at the package root, beside `sessions` and `instruments`, for the
reason those two do: several packages need it and it needs almost nothing.

Where the estimates come from
-----------------------------
* **Commission** is an assumption, not a measurement. Nothing in this repository
  observes a broker invoice, so the rate lives in `config/cost-model.json`,
  travels into every run card, and is labelled `assumed_` wherever it is
  published. Replace it with the real schedule and every downstream number
  moves with it.
* **Spread** defaults to a configured fixed rate per leg, and that default is a
  measurement rather than a preference. `market_data.bar_signals` already ships
  Corwin & Schultz (2012) and Roll (1984) — added for #1172, where they are
  scored as *signals* — and the obvious move was to reuse them here as a cost.
  Measured over the 27 tickers in the canonical bar manifest, thirty sessions
  each, Corwin-Schultz puts the **half**-spread at a median of **163 bps**, range
  27 to 393 (00100: 359, RKLX: 393). Real spreads on these names are single- to
  low-double-digit bps. At daily frequency the estimator attributes overnight
  gaps and intraday volatility to the spread, and the names it overestimates
  most are exactly the volatile ones the book trades. A net curve haircut by two
  hundred basis points a trade is a fiction in the other direction from zero, so
  `spread_source` defaults to `fixed`; `corwin_schultz` and `roll` stay
  selectable, and whichever ran is recorded on every trade. A marketable order
  crossing the quote pays about half the spread, so `spread_share` defaults to
  0.5 and is a knob.
* **Impact is off, deliberately.** Amihud's illiquidity is |return| per unit of
  dollar volume; turning it into a cost needs an order size *and* a calibration
  constant, and this book has neither. A number produced from an uncalibrated
  constant is invented, and an invented haircut is worse than a stated absence:
  it would make the net curve look rigorous while being arbitrary. `off` is
  published in the assumptions block so the omission is visible.

Both estimators return `None` rather than zero when their model does not
describe the day — Roll when the covariance comes out positive, Corwin-Schultz
when every window is negative — because zero is the *most liquid* value in the
cross-section and handing it to the names the model failed on is the one error
that flatters the result. Those days fall back to the configured fixed spread,
and every trade carries which source it actually used.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root(Path.cwd())
CONFIG = WS / 'config' / 'cost-model.json'

#: Half the quoted spread: what an order that crosses the touch pays, relative
#: to the mid. A resting order pays less and a sweeping one more; the shadow
#: book models neither, so half is the neutral assumption and it is a knob.
DEFAULT_SPREAD_SHARE = 0.5


@dataclass(frozen=True)
class CostModel:
    """A pre-registered cost assumption. Every field reaches the run card."""

    assumed_commission_bps: dict = field(default_factory=dict)
    assumed_minimum_commission: dict = field(default_factory=dict)
    spread_source: str = 'fixed'
    spread_bps_by_leg: dict = field(default_factory=dict)
    spread_share: float = DEFAULT_SPREAD_SHARE
    impact_source: str = 'off'
    registered_on: str | None = None

    @classmethod
    def load(cls, path: Path | None = None) -> 'CostModel':
        raw = json.loads(Path(path or CONFIG).read_text(encoding='utf-8'))
        return cls(
            assumed_commission_bps=dict(raw.get('assumed_commission_bps') or {}),
            assumed_minimum_commission=dict(
                raw.get('assumed_minimum_commission') or {}),
            spread_source=str(raw.get('spread_source') or 'fixed'),
            spread_bps_by_leg=dict(raw.get('spread_bps') or {}),
            spread_share=float(raw.get('spread_share', DEFAULT_SPREAD_SHARE)),
            impact_source=str(raw.get('impact_source') or 'off'),
            registered_on=raw.get('registered_on'),
        )

    @classmethod
    def free(cls) -> 'CostModel':
        """Every component zero. `net` must then equal `gross` exactly."""
        return cls(spread_source='off', spread_share=0.0, impact_source='off')

    def as_dict(self) -> dict:
        return {
            'assumed_commission_bps': dict(self.assumed_commission_bps),
            'assumed_minimum_commission': dict(self.assumed_minimum_commission),
            'spread_source': self.spread_source,
            'spread_bps': dict(self.spread_bps_by_leg),
            'spread_share': self.spread_share,
            'impact_source': self.impact_source,
            'registered_on': self.registered_on,
            'basis': ('commission is an assumption, not an observation; the '
                      'spread default is a configured rate because the bar-derived '
                      'estimators were measured at a median 163 bps half-spread '
                      'and do not survive it; impact is off because nothing here '
                      'calibrates it'),
        }


def _series(bars_by_date) -> tuple[list, dict]:
    """(bars in date order, date -> index). The estimators want positions."""
    ordered = sorted((bars_by_date or {}).items())
    rows = [dict(bar, date=date) for date, bar in ordered]
    return rows, {date: index for index, (date, _) in enumerate(ordered)}


def spread_bps(bars_by_date, date: str, model: CostModel, leg: str) -> tuple[float, str]:
    """(half-spread in bps, the source that produced it).

    Returns the *configured share* of the estimated spread, so the caller never
    has to remember whether the number is a full spread or what an order pays.
    """
    # Legs arrive as `US`/`HK` from the ledger and as `us`/`hk` from the config.
    # Normalising here rather than at each call site: the first version of this
    # looked up `US` in a table keyed `us`, found nothing, and charged every
    # trade exactly zero — a cost model that silently priced nothing.
    leg = str(leg or '').lower()
    fallback = float((model.spread_bps_by_leg or {}).get(leg, 0.0))
    if model.spread_source == 'off':
        return 0.0, 'off'
    # Imported here, not at module scope. This module sits at the package root
    # beside `sessions` and `instruments` because both `decision.shadow` and the
    # evaluation path price trades with it, and `evaluation` already imports
    # `decision`: a module-level `market_data` import would have made
    # decision <-> evaluation a package cycle, and `test_import_layering`
    # allows none. The estimators are also off the default path.
    from clawock.market_data import bar_signals

    rows, index_of = _series(bars_by_date)
    index = index_of.get(date)
    estimate = None
    if index is not None:
        if model.spread_source == 'corwin_schultz':
            estimate = bar_signals.corwin_schultz_spread(rows, index)
        elif model.spread_source == 'roll':
            estimate = bar_signals.roll_spread(rows, index)
        elif model.spread_source == 'fixed':
            estimate = None
    if estimate is None:
        # The estimator declined — the model did not describe that day. Zero is
        # the most liquid value in the cross-section and would be handed to
        # exactly the names it failed on, so the fallback is the configured
        # fixed spread, and the source says which one was used.
        return fallback * model.spread_share, (
            'fixed' if model.spread_source == 'fixed' else 'fixed_fallback')
    # The estimators report a spread in percent of price.
    return estimate * 100 * model.spread_share, model.spread_source


def trade_cost(notional: float, leg: str, date: str, bars_by_date,
               model: CostModel) -> dict:
    """What one filled leg costs, in the leg's own currency.

    Currency is never converted: `shadow` keeps HK and US books apart for the
    same reason, and adding HKD to USD is the one arithmetic this repository
    refuses.
    """
    leg = str(leg or '').lower()
    notional = abs(float(notional or 0.0))
    if notional <= 0:
        return {'commission': 0.0, 'spread': 0.0, 'total': 0.0, 'bps': 0.0,
                'spread_source': 'no_fill'}
    rate = float((model.assumed_commission_bps or {}).get(leg, 0.0))
    minimum = float((model.assumed_minimum_commission or {}).get(leg, 0.0))
    commission = max(notional * rate / 10_000, minimum) if (rate or minimum) else 0.0
    half, source = spread_bps(bars_by_date, date, model, leg)
    spread = notional * half / 10_000
    total = commission + spread
    return {
        'commission': round(commission, 6),
        'spread': round(spread, 6),
        'total': round(total, 6),
        'bps': round(10_000 * total / notional, 4),
        'spread_source': source,
    }

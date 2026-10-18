"""Shared sized-fill costs: account facts, sourced tariffs and explicit assumptions.

The default is a current-tariff counterfactual, not a historical invoice. The
user-reported commission waiver is conditional on unused monthly allowance.
Frozen older CostModel dictionaries retain their original assumptions and no
new fee schedule is silently injected into old trials. Spread and impact are
still assumptions; uncalibrated impact remains off.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP
import math
from pathlib import Path

from clawock.workspace import workspace_root

WS = workspace_root()
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
    account_commission: dict = field(default_factory=dict)
    regulatory_fees: dict = field(default_factory=dict)
    stamp_duty_exemptions: dict = field(default_factory=dict)
    assumed_reference_notional: dict = field(default_factory=dict)
    assumed_reference_share_price: dict = field(default_factory=dict)

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
            **{key: dict(raw.get(key) or {}) for key in (
                'account_commission', 'regulatory_fees', 'stamp_duty_exemptions',
                'assumed_reference_notional', 'assumed_reference_share_price')},
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
            'account_commission': dict(self.account_commission),
            'regulatory_fees': dict(self.regulatory_fees),
            'stamp_duty_exemptions': dict(self.stamp_duty_exemptions),
            'assumed_reference_notional': dict(self.assumed_reference_notional),
            'assumed_reference_share_price': dict(self.assumed_reference_share_price),
            'basis': ('account_commission is user-reported fact, conditional on monthly '
                      'allowance; regulatory_fees is a sourced current-tariff counterfactual; '
                      'assumed_* fields and spread are assumptions, not an observation; '
                      'impact is off because nothing here calibrates it'),
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


def commission_terms(model: CostModel, leg: str) -> tuple[float, float]:
    """Current account scenario, or legacy assumptions for frozen models."""
    account = model.account_commission
    if account:
        if leg not in account.get('markets', []):
            raise ValueError(f'account commission does not cover market {leg!r}')
        if account.get('scenario') != 'within_monthly_allowance':
            raise ValueError('commission outside the observed allowance is unknown')
        return (float(account['commission_bps'][leg]),
                float(account['minimum_commission'][leg]))
    return (float(model.assumed_commission_bps.get(leg, 0)),
            float(model.assumed_minimum_commission.get(leg, 0)))


def _rounded_fee(amount, *, whole=False, up=False):
    return float(Decimal(str(amount)).quantize(
        Decimal('1') if whole else Decimal('0.01'),
        rounding=ROUND_CEILING if up or whole else ROUND_HALF_UP))


def _regulatory_cost(notional, leg, model, *, direction, ticker, shares):
    schedule = model.regulatory_fees.get(leg, {})
    charges = {}
    if leg == 'hk':
        # Only explicit verified identities qualify; no ETF inference from a prefix.
        code = str(ticker or '').removeprefix('hk').removesuffix('.HK').zfill(5)
        exempt = code in model.stamp_duty_exemptions.get('tickers', {})
        for key, spec in schedule.items():
            amount = notional * spec['bps'] / 10000
            if key == 'stamp_duty' and exempt:
                amount = 0.0
            amount = max(amount, spec.get('minimum', 0))
            if spec.get('maximum') is not None:
                amount = min(amount, spec['maximum'])
            charges[key] = _rounded_fee(amount, whole=key == 'stamp_duty')
        return charges, {'stamp_duty_status': 'verified_exempt' if exempt else 'taxable_or_unknown'}
    if leg == 'us' and direction != 'buy':
        # Unknown direction is conservatively a sale, never a free regulatory leg.
        if 'sec' in schedule:
            charges['sec'] = _rounded_fee(notional * schedule['sec']['bps'] / 10000, up=True)
        share_basis = 'filled_shares'
        if 'taf' in schedule:
            if shares is None:
                price = model.assumed_reference_share_price.get('us')
                if not price or price <= 0:
                    raise ValueError('US regulatory fee needs shares or an explicit reference price')
                shares, share_basis = notional / price, 'assumed_reference_share_price'
            if isinstance(shares, bool) or not math.isfinite(shares) or shares <= 0:
                raise ValueError('shares must be positive and finite')
            spec = schedule['taf']
            amount = min(shares * spec['per_share'], spec['maximum'])
            # FINRA excludes executions priced below the per-share TAF rate.
            charges['taf'] = 0.0 if notional / shares < spec['per_share'] else _rounded_fee(amount, up=True)
        return charges, {'share_basis': share_basis,
                         'direction_basis': direction or 'unknown_charged_as_sell'}
    return charges, {}


def trade_cost(notional: float, leg: str, date: str, bars_by_date,
               model: CostModel, *, direction: str | None = None,
               ticker: str | None = None, shares: float | None = None) -> dict:
    """One fill in local currency; no FX conversion or allowance consumption.

    `date` selects spread observations. Regulatory rates are the model's dated
    snapshot, explicitly applied counterfactually even to older fills.
    """
    leg = str(leg or '').lower()
    if direction not in (None, 'buy', 'sell'):
        raise ValueError('direction must be buy, sell or unknown')
    if isinstance(notional, bool) or not math.isfinite(float(notional)):
        raise ValueError('notional must be finite')
    notional = abs(float(notional))
    if notional <= 0:
        return {'commission': 0.0, 'spread': 0.0, 'total': 0.0, 'bps': 0.0,
                'spread_source': 'no_fill'}
    rate, minimum = commission_terms(model, leg)
    commission = max(notional * rate / 10000, minimum)
    half, source = spread_bps(bars_by_date, date, model, leg)
    spread = notional * half / 10000
    regulatory, detail = _regulatory_cost(notional, leg, model, direction=direction,
                                          ticker=ticker, shares=shares)
    total = commission + spread + sum(regulatory.values())
    result = {'commission': round(commission, 6), 'spread': round(spread, 6),
              'total': round(total, 6), 'bps': round(10000 * total / notional, 4),
              'spread_source': source}
    if model.regulatory_fees or model.account_commission:
        result.update(regulatory=regulatory, regulatory_total=round(sum(regulatory.values()), 6),
                      fee_detail=detail, tariff_as_of=model.regulatory_fees.get('as_of'),
                      commission_scenario=model.account_commission.get('scenario', 'legacy_assumptions'),
                      allowance_usage_verified=model.account_commission.get('usage_verified', False))
    return result

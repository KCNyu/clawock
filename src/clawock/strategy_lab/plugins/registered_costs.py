"""The `costs` service: the registered cost model, per side, in basis points.

The assumptions are `config/cost-model.json`, the ones `decision.shadow` and
`decision.method_evaluation` already price fills with; this plugin reads them
through `clawock.costs.CostModel` and adds no second schedule. A row may set
`free: true` to mount the zero-cost model, under which net equals gross.

The minimum commission is not applied: it is a currency amount per order, and a
rank portfolio has weights but no order size.
"""
from __future__ import annotations

from clawock.costs import CostModel

name = 'registered-costs'


class Costs:
    def __init__(self, model: CostModel):
        self.model = model

    def side_bps(self, leg: str) -> float:
        """Commission plus the share of the spread a crossing order pays."""
        leg = str(leg or '').lower()
        model = self.model
        spread = 0.0 if model.spread_source == 'off' else (
            float((model.spread_bps_by_leg or {}).get(leg, 0.0)) * model.spread_share)
        return float((model.assumed_commission_bps or {}).get(leg, 0.0)) + spread

    def describe(self) -> dict:
        return {**self.model.as_dict(),
                'minimum_commission_applied': False,
                'side_bps': {leg: self.side_bps(leg) for leg in ('hk', 'us')}}


def apply(ctx, config):
    ctx.provide('costs', Costs(CostModel.free() if config.get('free') else CostModel.load()))

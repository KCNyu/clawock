"""The `costs` service: the registered cost model, per side, in basis points.

The assumptions are `config/cost-model.json`, the ones `decision.shadow` and
`decision.method_evaluation` already price fills with; this plugin reads them
through `clawock.costs.CostModel` and adds no second schedule. A row may set
`free: true` to mount the zero-cost model, under which net equals gross.

Ranks use explicitly assumed reference tickets; sized fills use their own notional.
"""
from __future__ import annotations

from clawock.costs import CostModel, trade_cost

name = 'registered-costs'


class Costs:
    def __init__(self, model: CostModel):
        self.model = model

    def side_bps(self, leg: str, ticker: str | None = None) -> float:
        """Conservative side on an explicit reference ticket for unsized ranks."""
        leg = str(leg or '').lower()
        notional = self.model.assumed_reference_notional.get(leg, 10000)
        return max(self.fill(notional, leg, '', direction=side, ticker=ticker)['bps']
                   for side in ('buy', 'sell'))

    def fill(self, notional: float, leg: str, session: str, **kwargs) -> dict:
        """Sized fill, including minimum commissions, tax and regulatory fees."""
        return trade_cost(notional, leg, session, {}, self.model, **kwargs)

    def describe(self) -> dict:
        return {**self.model.as_dict(),
                'minimum_commission_applied': True,
                'rank_cost_basis': 'reference ticket; larger of buy/sell costs; not sized execution',
                'side_bps': {leg: self.side_bps(leg) for leg in ('hk', 'us')}}


def apply(ctx, config):
    ctx.provide('costs', Costs(CostModel.free() if config.get('free') else CostModel.load()))

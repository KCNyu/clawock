"""The `strategies` service: what a strategy plugin registers, and where.

A strategy is a pure function from the bars known at a session to one number,
plus the parameters it was registered with and the grid an optimiser may search.
It holds no data source and no evaluator; those are other plugins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from clawock.plugin_host.kernel import KernelError

name = 'strategies'


@dataclass(frozen=True)
class StrategySpec:
    name: str
    #: The registered parameters: what the strategy runs with today.
    params: dict
    #: {parameter: candidate values}. The whole search an optimiser may run,
    #: declared before it runs so the trial count is known rather than recalled.
    space: dict
    #: `score(bars, params) -> float | None`. `bars` is the history up to and
    #: including the signal session, oldest first; higher means more bullish.
    #: The evaluator slices the history, so a strategy cannot see past its
    #: session however it is written.
    score: Callable = field(compare=False)
    description: str = ''


class Strategies:
    def __init__(self):
        self._specs: dict[str, StrategySpec] = {}

    def register(self, spec: StrategySpec):
        if spec.name in self._specs:
            raise KernelError(f'strategy {spec.name!r} is already registered')
        self._specs[spec.name] = spec
        return lambda: self._specs.pop(spec.name, None)

    def get(self, strategy: str) -> StrategySpec:
        if strategy not in self._specs:
            raise KeyError(
                f'no mounted strategy {strategy!r}; mounted: {sorted(self._specs)}')
        return self._specs[strategy]

    def names(self) -> list[str]:
        return sorted(self._specs)


def apply(ctx, config):
    ctx.provide('strategies', Strategies())

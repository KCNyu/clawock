"""Liquidity and volatility estimators from daily bars.

The implementation is the `bar_signals` plugin
(`clawock.strategies.plugins.bar_signals`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'bar_signals')

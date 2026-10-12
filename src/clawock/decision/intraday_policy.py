"""Per-strategy intraday policies.

The implementation is the `intraday_policy` plugin
(`clawock.strategies.plugins.intraday_policy`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'intraday_policy')

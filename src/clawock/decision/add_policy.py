"""Add-side sizing and tiers.

The implementation is the `add_policy` plugin
(`clawock.strategies.plugins.add_policy`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names. The code that lived here before the move is
`decision.legacy_add_policy`, read only by
`tests/test_migrated_plugins_equivalence.py`.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'add_policy')

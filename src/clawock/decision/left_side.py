"""The left-side ladder (observe mode).

The implementation is the `left_side` plugin
(`clawock.strategies.plugins.left_side`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'left_side')

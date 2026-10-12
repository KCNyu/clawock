"""The cross-sectional signal panel.

The implementation is the `signal_panel` plugin
(`clawock.strategy_lab.plugins.signal_panel`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'signal_panel')

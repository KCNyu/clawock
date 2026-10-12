"""The add-side radar and its three-state reads.

The implementation is the `add_side` plugin
(`clawock.strategies.plugins.add_side`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'add_side')

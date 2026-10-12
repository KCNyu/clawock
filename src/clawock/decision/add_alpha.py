"""Add authority and the confirmation setup.

The implementation is the `add_alpha` plugin
(`clawock.strategies.plugins.add_alpha`), mounted by the `live` rows of
`config/strategy-plugins.json`. This module keeps the import path its readers
use and is a view of the mounted service (`plugin_host.facade`), so what they
run is whatever the row names.
"""
from clawock.plugin_host import facade

facade.install(__name__, 'add_alpha')

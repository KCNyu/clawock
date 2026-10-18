"""Explicit research-kernel facade; deliberately never consults the live host."""


def replay(kernel, packet):
    """Delegate to whichever implementation the supplied research row mounted."""
    return kernel.get('intraday_reversion').replay(packet)


def replay_service(kernel, service, packet, params=None):
    """Explicit research service dispatch; never install on the live kernel."""
    if service not in ('intraday_reversion', 'intraday_vwap', 'intraday_breakout'):
        raise ValueError('unknown intraday research service')
    plugin = kernel.get(service)
    return (plugin.configured(params) if params is not None else plugin).replay(packet)

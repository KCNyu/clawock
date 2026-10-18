"""Explicit research-kernel facade; deliberately never consults the live host."""


def replay(kernel, packet):
    """Delegate to whichever implementation the supplied research row mounted."""
    return kernel.get('intraday_reversion').replay(packet)

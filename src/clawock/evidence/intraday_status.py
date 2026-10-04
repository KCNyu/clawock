"""The shared narrative-only intraday status sidecar contract."""
BANNER_LIMIT = 160
MOVER_LIMIT = 120


def normalize_status(data):
    if not isinstance(data, dict) or not isinstance(data.get('status_banner'), str):
        raise ValueError('status_banner must be text')
    movers = data.get('movers')
    if not isinstance(movers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                          for k, v in movers.items()):
        raise ValueError('movers must map tickers to text')
    return {'status_banner': data['status_banner'].strip()[:BANNER_LIMIT],
            'movers': {k.strip()[:12]: v.strip()[:MOVER_LIMIT] for k, v in movers.items()
                       if k.strip() and v.strip()}}

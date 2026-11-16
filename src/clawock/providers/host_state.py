"""Host-wide state paths shared across workspace checkouts."""
import os
from pathlib import Path


def delivery_state_dir(environ=None):
    """Resolve delivery dedupe storage; an explicitly empty override disables it.

    Preserve the historical host default so an upgrade keeps existing claims.
    This state belongs to clawock, independently of the selected runtime.
    """
    env = os.environ if environ is None else environ
    configured = env.get('CLAWOCK_DELIVERY_STATE_DIR')
    if configured is not None:
        return Path(configured) if configured.strip() else None
    home = Path(env['HOME']) if env.get('HOME') else Path.home()
    return home / '.local' / 'state' / 'clawock' / 'delivery'

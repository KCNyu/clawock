from pathlib import Path
from clawock.providers.host_state import delivery_state_dir


def test_delivery_state_override_and_disable():
    assert delivery_state_dir({'CLAWOCK_DELIVERY_STATE_DIR': '/state'}) == Path('/state')
    assert delivery_state_dir({'CLAWOCK_DELIVERY_STATE_DIR': ' '}) is None
    assert delivery_state_dir({'HOME': '/tenant'}) == Path('/tenant/.local/state/clawock/delivery')

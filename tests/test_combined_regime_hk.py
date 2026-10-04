"""The combined-book evaluation must use the shipped HK tier, including cash."""
import pytest
from clawock.decision import regime
from clawock.evaluation import combined_regime


@pytest.mark.parametrize('close,ma,vol,expected', [
    (110, 100, 0.1, 2), (110, 100, 0.9, 1),
    (90, 100, 0.1, 1), (90, 100, 0.9, 0),
    (90, None, None, 0), (110, 100, None, 1),
])
def test_hk_evaluation_matches_production(close, ma, vol, expected):
    actual = combined_regime.hk_effective_leverage(close, ma, vol)
    assert actual == expected == 2 * regime.classify(close, ma, vol)[3]

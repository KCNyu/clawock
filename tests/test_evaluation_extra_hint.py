"""A command that needs an extra says which one (#2547).

The two charting backtests import matplotlib at call time so a base install can
still import the package. Without the `evaluation` extra they died on a bare
ModuleNotFoundError, and no help text or doc named the selector.
"""
import sys

import pytest

from clawock.evaluation import combined_regime, us_leverage


@pytest.mark.parametrize("module, command", [
    (us_leverage, "evaluate-us-leverage"),
    (combined_regime, "evaluate-combined-regime"),
])
def test_a_missing_charting_extra_names_its_selector(monkeypatch, module, command):
    monkeypatch.setitem(sys.modules, "matplotlib", None)   # import raises ImportError

    with pytest.raises(SystemExit) as stopped:
        module._plotting()

    assert f"clawock {command}" in str(stopped.value)
    assert "pip install 'clawock[evaluation]'" in str(stopped.value)
    assert "clawock[evaluation]" in module.__doc__

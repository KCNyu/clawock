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


@pytest.mark.parametrize("name", ["gif", "screenshots"])
def test_a_missing_imaging_extra_is_not_reported_as_a_broken_artifact(monkeypatch, capsys, tmp_path, name):
    # The generic handler turned the missing Pillow into `ASSERTION FAILED: GIF …` (#2567).
    from clawock.publish import artifacts

    def needs_pillow(_name):
        from PIL import Image  # noqa: F401

    monkeypatch.setitem(sys.modules, "PIL", None)
    monkeypatch.setattr(artifacts, "_dispatch", needs_pillow)

    assert artifacts.main([name]) == 1
    printed = capsys.readouterr().err
    assert f"clawock validate-sidecar {name}" in printed
    assert "pip install 'clawock[imaging]'" in printed
    assert "ASSERTION FAILED" not in printed

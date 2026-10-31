"""Standalone console entrypoints must parse help before any pipeline work."""
import importlib
import sys
import tomllib
from pathlib import Path

import pytest


COMMANDS = ["clawock-gold-fetch", "clawock-influencer-scan",
            "clawock-news-digest", "clawock-brief-fallback"]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("flag", ["--help", "-h", "--unknown-flag"])
def test_console_script_parses_before_network_or_workspace(monkeypatch, tmp_path, capsys, command, flag):
    scripts = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["scripts"]
    module, function = scripts[command].split(":")
    monkeypatch.setenv("CLAWOCK_WORKSPACE", str(tmp_path))
    entry = importlib.import_module(module)
    def forbidden(*args, **kwargs):
        pytest.fail("help/invalid arguments reached pipeline I/O")
    import requests
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(sys, "argv", [command, flag])
    with pytest.raises(SystemExit) as exit:
        getattr(entry, function)()
    assert exit.value.code == (2 if flag == "--unknown-flag" else 0)
    output = capsys.readouterr()
    assert "usage:" in output.out + output.err
    assert not list(tmp_path.iterdir())

"""The claim the README makes: point clawock at someone else's book (#356).

`workspace_root()` has been overridable since #246, and #269 stopped every code
import resolving through the workspace. Neither made this true. `config/` was
still read from the workspace wholesale, and two modules loaded their config at
IMPORT time, so a foreign book killed brief/report/intraday preflight before any
of them reached a single argument.

The split this pins:

* **schemas ship with the engine** — they describe the format, so asking each
  book to vendor a copy of our validation rules is asking the wrong thing;
* **book data stays in the workspace, and absence is not corruption** — a
  workspace that has registered no instruments is every book but this one, while
  malformed JSON still raises, because degrading there would let numbers be
  published against metadata nobody validated.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CLIS = ("brief_preflight", "report_preflight", "intraday_preflight",
        "brief_postflight", "report_postflight", "intraday_postflight")


@pytest.fixture
def foreign_book(tmp_path):
    """A workspace with data and no config, code, or history — a new user."""
    book = tmp_path / "someone-elses-book"
    (book / "memory" / ".tmp").mkdir(parents=True)
    (book / "assets" / "data").mkdir(parents=True)
    (book / "portfolio.json").write_text(json.dumps({"portfolios": {
        "us_stocks": {"currency": "USD", "holdings": []},
        "hk_stocks": {"currency": "HKD", "holdings": []}}}), encoding="utf-8")
    assert not (book / "config").exists(), "the point is that config is absent"
    return book


@pytest.mark.parametrize("cli", CLIS)
def test_every_harness_cli_starts_against_a_foreign_book(cli, foreign_book):
    """--help is the cheapest proof the module got through import.

    Import is where this failed: both instrument_registry and entry_gate read
    their config at module scope, so the failure landed before argparse and took
    every consumer with it.
    """
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "harness" / f"{cli}.py"), "--help"],
        capture_output=True, text=True, timeout=90, cwd=str(ROOT),
        env=dict(os.environ, CLAWOCK_WORKSPACE=str(foreign_book)),
    )
    assert done.returncode == 0, (
        f"{cli} cannot start against a workspace that is not this repository:\n"
        f"{done.stdout[-500:]}\n{done.stderr[-1500:]}")


def test_an_absent_registry_is_empty_but_a_broken_one_still_raises(tmp_path):
    sys.path[:0] = [str(ROOT / "scripts" / "data"), str(ROOT)]
    import instrument_registry as registry

    assert registry.load_registry(tmp_path / "nope.json", missing_ok=True) == {}

    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot read instrument registry"):
        registry.load_registry(broken, missing_ok=True)


def test_schemas_come_from_the_engine_not_the_book(foreign_book):
    """A book must not have to carry our validation rules to be validated.

    Asserted in a subprocess WITH the override set, because in this one the
    workspace is the checkout: `SCHEMA_FILE == engine_config(...)` is vacuously
    true whenever the two roots coincide, which is every run on the live box.
    That is the exact confusion this issue exists to end, so a test that can
    only see it when they already agree proves nothing.
    """
    probe = (
        "import sys; sys.path[:0] = [%r, %r]\n"
        "import instrument_registry as r\n"
        "print(r.SCHEMA_FILE)\n"
        "print(r.REGISTRY_FILE)\n"
    ) % (str(ROOT / "scripts" / "data"), str(ROOT))
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), env=dict(os.environ, CLAWOCK_WORKSPACE=str(foreign_book)))
    assert done.returncode == 0, done.stderr
    schema, registry_file = done.stdout.strip().splitlines()

    assert schema.startswith(str(ROOT)), (
        f"the schema followed the workspace override to {schema}; it describes "
        "the format and must ship with the engine")
    assert registry_file.startswith(str(foreign_book)), (
        f"the registry did NOT follow the override ({registry_file}); the book's "
        "own instruments must come from the book")

"""The catalog the README calls "full" has to be the whole installation.

`docs/reference/commands.md` was hand-maintained, so a command could be added,
renamed or removed without it noticing, and the README linked it as the full
command and provider catalog anyway (#489). Its inventory is now rendered by
`ops/ci/generate_tool_reference.py` from the two script registries and the
classification in `config/information-layers.json`.

These tests check the three properties that make that worth anything:

1. the committed document is what the generator produces right now;
2. every command either distribution installs is in it, once, read back out of
   the markdown rather than out of the renderer;
3. the generator fails on a command it cannot classify instead of quietly
   shipping a catalog that omits it.

The third is the one that keeps this from being decorative. A generated
document that silently skips what it does not recognise is a hand-maintained
document with extra steps: #453 found gates that passed by discovering nothing,
so a generator gets the same treatment — it is asked, here, to react.

What these do not check is the prose after the generated block. Flag tables,
SEC's rate limit and which key a provider needs are hand-written on purpose;
no registry holds them.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ops" / "ci"))

from generate_tool_reference import (  # noqa: E402
    BEGIN,
    END,
    INSTANCE,
    PUBLIC,
    build,
    registries,
    render,
)

DOCUMENT = ROOT / "docs" / "reference" / "commands.md"
CONFIG = json.loads((ROOT / "config" / "information-layers.json").read_text())


def _generated_block(markdown):
    return markdown.split(BEGIN, 1)[1].split(END, 1)[0]


def _commands_in(markdown):
    """The commands the document actually names, as an operator would type them."""
    return re.findall(r"^\| `([^`]+)` \|", _generated_block(markdown), re.M)


def _key(invocation):
    """`clawock foo` → (clawock, foo); `clawock-kcnyu-foo` → (clawock-kcnyu, ...)."""
    if invocation.startswith("clawock "):
        return (PUBLIC, invocation.split(" ", 1)[1])
    return (INSTANCE, invocation)


def test_the_committed_inventory_is_what_the_generator_produces():
    """The drift gate. Everything else here is about a document that is current."""
    current = DOCUMENT.read_text()

    assert current == build(current, CONFIG, registries()), (
        "docs/reference/commands.md is stale; run "
        "ops/ci/generate_tool_reference.py")


def test_every_installed_command_is_named_exactly_once():
    """Read back out of the markdown, not out of the renderer.

    Comparing the renderer against itself would pass while the committed file
    said something else entirely.
    """
    available = registries()
    assert len(available[PUBLIC]) > 40, "the public registry shrank — check the parse"
    assert len(available[INSTANCE]) > 8, "the instance registry shrank — check the parse"

    named = [_key(invocation) for invocation in _commands_in(DOCUMENT.read_text())]

    duplicates = {key for key in named if named.count(key) > 1}
    assert not duplicates, f"listed twice in the catalog: {sorted(duplicates)}"

    installed = {(distribution, command)
                 for distribution, registry in available.items()
                 for command in registry}
    assert set(named) == installed, (
        "the catalog and the installation disagree: "
        f"missing {sorted(installed - set(named))}, "
        f"invented {sorted(set(named) - installed)}")


def test_the_document_names_the_module_behind_each_command():
    """A name that resolves is what survived #429 moving every module."""
    block = _generated_block(DOCUMENT.read_text())
    available = registries()

    for distribution, registry in available.items():
        for command, target in registry.items():
            module = target.split(":")[0]
            assert f"| `{module}` |" in block, (
                f"{command} is listed without the module it dispatches to")


def _fake(command="brand-new-command", note="a command nobody has classified"):
    available = registries()
    available[PUBLIC] = {**available[PUBLIC], command: "clawock.market_data.macro"}
    config = json.loads(json.dumps(CONFIG))
    return command, note, config, available


def test_a_new_command_appears_without_anyone_editing_the_document():
    """The property the hand-maintained version did not have."""
    command, note, config, available = _fake()
    config["layers"][0]["modules"].append({"command": command, "note": note})

    output = render(config, available)

    assert f"`clawock {command}`" in output and note in output


def test_an_unclassified_command_stops_the_generator():
    """Not a warning. A catalog that omits what it did not recognise is exactly
    the failure this replaced, so the generator refuses to write one."""
    command, _, config, available = _fake()

    with pytest.raises(SystemExit) as raised:
        render(config, available)

    assert command in str(raised.value)


def test_a_taxonomy_entry_for_a_command_nobody_installs_stops_the_generator():
    """The other direction: a deleted command cannot linger in the catalog."""
    config = json.loads(json.dumps(CONFIG))
    config["layers"][0]["modules"].append(
        {"command": "deleted-last-year", "note": "gone"})

    with pytest.raises(SystemExit) as raised:
        render(config, registries())

    assert "deleted-last-year" in str(raised.value)


def test_the_hand_written_half_is_left_alone():
    """The detail a registry cannot hold has to survive regeneration."""
    document = DOCUMENT.read_text()
    head, rest = document.split(BEGIN, 1)
    tail = rest.split(END, 1)[1]

    assert "SEC" in tail and "--financials" in tail, (
        "the hand-written per-command detail is gone, not kept alongside")

    rebuilt = build(head + BEGIN + "stale\n" + END + tail, CONFIG, registries())

    assert rebuilt.startswith(head) and rebuilt.endswith(tail)


def test_both_readmes_link_the_catalog_they_call_full():
    for readme in ("README.md", "README.zh.md"):
        text = (ROOT / readme).read_text()
        assert "docs/reference/commands.md" in text, f"{readme} lost the catalog link"
        assert "docs/reference/scripts.md" not in text, (
            f"{readme} still links the page named after the deleted scripts/ directory")

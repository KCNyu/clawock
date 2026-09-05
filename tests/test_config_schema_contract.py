"""The five shipped JSON schemas must agree with the Python that validates.

`src/clawock/config/*.schema.json` is the published shape of every artifact
clawock reads: `$id: urn:clawock:schema:...` is what an integrator is told to
build against. None of it is loaded at runtime. `SCHEMA_FILE` is assigned in
four modules (`instruments.py:21`, `decision/earnings.py:35`,
`decision/theses.py:14`, `decision/entry.py:32`) and never read; validation is
hand-written Python, and `profile.schema.json` is not even named by a constant.

So nothing made the two halves agree, and they stopped agreeing. #1049 deleted
the profile-level `templates` surface from `config/profiles.py` and from both
shipped profiles, but left `templates` (required) and `workflows.*.template` in
`profile.schema.json`. The result was a contract that contradicted the loader in
both directions: the two profiles this repository ships fail their own published
schema for a missing `templates`, and a profile written to satisfy that schema
is rejected by `load_profile` with `unknown fields: ['templates']`. That drift
survived from #1049 to 2026-09-05 because no run of anything read the file.

This module is what reads it. Each entry below pins one object in a schema to
the Python that decides the same field set, so a one-sided edit is red rather
than invisible. It deliberately does not re-implement JSON Schema semantics
(that would be the second implementation this file exists to prevent); it
compares field vocabularies, which is the axis #1049 drifted on.
"""

import json
from pathlib import Path

import pytest

from clawock import instruments
from clawock.config import profiles
from clawock.decision import earnings, entry, theses

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "src" / "clawock" / "config"


def _schema(name):
    return json.loads((CONFIG / name).read_text())


def _at(doc, pointer):
    """Resolve a slash-separated path of literal keys ('' is the document)."""
    node = doc
    for step in [s for s in pointer.split("/") if s]:
        node = node[step]
    return node


# (schema file, pointer to the object, expected field set, expected required set)
# `required is None` means "every declared property is required", which is what
# every object in these five schemas asserts today.
CONTRACTS = [
    ("profile.schema.json", "", profiles._TOP_LEVEL, None),
    ("profile.schema.json", "properties/markets/additionalProperties",
     profiles._MARKET_FIELDS, {"timezone", "label", "analysis_command"}),
    ("profile.schema.json", "properties/workflows/additionalProperties",
     profiles._WORKFLOW_FIELDS, {"enabled", "markets"}),
    ("profile.schema.json", "properties/delivery",
     profiles._DELIVERY_FIELDS, None),
    ("profile.schema.json",
     "properties/delivery/properties/targets/additionalProperties",
     profiles._TARGET_FIELDS, {"source"}),
    ("thesis.schema.json", "", theses.THESIS_FIELDS, None),
    ("entry_gate.schema.json", "", entry.ARTIFACT_FIELDS, None),
    ("entry_gate.schema.json", "properties/information",
     set(entry.grade_information([])), None),
    ("earnings_review.schema.json", "", earnings.ARTIFACT_FIELDS, None),
    ("instruments.schema.json", "$defs/instrument",
     instruments.REQUIRED_FIELDS, None),
]


@pytest.mark.parametrize(
    "schema_file,pointer,fields,required",
    CONTRACTS,
    ids=[f"{s}:{p or '<root>'}" for s, p, _f, _r in CONTRACTS],
)
def test_schema_object_matches_its_python_validator(
    schema_file, pointer, fields, required
):
    node = _at(_schema(schema_file), pointer)
    assert set(node["properties"]) == set(fields), (
        f"{schema_file}#{pointer or '/'} declares a different field set than the "
        f"Python that validates it; schema-only="
        f"{sorted(set(node['properties']) - set(fields))}, "
        f"python-only={sorted(set(fields) - set(node['properties']))}"
    )
    expected_required = set(node["properties"]) if required is None else set(required)
    assert set(node["required"]) == expected_required
    # `additionalProperties: false` is what makes the field set a contract at
    # all: without it the schema accepts fields the Python loader rejects, and
    # the comparison above proves nothing.
    assert node.get("additionalProperties") is False


@pytest.mark.parametrize(
    "module,schema_file",
    [
        (theses, "thesis.schema.json"),
        (entry, "entry_gate.schema.json"),
        (earnings, "earnings_review.schema.json"),
        (instruments, "instruments.schema.json"),
    ],
    ids=["thesis", "entry_gate", "earnings_review", "instruments"],
)
def test_schema_version_matches_the_module(module, schema_file):
    # SCHEMA_FILE points at the file; this is the one assertion that makes the
    # pointer mean something.
    assert module.SCHEMA_FILE == CONFIG / schema_file
    assert _schema(schema_file)["properties"]["schema_version"] == {
        "const": module.SCHEMA_VERSION
    }


PROFILES = sorted(
    list(ROOT.glob("config/profiles/*/profile.json"))
    + list(ROOT.glob("examples/profiles/*/profile.json"))
)


def test_the_repository_ships_profiles_to_check():
    # A glob that silently matched nothing would make the next test vacuous.
    assert PROFILES, "no profile.json found to check against profile.schema.json"


@pytest.mark.parametrize(
    "path", PROFILES, ids=[str(p.relative_to(ROOT)) for p in PROFILES]
)
def test_shipped_profiles_satisfy_the_published_schema(path):
    """Both directions of the #1049 drift, on the artifacts kcn actually runs.

    `load_profile` already covers the loader's own opinion; what was missing is
    that the *published* schema agrees with it about the same file.
    """
    schema = _schema("profile.schema.json")
    doc = json.loads(path.read_text())
    assert set(doc) == set(schema["required"])
    for key, workflow in doc["workflows"].items():
        allowed = set(
            schema["properties"]["workflows"]["additionalProperties"]["properties"]
        )
        assert set(workflow) <= allowed, f"workflows.{key} has {sorted(set(workflow) - allowed)}"
    # And it must still load: the schema being satisfiable is only interesting
    # if the code that consumes the file accepts the same document.
    profiles.load_profile(path.parent, path)

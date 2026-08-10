"""`clawock context audit` with no --profile must cover every profile.

#380's acceptance: "Removing or renaming a required context file becomes a
visible audit failure instead of a silent capability loss."

It did not, for the command anyone would actually run. With no `--profile` the
audit resolved to the manifest default — `isolated-cron`, five bootstrap files —
so emptying `MEMORY.md`, which only the seven-file `interactive` profile
requires, produced `ok: true` and exit 0. Measured on a copy of the live
workspace:

    context audit                      → ok=True   exit 0   empty=[]
    context audit --profile interactive → ok=False  exit 1   empty=['MEMORY.md']

Auditing one profile is still right when you mean one profile. Defaulting to one
was the bug: the obvious command has to be the safe one.
"""
import json

import pytest

from clawock.context.assembly import audit, audit_all, load_manifest


@pytest.fixture
def workspace(tmp_path):
    """A workspace carrying every file every profile requires."""
    manifest = load_manifest()
    for contract in manifest["profiles"].values():
        for name in contract["bootstrap"]:
            path = tmp_path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f'content of {name}\n')
        for relative in contract.get("capability_paths", []):
            # MEMORY.md is both a bootstrap document and a capability root, so
            # this must not try to turn an existing file into a directory.
            target = tmp_path / relative
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_a_complete_workspace_passes(workspace):
    assert audit_all(workspace)["ok"] is True


def test_every_profile_is_audited(workspace):
    result = audit_all(workspace)
    assert set(result["audited"]) == set(load_manifest()["profiles"])
    assert len(result["audited"]) > 1, (
        'with one profile this whole distinction is vacuous — if the manifest '
        'ever collapses to a single profile, this test should be reconsidered '
        'rather than silently passing'
    )


def _only_in_non_default_profile(manifest):
    """A bootstrap file some profile requires and the default profile does not."""
    default = manifest["profiles"][manifest["default_profile"]]["bootstrap"]
    for name, contract in manifest["profiles"].items():
        if name == manifest["default_profile"]:
            continue
        for item in contract["bootstrap"]:
            if item not in default:
                return name, item
    return None, None


def test_emptying_a_file_the_default_profile_ignores_still_fails(workspace):
    """The exact 2026-08-10 hole, expressed against the manifest rather than
    against MEMORY.md by name — so it keeps testing the property if the profiles
    are ever reorganised."""
    manifest = load_manifest()
    profile, name = _only_in_non_default_profile(manifest)
    assert name, 'no profile requires a file the default one does not — nothing to test'

    (workspace / name).write_text('   \n')

    assert audit(workspace)["ok"] is True, (
        'precondition: the default profile genuinely does not care about this file'
    )
    result = audit_all(workspace)
    assert result["ok"] is False
    assert f'{profile}:{name}' in result["empty"]


def test_removing_such_a_file_also_fails(workspace):
    manifest = load_manifest()
    profile, name = _only_in_non_default_profile(manifest)
    (workspace / name).unlink()

    result = audit_all(workspace)
    assert result["ok"] is False
    assert f'{profile}:{name}' in result["missing"]


def test_the_rollup_names_the_profile_each_finding_came_from(workspace):
    """A bare filename in a multi-profile rollup sends the reader looking in the
    wrong contract."""
    manifest = load_manifest()
    profile, name = _only_in_non_default_profile(manifest)
    (workspace / name).unlink()

    for item in audit_all(workspace)["missing"]:
        assert ':' in item, item
    assert audit_all(workspace)["profiles"][profile]["ok"] is False


def test_single_profile_audit_keeps_its_shape(workspace):
    """`--profile X` is unchanged — it is still the right operation when you
    mean one profile, and its JSON is what the adapter docs show."""
    result = audit(workspace, profile=load_manifest()["default_profile"])
    assert result["profile"] == load_manifest()["default_profile"]
    assert "bootstrap" in result and "profiles" not in result


def test_the_bare_command_audits_every_profile(workspace, capsys):
    """Through the real argument parser, not a hand-built namespace.

    The first version of this fix passed its unit tests and changed nothing:
    `--profile` carried `default="isolated-cron"`, so `args.profile` was never
    None and the all-profiles branch was unreachable. A test that constructs
    Args itself cannot see that — it tests the handler while the bug lives in
    the parser.
    """
    from clawock import cli

    manifest = load_manifest()
    _profile, name = _only_in_non_default_profile(manifest)
    (workspace / name).unlink()

    code = cli.main(['context', 'audit', '--workspace', str(workspace)])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1, 'the exit code is what a cron or a human actually reads'
    assert payload["ok"] is False
    assert set(payload["audited"]) == set(manifest["profiles"])


def test_naming_one_profile_still_audits_only_that_one(workspace, capsys):
    from clawock import cli

    manifest = load_manifest()
    _profile, name = _only_in_non_default_profile(manifest)
    (workspace / name).unlink()

    code = cli.main(['context', 'audit', '--workspace', str(workspace),
                     '--profile', manifest["default_profile"]])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0, 'the default profile genuinely does not require that file'
    assert payload["profile"] == manifest["default_profile"]

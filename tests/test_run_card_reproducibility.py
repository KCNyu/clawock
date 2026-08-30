"""The reproduction key promised more coverage than it had (#1139).

`run_card.build_card`'s docstring said "two runs sharing this key must produce
the same metrics". Three things could break that while the key stayed identical:
the seeds (eight literals inline in eight modules), the environment (numpy and
scipy are required dependencies and the evaluation lane leans on them), and the
configuration files a run read but did not pass explicitly.

These tests hold the schema-2 card to that promise — each of the three has to
move the key — and to the thing that makes a broken promise actionable: when two
cards disagree, `explain_mismatch` has to name which input moved, and has to say
so out loud when *nothing* recorded moved and the answer did anyway.
"""
import json

import pytest

from clawock import seeds
from clawock.evidence import run_card


def _card(**overrides):
    base = dict(params={'threshold': 0.5}, inputs=[{'symbol': 'X', 'digest': 'sha256:aa'}],
                metrics={'sharpe': 1.0})
    base.update(overrides)
    return run_card.build_card('demo', **base)


def test_every_seed_in_the_repository_is_registered():
    """The literal is the problem, not the number.

    A seed inline in a module is deliberate and invisible: the card recorded
    params, inputs and code, and the number deciding which bootstrap draws were
    taken lived nowhere in it.

    Walked with `ast` rather than matched with a regex, so a docstring that
    *mentions* a seed — including the one above `run_card.build_card` explaining
    why this gate exists — is not itself a violation.
    """
    import ast
    from pathlib import Path

    root = Path(run_card.__file__).parent.parent
    offenders = []
    for path in sorted(root.rglob('*.py')):
        if path.name == 'seeds.py':
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            big = None
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'Random'
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, int)
                    and node.args[0].value >= 100000):
                big = node.args[0]
            elif isinstance(node, ast.arguments):
                for name, default in zip(
                        [arg.arg for arg in node.kwonlyargs], node.kw_defaults):
                    if (name in ('seed', 'random_state')
                            and isinstance(default, ast.Constant)
                            and isinstance(default.value, int)
                            and default.value >= 100000):
                        big = default
            if big is not None:
                offenders.append(f'{path.name}:{big.lineno}: {big.value}')
    assert not offenders, (
        'seeds must come from clawock.seeds, not from a literal:\n'
        + '\n'.join(offenders))


def test_an_unregistered_seed_raises_instead_of_defaulting():
    """A typo falling back to a default would be reproducible and wrong."""
    with pytest.raises(KeyError) as caught:
        seeds.seed('not_a_real_seed')
    assert 'registered' in str(caught.value)


def test_a_different_seed_changes_the_reproduction_key():
    first = _card(seeds={'block_bootstrap': 1})
    second = _card(seeds={'block_bootstrap': 2})
    assert first['reproduction_key'] != second['reproduction_key']


def test_a_different_library_version_changes_the_reproduction_key(monkeypatch):
    """The half the key could not see.

    A minor numpy release that changes a random stream moves every metric under
    an unchanged key, which is the failure mode a reproduction key exists to
    make impossible.
    """
    baseline = _card()['reproduction_key']
    monkeypatch.setattr(run_card, 'environment', lambda: {
        'python': '3.12.3', 'implementation': 'CPython', 'platform': 'linux',
        'libraries': {'numpy': '9.9.9', 'scipy': '1.11.4', 'requests': '2.34.2'}})
    assert _card()['reproduction_key'] != baseline


def test_a_changed_config_file_changes_the_key(tmp_path):
    config = tmp_path / 'policy.json'
    config.write_text('{"weight": 1}')
    first = _card(config_files=[config])['reproduction_key']
    config.write_text('{"weight": 2}')
    assert _card(config_files=[config])['reproduction_key'] != first


def test_the_platform_alone_does_not_invalidate_every_card(monkeypatch):
    """A patch-level interpreter bump cannot change a float, and the key says so.

    The environment is recorded on the card for a reader; only the library
    versions are in the key. Putting the interpreter's patch level in it would
    invalidate every card on a routine security update.
    """
    libraries = run_card.environment()['libraries']
    baseline = _card()['reproduction_key']
    monkeypatch.setattr(run_card, 'environment', lambda: {
        'python': '3.12.9', 'implementation': 'CPython', 'platform': 'darwin',
        'libraries': libraries})
    assert _card()['reproduction_key'] == baseline


def test_the_metrics_digest_is_independent_of_the_key():
    """The interesting case is when the two disagree.

    The key answers "were the inputs the same"; the digest answers "was the
    answer the same". Identical key with a different digest is the one that
    means the card does not describe everything deciding the result.
    """
    same_inputs_different_answer = (_card(metrics={'sharpe': 1.0}),
                                    _card(metrics={'sharpe': 1.4}))
    first, second = same_inputs_different_answer
    assert first['reproduction_key'] == second['reproduction_key']
    assert first['metrics_digest'] != second['metrics_digest']
    report = run_card.explain_mismatch(first, second)
    assert report['unexplained'] is True
    assert report['same_reproduction_key'] and not report['same_metrics']


def test_explain_mismatch_names_the_input_that_moved(tmp_path):
    config = tmp_path / 'policy.json'
    config.write_text('{"weight": 1}')
    first = _card(config_files=[config])
    config.write_text('{"weight": 2}')
    second = _card(config_files=[config])
    report = run_card.explain_mismatch(first, second)
    assert report['unexplained'] is False
    assert 'config' in report['differences']
    assert 'params' not in report['differences']


def test_execution_metadata_is_recorded_when_a_start_time_is_given():
    import time
    card = _card(started_at=time.monotonic() - 0.5)
    assert card['execution']['wall_seconds'] >= 0.5
    assert card['execution'].get('peak_rss_kb', 1) > 0


def test_the_card_still_serialises_and_carries_its_schema():
    card = _card(config_files=[])
    assert card['schema_version'] == 2
    assert set(card) >= {'seeds', 'environment', 'config', 'metrics_digest', 'execution'}
    json.dumps(card)

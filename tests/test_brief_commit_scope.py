"""The brief commit carries this generation's artifacts, not the checkout."""
from clawock.harness import brief_postflight


def test_brief_commit_is_limited_to_this_generations_paths(tmp_path, monkeypatch):
    day = '2026-07-30'
    for relative in (f'memory/{day}-pre-open.md', f'memory/{day}-plan.json',
                     f'memory/snapshots/{day}.json', 'memory/decisions.jsonl',
                     'portfolio.json'):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    (tmp_path / 'memory/bars').mkdir(parents=True)
    (tmp_path / 'memory/strategy-lab').mkdir(parents=True)
    # A leftover from a timed-out earlier run, which the old `memory/` add swept in.
    (tmp_path / 'memory/2026-07-29-pre-open.md').write_text('yesterday')
    version_dir = tmp_path / 'memory' / 'brief-versions' / day
    version_dir.mkdir(parents=True)
    (version_dir / 'index.json').write_text('{}')
    (version_dir / 'v1-3f2a9c1b.md').write_text('# version')

    monkeypatch.setattr(brief_postflight, 'WS', tmp_path)
    for name in ('log_decisions', 'record_risk_stances', 'record_strategy_lab'):
        monkeypatch.setattr(brief_postflight, name, lambda *_a, **_k: True)
    monkeypatch.setattr(brief_postflight, 'rebuild_dashboard', lambda: (True, ''))
    monkeypatch.setattr(brief_postflight, 'push_with_rebase_retry', lambda: (True, ''))

    calls = []

    def git(*args):
        calls.append(args)
        return True, ''

    monkeypatch.setattr(brief_postflight, '_git', git)

    assert brief_postflight.maybe_commit('pass', day) == (True, 'committed + pushed')

    add = next(args for args in calls if args[0] == 'add')
    assert 'memory/' not in add, 'the whole memory/ directory is still staged'
    assert f'memory/{day}-plan.json' in add
    assert f'memory/{day}-pre-open.md' in add
    assert 'memory/snapshots/' in add, 'the snapshot directory (and its archive) is staged'
    assert f'memory/brief-versions/{day}/' in add, 'today\'s version directory is staged'
    assert 'memory/2026-07-29-pre-open.md' not in add

    commit = next(args for args in calls if args[0] == 'commit')
    assert '--' in commit
    assert list(commit[commit.index('--') + 1:]) == list(add[1:])

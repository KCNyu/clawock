"""Every file the brief builds must have exactly one owner that publishes it.

This is a contract test, not a unit test, because the bug it guards has now
recurred three times in six weeks and each time in a new file rather than a new
mechanism:

  * 2026-06-05 — GH Action fresh checkout stripped the sidecars;
  * 2026-06-10 — risk/lev_regime/benchmark were rebuilt every morning and never
    committed, so origin's copies went stale and GHA rebuilds regressed the
    dashboard to day-old values;
  * 2026-07-16 — t0_setups/em_news/guardrail_history did the same. Their last
    commits (940aaa9, 47c565d) were docs commits that happened to sweep them up.

Each fix was a hand-edited git-add list, which is why it kept coming back: nothing
tied the list to what preflight actually writes. These tests tie them together, so
the next file added to preflight fails here instead of six weeks later on a chart
nobody can explain.

Run: python3 -m pytest tests/test_brief_data_ownership.py -q
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'harness'))

import _harness_common

PREFLIGHT = (ROOT / 'scripts' / 'harness' / 'brief_preflight.py').read_text()
POSTFLIGHT = (ROOT / 'scripts' / 'harness' / 'brief_postflight.py').read_text()

# Owned by a GH Action: preflight reads these, the workflow writes and commits
# them. Committing them from the brief would fight the workflow, so they are the
# one legitimate reason for a path to be read by preflight and absent from its
# git-add list.
GHA_OWNED = {
    'macro.json': 'macro-scan.yml',
    'sentiment.json': 'sentiment-scan.yml',
    'us_news_digest.json': 'news-digest.yml',
    'influencer_feed.json': 'influencer-scan.yml',
}


def _postflight_add_list():
    """The paths brief_postflight stages, as written in its _git('add', ...) call."""
    m = re.search(r"_git\('add',(.*?)\)\n", POSTFLIGHT, re.S)
    assert m, "brief_postflight no longer has a _git('add', ...) call — did it move?"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def test_preflight_writes_are_committed():
    """Anything preflight builds under assets/data/ is staged by postflight.

    A file that is written every morning but never staged is strictly worse than
    one that is never written: the dashboard embeds the fresh local copy while
    origin serves an old one, so local and published disagree with no error
    anywhere.
    """
    staged = _postflight_add_list()
    # Paths preflight (or a script it runs) writes, taken from the source itself.
    written = set(re.findall(r"WS / 'assets' / 'data' / '([^']+)'", PREFLIGHT))
    written |= {'catalysts.json', 't0_setups.json', 't0_setups_history.jsonl',
                'quant_signals.json', 'quant_signals_history.jsonl', 'em_news.json'}
    unowned = sorted(f for f in written
                     if f not in GHA_OWNED and f'assets/data/{f}' not in staged)
    assert not unowned, (
        f'preflight writes {unowned} every morning but postflight never stages them. '
        f'Either add them to the _git add list, or add them to GHA_OWNED if a '
        f'workflow took ownership.')


def test_gha_synced_files_are_actually_gha_produced():
    """GHA_DATA_FILES is checked out from origin, so a local-only file must not be
    in it — the checkout would silently discard the copy preflight just fetched.

    catalysts.json was in that list for weeks with no workflow behind it: the sync
    overwrote each fresh fetch with origin's older copy, and since it wasn't
    committed either, origin only moved when an unrelated commit swept it up.
    """
    for name in _harness_common.GHA_DATA_FILES:
        assert name in GHA_OWNED, (
            f'{name} is synced from origin but no workflow owns it. If preflight is '
            f'its only writer, the sync discards fresh local data — remove it from '
            f'GHA_DATA_FILES.')


def test_gha_owned_files_are_not_committed_by_the_brief():
    """The other direction: two writers is the same bug wearing a different hat."""
    staged = _postflight_add_list()
    both = sorted(f for f in GHA_OWNED if f'assets/data/{f}' in staged)
    assert not both, (
        f'{both} are committed by both a workflow and the brief; they will race and '
        f'overwrite each other.')

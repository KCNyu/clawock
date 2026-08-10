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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTANCE_HARNESS = ROOT / 'instances' / 'kcnyu' / 'src' / 'clawock_kcnyu' / 'harness'
sys.path.insert(0, str(ROOT / 'instances' / 'kcnyu' / 'src'))

from clawock_kcnyu.harness import _harness_common

PREFLIGHT = (INSTANCE_HARNESS / 'brief_preflight.py').read_text()
POSTFLIGHT = (INSTANCE_HARNESS / 'brief_postflight.py').read_text()

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


def _preflight_utilities():
    """The packaged commands preflight shells out to, read from its own source."""
    return sorted(set(re.findall(r"\[\s*'clawock',\s*'([a-z0-9-]+)'", PREFLIGHT)))


def _utility_outputs():
    """Every path those utilities write, at any depth, discovered from source.

    This used to look for `scripts/data/<name>.py`, which #429 deleted — so it
    returned an empty dict and the test below asserted nothing at all. The
    discovery has to follow the code: preflight now spawns `clawock <command>`,
    and the CLI's own dispatch table says which module that is.

    A constant counts as an output when it resolves under the workspace and the
    module writes through it. `evidence.md` — the file #345 was opened for — is
    `WS / 'site' / 'evidence.md'` today, so the old single-segment pattern would
    have missed it even if the directory still existed.
    """
    import importlib

    from clawock.cli import PACKAGED_UTILITIES

    const = re.compile(
        r"^([A-Z_][A-Z0-9_]*)\s*=\s*([A-Z_][A-Z0-9_]*)((?:\s*/\s*'[^']+')+)\s*$", re.M)
    out = {}
    for command in _preflight_utilities():
        target = PACKAGED_UTILITIES.get(command)
        if not target:
            continue
        source = Path(importlib.import_module(target).__file__).read_text()
        relative = {'WS': ''}
        for name, base, tail in const.findall(source):
            if base in relative:
                parts = [relative[base], *re.findall(r"'([^']+)'", tail)]
                relative[name] = '/'.join(part for part in parts if part)
        for name, rel in relative.items():
            if name == 'WS' or not rel or '.' not in Path(rel).name:
                continue
            written = re.search(
                rf"\b\w*(?:write|dump)\w*\(\s*(?:str\()?{name}\b"
                rf"|{name}\.write_text\(|{name}\.open\(", source)
            if written:
                out[rel] = command
    return out


def test_outputs_outside_assets_data_are_committed_too():
    """The same contract, for files that do NOT live under assets/data/.

    This is the hole `evidence.md` fell through (#345): every `git add` above is
    directory-scoped, and the sibling test only discovers `assets/data/` paths, so
    an artifact outside it had no owner and nothing failed. build_evidence.py
    rewrote it each morning for months while the published page served 08-02
    numbers and live carried a permanently dirty file.

    A path is covered by an exact entry or by a staged directory above it; a
    gitignored path is deliberately not committed, and demanding it would push
    generated state back into the repository.
    """
    staged = _postflight_add_list()
    outputs = _utility_outputs()
    # Anti-vacuity. Between #429 and now this test discovered nothing and passed
    # for that reason alone, which is how the guard for #345 stopped guarding.
    assert len(_preflight_utilities()) >= 10 and len(outputs) >= 8, (
        f'discovery found {len(_preflight_utilities())} utilities and '
        f'{len(outputs)} outputs — it has stopped following the code again')

    def covered(path):
        if path in staged or Path(path).name in GHA_OWNED:
            return True
        if any(entry.endswith('/') and path.startswith(entry) for entry in staged):
            return True
        return subprocess.run(['git', 'check-ignore', '-q', path],
                              cwd=str(ROOT)).returncode == 0

    unowned = sorted(f'{name} (written by clawock {command})'
                     for name, command in outputs.items() if not covered(name))
    assert not unowned, (
        f'preflight rebuilds {unowned} but postflight never stages them, so '
        f'origin keeps serving a stale copy and live stays dirty.')


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


def test_every_gha_owned_file_is_synced_before_the_brief_reads_it():
    """The reverse inclusion, which the one-way check above cannot see.

    influencer_feed.json sat in exactly this blind spot: influencer-scan.yml builds
    and commits it, preflight reads it, but it was missing from GHA_DATA_FILES — so
    the sync never pulled the workflow's fresh copy and the brief read whatever stale
    version happened to be in the working tree. That is the 2026-05-22 sentiment bug
    (brief embedded 5-21 data because the sync hadn't fetched) which is the very
    reason sync_gha_data_files exists.
    """
    missing = sorted(set(GHA_OWNED) - set(_harness_common.GHA_DATA_FILES))
    assert not missing, (
        f'{missing} are produced by a workflow and read by the brief, but are not in '
        f'GHA_DATA_FILES — the brief will read a stale local copy instead of the '
        f"workflow's fresh one.")


def test_gha_owned_files_are_not_committed_by_the_brief():
    """The other direction: two writers is the same bug wearing a different hat."""
    staged = _postflight_add_list()
    both = sorted(f for f in GHA_OWNED if f'assets/data/{f}' in staged)
    assert not both, (
        f'{both} are committed by both a workflow and the brief; they will race and '
        f'overwrite each other.')

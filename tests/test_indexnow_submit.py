"""IndexNow submission must be incremental and change-aware, not a hardcoded URL.

From 2026-06-22 to 2026-07-23 the daily cron passed a single explicit URL, so the
49 brief pages were never announced to Bing — the script was correct, the
invocation was not. These tests pin the behaviour the cron now relies on:

- never-seen URLs go out; unchanged pages do not;
- a page whose ETag/Last-Modified changed IS re-announced (a URL-only ledger
  would silently drop every edit forever);
- the ledger advances only after an accepted POST, and merges rather than
  clobbers so a concurrent --all run cannot wipe the daily run's entries;
- main() itself is exercised on the success path, so deleting save_seen() or
  neutering select() fails a test instead of staying green.

Run: python3 -m pytest tests/test_indexnow_submit.py -q
"""
import json
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'ops' / 'growth'))
import indexnow_submit as ins

SITE = ins.SITE
HOME = f'{SITE}/'
BRIEFS = f'{SITE}/briefs.html'
OLD = f'{SITE}/memory/2026-05-16-pre-open.html'
NEW = f'{SITE}/memory/2026-07-24-pre-open.html'
SITEMAP = [HOME, BRIEFS, OLD, NEW]


def _ledger(tmp_path, mapping):
    ins.STATE = str(tmp_path / 'indexnow_seen.json')
    if mapping is not None:
        ins.save_seen(mapping)
    return ins.STATE


def _fixed_validators(mapping):
    """Patch HEAD lookups so tests are deterministic and never hit the network."""
    return mock.patch.object(ins, 'validator', side_effect=lambda u: mapping.get(u))


# --- selection -------------------------------------------------------------

def test_new_and_changed_go_out_unchanged_do_not(tmp_path):
    _ledger(tmp_path, {HOME: 'v1', BRIEFS: 'v1', OLD: 'etagOLD'})
    live = {HOME: 'v2', BRIEFS: 'v1', OLD: 'etagOLD', NEW: 'etagNEW'}
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), _fixed_validators(live):
        urls, record = ins.select(ins.parse_args([]))
    assert NEW in urls, 'a never-seen brief must be announced'
    assert HOME in urls, 'a page whose validator changed must be re-announced'
    assert BRIEFS not in urls, 'an unchanged page must not be re-POSTed'
    assert OLD not in urls, 'an unchanged archive page must not be re-POSTed'
    assert record == {HOME: 'v2', NEW: 'etagNEW'}


def test_unreachable_page_is_skipped_not_guessed(tmp_path):
    _ledger(tmp_path, {})
    with mock.patch.object(ins, 'sitemap_urls', return_value=[HOME, NEW]), \
            _fixed_validators({HOME: 'v1'}):  # NEW -> None (HEAD failed)
        urls, record = ins.select(ins.parse_args([]))
    assert urls == [HOME] and NEW not in record


def test_all_flag_backfills_every_reachable_url(tmp_path):
    _ledger(tmp_path, {HOME: 'v1', BRIEFS: 'v1', OLD: 'v1', NEW: 'v1'})
    live = {u: 'v1' for u in SITEMAP}
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), _fixed_validators(live):
        urls, record = ins.select(ins.parse_args(['--all']))
    assert set(urls) == set(SITEMAP) and record == live


def test_explicit_urls_bypass_the_sitemap(tmp_path):
    _ledger(tmp_path, {OLD: 'v1'})
    with mock.patch.object(ins, 'sitemap_urls', side_effect=AssertionError('must not fetch')), \
            _fixed_validators({NEW: 'etagNEW'}):
        urls, record = ins.select(ins.parse_args([NEW]))
    assert urls == [NEW] and record == {NEW: 'etagNEW'}


def test_all_with_explicit_urls_is_rejected():
    with mock.patch.object(sys, 'exit', side_effect=SystemExit):
        try:
            ins.parse_args(['--all', NEW])
            assert False, 'expected argparse to reject --all + URL'
        except SystemExit:
            pass


# --- ledger integrity ------------------------------------------------------

def test_corrupt_ledger_degrades_to_empty(tmp_path):
    path = _ledger(tmp_path, None)
    Path(path).write_text('{not json', encoding='utf-8')
    assert ins.load_seen() == {}


def test_save_merges_instead_of_clobbering_a_concurrent_run(tmp_path):
    _ledger(tmp_path, {HOME: 'v1'})
    ins.save_seen({NEW: 'etagNEW'})  # simulates the other process's write
    assert ins.load_seen() == {HOME: 'v1', NEW: 'etagNEW'}


# --- main() success + mutation resistance ----------------------------------

def _run_main(tmp_path, argv, live, seed=None):
    _ledger(tmp_path, seed if seed is not None else {})
    posted = {}
    def fake_post(key, urls):
        posted['urls'] = list(urls)
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), \
            _fixed_validators(live), \
            mock.patch.object(ins, 'find_key', return_value='0' * 32), \
            mock.patch.object(ins, 'post', side_effect=fake_post):
        ins.main(argv)
    return posted


def test_main_posts_changed_urls_and_records_them(tmp_path):
    live = {HOME: 'v2', BRIEFS: 'v1', OLD: 'v1', NEW: 'etagNEW'}
    posted = _run_main(tmp_path, [], live, seed={HOME: 'v1', BRIEFS: 'v1', OLD: 'v1'})
    # Deleting save_seen(record) or neutering select() breaks one of these:
    assert set(posted['urls']) == {HOME, NEW}, 'must POST exactly the changed/new URLs'
    assert ins.load_seen() == live, 'accepted POST must advance the ledger to current'


def test_main_records_nothing_when_post_fails(tmp_path):
    _ledger(tmp_path, {})
    live = {u: 'v1' for u in SITEMAP}
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), \
            _fixed_validators(live), \
            mock.patch.object(ins, 'find_key', return_value='0' * 32), \
            mock.patch.object(ins, 'post', side_effect=OSError('boom')):
        try:
            ins.main([])
        except OSError:
            pass
    assert ins.load_seen() == {}, 'ledger advanced despite a failed submission'


def test_missing_key_fails_before_sitemap_or_head_work():
    with mock.patch.object(ins, 'find_key', side_effect=SystemExit('missing')), \
            mock.patch.object(ins, 'select', side_effect=AssertionError('network work started')):
        try:
            ins.main([])
        except SystemExit as exc:
            assert str(exc) == 'missing'
        else:
            assert False, 'a real submission continued without its public key'


def test_dry_run_never_posts(tmp_path):
    live = {u: 'v1' for u in SITEMAP}
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), \
            _fixed_validators(live), \
            mock.patch.object(ins, 'post', side_effect=AssertionError('dry-run must not POST')):
        _ledger(tmp_path, {})
        ins.main(['--dry-run'])
    assert ins.load_seen() == {}


def test_record_only_seeds_ledger_without_posting(tmp_path):
    live = {u: 'v1' for u in SITEMAP}
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), \
            _fixed_validators(live), \
            mock.patch.object(ins, 'post', side_effect=AssertionError('record-only must not POST')):
        _ledger(tmp_path, {})
        ins.main(['--record-only'])
    assert ins.load_seen() == live, 'record-only must persist current validators'

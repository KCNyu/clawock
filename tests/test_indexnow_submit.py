"""IndexNow submission must be incremental, not one hardcoded URL forever.

From 2026-06-22 to 2026-07-23 the daily cron passed a single explicit URL, so the
49 brief pages were never announced to Bing at all — the script was correct and
the invocation was not. These tests pin the behaviour the cron now relies on:
never-submitted URLs go out, the daily-regenerated pages go out, unchanged
archive pages do not, and the ledger only advances after an accepted POST.

Run: python3 -m pytest tests/test_indexnow_submit.py -q
"""
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'data'))
import indexnow_submit as ins

SITE = ins.SITE
HOME = f'{SITE}/'
BRIEFS = f'{SITE}/briefs.html'
OLD = f'{SITE}/memory/2026-05-16-pre-open.html'
NEW = f'{SITE}/memory/2026-07-24-pre-open.html'
SITEMAP = [HOME, BRIEFS, OLD, NEW]


def _seen(tmp_path, urls):
    ins.STATE = str(tmp_path / 'indexnow_seen.json')
    if urls is not None:
        ins.save_seen(urls)
    return ins.STATE


def test_incremental_run_sends_new_and_daily_pages_but_not_stale_archive(tmp_path):
    _seen(tmp_path, {HOME, BRIEFS, OLD})
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP):
        urls, ledger = ins.select([])
    assert NEW in urls, 'a never-submitted brief must be announced'
    assert HOME in urls and BRIEFS in urls, 'daily-regenerated pages must be re-announced'
    assert OLD not in urls, 'unchanged archive pages must not be re-POSTed every day'
    assert ledger == set(SITEMAP)


def test_new_url_is_not_duplicated_when_it_is_also_a_daily_page(tmp_path):
    _seen(tmp_path, set())
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP):
        urls, _ = ins.select([])
    assert sorted(urls) == sorted(set(urls)), f'duplicate submission: {urls}'
    assert set(urls) == set(SITEMAP), 'an empty ledger means everything is new'


def test_all_flag_backfills_every_sitemap_url(tmp_path):
    _seen(tmp_path, set(SITEMAP))
    with mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP):
        urls, ledger = ins.select(['--all'])
    assert set(urls) == set(SITEMAP) and ledger == set(SITEMAP)


def test_explicit_urls_bypass_the_sitemap_and_extend_the_ledger(tmp_path):
    _seen(tmp_path, {OLD})
    with mock.patch.object(ins, 'sitemap_urls', side_effect=AssertionError('must not fetch')):
        urls, ledger = ins.select([NEW])
    assert urls == [NEW] and ledger == {OLD, NEW}


def test_corrupt_ledger_degrades_to_empty_instead_of_killing_the_cron(tmp_path):
    path = _seen(tmp_path, None)
    Path(path).write_text('{not json', encoding='utf-8')
    assert ins.load_seen() == set()


def test_ledger_is_not_advanced_when_the_post_fails(tmp_path):
    """A failed POST that still recorded the URLs would silently drop them forever."""
    _seen(tmp_path, set())
    with mock.patch.object(sys, 'argv', ['indexnow_submit.py']), \
            mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), \
            mock.patch.object(ins, 'find_key', return_value='0' * 32), \
            mock.patch.object(ins.urllib.request, 'urlopen', side_effect=OSError('boom')):
        try:
            ins.main()
        except OSError:
            pass
    assert ins.load_seen() == set(), 'ledger advanced despite a failed submission'


def test_dry_run_never_posts(tmp_path):
    _seen(tmp_path, set())
    with mock.patch.object(sys, 'argv', ['indexnow_submit.py', '--dry-run']), \
            mock.patch.object(ins, 'sitemap_urls', return_value=SITEMAP), \
            mock.patch.object(ins, 'find_key', return_value='0' * 32), \
            mock.patch.object(ins.urllib.request, 'urlopen',
                              side_effect=AssertionError('dry-run must not POST')):
        ins.main()
    assert ins.load_seen() == set()

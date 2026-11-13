"""The brief version chain: immutable renders, one current pointer, delivery binding."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from clawock.harness import brief_versions

DAY = '2026-11-13'
HKT = timezone(timedelta(hours=8))
REPORT = ('---\nlayout: default\ntitle: 盘前深度简报 · 2026-11-13\n---\n\n'
          '# 盘前深度简报｜2026-11-13\n\n现金 13.2 亿美元\n')


def _capture(workspace, text=REPORT, **kwargs):
    return brief_versions.capture(
        workspace, DAY, text,
        at=kwargs.pop('at', datetime(2026, 11, 13, 8, 32, tzinfo=HKT)),
        **kwargs)


def test_capture_writes_an_immutable_node_and_points_current_at_it(tmp_path):
    row = _capture(tmp_path, generation_id='generation-1')

    assert row['id'].startswith('v1-') and len(row['id']) == 11
    index = json.loads(brief_versions.index_path(tmp_path, DAY).read_text())
    assert index['schema_version'] == 1
    assert index['date'] == DAY
    assert index['current'] == row['id']
    assert index['current_sha256'] == row['sha256']
    assert len(index['versions']) == 1
    version_file = brief_versions.versions_dir(tmp_path, DAY) / row['file']
    assert version_file.read_text(encoding='utf-8') == REPORT
    assert row['path'] == f'memory/brief-versions/{DAY}/{row["file"]}'
    assert row['parent'] is None
    assert row['generation_id'] == 'generation-1'
    assert row['bytes'] == len(REPORT.encode('utf-8'))


def test_identical_bytes_reuse_the_node_and_only_revert_the_pointer(tmp_path):
    first = _capture(tmp_path)
    second = _capture(
        tmp_path, at=datetime(2026, 11, 13, 8, 40, tzinfo=HKT))

    assert second['id'] == first['id']
    index = json.loads(brief_versions.index_path(tmp_path, DAY).read_text())
    assert len(index['versions']) == 1
    assert index['current'] == first['id']


def test_a_correction_appends_a_node_and_records_its_parent(tmp_path):
    first = _capture(tmp_path)
    corrected = REPORT.replace('现金 13.2 亿美元', '现金 13.1 亿美元')
    second = _capture(
        tmp_path, corrected, at=datetime(2026, 11, 13, 9, 2, tzinfo=HKT))

    assert second['id'].startswith('v2-')
    assert second['parent'] == first['id']
    index = json.loads(brief_versions.index_path(tmp_path, DAY).read_text())
    assert index['current'] == second['id']
    assert [row['id'] for row in index['versions']] == [first['id'], second['id']]
    # The delivered node is still exactly the bytes it archived.
    assert brief_versions.load_report(tmp_path, DAY, first['id']) == REPORT
    assert brief_versions.load_report(tmp_path, DAY, second['id']) == corrected


def test_reverting_to_older_bytes_moves_current_back_without_a_duplicate(tmp_path):
    first = _capture(tmp_path)
    second_text = REPORT.replace('现金 13.2 亿美元', '现金 13.1 亿美元')
    second = _capture(
        tmp_path, second_text, at=datetime(2026, 11, 13, 9, 2, tzinfo=HKT))
    back = _capture(
        tmp_path, at=datetime(2026, 11, 13, 9, 10, tzinfo=HKT))

    assert back['id'] == first['id']
    index = json.loads(brief_versions.index_path(tmp_path, DAY).read_text())
    assert index['current'] == first['id']
    assert len(index['versions']) == 2
    assert {row['id'] for row in index['versions']} == {first['id'], second['id']}


def test_record_delivery_binds_the_version_and_the_receipt(tmp_path):
    row = _capture(tmp_path)
    bound = brief_versions.record_delivery(
        tmp_path, DAY, row['id'],
        at=datetime(2026, 11, 13, 8, 32, 47, tzinfo=HKT),
        channels={'wechat': True, 'telegram': True},
        receipt_name='brief-sent-2026-11-13.json')

    assert bound['delivery']['channels'] == {'wechat': True, 'telegram': True}
    assert bound['delivery']['receipt'] == 'brief-sent-2026-11-13.json'
    index = json.loads(brief_versions.index_path(tmp_path, DAY).read_text())
    assert index['versions'][0]['delivery'] == bound['delivery']
    assert brief_versions.record_delivery(tmp_path, DAY, 'v9-deadbeef') is None


def test_find_by_sha_names_an_archived_delivery(tmp_path):
    first = _capture(tmp_path)
    _capture(tmp_path, REPORT.replace('13.2', '13.1'))

    assert brief_versions.find_by_sha(tmp_path, DAY, first['sha256'])['id'] == first['id']
    assert brief_versions.find_by_sha(tmp_path, DAY, '0' * 64) is None


def test_load_report_rejects_path_like_ids(tmp_path):
    _capture(tmp_path)
    assert brief_versions.load_report(tmp_path, DAY, '../index.json') is None
    assert brief_versions.load_report(tmp_path, DAY, 'v1-../../etc/passwd') is None


def test_a_corrupt_index_is_not_overwritten(tmp_path):
    path = brief_versions.index_path(tmp_path, DAY)
    path.parent.mkdir(parents=True)
    path.write_text('{not json', encoding='utf-8')

    with pytest.raises(brief_versions.VersionStoreError):
        _capture(tmp_path)
    assert path.read_text(encoding='utf-8') == '{not json'


def test_capture_refuses_an_empty_report(tmp_path):
    with pytest.raises(brief_versions.VersionStoreError):
        brief_versions.capture(tmp_path, DAY, '')


def test_archive_url_uses_the_declared_repository(tmp_path):
    row = _capture(tmp_path)
    config = tmp_path / 'config'
    config.mkdir()
    (config / 'pages-public.json').write_text(json.dumps({
        'site_url': 'https://example.invalid/desk',
        'repo_url': 'https://github.com/example/desk/',
    }))

    assert brief_versions.archive_url(tmp_path, row) == (
        f"https://github.com/example/desk/blob/master/{row['path']}")


def test_archive_url_is_empty_without_a_repository(tmp_path):
    row = _capture(tmp_path)
    assert brief_versions.archive_url(tmp_path, row) == ''

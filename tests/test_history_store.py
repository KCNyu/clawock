"""#951 的验收闸：滚动窗口只改存储，不改任何读者看到的序列。

「顺手加个 cap」在这四个 JSONL 上是不安全的，因为两个读者读的是完整历史：
novelty 用它区分「旧事重提」(0.8) 与「全新」(1.0)，walk-forward 用它决定评估
窗口。所以这里钉的不是「文件变小了」，而是**分档之后读者读到的东西逐行不变**。
"""
import json
from datetime import date, datetime, timedelta, timezone

from clawock import history_store
from clawock.evidence import news_evidence_graph as graph


TODAY = date(2026, 8, 25)


def _rows(days, *, start=TODAY - timedelta(days=400)):
    return [
        {'as_of': (start + timedelta(days=offset)).isoformat(), 'payload': offset}
        for offset in range(days)
    ]


def _write(tmp_path, rows, name='news_evidence_history.jsonl'):
    path = tmp_path / name
    history_store.write_series(path, rows, today=TODAY)
    return path


def test_the_reader_sees_the_same_series_the_writer_was_given(tmp_path):
    rows = _rows(400)
    path = _write(tmp_path, rows)

    assert history_store.load_series(path) == rows
    # …and the split actually happened, otherwise the assertion above is the
    # old behaviour passing under a new name.
    hot = [json.loads(line) for line in path.read_text().splitlines()]
    cold = [json.loads(line)
            for line in history_store.archive_path(path).read_text().splitlines()]
    assert cold and hot
    assert cold + hot == rows
    assert len(hot) <= history_store.HOT_WINDOW_DAYS + 1
    assert max(row['as_of'] for row in cold) < min(row['as_of'] for row in hot)


def test_a_row_the_window_cannot_date_stays_in_the_working_file(tmp_path):
    """无日期的行证明不了自己旧。悄悄归档等于让还在扫工作文件的读者丢行。"""
    rows = [{'payload': 'undated'}, *_rows(400)]
    path = _write(tmp_path, rows)

    hot = [json.loads(line) for line in path.read_text().splitlines()]
    assert {'payload': 'undated'} in hot


def test_rewriting_the_series_does_not_churn_the_archive(tmp_path):
    """归档必须是稳定字节：同样的冷段每天重写出同样的文件，否则 daily commit
    还是照抄一遍全量 —— 那正是 #951 要消掉的成本。"""
    rows = _rows(400)
    path = _write(tmp_path, rows)
    first = history_store.archive_path(path).read_bytes()

    rows.append({'as_of': TODAY.isoformat(), 'payload': 'today'})
    history_store.write_series(path, rows, today=TODAY)

    assert history_store.archive_path(path).read_bytes() == first


def test_the_digest_covers_the_whole_series_not_just_the_hot_window(tmp_path):
    rows = _rows(400)
    path = _write(tmp_path, rows)
    full = history_store.series_digest(path)

    # 把冷段删掉 —— 摘要必须跟着变，否则它描述的不是被计数的那批行。
    history_store.archive_path(path).unlink()
    assert history_store.series_digest(path) != full


def test_an_old_cluster_stays_recurrent_after_it_moves_into_the_archive(
        tmp_path, monkeypatch):
    """#951 里点名的那条语义：>30d 未见的 cluster 给 0.8 而不是 1.0。

    先让一条 300 天前的快照落进 archive，再走一遍生产读路径（``_load_history``
    → ``apply_novelty``）。如果读者只读工作文件，这条会被判成 new_cluster，
    也就是把「旧事重提」当成全新消息 —— 这条测试就是为拦这个而写的。
    """
    now = datetime(2026, 8, 25, 8, tzinfo=timezone.utc)
    event = graph.make_event(
        graph.load_policy(),
        ticker='ABC', title='ABC faces SEC investigation',
        published_at=now.isoformat(), event_time=now.isoformat(),
        origin='sec_filing', source='SEC EDGAR',
        url='https://www.sec.gov/Archives/abc.htm', event_type='filing_8k',
    )
    old_day = (TODAY - timedelta(days=300)).isoformat()
    history = [{
        'as_of': old_day,
        'events': [{
            'event_id': 'older-id',
            'ticker': 'ABC',
            'novelty_cluster': event['novelty_cluster'],
            'published_at': f'{old_day}T00:00:00+00:00',
        }],
    }]
    path = tmp_path / 'news_evidence_history.jsonl'
    monkeypatch.setattr(graph, 'HISTORY', path)
    history_store.write_series(path, history, today=TODAY)
    # 反空转：这条必须真的在 archive 里，工作文件必须是空的。
    assert history_store.archive_path(path).exists()
    assert path.read_text().strip() == ''

    graph.apply_novelty(graph.load_policy(), [event], graph._load_history(), now)

    assert event['novelty_reason'] == 'cluster_old_but_recurrent'
    assert event['novelty_score'] == 0.8

from clawock.decision import session_history as history
from clawock.decision import setup_review, signal_review


def _bars(monkeypatch):
    monkeypatch.setattr(history.bars, 'load_bars', lambda ticker: {'bars': {
        '2026-08-07': {'close': 100},
        '2026-08-10': {'close': 90},
        '2026-08-11': {'close': 80},
    }})


def _records():
    return [
        {'as_of': '2026-08-08', 'ts': '2026-08-08T08:00:00+08:00',
         'rows': {'NVDA': {'close': 100, 'grade_label': '追高低质', 'rsi14': 80, 'trend_on': True}}},
        {'as_of': '2026-08-09', 'ts': '2026-08-09T08:00:00+08:00',
         'rows': {'NVDA': {'close': 100, 'grade_label': '追高低质', 'rsi14': 80, 'trend_on': True}}},
        {'as_of': '2026-08-11', 'ts': '2026-08-11T08:00:00+08:00',
         'rows': {'NVDA': {'close': 90, 'grade_label': '中性', 'rsi14': 50, 'trend_on': False}}},
    ]


def test_legacy_weekend_close_restores_one_real_session_without_mutation(monkeypatch):
    _bars(monkeypatch)
    records = _records()
    days = history.normalize_days(records)
    assert [d['as_of'] for d in days] == ['2026-08-07', '2026-08-10']
    assert records[0]['as_of'] == '2026-08-08'
    assert setup_review._closed_trigger_rows(days) == 0
    assert setup_review._settle(days, 1)[1]['chase_low_quality']['n'] == 1
    assert signal_review._closed_trigger_rows(days) == 0


def test_holiday_drift_without_price_evidence_stays_excluded(monkeypatch):
    _bars(monkeypatch)
    records = _records()
    records[0]['rows']['NVDA']['close'] = 101
    days = history.normalize_days(records[:1])
    assert days[0]['as_of'] == '2026-08-08'
    assert setup_review._closed_trigger_rows(days) == 1


def test_explicit_source_dates_win_and_last_row_wins(monkeypatch):
    _bars(monkeypatch)
    rows = _records()
    rows[0]['rows']['NVDA']['session_date'] = '2026-08-07'
    rows[1]['rows']['NVDA'].update(row_as_of='2026-08-07', close=99)
    days = history.normalize_days(rows)
    assert days[0]['rows']['NVDA']['close'] == 99


def test_unmatched_missing_or_unzoned_timestamps_keep_fallback(monkeypatch):
    monkeypatch.setattr(history.bars, 'load_bars', lambda _: {'bars': {}})
    assert history.normalize_days(_records())[0]['as_of'] == '2026-08-08'
    _bars(monkeypatch)
    row = _records()[0]
    row['ts'] = '2026-08-08T08:00:00'
    assert history.normalize_days([row])[0]['as_of'] == '2026-08-08'


def test_daily_factor_history_without_timestamp_uses_nearby_bar(monkeypatch):
    _bars(monkeypatch)
    row = _records()[0]
    del row['ts']
    assert history.normalize_days([row])[0]['as_of'] == '2026-08-07'
    row['as_of'] = '2026-09-01'
    assert history.normalize_days([row])[0]['as_of'] == '2026-09-01'


def test_factor_review_consumes_session_keys_before_settlement(monkeypatch):
    _bars(monkeypatch)
    monkeypatch.setattr(signal_review.history_store, 'load_series', lambda _: _records())
    captured = {}
    monkeypatch.setattr(signal_review, 'safe_write_json', lambda _, data: captured.update(data))
    # The real history existence guard is retained; isolate it from the host.
    class History:
        def exists(self):
            return True
    monkeypatch.setattr(signal_review, 'HIST', History())
    signal_review.main()
    assert captured['factors']['trend_on_follow']['n_events'] == 1
    assert captured['closed_market_rows_excluded'] == 0

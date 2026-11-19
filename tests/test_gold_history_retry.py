"""Gold history requests retry transport and body failures within one budget."""
import subprocess
from unittest.mock import Mock

import pytest

from clawock.market_data.gold import fetch as gold


def response(body="", status=200, exit_code=0):
    return subprocess.CompletedProcess(["curl"], exit_code, f"{body}\n{status:03d}")


@pytest.fixture
def request_script(monkeypatch):
    run = Mock()
    sleep = Mock()
    monkeypatch.setattr(gold.subprocess, "run", run)
    monkeypatch.setattr(gold.time, "sleep", sleep)
    return run, sleep


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired(["curl"], 20),
    response(status=0, exit_code=7),
    response(status=0, exit_code=28),
    response(status=408),
    response(status=429),
    response(status=503),
    response('{"rates":{"CNY":7.10', exit_code=18),
    response('{"rates":{"CNY":7.10'),
])
def test_transient_errors_retry_the_same_request(request_script, failure):
    run, sleep = request_script
    run.side_effect = [failure, failure, response('{"rates":{"CNY":7.10}}')]

    assert gold.fetch_usdcny(None) == (7.1, {})
    assert run.call_count == 3
    assert run.call_args_list[0] == run.call_args_list[-1]
    assert [call.args for call in sleep.call_args_list] == [(0.5,), (1,)]


def test_nonretryable_status_does_not_accept_even_a_parseable_body(request_script):
    run, sleep = request_script
    run.return_value = response('{"rates":{"CNY":7.10}}', status=404)

    assert gold.fetch_usdcny(None) == (None, {})
    assert run.call_count == 1
    sleep.assert_not_called()


def test_truncated_sina_http_200_retries_before_fallback(monkeypatch, request_script):
    run, sleep = request_script
    body = 'var_=([{"date":"2026-11-19","close":"1234.5"}]);'
    run.side_effect = [response(body[:-3]), response(body)]
    fallback = Mock()
    monkeypatch.setattr(gold, "_em_text", fallback)

    assert gold.fetch_xau_history("2026-11-19") == (
        [("2026-11-19", 1234.5)], {"name": gold.XAU_PRIMARY_SOURCE, "points": 1}
    )
    sleep.assert_called_once_with(0.5)
    fallback.assert_not_called()


def test_exhausted_sina_body_retries_fall_back_once(monkeypatch, request_script):
    run, sleep = request_script
    run.return_value = response('<html>unavailable</html>')
    fallback = Mock(return_value='{"data":{"klines":["2026-11-19,1234.5"]}}')
    monkeypatch.setattr(gold, "_em_text", fallback)

    assert gold.fetch_xau_history("2026-11-19") == (
        [("2026-11-19", 1234.5)], {"name": gold.XAU_FALLBACK_SOURCE, "points": 1}
    )
    assert run.call_count == 3
    assert sleep.call_count == 2
    fallback.assert_called_once()


def test_fx_range_retry_retains_successful_latest_request(request_script):
    run, sleep = request_script
    run.side_effect = [
        response('{"rates":{"CNY":7.10}}'),
        response('{"rates":{"2026-11-19":{"CNY":7.0}'),
        response('{"rates":{"2026-11-19":{"CNY":7.0}}}'),
    ]

    assert gold.fetch_usdcny("2026-11-19") == (7.1, {"2026-11-19": 7.0})
    assert run.call_count == 3
    assert run.call_args_list[1] == run.call_args_list[2]
    sleep.assert_called_once_with(0.5)

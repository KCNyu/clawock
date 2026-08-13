"""Regression coverage for canonical FX and Eastmoney transport ownership."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "scripts" / "data"
sys.path.insert(0, str(DATA))

from clawock.market_data import hk_analysis as hk  # noqa: E402
from clawock.portfolio import fx  # noqa: E402
from clawock.market_data.gold import fetch as gold  # noqa: E402
from clawock.market_data import us_quotes as us  # noqa: E402
from clawock.portfolio import risk  # noqa: E402


class FakeResponse:
    def __init__(self, payload=None, text=None):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        return self._payload


def test_risk_uses_canonical_usdhkd_with_provenance(monkeypatch):
    monkeypatch.setattr(risk, "get_usdhkd", lambda: {
        "pair": "USDHKD",
        "rate": 7.8375,
        "source": "Frankfurter",
        "fetched_at": "2026-07-16T00:00:00+00:00",
        "fallback_used": False,
    })

    hkd_to_usd, meta = risk.load_canonical_fx()

    assert hkd_to_usd == pytest.approx(1 / 7.8375)
    assert meta == {
        "pair": "USDHKD",
        "rate": 7.8375,
        "source": "Frankfurter",
        "fetched_at": "2026-07-16T00:00:00+00:00",
        "fallback_used": False,
        "warning": None,
    }


def test_combined_risk_refuses_to_mix_currencies_without_fx():
    hk_meta = {
        "aligned_dates": ["2026-07-14", "2026-07-15"],
        "port_rets": np.array([0.01]),
    }
    with pytest.raises(ValueError, match="USDHKD rate required"):
        risk.compute_combined(None, hk_meta, {"us": [], "hk": [{"current_value": 100.0}]})


def test_fetch_fx_marks_provider_and_hardcoded_fallbacks(monkeypatch):
    monkeypatch.setattr(fx, "_from_cache", lambda allow_stale=False: None)
    monkeypatch.setattr(fx, "_save_cache", lambda data: None)
    monkeypatch.setattr(fx, "_get_frankfurter", lambda: None)
    monkeypatch.setattr(fx, "_get_exchangerate_host", lambda: 7.8375)
    monkeypatch.setattr(fx, "_get_yahoo", lambda: None)

    secondary = fx.get_usdhkd(force_refresh=True)
    assert secondary["source"] == "exchangerate.host"
    assert secondary["fallback_used"] is True

    monkeypatch.setattr(fx, "_get_exchangerate_host", lambda: None)
    hardcoded = fx.get_usdhkd(force_refresh=True)
    assert hardcoded["source"] == "HARDCODED_PEG_FALLBACK"
    assert hardcoded["fallback_used"] is True
    assert hardcoded["warning"]


def test_us_and_hk_quotes_use_shared_eastmoney_client(monkeypatch):
    calls = []

    def fake_em_get(url, **kwargs):
        calls.append((url, kwargs.get("label")))
        ticker = "AAPL" if "US quote" in kwargs.get("label", "") else "00100"
        return FakeResponse({"data": {"diff": [{
            "f12": ticker, "f14": ticker, "f2": 10.0, "f3": 1.0,
            "f5": 100, "f15": 10.2, "f16": 9.8, "f17": 9.9, "f18": 9.9,
        }]}})

    monkeypatch.setattr(us, "em_get", fake_em_get)
    monkeypatch.setattr(hk, "em_get", fake_em_get)

    assert us.get_eastmoney_batch(["AAPL"])["AAPL"]["c"] == 10.0
    assert hk._fetch_eastmoney_hk(["00100"])["00100"]["c"] == 10.0
    assert [label for _, label in calls] == ["US quote batch", "HK quote batch"]


def test_gold_eastmoney_legs_use_shared_client_and_keep_truth_separate(monkeypatch):
    calls = []

    def fake_em_get(url, **kwargs):
        calls.append(url)
        if "lsjz" in url:
            return FakeResponse(text=json.dumps({"Data": {"LSJZList": [{
                "FSRQ": "2026-07-15", "DWJZ": "3.5", "JZZZL": "0.5",
            }]}}))
        if "fundgz" in url:
            return FakeResponse(text='jsonpgz({"gsz":"3.51","gszzl":"0.6",'
                                             '"gztime":"x","jzrq":"2026-07-15"});')
        return FakeResponse(text=json.dumps({"data": {"klines": ["2026-07-15,3300"]}}))

    monkeypatch.setattr(gold, "em_get", fake_em_get)
    monkeypatch.setattr(gold, "_curl", lambda *args, **kwargs: "")  # force XAU fallback

    assert gold.fetch_nav_history("000217", pages=1) == [("2026-07-15", 3.5, 0.5)]
    assert gold.fetch_realtime("000217")["est_nav"] == 3.51
    history, source = gold.fetch_xau_history("2026-07-01")
    assert history == [("2026-07-15", 3300.0)]
    assert source == {"name": gold.XAU_FALLBACK_SOURCE, "points": 1}
    assert any("api.fund.eastmoney.com" in url for url in calls)
    assert any("fundgz.1234567.com.cn" in url for url in calls)
    assert any("push2his.eastmoney.com" in url for url in calls)

    seed = {
        "principal_invested": 1000.0, "units_held": 300.0,
        "reconciled_date": "2026-07-14", "daily_amount": 200.0,
        "start_date": "2026-07-01",
    }
    derived = gold.compute(seed, [("2026-07-15", 3.5, 0.5)], None)
    assert gold.GROUND_TRUTH_FIELDS.isdisjoint(derived)

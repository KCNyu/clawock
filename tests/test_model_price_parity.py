"""The dispatch price table may not silently disagree with the model registry."""
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _registry_cost_by_slug():
    registry = tomllib.loads((ROOT / "config/models.toml").read_text())["models"]
    out = {}
    for entry in registry.values():
        ref = entry.get("ref") or ""
        cost = entry.get("cost") or {}
        if ref and cost:
            out[ref.rsplit("/", 1)[-1]] = {
                "in": cost.get("input"), "out": cost.get("output"),
                "cache_read": cost.get("cacheRead"),
            }
    return out


def test_overlapping_model_prices_match_the_registry():
    registry = _registry_cost_by_slug()
    prices = json.loads((ROOT / "ops/host/model_prices.json").read_text())["models"]
    overlap = sorted(set(prices) & set(registry))
    assert overlap, "no model name overlaps the two tables; the guard went vacuous"
    mismatched = {
        name: (prices[name], registry[name]) for name in overlap
        if prices[name].get("in") != registry[name]["in"]
        or prices[name].get("out") != registry[name]["out"]
        or prices[name].get("cache_read") != registry[name]["cache_read"]
    }
    assert not mismatched, mismatched

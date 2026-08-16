"""Policy config keys vs code references must not drift (#553).

`packet.py` reads add-authorization policy from `config/add-alpha-policy.json`
and sizing-overlay policy from `config/news-evidence-policy.json` (via the
`information_overlay.sizing_policy` the evidence graph publishes). Every
`policy.get(key, default)` call that names a literal key is a configuration
contract: if the key is missing from its config, the code silently falls back
to a hardcoded default and editing the config does nothing. This parity test
is the trip-wire for that drift (same idea as `test_readme_parity`).
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "src" / "clawock" / "decision" / "packet.py"


def _flat_keys(mapping, prefix=""):
    out = set()
    for key, value in mapping.items():
        if isinstance(value, dict):
            out |= _flat_keys(value, f"{prefix}{key}.")
        else:
            out.add(f"{prefix}{key}")
    return out


def _literal_policy_keys(function_name):
    """Literal `policy.get("key", ...)` keys inside a named function."""
    source = PACKET.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != function_name:
            continue
        segment = ast.get_source_segment(source, node) or ""
        return set(re.findall(r'policy\.get\("([a-z_0-9]+)"', segment))
    return set()


def test_add_alpha_policy_keys_all_present_in_config():
    """Every literal add_policy.get key must exist in add-alpha-policy.json."""
    source = PACKET.read_text(encoding="utf-8")
    used = set(re.findall(r'add_policy\.get\("([a-z_0-9]+)"', source))
    assert used, "no add_policy.get literal keys found — test fixture drift"
    config = json.loads((ROOT / "config" / "add-alpha-policy.json").read_text())
    present = _flat_keys(config)
    missing = used - present
    assert not missing, (
        "packet.py add_policy keys missing from config/add-alpha-policy.json: "
        f"{sorted(missing)} — editing the config cannot change them"
    )


def test_sizing_policy_keys_all_present_in_news_evidence_config():
    """Every literal sizing policy.get key must exist in the sizing section."""
    used = _literal_policy_keys("_information_sizing_overlay")
    assert used, "no sizing policy.get literal keys found — test fixture drift"
    config = json.loads(
        (ROOT / "config" / "news-evidence-policy.json").read_text()
    )
    sizing = (config.get("information_overlay") or {}).get("sizing") or {}
    present = _flat_keys(sizing)
    missing = used - present
    assert not missing, (
        "packet.py sizing_policy keys missing from news-evidence-policy.json "
        f"'sizing' section: {sorted(missing)} — editing the config cannot change them"
    )


def test_early_trend_and_radar_policy_keys_all_present_in_config():
    """#621: parity coverage extends beyond packet.py to the intraday lanes —
    early_trend.classify and the opportunity radar are the direct consumers of
    minimum_peer_count / minimum_attention_rank / early_no_chase_zscore /
    opportunity_near_pct. A key missing from the config silently falls back to
    a hardcoded default and editing the config does nothing."""
    sources = {
        "early_trend.py": (ROOT / "src" / "clawock" / "decision" / "early_trend.py"),
        "intraday_preflight.py": (ROOT / "src" / "clawock" / "harness" / "intraday_preflight.py"),
        # #640/#643: the watch-list 5d gate and the short-history window are
        # config consumers too — their keys must exist or edits do nothing.
        "watch_list.py": (ROOT / "src" / "clawock" / "decision" / "watch_list.py"),
        "signals.py": (ROOT / "src" / "clawock" / "decision" / "signals.py"),
    }
    used = set()
    for name, path in sources.items():
        keys = set(re.findall(
            r'policy\.get\("([a-z_0-9]+)"', path.read_text(encoding="utf-8")))
        assert keys, f"no policy.get literal keys in {name} — fixture drift"
        used |= keys
    config = json.loads((ROOT / "config" / "add-alpha-policy.json").read_text())
    present = _flat_keys(config)
    # Keys read off a per-market sub-policy (minimum_peer_count etc.) live
    # nested under markets.* — flatten those too (the dict key itself counts).
    present.add("markets")
    for market, sub in (config.get("markets") or {}).items():
        present |= _flat_keys(sub)
    missing = used - present
    assert not missing, (
        "early_trend/intraday_preflight/watch_list/signals policy keys missing "
        f"from add-alpha-policy.json: {sorted(missing)} — editing the config "
        "cannot change them")

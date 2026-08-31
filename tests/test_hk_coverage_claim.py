"""The README's Hong Kong claim has to track the code that backs it (#1122).

"Bilingual HK + US coverage" is true of quotes, fundamentals, news and the
cash-flow reconciliation. It is not true of two research-breadth capabilities:
same-industry peers are auto-discovered for US names and read from a curated
map for HK ones, and a US halt arrives as a structured feed while an HK
suspension arrives as an announcement a human has to read.

Prose does not fail a build on its own, so this is the gate: while the code is
asymmetric the copy has to say so in both languages, and the day the flag flips
this test turns red, which is what makes someone rewrite the sentence instead of
leaving a claim that is now too modest standing next to code that outgrew it.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EN = (ROOT / "README.md").read_text()
ZH = (ROOT / "README.zh.md").read_text()


def test_hk_research_breadth_is_narrowed_while_the_code_is_asymmetric():
    from clawock.market_data import peer_discovery

    if peer_discovery.HK_AUTO_PEERS_ENABLED:
        # The flag moved. Both narrowing sentences are now wrong; rewrite them
        # rather than deleting this test.
        assert "the flag stays off" not in EN, (
            "HK auto peer discovery is ON — README.md still says the flag is off")
        assert "闸仍关着" not in ZH, (
            "HK auto peer discovery is ON — README.zh.md still says the flag is off")
        return

    for text, name in ((EN, "README.md"), (ZH, "README.zh.md")):
        assert "peer_discovery.py" in text, (
            f"{name} must name the module its HK peer claim rests on")
        assert "mover_evidence.py" in text, (
            f"{name} must name the module its HK halt claim rests on")

    # Each language states the asymmetry in its own words; pin the claim, not a
    # translation. English says research breadth is behind, Chinese says the
    # same about 研究广度.
    assert "research breadth behind US" in EN
    assert "研究广度落后美股" in ZH


def test_the_two_gaps_are_still_the_gaps_the_readme_names():
    """If either gap closes in code, the copy above is stale — fail here first."""
    from clawock.market_data import peer_discovery, mover_evidence

    # Peers: an HK holding still gets no auto peers, and asks East Money for
    # none. Asserted through the public entry point rather than off the flag,
    # so a gate moved somewhere else still fails here.
    calls = []
    monkeypatched = getattr(peer_discovery, "_suggest_hk")
    try:
        peer_discovery._suggest_hk = lambda *a, **k: calls.append(a) or [{"ticker": "x"}]
        assert peer_discovery.suggest_auto_peers("00100", "hk", []) == []
    finally:
        peer_discovery._suggest_hk = monkeypatched
    assert calls == [], "HK auto peer discovery reached its source — recheck the README"

    # Halts: the shared fetch is the US feed; HK has no structured equivalent.
    doc = mover_evidence.halts.__doc__ or ""
    assert "HK has no free equivalent" in doc, (
        "mover_evidence.halts no longer documents the HK gap — recheck the README")

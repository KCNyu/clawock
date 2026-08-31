"""Every seed in the repository, declared once, in one place.

Eight modules held a literal like `random.Random(20260813)` inline. Each was
deliberate and each was invisible: a run card recorded the parameters, the input
digests and the code digests, and then claimed that "two runs sharing this
reproduction key must produce the same metrics" — while the number that decides
which bootstrap draws are taken lived nowhere in the card.

It lives at the top of the package rather than under `evidence/` for a reason
the layering test would otherwise have caught: `decision` may not import
`evidence` (`test_import_layering` pins both directions), and two of the eight
seeds are in `decision/ledger.py`. A registry every layer has to reach is a leaf
module with no imports of its own.

That claim was not quite true for a second reason too. The key covers params,
inputs and code; it does not cover the *environment*. `numpy` and `scipy` are
required dependencies now and the evaluation lane leans on them, so a minor
release that changes a random stream or a linear-algebra path moves the metrics
under an unchanged key. `run_card.environment()` closes that half; this module
closes the other.

The dates are the day the seed was chosen and carry no meaning beyond being
arbitrary and fixed. **Never change one to make a result look better** — that is
a search over a nuisance parameter, and it is the cheapest possible way to
overfit. If a seed genuinely has to change, change it, and expect every card
whose reproduction key it touches to stop matching, which is the system working.
"""
from __future__ import annotations

#: seed name -> value. The name is what a run card records, so it must describe
#: what the seed governs rather than where it lives.
SEEDS = {
    'decision_episode_bootstrap': 20260714,
    'decision_cluster_bootstrap': 20260717,
    'factor_walk_forward_bootstrap': 20260726,
    'regime_permutation': 20260802,
    'add_alpha_cluster_bootstrap': 20260813,
    'signal_panel_cluster_bootstrap': 20260829,
    'block_bootstrap': 20260830,
    'drift_session_permutation': 20260830,
    'signal_panel_placebo_permutation': 20260831,
}


def seed(name: str) -> int:
    """The registered seed, or a KeyError naming the ones that exist.

    Deliberately not `.get(name, default)`: a typo silently falling back to a
    default seed would produce a run that is reproducible and not the one the
    caller meant.
    """
    if name not in SEEDS:
        raise KeyError(f'unregistered seed {name!r}; registered: {sorted(SEEDS)}')
    return SEEDS[name]

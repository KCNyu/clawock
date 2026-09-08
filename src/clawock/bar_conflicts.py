"""Naming the shape of a stored-vs-fetched bar disagreement.

Foundation-shaped, and here rather than in `market_data` for the reason #814
moved four other modules to this level: it imports nothing from this package,
and both the store that *writes* a refusal (`market_data.bars`) and the health
report that *reads the log back* (`portfolio.integrity`) need it. Importing
across those two packages the other way is a cycle, and a function-level import
is not a fix for a cycle — it is a cycle that starts working.

Nothing here touches a file. Two dicts in, one word out.
"""
from __future__ import annotations

#: The closed vocabulary a refusal is classified into. Deliberately small, and
#: deliberately about the *shape* of the disagreement rather than its cause —
#: "the provider re-priced the whole bar by one ratio" is observable, "the
#: provider applied a split" is a guess about someone else's system.
CONFLICT_KINDS = (
    "impossible_bar",      # fails the structural check outright — never stored
    "uniform_rescale",     # every leg moved by the same ratio: adjustment signature
    "close_only",          # only the close moved: a settlement-price revision
    "rounding",            # every leg moved by < 5bp: precision, not information
    "extreme_only",        # only a wick moved, by about a tick: nothing settles on it
    "bar_revision",        # anything else: a real disagreement about the session
)

#: Below this, a difference is precision rather than information. 5bp of a
#: HK$700 close is 35 cents — smaller than one tick on that board.
ROUNDING_REL_TOL = 5e-4
#: How close the four ratios must be to each other to read as one rescale.
RESCALE_REL_TOL = 1e-3
#: How far a high or low may be revised and still read as a tick on a wick.
#: One tick is ~0.1% of a HK$2 board lot and ~0.2% of a HK$0.50 one, so 1%
#: leaves an order of magnitude of headroom; above it the provider is
#: disagreeing about the session's range itself, which is a `bar_revision`
#: whether or not it touches a leg the ledger settles on.
WICK_REL_TOL = 1e-2


def classify_conflict(old: dict, fetched: dict) -> str:
    """Name the shape of a stored-vs-fetched disagreement.

    The store already refuses to overwrite; what it could not say is *what kind*
    of disagreement it refused. A weekly stream of `rounding` and a single
    `bar_revision` on a session the ledger settled against are the same line of
    output today, and they call for opposite responses.
    """
    legs = ("open", "high", "low", "close")
    moved = [k for k in legs
             if abs(old.get(k, 0) - fetched.get(k, 0)) > 1e-9]
    if not moved:
        return "rounding"
    relative = [
        abs(old[k] - fetched[k]) / abs(old[k])
        for k in legs
        if isinstance(old.get(k), (int, float)) and old.get(k)
    ]
    if relative and max(relative) < ROUNDING_REL_TOL:
        return "rounding"
    if moved == ["close"]:
        return "close_only"
    # The shape the log is actually full of (2026-09-08): the provider revises an
    # intraday extreme by about one tick and leaves open and close alone. All 25
    # rows ever recorded here move `low` and nothing else — NOT ONE moves open or
    # close — and the largest is 0.107%, three cents on a $27.93 low. Eleven land
    # under the rounding tolerance already; the other fourteen are this kind.
    #
    # It matters which name that gets. The ledger settles on `close`
    # (`memory/bars` is the only store the settled views read), so a bar whose
    # open and close are unchanged cannot move a number anything was settled
    # against — while `bar_revision` is the kind whose remedy is `--repair`.
    # Those fourteen were being reported as nine `uniform_rescale` — which names
    # a SPLIT — and five `bar_revision`, two different wrong answers for one
    # shape, decided by nothing more than which side of a spread test the
    # untouched legs' ratios of exactly 1.0 happened to fall on.
    #
    # Above the rounding tolerance on purpose: this is not "too small to care
    # about", it is "real, and confined to a leg nothing settles on". And bounded
    # by `WICK_REL_TOL` on purpose too: a provider that moves the high 12% still
    # disagrees about the session, wick or not.
    if moved and not ({"open", "close"} & set(moved)):
        if relative and max(relative) < WICK_REL_TOL:
            return "extreme_only"
    ratios = [
        fetched[k] / old[k]
        for k in legs
        if isinstance(old.get(k), (int, float)) and old.get(k)
        and isinstance(fetched.get(k), (int, float))
    ]
    if len(ratios) == len(legs):
        spread = max(ratios) - min(ratios)
        # A rescale is every leg moving by the SAME factor. The spread test alone
        # cannot say that: when three legs are untouched their ratios are exactly
        # 1.0, the spread is tiny, and "almost nothing moved" passes a test meant
        # for "everything moved together" — which is how a one-cent low became a
        # split seven times. Require the common factor to actually be a rescale.
        common = sum(ratios) / len(ratios)
        rescaled = abs(common - 1.0) > RESCALE_REL_TOL
        if rescaled and spread <= RESCALE_REL_TOL * max(abs(r) for r in ratios):
            return "uniform_rescale"
    return "bar_revision"

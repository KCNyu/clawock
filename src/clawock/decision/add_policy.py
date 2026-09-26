"""The add side's policy, read once and applied the same way by every entry.

`config/add-alpha-policy.json` is the data; this module is the one piece of code
that turns it into numbers. Everything here is pure — no file, clock or network
access — so the three entries that consume it compose the same logic from the
context they already hold:

========================  ===================================================
entry                     what it calls here
========================  ===================================================
brief decision packet     ``tier_terms`` (via ``add_alpha.confirmation_setup``
(``decision/packet.py``)  and ``early_trend.exploration_setup``) and
                          ``tranche_plan`` — the size of an authorised tranche
brief opportunity reads   ``read_params`` + ``ENTRY_PROFILES["brief"]`` →
(``brief_preflight``)     ``add_side.radar`` / ``add_side.read_rows``
intraday add-side reads   ``read_params`` + ``ENTRY_PROFILES["intraday"]`` →
(``intraday_preflight``)  the same ``add_side.radar`` / ``add_side.read_rows``
evaluation                ``add_alpha_walkforward`` / ``add_shapes`` reuse the
                          same primitives on historical bars
========================  ===================================================

Why it exists: before it, the brief and the intraday slot each parsed the policy
with their own copy of the defaults, built the opportunity radar in two places,
and the intraday card quoted ``exploration_tranche_pct`` as "the" size cap while
the packet sized cold-start at half that and validated at three times it. Making
the add side more aggressive on top of that would have widened two disagreeing
answers, so the differences between entries are now stated as data
(``ENTRY_PROFILES``) and the numbers come from here only.
"""
from __future__ import annotations


#: Defaults for keys a policy file may omit. The only copy — callers must not
#: carry their own fallback numbers (#649/#666: an explicit 0 is legal and must
#: survive, so every read below is an explicit ``is None`` check).
READ_DEFAULTS = {
    "opportunity_near_pct": 5.0,
    "early_no_chase_zscore": 2.0,
    "exploration_tranche_pct": 0.025,
    "exploration_max_book_pct": 0.03,
    "confirmation_window_sessions": 5,
}

#: How the entries differ. Nothing else may: a threshold that only one entry
#: applies belongs in the policy file, not in a harness branch.
#:
#: * ``close_confirmed`` — the brief reads bars the market settled; the intraday
#:   slot reads a live print over the same bars, so its "close" is pending and
#:   its rows say so.
#: * ``price_source`` — where the radar's close comes from (documentation).
#: * ``information_lane`` — whether graded news reaches ``read_rows``. The
#:   intraday slot has its information summary (morning files + live feeds);
#:   the brief is the run that *writes* those morning files, so its
#:   opportunity read gets none and its decision path uses the evidence graph
#:   through ``add_alpha.classify_authority`` instead. A news-backed pullback
#:   candidate is therefore an intraday-only row by input, not by code.
#: * ``anomalies`` / ``mover_news`` — intraday price movers and the filings
#:   probed for them exist only in a slot.
ENTRY_PROFILES = {
    "brief": {
        "close_confirmed": True,
        "price_source": "settled daily bars (memory/bars)",
        "information_lane": False,
        "anomalies": False,
        "mover_news": False,
    },
    "intraday": {
        "close_confirmed": False,
        "price_source": "live print over the slot's cached daily bars",
        "information_lane": True,
        "anomalies": True,
        "mover_news": True,
    },
}


def _value(policy: dict | None, key: str):
    raw = (policy or {}).get(key)
    return raw if raw is not None else READ_DEFAULTS[key]


def read_params(policy: dict | None) -> dict:
    """The radar thresholds every reader uses, with the one set of defaults.

    A malformed value falls back to the default instead of raising: a broken
    policy file must not red a brief or a slot (both harnesses already treated
    it that way; this is where that behaviour now lives).
    """
    out = {}
    for key, name in (("opportunity_near_pct", "near_pct"),
                      ("early_no_chase_zscore", "no_chase_z")):
        try:
            out[name] = float(_value(policy, key))
        except (TypeError, ValueError):
            out[name] = float(READ_DEFAULTS[key])
    return out


def entry_profile(entry: str) -> dict:
    try:
        return dict(ENTRY_PROFILES[entry])
    except KeyError:
        raise ValueError(f"unknown add-side entry {entry!r}; "
                         f"expected one of {sorted(ENTRY_PROFILES)}") from None


#: Tranche level each tier reaches, as a share of a full validated campaign.
TARGET_TRANCHE_LEVEL = {
    "validated": 1.0,
    "exploration": 0.25,
    "exploration_cold_start": 0.125,
}


def tier_terms(policy: dict, tier: str) -> dict:
    """``max_tranches`` / ``tranche_pct_of_position`` / level for one tier.

    The single place that maps an authority tier to its size, read by the
    packet's alpha and early-trend setups and quoted by the add-side reads.
    """
    if tier == "validated":
        return {
            "max_tranches": int(policy["validated_max_tranches"]),
            "tranche_pct_of_position": float(policy["validated_tranche_pct"]),
            "target_tranche_level": TARGET_TRANCHE_LEVEL[tier],
        }
    if tier == "exploration_cold_start":
        # Half the exploration slice, one tranche. The families are least
        # validated exactly while they are warming up, so the one period that
        # relaxes the count is the one that must not relax the size.
        return {
            "max_tranches": 1,
            "tranche_pct_of_position": float(policy["cold_start_tranche_pct"]),
            "target_tranche_level": TARGET_TRANCHE_LEVEL[tier],
        }
    if tier == "exploration":
        raw_max = policy.get("exploration_max_tranches")
        return {
            "max_tranches": int(raw_max) if raw_max is not None else 1,
            "tranche_pct_of_position": float(_value(policy, "exploration_tranche_pct")),
            "target_tranche_level": TARGET_TRANCHE_LEVEL[tier],
        }
    raise ValueError(f"tier {tier!r} has no size")


def size_cap_text(policy: dict | None) -> str | None:
    """How a read quotes the size ceiling of a not-yet-authorised add.

    A read never sizes; it names the tier a candidate would at most reach
    (exploration) with the number ``tier_terms`` gives the packet.
    """
    try:
        pct = tier_terms(policy or {}, "exploration")["tranche_pct_of_position"]
    except (TypeError, ValueError, KeyError):
        return None
    return f"上限探索档 {round(pct * 100, 4):g}%(add-alpha-policy)"


EXPLORATION_TIERS = ("exploration", "exploration_cold_start")

#: Concentration ceiling for one name inside its market's invested book.
TARGET_MAX_PCT = 60.0


def tranche_plan(
    *,
    tier: str,
    price: float | None,
    lot: int | None,
    shares: int,
    current_value: float | None,
    capital: float,
    cash: float,
    setup_pcts: list[float],
    sizing_multiplier: float = 1.0,
    exploration_max_book_pct: float = 0.03,
) -> dict:
    """Shares for the next tranche of an add, before thesis/blocker gates.

    ``capital`` is the market leg's invested book, ``cash`` its cash. Integer
    shares (US) or whole board lots (HK); ``lot`` None means the lot is unknown
    and nothing can be sized.
    """
    target_fraction = TARGET_MAX_PCT / 100
    # Solve (position + add) / (invested_book + add) <= target. Cash is an
    # affordability bound, not denominator camouflage.
    room_value = max(
        0.0,
        (target_fraction * capital - (current_value or 0))
        / (1 - target_fraction),
    )
    max_value = min(max(cash, 0.0), room_value)
    position_room_shares = (
        int(max_value // (price * lot)) * lot
        if price and lot else 0
    )
    tranche_pct = min(setup_pcts) if setup_pcts else 0.05
    desired = int(shares * tranche_pct * sizing_multiplier)
    rounded = ((desired // lot) * lot if lot else 0)
    exploration_budget = max(0.0, capital * exploration_max_book_pct)
    # Both exploration tiers are budgeted (cloud review F17): the cold-start
    # half-slice used to fall through to the validated branch below and get
    # max(lot, rounded) — the least validated tier sized the most loosely.
    if tier in EXPLORATION_TIERS:
        unit_value = price * lot if price and lot else None
        # The tranche % is the target step; the market-book cap is the hard
        # execution envelope. One indivisible broker unit may bridge that small
        # gap, but an expensive HK board lot may not masquerade as a tiny
        # experiment.
        suggested = (
            rounded if rounded > 0
            else lot if unit_value and unit_value <= exploration_budget
            else 0
        )
    else:
        # Existing validated/basic campaigns retain one market unit as their
        # minimum executable size, subject to cash and concentration room.
        suggested = max(lot, rounded) if lot else 0
    suggested = min(suggested, position_room_shares)
    return {
        "desired_shares": desired,
        "suggested_shares": suggested,
        "position_room_shares": position_room_shares,
        "exploration_budget_value": round(exploration_budget, 2),
        "target_max_pct": TARGET_MAX_PCT,
    }

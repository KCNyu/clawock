"""Three kinds of finding about a proposed decision, kept apart (#2842).

One validator used to answer three different questions with one list of
errors: is this true, can this be done, and would the registered policy have
done it. A proposal that departed from a preset entry price was refused with
the same authority as one that sold shares the book does not hold.

    fact         a reference that does not exist, a number that does not add
                 up, a ticker nothing can price. The artifact is wrong.
    feasibility  cash, inventory, board lots, an order already open, an
                 obligation still in force, an authorisation kcn has not given.
                 The view may stand; the action cannot be carried out as
                 written.
    strategy     a registered rule would not have done this: no approved
                 setup, an unescalated event, a tranche above the policy's.
                 Recorded as an objection and printed next to the decision. It
                 never rejects, and nothing rewrites the proposal to agree.

`fact` and `feasibility` block. `strategy` does not, and a blocked proposal is
reported with a code from its own channel so "repair an error" and "change the
answer to the one the system prefers" can be counted separately.
"""
from __future__ import annotations

FACT = "fact"
FEASIBILITY = "feasibility"
STRATEGY = "strategy"
CHANNELS = (FACT, FEASIBILITY, STRATEGY)
BLOCKING = frozenset({FACT, FEASIBILITY})


#: The authorisations a plan is held to: what each one binds and where its
#: number lives. These are choices about risk, not facts about the market —
#: listed so that a decision can record which set it was reviewed under, and
#: so that changing one is a visible change of version rather than an edit to
#: a validator (#2842).
AUTHORIZATIONS = (
    ("AUTH_OBLIGATION_IN_FORCE",
     "a leveraged product at or below the hard-stop line, or under a regime "
     "de-lever, must be cut or swapped", "caps.lev_etf_stop_pct; lev_regime"),
    ("AUTH_OBLIGATION_SHORTFALL",
     "a hard stop is answered by the full position", "required_reduction.minimum_shares"),
    ("AUTH_ADD_FROZEN_BY_BREACH",
     "no add or T trade on a name with an open risk breach", "risk_guardrail breaches"),
    ("AUTH_LEVERAGED_ADD",
     "no add to a daily-reset leveraged product without validated evidence",
     "add-alpha-policy"),
    ("AUTH_EXCEEDS_ROOM",
     "an add stays inside cash and the single-name target", "target_max_pct"),
    ("AUTH_SWAP_MANDATE",
     "a risk-rule buy is the named target, paired with its sell, within the "
     "mandate's value", "required_reduction.swap_to"),
    ("AUTH_NO_SWAP_MANDATE",
     "a buy may claim a risk rule only where a breach prescribes it",
     "required_reduction.swap_to"),
)


def authorization_set(*, caps: dict | None, respond_only: list[str],
                      target_max_pct=None) -> dict:
    """The current authorisations with a version that changes when they do."""
    import hashlib  # noqa: PLC0415
    import json  # noqa: PLC0415

    body = {
        "rules": [{"code": code, "binds": binds, "parameter": parameter}
                  for code, binds, parameter in AUTHORIZATIONS],
        "caps": dict(sorted((caps or {}).items())),
        # Caps in this list are answered, never forced (`risk.RESPOND_ONLY_TYPES`).
        "respond_only_breach_types": sorted(respond_only),
        "target_max_pct": target_max_pct,
    }
    digest = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return {"version": f"auth-{digest[:12]}", **body}


def finding(channel: str, code: str, message: str, *, index: int | None = None,
            ticker: str | None = None) -> dict:
    """One finding. `code` is stable; `message` is for a person."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown receipt channel {channel!r}")
    prefix = {FACT: "FACT_", FEASIBILITY: ("FEAS_", "AUTH_"), STRATEGY: "STRAT_"}[channel]
    if not code.startswith(prefix):
        raise ValueError(f"{code} does not belong to the {channel} channel")
    return {"channel": channel, "code": code, "message": message,
            "index": index, "ticker": ticker}


def is_blocking(item: dict) -> bool:
    return item.get("channel") in BLOCKING


def blocking(findings: list[dict]) -> list[dict]:
    return [item for item in findings if is_blocking(item)]


def objections(findings: list[dict]) -> list[dict]:
    return [item for item in findings if item.get("channel") == STRATEGY]


def tagged(item: dict) -> str:
    """The finding as one line, ending in its code."""
    return f"{item['message']} [{item['code']}]"


def review_of(findings: list[dict]) -> dict:
    """What a decision keeps of its review: the objections it was filed over.

    Only decisions that passed the blocking channels are ever persisted, so the
    stored review is the strategy channel plus any authorisation still pending.
    """
    return {
        "agrees_with_policy": not objections(findings),
        "objections": [{"code": item["code"], "message": item["message"]}
                       for item in objections(findings)],
    }


#: An objection in the reader's words, for the card and the page. The stored
#: `message` names the decision and the numbers; this names the rule.
OBJECTION_WORDS = {
    "STRAT_SELL_WITHOUT_ESCALATED_EVENT": "卖出没有已升级事件支持",
    "STRAT_ADD_OUTSIDE_POLICY": "加仓不在登记的加仓策略之内",
    "STRAT_ACTIVE_WITHOUT_CATALYST": "主动动作没有催化、登记形态或风控规则",
    "STRAT_EVENT_NOT_ESCALATED": "所引事件未被资讯策略升级",
    "STRAT_SIZE_ABOVE_POLICY_TRANCHE": "股数超过登记策略的单批上限",
    "STRAT_ENTRY_DIFFERS_FROM_SETUP": "入场、失效或批次与所引的登记形态不同",
    "STRAT_VALIDITY_DIFFERS_FROM_SETUP": "有效期与所引的登记形态不同",
    "STRAT_NOT_A_REGISTERED_SETUP": "入场位由本计划自定，不对应登记形态",
}
AUTHORIZATION_WORDS = {"entry_gate_required": "持仓外标的，尚未过建仓前研究闸"}


def review_words(review: dict | None) -> list[str]:
    """What a stored `policy_review` says, as short reader-facing phrases."""
    if not isinstance(review, dict):
        return []
    words = [OBJECTION_WORDS.get(item.get("code"), item.get("code") or "")
             for item in review.get("objections") or [] if isinstance(item, dict)]
    pending = AUTHORIZATION_WORDS.get(review.get("authorization"))
    return list(dict.fromkeys(word for word in [*words, pending] if word))


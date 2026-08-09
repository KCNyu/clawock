"""KCNyu-only sections injected into the portable dashboard projection."""

from clawock_kcnyu.harness.brief_preflight import (
    compute_breakeven_math,
    compute_concentration,
    compute_risk_guardrail,
)


def guardrail_sections(portfolio, risk, lev_regime=None):
    us_book = portfolio['portfolios']['us_stocks']
    hk_book = portfolio['portfolios']['hk_stocks']
    hk_holdings = hk_book['holdings']
    us_holdings = us_book['holdings']
    guardrail = compute_risk_guardrail(
        hk_holdings,
        us_holdings,
        compute_concentration(hk_holdings),
        compute_concentration(us_holdings),
        risk,
        lev_regime=lev_regime,
    )
    breakeven = compute_breakeven_math(
        hk_holdings, us_holdings, lev_regime=lev_regime)
    if isinstance(guardrail, dict) and isinstance(
        guardrail.get('lev_regime'), dict
    ):
        guardrail['lev_regime_tier'] = guardrail['lev_regime'].get('tier')
        guardrail.pop('lev_regime')
    return {'risk_guardrail': guardrail, 'breakeven_math': breakeven}

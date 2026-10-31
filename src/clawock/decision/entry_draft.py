"""Unassessed entry-gate templates. Never write them into the authorization archive."""
from datetime import datetime, timezone

from . import entry


def build(candidate, *, workspace):
    """Populate identity and questions only; all investment checks remain unknown."""
    ticker, market = candidate['ticker'], candidate['market']
    vetoes = entry.load_vetoes(workspace / 'config/entry-gate-vetoes.json', missing_ok=True)
    return {
        'schema_version': 1, 'gate_id': f'draft-{market}-{ticker}',
        'ticker': ticker, 'market': market, 'instrument_kind': 'company',
        'sector': candidate.get('sector_label') or candidate.get('sector') or '行业待核验',
        'assessed_at': datetime.now(timezone.utc).isoformat(),
        'quote': {'price': None, 'currency': 'HKD' if market == 'HK' else 'USD',
                  'as_of': None, 'source_class': 'tencent_quote' if market == 'HK' else 'analyze_us_stocks'},
        'information': entry.grade_information([]),
        'mechanism': '', 'key_variables': [],
        'checks': [{'id': key, 'verdict': 'unknown', 'finding': '待补一手证据', 'evidence_ids': []}
                   for key in entry.COMPANY_CHECKS],
        'vetoes': [{'id': key, 'status': 'unknown', 'finding': '待核验硬否决',
                    'evidence_ids': [], 'exception': None} for key in sorted(vetoes)],
        'mirror_test': [], 'evidence': [],
        'next_evidence': [
            {'question': '核验报价时点、交易场次与价格口径', 'where_to_look': 'clawock fetch-peers'},
            {'question': '核验行业、商业模式、估值、治理和下行风险',
             'where_to_look': 'HKEX/issuer IR' if market == 'HK' else 'SEC/issuer IR'},
            {'question': '补齐关键变量与五句镜像测试，核验每项硬否决', 'where_to_look': 'skills/entry-gate/SKILL.md'},
        ],
        'verdict': 'gray_needs_evidence', 'routing': entry.ROUTING[(market, 'company')],
    }

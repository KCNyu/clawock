"""Pure trading-prose checks shared by workflow and harness output gates."""
import re

ADVISORY_MARK = '(advisory)'

# Words that only exist on the writer's side of the prompt. kcn reads the pushed
# message; he never sees a preflight, a decision packet or a context file, so a
# sentence built on them is the prompt showing through rather than analysis.
# Every entry was observed in delivered prose, not guessed: 2026-09-14 HK mid
# "00100 / 02208 / 03032 / 03033 全部 hold_and_watch packet 锁定"; 2026-09-01
# "按 harness 严令只能停在 `add_side_reads: wait`"; 2026-09-09 card "9/9
# preflight 仍 4 breach". 15 of 244 prose bodies sent 2026-08-31..09-14 carried
# one. The first-person kind ("我将为您…" / "根据以上指令") was searched for and
# never found, so it is not listed.
#
# ASCII boundaries are explicit lookarounds: `\b` does not fire between
# "packet" and a following 锁, because CJK characters count as word characters.
PIPELINE_TERMS = (
    'harness', 'preflight', 'postflight', 'packet', 'sidecar',
    'context_id', 'raw_wechat_block', 'wechat_prefix', 'SKILL.md',
)
_PIPELINE_TERM = re.compile(
    r'(?<![A-Za-z0-9_])(' + '|'.join(re.escape(t) for t in PIPELINE_TERMS)
    + r')(?![A-Za-z0-9_])', re.IGNORECASE)


def check_pipeline_self_reference(text, label='散文'):
    """One advisory issue when model-written text names pipeline internals.

    Advisory on purpose, like check_numeric_claims: the sentence around the word
    is usually a correct read ("风控只允许持有观察") phrased in the wrong
    vocabulary, and turning 6% of otherwise good slots into data-block-only sends
    would cost kcn the analysis to spare him one word. The prompt rule in the
    SKILLs is the fix; this is what makes a relapse visible.
    """
    found = []
    for match in _PIPELINE_TERM.finditer(text or ''):
        term = match.group(1).lower()
        if term not in found:
            found.append(term)
    if not found:
        return []
    return [f'{label}出现内部管线术语（{", ".join(found)}）—— 读者看不到管线，'
            f'改写成交易语言 {ADVISORY_MARK}']


# A context field or enum name printed in the judgment. The pipeline-term list
# above names words; it cannot name every key, and 2026-09-25 HK 14:33 shipped
# 「本档无实质变化（semantic_unchanged）」 with a clean pass because
# `semantic_unchanged` was on no list. A snake_case identifier (or a `key=value`
# pair: 2026-09-24 US 「CRCL verdict=wait」) is never trading language, so the
# shape is the rule rather than a vocabulary. Escalating, unlike the word list:
# an identifier is unambiguous, and a card that shows one must say so on top.
_IDENTIFIER = re.compile(
    r'(?<![A-Za-z0-9_./-])([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+)(?![A-Za-z0-9_])')
# Two letters at least: 「z=2.22」 is the zscore shorthand the card itself
# prints as 「z 2.22」 (2026-09-25 US 22:03), not a field name.
_KEY_VALUE = re.compile(r'(?<![A-Za-z0-9_])([a-z][a-z0-9_]+)\s*=\s*[A-Za-z0-9_]')


def check_identifier_leak(text, label='判断段'):
    """One escalating issue listing every field/enum identifier in `text`."""
    found = []
    for pattern in (_IDENTIFIER, _KEY_VALUE):
        for match in pattern.finditer(text or ''):
            if match.group(1) not in found:
                found.append(match.group(1))
    if not found:
        return []
    return [f'{label}出现字段名/内部标识（{", ".join(found[:4])}）—— 读者看不到 context，'
            f'改写成交易语言']

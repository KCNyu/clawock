"""Pure trading-prose checks shared by workflow and harness output gates."""
import re
from importlib.resources import files


def storytelling_prompt():
    return files('clawock').joinpath('trading-prose.md').read_text(encoding='utf-8').strip()


ADVISORY_MARK = '(advisory)'


class Advisory(str):
    """A finding whose severity is assigned by the validator, not its wording."""

    def __new__(cls, message):
        return super().__new__(cls, f'{message} {ADVISORY_MARK}')

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
    return [Advisory(f'{label}出现内部管线术语（{", ".join(found)}）—— 读者看不到管线，'
                     '改写成交易语言')]


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


# These are editorial hints. They must never make an otherwise correct report
# drop its judgment or make the editor touch the source data.
_VAGUE_AUTHORITY = re.compile(r'业内普遍认为|业内认为|市场普遍认为|专家普遍认为')
_ATTRIBUTION = re.compile(r'据\s*[^，。！？；：,:]{1,40}|[^，。！？；：,:]{1,40}(?:指出|表示|报道|披露|撰文)[：:]?')
_QUOTED = re.compile(r'《[^》\n]*》|“[^”\n]*”|「[^」\n]*」|『[^』\n]*』|"[^"\n]*"')
_STOCK_CLOSER = re.compile(r'^\s*(?:总而言之|综上所述|归根结底)[，,]\s*(.+)')
_GENERIC_CLOSER = re.compile(r'(?:仍需|继续|保持|建议|需要|应当)?\s*(?:谨慎|关注|观望|观察|耐心|跟踪)[。！!\s]*$')
MEASUREMENT = '\uFFF0'
CITATION = '\uFFF1'
_SENTENCE_END = re.compile(r'[。！？；!?;\n]')


def check_storytelling(draft, label, *, dense_measurements=True, repeated_measurement=False):
    """Flag rhetorical tics and strings of measurements in authored prose."""
    findings = []
    sentences = _SENTENCE_END.split(_QUOTED.sub(' ', draft))
    if any(_VAGUE_AUTHORITY.search(sentence) and CITATION not in sentence
           and not _ATTRIBUTION.search(sentence) for sentence in sentences):
        findings.append('归因没说是谁')
    lines = draft.rstrip().splitlines()
    if lines and (closer := _STOCK_CLOSER.match(lines[-1])) and _GENERIC_CLOSER.fullmatch(closer[1]):
        findings.append('套话收尾')
    if any(sentence.count('——') > 1 for sentence in sentences):
        findings.append('一句里连用破折号')
    if dense_measurements and any(sentence.count(MEASUREMENT) >= 3 for sentence in sentences):
        findings.append('一句里连报多项读数')
    if repeated_measurement:
        findings.append('重复引用同一数值字段')
    if not findings:
        return []
    return [Advisory(f'{label}写作提示（{"、".join(findings)}），留下影响判断的那件事')]


_FENCE_LINE = re.compile(r'^ {0,3}(`{3,}|~{3,})(.*)$')


def section_prose_lines(text):
    """Yield (offset, line) for lines outside Markdown fenced code blocks."""
    fence = None
    offset = 0
    for raw_line in (text or '').splitlines(keepends=True):
        line = raw_line.rstrip('\r\n')
        match = _FENCE_LINE.match(line)
        if fence:
            if (match and match[1][0] == fence[0] and len(match[1]) >= len(fence)
                    and not match[2].strip(' \t')):
                fence = None
        elif match and (match[1][0] == '~' or '`' not in match[2]):
            fence = match[1]
        else:
            yield offset, line
        offset += len(raw_line)


_PEER_NAG = (
    (re.compile(r'^\s*(?:题材|板块|同业)\s*[加减强弱+−-][，,、 /]+(?:自己|个股|自身)\s*[加减强弱+−-]'), '用实际同业差别代替四选一开头'),
    (re.compile(r'^\s*(?:这一格还是老样子[，,]\s*)?(?:继续观察|维持观望|看情况)[。！\s]*$'), '写明继续观察的具体条件'),
    (re.compile(r'^\s*(?:被市场抛售[，,]\s*所以掉队|跟板块\s*beta[，,]\s*没有自己的消息)[。！\s]*$', re.I), '指出判断所依据的成交、同行或消息'),
)


def peer_style_issues(value):
    if not isinstance(value, str):
        return []
    return [Advisory(f'简报同业判断：{note}') for pattern, note in _PEER_NAG
            if pattern.search(value)]

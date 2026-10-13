"""What a signal source has to say about itself before it is mounted.

A signal source is a plugin whose readings reach a decision: the factor row,
the bar estimators, a strategy's score, the attention and statement feeds. Each
one carries a module-level `SIGNAL_SOURCE`, and a row that names such a module
is not mounted until the declaration passes `validate`. The shape is the same
for every family, because the questions a reader has are the same:

* `inputs` — what it is computed from, and where that comes from;
* `outputs` — every field it can produce, each with its unit, the window it is
  measured over, and what the field holds when it cannot be measured;
* `missing` — what the whole reading is when its inputs are absent or old.

`missing.policy` is one of `POLICIES`. None of them is "the last value": a
source here may answer null, leave the reading out, or refuse, and it says
which. `serves_stale` exists so that the answer to "does this ever hand back an
old reading as today's" is a field, and the only value accepted is `False`.
"""
from __future__ import annotations

FAMILIES = ('factor', 'technical', 'strategy', 'sentiment')

#: What a source does when it cannot measure.
#: `null`: the field is present and null. `omitted`: the reading is left out
#: and the reason is reported beside it. `refused`: the call raises.
POLICIES = ('null', 'omitted', 'refused')

_INPUT_KEYS = ('name', 'what', 'source')
_OUTPUT_KEYS = ('field', 'unit', 'window', 'missing')


class DeclarationError(ValueError):
    """A signal source that does not say what a reader needs to know."""


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(declaration, where: str = 'SIGNAL_SOURCE') -> dict:
    """The declaration, or a `DeclarationError` naming every gap in it."""
    if not isinstance(declaration, dict):
        raise DeclarationError(f'{where}: must be a dict, got {type(declaration).__name__}')
    gaps = []
    for key in ('id', 'summary'):
        if not _text(declaration.get(key)):
            gaps.append(f'{key} is missing')
    if declaration.get('family') not in FAMILIES:
        gaps.append(f'family must be one of {FAMILIES}, got {declaration.get("family")!r}')
    for label, keys in (('inputs', _INPUT_KEYS), ('outputs', _OUTPUT_KEYS)):
        rows = declaration.get(label)
        if not isinstance(rows, (list, tuple)) or not rows:
            gaps.append(f'{label} must list at least one row')
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                gaps.append(f'{label}[{index}] must be a dict')
                continue
            named = row.get(keys[0]) if _text(row.get(keys[0])) else index
            gaps.extend(f'{label}[{named}].{key} is missing'
                        for key in keys if not _text(row.get(key)))
    outputs = declaration.get('outputs')
    fields = [row.get('field') for row in outputs if isinstance(row, dict)] \
        if isinstance(outputs, (list, tuple)) else []
    repeated = sorted({field for field in fields if _text(field) and fields.count(field) > 1})
    if repeated:
        gaps.append(f'outputs repeat {repeated}')
    missing = declaration.get('missing')
    if not isinstance(missing, dict):
        gaps.append('missing must say what the reading is without its inputs')
    else:
        if missing.get('policy') not in POLICIES:
            gaps.append(f'missing.policy must be one of {POLICIES}, got {missing.get("policy")!r}')
        if not _text(missing.get('detail')):
            gaps.append('missing.detail is missing')
        if missing.get('serves_stale') is not False:
            gaps.append('missing.serves_stale must be False: a source may answer null, '
                        'leave the reading out or refuse, never hand back an old one')
    if gaps:
        raise DeclarationError(f'{where}: ' + '; '.join(gaps))
    return declaration


def of(plugin, where: str | None = None) -> dict | None:
    """A plugin's validated declaration, or None when it is not a signal source."""
    declaration = getattr(plugin, 'SIGNAL_SOURCE', None)
    if declaration is None:
        return None
    label = where or str(getattr(plugin, '__name__', plugin))
    return validate(declaration, f'{label}.SIGNAL_SOURCE')


def fields(declaration: dict) -> list[str]:
    return [row['field'] for row in declaration['outputs']]

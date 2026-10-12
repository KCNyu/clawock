"""Every call a test makes into a migrated plugin is also made into the code it replaced.

Eight modules moved into plugins (add policy, add authority, the left side, the
add-side reads, the pre-position lane, the intraday strategy policies, the bar
estimators and the signal panel). The code they held is still in the tree as
`legacy_*`, and stays until the plugins have run in production. This fixture is
the comparison that has to hold in the meantime: while it is armed, each public
function of a plugin is wrapped, and an outermost call into it runs the legacy
function on a copy of the same arguments. The two must return values with the
same `repr` (floats included), raise the same error, and leave their arguments
in the same state. So the corpus is every call the suite already makes.

Details that keep the comparison honest:

* A callable argument (a bar fetcher, say) is called once, by the plugin; the
  legacy side is handed its recorded answers, and asking for one the plugin
  never asked for is itself a mismatch.
* A module global a test has patched on the plugin is patched on the legacy
  module for the length of the legacy call.
* A mismatch is collected and failed at the end of the test, because the
  callers under test often catch `Exception`.

Not compared: functions that write (`record_history`, `evaluate_cached`,
`main`), and the signal panel's memo key, which hashes the module's own source
and so differs by construction.
"""
from __future__ import annotations

import copy
import functools
import importlib
import threading
import types

PAIRS = (
    ('clawock.strategies.plugins.add_policy', 'clawock.decision.legacy_add_policy'),
    ('clawock.strategies.plugins.add_alpha', 'clawock.decision.legacy_add_alpha'),
    ('clawock.strategies.plugins.left_side', 'clawock.decision.legacy_left_side'),
    ('clawock.strategies.plugins.add_side', 'clawock.decision.legacy_add_side'),
    ('clawock.strategies.plugins.preposition', 'clawock.decision.legacy_preposition'),
    ('clawock.strategies.plugins.intraday_policy', 'clawock.decision.legacy_intraday_policy'),
    ('clawock.strategies.plugins.bar_signals', 'clawock.market_data.legacy_bar_signals'),
    ('clawock.strategy_lab.plugins.signal_panel', 'clawock.evaluation.legacy_signal_panel'),
)
NOT_COMPARED = {'apply', 'record_history', 'evaluate_cached', 'main', 'evaluation_key', 'memo_path'}
#: Module globals that differ between a plugin and its legacy module by design.
OWN_GLOBALS = {'add_policy', 'left_side', 'live_plugins', 'sys', 'name', 'EVALUATION_SOURCES'}

_state = threading.local()
mismatches: list[str] = []
compared: dict[str, int] = {}


class _Unasked(Exception):
    pass


def _key(args, kwargs):
    return repr((args, sorted(kwargs.items())))


def _recording(fn, tape):
    def call(*args, **kwargs):
        answers = tape.setdefault(_key(args, kwargs), [])
        try:
            value = fn(*args, **kwargs)
        except Exception as exc:
            answers.append(('error', exc))
            raise
        answers.append(('value', copy.deepcopy(value)))
        return value
    return call


def _replaying(tape):
    asked: dict[str, int] = {}

    def call(*args, **kwargs):
        key = _key(args, kwargs)
        turn = asked.get(key, 0)
        asked[key] = turn + 1
        if turn >= len(tape.get(key, ())):
            raise _Unasked(key)
        kind, value = tape[key][turn]
        if kind == 'error':
            raise value
        return copy.deepcopy(value)
    return call


def _is_callback(value):
    return isinstance(value, (types.FunctionType, types.MethodType, functools.partial))


def _same(mine, theirs):
    try:
        if mine == theirs:
            return True
    except Exception:
        pass
    return repr(mine) == repr(theirs)


def _outcome(fn, args, kwargs):
    try:
        return ('value', fn(*args, **kwargs))
    except _Unasked as exc:
        return ('asked a callback for what the plugin never asked', str(exc))
    except Exception as exc:
        return ('error', f'{type(exc).__name__}: {exc}')


def _data(args, kwargs, raw_args, raw_kwargs):
    return ([value for value, raw in zip(args, raw_args) if not _is_callback(raw)],
            sorted((key, value) for key, value in kwargs.items()
                   if not _is_callback(raw_kwargs[key])))


def _wrap(plugin, legacy, fn_name, armed):
    original, reference = getattr(plugin, fn_name), getattr(legacy, fn_name)
    label = f'{plugin.__name__.rsplit(".", 1)[-1]}.{fn_name}'

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        if getattr(_state, 'depth', 0):
            return original(*args, **kwargs)

        def split(value):
            if not _is_callback(value):
                return value, copy.deepcopy(value)
            tape: dict = {}
            return _recording(value, tape), _replaying(tape)
        try:
            pairs = [split(value) for value in args]
            named = {key: split(value) for key, value in kwargs.items()}
        except Exception:
            # An argument that cannot be copied cannot be handed to both sides.
            return original(*args, **kwargs)
        theirs_args = [pair[1] for pair in pairs]
        theirs_kwargs = {key: pair[1] for key, pair in named.items()}
        failure = None
        _state.depth = 1
        try:
            try:
                value = original(*[pair[0] for pair in pairs],
                                 **{key: pair[0] for key, pair in named.items()})
                got = ('value', value)
            except Exception as exc:
                failure, got = exc, ('error', f'{type(exc).__name__}: {exc}')
            # A global a test patched on the plugin is patched on the legacy
            # module for the length of its call.
            patched = {key: now for key, now in vars(plugin).items()
                       if key in armed and now is not armed[key] and key not in OWN_GLOBALS}
            absent = object()
            before = {key: vars(legacy).get(key, absent) for key in patched}
            vars(legacy).update(patched)
            try:
                want = _outcome(reference, theirs_args, theirs_kwargs)
            finally:
                for key, was in before.items():
                    if was is absent:
                        del vars(legacy)[key]
                    else:
                        vars(legacy)[key] = was
        finally:
            _state.depth = 0
        compared[label] = compared.get(label, 0) + 1
        if got[0] != want[0] or not _same(got[1], want[1]):
            mismatches.append(f'{label}: plugin {got[0]} {repr(got[1])[:300]} '
                              f'!= legacy {want[0]} {repr(want[1])[:300]}')
        elif not _same(_data(args, kwargs, args, kwargs),
                       _data(theirs_args, theirs_kwargs, args, kwargs)):
            mismatches.append(f'{label}: the two left their arguments in different states')
        if failure is not None:
            raise failure
        return value
    return wrapper
def arm():
    """Wrap every public function of every plugin; returns the undo."""
    undo = []
    for plugin_name, legacy_name in PAIRS:
        plugin, legacy = importlib.import_module(plugin_name), importlib.import_module(legacy_name)
        armed = dict(vars(plugin))
        for fn_name, value in list(vars(plugin).items()):
            if (isinstance(value, types.FunctionType) and value.__module__ == plugin_name
                    and not fn_name.startswith('_') and fn_name not in NOT_COMPARED):
                wrapped = _wrap(plugin, legacy, fn_name, armed)
                armed[fn_name] = wrapped
                setattr(plugin, fn_name, wrapped)
                undo.append((plugin, fn_name, value))

    def disarm():
        for plugin, fn_name, value in undo:
            setattr(plugin, fn_name, value)
    return disarm

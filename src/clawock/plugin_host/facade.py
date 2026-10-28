"""A module that keeps an import path and answers from a mounted service.

When an implementation moves into a plugin, its readers keep importing the old
path. `install(__name__, service)` turns that module into a view of the live
service: reading an attribute reads the service's, and setting one sets the
service's, so a caller or a test that reaches for `module.NAME` reaches the
code the live row actually mounted.

The view holds none of those names itself, so a write through it covers the
service's value and deleting the name through the view uncovers it again: the
covered value is put back, and only a name the view never covered is deleted
from the service. pytest >= 9.2 undoes `monkeypatch.setattr` on a module by
deleting the name when the module's own `__dict__` did not hold it; without
this, that undo deleted the plugin's real global (master CI, 2026-10-28).
"""
from __future__ import annotations

import sys
import types

from clawock.plugin_host import live

_MISSING = object()


class _Facade(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return getattr(live.service(self.__dict__['_facade_service']), name)

    def __setattr__(self, name, value):
        if name.startswith('__'):
            return super().__setattr__(name, value)
        target = live.service(self.__dict__['_facade_service'])
        self.__dict__['_facade_covered'].setdefault(name, []).append(
            (target, getattr(target, name, _MISSING)))
        setattr(target, name, value)

    def __delattr__(self, name):
        if name.startswith('__'):
            return super().__delattr__(name)
        covered = self.__dict__['_facade_covered'].get(name)
        if not covered:
            return delattr(live.service(self.__dict__['_facade_service']), name)
        target, original = covered.pop()
        if not covered:
            del self.__dict__['_facade_covered'][name]
        if original is _MISSING:
            delattr(target, name)
        else:
            setattr(target, name, original)


def install(module_name: str, service: str) -> None:
    module = sys.modules[module_name]
    module.__dict__['_facade_service'] = service
    module.__dict__['_facade_covered'] = {}
    module.__class__ = _Facade

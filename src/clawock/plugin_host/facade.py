"""A module that keeps an import path and answers from a mounted service.

When an implementation moves into a plugin, its readers keep importing the old
path. `install(__name__, service)` turns that module into a view of the live
service: reading an attribute reads the service's, and setting one sets the
service's, so a caller or a test that reaches for `module.NAME` reaches the
code the live row actually mounted.
"""
from __future__ import annotations

import sys
import types

from clawock.plugin_host import live


class _Facade(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return getattr(live.service(self.__dict__['_facade_service']), name)

    def __setattr__(self, name, value):
        if name.startswith('__'):
            return super().__setattr__(name, value)
        setattr(live.service(self.__dict__['_facade_service']), name, value)

    def __delattr__(self, name):
        if name.startswith('__'):
            return super().__delattr__(name)
        delattr(live.service(self.__dict__['_facade_service']), name)


def install(module_name: str, service: str) -> None:
    module = sys.modules[module_name]
    module.__dict__['_facade_service'] = service
    module.__class__ = _Facade

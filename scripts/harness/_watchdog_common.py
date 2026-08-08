"""Compatibility alias; remove after host watchdogs use clawock-kcnyu."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("clawock_kcnyu.harness._watchdog_common")

"""Compatibility alias; remove after repository callers use clawock-kcnyu."""

import sys
from importlib import import_module

sys.modules[__name__] = import_module("clawock_kcnyu.harness._harness_common")

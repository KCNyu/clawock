#!/usr/bin/env python3
"""Compatibility CLI; production uses the installed KCNyu adapter."""

import sys
from importlib import import_module

if __name__ == "__main__":
    raise SystemExit(import_module("clawock_kcnyu.harness.report_preflight").main())
sys.modules[__name__] = import_module("clawock_kcnyu.harness.report_preflight")

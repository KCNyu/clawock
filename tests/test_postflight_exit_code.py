from __future__ import annotations

import inspect

from clawock.harness import (
    brief_postflight, intraday_postflight, report_postflight,
)
from clawock.harness.validation import postflight_exit_code


def test_shipped_warn_is_not_a_failed_turn():
    # An exec's non-zero exit files the whole cron turn as `error`; 2026-09-11's
    # brief was delivered, committed and published, then filed as
    # `ERR: Exec failed: clawock brief postflight` because warn exited 1.
    assert postflight_exit_code("pass") == 0
    assert postflight_exit_code("warn") == 0
    assert postflight_exit_code("fail") == 2


def test_every_postflight_exits_through_the_shared_rule():
    # The brief postflight exited on raw `status` while the other two used
    # `product`, so an advisory-only brief exited 1 where a report exited 0.
    for module in (brief_postflight, intraday_postflight, report_postflight):
        tail = inspect.getsource(module.main).rstrip().splitlines()[-1]
        assert tail.strip() == "return postflight_exit_code(product)", module

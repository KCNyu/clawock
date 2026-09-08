"""Delivery, with a status a boolean cannot express.

`send_wechat()` returns `(ok, tail)` today, and `ok` means "the CLI exited 0" —
which is not the same as "kcn saw it". WeChat has a documented cold-session
silent drop (upstream wontfix, #81096/#81316): the send is accepted and the
message never arrives, which is exactly why `intraday_watchdog` mirrors to
Telegram when it *judges* a push probably dropped.

So a two-state result is a lie by construction. Four states:

    accepted   handed to the transport; it did not object
    confirmed  the transport says it reached the target
    unknown    accepted, but this channel cannot confirm — WeChat's normal case
    failed     refused, with a reason

`unknown` is the important one. Collapsing it into `accepted` is what makes a
dropped report look delivered; collapsing it into `failed` would trigger
duplicate sends. It has to be its own state.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

# Channels that can tell us a message arrived. WeChat cannot: the CLI reports
# success for a send the cold session silently drops.
CONFIRMING_CHANNELS = frozenset({"telegram"})


def delivery_disabled() -> bool:
    """Whether this process is forbidden from contacting a real transport.

    Tests set this before collection.  Keep the check in the provider itself,
    not only in a harness caller: an import/adapter refactor must never be able
    to bypass the safety boundary by changing which function gets patched.
    """
    return os.environ.get("CLAWOCK_DELIVERY_DISABLED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


_MESSAGE_ID = re.compile(r'"messageId"\s*:\s*"?([^",\s}]+)', re.IGNORECASE)
#: The runtime CLI's own way of saying it stopped waiting for its gateway. It
#: exits non-zero with this, which is the same *event* as our subprocess timing
#: out — not a refusal.
_GATEWAY_TIMEOUT = re.compile(r"gateway timeout after \d+\s*ms", re.IGNORECASE)


def _timed_out_waiting(output: str | None) -> bool:
    """Whether a non-zero exit is the CLI giving up on its own gateway."""
    return bool(output) and bool(_GATEWAY_TIMEOUT.search(output))


def _names_a_message(output: str | None) -> bool:
    """Whether the transport's output identifies a message it accepted.

    Only a real id counts: `"messageId": null` is the transport saying it has
    none, which is the opposite of evidence.
    """
    if not output:
        return False
    return any(m.group(1).lower() not in ("null", "none", "")
               for m in _MESSAGE_ID.finditer(output))


@dataclass(frozen=True)
class DeliveryResult:
    status: str                     # accepted | confirmed | unknown | failed
    channel: str
    target: str
    detail: str = ""
    receipt: str | None = None
    idempotency_key: str | None = None

    STATES = ("accepted", "confirmed", "unknown", "failed")

    def __post_init__(self) -> None:
        if self.status not in self.STATES:
            raise ValueError(
                f"unknown delivery status {self.status!r}; "
                f"expected one of {', '.join(self.STATES)}")

    @property
    def reached_target(self) -> bool:
        """True only when the transport actually confirmed it.

        Deliberately not true for `accepted`/`unknown`: a caller that wants to
        know whether kcn saw the message must not get a yes from a channel that
        cannot answer.
        """
        return self.status == "confirmed"

    @property
    def worth_mirroring(self) -> bool:
        """Whether a backup channel should carry the same message."""
        return self.status in ("unknown", "failed")


class DeliveryProvider(Protocol):
    name: str

    def send(self, channel: str, target: str, message: str, *,
             dry_run: bool = False,
             idempotency_key: str | None = None) -> DeliveryResult:
        ...


class OpenClawDelivery:
    """Today's path: `openclaw message send --json`, unchanged."""

    name = "openclaw"

    def __init__(self, binary: str | None = None, account: str | None = None,
                 timeout: int = 60, runner=None) -> None:
        # Resolve at construction time so one installed wheel can target a
        # non-default runtime without importing host constants.
        from clawock.providers.openclaw import runtime_paths
        self.binary = binary or runtime_paths().binary
        self.account = account
        self.timeout = timeout
        self._runner = runner or self._run

    def rpc_ceiling_ms(self) -> int:
        """How long the CLI may wait for its gateway, in ms — see #1405.

        The rule lives with the runtime it is about, because every call that
        spawns that CLI needs it, not only this one.
        """
        from clawock.providers.openclaw import rpc_ceiling_ms

        return rpc_ceiling_ms(self.timeout)

    def _run(self, cmd):
        # The runtime's own launcher needs `node` on PATH, so a job started from
        # the user crontab cannot spawn it with the PATH it inherited. And the
        # CLI must be told to wait as long as we are waiting, or it abandons the
        # gateway at 10s inside a 60s budget.
        from clawock.providers.openclaw import runtime_env
        done = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self.timeout,
                              env=runtime_env(call_timeout=self.timeout))
        return done.returncode, (done.stdout + done.stderr)

    def send(self, channel: str, target: str, message: str, *,
             dry_run: bool = False,
             idempotency_key: str | None = None) -> DeliveryResult:
        if delivery_disabled():
            return DeliveryResult(
                "failed", channel, str(target),
                detail="delivery blocked by CLAWOCK_DELIVERY_DISABLED",
                idempotency_key=idempotency_key,
            )

        cmd = [self.binary, "message", "send", "--channel", channel,
               "--target", str(target), "-m", message, "--json"]
        if self.account:
            cmd[3:3] = ["--account", self.account]
        if dry_run:
            cmd.append("--dry-run")

        try:
            code, output = self._runner(cmd)
        except FileNotFoundError:
            return DeliveryResult("failed", channel, str(target),
                                  detail=f"{self.binary} is not installed",
                                  idempotency_key=idempotency_key)
        except subprocess.TimeoutExpired:
            # Timed out after handing over the message: it may well have gone.
            # Calling this `failed` would invite a duplicate send.
            return DeliveryResult("unknown", channel, str(target),
                                  detail="timed out waiting for the transport",
                                  idempotency_key=idempotency_key)

        tail = (output or "").strip()[-400:]
        if code != 0:
            # A non-zero exit is not proof that nothing was sent. On 2026-08-31
            # the brief's Telegram co-send was recorded failed at 08:08:50 while
            # the gateway went on to hand Telegram messageId 1164 at 08:08:54 —
            # so the marker said tg_ok=false and the watchdog mirrored a card
            # that had already landed. When the transport's own output names a
            # message it accepted, treat the exit the way a timeout is treated:
            # `unknown`, which still mirrors, rather than `failed`.
            # A gateway timeout joins that rule for the same reason one step
            # earlier: the CLI stopped waiting, which says nothing about what
            # the gateway did next. Measured on 2026-09-08 — both of the day's
            # "failed" sends were sitting in the gateway and went out at 16.5s
            # and 25.7s. `failed` there wrote tg_ok=false into the marker, the
            # watchdog read it as a miss and mirrored a report kcn already had.
            status = ("unknown"
                      if _names_a_message(output) or _timed_out_waiting(output)
                      else "failed")
            return DeliveryResult(status, channel, str(target), detail=tail,
                                  idempotency_key=idempotency_key)
        status = "confirmed" if channel in CONFIRMING_CHANNELS else "unknown"
        return DeliveryResult(status, channel, str(target), detail=tail,
                              idempotency_key=idempotency_key)


def default_provider(account: str | None = None):
    """The provider this workspace delivers through.

    The choice of implementation belongs in the adapter layer, not in whichever
    caller happens to need one — `providers/__init__.py` exists to be the one
    place that knows. The harness asks here, and so does the operator health
    check, which must not import the harness at all
    (`test_system_check_reads_cron_state_only_through_the_core_provider`).
    """
    return OpenClawDelivery(account=account)


@dataclass
class NullDelivery:
    """Records instead of sending — foreign workspaces, dry runs, tests.

    Reports `accepted`, never `confirmed`: nothing was delivered, and a provider
    that claimed otherwise would make a dry run indistinguishable from a send.
    """

    name: str = "null"
    sent: list = field(default_factory=list)

    def send(self, channel: str, target: str, message: str, *,
             dry_run: bool = False,
             idempotency_key: str | None = None) -> DeliveryResult:
        self.sent.append({"channel": channel, "target": target,
                          "message": message, "dry_run": dry_run,
                          "idempotency_key": idempotency_key})
        return DeliveryResult("accepted", channel, str(target),
                              detail="recorded by the null provider; not sent",
                              idempotency_key=idempotency_key)

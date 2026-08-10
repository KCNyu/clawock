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

    def _run(self, cmd):
        # The runtime's own launcher needs `node` on PATH, so a job started from
        # the user crontab cannot spawn it with the PATH it inherited.
        from clawock.providers.openclaw import runtime_env
        done = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=self.timeout, env=runtime_env())
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
            return DeliveryResult("failed", channel, str(target), detail=tail,
                                  idempotency_key=idempotency_key)
        status = "confirmed" if channel in CONFIRMING_CHANNELS else "unknown"
        return DeliveryResult(status, channel, str(target), detail=tail,
                              idempotency_key=idempotency_key)


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

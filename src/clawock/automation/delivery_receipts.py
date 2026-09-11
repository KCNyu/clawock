"""Delivery receipts: where a send is filed, what a receipt says, which channels go.

Three postflights send a report, three watchdogs decide whether to back one up, and
the workflow ledger reconciles slots whose sender died before recording. Until
2026-09-12 each of the seven spelled its own receipt path, parsed the JSON its own
way and folded `sent_ok` / `tg_ok` into its own idea of "delivered" — the reason
more than one incident in this repository's memory is a question of which file to
believe (`sent_ok` is WeChat only; `tg_ok` is the channel that always lands). They
now share this one definition. Storage is unchanged — the same file names and the
same fields — so a receipt written before this module reads the same after it.

Kept in `automation` on purpose: the harness already depends on this package and
the ledger lives in it, so both sides can use it without a new dependency edge.

`CHANNELS` is the delivery policy. Every kind goes to both channels today. How the
WeChat allowance (about ten pushes per message kcn sends the bot,
Tencent/openclaw-weixin#81) is spent is a change to this table, not to three
postflights.
"""
from __future__ import annotations

import json
from pathlib import Path

KINDS = ("brief", "report", "intraday")

#: kind -> the channels its report is sent to, in send order.
CHANNELS: dict[str, tuple[str, ...]] = {
    "brief": ("wechat", "telegram"),
    "report": ("wechat", "telegram"),
    "intraday": ("wechat", "telegram"),
}


def _slug(kind, market, phase, date):
    if kind == "brief":
        return date
    if kind == "report":
        return f"{market}-{phase}-{date}"
    if kind == "intraday":
        return market
    raise ValueError(f"unknown delivery kind: {kind!r}")


def receipt_name(kind, *, market=None, phase=None, date=None) -> str:
    """`brief-sent-{date}.json`, `report-sent-{market}-{phase}-{date}.json`,
    `intraday-sent-{market}.json` — the names every existing reader already uses."""
    return f"{kind}-sent-{_slug(kind, market, phase, date)}.json"


def parse_receipt_name(name) -> tuple[str, list[str]] | None:
    """(kind, slug parts) for a receipt file name, or None if it is not one.

    `report-sent-hk-open-2026-09-11.json` → ("report", ["hk", "open", "2026", "09", "11"]).
    """
    for kind in KINDS:
        prefix = f"{kind}-sent-"
        if name.startswith(prefix) and name.endswith(".json"):
            return kind, name[len(prefix): -len(".json")].split("-")
    return None


def claim_name(kind, *, market=None, phase=None, date=None) -> str:
    """The send-right lock taken before a send (#508), same naming as the receipt."""
    return f"{kind}-send-{_slug(kind, market, phase, date)}.claim"


def receipt_path(tmp, kind, **slot) -> Path:
    return Path(tmp) / receipt_name(kind, **slot)


def claim_path(tmp, kind, **slot) -> Path:
    return Path(tmp) / claim_name(kind, **slot)


def build_receipt(*, ts, sent_ok, tg_ok, out="", **fields) -> dict:
    """The receipt body. `sent_ok` is WeChat, `tg_ok` is Telegram; the caller's own
    identity fields (first line, context id, slot…) ride along unchanged."""
    return {"ts": ts, "sent_ok": bool(sent_ok), "tg_ok": bool(tg_ok),
            **fields, "out": (out or "")[-200:]}


def read_receipt(path) -> dict | None:
    """The receipt at `path`, or None when it is absent or unreadable."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def channels(receipt) -> tuple[bool, bool]:
    """(wechat_ok, telegram_ok) as the receipt proves them — True only when recorded True."""
    receipt = receipt or {}
    return receipt.get("sent_ok") is True, receipt.get("tg_ok") is True


def delivered(receipt) -> bool:
    """A receipt proves delivery when either channel reports a real send."""
    return any(channels(receipt))

"""WeChat's per-inbound send allowance, and the line that asks kcn to renew it.

Tencent's iLink bot API lets a bot send about ten messages after each message the
user sends it, within a 24-hour session; past that, `sendmessage` answers
`ret=-2 prepare failed` until the user writes again (Tencent/openclaw-weixin#81,
acknowledged by the maintainers in #202, unchanged as of 2026-09-11). Measured on
this desk 2026-09-07…11: eight inbound-to-inbound runs, each ~9 pushes landing
and every later push failing — the bot's own chat reply spends the tenth. With
~26 slots a day and 2–3 messages from kcn, part of every day was going to drop,
and 08:03 dropped most: the overnight monitor and the US close spend the
allowance first.

Nothing on this side can raise the allowance; a keep-alive was declined, and
sending without a context token (what `openclaw message send` does anyway — the
CLI loads the plugin fresh and never restores its token map) is refused the same
way. What this module does is count, so the last messages that can still land say
so: kcn 2026-09-12:「提醒我刷新」.

The count is local: pushes that this desk sent successfully since the user's last
inbound, whose time is the mtime of the plugin's context-token file (the gateway
rewrites it on every inbound). When that file is missing or does not name the
recipient, nothing is annotated — an unknown count is not guessed.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

#: Server-side, per user inbound (Tencent/openclaw-weixin#81).
ALLOWANCE = 10
#: The bot's chat reply to that inbound spends one.
RESERVED_FOR_REPLY = 1
#: Annotate while this many pushes, or fewer, remain after the one being sent.
NOTE_AT_REMAINING = 2
#: The plugin splits text at this many characters, and every chunk is a message.
CHUNK_CHARS = 4000
_KEEP = 200


def _accounts_dir() -> Path:
    from clawock.providers.openclaw import runtime_paths
    return runtime_paths().weixin_accounts_dir


def last_inbound(target, accounts_dir=None) -> float | None:
    """Epoch seconds of the user's last message to the bot, or None if unknown."""
    folder = Path(accounts_dir) if accounts_dir else _accounts_dir()
    newest = None
    for path in folder.glob("*.context-tokens.json"):
        try:
            if str(target) in json.loads(path.read_text(encoding="utf-8")):
                mtime = path.stat().st_mtime
                newest = mtime if newest is None else max(newest, mtime)
        except (OSError, ValueError):
            continue
    return newest


def chunks(message) -> int:
    return max(1, math.ceil(len(str(message or "")) / CHUNK_CHARS))


def _sends(ledger: Path) -> list[dict]:
    try:
        rows = json.loads(Path(ledger).read_text(encoding="utf-8"))
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def used_since(target, since, ledger: Path) -> int:
    return sum(int(row.get("chunks") or 1) for row in _sends(ledger)
               if row.get("target") == str(target) and row.get("ok")
               and float(row.get("ts") or 0) >= since)


def remaining_after(target, message, *, ledger: Path, accounts_dir=None):
    """Pushes left after this one lands, or None when the count is unknown."""
    since = last_inbound(target, accounts_dir)
    if since is None:
        return None
    budget = ALLOWANCE - RESERVED_FOR_REPLY
    return budget - used_since(target, since, ledger) - chunks(message)


def note(remaining) -> str:
    if remaining is None or remaining > NOTE_AT_REMAINING:
        return ""
    head = ("📮 这是本轮最后一条微信推送" if remaining <= 0
            else f"📮 微信本轮还能再推 {remaining} 条")
    return (f"{head}（腾讯规定你每发一条消息，bot 最多推约 10 条）。"
            "回我任意一个字就续满；不回的话，之后的推送只在 Telegram。")


def annotate(target, message, *, ledger: Path, accounts_dir=None):
    """(message with the renewal line appended when due, remaining-or-None)."""
    remaining = remaining_after(target, message, ledger=ledger,
                                accounts_dir=accounts_dir)
    line = note(remaining)
    return (f"{message.rstrip()}\n\n{line}" if line else message), remaining


def record(target, message, ok, *, ledger: Path, now=None) -> None:
    """File one send. Best effort: losing a row only makes the note late.

    The ledger path is the caller's: where a desk keeps its runtime state is the
    harness's business, not the delivery provider's (providers import no
    workspace layout).
    """
    rows = _sends(ledger)
    rows.append({"ts": now if now is not None else time.time(), "target": str(target),
                 "ok": bool(ok), "chunks": chunks(message)})
    path = Path(ledger)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows[-_KEEP:], ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass

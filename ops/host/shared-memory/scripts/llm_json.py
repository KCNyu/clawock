#!/usr/bin/env python3
"""One-shot model call and strict JSON extraction for the memory intake/review jobs.

The memory jobs run outside an agent turn: they need a decision, not a tool loop.
`openclaw infer model run` is the stable gateway-reached surface (the configured
provider keys stay in the gateway). A caller that cannot reach it must fail closed:
the raw item stays private and is retried later.

No prompt or model output is logged here. `MEMORY_LLM_MODEL` selects the model
(default `minimax/MiniMax-M3.1-Flash`, the same provider the gateway itself uses);
`MEMORY_LLM_CMD` can replace the command for a test harness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

# Same id as `[models.flash]` in config/models.toml: the memory jobs use the
# gateway's own MiniMax model.
DEFAULT_MODEL = "minimax/MiniMax-M3.1-Flash"


class LLMError(RuntimeError):
    pass


def model() -> str:
    return (os.environ.get("MEMORY_LLM_MODEL") or DEFAULT_MODEL).strip()


def thinking_level(model_id: str) -> str:
    """M3.1 cannot disable thinking; the endpoint rejects `off` with HTTP 400.

    OpenClaw resolves this host's default to `off`, so the level is always sent
    explicitly. A model selected through `MEMORY_LLM_MODEL` keeps the old pinned
    `off` unless it is a MiniMax endpoint.
    """
    provider = model_id.split("/", 1)[0].strip().lower()
    return "adaptive" if provider.startswith("minimax") else "off"


def _resolve_cli() -> str:
    found = shutil.which("openclaw")
    if found:
        return found
    # Cron starts with /usr/bin:/bin; the host installs the CLI under the pnpm
    # prefix and the launcher still needs node on PATH. Build the candidates from
    # segments so this module does not spell out a runtime path.
    home = Path.home()
    for candidate in (home / ".local" / "share" / "pnpm" / "openclaw",
                      home / ".local" / "bin" / "openclaw"):
        if candidate.is_file():
            return str(candidate)
    return ""


def _environment(cli: str) -> dict:
    env = dict(os.environ)
    node = shutil.which("node")
    if not node:
        fallback = Path("/usr/local/bin/node")
        node = str(fallback) if fallback.is_file() else ""
    if node:
        env["PATH"] = f"{Path(node).parent}:{Path(cli).parent}:{env.get('PATH', '')}"
    return env


def _command(prompt: str, model_id: str) -> tuple[list[str], dict]:
    override = (os.environ.get("MEMORY_LLM_CMD") or "").strip()
    if override:
        # A test/alternate harness gets the prompt on stdin, not argv.
        return shlex.split(override), dict(os.environ)
    cli = _resolve_cli()
    if not cli:
        raise LLMError("openclaw CLI not found on PATH or in the host prefix")
    return ([cli, "infer", "model", "run", "--model", model_id,
             "--thinking", thinking_level(model_id),
             "--prompt", prompt, "--json"], _environment(cli))


def run_model(prompt: str, *, model_id: str | None = None, timeout: int = 180) -> str:
    """Return the model's text. Raises LLMError; never prints the prompt."""
    model_id = model_id or model()
    command, env = _command(prompt, model_id)
    try:
        if os.environ.get("MEMORY_LLM_CMD"):
            proc = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                  timeout=timeout, env=env)
        else:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LLMError(f"model call failed: {type(exc).__name__}") from exc
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise LLMError(f"model call exited {proc.returncode}: {detail[-1][:200] if detail else 'no output'}")
    if os.environ.get("MEMORY_LLM_CMD"):
        return proc.stdout
    try:
        payload = json.loads(proc.stdout)
        text = payload["outputs"][0]["text"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("model call returned no text") from exc
    if not isinstance(text, str) or not text.strip():
        raise LLMError("model call returned empty text")
    return text


def extract_json(text: str):
    """First complete JSON value in a model reply; fences and prose are ignored."""
    stripped = text.strip()
    if stripped.startswith("```"):
        # A reply may close the fence on the same line as the JSON
        # (`[...]```), so strip the opening line and a trailing fence rather
        # than only whole fence lines; otherwise the array would be reduced to
        # its first object by the fallback scan below.
        newline = stripped.find("\n")
        stripped = stripped[newline + 1:] if newline != -1 else ""
        stripped = stripped.rstrip()
        if stripped.endswith("```"):
            stripped = stripped[:-3].rstrip()
    try:
        return json.loads(stripped)
    except ValueError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth, in_string, escaped = 0, False, False
            for index in range(start, len(text)):
                char = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                    continue
                if char == '"':
                    in_string = True
                elif char == opener:
                    depth += 1
                elif char == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start:index + 1])
                        except ValueError:
                            break
            start = text.find(opener, start + 1)
    raise LLMError("model reply contained no complete JSON object or array")

#!/usr/bin/env python3
"""One-shot model call and strict JSON extraction for the memory intake/review jobs.

The memory jobs run outside an agent turn: they need a decision, not a tool loop.
`openclaw infer model run` is the stable gateway-reached surface (the configured
provider keys stay in the gateway). A caller that cannot reach it must fail closed:
the raw item stays private and is retried later.

No prompt or model output is logged here. `MEMORY_LLM_MODEL` selects the model;
`MEMORY_LLM_CMD` can replace the command for a test harness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"


class LLMError(RuntimeError):
    pass


def model() -> str:
    return (os.environ.get("MEMORY_LLM_MODEL") or DEFAULT_MODEL).strip()


def _command(prompt: str, model_id: str) -> list[str]:
    override = (os.environ.get("MEMORY_LLM_CMD") or "").strip()
    if override:
        # A test/alternate harness gets the prompt on stdin, not argv.
        return shlex.split(override)
    cli = shutil.which("openclaw")
    if not cli:
        fallback = Path.home() / ".local" / "bin" / "openclaw"
        cli = str(fallback) if fallback.is_file() else ""
    if not cli:
        raise LLMError("openclaw CLI not found on PATH")
    return [cli, "infer", "model", "run", "--model", model_id, "--thinking", "off",
            "--prompt", prompt, "--json"]


def run_model(prompt: str, *, model_id: str | None = None, timeout: int = 180) -> str:
    """Return the model's text. Raises LLMError; never prints the prompt."""
    model_id = model_id or model()
    command = _command(prompt, model_id)
    try:
        if os.environ.get("MEMORY_LLM_CMD"):
            proc = subprocess.run(command, input=prompt, text=True, capture_output=True,
                                  timeout=timeout)
        else:
            proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
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
        lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
        stripped = "\n".join(lines).strip()
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

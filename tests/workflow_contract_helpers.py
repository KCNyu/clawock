"""Shared extraction helpers for GitHub Actions workflow contract tests."""
from __future__ import annotations

import textwrap
from pathlib import Path
import re


VALIDATOR_COMMAND = 'clawock validate-sidecar'


def push_paths(workflow: Path) -> list[str]:
    text = workflow.read_text(encoding='utf-8')
    block = text.split('    paths:', 1)[1].split('\n  pull_request:', 1)[0]
    return re.findall(r"^\s*-\s*'([^']+)'", block, re.MULTILINE)


def steps(workflow: Path):
    lines = workflow.read_text().splitlines()
    return [
        (i, line.strip().removeprefix('- name: '))
        for i, line in enumerate(lines)
        if line.lstrip().startswith('- name: ')
    ]


def step_block(workflow: Path, name: str) -> str:
    lines = workflow.read_text().splitlines()
    start = next(i for i, step_name in steps(workflow) if step_name == name)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].startswith(' ' * indent + '- ')),
        len(lines),
    )
    return '\n'.join(lines[start:end])


def strip_hash_comments(text: str) -> str:
    """Remove # comments while retaining hashes inside single/double quotes."""
    stripped = []
    for line in text.splitlines():
        quote = None
        escaped = False
        for index, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if char == '\\' and quote is not None:
                escaped = True
                continue
            if char in ("'", '"'):
                if quote is None:
                    quote = char
                elif quote == char:
                    quote = None
                continue
            if char == '#' and quote is None:
                line = line[:index]
                break
        stripped.append(line.rstrip())
    return '\n'.join(stripped)


def step_run(workflow: Path, name: str) -> str:
    block = step_block(workflow, name).splitlines()
    inline = next(
        (line.split('run:', 1)[1].strip()
         for line in block if line.strip().startswith('run: ')
         and line.strip() != 'run: |'),
        None,
    )
    if inline is not None:
        return strip_hash_comments(inline)
    run_start = next(
        (i for i, line in enumerate(block) if line.strip() == 'run: |'),
        None,
    )
    assert run_start is not None, f'{name} has no multiline run block'
    run = textwrap.dedent('\n'.join(block[run_start + 1:]))
    return strip_hash_comments(run)


def assert_validator_step(workflow: Path, step_name: str, validator_name: str) -> None:
    block = step_block(workflow, step_name)
    assert 'continue-on-error' not in block
    assert step_run(workflow, step_name) == f'{VALIDATOR_COMMAND} {validator_name}'


def staged_paths(workflow: Path, name: str) -> list[str]:
    """What a publishing step stages, whichever shape it is written in.

    Five workflows moved from an inline `git add` to the `clawock-commit`
    composite (#806). The contract those tests protect is unchanged — exactly
    these paths, and only after validation — so the extraction adapts rather
    than the assertions being dropped.

    The composite form can name the paths inline (`paths: a b`) or through an
    env var the caller computed (`paths: ${{ env.COMMIT_PATHS }}`), because a
    `with:` cannot run shell. In the second case the literal is read out of the
    step that wrote it, so a workflow cannot hide what it stages behind an
    indirection.
    """
    block = step_block(workflow, name)
    if 'clawock-commit' in block:
        line = next(ln for ln in block.splitlines() if ln.strip().startswith('paths:'))
        value = line.split('paths:', 1)[1].strip()
        if value.startswith('${{'):
            var = value.split('env.', 1)[1].split('}', 1)[0].strip()
            text = strip_hash_comments(workflow.read_text())
            assign = next(ln for ln in text.splitlines()
                          if f'{var}=' in ln and 'GITHUB_ENV' in ln)
            value = assign.split(f'{var}=', 1)[1].split('"', 1)[0].strip()
            # A computed list is spelled `$paths`; resolve the shell variable it
            # accumulates so the assertion still sees real paths.
            if value.startswith('$'):
                shell = strip_hash_comments(step_block(workflow, _writer_step(workflow, var)))
                parts: list[str] = []
                for ln in shell.splitlines():
                    stripped = ln.strip()
                    if stripped.startswith('paths='):
                        chunk = stripped.split('=', 1)[1].strip().strip('"')
                        parts += [t for t in chunk.split() if not t.startswith('$')]
                return parts
        return _split_paths(value)

    add_lines = [ln.strip() for ln in step_run(workflow, name).splitlines()
                 if ln.strip().startswith('git add')]
    out: list[str] = []
    for line in add_lines:
        out += [t for t in line.removeprefix('git add').split() if t != '--']
    return out


def _split_paths(value: str) -> list[str]:
    """Split on spaces, but keep a `$(date ...)` substitution as one token.

    A naive split turns `memory/weekly/$(date -u +%G-W%V).md` into three paths
    and the assertion then compares nonsense to nonsense.
    """
    out, buf, depth = [], '', 0
    for ch in value:
        if ch == '(' and buf.endswith('$'):
            depth += 1
        elif ch == ')' and depth:
            depth -= 1
        if ch == ' ' and not depth:
            if buf:
                out.append(buf)
            buf = ''
            continue
        buf += ch
    if buf:
        out.append(buf)
    return out


def _writer_step(workflow: Path, var: str) -> str:
    """Name of the step that writes `var` into GITHUB_ENV."""
    for _, name in steps(workflow):
        if f'{var}=' in step_block(workflow, name):
            return name
    raise AssertionError(f'nothing writes {var} into GITHUB_ENV')

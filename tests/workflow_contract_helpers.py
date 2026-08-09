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


def case_patterns(workflow: Path, step_name: str = 'Detect code changes') -> list[str]:
    detect = workflow.read_text(encoding='utf-8').split(step_name, 1)[1]
    line = next(ln for ln in detect.splitlines()
                if ln.strip().endswith(')') and '|' in ln)
    return line.strip().rstrip(')').split('|')


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

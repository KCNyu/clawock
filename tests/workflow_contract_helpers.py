"""Shared extraction helpers for GitHub Actions workflow contract tests."""
from __future__ import annotations

import textwrap
from pathlib import Path


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
    run_start = next(
        (i for i, line in enumerate(block) if line.strip() == 'run: |'),
        None,
    )
    assert run_start is not None, f'{name} has no multiline run block'
    run = textwrap.dedent('\n'.join(block[run_start + 1:]))
    return strip_hash_comments(run)

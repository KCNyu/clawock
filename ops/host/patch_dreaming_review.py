#!/usr/bin/env python3
"""Quarantine automatic promotions; no gateway restart is performed here."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

from patch_dreaming_fallbacks import replace_once

MARKER = 'clawock-dreaming-review-v1'
OLD_PATH = 'const memoryPath = path.join(workspaceDir, "MEMORY.md");'
NEW_PATH = '''// clawock-dreaming-review-v1: private candidates, never long-term memory.
	const memoryPath = path.join(workspaceDir, "memory", ".dreams", "promotion-candidates.md");
	await fs.mkdir(path.dirname(memoryPath), { recursive: true, mode: 0o700 });'''
OLD_BUDGET = 'budgetChars: typeof options.memoryFileMaxChars === "number" && Number.isFinite(options.memoryFileMaxChars) ? Math.max(0, Math.floor(options.memoryFileMaxChars)) : DEFAULT_MEMORY_FILE_MAX_CHARS'
OLD_WRITE = 'await fs.writeFile(memoryPath, `${header}${withTrailingNewline(baseMemory)}${section}`, "utf-8");'
NEW_WRITE = 'await fs.writeFile(memoryPath, `${header}${withTrailingNewline(baseMemory)}${section}`, { encoding: "utf-8", mode: 0o600 });'
NEW_BUDGET = 'budgetChars: Number.MAX_SAFE_INTEGER // retain pending candidates until review'


def patch(text):
    if MARKER in text:
        if NEW_PATH not in text or NEW_BUDGET not in text or NEW_WRITE not in text or OLD_PATH in text:
            raise ValueError('incomplete dreaming review patch')
        return text
    return replace_once(replace_once(replace_once(text, OLD_PATH, NEW_PATH),
                                     OLD_BUDGET, NEW_BUDGET), OLD_WRITE, NEW_WRITE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.dist is None:
        from clawock.providers.openclaw import runtime_paths
        install = runtime_paths().install_dir
        if install is None:
            parser.error('OpenClaw installation missing')
        args.dist = install / 'dist'
    paths = [p for p in args.dist.glob('short-term-promotion-*.js')
             if 'async function applyShortTermPromotions(options)' in p.read_text()]
    if len(paths) != 1:
        raise ValueError('expected one promotion bundle')
    path = paths[0]
    old = path.read_text()
    new = patch(old)
    if args.check and old != new:
        raise ValueError('dreaming review patch not installed')
    subprocess.run(['node', '--input-type=module', '--check'], input=new, text=True, check=True)
    if new != old:
        backup = path.with_name(path.name + '.before-dreaming-review')
        if not backup.exists():
            backup.write_text(old)
        tmp = path.with_name(path.name + '.dreaming-review-tmp')
        tmp.write_text(new)
        tmp.chmod(path.stat().st_mode & 0o777)
        tmp.replace(path)
    print(f'{MARKER}: verified; gateway not restarted')


if __name__ == '__main__':
    main()

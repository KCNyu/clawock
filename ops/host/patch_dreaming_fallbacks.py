#!/usr/bin/env python3
"""Backport ordered Dream Diary fallbacks to OpenClaw 2026.7.1-2.

Run before sync_models --apply, then restart the idle gateway. No restart here.
Only the narrative loop and memory-core config schema change; promotion, plugin
model authorization, and per-model runtime/thinking selection stay native.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

_CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_CHECKOUT))
sys.path.insert(0, str(_CHECKOUT / "src"))
from clawock.providers.openclaw import runtime_paths  # noqa: E402

MARKER = 'clawock-dreaming-fallbacks-v1'
HELPER = r'''
// clawock-dreaming-fallbacks-v1
function isRetryableDreamingModelError(raw) {
    // Policy failures must stay visible; never bypass the plugin allowlist.
    if (/not (?:trusted|authorized|allowlisted)|allowlist|permission|forbidden/i.test(raw)) return false;
    return isConfiguredModelUnavailableNarrativeError(raw) ||
        /\b429\b|rate.?limit|quota|token plan|用量上限|\b50[234]\b|overloaded|temporarily unavailable/i.test(raw);
}
'''


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError(f'expected one OpenClaw anchor: {old[:100]!r}')
    return text.replace(old, new, 1)


def patch_narrative(text: str) -> str:
    if MARKER in text:
        return text
    text = replace_once(text, 'function formatNarrativeTerminalStatus(params) {',
                        HELPER + '\nfunction formatNarrativeTerminalStatus(params) {')
    text = replace_once(text,
        'const attemptModels = params.model ? [params.model, void 0] : [void 0];',
        '''const configuredFallbacks = getRuntimeConfig()?.plugins?.entries?.["memory-core"]?.config?.dreaming?.fallbacks;
            const hasExplicitFallbacks = Array.isArray(configuredFallbacks);
            const attemptModels = hasExplicitFallbacks
                ? [...new Set([params.model, ...configuredFallbacks].filter(Boolean))]
                : params.model ? [params.model, void 0] : [void 0];
            if (attemptModels.length === 0) attemptModels.push(void 0);''')
    text = replace_once(text,
        'if (attemptModel && result.status === "error" && isConfiguredModelUnavailableNarrativeError(result.error ?? "")) {',
        '''if (attemptIndex + 1 < attemptModels.length && attemptModel && result.status === "error" &&
                        (hasExplicitFallbacks ? isRetryableDreamingModelError(result.error ?? "") : isConfiguredModelUnavailableNarrativeError(result.error ?? ""))) {''')
    text = replace_once(text,
        'if (attemptModel && isConfiguredModelUnavailableNarrativeError(formatErrorMessage(err))) {',
        '''if (attemptIndex + 1 < attemptModels.length && attemptModel &&
                        (hasExplicitFallbacks ? isRetryableDreamingModelError(formatErrorMessage(err)) : isConfiguredModelUnavailableNarrativeError(formatErrorMessage(err)))) {''')
    # Keep the original default-model retry when no explicit chain is configured.
    text = text.replace('retrying with the session default',
                        'retrying with ${attemptModels[attemptIndex + 1] ?? "the session default"}')
    return text


def patch_manifest(text: str) -> str:
    manifest = json.loads(text)
    properties = manifest['configSchema']['properties']['dreaming']['properties']
    spec = {'type': 'array', 'items': {'type': 'string'}}
    if 'fallbacks' in properties and properties['fallbacks'] != spec:
        raise ValueError('upstream dreaming.fallbacks schema changed; review the backport')
    if properties.get('fallbacks') == spec:
        return text
    properties['fallbacks'] = spec
    return json.dumps(manifest, indent=2, ensure_ascii=False) + '\n'


def apply(dist: Path, check: bool = False) -> None:
    candidates = [p for p in dist.glob('dreaming-narrative-*.js')
                  if 'const DETACHED_NARRATIVE_CONCURRENCY' in p.read_text()]
    if len(candidates) != 1:
        raise ValueError(f'expected one dreaming narrative bundle, found {len(candidates)}')
    edits = [(candidates[0], patch_narrative),
             (dist / 'extensions' / 'memory-core' / 'openclaw.plugin.json', patch_manifest)]
    # Validate every anchor before writing anything. Backups are never overwritten.
    plan = [(path, path.read_text(), patch(path.read_text())) for path, patch in edits]
    if check and any(old != new for _, old, new in plan):
        raise ValueError('dreaming fallbacks backport is not installed')
    staged = []
    try:
        for path, old, new in plan:
            if old == new:
                continue
            tmp = path.with_name(path.name + '.dreaming-fallbacks.tmp')
            tmp.write_text(new)
            tmp.chmod(path.stat().st_mode & 0o777)
            staged.append((path, tmp, old))
            if path.suffix == '.js':
                subprocess.run(['node', '--input-type=module', '--check'], input=new,
                               text=True, check=True)
        for path, tmp, old in staged:
            backup = path.with_name(path.name + '.before-dreaming-fallbacks')
            if not backup.exists():
                backup.write_text(old)
                backup.chmod(path.stat().st_mode & 0o777)
            tmp.replace(path)
    finally:
        for _, tmp, _ in staged:
            tmp.unlink(missing_ok=True)
    subprocess.run(['node', '--check', str(candidates[0])], check=True)
    print(f'{MARKER}: schema and narrative verified; gateway not restarted')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, help='override the discovered installation dist')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    install = runtime_paths().install_dir
    dist = args.dist or (install / 'dist' if install else None)
    if dist is None:
        parser.error('OpenClaw installation not found; pass --dist')
    apply(dist.resolve(), args.check)


if __name__ == '__main__':
    main()

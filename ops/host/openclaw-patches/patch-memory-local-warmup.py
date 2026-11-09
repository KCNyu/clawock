#!/usr/bin/env python3
"""Warm the local embedding model at gateway start, not on the first recall.

Measured on this host 2026-11-10 (openclaw 2026.7.1-2): the first memory_search
after a gateway restart paid searchMs=27.3s (worker spawn + ~11s of GGUF I/O +
schema/vector work) while the next searches in the same process returned in
0.5-5.5s. The model is loaded lazily by the memory-core plugin's local provider,
so the one question a user asks after a deploy is the one that waits 30s.

This adapter registers a plugin service that probes the local provider 5s after
startup. The probe is fire-and-forget and only runs when the configured
memorySearch provider is `local`; remote providers keep their existing lazy
behaviour (no surprise API call). The worker and model stay resident, so every
later recall takes the warm path.

Lives inside the .pnpm/openclaw@<ver> tree and is WIPED on every openclaw
upgrade -> re-run this after each upgrade (idempotent). Registered in the repo's
ops/host/openclaw-patches/manifest.json inventory and per-target postconditions.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

HOST = Path(__file__).resolve().parent
sys.path.insert(0, str(HOST.parent))

from patch_dreaming_fallbacks import replace_once  # noqa: E402

MARKER = 'clawock-memory-local-warmup-v1'
ANCHOR = '\t\tapi.registerMemoryCapability({'
INSERT = '''\t\t// clawock-memory-local-warmup-v1: pay the local model load at startup,
\t\t// not on the first recall after every gateway restart.
\t\tapi.registerService({
\t\t\tid: "memory-local-warmup",
\t\t\tstart: (ctx) => {
\t\t\t\tconst timer = setTimeout(async () => {
\t\t\t\t\tconst startedAt = Date.now();
\t\t\t\t\ttry {
\t\t\t\t\t\tconst cfg = ctx?.config ?? api.config;
\t\t\t\t\t\tconst { sessionAgentId } = resolveSessionAgentIds({ config: cfg });
\t\t\t\t\t\tconst settings = resolveMemorySearchConfig(cfg, sessionAgentId);
\t\t\t\t\t\tif (!settings || settings.provider !== "local") return;
\t\t\t\t\t\tconst { manager } = await memoryRuntime.getMemorySearchManager({ cfg, agentId: sessionAgentId });
\t\t\t\t\t\tif (!manager?.probeEmbeddingAvailability) throw new Error("memory manager unavailable");
\t\t\t\t\t\tconst probe = await manager.probeEmbeddingAvailability();
\t\t\t\t\t\tif (probe?.ok === false) throw new Error(probe.error || "embedding probe failed");
\t\t\t\t\t\tapi.logger?.info?.(`memory warmup: local embeddings ready in ${Date.now() - startedAt}ms`);
\t\t\t\t\t} catch (err) {
\t\t\t\t\t\tapi.logger?.warn?.(`memory warmup failed: ${String(err)}`);
\t\t\t\t\t}
\t\t\t\t}, 5000);
\t\t\t\ttimer.unref?.();
\t\t\t}
\t\t});
'''


def patch(text):
    if MARKER in text:
        if 'probeEmbeddingAvailability' not in text or 'memory-local-warmup' not in text:
            raise ValueError('incomplete memory warmup patch')
        return text
    return replace_once(text, ANCHOR, INSERT + ANCHOR)


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
    path = args.dist / 'extensions' / 'memory-core' / 'index.js'
    if not path.is_file():
        raise ValueError(f'memory-core plugin entry not found: {path}')
    old = path.read_text()
    new = patch(old)
    if args.check and old != new:
        raise ValueError('memory warmup patch not installed')
    subprocess.run(['node', '--input-type=module', '--check'], input=new, text=True, check=True)
    if new != old:
        backup = path.with_name(path.name + '.before-memory-warmup')
        if not backup.exists():
            backup.write_text(old)
        tmp = path.with_name(path.name + '.memory-warmup-tmp')
        tmp.write_text(new)
        tmp.chmod(path.stat().st_mode & 0o777)
        tmp.replace(path)
    print(f'{MARKER}: verified; gateway not restarted')


if __name__ == '__main__':
    main()

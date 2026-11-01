#!/usr/bin/env python3
"""Versioned OpenClaw patch kit: stage all edits, verify, then journal and install.

No gateway restart and no config/plugin installation. The upgrade wrapper owns those
separate lifecycle steps. An idle gateway is required before applying or rolling back.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

HOST = Path(__file__).resolve().parent
sys.path.insert(0, str(HOST.parents[1] / 'src'))
DEFAULT_MANIFEST = HOST / 'openclaw-patches/manifest.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inside(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or path.is_symlink():
        raise ValueError(f'unsafe patch path: {relative}')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'patch path escapes root: {relative}')
    return path


def load_manifest(path):
    manifest = json.loads(path.read_text())
    if manifest.get('schema') != 1 or not manifest.get('patches'):
        raise ValueError('unsupported or empty patch manifest')
    ids = [p['id'] for p in manifest['patches']]
    if len(ids) != len(set(ids)):
        raise ValueError('duplicate patch id')
    return manifest


def resolve_targets(dist, manifest):
    # Resolve every selector before any adapter runs. Never guess the first match.
    sources = {p: p.read_text() for p in dist.glob('*.js') if not p.is_symlink()}
    resolved = []
    for patch in manifest['patches']:
        targets = []
        for spec in patch['targets']:
            if 'path' in spec:
                path = inside(dist, spec['path'])
                if not path.is_file():
                    raise ValueError(f"{patch['id']}: missing {spec['path']}")
            else:
                matches = [p for p, text in sources.items() if spec['selector'] in text]
                if len(matches) != 1:
                    raise ValueError(f"{patch['id']}: selector matched {len(matches)} bundles: {spec['selector']}")
                path = matches[0]
            targets.append((path.relative_to(dist).as_posix(), spec))
        resolved.append((patch, targets))
    return resolved


def verify(stage_dist, resolved):
    files = set()
    for patch, targets in resolved:
        for relative, spec in targets:
            path = inside(stage_dist, relative)
            text = path.read_text()
            if any(marker not in text for marker in spec.get('required', [])):
                raise ValueError(f"{patch['id']}: incomplete postconditions in {relative}")
            if spec.get('any_of') and not any(marker in text for marker in spec['any_of']):
                raise ValueError(f"{patch['id']}: no supported implementation in {relative}")
            files.add(path)
    for path in sorted(files):
        if path.suffix == '.js':
            subprocess.run(['node', '--input-type=module', '--check'], input=path.read_bytes(),
                           check=True, capture_output=True)
        elif path.suffix == '.json':
            json.loads(path.read_text())


def prepare(install, manifest_path, stage, host=HOST):
    manifest = load_manifest(manifest_path)
    dist = install / 'dist'
    resolved = resolve_targets(dist, manifest)
    originals = {}
    for _, targets in resolved:
        for relative, _ in targets:
            if relative in originals:
                continue
            source = inside(dist, relative)
            originals[relative] = source.read_bytes()
            dest = inside(stage / 'dist', relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
    package = json.loads((install / 'package.json').read_text())
    (stage / 'package.json').write_text(json.dumps({'type': 'module'}))
    backup = stage / 'backups'
    backup.mkdir()
    env = {**os.environ, 'CLAWOCK_PATCH_STAGE': str(stage), 'CLAWOCK_PATCH_BACKUP_DIR': str(backup)}
    scripts = {}
    for patch, _ in resolved:
        script = inside(host, patch['script'])
        scripts[patch['script']] = sha(script.read_bytes())
        command = ['bash', str(script)] if script.suffix == '.sh' else [
            sys.executable, str(script), '--dist', str(stage / 'dist')]
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise ValueError(f"{patch['id']}: staging failed: {result.stderr.strip() or result.stdout.strip()}")
    verify(stage / 'dist', resolved)
    updated = {name: inside(stage / 'dist', name).read_bytes() for name in originals}
    report = {'schema': 1, 'install': str(install), 'version': package.get('version'),
              'manifest_sha256': sha(manifest_path.read_bytes()), 'scripts': scripts,
              'patches': [p['id'] for p, _ in resolved],
              'validated_version': package.get('version') in manifest.get('validated_versions', []),
              'files': {name: {'before': sha(old), 'after': sha(updated[name])}
                        for name, old in originals.items()},
              'changes': [name for name in originals if originals[name] != updated[name]]}
    return report, originals, updated


def atomic_write(path, data, mode=0o600):
    fd, tmp = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def save_receipt(path, report):
    atomic_write(path, (json.dumps(report, indent=2) + '\n').encode())


def rollback(receipt):
    report = json.loads(receipt.read_text())
    dist = Path(report['install']) / 'dist'
    # Refuse the whole rollback if any file has since changed: no partial clobber.
    for name in report['changes']:
        data = inside(dist, name).read_bytes()
        if sha(data) not in (report['files'][name]['before'], report['files'][name]['after']):
            raise ValueError(f'rollback refused: {name} changed since this transaction')
        saved = inside(receipt.parent / 'before', name)
        if sha(saved.read_bytes()) != report['files'][name]['before']:
            raise ValueError(f'rollback backup hash mismatch: {name}')
    for name in report['changes']:
        path = inside(dist, name)
        atomic_write(path, inside(receipt.parent / 'before', name).read_bytes(),
                     report['files'][name]['mode'])
    report['status'] = 'rolled_back'
    save_receipt(receipt, report)
    return report


def commit(install, report, originals, updated, state):
    dist = install / 'dist'
    for name, data in originals.items():
        if inside(dist, name).read_bytes() != data:
            raise ValueError(f'install changed during staging: {name}')
    transaction = state / uuid.uuid4().hex
    transaction.mkdir(parents=True, mode=0o700)
    receipt = transaction / 'receipt.json'
    for name in report['changes']:
        path = inside(dist, name)
        report['files'][name]['mode'] = path.stat().st_mode & 0o777
        saved = inside(transaction / 'before', name)
        saved.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(saved, originals[name])
    report['status'] = 'prepared'
    save_receipt(receipt, report)  # Durable before the first live replacement.
    try:
        for name in report['changes']:
            path = inside(dist, name)
            if path.read_bytes() != originals[name]:
                raise ValueError(f'install changed before replacement: {name}')
            atomic_write(path, updated[name], report['files'][name]['mode'])
        report['status'] = 'applied'
        save_receipt(receipt, report)
    except BaseException:
        rollback(receipt)
        raise
    report['receipt'] = str(receipt)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['plan', 'check', 'apply', 'rollback'])
    parser.add_argument('--install', type=Path)
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--scratch', type=Path, default=Path.home() / 'scratch/openclaw-patches')
    parser.add_argument('--state', type=Path, default=Path.home() / 'logs/openclaw-patches')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.mode == 'rollback':
        if args.receipt is None:
            parser.error('rollback requires --receipt')
        args.install = Path(json.loads(args.receipt.read_text())['install'])
    if args.install is None:
        from clawock.providers.openclaw import runtime_paths
        args.install = runtime_paths().install_dir
    if args.install is None:
        parser.error('OpenClaw installation missing; pass --install')
    install = args.install.resolve()
    args.scratch.mkdir(parents=True, exist_ok=True)
    # All modes share a lock per installation, not per checkout or patch version.
    lock_path = args.scratch / (sha(str(install).encode()) + '.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.mode == 'rollback':
            report = rollback(args.receipt)
        else:
            with tempfile.TemporaryDirectory(prefix='stage-', dir=args.scratch) as temp:
                report, old, new = prepare(install, args.manifest, Path(temp))
                report['status'] = 'drift' if report['changes'] else 'verified'
                if args.mode == 'apply':
                    report = commit(install, report, old, new, args.state)
        print(json.dumps(report, indent=2))
        return 1 if args.mode == 'check' and report['changes'] else 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'openclaw-patches: {exc}', file=sys.stderr)
        sys.exit(2)

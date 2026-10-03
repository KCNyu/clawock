#!/usr/bin/env python3
"""Read-only structural evidence. Size, names and arbitrary thresholds are not checks.

Exit 1 is a measured violation; 0 refutes it; 2 means the probe is invalid.
The gate calls this same evaluator before granting a debt-only precedent exemption.
"""
import ast
import copy
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib

CHECKS = ('duplicate-python', 'import-cycle', 'undeclared-import')
IMPORT_DISTRIBUTIONS = {'PIL': 'pillow', 'google.auth': 'google-auth'}


def source(root, path):
    p = Path(path)
    if p.is_absolute() or '..' in p.parts or not path.endswith('.py'):
        raise ValueError('source must be a relative Python path')
    resolved = (root / p).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError('source escapes worktree')
    tracked = subprocess.run(['git', 'ls-files', '--error-unmatch', '--', path],
                             cwd=root, capture_output=True, timeout=10)
    if tracked.returncode:
        raise ValueError(f'untracked source: {path}')
    return ast.parse(resolved.read_text()), resolved.read_text()


def module_name(path):
    p = Path(path)
    if p.parts[:2] != ('src', 'clawock'):
        raise ValueError('cycle modules must be in src/clawock')
    parts = list(p.with_suffix('').parts[1:])
    if parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts)


def imports(tree, module='', package=False, eager=False):
    """Resolve direct import edges, including relative imports, without importing code."""
    nodes = []
    def collect(node):
        if eager and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            nodes.append(node)
        for child in ast.iter_child_nodes(node):
            collect(child)
    collect(tree)
    out = set()
    for n in nodes:
        if isinstance(n, ast.Import):
            out.update(a.name for a in n.names)
        elif n.level:
            base = module.split('.') if package else module.split('.')[:-1]
            prefix = '.'.join(base[:len(base) - n.level + 1])
            if n.module:
                out.add(prefix + '.' + n.module)
            else:
                out.update(prefix + '.' + a.name for a in n.names)
        elif n.module:
            out.add(n.module)
            out.update(n.module + '.' + a.name for a in n.names)
    return out


def evaluate(contract, root):
    """Return (violated, measurement, source paths). Malformed claims raise ValueError."""
    root = Path(root)
    if not isinstance(contract, dict):
        raise ValueError("contract must be a JSON object")
    kind = contract.get('check')
    if kind not in CHECKS:
        raise ValueError('unsupported check; size/naming/threshold checks are not evidence')
    for key in ('fact', 'repair', 'guard'):
        if not isinstance(contract.get(key), str) or len(contract[key].strip()) < 12:
            raise ValueError(f'{key} must explain the fact, owner/cut and regression guard')
    if kind == 'duplicate-python':
        symbols = contract.get('symbols', [])
        if not isinstance(symbols, list) or not 2 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols):
            raise ValueError('need 2..10 distinct path::function symbols')
        bodies, paths, sizes = [], [], []
        for symbol in symbols:
            path, name = symbol.split('::')
            tree, _ = source(root, path)
            matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
            if len(matches) != 1:
                raise ValueError(f'{symbol} must resolve to one top-level function')
            n = matches[0]
            # Keep arguments, constants and identifier references; ignore only declaration name.
            sizes.append(n.end_lineno - n.lineno + 1)
            canonical = copy.deepcopy(n)
            canonical.name = 'OWNER'
            bodies.append(ast.dump(canonical, include_attributes=False))
            paths.append(path)
        if len(set(paths)) < 2:
            raise ValueError('need implementations in distinct modules')
        if min(sizes) < 5:
            return False, f'duplicate-python: copies=0 (wrappers/tiny idioms) lines={sizes} symbols={symbols}', paths
        same = len(set(bodies)) == 1
        return same, f'duplicate-python: copies={len(symbols) if same else 1} lines={sizes} symbols={symbols}', paths
    if kind == 'import-cycle':
        paths = contract.get('modules', [])
        if not isinstance(paths, list) or not 2 <= len(paths) <= 20 or len(set(paths)) != len(paths):
            raise ValueError('need an ordered cycle of 2..20 distinct source modules')
        names = [module_name(p) for p in paths]
        edges = []
        for i, path in enumerate(paths):
            tree, _ = source(root, path)
            targets = imports(tree, names[i], Path(path).name == '__init__.py', eager=True)
            nxt = names[(i + 1) % len(names)]
            edges.append((names[i], nxt, nxt in targets))
        return all(e[2] for e in edges), f'import-cycle: eager edges={edges}', paths
    path = contract.get('source', '')
    name = contract.get('import', '')
    if not isinstance(name, str) or not name or name.split('.')[0] in sys.stdlib_module_names | {'clawock'}:
        raise ValueError('import must name an external dependency')
    tree, _ = source(root, path)
    seen = imports(tree)
    if name not in seen:
        raise ValueError(f'{name} is not imported by {path}')
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    specs = list(project.get('dependencies', []))
    for extra in project.get('optional-dependencies', {}).values():
        specs.extend(extra)
    import re
    normalize = lambda s: re.sub(r'[-_.]+', '-', s).lower()
    declared = {normalize(re.split(r'[<>=!~\[; ]', s, 1)[0]) for s in specs}
    dist = IMPORT_DISTRIBUTIONS.get(name, name.split('.')[0])
    missing = normalize(dist) not in declared
    return missing, f'undeclared-import: {path} imports={name} distribution={dist} declared={sorted(declared)}', [path, 'pyproject.toml']


def red_command(contract, tool):
    return 'python3 ' + shlex.quote(str(Path(tool) / 'debt_check.py')) + ' ' + shlex.quote(json.dumps(contract, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('usage: debt_check.py <contract-json>')
        violated, measured, _ = evaluate(json.loads(sys.argv[1]), Path.cwd())
        print(measured)
        print('DEBT RED' if violated else 'DEBT GREEN')
        sys.exit(1 if violated else 0)
    except (ValueError, OSError, SyntaxError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'INVALID DEBT CHECK: {exc}', file=sys.stderr)
        sys.exit(2)

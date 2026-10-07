#!/usr/bin/env python3
"""Read-only structural evidence. Names and hand-picked thresholds are not checks.

Exit 1 is a measured violation; 0 refutes it; 2 means the probe is invalid.
The gate calls this same evaluator before granting a debt-only precedent exemption.

`structure` is the one check that reads a size: it recomputes the measure for every
function at this HEAD and only accepts a symbol at or above that distribution's p99.
The cut-off is measured on each run and printed; it is never a number in this file.
Its history is the function's own: fix counts and precedents are read from the commits
whose diff reached the function body (`git log -L`), never from the file it lives in.

`--candidates` lists where to read (tail functions, renamed copies, unreferenced
symbols). It is a search aid for the round, not evidence: a candidate becomes a
finding only through one contract evaluated above.
"""
import ast
import collections
import copy
import datetime
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tomllib

CHECKS = ('duplicate-python', 'import-cycle', 'undeclared-import', 'unreferenced-symbol', 'structure')
MEASURES = ('cc', 'length', 'nesting')
SCOPE = ('src/clawock', 'ops')    # the population a structure measure is ranked against
TAIL = 0.99
WINDOW = 60    # days of history a fix count covers
FUNC = (ast.FunctionDef, ast.AsyncFunctionDef)
BRANCH = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension, ast.match_case)
BLOCK = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.Match)
# The existing dependency guard owns import/distribution aliases. Read its literal
# without importing tests or running arbitrary repository code; do not fork that fact.
DEPENDENCY_GUARD = 'tests/test_packaging_extras_contract.py'


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


def git(root, *args):
    out = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, timeout=60)
    return out.returncode, out.stdout


def is_test(path):
    return 'tests' in Path(path).parts or Path(path).name.startswith(('test_', 'conftest'))


def split_symbol(symbol):
    if not isinstance(symbol, str) or symbol.count('::') != 1 or not all(symbol.split('::')):
        raise ValueError(f'{symbol!r} must be path::name')
    return symbol.split('::')


def top_level(root, symbol, kinds=FUNC):
    """The one module-level definition a symbol names, or None once it (or its file) is gone."""
    path, name = split_symbol(symbol)
    try:
        tree, _ = source(root, path)
    except ValueError as exc:
        if 'untracked source' in str(exc):
            return None
        raise
    matches = [n for n in tree.body if isinstance(n, kinds) and n.name == name]
    if len(matches) > 1:
        raise ValueError(f'{symbol} is defined {len(matches)} times at module level')
    if not matches and any(isinstance(n, kinds) and n.name == name for n in guarded(tree.body)):
        # Still in the module's scope, under an `if`/`try`: not seen is not gone.
        raise ValueError(f'{symbol} is defined below module level (inside if/try/with): the check cannot read it')
    return matches[0] if matches else None


def guarded(body):
    """Statements of a module that sit inside its compound statements, not inside a def or class."""
    for stmt in body:
        if isinstance(stmt, FUNC + (ast.ClassDef,)):
            continue
        for field in ('body', 'orelse', 'finalbody'):
            inner = getattr(stmt, field, None) or []
            yield from inner
            yield from guarded(inner)
        for part in [*getattr(stmt, 'handlers', []), *getattr(stmt, 'cases', [])]:
            yield from part.body
            yield from guarded(part.body)


def own_nodes(fn):
    """Nodes of fn without nested function/class bodies: those are ranked on their own."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        n = stack.pop()
        yield n
        if not isinstance(n, FUNC + (ast.ClassDef, ast.Lambda)):
            stack.extend(ast.iter_child_nodes(n))


def measure(fn, kind):
    if kind == 'length':
        return fn.end_lineno - fn.lineno + 1
    if kind == 'cc':
        c = 1
        for n in own_nodes(fn):
            if isinstance(n, BRANCH):
                c += 1 + (len(n.ifs) if isinstance(n, ast.comprehension) else 0)
            elif isinstance(n, ast.BoolOp):
                c += len(n.values) - 1
        return c
    def depth(n, d):
        best = d
        for ch in ast.iter_child_nodes(n):
            if not isinstance(ch, FUNC + (ast.ClassDef, ast.Lambda)):
                best = max(best, depth(ch, d + 1 if isinstance(ch, BLOCK) else d))
        return best
    return depth(fn, 0)


def population(root):
    """(path, tree) for every tracked non-test Python module the measures are ranked over."""
    code, out = git(root, 'ls-files', '--', *SCOPE)
    if code:
        raise ValueError('cannot list tracked sources')
    for path in sorted(p for p in out.splitlines() if p.endswith('.py') and not is_test(p)):
        try:
            yield path, ast.parse((Path(root) / path).read_text(errors='replace'))
        except (SyntaxError, OSError):
            continue


def tail_cutoff(values):
    """p99 of this HEAD's own distribution (nearest rank); moves when the code does."""
    ordered = sorted(values)
    if not ordered:
        raise ValueError('no functions to rank against')
    return ordered[min(len(ordered) - 1, int(round(TAIL * (len(ordered) - 1))))]


_IDENTIFIERS = {}


def identifiers(path, tree):
    """Every name a module mentions, walked once per process."""
    if path not in _IDENTIFIERS:
        _IDENTIFIERS[path] = {getattr(n, 'id', None) or getattr(n, 'attr', None) or getattr(n, 'name', None)
                              for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute, ast.alias) + FUNC)}
    return _IDENTIFIERS[path]


def references(root, symbol, trees=None):
    """Non-test uses of a module-level function, resolved through imports: `path:line` list."""
    path, name = split_symbol(symbol)
    target = Path(path).with_suffix('')
    dotted = '.'.join(target.parts[1:] if target.parts[0] == 'src' else target.parts)
    stem = target.name
    owner = lambda mod: bool(mod) and (mod == dotted or mod.endswith('.' + stem) or mod == stem)
    sites = []
    for other, tree in (trees if trees is not None else population(root)):
        if name not in identifiers(other, tree):
            continue
        parts = list(Path(other).with_suffix('').parts)
        here = '.'.join(parts[1:] if parts[0] == 'src' else parts)
        package = here.rsplit('.', 1)[0] if '.' in here else ''
        direct, modules = ({name} if other == path else set()), set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                base = n.module or ''
                if n.level:
                    up = package.split('.') if package else []
                    up = up[:len(up) - n.level + 1] if n.level > 1 else up
                    base = '.'.join(up + ([n.module] if n.module else []))
                for a in n.names:
                    if owner(base) and a.name == name:
                        direct.add(a.asname or a.name)
                    elif owner(base + '.' + a.name if base else a.name):
                        modules.add(a.asname or a.name)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if owner(a.name):
                        modules.add(a.asname or a.name)
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and n.id in direct and isinstance(n.ctx, ast.Load):
                sites.append(f'{other}:{n.lineno}')
            elif isinstance(n, ast.Attribute) and n.attr == name and ast.unparse(n.value) in modules:
                sites.append(f'{other}:{n.lineno}')
    return sorted(set(sites))


def precedent_touches(root, number, paths):
    """Newest commit that names #number and changed one of paths, as 'sha path'; '' if none.

    An issue number that merely exists says nothing about this code. A fix that named
    the issue and edited the file is the weakest claim that still ties the two together.
    """
    for path in paths:
        code, out = git(root, 'log', '-n', '1', '--format=%h', '-E', f'--grep=#{int(number)}([^0-9]|$)', '--', path)
        if code == 0 and out.strip():
            return f'{out.strip()} {path}'
    return ''


def body_history(root, path, fn, grep=None):
    """Commits whose diff reached fn's own lines, newest first, as (sha, date, subject).

    git follows the line range back from HEAD, so a fix to a neighbour in the same file is
    not this function's history (#2741, #2743, #2744, #2745 each carried the file's count).
    The range is read from the committed file: an edited one would shift it.
    """
    if subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', path], cwd=root, timeout=60).returncode:
        raise ValueError(f'{path} differs from HEAD: the history of a line range can only be read from a committed file')
    start = min([fn.lineno] + [d.lineno for d in fn.decorator_list])
    args = ['log', '-s', '--date=short', '--format=%h%x09%ad%x09%s']
    if grep is not None:
        args += ['-E', f'--grep=#{int(grep)}([^0-9]|$)']
    code, out = git(root, *args, f'-L{start},{fn.end_lineno}:{path}')
    if code:
        raise ValueError(f'cannot read the history of {path}:{start}-{fn.end_lineno}')
    return [tuple(line.split('\t', 2)) for line in out.splitlines() if line]


def recent_fixes(history, today=None):
    """The `fix` commits of a body history inside WINDOW days, as 'sha subject' lines."""
    since = ((today or datetime.date.today()) - datetime.timedelta(days=WINDOW)).isoformat()
    return [f'{sha} {subject}' for sha, date, subject in history if date >= since and subject.lower().startswith('fix')]


class Alpha(ast.NodeTransformer):
    """Rename what the function itself binds (parameters, assigned names) by first appearance.

    Globals, builtins, attributes and constants stay: two functions that call different
    helpers or compare against different values do not state the same fact.
    """
    def __init__(self, fn):
        self.names = {}
        outer = set()
        bound = []
        for n in ast.walk(fn):
            if isinstance(n, (ast.Global, ast.Nonlocal)):
                outer.update(n.names)
            elif isinstance(n, ast.arg):
                bound.append(n.arg)
            elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                bound.append(n.id)
        self.local = set(bound) - outer

    def _n(self, name):
        return self.names.setdefault(name, f'v{len(self.names)}') if name in self.local else name

    def visit_Name(self, n):
        n.id = self._n(n.id)
        return n

    def visit_arg(self, n):
        n.arg, n.annotation = self._n(n.arg), None
        return n


def canonical(fn, normalize):
    c = copy.deepcopy(fn)
    c.name = 'OWNER'
    if normalize == 'alpha':
        if c.body and isinstance(c.body[0], ast.Expr) and isinstance(getattr(c.body[0], 'value', None), ast.Constant) \
                and isinstance(c.body[0].value.value, str):
            c.body = c.body[1:] or [ast.Pass()]
        c.decorator_list, c.returns = [], None
        c = Alpha(c).visit(c)
    return ast.dump(c, include_attributes=False)


def unreferenced(root, symbol):
    """Lines in every tracked file that name the symbol, minus its own definition; None if gone."""
    path, name = split_symbol(symbol)
    if name.startswith('__') or Path(path).name == '__init__.py' or name == 'main' or name.startswith('test_'):
        raise ValueError(f'{symbol}: dunder names, package __init__ exports, main and tests are reached without a reference')
    node = top_level(root, symbol, FUNC + (ast.ClassDef,))
    if node is None:
        return None
    if node.decorator_list:
        raise ValueError(f'{symbol} is decorated: a registration point is used by its decorator, not by name')
    code, out = git(root, 'grep', '-w', '-F', '-c', '-I', '-e', name)
    if code not in (0, 1):
        raise ValueError('git grep failed')
    return sum(int(line.rsplit(':', 1)[1]) for line in out.splitlines()) - 1


def structure(contract, root):
    symbol, kind, after = contract.get('symbol'), contract.get('measure'), contract.get('after')
    path, _ = split_symbol(symbol)
    if kind not in MEASURES:
        raise ValueError(f'measure must be one of {MEASURES}; module size is not a measure')
    if not isinstance(after, int) or isinstance(after, bool) or after < 1:
        raise ValueError('after must be the positive target value of the measure')
    landing = contract.get('landing')
    if not isinstance(landing, list) or len(landing) < 2 or len(set(landing)) != len(landing) or symbol in landing:
        raise ValueError('landing must name at least 2 new path::function symbols the body is cut into')
    callers, precedent = contract.get('callers'), contract.get('precedent')
    if not isinstance(callers, int) or isinstance(callers, bool) or callers < 0:
        raise ValueError('callers must be the number of non-test use sites')
    if not isinstance(contract.get('benefit'), str) or len(contract['benefit'].strip()) < 12 \
            or not re.search(r'\d', contract['benefit']):
        raise ValueError('benefit must state a measured gain with a number, not "cleaner"')
    if not isinstance(precedent, list) or not all(isinstance(n, int) and not isinstance(n, bool) for n in precedent):
        raise ValueError('precedent must be a list of issue/PR numbers; [] means none, and the draft must say so')
    trees = list(population(root))
    cutoff = tail_cutoff([measure(n, kind) for _, t in trees for n in ast.walk(t) if isinstance(n, FUNC)])
    scale = f'{kind} p99 at this HEAD={cutoff}'
    node = top_level(root, symbol)
    landed = [(s, top_level(root, s)) for s in landing]
    values = {s: measure(n, kind) for s, n in landed if n is not None}
    absent = [s for s, n in landed if n is None]
    if node is not None and measure(node, kind) > after:
        value = measure(node, kind)
        if value < cutoff:
            raise ValueError(f'{symbol} {kind}={value} is below the tail ({scale}): long is not debt')
        if after >= cutoff:
            raise ValueError(f'after={after} leaves the function in the tail ({scale})')
        sites = references(root, symbol, trees)
        if len(sites) != callers:
            raise ValueError(f'callers={callers} claimed, measured {len(sites)}: {sites}')
        history = body_history(root, path, node)
        fixed = recent_fixes(history)
        claimed = contract.get('fixes')
        if claimed is not None and (isinstance(claimed, bool) or claimed != len(fixed)):
            raise ValueError(f'fixes={claimed} claimed, measured {len(fixed)} fix commits on the body of {symbol} in '
                             f'{WINDOW} days: {fixed} (the count for the whole file is not this function\'s)')
        unrelated = [n for n in precedent if not body_history(root, path, node, grep=n)]
        if unrelated:
            raise ValueError(f'precedent {unrelated} never changed the body of {symbol} '
                             f'(git log --grep "#N" -L{node.lineno},{node.end_lineno}:{path} is empty; '
                             'a fix elsewhere in the file is not a precedent for this function)')
        return True, (f'structure: claim=full {symbol} {kind}={value} target<={after} {scale} '
                      f'callers={callers} body-fixes-{WINDOW}d={len(fixed)} body-last-changed={history[0][1] if history else "never"} '
                      f'precedent={precedent or "none"} landing={landing}'), [path]
    # The original is at or under the target, or gone. That is a repair only if the body went
    # where the contract said and none of the pieces is as bad as what it replaced.
    if absent:
        raise ValueError(f'{symbol} is {"gone" if node is None else "under the target"} but landing {absent} '
                         'does not exist: the contract no longer describes this code')
    over = {s: v for s, v in values.items() if v > after}
    state = 'relocated' if node is None else 'moved-not-cut'
    if over:
        return True, f'structure: claim={state} {symbol} target<={after} {scale} landing={values}', [path]
    # Green is a claim too, so it is checked like the red one: the pieces must come out of this
    # function (used by it or by each other), and the caller count and precedent must be real.
    # A function that already existed and is used elsewhere is nobody's landing.
    pieces = [(path, node)] if node is not None else []
    pieces += [(split_symbol(s)[0], n) for s, n in landed]
    inside = lambda site: any(site.rsplit(':', 1)[0] == p and n.lineno <= int(site.rsplit(':', 1)[1]) <= n.end_lineno
                              for p, n in pieces)
    outside = {s: [site for site in references(root, s, trees) if not inside(site)] for s in landing}
    if node is not None:
        sites = references(root, symbol, trees)
        if len(sites) != callers:
            raise ValueError(f'callers={callers} claimed, measured {len(sites)}: {sites}')
        foreign = {s: sites for s, sites in outside.items() if sites}
    else:
        # The original is gone, so its callers may now call the pieces directly — but no more of them.
        foreign = {s: sites for s, sites in outside.items() if len(sites) > callers}
    if foreign:
        raise ValueError(f'landing {sorted(foreign)} is used outside {symbol} ({foreign}): '
                         'a function with its own callers was not cut out of this one')
    unrelated = [n for n in precedent if not precedent_touches(root, n, [path])]
    if unrelated:
        raise ValueError(f'precedent {unrelated} never changed {path} (git log --grep "#N" -- {path} is empty)')
    return False, f'structure: claim=repaired {symbol} target<={after} {scale} landing={values}', [path]


def evaluate(contract, root):
    """Return (violated, measurement, source paths). Malformed claims raise ValueError."""
    root = Path(root)
    if not isinstance(contract, dict):
        raise ValueError("contract must be a JSON object")
    kind = contract.get('check')
    if kind not in CHECKS:
        raise ValueError('unsupported check; naming and hand-picked thresholds are not evidence')
    for key in ('fact', 'repair', 'guard'):
        if not isinstance(contract.get(key), str) or len(contract[key].strip()) < 12:
            raise ValueError(f'{key} must explain the fact, owner/cut and regression guard')
    if kind == 'structure':
        return structure(contract, root)
    if kind == 'unreferenced-symbol':
        symbols = contract.get('symbols', [])
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols):
            raise ValueError('need 1..10 distinct path::name symbols')
        counts = {s: unreferenced(root, s) for s in symbols}
        dead = [s for s, n in counts.items() if n == 0]
        claim = 'full' if len(dead) == len(symbols) else 'partial'
        shown = {s: 'removed' if n is None else n for s, n in counts.items()}
        return bool(dead), f'unreferenced-symbol: claim={claim} references outside the definition={shown}', \
            [split_symbol(s)[0] for s in symbols]
    if kind == 'duplicate-python':
        symbols = contract.get('symbols', [])
        if not isinstance(symbols, list) or not 2 <= len(symbols) <= 10 or len(set(symbols)) != len(symbols):
            raise ValueError('need 2..10 distinct path::function symbols')
        normalize = contract.get('normalize', 'exact')
        if normalize not in ('exact', 'alpha'):
            raise ValueError('normalize is exact (default) or alpha (own parameters/locals renamed)')
        bodies, paths, sizes = [], [], []
        for symbol in symbols:
            path, name = symbol.split('::')
            tree, _ = source(root, path)
            matches = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name]
            if len(matches) != 1:
                raise ValueError(f'{symbol} must resolve to one top-level function')
            n = matches[0]
            # exact keeps arguments, constants and identifier references; ignore only declaration name.
            sizes.append(n.end_lineno - n.lineno + 1)
            bodies.append(canonical(n, normalize))
            paths.append(path)
        if len(set(paths)) < 2:
            raise ValueError('need implementations in distinct modules')
        if min(sizes) < 5:
            return False, f'duplicate-python: copies=0 (wrappers/tiny idioms) lines={sizes} symbols={symbols}', paths
        copies = max(bodies.count(body) for body in set(bodies))
        return copies >= 2, f'duplicate-python: copies={copies} of {len(symbols)} symbols lines={sizes} symbols={symbols}', paths
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
    if Path(path).parts[0] not in ('src', 'ops'):
        raise ValueError('dependency source must be in src or ops')
    local = {p.stem for p in (root / Path(path).parts[0]).rglob('*.py')}
    if name.split('.')[0] in local:
        raise ValueError('repository-local import is not an external dependency')
    seen = imports(tree)
    if name not in seen:
        raise ValueError(f'{name} is not imported by {path}')
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    specs = list(project.get('dependencies', []))
    for extra in project.get('optional-dependencies', {}).values():
        specs.extend(extra)
    normalize = lambda s: re.sub(r'[-_.]+', '-', s).lower()
    declared = {normalize(re.split(r'[<>=!~\[; ]', s, 1)[0]) for s in specs}
    guard_tree = ast.parse((root / DEPENDENCY_GUARD).read_text())
    aliases = next((ast.literal_eval(n.value) for n in guard_tree.body
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'DISTRIBUTION'
                                                         for t in n.targets)), None)
    if not isinstance(aliases, dict):
        raise ValueError('dependency alias owner missing or not a literal mapping')
    dist = aliases.get(name.split('.')[0], name.split('.')[0])
    missing = normalize(dist) not in declared
    return missing, f'undeclared-import: {path} imports={name} distribution={dist} declared={sorted(declared)}', [path, 'pyproject.toml']


def red_command(contract, tool):
    return 'python3 ' + shlex.quote(str(Path(tool) / 'debt_check.py')) + ' ' + shlex.quote(json.dumps(contract, ensure_ascii=False, sort_keys=True))


def candidates(root, top=25):
    """Where a debt round should read first. Ranking only; every line still needs its contract."""
    root = Path(root)
    trees = list(population(root))
    funcs = [(p, n) for p, t in trees for n in ast.walk(t) if isinstance(n, FUNC)]
    cut = {k: tail_cutoff([measure(n, k) for _, n in funcs]) for k in MEASURES}
    print(f'# measured at this HEAD over {len(trees)} modules / {len(funcs)} functions; p99: ' +
          ' '.join(f'{k}={v}' for k, v in cut.items()))
    print(f'## tail functions (module-level, cc or length at/above p99; fix = fix commits whose diff reached '
          f'this function body in {WINDOW} days, last = its newest change of any kind; neither is the file\'s)')
    tail = []
    for p, t in trees:
        for n in t.body:
            if isinstance(n, FUNC) and (measure(n, 'cc') >= cut['cc'] or measure(n, 'length') >= cut['length']):
                try:
                    history = body_history(root, p, n)
                except ValueError:
                    continue
                tail.append((len(recent_fixes(history)), measure(n, 'cc'), history[0][1] if history else 'never', p, n))
    for fix, cc, last, p, n in sorted(tail, key=lambda r: (-r[0], -r[1]))[:top]:
        print(f'{p}:{n.lineno} {n.name} cc={cc} length={measure(n, "length")} nesting={measure(n, "nesting")} '
              f'fix={fix} last={last} callers={len(references(root, p + "::" + n.name, trees))}')
    print('## renamed copies across modules (normalize=alpha, >=5 lines)')
    groups = collections.defaultdict(list)
    for p, t in trees:
        for n in t.body:
            if isinstance(n, FUNC) and n.end_lineno - n.lineno + 1 >= 5:
                groups[canonical(n, 'alpha')].append(f'{p}::{n.name}')
    for members in sorted(groups.values()):
        if len({m.split('::')[0] for m in members}) >= 2:
            print(' == '.join(members))
    print('## module-level symbols no tracked file refers to')
    names = collections.defaultdict(list)
    for p, t in trees:
        for n in t.body:
            if isinstance(n, FUNC + (ast.ClassDef,)) and not n.decorator_list:
                names[n.name].append(p)
    seen = collections.Counter()
    _, files = git(root, 'ls-files')
    for path in files.splitlines():
        f = root / path
        if not re.search(r'\.(py|js|ts|mjs|sh|md|json|ya?ml|toml|html|txt|cfg|tsv|service|timer)$', path) \
                or path.startswith(('assets/data/', 'memory/')) or not f.is_file() or f.stat().st_size > 1_500_000:
            continue
        seen.update(t for t in re.findall(r'[A-Za-z_]\w*', f.read_text(errors='replace')) if t in names)
    for name in sorted(n for n, where in names.items() if seen[n] <= 1 and len(where) == 1):
        try:
            if unreferenced(root, f'{names[name][0]}::{name}') == 0:
                print(f'{names[name][0]}::{name}')
        except ValueError:
            continue


if __name__ == '__main__':
    try:
        if sys.argv[1:2] == ['--candidates']:
            candidates(Path.cwd(), int(sys.argv[2]) if len(sys.argv) > 2 else 25)
            sys.exit(0)
        if len(sys.argv) != 2:
            raise ValueError('usage: debt_check.py <contract-json> | --candidates [N]')
        violated, measured, _ = evaluate(json.loads(sys.argv[1]), Path.cwd())
        print(measured)
        print('DEBT RED' if violated else 'DEBT GREEN')
        sys.exit(1 if violated else 0)
    except (ValueError, OSError, SyntaxError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f'INVALID DEBT CHECK: {exc}', file=sys.stderr)
        sys.exit(2)

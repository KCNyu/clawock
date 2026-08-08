"""
Shared safe-write helpers for portfolio.json and other critical state files.

Atomic write pattern: write to a sibling .tmp file, fsync, then os.replace().
On POSIX os.replace is atomic — the file at the final path is either the old
content or the new content; never partial / truncated.

Strict JSON: `NaN`, `Infinity` and `-Infinity` are Python-specific tokens that
`json.dump` emits by default and that no strict parser accepts — including the
browser's `JSON.parse`, which consumes every file under `assets/data/`. One
non-finite float therefore takes the whole dashboard card down, and the ratio
computations upstream (β, Sharpe, correlation) produce them from degenerate
windows without anyone writing a literal `nan`. `json_repair` already refuses
these tokens on the read side; this module closes the same hole on the write
side.
"""
import contextlib
import fcntl
import json
import math
import os
import sys
import tempfile


@contextlib.contextmanager
def file_lock(path: str):
    """Advisory exclusive flock on `<path>.lock`, held for the `with` block.

    Atomic write (safe_write_json) prevents a *half-written* file, but NOT a
    lost update: two writers that both load -> modify-in-memory -> write will
    have the second clobber the first's fields (the load-modify-write race that
    has bitten portfolio.json, e.g. the gold-vs-market overlap). Hold this lock
    across the WHOLE read-modify-write so writers serialize. Keep the critical
    section short — do any network I/O BEFORE acquiring, never inside.
    """
    lock_path = str(path) + '.lock'
    lf = open(lock_path, 'w')
    try:
        fcntl.flock(lf, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lf, fcntl.LOCK_UN)
        finally:
            lf.close()


def mutate_json(path: str, mutate_fn, default=None):
    """Lock + read-fresh + mutate + atomic-write, as one serialized critical
    section. `mutate_fn(data)` receives the freshly-read dict (so it never works
    off a stale copy) and returns the dict to write (or mutates in place).
    Correct pattern for fetchers: do the network fetch first, then
    `mutate_json(PORTFOLIO, lambda d: merge(d, fetched))` — the merge re-reads
    the current file under lock and applies fetched fields without clobbering a
    concurrent writer's changes."""
    path = os.path.abspath(path)
    with file_lock(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            data = default
        new = mutate_fn(data)
        if new is None:
            new = data
        safe_write_json(path, new)
        return new


def json_safe(data, _path: str = '$', _found=None):
    """Return `data` with every non-finite float replaced by `None`.

    Returns `(sanitized, paths)` where `paths` names each replaced value, e.g.
    `['$.us.beta', '$.holdings[3].sharpe']`. Producers that can reason about a
    degenerate result should call this themselves and attach a reason to the
    field; `safe_write_json` calls it as the last line of defence.

    numpy scalars are coerced through `.item()` — `np.float32('nan')` is not a
    Python float and would otherwise slip past both the finiteness check and
    `json.dump`.
    """
    found = [] if _found is None else _found

    if isinstance(data, dict):
        out = {k: json_safe(v, f'{_path}.{k}', found)[0] for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        out = [json_safe(v, f'{_path}[{i}]', found)[0] for i, v in enumerate(data)]
    else:
        out = data
        # numpy scalars (np.float32/np.int64/...) expose .item(); str/bytes and
        # the JSON primitives do not, so this only catches the foreign types.
        if not isinstance(data, (str, bytes, bool, int, float, type(None))) \
                and hasattr(data, 'item') and callable(data.item):
            try:
                out = data.item()
            except (TypeError, ValueError):
                out = data
        if isinstance(out, float) and not math.isfinite(out):
            found.append(_path)
            out = None

    return out, found


def safe_write_json(path: str, data, indent: int = 2, strict: bool = False) -> None:
    """Atomically write `data` as pretty JSON to `path`.

    Guarantees: if the process crashes or disk fills, `path` either keeps its
    old content or gets the full new content. Never a half-written file, and
    never a file a strict parser rejects.

    Non-finite floats are replaced by `null` and reported on stderr. They are
    NOT a reason to drop the write: refusing to publish would turn a single bad
    field into a missing dashboard, which is the failure this is meant to
    prevent. Pass `strict=True` (tests, and producers that would rather abort
    than publish a hole) to raise instead.
    """
    data, non_finite = json_safe(data)
    if non_finite:
        detail = ', '.join(non_finite[:5])
        if len(non_finite) > 5:
            detail += f' … (+{len(non_finite) - 5} more)'
        msg = (f'{os.path.basename(path)}: {len(non_finite)} non-finite float(s) '
               f'written as null: {detail}')
        if strict:
            raise ValueError(msg)
        print(f'⚠ {msg}', file=sys.stderr)

    path = os.path.abspath(path)
    dirname = os.path.dirname(path) or '.'
    os.makedirs(dirname, exist_ok=True)

    # Create temp file in same dir so os.replace stays atomic (same filesystem)
    fd, tmp = tempfile.mkstemp(dir=dirname, prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            # allow_nan=False is deliberately kept even though json_safe has
            # already run: it turns a hole in the sanitizer into a loud failure
            # here instead of an invalid file on disk.
            json.dump(data, f, ensure_ascii=False, indent=indent, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Clean up the orphan tmp on any failure
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def safe_write_text(path: str, text: str) -> None:
    """Atomic text-file write — same guarantees as safe_write_json."""
    path = os.path.abspath(path)
    dirname = os.path.dirname(path) or '.'
    os.makedirs(dirname, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dirname, prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


if __name__ == '__main__':
    # Self-test
    import tempfile as _tf
    with _tf.TemporaryDirectory() as td:
        target = os.path.join(td, 'a.json')
        safe_write_json(target, {'x': 1, 'arr': [1, 2, 3]})
        assert json.load(open(target)) == {'x': 1, 'arr': [1, 2, 3]}
        print('safe_write_json: OK')

        # Concurrency self-test: N processes each increment a distinct key under
        # the lock. Without locking, load-modify-write loses updates and some
        # keys go missing; with mutate_json all N must survive.
        import multiprocessing
        ctr = os.path.join(td, 'ctr.json')
        safe_write_json(ctr, {})

        def _bump(i):
            import time
            import random
            time.sleep(random.random() * 0.02)
            mutate_json(ctr, lambda d: {**(d or {}), f'k{i}': i})

        procs = [multiprocessing.Process(target=_bump, args=(i,)) for i in range(20)]
        for p in procs:
            p.start()
        for p in procs:
            p.join()
        final = json.load(open(ctr))
        assert len(final) == 20, f'lost updates: only {len(final)}/20 keys survived'
        print('mutate_json concurrency (20 writers, no lost updates): OK')

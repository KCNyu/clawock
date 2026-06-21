"""
Shared safe-write helpers for portfolio.json and other critical state files.

Atomic write pattern: write to a sibling .tmp file, fsync, then os.replace().
On POSIX os.replace is atomic — the file at the final path is either the old
content or the new content; never partial / truncated.
"""
import contextlib
import fcntl
import json
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


def safe_write_json(path: str, data, indent: int = 2) -> None:
    """Atomically write `data` as pretty JSON to `path`.

    Guarantees: if the process crashes or disk fills, `path` either keeps its
    old content or gets the full new content. Never a half-written file.
    """
    path = os.path.abspath(path)
    dirname = os.path.dirname(path) or '.'
    os.makedirs(dirname, exist_ok=True)

    # Create temp file in same dir so os.replace stays atomic (same filesystem)
    fd, tmp = tempfile.mkstemp(dir=dirname, prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
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

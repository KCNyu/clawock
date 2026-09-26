"""One provider call per symbol, run side by side, answers in input order.

The quote refresh is a chain of per-symbol providers with 10–25 s timeouts. Run
one symbol after another, a provider having a bad minute costs timeout × symbols
before the next provider is even asked: measured on the live contexts, the
analyzer phase of a 美股盘中 slot went from its usual ~18 s to 50–120 s exactly
in the slots whose quotes fell through Finnhub, and a 港股 slot hit the 120 s
analyzer cap (2026-09-24 14:33). Overlapping the per-symbol waits bounds a tier
by its slowest symbol instead of the sum.

Only the waiting overlaps. Each caller keeps its provider order and its own
per-symbol rule for which answer wins, and consumes the answers in the order it
asked, so what is chosen — and what is printed — is what the serial loop chose.
"""
from concurrent.futures import ThreadPoolExecutor

MAX_WORKERS = 8


def each(fn, items, *args, max_workers=MAX_WORKERS):
    """`[fn(item, *args) for item in items]`, with the calls overlapped.

    An exception raised by `fn` surfaces here, as it would have from the loop.
    """
    items = list(items)
    if len(items) <= 1:
        return [fn(item, *args) for item in items]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return list(pool.map(lambda item: fn(item, *args), items))

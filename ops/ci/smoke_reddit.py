#!/usr/bin/env python3
"""Probe the same Reddit archive and schema the sentiment producer uses."""
from __future__ import annotations

import requests

from clawock.market_data.sentiment import REDDIT_SUBREDDITS, fetch_reddit_community


class Unreachable(Exception):
    """The runner was blocked, throttled or could not reach the archive."""


def check(get=None) -> tuple[str, int]:
    total = 0
    for subreddit in REDDIT_SUBREDDITS:
        try:
            _, count = fetch_reddit_community(subreddit, get=get)
        except requests.HTTPError as exc:
            code = exc.response.status_code
            if code in {403, 429}:
                raise Unreachable(f'r/{subreddit}: HTTP {code}') from exc
            raise
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as exc:
            raise Unreachable(f'r/{subreddit}: {type(exc).__name__}') from exc
        total += count
    return 'reachable', total


def main() -> int:
    try:
        verdict, count = check()
    except Unreachable as exc:
        print(f'::warning::Reddit archive unreachable from this runner ({exc})')
        return 0
    except (requests.RequestException, ValueError, OverflowError, OSError) as exc:
        print(f'::error::Reddit archive probe failed: {type(exc).__name__}: {exc}')
        return 1
    print(f'Reddit archive from this runner: {verdict} '
          f'({count} posts across {len(REDDIT_SUBREDDITS)} communities)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

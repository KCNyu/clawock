---
name: scrapling
description: Optional Scrapling adapter for static HTML or JS/anti-bot pages when normal fetch/search cannot retrieve the needed evidence. Use only when Scrapling and its required browser runtime are available; report retrieval gaps otherwise.
---

# Optional page retrieval

Use the current session's fetch/browser tools first. This repository directory
does not prove that a Scrapling tool or browser is installed or available in the
agent catalog. Check availability before offering to fetch; installation follows
`docs/operations/skills-store-policy.md` and the host's environment rules.

For an environment that already provides Scrapling:

```python
from scrapling.fetchers import Fetcher
page = Fetcher.get(url)  # static HTML, no browser
text = page.css('p::text').getall()
```

Only when JavaScript or anti-bot handling is needed and browser execution is
permitted in the current environment:

```python
from scrapling.fetchers import StealthyFetcher
page = StealthyFetcher.fetch(url, headless=True, network_idle=True)
text = page.css('p::text').getall()
```

Record the URL, retrieval time and what content was actually returned. A login,
challenge, rate limit or empty page is a retrieval gap, not evidence of no news.
Check installed API help if these calls differ from the available version.
Respect site access rules; do not launch bulk spiders for a single evidence check.

Stock prices still come from `clawock analyze-hk` / `clawock analyze-us` and their
configured providers. Social comments supply leads or sentiment, not primary
proof of filings, customer contracts or executable prices.

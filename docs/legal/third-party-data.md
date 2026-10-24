# Third-party data and services

The [MIT License](../../LICENSE) covers the original software in this repository. It
does **not** grant rights to third-party market data, news, social posts,
filings, trademarks, APIs, or other material retrieved by the software.

Anyone running or redistributing this project is responsible for checking the
current terms, access rules, rate limits, attribution requirements, privacy
requirements, and local laws that apply to each source. A publicly reachable
endpoint is not, by itself, permission to copy, redistribute, sublicense, or
use its content for model training.

Generated files may contain derived values, excerpts, headlines, or identifiers
from third-party services. Do not assume those files are covered by the MIT
License. Review the relevant provider terms before redistributing them or using
them commercially.

## Request hygiene

- Identify automated clients when a provider requires it.
- Prefer documented APIs and authenticated access where required.
- Respect provider rate limits, `Retry-After`, robots directives, and removal
  requests.
- Cache conservatively, request only what is needed, and fail closed rather
  than bypassing access controls.
- Do not imply that a data provider sponsors or endorses clawock.

## Source-specific notes

- **SEC EDGAR:** automated access must follow the SEC fair-access policy. The
  included client sends an identifying User-Agent and stays below the published
  request ceiling.
- **Reddit:** access and display are governed by Reddit's Developer and Data API
  terms, including access, attribution, rate-limit, user-content, and removal
  requirements. Public JSON availability is not a substitute for a compliant
  Data API setup.
- **Live information sources** (`clawock.evidence.live_sources`: HKEXnews,
  EDGAR full-text search, Google News RSS, Yahoo Finance RSS, 同花顺 7×24, 东财 7×24):
  each caller passes a per-source request budget, per-source concurrency cap,
  timeouts and a cache TTL; the intraday slot makes one HKEXnews and one EDGAR
  request per 30-minute slot for the whole book and one feed request per issuer.
  Only headlines, times and links are kept, for the session. HKEXnews content
  is subject to HKEX's terms of use; EDGAR full-text search follows the same
  SEC fair-access policy and User-Agent as the rest of the SEC client.
- **Finnhub personal research:** `fundamentals --analysts` uses the existing
  personal API key for ratings and reported earnings. Finnhub's
  [terms](https://finnhub.io/terms-of-service) prohibit sharing data or derived
  results without written permission. This new path is private-only, has a
  24-hour local cache, and is not a scheduled/public brief input.
- **FRED credit spreads:** `macro --credit-spreads` reads BAA10Y for private
  research. [Series notes](https://fred.stlouisfed.org/series/BAA10Y) carry Moody's
  copyright and redistribution restrictions. Free download is not a public
  publishing license. Values retain their observation date and definition.
- **US Treasury:** the public daily par curve CSV supplies 14 maturity points,
  dated yields and same-date slopes. It is an official reference curve, not a
  bond execution quote; Treasury's publication date remains attached.
- **Cboe:** daily VIX/VIX9D/VIX3M/SKEW closes come from the official public
  historical CSVs. Source URLs and observation dates travel with each row;
  access does not transfer ownership of index data or trademarks.
- **ExchangeRate-API Open:** daily FX reference rates use the no-key Open API.
  Attribution: [Rates by ExchangeRate-API](https://www.exchangerate-api.com/).
  [Open API terms](https://www.exchangerate-api.com/docs/free) apply; this is not
  an executable dealing rate.
- **Other market and news providers:** availability and usage rights vary by
  provider and can change independently of this repository. Re-check their
  current terms before operating the corresponding fetcher.

This notice is operational guidance, not legal advice.

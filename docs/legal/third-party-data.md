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
- **Other market and news providers:** availability and usage rights vary by
  provider and can change independently of this repository. Re-check their
  current terms before operating the corresponding fetcher.

This notice is operational guidance, not legal advice.

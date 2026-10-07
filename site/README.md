# Website source

This directory owns the static clawock website: Jekyll configuration and
layouts, the dashboard shell, browser code, icons, architecture visuals and
social media assets.

Public URLs intentionally do not include the `site/` prefix. The Pages workflow
uses `ops/pages/stage_site.py` to assemble a temporary Jekyll source tree, then
joins the static files here with the KCNyu instance's published JSON and public
reports. The staging step is one-way and never writes into the live workspace.

The HTML entry points link to `llms.txt`. Staging generates `faq.html.md` from
the visible FAQ and `llms-full.txt` from the overview, FAQ and external-agent
invocation protocol. The Pages allowlist requires both generated files. These
are documentation conveniences for agents that fetch them, not search ranking
signals. Discovery sources and the measurement protocol are in
[`docs/operations/agent-discovery.md`](https://kcnyu.github.io/clawock/docs/operations/agent-discovery.md).

`assets/data/` therefore remains outside this directory for now: it is generated
runtime state with its own data-plane publication contract, not website source.

`assets/dashboard.gif` is the animated dashboard preview linked from both READMEs
and the published clawock 0.2.0 PyPI description. It remains a repository-only
asset and is excluded from Pages artifacts. The screenshot refresh workflow regenerates it
from the live dashboard only on manual dispatch; its two PNGs refresh weekly.

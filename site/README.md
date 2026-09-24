# Website source

This directory owns the static clawock website: Jekyll configuration and
layouts, the dashboard shell, browser code, icons, architecture visuals and
social media assets.

Public URLs intentionally do not include the `site/` prefix. The Pages workflow
uses `ops/pages/stage_site.py` to assemble a temporary Jekyll source tree, then
joins the static files here with the KCNyu instance's published JSON and public
reports. The staging step is one-way and never writes into the live workspace.

`assets/data/` therefore remains outside this directory for now: it is generated
runtime state with its own data-plane publication contract, not website source.

`assets/dashboard.gif` is a compact six-frame compatibility preview. The published
clawock 0.2.0 PyPI description links to its raw `master` URL and cannot be edited.
The current README uses the weekly social card and live dashboard link instead.
The compatibility preview is not part of the screenshot refresh workflow.

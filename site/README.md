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

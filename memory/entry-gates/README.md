# Pre-investment entry gate artifacts

One assessment per file: `memory/entry-gates/<TICKER>-<YYYY-MM-DD>.json`. The file
is the record of why a name was or was not worth a deep-research run.

```bash
clawock entry-gate validate memory/entry-gates/<TICKER>-<date>.json
clawock entry-gate assess   memory/entry-gates/<TICKER>-<date>.json
```

Shape: `src/clawock/config/entry_gate.schema.json`. Hard vetoes and their encoded industry
exceptions: `config/entry-gate-vetoes.json`. Workflow:
`skills/entry-gate/SKILL.md`. A worked example lives in
`tests/fixtures/entry-gates/`.

What the script decides regardless of what the artifact claims:

- `verdict` and `routing` are recomputed; a stated verdict that disagrees is an error;
- vetoes resolve before any check is counted, so a good tally cannot outweigh one;
- `information.grade` comes from the cited evidence source classes — a `C` grade
  yields `gray_needs_evidence`, never `reject`;
- quotes must come from the workspace pipelines, and a stale quote makes the
  verdict gray.

---
name: incident-python-fstring
description: "CI failure"
metadata:
  type: project
  updated: 2026-11-08
  salience: normal
  status: verified
  tags: "ci, python"
---

CI failed on the old interpreter: nested f-strings need Python 3.12, while the CI image still ran 3.11 for that shard.

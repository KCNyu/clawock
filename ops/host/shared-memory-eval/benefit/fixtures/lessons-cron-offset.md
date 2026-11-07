---
name: lessons-cron-offset
description: "scheduled job timing"
metadata:
  type: project
  updated: 2026-11-08
  salience: normal
  status: verified
  tags: "cron, schedule"
---

Run scheduled jobs at five past the hour, not on the hour. The top of the hour is when every clock-driven job competes for the same lock.

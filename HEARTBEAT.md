# HEARTBEAT.md

_状态：idle — 无待办任务，回复 `HEARTBEAT_OK` 即可。_

## 如何工作

openclaw 收到 heartbeat poll 时会自动注入提示，让 agent 读这个文件并严格 follow。规则：

- **本文件 idle 状态**（当前）→ agent 直接回复 `HEARTBEAT_OK`，不做任何动作
- **本文件有具体任务**（譬如下面的"待办任务"段）→ agent 严格执行该任务，完成后把本文件改回 idle 状态

## 待办任务

_（无）_


# 阶段 1：公开仓库边界复核稿

基线为 `cf5c75ce2`。`phase-1-file-inventory.tsv` 对该提交的 2,089 条 Git 路径逐条列出类别、建议、理由和影响面。清单中的动作是切换建议。代码、测试和文档各有一栏，标明是否沿用现行契约或需在切换前核验。README 明确列出的能力按产品保留，包括 DSH 派发队列、agent-dispatch runner、回收单元、六个 runner 测试和对应 CI。本 PR 只增加复核材料，保留工作区文件、跟踪规则及现行发布链。

## 跟踪规则草案

以下规则随对应文件和写入者迁移后启用。以精确路径检查覆盖范围。启动模板、许可、示例、覆盖率徽标及产品证据附件仍可加入仓库。上述简报规则在 data-plane 完整上线后启用于 master。原放行项随迁移退役。对不公开内容增加提交和 CI 闸，覆盖强制添加的情况。

```gitignore
/AGENTS.md
/CLAUDE.md
/TOOLS.md
/MEMORY.md
/DREAMS.md
/SOUL.md
/IDENTITY.md
/USER.md
/HEARTBEAT.md
/portfolio.json
/config/profiles/kcnyu/
/config/watch-list.json
/config/entry-gate-vetoes.json
/ops/host/shared-memory/publish-manifest.json
/ops/ci/legacy_plan_book_values.json
/logs/
/memory/*-pre-open.md
/memory/weekly/
# 按逐文件清单处理其他实例状态，保留公开可复算的输入。
/assets/data/*
!/assets/data/coverage.json
```

切换采用正常 Git 提交。保留已安装实例的文件及路径后，取消索引跟踪，并验证干净新 clone 使用合成数据可启动。历史保留现状。

## 文档草案

| 文件 | 改法 |
|---|---|
| `AGENTS.md`、`CLAUDE.md`、`TOOLS.md`、`SOUL.md`、`IDENTITY.md`、`USER.md`、`HEARTBEAT.md` | 原样留在本地并退出跟踪。CLAUDE 仍然指向本地 AGENTS，保留现有运行时行为。BOOTSTRAP 与 INVESTMENT_SOP 的切换同样先查运行消费者。编写独立的 `CONTRIBUTING.md`，补贡献流程、worktree、分支、定向与 CI 验证。同步 README、CI 触发项和根 allowlist。 |
| `README.md`、`README.zh.md`、`docs/how-the-desk-works*.md`、`docs/decision-mind-ledger.md` | 说明 Dashboard 发布数据可用于核算。当前保留可独立复算的决策账本、bars、snapshots 和计划，原始持仓账本私有化。保留 Daily briefs 链接与评分公式，更新两版 README 的投影与贡献说明。|
| `docs/architecture/{agent-memory-unified,memory-components,dispatch-memory-intake}.md`、`docs/operations/dreaming-review.md`、共享记忆维护说明 | 将 `publish: public` 描述为本地面向助手的投影级别；两个根投影、清单和审阅回执归实例目录。说明迁移报告、召回退出步骤、运行窗口和回滚开关。|
| `docs/architecture/{data-plane,harness,brief-versions}.md`、`docs/reference/{data-coverage,product-profile-operations}.md`、`site/{README,faq,briefs}.md`、`ops/publish/README.md` | 写清 runtime、Pages 和既有 data-plane 的来源与责任。公开最新简报的页面和 JSON 按现网契约保留，源文件由部署通道供给。保留数值、缺失语义、窗口及所有公开 URL。|
| `docs/README.md`、`docs/design/workbench-conformance.md` | 清理待删除设计对照的链接和图表。保留仍有回归引用的布局契约。|
| `docs/operations/{openclaw-patch-kit,release}.md`、`skills/openclaw-upgrade/SKILL.md` | 记录 fork 源码与已安装产物身份校验，以及主机专用配置的重放入口。使用变量说明路径。|

## 切换前的代码、测试和文档勾选

| 路径或能力 | 代码 | 测试 | 文档 |
|---|---|---|---|
| Dispatch runner、回收 service/timer、六个 runner 测试、DSH 示例 | ✓ 保留入口 | ✓ 保留测试和 CI | ✓ README 的 Harness 界面与后台工作 |
| `memory/decisions.jsonl`、bars、snapshots、计划 | ✓ 保留现有公开溯源与读取 | ✓ 现行 CI | ☐ README 区分公开决策数据与原始持仓账本 |
| 日简报及周复盘 | ☐ data-plane 同代写入、回填、Pages 严格读取 | ☐ 条目数、5 篇正文、最新链接、失败路径 | ☐ URL 保留，更新来源说明 |
| `portfolio.json` | ☐ 三个 postflight、Actions 回退和发布先脱离公开原始账本 | ☐ 持仓更新时效、Dashboard 和 cron 回归 | ☐ 账本路径保持本地 |
| `config/profiles/kcnyu/profile.json` | ☐ 保持本地解析，公开仅留中性 profile 和 schema | ☐ conftest 和 delivery profile 改用中性数据 | ☐ 更换公开示例链接 |
| `MEMORY.md`、`DREAMS.md` 与运行时根文件 | ☐ context manifest、assembly、system_check、git guard 和 allowlist 同步 | ☐ 缺省可启动、本机投影与 store 一致、运行时原文逐字节一致 | ☐ CONTRIBUTING 独立和双语 README 同步 |
| 设计稿和图 | ☐ 删除清单逐项核引用 | ☐ 查断链，保留产品图和测试引用 | ☐ 索引和设计契约同次更新 |

简报与周复盘以现有 public Markdown 原文迁 data-plane。建立完整归档索引和摘要后再切换写入，Pages 从同一 ref 拉取归档和面板数据。拉取不全立即失败。保持目前的 URL 和正文；最终验收在实际页面点开最新一期，核条目数及 5 篇样本。基线盘点为每日 136 篇、每周 27 篇，共 163 篇。已知并接受简报和卡片继续公开股数、成本、浮盈金额。

原始账本不能通过 `git add -f` 重新提交到 public master。先让三条 postflight 分别提交剩余公开产物，在本地保留持仓路径，同时为离机校验、回退和 Dashboard 更新接通所需输入。不同路径的移出与 allowlist、CI、代码、测试同步验证后实施。任何破坏数值、更新时效、90 天窗口、缺失标记或导航的切换都撤回。

## 本地工作区

本机另盘点到 6,115 条未跟踪文件和链接（含忽略项；Git 元数据库单列）。完整路径和大小审计留在本机。

| 路径 | 大小（磁盘，基线） | 实际读者、保留建议和恢复方式 |
|---|---:|---|
| `memory/scorecard-inputs/` | 266 MiB | `scorecard-provenance --check --recompute` 用内容寻址快照恢复该简报写回前后账本；旧账、行情和上下文会变化，不能等价重建。保留。归档前建立上下文引用索引，搬运需受保护备份。 |
| `examples/` | 133 MiB | 约 130 MiB 是已忽略的 DSH `node_modules`，本机打包、安装和测试读取。源码、锁和跟踪的 `lib` 有发布读者。保留当前依赖，可用锁定的安装命令重建。 |
| `.git/` | 491 MiB | 共享 worktree、Git 输入、评分来源与回滚都用。保留。 |
| `media/inbound/` | 4.4 MiB | OpenClaw 接收附件且会话可能仍引用原路径。上传原件无法重建。保留；需先核实会话保留窗口和可恢复备份。 |
| `logs/` | 3.4 MiB | Cron 健康、发布诊断及故障审计有读者。现有 `gc_sessions.py` 已按大小和尾部窗口裁剪 append-only 日志，同时保留状态文件。继续沿用，保留目录。 |
| `.data-plane.cache/` | 1.2 MiB | 定时发布将上一代用作缺输入时的卡片恢复和语义对比基线。保留；可从受验证的发布分支重建。 |

清理候选另包括 `memory/brief-versions`、`memory/dreaming/light` 及逐个确认的旧日志或媒体。Brief versions 有版本恢复读者，light 仍是召回来源，scorecard-inputs 仍是复算输入。每项要先核引用或结束读者迁移，确认可恢复备份后再按文件清理。删除验收需 Dashboard 对拍和 cron 档冒烟。

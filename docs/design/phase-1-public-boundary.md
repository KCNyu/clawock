# 阶段 1：公开仓库边界复核稿

基线为 `cf5c75ce2`。`phase-1-file-inventory.tsv` 对该提交的 2,089 条 Git 路径逐条列出类别、建议、理由和影响面。清单中的动作是切换建议。本 PR 只增加复核材料，保留工作区文件、跟踪规则及现行发布链。

## 跟踪规则草案

以下规则随对应文件和写入者迁移后启用。以精确路径检查覆盖范围。启动模板、许可、示例、覆盖率徽标及产品证据附件仍可加入仓库。原 `memory/*-pre-open.md` 和 `logs/dashboard_build_status.json` 的放行项随迁移退役。对不公开内容增加提交和 CI 闸，覆盖强制添加的情况。

```gitignore
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
/memory/*
!/memory/backtests/
/memory/backtests/*
# 将通过 R&D 审核的产品证据迁到合成示例或证据目录。
/assets/data/*
!/assets/data/coverage.json
```

切换采用正常 Git 提交。保留已安装实例的文件及路径后，取消索引跟踪，并验证干净新 clone 使用合成数据可启动。历史保留现状。

## 文档草案

| 文件 | 改法 |
|---|---|
| `AGENTS.md` | 用“实例账本、计划、原始简报、记忆和回执保存在本地部署目录。站点通过约定的发布数据接口读取展示产物”替换 Runtime commits 的公开承诺与直推表。Memory 节以 shared store 为真源、两个本地投影和三个审核去向为准。|
| `CLAUDE.md`、`TOOLS.md`、`BOOTSTRAP.md`、`INVESTMENT_SOP.md` | 公开 agent 命令和初始化步骤改为参数化工作区；将个人约束、主机绝对路径与账号相关示例迁到本地。|
| `README.md`、`README.zh.md`、`docs/how-the-desk-works*.md`、`docs/decision-mind-ledger.md` | “账本全部公开”“公开账本”“从公开分支复算”改为“使用自有账本或合成示例复算”。保留评分公式、命令和页面链接；同步两版 README。|
| `docs/architecture/{agent-memory-unified,memory-components,dispatch-memory-intake}.md`、`docs/operations/dreaming-review.md`、共享记忆维护说明 | 将 `publish: public` 描述为本地面向助手的投影级别；两个根投影、清单和审阅回执归实例目录。说明迁移报告、召回退出步骤、运行窗口和回滚开关。|
| `docs/architecture/{data-plane,harness,brief-versions}.md`、`docs/reference/{data-coverage,product-profile-operations}.md`、`site/{README,faq,briefs}.md`、`ops/publish/README.md` | 写清 runtime、Pages 和既有 data-plane 的来源与责任。公开最新简报的页面和 JSON 按现网契约保留，源文件由部署通道供给。保留数值、缺失语义、窗口及所有公开 URL。|
| `docs/README.md`、`docs/design/workbench-conformance.md` | 清理待删除设计对照的链接和图表。保留仍有回归引用的布局契约。|
| `docs/operations/{openclaw-patch-kit,release}.md`、`skills/openclaw-upgrade/SKILL.md` | 记录 fork 源码与已安装产物身份校验，以及主机专用配置的重放入口。使用变量说明路径。|

## Dashboard 切换前提

- `memory/snapshots`、`memory/bars/*.json`、`memory/decisions.jsonl`、`portfolio.json`、`assets/data` 及现有 `data-plane` 都有读者。保留目录、内容和保留窗口。按 `config/pages-public.json` 同步浏览器数据清单。
- Pages 先取 data-plane，再由 `ops/pages/stage_site.py` 枚举 `memory/*-pre-open.md` 和 `memory/weekly` 以及复制 `assets/data`。仅取消跟踪会让最新简报和历史简报消失，且让若干面板数据路径变空。应先在隔离构建中证明现有 Pages 发布来源可替换。
- `scorecard_provenance.dashboard_source` 目前用 `git show` 取 `origin/master` 的原始账本，`verify_public_source` 检查该引用祖先关系；决策卡会显示核验状态。换本地来源需要固定快照身份，并保持旧发布代与新发布代的验证语义和字段。若要保留公众对新增评分的独立复算，必须明确其可访问证据。
- 风险、计划、周复盘和回退 workflow 仍读取或提交原始实例数据，CI 也从根账本校验。先迁移 writer、CI 夹具、GitHub Actions 输入及健康回执。用干净 clone 和暂存站点抽查 latest-brief、组合曲线、回撤、β/Vol、决策卡。用同一输入、水位和时钟生成五份 Dashboard JSON，逐字段对比。
- 验证任何一项数字、窗口、缺失标记或页面有变化，保持现行读写路径并撤回切换。直接运行常规 live 快进，Git 可能移除已取消跟踪的路径。部署先备份、按路径恢复、核字节与权限，然后才接回调度。

## 本地工作区

| 路径 | 大小（磁盘，基线） | 实际读者、保留建议和恢复方式 |
|---|---:|---|
| `memory/scorecard-inputs/` | 266 MiB | `scorecard-provenance --check --recompute` 用内容寻址快照恢复该简报写回前后账本；旧账、行情和上下文会变化，不能等价重建。保留。归档前建立上下文引用索引，搬运需受保护备份。 |
| `examples/` | 133 MiB | 约 130 MiB 是已忽略的 DSH `node_modules`，本机打包、安装和测试读取。源码、锁和跟踪的 `lib` 有发布读者。保留当前依赖，可用锁定的安装命令重建。 |
| `.git/` | 491 MiB | 共享 worktree、Git 输入、评分来源与回滚都用。保留。 |
| `media/inbound/` | 4.4 MiB | OpenClaw 接收附件且会话可能仍引用原路径。上传原件无法重建。保留；需先核实会话保留窗口和可恢复备份。 |
| `logs/` | 3.4 MiB | Cron 健康、发布诊断及故障审计有读者。现有 `gc_sessions.py` 已按大小和尾部窗口裁剪 append-only 日志，同时保留状态文件。继续沿用，保留目录。 |
| `.data-plane.cache/` | 1.2 MiB | 定时发布将上一代用作缺输入时的卡片恢复和语义对比基线。保留；可从受验证的发布分支重建。 |

上述目录没有满足“无读者、可重建、非运行输入”三项的整体删除候选。逐文件确认读者和恢复方式后再评估清理。后续若有精确到文件的候选，采用同一输入的 Dashboard 对拍和 cron 档冒烟复核。

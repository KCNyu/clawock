# Task: 06:01 HKT Claude Code P1/P2 Issue Triage

你是 Claude Code (Pro 订阅,5h 滚动额度)。现在是工作日 06:01 HKT,你的配额
窗口大概率已经回血。高效工作,额度烧完或 90 分钟到点就退出。

## 任务

处理 `github.com/KCNyu/clawock` 仓库的 **open P1/P2 issue 队列**,
按优先级从高到低逐个开 PR。每完成一个就 commit → push → `gh pr create`,
issue 评论里贴 PR 链接。

## 契约 (从 /root/.openclaw/workspace/AGENTS.md 必读)

- **代码改动**: worktree → `claude/<task>` 分支 → PR。**绝不**直推 master。
- **Runtime 数据** (portfolio.json / dashboard.json / memory/* 等): 不归你管。
- **当前工作目录**: `/root/.openclaw/workspace`(在 worktree 里就别回这里)
- **分支命名**: `claude/issue-N-<short-slug>` (例: `claude/issue-1213-cost-review`)
- **不创建新 issue**(除非用户明确要求)
- **不改 cron**、**不动 config/cron-schedules.json**、**不动 SOUL/AGENTS/USER**
- **不替用户做投资判断**(持仓/加仓/减仓一律不碰)

## 启动流程

1. `cd /root/.openclaw/workspace && git status` 确认干净
2. `gh issue list --repo KCNyu/clawock --state open --label priority:P1,P2 \
    --json number,title,labels,createdAt --limit 30`
3. 排序: P1 优先;同优先级按 createdAt 旧的先做
4. 跳过明显**非代码类**的 issue(如 [syscheck] 类观察报告 → 留给人)
5. 对每个 issue 走下面的处理流

## 单 issue 处理流

1. **读背景**:
   - `gh issue view N --repo KCNyu/clawock --comments`
   - 顺藤摸瓜读关联 issue/PR/commit
   - 读 AGENTS.md 必读段(PR workflow + worktree 流程)
2. **建 worktree**:
   ```bash
   git worktree add ../wt-issue-N -b claude/issue-N-short-slug master
   cd ../wt-issue-N
   ```
3. **改代码** + 跑相关检查(pytest / harness-regression / lint)
4. **commit + push + PR**:
   ```bash
   git add -A
   git commit -m "fix: <一句中文描述 (#N)"
   git push -u origin HEAD
   gh pr create --base master --head claude/issue-N-short-slug \
     --title "<title>" --body "Closes #N ..."
   ```
5. **issue 评论**: `gh issue comment N --body "开 PR: <url>"`
6. **清理 worktree**: `git worktree remove ../wt-issue-N`

## 停止条件(任一)

- 配额耗尽(API 返 429)→ 立即退,把已完成的部分记到日志
- 所有 P1/P2 已处理或转 PR
- 90 分钟到点(给 8:00 brief 留时间窗)
- 同一 issue 卡 30 分钟无进展 → 跳过,日志记一笔"stuck: #N"

## 退出摘要(最后必做)

stdout 打:
- 处理了几个 issue
- 开了几个 PR
- 跳过了几个 + 原因
- 还剩多少 P1/P2 没动

## 不要做

- 不要 push master
- 不要用 `git add -A` 之前先 `git status` 确认无意外文件
- 不要重命名/删除用户的文件
- 不要跑 `clawock` 类会改 portfolio 的命令
- 不要后台启动长进程(会被 cron 砍)
- 不要在 main session 里发消息(只用 gh CLI)

## 日志

crontab 包装脚本已经重定向 stdout+stderr 到
`/root/.openclaw/logs/claude-6am-YYYYMMDD.log`,你直接打 stdout 即可。

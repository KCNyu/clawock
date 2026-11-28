# 重写评估

逐文件判断和当前行数见 `phase-1-rewrite-assessment.tsv`。条件 R1 为职责已变，R2 为重复或过时，R3 为契约测试按语义断言，R4 为可缩短且保留要求。整体重写须满足至少两项。运行时自动注入文件只处理跟踪状态，保持原文。

## 调研如何应用

- 把操作顺序、失败条件与同代输入契约留在入口，将分析、输出和写作约束按阶段读取。保留单轮回退对同一权威规则的读取。上下文预算记录常驻输入、按需读取和缩减顺序。[Anthropic context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents)
- Skill 描述写调用时机、输入、输出、失败条件，明确手动复盘走另一入口。用一层直接链接按任务消费 reference。[Claude Skill authoring](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- 回归先用真实失败及通过案例，固定输入和期望事实。schema、字段和引用可由程序核查，评测结果作为 CI 条件。[OpenAI eval best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
- 示例服务首次运行，运维文档服务排班及故障处理，schema 与字段表归 reference，架构解释职责和来源。[Diátaxis](https://diataxis.fr/)

实施按简报 Skill、evals、cron payload、上下文预算顺序，各有独立 PR。Skill 拆分时按原小节保留要求和覆盖表，复用已公开的运行回执字段与日期，核对新入口和离机回退。后续证据定位、schema 生成和机械检查另验实际消费者。

# 记忆召回性能：一次召回拆成五段

本文记录 2026-11-07 对 OpenClaw `memory_search` 的实测，以及最后只做的那一刀。
被测库与维护记录见 [`sqlite-maintenance.md`](sqlite-maintenance.md)。

## 结论先说

- **7.7 s 不是稳态**。同一个 gateway、同一个查询集，热召回中位数是
  **347.7 ms**（维护前）→ **139.9 ms**（VACUUM 后）→ **119.5 ms**（补丁后）。
  7–9 s 是 **gateway 重启/长时间空闲后的第一次召回**：模型加载 + 首次
  embedding + 冷页缓存；第二次就回到百毫秒级。
- 热路径最大的一段原本是 **sqlite-vec KNN**，不是查询向量化：
  242.6 ms / 347.7 ms。它慢的原因主要是 101,491 页的库 + 7,256 页 freelist
  造成向量表页跳读；离线 `VACUUM` 把它降到 39.1 ms。
- 最小代码改动是 **KNN oversample 8 → 1**：热 KNN 39.1 → 24.9 ms，
  总召回 139.9 → 119.5 ms；5 个固定中文查询的 top-10 完全一致。
- 冷启的瓶颈在 **300M embedding 模型本身**：首次 embedding 3.0–5.1 s，
  模型/provider 初始化 0.9–2.0 s。1.9 GB 内存、无 GPU、`threads: 1`
  （多线程路径有已知死锁）就是当前下限。不改模型/维度/线程，就没有免费的大幅提升。

## 方法

- 用真实 `MemoryIndexManager`（与 `memory_search` 同一条代码路径），在独立
  Node 进程里包住 `searchKeywordWithFallback`、`embedQueryWithRetry`、
  `searchVector`、`mergeHybridResults`、`ensureProviderInitialized`、
  `ensureVectorReady` 计时；不经过 agent 的自然语言回合。
- 5 个固定查询：`昨天美股为什么跌`、`记忆索引 SQLite 压缩`、`dsh 任务派发`、
  `港股开盘报告`、`quant regime`；每个状态跑 5 轮 × 5 查询，取每轮中位数。
- 热路径取第 1–4 轮（第 0 轮是进程内第一次召回，单独算冷启）；
  `/proc/loadavg` 随每次输出记录，报告里标明当时负载。
- 2026-11-07 的共享主机负载：维护前 1.1–2.0，维护/补丁后 1.3–2.8，
  对比期间有 dsh/巡检任务并发；绝对毫秒会随负载漂移，比例和同负载下的前后对比更可靠。
- 质量对比用 `path:startLine:score`（score 6 位小数）的 top-10 签名，逐查询比对。

## 热召回：五段中位数

单位 ms；每格是该状态下 5 个查询 × 4 轮的中位数。`其他` 是总耗时减去四段后的残差
（manager 查找、JS 开销、SQLite 打开等）。

| 段 | 维护前 | VACUUM 后（未打补丁） | 打补丁后 |
|---|---:|---:|---:|
| 查询向量化（provider init + embed） | 57.0 | 57.0 | 58.6 |
| 读库 + 反序列化 | 0（未发生，见下） | 0 | 0 |
| 相似度计算（sqlite-vec KNN + join） | 242.6 | 39.1 | 24.9 |
| FTS + 合并（含 MMR/时间衰减） | 33.3 | 30.7 | 30.5 |
| 其他 | 14.8 | 13.1 | 5.5 |
| **合计** | **347.7** | **139.9** | **119.5** |

逐查询合计中位数（打补丁后）：`昨天美股为什么跌` 147.5、
`记忆索引 SQLite 压缩` 120.9、`dsh 任务派发` 123.5、`港股开盘报告` 112.6、
`quant regime` 94.3。

### 读库+反序列化为什么是 0

索引有 `memory_index_chunks_vec`（sqlite-vec `vec0`）且 `ensureVectorReady`
成功，搜索走的是：

```sql
SELECT ..., vec_distance_cosine(v.embedding, ?)
FROM memory_index_chunks_vec v JOIN memory_index_chunks c ON c.id = v.id
WHERE v.embedding MATCH ? AND k = ? ...
```

`vec0` 直接读 float32 向量，不存在“逐行读 8,697 条 embedding JSON 再
`parseEmbedding`”。`searchChunksByEmbedding`（逐行读 + JSON 反序列化）只在
`ensureVectorReady` 失败时作为 fallback；本次没有走到。因此疑点②不是本机的原因。

### 为什么 KNN 原来要 242 ms

维护前 `searchVector` 的候选上限是 `limit × 8`（这里 40 × 8 = 320），
而 `vec0` 要对 8,697 条 × 768 维做精确 KNN。`VACUUM` 把 101,491 页压到
94,192 页、freelist 清零后，同一 k=320 的扫描从 242.6 ms 降到 39.1 ms；
再把 k 降到 40，降到 24.9 ms。两者叠加是 242.6 → 24.9 ms（−90%）。

## 冷启：第一次召回的 6–9 秒花在哪

一次代表性的时间线（补丁后，gateway 正常，load 1.3；各段有嵌套/重叠，
所以不能简单相加）：

| 段 | 开始 → 结束（ms，相对 search 开始） | 说明 |
|---|---|---:|
| provider 初始化 / 模型加载 | 0.6 → 960.9 | 本地 embedding worker 起模型 |
| FTS | 971.4 → 1257.2 | trigram FTS5，与扩展加载重叠 |
| sqlite-vec 扩展 ready | 961.6 → 1265.8 | 被并发的 sync 触发，落在 FTS 窗口内 |
| 查询 embedding | 1257.2 → 6160.0 | **4.90 s，冷启最大头** |
| 向量 KNN + join | 6160.0 → 6435.8 | 275.8 ms |
| 合并 | 6435.8 → 6437.8 | 2 ms |
| **合计** | | **6,437.8 ms** |

维护前同一查询的冷启样本是 6.9–8.8 s（3 次，load 2.3–2.6），其中
FTS 0.04–1.12 s、向量 0.74–3.77 s、embedding 3.9–4.1 s、provider init
1.8–2.0 s。VACUUM + 补丁把 FTS/向量的冷页成本压下去了，但 **首次 embedding
仍然要 3–5 s**，所以冷启总时长只从 ~8 s 降到 ~5 s，且随负载波动。

真实 gateway（不是独立 Node）的两次 `memory_search` 也一致：

| 次 | managerMs | searchMs | toolMs |
|---|---:|---:|---:|
| 重启后第一次 | 1,658 | 6,595 | 8,661 |
| 同一 gateway 第二次 | 1 | 499 | 842 |

## 质量：5 个固定中文查询

| 查询 | 维护前 top-1 | VACUUM 后 top-1 | 补丁后 top-1 |
|---|---|---|---|
| 昨天美股为什么跌 | `memory/2026-07-10-pre-open.md:29` | 同左 | 同左 |
| 记忆索引 SQLite 压缩 | `memory/2026-07-27-pre-open.md:160` | 同左 | 同左 |
| dsh 任务派发 | `memory/2026-07-27-pre-open.md:160` | 同左 | 同左 |
| 港股开盘报告 | `memory/2026-09-15-0908.md:280` | 同左 | 同左 |
| quant regime | `memory/2026-07-27-pre-open.md:160` | 同左 | 同左 |

不止 top-1：三个状态下每个查询的完整 top-10 `path:startLine:score` 签名
逐字符相同（score 到 6 位小数）。KNN 是精确扫描，oversample 只是多取了
永远不会被 `LIMIT 40` 用到的行；`VACUUM` 不改变行内容。因此这两项都**不改质量**。

## 优化项 / 改动量 / 前后 / 质量

| 优化项 | 改动量 | 召回耗时前后 | 召回质量 |
|---|---|---|---|
| 离线 `wal_checkpoint(TRUNCATE)` + `auto_vacuum=INCREMENTAL` + `VACUUM` | 新增 `ops/host/sqlite_maintenance.py`（约 400 行）+ 季度 job | 热 347.7 → 139.9 ms；KNN 242.6 → 39.1 ms；主库 −28.5 MiB | 不变 |
| KNN oversample `VECTOR_KNN_OVERSAMPLE_FACTOR` 8 → 1 | dist 一行常量 + 一个 patch 脚本（约 45 行） | 热 139.9 → 119.5 ms；KNN 39.1 → 24.9 ms | 不变 |
| 状态库 `wal_checkpoint(TRUNCATE)` | 同上脚本内 | WAL 4.1 MB → 0；库大小不变 | 不变 |
| `PRAGMA cache_size` / `mmap_size` | 未做 | VACUUM 后 KNN 已 25 ms，收益不足以再背一个 dist 补丁 | — |
| FTS 粗筛后再向量精排 | 未做 | 估计热路径省 30 ms 左右；需要改 merge 语义 | **会变**（纯向量命中可能被 FTS 漏掉） |
| FTS 与查询 embedding 并行 | 未做 | 估计热路径省 30–60 ms、冷启省 0.3 s；要重构 search 的错误/fallback 顺序 | 不变（若实现正确） |
| embedding 线程 1 → 2/4 | 不做 | 可能降低冷启 embedding，但本机有 node-llama-cpp 多线程死锁前科（2026-07-08 根因） | 模型不变，但运行稳定性风险 |
| 换小模型 / 降维 / 引入向量服务 | 不做 | 会显著降低 embedding 成本 | **会变**，且违反本任务约束 |

### 最小代价的一刀

如果只允许改一行代码：把 `VECTOR_KNN_OVERSAMPLE_FACTOR` 从 8 改成 1。
`searchVector` 在模型过滤后不足 `limit` 时本来就会把 k 扩到
`MAX_VECTOR_KNN_K`，所以 8 倍只是多算；本机单模型索引上 k=40 与 k=320 的
top-10 完全相同。若只允许做一次运维：离线 `VACUUM`，它解决了更大的页跳读问题。
两者叠加才是 347.7 → 119.5 ms。

## 明确不做的

- 不引入 Elasticsearch、Qdrant、Milvus 或任何需要常驻服务/大内存的组件：
  本机总内存 1.9 GB，当前 gateway ~250 MB，swap 已用 1.8 GB。
- 不降 768 维、不换 embedding 模型、不改 `threads: 1` 的死锁规避。
- 不用 `journal_size_limit` 冒充持久修复：它是连接级设置，重连读回 -1；
  它也不能阻止长读事务挡住 checkpoint。
- 不做“FTS 粗筛 + 向量精排”这种会改变召回集合的优化，除非 kcn 明确接受质量变化。

## 复现

```bash
cd /root/.openclaw/workspace
python3 ops/host/sqlite_maintenance.py --check
python3 ops/host/sqlite_maintenance.py --apply      # 需要停 gateway
```

性能测量用的是一次性 Node 包装脚本（直接 import 已安装的
`MemoryIndexManager` 并包住上述方法），因为它依赖 OpenClaw 2026.7.1-2 的内部
dist 文件名，没有作为仓库工具提交；测量方法、查询集、轮次和原始中位数都在本文。
重跑时请先记录 `/proc/loadavg`，并在同一负载窗口内做前后对比。

# Patrol 覆盖与聊天版式

沿用 #2425 的 findings 链接、#2440 的单组历史折叠与 #2482 的八轮宿主上限。
在原 patrol 分节头下面加一个只读「巡检覆盖」展开区，不另建入口、不改五轨任务行。
默认收起，原来的最近轮次仍可扫描；展开后每个 lens 一张记录卡、每个 area 一张问题归属卡。
名字链接到相应 GitHub open patrol issues。Apple/Emil 的层级与排版原则用于字阶、留白、
固定宽度数字、触屏链接热区与现有主题材质；没有新增动画，遵守 animate 的频率与功能判据。
读数每十五秒可能更新，不为装饰移动数据；原 reduced-motion 规则保留。

## 真实数据与边界

- `taskqueue.ts` 是唯一宿主供给入口。独立统计全部可读 `rounds.tsv` 有效记录，并仅向原历史
  提供最新八条。来源超过 8 MiB 时拒读，显示未知，不截取尾部后声称全量。
- 轮次只有时间、编号、lens、任务 id、结果、耗时。统计的是记录/尝试，包含失败、中断，
  也可能有同编号的多条记录；不等于成功轮次、代码覆盖率或一轮完整循环。
  最近状态、发现列表与距今时间复用 `roundRow` 及既有日期/结果文案规则。
- 范围从首条可读记录起算。损坏记录单独提示；缺失与未记录分别表达，缺失不会成为 0。
  已安装 `axes.tsv` 是 lens 清单；`labels-known.json` 是 area 清单。清单缺失也提示，
  历史/标签里实测到的名称仍可显示，不宣称清单完整。
- Open issue 数来自 `gh issue list --label patrol --state open --json labels`；只读，
  内存缓存最多五分钟，快照时间可见。查询失败、形状错误或达到 1000 条上限时数值未知。
  队列写操作仍只走原 ops 入口；巡检目录没有任何新状态。
- **area↔lens 没有可靠的历史映射。** supervisor 按 axis 派发；`round-prompt.md` 与 `ledger.md`
  都覆盖写入当前轮资料。`area:*` 是 filing gate 给发现的问题定归属，`lens:*` 是巡检视角。
  同一 lens 可发现不同 area 的问题，有问题不证明查过整个 area、没有问题也不证明没查。
  因此 area 仅显示 open 数，巡检轮次/时间/结论在区块说明中明确为未知。

## 界面实拍

390px、WebKit/iPhone 13、light、reduced-motion 的真实分支 client bundle，借生产只读页面
预览。仅 taskQueue 响应替换为新宿主 reader 在本机真实读得的同一快照；余额仍走原宿主。
生产进程没有重启，浏览器没有执行队列写操作。截图隐藏背景与其余面板，未改覆盖 DOM。

2026-10-04 16:23 HKT 快照：499 条有效记录、1 条损坏记录、15 个 lens、10 个 area；
GitHub open patrol 查询同时取数。截图是这份快照，不是固定的产品数字。
DOM 实测宽 334px、scrollWidth 334px，15/10 个节点全部经过 RPC codec 并渲染；无 pageerror。
作者已亲自查看全图，所有卡片自然换行，未截断名称或结果。英文来自生产页面语言设置，
中文与英文文案均通过同一 translate 路径。

![Patrol 真实来源覆盖展开区](progress.png)

## 微信 Markdown 链路证据与未完成项

`text.ts` 用 H1/H2/H3、额度标签粗体与平铺列表；不使用表格、嵌套列表、HTML，也不依赖
等宽字体。provider/队列/最近结束/patrol/ops 块按原 view model 顺序与原词表达。
动态文字转义、换行压平，防止任务名称变成额外 Markdown 结构。
聊天只给覆盖摘要，不把所有卡片塞进一条消息。

实际安装的微信通道 `channel.ts` 的 `sendWeixinOutbound` 对正文运行
`StreamingMarkdownFilter.feed()` + `flush()`。该 filter 保留 H1–H4、粗体、行内代码，
剥除 H5/H6 与部分不支持的语法。已用新 `dispatchListText()` 的真实 1509 字输出运行
**这份实际安装的 filter**，输出与输入逐字相同；证据为 [通道 filter 输出](wechat-filter-output.md)。
示例的余额/队列/时间来自截图时的真实宿主快照，会继续变化。

**没有微信手机客户端访问能力，未取得实体微信实际渲染截图，也未发送额外测试消息。**
这里的文本是通道过滤链路证据，不冒充手机渲染证据。此验收项仍未完成。

生产 dsh 与 OpenClaw gateway 的 host 半边不会因无重启安装而自动加载新代码。
按照本机不重启约定安装 client/host 文件，完整新覆盖数据与 `/dispatch-list` 新版式要等
获授权或自然发生的服务重启。本任务不额外重启正在承载任务的服务。

## 验证

51 个插件 spec（含全历史/八轮分离、损坏/缺失数据、area 不推断、真实 RPC schema 保留字段、
聊天与面板信息契约及 Markdown 平铺结构）、13 个 README parity 检查通过。
生成 lib 随源重建；全仓定向外的检查交给 PR CI。合并前从最新 master rebase，重新跑相关
检查并由 CI 重跑全量。最终 PR、CI 与刷新结果见任务交付报告。

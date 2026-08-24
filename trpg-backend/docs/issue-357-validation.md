# Issue #357 PR1/PR2 连续真实模型验证

本页定义 legacy 融合 producer 与 hybrid producer（按输入门控 semantic Turn Planner）的同环境、同语料验证方式。
固定 `24/24/48` 小时观察窗口已取消，替换为一次 smoke 和连续两轮正式测试。工具不会
人为等待；仅真实请求耗时和配置的 `0.25s` transport retry 退避会占用时间。

### 当前架构决策

真实 Round 1 重跑与后续 micro benchmark 证明：统一 `ActionPlan(1..N)` 执行层是可行的，
但复杂一步行动可能因独立 Step Adjudicator 而增加一次串行模型调用。Issue #357 当前采用
“统一执行层、保留低延迟 producer”的路线：明确一步输入走 legacy fast producer 并由内部
adapter 转成 `ActionPlan(1)`；多步、多目标、顺序依赖和语义不确定输入才按稳定 rollout bucket
进入 semantic Planner。详见 `docs/issue-357-architecture-decision.md`。

因此，原性能门槛仍然是报告门槛，不会因为保留 fast producer 而被修改；当前决策也不等于
PR3 已获准执行。`SingleActionDecision` 暂作为内部过渡 adapter 保留，直到新的 fast producer
contract 能直接返回统一 `ActionPlan(1)` 并完成独立回归验证。

测试通过只表示 PR1 的真实 legacy 基线和 PR2 的真实对比达到进入 PR3 的数据门槛，
不会自动合并 Draft PR、提高生产 rollout 或删除旧链路。连续测试不覆盖长时间生产流量波动，
这是取消时间灰度后明确接受并记录的剩余风险。

## 安全配置

在仓库外创建 `/Users/jiahao/.config/trpg/issue357-benchmark.env`，权限必须为 `0600`。
文件由本机测试 shell 加载，禁止提交、打印或从 GitHub Secrets 导出。至少配置：

```bash
HOST_MODEL_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=...
DEEPSEEK_MODEL=...
TURN_PLANNER_PROVIDER=deepseek
TURN_PLANNER_API_KEY=...
TURN_PLANNER_BASE_URL=...
TURN_PLANNER_MODEL=deepseek-chat
```

然后执行：

```bash
chmod 600 /Users/jiahao/.config/trpg/issue357-benchmark.env
cd trpg-backend
./scripts/run_issue_357_validation.sh \
  /Users/jiahao/.config/trpg/issue357-benchmark.env
```

脚本把 `TURN_PLANNER_TIMEOUT_SECONDS=5`、`TURN_PLANNER_MAX_ATTEMPTS=2` 和
`TURN_PLANNER_RETRY_BACKOFF_SECONDS=0.25` 固定在测试进程内。全局
`TURN_PLANNER_ROLLOUT_PERCENT` 保持 `0`；仅 semantic E2E 工具在进程内构造 100% 的应用，
不修改部署配置。benchmark 的 WebSocket 单次接收等待默认是 `30s`，可用
`ISSUE_357_BENCHMARK_RECEIVE_TIMEOUT_SECONDS` 覆盖；它与模型请求 timeout 分开，避免把真实
模型处理时间误报成 `BENCHMARK_TIMEOUT`。默认结果目录为 `/tmp/issue-357-validation-<timestamp>`，权限由 `umask 077`
限制。环境文件内容、单条输入、Prompt、模型正文、Keeper payload 和逐次样本均不写入报告。

即使 Planner 与 Host 目前使用相同的 DeepSeek key、endpoint 或模型，也必须在环境文件中
显式填写全部 `TURN_PLANNER_*` 字段。验证脚本不再从 `DEEPSEEK_*` 静默回退，避免把
“独立 Planner 配置”误报成独立模型结果。当前官方 endpoint 的可用模型是 `deepseek-chat`，
因此可以显式把 Planner 也锁定为 `deepseek-chat`；`deepseek/deepseek-v4-flash` 是兼容网关
模型名，不能与 `https://api.deepseek.com` 混用。

## 执行规模

Smoke 不计入正式质量指标，但计入 2500 次 transport call 总预算：

- legacy 与 semantic 各运行 40 项语料一次。
- legacy 与 hybrid 各运行三个 E2E 场景一次；hybrid 报告同时记录实际 `legacy_fast`/`semantic` 路由。
- 认证、配置、脱敏和 E2E 基础设施全部正常后才进入正式轮次。

每轮正式测试包含：

- legacy 语料 `40 x 5 = 200`。
- semantic 语料 `40 x 5 = 200`。
- legacy E2E `3 x 20 = 60`。
- hybrid E2E `3 x 20 = 60`。

Round 1 按 legacy、semantic 顺序执行；Round 2 立即反转为 semantic、legacy，不加入固定等待。
两轮合计 1040 个语料/回合执行。E2E 每回合可能有 Planner、Step Adjudicator、Narrator 等
多次调用，因此实际 transport call 数更高；累计超过 2500 时工具中止。

40 项玩家安全语料覆盖确定性行动、复杂一步、对话与 Runtime 创建、2..N 多目标、同行前置、
pending、Narrator、多语言、标点和模糊指代。E2E 固定覆盖 `real_observation`、
`real_investigation`、`real_multi_step`。两类 producer 使用同一 `PlayerView`；legacy 通过
`PromptHostTurnDecisionModel`，hybrid 对 semantic eligible 输入通过 `PromptTurnPlanner`（当前 prompt version 为
`trpg-turn-planner-v2`）。semantic step 必须保留玩家明确提供的公开名称、别名和动作限定，
但不得输出目标 ID、Keeper-only 名称或裁决信息。

## 报告与门槛

每轮生成四份脱敏聚合输入、一份比较 JSON 和一份比较 Markdown；两轮完成后再生成最终
汇总 JSON/Markdown。比较器先检查 revision、样本量及 Host/Planner provider/model 是否兼容，
再逐轮独立判定：

- `real_investigation` P95 增量同时不超过 `1500ms` 和 `25%`。
- hybrid 一步场景总体 P95 不超过 `6500ms`。
- semantic Planner 和 hybrid E2E terminal failure rate 分别不超过 `2%`。
- semantic `multi` cohort 的 step-count 与 kind 顺序准确率分别至少 `95%`。
- semantic Planner 经一次结构重试后的结构成功率至少 `99%`。
- semantic 与 legacy 在双方都经过当前 Step Adjudicator 的共同步骤（多步计划从第二步开始）上，
  deterministic/rule-first 命中率相对下降不超过 5 个百分点；报告仍保留全步骤速率作为诊断，
  但不再把 legacy producer 的首步预冻结路径与 semantic 当前步骤直接相减。
- smoke 加两轮的累计 transport calls 不超过 `2500`。

报告同时包含 P50/P95/P99、首轮结构成功率、transport/structured retry、场景 step-count 及其
分布、Step Adjudicator 的 `deterministic/rule_first/model/repair` 路径计数、模型调用数、
input/output token、failure stage、terminal event 和 Narrator 重试信息。只有显式提供可验证的 input/output 单价时才计算货币成本；
默认标记为 unavailable，不推测价格。

任何一轮 no-go 时脚本以非零状态退出，Draft PR 保持 Draft，PR3 继续阻塞。修改代码、Prompt
或配置后，必须从 smoke 开始重新运行完整两轮；旧的脱敏失败报告作为证据保留。两轮都通过时，
只把 PR1 标记为“真实 legacy 基线完成”、PR2 标记为“连续真实模型对比完成”，随后另行拟定 PR3。

## 单独运行工具

语料 runner 对两类 producer 使用相同入口：

```bash
uv run python tests/benchmarks/issue_357_planner.py \
  --producer legacy --repetitions 5 --output /tmp/legacy-corpus.json
uv run python tests/benchmarks/issue_357_planner.py \
  --producer semantic --repetitions 5 --output /tmp/semantic-corpus.json
```

E2E runner 仍显式触发，默认测试不会产生模型费用：

```bash
ISSUE_356_BENCHMARK_MODE=real ISSUE_356_BENCHMARK_REPEATS=20 \
ISSUE_356_BENCHMARK_OUTPUT=/tmp/legacy-e2e.json \
uv run pytest -s tests/benchmarks/issue_356_turn_run.py

ISSUE_357_TURN_BENCHMARK_REPEATS=20 \
ISSUE_357_TURN_BENCHMARK_OUTPUT=/tmp/semantic-e2e.json \
uv run pytest -s tests/benchmarks/issue_357_turn_run.py
```

`tests/benchmarks/issue_357_compare.py` 的 `round` 子命令读取四份聚合报告并以退出码表示
go/no-go；`summary` 子命令要求两轮分别通过，不计算合并平均值。只有这些脱敏聚合结果、
实际命令、revision、机器、provider/model、配置摘要和结论可以提交到 Draft PR #403。

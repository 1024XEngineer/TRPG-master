# Issue #357 验证说明

本页定义 hybrid producer（按输入门控 semantic Turn Planner）的当前验收方式，并说明仓库中
历史真实模型报告的用途。

### 当前架构决策

真实 Round 1 重跑与后续 micro benchmark 证明：统一 `ActionPlan(1..N)` 执行层是可行的，
但复杂一步行动可能因独立 Step Adjudicator 而增加一次串行模型调用。Issue #357 当前采用
“统一执行层、保留低延迟 producer”的路线：明确一步输入走 legacy fast producer 并由内部
adapter 转成 `ActionPlan(1)`；多步、多目标、顺序依赖和语义不确定输入才按稳定 rollout bucket
进入 semantic Planner。详见 `docs/issue-357-architecture-decision.md`。

纯 semantic 方案的性能门槛没有被降低。该方案已经在有效 Round 1 重跑中得到 `NO-GO`，结果
保留在 `docs/issue-357-validation-results.md`。hybrid 方案不再以 Round 1/2 作为合并门槛，也
不进入原 PR3。`SingleActionDecision` 暂作为内部过渡 adapter 保留，直到未来有等价的
`FastSingleStepProducer -> ActionPlan(1)` contract 和独立架构评审。

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

真实模型 smoke 必须显式执行，默认测试不会产生费用。当前 smoke 使用下方“单独运行工具”中
的 `repetitions=1` 命令。`scripts/run_issue_357_validation.sh` 是纯 semantic 方案的历史完整
Round runner，不用于当前 hybrid 验收。

测试进程使用独立 Planner timeout/retry 配置，不修改部署 rollout。结果写入仓库外的临时目录。
环境文件内容、单条输入、Prompt、模型正文、Keeper payload 和逐次样本均不写入报告。

即使 Planner 与 Host 目前使用相同的 DeepSeek key、endpoint 或模型，也必须在环境文件中
显式填写全部 `TURN_PLANNER_*` 字段。验证脚本不再从 `DEEPSEEK_*` 静默回退，避免把
“独立 Planner 配置”误报成独立模型结果。当前官方 endpoint 的可用模型是 `deepseek-chat`，
因此可以显式把 Planner 也锁定为 `deepseek-chat`；`deepseek/deepseek-v4-flash` 是兼容网关
模型名，不能与 `https://api.deepseek.com` 混用。

## 当前验收

当前 hybrid 方案的验收由以下证据组成：

- Framework 与 Backend 自动化测试；
- route classifier、稳定 rollout bucket、adapter 和比较器的定向回归；
- WebSocket/ActionPlan 恢复、取消、幂等、Narrator 和进度语义回归；
- 一次显式真实模型 smoke：legacy/semantic 各 40 项语料一次，legacy/hybrid 各三个 E2E 场景一次；
- hybrid E2E 报告中的实际 `legacy_fast`/`semantic` 路由及 Step Adjudicator 路径符合架构决策；
- smoke 不出现 terminal provider/structured failure，报告不包含敏感正文。

已完成的 hybrid smoke 结果记录在 `docs/issue-357-validation-results.md`。不再运行连续 Round 1/2，
因为两轮协议原本用于判断“所有输入切到 semantic 并删除旧 producer”是否可行，而 hybrid 决策
已经撤销了这个目标。

40 项玩家安全语料仍覆盖确定性行动、复杂一步、对话与 Runtime 创建、2..N 多目标、同行前置、
pending、Narrator、多语言、标点和模糊指代。E2E 固定覆盖 `real_observation`、
`real_investigation`、`real_multi_step`。

## 历史报告

`issue-357-validation-round-1/` 和 `issue-357-validation-round-1-rerun/` 是纯 semantic 全量替换
方案的历史验证证据。它们证明结构正确性达标，但一步复杂行动的额外串行裁决调用使延迟超过
门槛，因此促成 hybrid 决策。仓库保留 runner 和脱敏聚合报告以便复现和审计，但不要求再次
执行；这些报告仅用于记录当时的架构取舍。

## 单独运行工具

语料 smoke 对两类 producer 使用相同入口，各执行一次：

```bash
uv run python tests/benchmarks/issue_357_planner.py \
  --producer legacy --repetitions 1 --output /tmp/legacy-corpus.json
uv run python tests/benchmarks/issue_357_planner.py \
  --producer semantic --repetitions 1 --output /tmp/semantic-corpus.json
```

E2E runner 仍显式触发，默认测试不会产生模型费用：

```bash
ISSUE_356_BENCHMARK_MODE=real ISSUE_356_BENCHMARK_REPEATS=1 \
ISSUE_356_BENCHMARK_OUTPUT=/tmp/legacy-e2e.json \
uv run pytest -s tests/benchmarks/issue_356_turn_run.py

ISSUE_357_TURN_BENCHMARK_REPEATS=1 \
ISSUE_357_TURN_BENCHMARK_OUTPUT=/tmp/hybrid-e2e.json \
uv run pytest -s tests/benchmarks/issue_357_turn_run.py
```

`tests/benchmarks/issue_357_compare.py` 的 `round`/`summary` 子命令继续用于复现历史实验，不是
hybrid PR 的现行合并门槛。只有脱敏聚合结果、实际命令、revision、机器、provider/model、
配置摘要和结论可以提交；不得提交任何逐次样本或模型正文。

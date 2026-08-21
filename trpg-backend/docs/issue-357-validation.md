# Issue #357 验证与发布门槛

本页定义 semantic Turn Planner 的可重复、脱敏验证方式。工具不会保存 Prompt、玩家原文、
模型输出、Keeper payload 或凭证；真实 provider 调用只由显式命令触发。

## Planner 语料 benchmark

先在 `trpg-backend` 配置独立 Planner 环境变量：

```bash
export TURN_PLANNER_PROVIDER=deepseek
export TURN_PLANNER_API_KEY='...'
export TURN_PLANNER_BASE_URL='https://api.qnaigc.com/v1'
export TURN_PLANNER_MODEL='deepseek/deepseek-v4-flash'
export TURN_PLANNER_TIMEOUT_SECONDS=5
export TURN_PLANNER_MAX_ATTEMPTS=2
export TURN_PLANNER_RETRY_BACKOFF_SECONDS=0.25
uv run python tests/benchmarks/issue_357_planner.py \
  --repetitions 5 \
  --output /tmp/issue-357-planner.json
```

语料固定为 40 项，覆盖确定性行动、复杂一步、对话与 Runtime 创建、2..N 多目标、同行前置、
pending、Narrator、多语言、标点与模糊指代。报告包含 revision、机器、provider/model、配置摘要、
P50/P95/P99、step-count/kind 准确率、首轮结构成功率、模型调用数、token、重试与安全失败码。

端到端融合 benchmark 沿用 Issue #356 的 WebSocket 工具采集相同运行环境的 legacy 基线；
Issue #357 报告必须把 40 项语料每项重复 5 次，并对每个端到端场景至少取得 20 个成功样本。
不要提交 `/tmp` 下的逐次数据，也不要在报告中增加原始输入/输出字段。

同一环境下显式运行 semantic 端到端工具：

```bash
ISSUE_357_TURN_BENCHMARK_REPEATS=20 \
uv run pytest -s tests/benchmarks/issue_357_turn_run.py
```

该工具强制 semantic producer 为 100%，但不会改写环境或部署配置；Host Adjudicator/Narrator
继续使用当前真实配置。用相同机器、Host provider/model 和语料运行 #356 real mode，才能计算
复杂一步 P95 的绝对与相对增量。

## 硬门槛

- 复杂一步 P95 增量同时不超过 1.5 秒和 25%。
- 整体一步 P95 不超过 6.5 秒。
- terminal provider/structured failure 不超过 2%。
- 多目标召回率至少 95%。
- 结构化输出经一次重试后的成功率至少 99%。
- deterministic/rule-first 命中率较基线下降不超过 5 个百分点。

报告还必须给出 P50/P95/P99、模型调用数、input/output token 与估算成本、首轮结构成功率、
retryable failure 和各场景 step-count 准确率。任一门槛失败都不得提高 rollout。

## 灰度顺序

1. Preview 设置 `TURN_PLANNER_ROLLOUT_PERCENT=100`，完整 benchmark 通过。
2. 生产 5% 至少运行 24 小时且取得 50 个 semantic 完成回合。
3. 生产 25% 至少运行 24 小时且取得 100 个 semantic 完成回合。
4. 生产 100% 至少运行 48 小时且取得 200 个 semantic 完成回合。

路由使用 `room_id + client_action_id` 稳定哈希；同一幂等重试不会换桶。semantic 失败不在同一
回合回退 legacy。任一档失败时把比例设回 0；无需回滚 ActionPlanRun、数据库或 #356 状态机。

## PR3 门禁

只有上述发布窗口全部通过，才删除 `SingleActionDecision`、`HostTurnDecision` parser/model/
executor/adapter、`initial_adjudication` ingress、`single-action` 特判和 legacy rollout 配置。
升级前 Engine-only pending recovery adapter、`ActionAdjudication`、`SingleAdjudicationExecutor`、
`ActionPlanRun` 与 Engine 单步提交能力继续保留。

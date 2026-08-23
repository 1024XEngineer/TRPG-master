# Issue #357 连续真实模型验证结果

## 测试环境

- 测试 revision：`d6bd38aa68949cb5882d0ff09253ea12bc8309ae`
- 运行机器：本机 macOS；Python、架构和 provider 配置均由脱敏报告记录
- Host provider/model：`deepseek` / `deepseek-chat`
- Planner provider/model：`deepseek` / `deepseek-chat`
- Planner timeout：`5s`
- Planner max attempts：`2`
- Planner retry backoff：`0.25s`
- 货币成本：不可用；报告只记录 token 总量

本次使用官方 endpoint `https://api.deepseek.com`。该 endpoint 支持
`deepseek-chat`；`deepseek/deepseek-v4-flash` 是兼容网关模型名，不能与该官方 endpoint
混用。Planner 仍使用独立 client 和独立配置，只复用同一 endpoint/key/model。

## Smoke

Smoke 四条路径均通过，transport calls 为 `97 / 2500`：

- legacy corpus：`40 x 1`，失败率 `0%`
- semantic corpus：`40 x 1`，失败率 `0%`
- legacy E2E：`3 x 1`，失败率 `0%`
- semantic E2E：`3 x 1`，失败率 `0%`

## Round 1

Round 1 完整执行了 legacy/semantic 各 `40 x 5` 语料和各 `3 x 20` E2E，共 520 个正式样本。
比较器结果为 **NO-GO**，因此按协议没有启动 Round 2。

通过项：

- Planner terminal failure rate：`0%`，门槛 `<=2%`
- multi step-count accuracy：`100%`，门槛 `>=95%`
- multi kind-sequence accuracy：`100%`，门槛 `>=95%`
- 一次结构重试后的结构成功率：`100%`，门槛 `>=99%`
- 复杂一步 P95 增量：`1320.257ms` 且 `20.06%`，门槛分别为 `1500ms` 和 `25%`
- cumulative transport calls：`849 / 2500`

未通过项：

- semantic 一步总体 P95：`7577.760ms`，超过 `6500ms`
- semantic E2E terminal failure rate：`5%`，超过 `2%`
- deterministic/rule-first 命中率下降：`14.51` 个百分点，超过 `5` 个百分点

semantic E2E 的聚合失败分类为 `BENCHMARK_TIMEOUT` 和 `MODEL_OUTPUT_UNREADABLE`；legacy E2E
也出现少量 benchmark timeout/narrator failure。Planner 语料本身没有 terminal failure，且多目标
step count/kind 顺序全部正确。

## 后续状态

- Round 2：未执行。根据协议，任一轮失败必须先定位问题，不能用第二轮平均值掩盖 Round 1。
- PR3：不具备数据门槛，不删除旧 producer 或 `SingleActionDecision`。
- Draft PR #403：保持 Draft；后续若修复模型配置、Prompt 或 benchmark 基础设施，必须从 smoke
  和两轮正式测试全部重跑，旧失败报告保留为证据。

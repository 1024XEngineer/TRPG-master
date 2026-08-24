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

## Round 1 重跑

上一轮结果和报告保持不变，作为历史失败证据保留在
`issue-357-validation-round-1/`。针对上一轮的后台任务/锁竞争和配置问题修复后，使用同一语料、
同一 E2E 场景和同一 provider/model 在 revision `aca238b48441de688ced4d57545f61d57374e71e`
重新从 smoke 开始执行。重跑报告位于 `issue-357-validation-round-1-rerun/`，smoke 比较报告为
`issue-357-validation-smoke-rerun.json` 与 `issue-357-validation-smoke-rerun.md`。

- Smoke：四条路径均通过，`95 / 2500` transport calls。
- Round 1：520 个正式样本，legacy/semantic corpus 各 200，legacy/semantic E2E 各 60；
  `1288 / 2500` cumulative transport calls。
- Planner terminal failure rate：`0%`；semantic E2E terminal failure rate：`0%`。
- 多目标 step-count 与 kind 顺序准确率均为 `100%`；结构化输出经重试后的成功率为 `100%`。
- semantic 一步 P95：`7860.309ms`，超过 `6500ms`；复杂一步 P95 相对 legacy 增量为
  `2203.02ms / 36.9821%`，超过 `1500ms / 25%`。
- Round 1 重跑仍为 **NO-GO**，因此没有执行 Round 2，也没有进入 PR3。

重跑显示主要瓶颈是一步复杂行动的额外裁决调用：semantic 的
`real_investigation` 在 `20/20` 个回合进入 Step Adjudicator 的 model 路径，而 legacy 首步的
旧 producer 调用已经包含同等裁决；semantic Step Adjudicator P95 约 `2383ms`。Planner 自身
P95 约 `1132ms`，并非主要失败来源。该差异说明当前语义 Planner 到当前步骤策略之间仍缺少
足够的确定性/rule-first 覆盖，不能据此删除旧 producer contract。

## 后续状态

- Round 2：未执行。根据协议，任一轮失败必须先定位问题，不能用第二轮平均值掩盖 Round 1。
- PR3：不具备数据门槛，不删除旧 producer 或 `SingleActionDecision`。
- Draft PR #403：保持 Draft；后续若修复模型配置、Prompt 或 benchmark 基础设施，必须从 smoke
  和两轮正式测试全部重跑，旧失败报告保留为证据。

## 架构决策更新

基于上述失败证据和 2026-08-24 的诊断 micro benchmark，Issue #357 改采用“统一执行层、保留低延迟 producer”的路线。

- `ActionPlan(1..N)`、`ActionPlanRun`、Engine 单步边界、恢复/取消/幂等和 Narrator 状态机继续统一；
- 明确的一步输入继续走 legacy fast producer，并由现有内部 adapter 转成 `ActionPlan(1)`；
- 多步、多目标、顺序依赖和语义不确定输入进入 semantic Planner；
- `real_investigation` 的 `target_missing` 仍由当前 Step Adjudicator 裁决，不能伪造 deterministic 成功；
- 原性能门槛没有降低，旧 NO-GO 结果仍然有效；
- `SingleActionDecision` 暂作为内部过渡 adapter 保留，PR3 不启动。

完整决策、路由安全边界和剩余风险见 `docs/issue-357-architecture-decision.md`。

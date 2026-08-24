# Issue #357 架构决策记录：统一执行层，保留低延迟 Producer

## 决策

Issue #357 不再把“统一 `ActionPlan(1..N)` 执行模型”和“所有输入都必须经过纯语义 Planner”视为同一个目标。
采用混合 producer 路由：明确、低歧义的一步行动继续使用 legacy fast producer；多步、多目标、顺序依赖和语义不确定输入才进入 semantic Planner。

两类 producer 的输出最终都进入同一条执行链路：

```text
PlayerInput
  -> fast producer 或 semantic Planner
  -> ActionPlan(1..N)
  -> bounded prerequisite resolution（semantic route）
  -> ActionPlanRun
  -> current-step policy/adjudicator
  -> Engine
  -> Narrator
```

现有 `HostTurnDecisionExecutor` 已把 legacy `SingleActionDecision` 适配成 `ActionPlan(1)`，因此 legacy fast producer 不再拥有独立的运行、恢复、取消、幂等或 Engine 路径。

## 背景与证据

上一轮真实 Round 1 重跑显示 semantic 一步复杂行动的 P95 为 `7860.309ms`，相比 legacy 的增量为 `2203.02ms / 36.9821%`，超过原定 `1500ms / 25%` 门槛。随后 micro benchmark 在有效 Chat Completions 配置下复现了路径差异：

- `real_observation`：semantic 3/3 deterministic；
- `real_multi_step`：semantic 6/6 steps deterministic；
- `real_investigation`：semantic 3/3 进入 Step Adjudicator model；
- 三次 investigation 的安全 miss reason 均为 `target_missing`。

`target_missing` 表示目标不在当前玩家安全可见投影中，不是可以安全扩展为 deterministic 成功的唯一公开目标。强行绕过 Step Adjudicator 会把目标、规则、检定和效果裁决提前冻结，违反 #357 的职责边界。

因此，额外的 Step Adjudicator 调用是新架构对复杂行动的真实职责成本，而不是一个可以通过猜测目标修掉的路由 bug。保留纯语义 Planner 的同时，对明确一步行动使用 fast producer，可以避免所有简单回合无条件支付这次成本。

## 路由规则

路由门只读取玩家输入，不读取 Keeper capability、规则候选、检定、效果或隐藏 Canon。当前安全分类为：

- 多步标记（例如“先/然后/接着/随后”） -> semantic；
- 多目标标记（例如“分别/每个/所有/多个/和/以及”） -> semantic；
- 语义不确定标记（例如“仔细/调查/搜索/搜查/查找/研究/线索/眼前的人”） -> semantic；
- 其他明确一步输入 -> legacy fast producer。

semantic rollout percentage 仍作为稳定 canary bucket；它只控制“已被安全分类为 semantic”的输入，不会把明确一步输入强行改道。相同 `room_id + client_action_id` 的幂等重试仍保持同一路由。

这是一个保守的 producer 选择，不是对目标或规则的裁决。当前步骤的最新 `PlayerView`、revision 校验、Step Adjudicator 和 Engine 拒绝机制继续保持权威。

## 保留与删除范围

保留：

- `ActionPlan(1..N)`、`ActionPlanRun`、统一恢复/修复/取消/幂等；
- Engine 单步提交边界和 Narrator 状态机；
- `PromptTurnPlanner`、`TurnPlanningContext`、`PlanPrerequisiteResolver`；
- legacy fast producer 的内部适配器，直到新的 fast producer contract 能直接返回统一 `ActionPlan(1)`。

本决策下暂不执行 PR3 的旧 contract 删除。`SingleActionDecision` 目前是内部过渡适配器，不是恢复第二条执行链的理由。后续若删除它，必须先实现等价的 `FastSingleStepProducer -> ActionPlan(1)` contract，并重新验证简单一步延迟和行为回归。

## 影响与剩余风险

简单明确的一步行动保留低延迟；复杂行动仍可能比旧融合 producer 多一次串行模型调用，这是职责拆分带来的可见成本。当前不声称原性能门槛已经通过，也不通过修改比较器或降低门槛来制造 GO。

后续性能优化只能在不扩大 Planner 权限的前提下进行，例如更快的模型、连接复用、输入压缩和 transport 调优。任何改变 Planner 可见信息或让 Planner 生成裁决的方案，都必须另开架构评审。


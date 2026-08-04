# Rule Engine v3：单意图权威裁决

本文落实 Issue #212 的 B 侧边界。Host / Keeper Agent 仍负责理解自然语言并产出
`ActionAdjudication`；Rule Engine 不读取玩家原话、不匹配 Checkpoint Route，也不拆解或
续跑复合行动。

## 命令状态机

```text
ActionAdjudication(check.mode=none)
  -> effects + action.succeeded

ActionAdjudication(check.mode=required|player_choice)
  -> PendingCheckDecision(awaiting_skill_choice)
  -> select -> server roll -> CheckRun
       -> success: effects + check.resolved + action.succeeded
       -> failure: awaiting_post_roll_decision
            -> accept: failure effects + action.failed
            -> exact luck spend: resource + success effects + action.succeeded
            -> one push: server reroll + final effects + action result
  -> cancel before first roll -> action.cancelled
```

每一个箭头都是独立命令，携带自己的 `request_id` 和当前 `source_revision`。命令结果、
Pending 决策、骰点和 Event 在同一数据库事务中提交。相同 `request_id` 与相同请求返回
首次结果；重用 id 提交不同内容、过期 revision、过期 decision/check version 均拒绝。

## 校验边界

- 候选集合整体校验：candidate id 唯一、skill id 必须出现在 Actor 的 Ruleset 快照、
  数值和 difficulty 合法；任一项非法即拒绝整份裁决，不静默过滤或重新排序。
- 首次骰点由服务端密码学随机源生成并立即持久化。客户端只能提交 candidate id、
  cancel 或已有的 post-roll option id，不能提交骰点、技能、难度、效果或资源花费。
- 幸运花费由 Ruleset 状态计算为精确数值，与资源扣除、结果转换和效果一起提交。
- 强推必须引用既有 CheckRun 并携带经 Agent 整理的新方法；每个 CheckRun 最多两次骰点。
- `ActionAdjudication` 只能携带已注册的高层效果；没有任意 JSON Patch 或状态路径入口。
- Canon Information、Entity、Location 和 Ending 引用必须存在。Runtime 内容不得 shadow
  Canon id，并记录 `agent_adjudication` provenance。

## Event 与副作用

`check.choice_requested` 和 `check.rolled` 只负责恢复 UI、审计和幂等，不应用成功/失败
效果。最终收束才写 `check.resolved`、领域 Event 及 `action.succeeded/action.failed`。
取消写 `action.cancelled`，不写 `action.failed`，不掷骰，默认不推进时间。

`ModuleContent.event_rules` 只匹配最终领域 Event；发布契约直接拒绝监听
`check.choice_requested/check.rolled/check.post_roll_option_selected` 的规则。命中规则按
`priority DESC, id ASC` 稳定排序，仍然只能产生注册的高层效果，并受单次 100 Event
上限保护，避免循环规则无限执行。

首期执行器支持 #212 冻结的高层效果：Information 显隐、Location 进入和 Runtime
创建、Runtime Entity 创建/移动/状态变化/消耗、时间推进、CoreResolution、Ending 可用性
和终局确认，以及无状态的 `narrative_only`。这些效果都转换为具名领域 Event；Narrator
只能使用提交后的 Event 引用。

## 持久化

除现有 `game_sessions/game_events/action_executions` 外，v3 增加：

| 表 | 权威内容 |
|---|---|
| `pending_check_decisions` | 完整冻结的 ActionAdjudication、玩家安全候选、状态和 version |
| `check_runs` | 首次/强推骰点、合法 post-roll options、最终结果和 version |
| `adjudication_command_executions` | submit/select/cancel/luck/push 的请求与首次结果 |

三张表都以 Room 为作用域。每个工作流 Event 同时推进 `GameState.event_sequence`，因此
断线重连后的 PlayerView revision 与待处理 UI 一致，不会复用创建决策之前的视图。

## 前端投影协议

前端只消费 `PendingCheckDecisionView`、`CheckRunView` 和 `AdjudicationExecution`：

- `awaiting_skill_choice`：显示方法摘要、玩家安全理由、技能显示名、难度和取消按钮；
- `awaiting_post_roll_decision`：显示服务端骰点以及 Engine 返回的接受、精确幸运或强推；
- `resolved/cancelled`：使用最终 Event 与新 revision 刷新 PlayerView。

仓库内的 `trpg-frontend/src/features/adjudication/CheckWorkflowPanel.tsx` 已按这三个安全
投影实现展示，并使用模拟 Engine 输出覆盖选择、取消、精确幸运和强推输入；在 A 侧尚未
产出 `ActionAdjudication` 前，它不会接管现有 v2 房间回合。

当前生产 Host 仍输出 ModuleContent v2 `Intent`，本变更不修改 Agent 或把 v2 Intent
偷偷转换成 v3 语义。后续 A 侧接入只需提交上述公共契约；数据库状态机和前端安全投影
不需要重新设计。v2 `RuleEngineService.execute(ActionRequest)` 在迁移期继续可用。

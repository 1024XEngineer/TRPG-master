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

## 高层效果的端到端闭环

引擎从一开始就实现并校验了 #212 冻结的全部高层效果，但只有 `enter_location` 和
`narrative_only` 真的能被用上：其余效果要么 Agent 没有可用的词汇（不知道尚未发现的
Canon Information id、不在场的 Entity id、Ending id），要么提交之后没有任何投影会变，
玩家和 Agent 的下一步都观察不到。现在两端都补齐：

### Agent 侧：`KeeperCapabilityView`

`RuleEngineService.read_keeper_capabilities(scope)` 与 `read(scope)` 用同一份 runtime
快照，产出受控的 Keeper 词汇表：全部 Canon Information（含 `known_by_party/known_by_actor`）、
Canon 与 Runtime 的 Location/Entity 当前位置、可提交的 Ending id、`core_resolved` 与
`ending_available`。

边界：

- 只进入 planner（单动作）与步骤裁决两处模型调用，通过
  `HostAgentContext.keeper_capabilities` 与 `ActionPlanStepContext.keeper_capabilities`；
- 不进入 `ActionPlanNarrationContext`——Narrator 仍然只能引用已提交的 evidence；
- 不出现在任何发往客户端的 payload 里；
- 与配套 PlayerView 必须同 revision，两者由 schema 校验强制配对；
- 它只是词汇表，不是授权：Engine 在 submit 时用同一份快照重新校验每一个 id。

### 投影侧：效果必须可观察

`ProjectionSnapshot` / `PlayerView` 增加 `world` 块（`elapsed_minutes`、`time_of_day`、
`core_resolved`、`ending_available`、`ending_id`），并补上这些投影：

| 效果 | 之前 | 现在 |
|---|---|---|
| `reveal_information` / `hide_information` | 已投影 | 不变 |
| `set_visibility` | 只写 `GameState`，无人读取 | Entity/Location/Information 投影按 actor 优先于 party 应用；party 作用域的 key 不再按行动者分片 |
| `ensure_runtime_entity` / `move_entity` / `consume_entity` | 不投影 | Runtime NPC 进入 `scene.visible_entities`；Runtime object 成为 `ItemInstance`，按 custody 进入 `scene.loose_items` 或 `inventory`，消费后退出两者 |
| `ensure_runtime_location` | 不投影，且 `enter_location` 进去会让投影直接抛 `当前 Scene 不存在` | 作为出口出现在连接它的场景里，可以进入；进入后只保留回到连接点的出口 |
| `advance_time` | 只有 `time_of_day` 间接可见 | `world.elapsed_minutes` + `world.time_of_day` |
| `mark_core_resolved` / `set_ending_availability` | 不投影 | `world.core_resolved` / `world.ending_available` |

`commit_terminal_ending` 已从可执行裁决边界移除；`world.ending_id` 只由同 revision
`EndingDraft` 的显式确认产生。

前端在地图面板显示权威时钟与主线/结局状态；线索列表与场景实体沿用既有 UI，因此
`reveal_information` 与 Runtime NPC 提交后立刻可见；Runtime object 则进入场景物品或
背包列表，不再伪装成随身 `visible_entity`。

复杂规则（ModuleContent v3 `event_rules` 的完整语义）不在本次范围内。

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
投影实现展示，并使用模拟 Engine 输出覆盖选择、取消、精确幸运和强推输入。自 #225 的
ActionPlan 回合接入后，房间回合已经由它承担真实的检定交互。

房间回合走 #225 的 ActionPlan 路径，Host 直接产出 v3 `ActionAdjudication`；上面的
`KeeperCapabilityView` 与 `world` 投影补齐后，全部已注册的高层效果都能由 Agent 提出、
由 Engine 提交、并在玩家视图里被看到。v2 `RuleEngineService.execute(ActionRequest)` 在
迁移期继续可用。

## ActionPlan 编排边界（Issue #225）

复合输入现在有独立的 A 侧编排基座，但没有改变本服务的单意图职责：

```text
HostTurnDecision
  ├─ SingleActionDecision -> AdjudicationEngineService.submit() 一次
  └─ ActionPlan -> ActionPlanOrchestrator
       -> 最新 PlayerView 裁决当前 semantic step
       -> AdjudicationEngineService.submit() 一次
       -> 刷新 revision
       -> 当前步 resolved 后才可进入下一步
```

`ActionPlan` 是变长顺序数组，公共 Schema 只要求至少两步；运行时
`ActionPlanPolicy.max_plan_steps` 默认 32，`max_steps_per_advance` 默认 3。后者只是持久化
调度窗口，4/5 步计划会在 checkpoint 后续跑同一 parent action，不会截断或要求玩家重输。

`ActionPlanRunStore` 与 `EngineStore` 分层。前者保存 plan/step 游标、冻结的单步裁决、CAS
version、worker lease 和房间行动占用；后者仍只保存单个 `ActionAdjudication` 的权威命令、
检定和领域 Event。两者通过确定性的 `step_request_id` 做 Saga 对账：Engine 已提交而
PlanRun 尚未前移时，恢复会查询/重放首次结果，不重复状态效果或骰点。

当前步骤进入技能选择或检定后选择时，PlanRun 进入 `waiting_for_player`，后续步骤禁止
执行；最终成功后基于新 revision 继续，取消或最终失败则保留前序已提交事实并停止剩余
步骤。Plan 到达 `awaiting_narration` 后不再调用 Adjudicator/Engine，只有叙事成功后才标记
`completed`。

# A/B 有限 ActionPlan 的逐 revision 编排、步骤幂等与恢复

- 上位需求：[Issue #208](https://github.com/1024XEngineer/TRPG-master/issues/208)
- 复合意图先例：[Issue #149](https://github.com/1024XEngineer/TRPG-master/issues/149)
- 单步执行基座：[Issue #212](https://github.com/1024XEngineer/TRPG-master/issues/212)
- 当前实现基线：`agent/issue-212-rule-engine-v3` / `e78bdb3`

---

## 一、背景

#208 已确认，项目当前只能安全完成一个原子动作：

```text
PlayerInput
→ revision-bound PlayerView
→ Host 生成一个 Intent / ActionAdjudication
→ ActionExecutor 执行一次
→ 重新投影 PlayerView
→ Narrator
```

这条链路保住了必要的安全边界，但无法完整执行正常的复合表达：

```text
去书房找线索
到墓地问守墓人
回旅店休息，晚上再去墓地
```

#149 已把最小问题定义为“移动 + 目的地动作”：移动提交后 scene/revision 已改变，
目的地动作必须在新的 PlayerView 上重新理解；不能提前读取目的地 Entity、Information、
技能候选或隐藏内容。

#212 又冻结了 ModuleContent v3 的交接边界：Agent 可以编排多个步骤，但
`AdjudicationEngineService` 每次只能接收并执行一个 `ActionAdjudication`。当前分支已经
实现单意图 `ActionAdjudication`、步骤命令幂等、`PendingCheckDecision`、`CheckRun` 和
SQL 恢复，但尚无跨步骤的 ActionPlan 运行记录与 A 侧续跑状态机。

本 Issue 只补齐 #208 建议拆分中的第 2 项：

> A/B：有限 Action Plan、步骤幂等和恢复。

它必须能成为 #208 后续时间、Ambient 世界、Validator 修复和 Director 能力的稳定编排
底座，而不能只为“去书房找线索”写一个两步特例。

## 二、目标

实现一个项目自有、有限、顺序、可持久恢复的 `ActionPlan` 编排层，使一次玩家提交可以：

1. 由 A 判断是单一行动还是复合目标；
2. 将复合目标表达为可变数量的顺序语义步骤，不把常见产品输入锁死为 2 或 3 步；
3. 每一步都基于该步开始时最新的 revision-bound PlayerView / 受控 GMView 生成一个
   `ActionAdjudication`；
4. 每一步只提交一个 `ActionAdjudication`；需要检定时，后续选择/掷骰/检定后决定继续
   使用 #212 已冻结的单意图 check workflow；
5. 每次权威提交后重新投影视图，再决定是否继续；
6. 遇到玩家选择、pending check、失败、澄清、不可逆边界或预算耗尽时停止自动续跑；
7. 在网络重试、Host/Agent 失败、进程重启、Engine 已提交但 PlanRun 尚未更新、
   Narrator 失败等情况下，不重复任何已提交步骤；
8. 最终叙事只消费所有已提交步骤的玩家安全 evidence 和最终 PlayerView。

## 三、范围

### 包含

- `SingleAction | ActionPlan` 的 A 侧输出契约；
- 可变长度、仅顺序依赖的有限 ActionPlan；
- 可配置的计划技术上限与分段自动推进软预算；
- 每步延迟裁决、逐 revision 执行与停止条件；
- 父动作、计划和步骤的稳定 ID / fingerprint；
- `ActionPlanRun`、步骤快照、乐观并发与 SQL 恢复；
- 与 #212 `ActionAdjudication`、`PendingCheckDecision`、`CheckRun`、
  `AdjudicationExecution` 的衔接；
- 部分成功、可重试失败、需澄清和取消的收束语义；
- Narrator evidence 聚合及叙事失败恢复；
- 玩家安全的计划进度事件和断线恢复投影；
- 玩家显式取消剩余计划的幂等命令；已提交步骤不回滚；
- #149 的 Canon “移动 + 目的地动作/对话”确定性纵切；
- 为 #208 的 `travel → rest/wait → travel` 三步组合提供不依赖具体领域效果的编排能力。

### 不包含

- 时间/休息命令和自然时间解析本身（#208 建议拆分 1）；
- Ambient Scene / Ambient Fact 的创建、验证和生命周期（#208 建议拆分 3）；
- Validator 拒绝后的 Agent 自动修复循环（#208 建议拆分 4）；
- Director 停滞判断、主动剧情或 `no_op`（#208 建议拆分 5）；
- Narrator 建议的可执行性审查（#208 建议拆分 6）；
- 条件分支、循环、并行、动态追加步骤、长期任务或无限自主规划；
- 让 Engine 解释自然语言、拆分计划或自动续跑；
- 任意 JSON Patch、直接 GameState/数据库写入或新的平行权威入口。

本 Issue 完成时，ActionPlan 编排底座和 #149 Canon 纵切应可运行；但 #208 Case 1
“回旅店休息，晚上再去墓地”的完整产品验收仍需时间/休息与 Ambient 两个后续 Issue
接入同一 ActionPlan。不得以本 Issue 的完成宣称整个 #208 已完成。

## 四、冻结的设计决策

### 4.1 Engine 保持单意图，Plan 属于 A 编排层

数据流冻结为：

```text
PlayerInput
→ HostTurnDecision: SingleAction | ActionPlan

SingleAction
→ 一个 ActionAdjudication
→ AdjudicationEngineService（一次）

ActionPlan
→ 持久化 ActionPlanRun
→ 基于 revision N 裁决 step 1
→ AdjudicationEngineService（一次）
→ 重新投影 revision N+1
→ 基于 revision N+1 裁决 step 2
→ ...
→ 最终/暂停/安全停止
```

`AdjudicationEngineService` 不接收 `ActionPlan`，也不读取、拆分或续跑计划。A 依赖一个
独立 `ActionPlanRunStore` 端口；B 提供其 InMemory/SQL 实现。该 Store 可以与 Engine
使用同一数据库，但不得扩张 Engine 的单意图职责。

### 4.2 单动作快路径保持不变

Host 的顶层决策是有鉴别字段的 union：

```text
SingleActionDecision
  kind = single_action
  adjudication = ActionAdjudication

ActionPlan
  kind = action_plan
  goal
  steps[2..N]
```

单一行动直接提交一个 `ActionAdjudication`：不创建 PlanRun、不产生额外步骤级 Host
调用、不改变现有 Engine 幂等语义。

### 4.3 ActionPlan 只保存语义目标

建议公共契约：

```json
{
  "kind": "action_plan",
  "goal": "去书房找线索",
  "steps": [
    {
      "kind": "travel",
      "semanticGoal": "前往书房"
    },
    {
      "kind": "action",
      "semanticGoal": "在到达的书房寻找与委托有关的线索"
    }
  ]
}
```

约束：

- `steps.length` 至少为 2；上限不写死在公共 Schema，由运行时 `ActionPlanPolicy` 校验；
- `step.kind` 只能是 `travel | wait | rest | action | dialogue`；它只用于有限计划策略、
  进度和停止校验，不替代当前步的 `ActionAdjudication`；
- 顺序依赖由数组位置表达，不能携带图、分支、循环或并行依赖；
- step 只保存玩家目标的安全语义，不携带 `ActionEffect`、检定结果、State Patch、
  目的地秘密或预解析的未来 `ActionAdjudication`；
- Plan 只按玩家目标中的状态依赖边界拆步；单个 `ActionAdjudication` 可以原子提交多个
  已注册高层效果，不能因为内部有多条 Event/数据库写入就拆成多个 Plan step；
- 模型不能指定权威 `plan_id`、`step_id`、`request_id`、revision、status 或 retry count；
- 一步目标应返回 `single_action`；无法安全切分时应请求澄清，不能静默丢步骤。

步骤预算分为两层，避免把安全预算误写成产品能力上限：

```text
ActionPlanPolicy
  max_plan_steps = 32          # 可配置的绝对技术安全上限；建议默认值
  max_steps_per_advance = 3    # 一次调度窗口的软预算；建议默认值
```

- `max_plan_steps` 不是业务语义，也不进入数据库 Schema 约束；部署可以在资源评估后提高，
  无需修改公共契约或迁移。默认 32 用于限制异常模型输出、超长请求和资源滥用，正常的
  4、5 或更多步骤可以完整进入同一 Plan；
- `max_steps_per_advance` 只控制单次 worker/请求连续推进多少个已解决步骤。窗口耗尽时
  持久化 checkpoint、重新确认 revision 和 room ownership，然后由服务端继续同一 Plan；
  它不是整份计划的最大长度，也不能要求玩家重新输入剩余步骤；
- 有效软窗口可以按风险缩小：遇到检定、玩家选择、不可逆效果或高影响边界时立即变为
  1/暂停；低风险步骤也不能超过冻结的 `max_steps_per_advance`；
- 任何超过当前 `max_plan_steps` 的计划都必须返回稳定的 `PLAN_TOO_LARGE` / 澄清结果，
  明确要求玩家拆分或缩小目标；绝不截断后续步骤、只执行前 32 步或让 Narrator 假装
  剩余步骤已经发生；
- PlanRun 创建时冻结 `ActionPlanPolicy` 快照，重试或服务重建不能因配置热更新而改变同一
  父动作的步骤边界。

#149 的两步 `travel → destination action/dialogue` 作为首个真实纵切；#208 的三步
`travel → rest/wait → travel` 是后续领域能力接入的最小组合，但两者都不是 Schema 的
唯一长度。

本期的确定性 `ActionPlanPolicy` 冻结技术上限、调度窗口、step kind 白名单、顺序依赖、停止条件和
“每步必须来自玩家明确目标”约束。它不穷举每一种顺序组合，也不把 `kind` 直接映射为
状态效果；某个领域步骤能否执行仍由该步最新上下文中的 `ActionAdjudication` 与 Engine
校验决定。尚未接入的 `wait/rest` 可以被计划契约表达，但必须安全停止为 unsupported，
不能只靠 Narrator 假装时间已经推进。

### 4.4 每一步延迟生成 ActionAdjudication

初始 Plan 不能预解析后续步骤。每一步开始时，A 组装：

```text
original PlayerInput
+ 当前 step.semantic_goal
+ 当前 revision-bound PlayerView
+ 受控 GMView（如该领域裁决需要）
+ Ruleset / Actor 能力
+ 已提交步骤的玩家安全摘要与 evidence refs
```

然后只生成当前一步的 `ActionAdjudication`。应用层负责注入或核对 room、player、actor、
step request id 和 source revision；模型不能覆盖这些身份字段。

必须保证：

- step 2 看不到 step 1 提交前不可见的目的地秘密；
- step 2 只能使用 step 1 提交并重新投影后的 revision；
- 已提交步骤的 raw Agent 输出、GM-only 数据和推理不进入后续 PlayerView 或公共事件；
- future step 只有 semantic goal，不因第一轮规划而获得权威含义。

### 4.5 确定性停止条件

A 只在以下条件全部满足时自动进入下一步：

- 当前步骤已权威 `resolved`；
- 当前结果允许继续，且没有 pending 玩家选择；
- 已重新投影出与 Engine result 一致的新 revision；
- 仍有未执行步骤且没有触发冻结的绝对技术上限；
- 房间、玩家、actor 和 parent action ownership 未变化。

遇到以下任一情况立即暂停或收束：

| 条件 | Plan 行为 |
|---|---|
| `awaiting_skill_choice` / `awaiting_post_roll_decision` | `waiting_for_player`，持久化并等待同一检查工作流 |
| 玩家取消当前步骤 | `stopped`，保留此前成功步骤，不执行后续步骤 |
| 玩家在步骤间显式取消剩余 Plan | 幂等写入 `cancelled`；已提交步骤不回滚，不取消已知骰点 |
| 当前步骤失败且失败不允许继续 | `stopped`，进入部分成功/失败叙事 |
| 需要玩家澄清 | `needs_clarification`，不替玩家选择剧情方向 |
| Host/Provider 临时失败 | `retryable_failure`，同一 parent ID 从当前步骤恢复 |
| revision 冲突且当前步骤尚未提交 | 丢弃未提交裁决，基于最新视图重新裁决当前语义步骤 |
| revision 冲突但已有同 step request 的提交证据 | 重放首次结果并补记 PlanRun，不重新裁决 |
| 达到本次 `max_steps_per_advance` 软窗口 | 持久化 `checkpointed`，由服务端续跑同一 Plan，不丢失剩余步骤 |
| Planner 输出超过 `max_plan_steps` | 在任何权威步骤前返回 `PLAN_TOO_LARGE`，不截断执行 |

Validator 自动修复不在本 Issue；结构拒绝只能安全停止/重试，不能在本 Issue 内引入隐式
重规划循环。

## 五、父动作、计划和步骤幂等

### 5.1 稳定身份

```text
parent_action_id
  = 原始 clientActionId

parent_input_fingerprint
  = hash(room_id, player_id, actor_id, normalized utterance)

plan_id
  = application-generated stable id，绑定 parent_action_id

step_id
  = application-generated stable id，绑定 plan_id + zero-based index

step_request_id
  = fixed-length hash(parent_action_id, plan_version, step_index)
```

- 同一父 ID + 同一 fingerprint：创建或恢复同一 PlanRun；
- 同一父 ID + 不同 fingerprint/owner：fail closed；
- step request id 必须满足 #212 的 200 字符限制；
- 每个步骤只允许一个冻结后的 `ActionAdjudication` 对应一个 step request id；
- 同一 step request id 提交不同 adjudication，由 Engine 现有 command fingerprint/完整请求
  对比拒绝；
- pending check 的 select/cancel/post-roll 命令继续使用 #212 自己的 request id 与 version，
  Plan 不复制或替代其幂等机制。

### 5.2 为什么不能只靠 parent clientActionId

一个父动作可能合法提交多个不同 revision 上的权威命令。如果所有步骤复用同一个
Engine request id，第二步会被误判为“同一请求不同 payload”；如果每次重试随机生成子
ID，第一步又会重复移动或发放事实。因此父 ID 负责整次玩家目标，确定性 step request id
负责每一个单意图提交。

## 六、ActionPlanRun 持久化

### 6.1 编排记录

建议内部模型：

```text
ActionPlanRun
  plan_id
  parent_action_id
  parent_input_fingerprint
  room_id / player_id / actor_id
  created_revision
  plan_schema_version
  run_version
  status
    active
    checkpointed
    waiting_for_player
    needs_clarification
    retryable_failure
    awaiting_narration
    completed
    cancelled
    stopped
  current_step_index
  policy_snapshot
  plan: ActionPlan
  steps: ActionPlanStepRun[2..max_plan_steps]

ActionPlanStepRun
  step_id
  step_request_id
  semantic_goal
  status
    pending
    adjudicating
    ready
    waiting_for_player
    completed
    stopped
  source_revision?
  adjudication?
  adjudication_execution?
  event_refs[]
  pending_action_request_id?
  safe_failure_code?
```

`ActionPlanRun` 只记录编排状态和已经通过契约校验的单步命令/结果；不保存模型思维链、
工具原始输出、GM-only 正文或 Narrator 草稿。

### 6.2 Store 边界

新增 A-owned port / B-owned adapter：

```text
ActionPlanRunStore
  create(run)
  load(room_id, parent_action_id)
  compare_and_swap(expected_run_version, updated_run)
```

SQL 表建议 `action_plan_runs`：

- 主键或唯一键：`(room_id, parent_action_id)`；
- owner 列：`player_id`、`actor_id`；
- `parent_input_fingerprint`；
- `status`、`current_step_index`、`run_version`；
- `policy_snapshot`，冻结该 Plan 的绝对上限和调度窗口；
- 带 schema version 的 `plan_json`、`steps_json`；
- `created_at`、`updated_at`；
- `run_version` 使用 compare-and-swap，防止多 worker 同时推进同一步。

Plan Store 与 Engine Store 可以共享数据库，但不要求把“保存 Plan 状态”和“提交领域
Event”伪装成一个大事务。跨两次提交使用 Saga 式恢复：稳定 step request id + Engine
command log 是权威事实，PlanRun 是可对账的编排游标。

active/checkpointed/waiting PlanRun 还必须持有可恢复的 room action reservation。一次调度
窗口结束可以释放当前 worker lease，但不能把同一父 Plan 误判为已经结束；新 worker 通过
原子 claim 继续。包括等待 check/player decision 在内，其他父动作在计划 completed、stopped
或 cancelled 前都收到安全的 `ACTION_IN_PROGRESS`，避免 pending decision 被外部 revision
变化破坏。玩家若不再继续，应显式取消当前步骤/剩余 Plan。

### 6.3 Engine 状态查询

为恢复提供一个 B-owned、只读、player-safe 的查询边界：

```text
get_adjudication_status(room_id, player_id, action_request_id)
  -> not_submitted
   | awaiting_skill_choice
   | awaiting_post_roll_decision
   | resolved
   | cancelled
```

它复用 #212 的 `adjudication_command_executions`、`pending_check_decisions` 和 `check_runs`，
不让 A 直接查询 ORM 表，也不返回隐藏 `ActionEffect` 或 GM-only 数据。

## 七、崩溃窗口与恢复算法

| 崩溃/中断位置 | 已有持久证据 | 恢复行为 |
|---|---|---|
| 顶层决策/PlanRun 落库前 | 无 PlanRun、无 step command | 重新执行顶层 Host 决策 |
| PlanRun 已创建、当前步尚未裁决 | step=`pending` | 只裁决当前步骤 |
| 当前步 Host 调用中 | step=`adjudicating`，无冻结 adjudication | 重启后重新裁决当前语义目标 |
| adjudication 已冻结、Engine 前 | step=`ready` | 复用冻结 adjudication，不重复调用 Host |
| Engine 提交前 | status query=`not_submitted` | 使用相同 step request id 提交 |
| Engine 已提交、PlanRun 未更新 | command log/pending check 已存在，step 仍=`ready` | 查询并重放首次结果，补记 PlanRun |
| step 完成、下一步未裁决 | 前一步=`completed` | 从最新 PlayerView 裁决下一步 |
| 等待技能/检定后决定时重启 | #212 pending decision/check run + Plan pointer | 重投影同一安全选项，不重跑 Host/前序步骤/骰点 |
| 玩家选择命令响应丢失 | #212 command execution 已存在 | 使用相同选择 command id 重放首次结果 |
| 全部步骤完成、Narrator 前 | Plan=`awaiting_narration` | 聚合既有 evidence，只运行 Narrator |
| narration 已落库、Plan 未标完成 | parent correlation narration 已存在 | 不重复广播权威叙事，补记 Plan=`completed` |

恢复入口：

- 网络重试：重发同一父 `clientActionId + utterance`；
- 断线重连：按 room/player 查询未完成且属于该玩家的 PlanRun，返回安全进度/待选择投影；
- 服务重建：新 `ActionPlanOrchestrator` 实例只依赖 SQL Plan Store、#212 Engine command
  store 和当前视图即可恢复，不依赖 WebSocket 连接内存。
- 调度窗口续跑：服务端原子 claim `checkpointed` PlanRun 并继续当前 cursor；这只是让出
  worker/event loop，不创建新玩家回合，也不重新规划已经保存的剩余步骤。

## 八、pending check 与玩家选择

ActionPlan 不新建第二套检定协议。当前步骤生成的 `ActionAdjudication` 若需要检定：

1. #212 Engine 提交 `PendingCheckDecision`；
2. Plan step 保存 `pending_action_request_id`，整体进入 `waiting_for_player`；
3. 前端只收到 #212 的 `PendingCheckDecisionView` / `CheckRunView` 和父 plan progress；
4. 玩家选择 candidate/cancel 或 post-roll option 时，继续调用 #212 的 `decide()` /
   `decide_post_roll()`；
5. 首次骰点由 Engine 权威生成并立即持久化，客户端不提交 `roll_value`；
6. pending 状态恢复不重新调用 Planner/Adjudicator，不重走此前步骤，不重新掷骰；
7. 当前步骤最终 resolved 后重新投影 PlayerView，再按停止条件决定下一步；
8. cancel 或最终失败是否继续由冻结的系统停止规则决定，模型不能临时绕过玩家选择。

## 九、部分成功、错误与叙事

### 9.1 部分成功

- 已提交步骤不回滚；
- 后续步骤 retryable Host 失败时，保留当前 step 和之前结果，同一 parent ID 从当前步重试；
- 后续步骤需要澄清或被取消时，Plan 安全停止并保留已发生的位置、时间、资源和事实；
- 前端/错误文案必须说明“前序步骤已经发生，当前步骤等待重试/澄清”，不能显示成整轮
  什么都没发生；
- 不得为了得到整齐的最终叙事而重做、补写或撤销权威步骤。

### 9.2 Narrator evidence

Plan 达到 `awaiting_narration` 或安全 `stopped` 后，A 组装：

```text
original PlayerInput
+ ActionPlan 的玩家安全 goal/step summaries
+ 每个已提交 AdjudicationExecution 的公开 outcome/event refs
+ 最终 revision-bound PlayerView
+ 已允许公开的 committed evidence
```

Narrator 不能读取未提交 adjudication、GM-only rejection details、raw plan reasoning 或未来
步骤。`claimed_fact_ids/evidence_refs` 必须是所有已提交步骤公开 evidence 的子集。

Narrator 失败时 Plan 保持 `awaiting_narration`；重试只重新生成/校验叙事，不再调用
Planner、Adjudicator 或 Engine。最终 narration 继续使用父 action id 作为 correlation，
依靠现有事件唯一约束避免重复权威记录。

## 十、玩家安全进度协议

建议补充或扩展安全事件：

```text
plan.started
  correlation_id / current_step / total_steps

plan.step_changed
  correlation_id / step_index / total_steps
  phase = understanding | executing | waiting_for_player | completed
  public_progress_label

plan.stopped | plan.completed
  correlation_id / completed_steps / total_steps / safe_reason?
```

不得发送：

- raw ActionPlan JSON；
- raw `ActionAdjudication` / ActionEffect；
- 工具参数/结果；
- GMView、隐藏目标、未公开 Information；
- 模型推理或内部 Validator 正文。

单动作仍沿用现有 `turn.*` 事件。复合计划对外始终使用父 `clientActionId` 关联；step
request id 只在服务端审计和幂等层使用。

一个父计划只产生一个最终 `turn.completed`。步骤完成通过上述安全 progress event 表达，
不得把内部 step 伪装成多个独立玩家回合，也不得把 raw step result 直接广播为叙事。

## 十一、实施任务

### A. 契约与 Planner/Adjudicator

- [ ] 增加 `HostTurnDecision = SingleActionDecision | ActionPlan`；
- [ ] 增加可变长度 `ActionPlan` / `ActionPlanStep`（至少 2 步、顺序、无分支）；
- [ ] 增加可配置 `ActionPlanPolicy`，默认 `max_plan_steps=32`、
  `max_steps_per_advance=3`，并在 PlanRun 中冻结快照；
- [ ] 更新 provider-neutral Prompt、structured output schema 和 deterministic parser；
- [ ] 保持单动作直接输出/提交 `ActionAdjudication`；
- [ ] 实现逐步 adjudication context，确保未来步骤延迟裁决；
- [ ] 定义安全停止原因和公开错误映射；
- [ ] 对 Planner/Adjudicator output 做 schema、identity、revision 和 scope 校验。

### B. PlanRun 与恢复持久化

- [ ] 增加 `ActionPlanRun` / `ActionPlanStepRun` 内部模型和 schema version；
- [ ] 增加独立 `ActionPlanRunStore` port；
- [ ] 实现 InMemory Store 与 SQLAlchemy Store；
- [ ] 新增 `action_plan_runs` Alembic 迁移及正反迁移测试；
- [ ] 实现 `run_version` compare-and-swap 和 owner/fingerprint 冲突保护；
- [ ] 实现 active/checkpointed Plan 的 durable room reservation 与 worker claim/lease；
- [ ] 增加带 parent owner、run version 和 request id 的幂等 `plan.cancel`；
- [ ] 增加 player-safe `get_adjudication_status()` 恢复查询；
- [ ] 实现 Engine 已提交但 Plan 未更新的 reconciliation。

### A/B. Orchestrator 与协议接入

- [ ] 实现 `ActionPlanOrchestrator.start_or_resume()`；
- [ ] 实现软窗口 checkpoint 与服务端自动 continuation，不要求玩家重输剩余步骤；
- [ ] 支持玩家在步骤边界取消剩余 Plan，保留已提交事实并释放 room reservation；
- [ ] 每步冻结 adjudication 后才调用 #212 Engine；
- [ ] 每次提交后刷新 PlayerView 并验证 revision；
- [ ] 接入 pending skill/post-roll decision 的暂停与恢复；
- [ ] 实现 completed/stopped/retryable/clarification 的状态迁移；
- [ ] 聚合 committed evidence 并只运行一次最终 Narrator；
- [ ] 接入 WebSocket/API 的安全 Plan progress 和 reconnect projection；
- [ ] 保持单动作快路径与现有协议兼容。

### Schema、文档与可观测性

- [ ] 导出 ActionPlan/Plan progress JSON Schema；
- [ ] 更新 SDK 生成类型和事件 validator；
- [ ] 日志只记录 plan/step id、步数、revision、termination reason、延迟和 token usage；
- [ ] 不记录玩家原话、GM-only context、raw model output 或隐藏效果；
- [ ] 更新 `rule-engine-v3.md`，明确 Plan Store 与单意图 Engine 的非重叠边界。

## 十二、验收标准

### 12.1 有限计划与单动作兼容

- [ ] 自然语言单动作继续走 `SingleActionDecision → ActionAdjudication` 快路径，不创建
  PlanRun、不增加步骤级 Host/Engine 调用；
- [ ] ActionPlan 支持从 2 到运行时技术上限的可变数量顺序步骤；4 步输入不会因固定
  Schema 上限失败；1 步继续走 single action；分支、循环、并行和动态追加仍拒绝；
- [ ] 默认技术上限为 32 且可配置；超过上限返回 `PLAN_TOO_LARGE`，不会静默截断、部分
  执行或丢失后续玩家目标；
- [ ] 默认每次推进窗口为 3 且可配置；4 步以上计划跨窗口自动续跑时仍保持同一 parent、
  PlanRun、步骤顺序和 room ownership；
- [ ] 风险边界可以缩小有效窗口但不能扩大绝对上限；玩家可取消剩余步骤，取消不回滚
  已提交步骤、不规避已经产生的权威骰点；
- [ ] step kind 只允许 `travel/wait/rest/action/dialogue`；尚无领域执行能力的步骤会在
  权威提交前安全停止，Narrator 不得把未执行效果写成已经发生；
- [ ] “去书房找线索”在一次父提交中先移动，再在书房新 revision 上形成调查裁决；
- [ ] “去图书馆查旧报纸”到达后只能使用目的地新视图/GMView 允许的 Information、来源
  和技能候选；
- [ ] “到墓地问守墓人”到达后才能解析目的地可见 NPC 并形成对话/行动裁决；
- [ ] scripted 3-step Plan 可以逐 revision 执行，证明编排底座可承接 #208 的
  `travel → rest/wait → travel`，但不伪称已实现时间或 Ambient 领域；
- [ ] scripted 4/5-step Plan 跨默认 3 步软窗口继续执行，证明窗口不是产品步骤上限。

### 12.2 revision、权限与保密

- [ ] 每一步持久化自己的 source revision，后一项严格使用前一项提交后重新投影的视图；
- [ ] 目的地隐藏 Entity、Information、技能候选和 Keeper-only 内容不进入初始 Plan、前序
  step context 或公共 progress event；
- [ ] stale adjudication 在 Engine 提交前被拒绝；未提交步骤可以基于最新视图重新裁决，
  已提交步骤只能重放首次结果；
- [ ] Agent 不能指定/覆盖 parent、plan、step request id、owner 或 revision；
- [ ] ActionPlan/PlanRun 不包含任意 State Patch；所有领域状态仍只由 #212 Engine 写入；
- [ ] Engine 不接收或解释 ActionPlan，不自动续跑下一步。

### 12.3 幂等、并发与服务恢复

- [ ] 同一父 `clientActionId + fingerprint` 重试恢复同一 PlanRun，不重复移动、推进时间、
  掷骰、扣资源或发放事实；
- [ ] 同一父 ID 携带不同输入、player 或 actor 被拒绝；
- [ ] 多 worker 同时推进同一 Plan 时，CAS 只允许一个 adjudication 成为冻结步骤；
- [ ] 同一房间同时只有一个 active/checkpointed/waiting Plan；worker lease 过期可恢复，
  但其他父动作不能让 pending plan 的 revision 漂移；
- [ ] Host 在任意后续步骤失败后，同一父 ID 只重试当前未提交步骤；
- [ ] 覆盖 adjudication 冻结后/Engine 前和 Engine 提交后/Plan 更新前两个 crash window；
- [ ] pending skill choice、首次权威骰点和 post-roll decision 在进程/Store 重建后恢复；
- [ ] 重复 select/cancel/luck/push 命令重放 #212 的首次结果，不重新掷骰或重复效果；
- [ ] 所有步骤完成后 Narrator 失败，只重试叙事；
- [ ] narration 已持久化但 Plan 未标完成时，恢复不会重复权威叙事；
- [ ] SQL Store 新实例和 `ActionPlanOrchestrator` 新实例可恢复 active/waiting/awaiting_narration
  的计划，不依赖 WebSocket 内存。

### 12.4 部分成功、UX 与叙事真实性

- [ ] 第一步已成功、第二步 retryable 失败时，玩家看到“已完成前序步骤，当前步骤可重试”，
  而不是整轮失败；
- [ ] 第二步需要澄清、取消或最终失败时，不回滚第一步，且不会继续执行第三步；
- [ ] Plan progress 可区分理解当前步骤、执行、等待玩家、停止和完成；
- [ ] 公共事件不暴露 raw plan/adjudication、工具参数、GM-only 内容或内部拒绝正文；
- [ ] 最终 Narrator 只能声明已提交步骤的公开 evidence；位置、时间、检定和资源描述与
  最终 PlayerView 一致；
- [ ] `claimed_fact_ids/evidence_refs` 跨步骤聚合后仍执行子集校验。

### 12.5 自动化验证

- [ ] Contract/Policy 单测覆盖 single、2/3/4/5 步、默认上限、配置上限、超限不截断、
  非法结构和身份字段；
- [ ] deterministic Fake Planner/Adjudicator 覆盖成功、第二步 check、第二步非法、第二步
  Host 失败、取消、Narrator 失败；
- [ ] 自然中文同义词、省略和复合表达至少覆盖“去 X 找 Y”“到 X 问 Y”“进入 X 搜索”
  等 #149 句式；
- [ ] 使用当前生产模型至少完成人工/非 CI 纵切验收并保存脱敏结果，证明真实输出能稳定
  选择 single action 或可变长度 plan；CI 不依赖外部模型可用性；
- [ ] 隐私测试证明第二步目标只在第一步提交后的 context 出现；
- [ ] InMemory fault injection 覆盖每个 crash window；
- [ ] SQL 集成测试覆盖迁移、CAS、重建、pending check 和 reconciliation；
- [ ] WebSocket/E2E 覆盖父请求重试、断线恢复、部分成功和安全进度；
- [ ] 现有 #212 单意图 adjudication、check、revision、幂等、Event/Rule、visibility 和
  schema tests 全部通过；
- [ ] lint、typecheck、schema export drift、Alembic single-head 和相关全量测试通过。

## 十三、完成定义

本 Issue 只有在以下条件同时满足时才能关闭：

1. 计划契约、逐 revision 编排、PlanRun SQL 持久化和恢复均已实现；
2. #149 的三个 Canon 复合表达至少由 deterministic E2E 覆盖；
3. 可变长度计划、软执行窗口、绝对技术上限、停止条件、部分成功和所有关键 crash
   window 有自动化证据；
4. pending check、post-roll decision 和 Narrator 失败均能跨服务实例恢复；
5. 单动作快路径和 #212 单意图 Engine 回归保持通过；
6. 未引入平行权威写入口，未提前实现或伪装时间、Ambient、自动修复或 Director；
7. 文档明确记录：该 Issue 完成的是 #208 的 ActionPlan 子项，不等于整个 #208 已完成；
8. 代码经过至少一名成员人工 Review。

以下不构成完成：只修改 Prompt、只在进程内循环调用多个 Agent、只增加内存 Plan、要求
玩家手工拆句、复用一个 request id 执行多步、提前读取目的地内容，或只覆盖正常成功路径。

## 十四、依赖与后续联调

- 依赖 #212 的单意图 `ActionAdjudication` 与 check workflow 作为每一步执行基座；
- 时间/休息 Issue 接入后，增加 `travel → rest/wait → travel` 的权威时间联调；
- Ambient Issue 接入后，增加“普通旅店创建/复用 → 休息 → 返回 Canon 墓地”的联调；
- Validator 修复 Issue 接入后，只修复当前未提交步骤，不能重写已完成步骤；
- Director/Narrator 后续能力只能消费 Plan 的安全状态与 committed evidence，不能绕过
  ActionPlanOrchestrator 或 Engine。

当时间与 Ambient 两项完成后，#208 Case 1 必须升级为跨 Issue 端到端关闭门槛：

```text
“我回旅店休息，晚上再去墓地”
→ 3-step ActionPlan
→ 普通旅店被安全创建或复用
→ 权威时间推进到夜晚
→ 最终位置为已知墓地
→ Narrator 与实际 PlayerView 完全一致
```

---

## 决策状态

1. **已确认：可变长度计划 + 双层预算**。公共 ActionPlan 不固定为 3 步；运行时绝对技术
   上限建议默认 32 且可配置，单次自动推进软窗口建议默认 3。4/5 步正常执行，超技术
   上限明确澄清且绝不截断；
2. **已确认：Plan Store 与单意图 Engine Store 分层**。共享数据库但职责分离，以 Saga
   对账恢复，不让 Engine 接收 ActionPlan；
3. **已确认：本 Issue 的关闭范围**。完成 ActionPlan 子项和 #149 Canon 纵切；#208 的
   旅店/休息/夜晚/墓地完整 Case 由时间与 Ambient 后续 Issue 联调后作为上位 #208 的
   关闭门槛。

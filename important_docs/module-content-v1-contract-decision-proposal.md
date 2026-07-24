# ModuleContent v1 Contract Decision Proposal

- 状态：Proposed
- 日期：2026-07-23
- 目标：供 Parser、Rule Engine、Host 三方讨论并冻结 v1 开发边界
- 当前可执行权威：`agent-collaboration-framework/collaboration_framework/contracts/module.py`
- 非目标：不设计未来完整 Schema，不直接合并 PR99，不实现新领域模型

> 文档关系：本文保留为当前最小 v1 冻结提案。面向多个模组的统一扩展方向已转入 [`../agent-collaboration-framework/docs/architecture/data-model-alignment-rfc.md`](../agent-collaboration-framework/docs/architecture/data-model-alignment-rfc.md)，两者分别代表“当前可执行基线”和“待冻结目标”。

## 1. v1 总体决议

v1 采用当前最小可执行闭环：

```text
ModuleDraft
→ Validation
→ ModuleContent
→ Runtime + GameState
→ ActionResult / PlayerView
→ Host
```

v1 只承诺：

```text
Scene
→ Entity
→ Checkpoint
→ Rule/Operation
→ Entity State Modification
→ Event
→ WinCondition
→ phase = ended
```

PR99 和 Archive 中出现的其他概念只作为 Capability Gap 和后续演进依据，不进入 v1。

## 2. ModuleContent v1 字段

### 2.1 顶层字段

v1 最终只包含：

| 字段 | 职责 |
|---|---|
| `module_id` | 模组稳定身份 |
| `version` | 模组内容版本 |
| `world_ref` | Ruleset/World 引用 |
| `scenes` | 叙事和交互上下文 |
| `entities` | 可交互对象、初始状态和局部规则 |
| `checkpoints` | 模组声明的检定机会和结果 |
| `win_conditions` | 正式终局触发条件 |

v1 不增加：

- `contract_version`；
- `content_hash`；
- `metadata`；
- `entry_points`；
- `locations`；
- `facts`；
- `resources`；
- `timelines`；
- `tracks`；
- `encounters`；
- `endings`；
- `assets`；
- `character_templates`；
- 顶层 `initial_state`。

### 2.2 SceneSpec

保留：

```text
id
name
content
entity_ids
checkpoint_ids
```

### 2.3 EntitySpec

保留：

```text
id
kind
name
aliases
content
secrets
state
refuse_ops
blocked_text
direct_responses
rules
```

v1 的 `kind` 继续使用：

```text
npc
object
location
```

不在 v1 拆分 Character、Resource 或 Location。

### 2.4 RuleSpec

保留：

```text
id
hook
priority
when
then
facts
player_visible_information
```

Condition 保留：

```text
path
equals
```

Operation 保留：

```text
allow
modify
```

不增加完整 Expr、脚本、自然语言 Condition 或 PR99 Effect 类型。

### 2.5 CheckpointSpec

保留：

```text
id
scene_id
action
target_id
skills
difficulty
outcomes
```

Outcome 保留：

```text
facts
player_visible_information
narration_constraints
ops
```

当前 `mvp_check_result` 只视为 Fake Runtime 和测试的过渡控制项，不视为模组领域语义。v1 开发期间不要求 Parser 从原文提取该字段。

### 2.6 WinConditionSpec

保留：

```text
id
when
fact
player_visible_information
```

命中后由 Runtime：

```text
ending_id = WinCondition.id
phase = ended
```

## 3. 暂不进入 v1 的概念

| 概念 | 来源 | 暂不进入原因 |
|---|---|---|
| Location 一级模型 | PR99 | 当前没有 navigation、多人位置和隐藏路线 Runtime |
| FactSpec/ClueSpec | PR99/Archive | 当前 Runtime 使用结果字符串，尚无事实图和线索授权模型 |
| ResourceSpec | PR99 | 当前没有 Inventory/Resource subsystem |
| Character/Pregen | PR99/Archive | 当前不负责自动建局和角色初始化 |
| SanityEvent/SanTrigger | Archive/PR99 | 尚未确定属于通用 Contract 还是 CoC Ruleset extension |
| Timeline | PR99 | 当前没有 Runtime scheduler |
| Track | PR99 | 当前没有通用阶段状态机 |
| Encounter | PR99 | 当前没有持续挑战 Orchestrator |
| Puzzle/Table | PR99 | 缺少稳定的跨模组语义和 Runtime consumer |
| Asset | PR99/Archive | Repository、权限和展示策略尚未确定 |
| Ending 一级模型 | PR99 | 当前已有 WinCondition 消费链，不能维护两套终局集合 |
| 完整 Expr | Archive | 当前 Runtime 只支持状态路径等值判断 |
| Source references | PR99 | 属于 ParserResult/provenance，不属于 Runtime 内容 |
| extraction quality/rights | PR99 | 属于 Parser、Publish 或 Repository |
| content hash | PR99 | 由 Publish 计算，不属于内容本体 |
| 顶层 initial_state | PR99 | 当前状态属于 GameState；Entity.state 已提供对象初值声明 |

这些概念应记录为：

```text
Capability Candidate
或
CapabilityGap
```

不能通过增加未消费字段假装已经支持。

## 4. 三层数据流

### 4.1 Parser Draft

Parser 私有层负责保存：

- 待验证的模组内容候选；
- 尚未规范化的 ID 和引用；
- 无法表达的原文机制；
- 未决问题；
- 来源证据和解析信息。

推荐关系：

```text
ParserResult
├── draft: ModuleDraft
├── provenance
├── normalization_decisions
├── unresolved_questions
└── capability_gaps
```

`ModuleDraft` 不进入 Runtime。

### 4.2 ModuleContent

Validation 是唯一转换入口：

```text
ModuleDraft
→ Schema validation
→ Reference validation
→ State path validation
→ Runtime capability validation
→ ModuleContent
```

ModuleContent：

- 严格；
- 不可变；
- 拒绝未知字段；
- 不含 Parser provenance；
- 不含某局游戏状态；
- 只包含 Runtime 能执行的静态声明。

### 4.3 Runtime State

Runtime 加载 ModuleContent，并结合已经初始化的 GameState 执行。

```text
ModuleContent.Entity.state
= 每局初始状态声明

GameState.entities
= 某个 Room 当前状态
```

Runtime State 包含：

- `room_id`；
- 当前 `scene_id`；
- `phase`；
- `ending_id`；
- Actor 状态；
- Entity 当前状态；
- Event sequence；
- EventLog；
- Check result；
- StateChange；
- ExecutionResult。

Runtime 不修改 ModuleContent。

## 5. Decision Proposals

### Decision 1：Scene vs Location

**Decision：**

v1 只保留 `SceneSpec`。Location 暂不建立独立一级模型，地点可暂时通过 `EntitySpec(kind="location")` 表达。

**Reason：**

- Scene 已被 Runtime 用于确定 Entity 和 Checkpoint 候选；
- 当前没有地图导航、空间连接或多人位置执行语义；
- 独立 Location 会增加引用和状态同步成本；
- 真实模组需要 Location，不等于 v1 Runtime 已经需要它。

**Rejected Alternative：**

同时保留 Scene、Location 和 `Entity(kind="location")`。

**Impact：**

- Parser v1 只生成 Scene 和 location Entity；
- Rule Engine 不实现导航系统；
- Host 只获得当前 Scene 的安全投影；
- 复杂空间结构记录为 CapabilityGap。

### Decision 2：Entity.state

**Decision：**

`Entity.state` 保留在 ModuleContent，表示状态键声明和每局初始值；运行中的值只保存在 GameState。

**Reason：**

- Validation 需要根据它验证 Condition/Operation 状态路径；
- 每个 Room 需要独立状态副本；
- ModuleContent 发布后不可变；
- 当前状态不能污染所有房间共享的静态内容。

**Rejected Alternative：**

- 将 Entity 当前状态直接写回 ModuleContent；
- 在 ModuleContent 顶层再增加一套重复 `initial_state`；
- 完全移除初始状态，让 Runtime 猜测状态键。

**Impact：**

```text
Entity.state
→ Loader 复制
→ GameState.entities
→ Runtime 只修改 GameState
```

当前 Phase 1 继续使用外部 `demo-state.json`，不实现自动初始化。

### Decision 3：Rule.hook

**Decision：**

v1 正式执行范围建议只承诺 `on_action`。其他已声明 hook 在 dispatcher 实现前视为未支持能力，Validation 不应允许其进入正式发布物。

**Reason：**

- 当前 action 流程没有按照 hook 正确过滤 Rule；
- 声明字段但不执行语义会导致规则在错误时机运行；
- Parser、Validation 和 Runtime 的 hook catalog 必须一致；
- v1 不需要为了保留枚举而宣称四种 hook 已支持。

**Rejected Alternative：**

- 保留四种 hook，并假设 Runtime 会忽略未实现值；
- 由 Host 根据 hook 名称自行执行 Rule；
- 删除 hook，让所有 Rule 都在 action 时执行。

**Impact：**

- 团队需要确认 v1 是收窄为 `on_action`，还是由 B 侧补齐 dispatcher；
- 在确认前，`on_scene_enter/on_turn_end/on_check_resolve` 属于 Runtime Gap；
- Parser 遇到依赖这些时机的机制必须产生 CapabilityGap，不能静默改成 `on_action`。

### Decision 4：Checkpoint

**Decision：**

Checkpoint 是 ModuleContent 中的静态检定声明；ActionRequest、骰点、成功等级和本次 Outcome 属于 Runtime。

**Reason：**

Checkpoint 描述：

- 在哪个 Scene；
- 针对哪个 Entity；
- 哪些技能合法；
- 难度是什么；
- 成功和失败分别产生什么结果。

它不描述玩家本次一定做了什么，也不拥有本次骰点结果。

**Rejected Alternative：**

- 把 Checkpoint 当成已经发生的故事 Event；
- 把 Checkpoint 当成 Runtime Action；
- 由 Host 临时生成技能、难度和后果；
- 让 `mvp_check_result` 成为正式模组内容。

**Impact：**

```text
CheckpointSpec
→ Host 匹配 Intent
→ Runtime 校验候选
→ CheckResolver 决定结果
→ Runtime 执行 Outcome
```

Phase 1 Fake Runtime 可以继续使用固定结果测试，但 Parser 不负责提取测试结果。

### Decision 5：WinCondition vs Ending

**Decision：**

v1 继续使用 `WinConditionSpec/win_conditions`，且只表达正式终局。暂不增加 `EndingSpec/endings`。

**Reason：**

- 当前 Runtime 已消费 `win_conditions`；
- 已有完整集成测试；
- 当前 WinCondition 命中后会设置 `phase="ended"`；
- 两套终局集合会产生优先级和事实来源冲突；
- 名称迁移不是 v1 闭环的必要条件。

**Rejected Alternative：**

- 同时保留 `win_conditions` 和 `endings`；
- 把状态回滚和非终局失败放进 WinCondition；
- 立即破坏性重命名所有代码和 fixture；
- 让 Host 自行判断故事结束。

**Impact：**

- v1 Parser 只生成 `win_conditions`；
- Runtime 命中后进入 ended；
- 非终局失败、重试和回滚由 Rule/Operation 表达；
- 是否迁移为 `endings` 留给后续独立 ADR。

### Decision 6：Fact

**Decision：**

v1 不新增 `FactSpec`。继续使用 Rule、CheckpointOutcome 和 WinCondition 中现有的 `facts` 文本。

**Reason：**

- 当前 Runtime 把 facts 作为已确认结果文本消费；
- 当前没有 Fact ID、Clue 授权、Fact Graph 或持久化事实系统；
- 新增 FactSpec 会要求同时修改 Runtime、Projection 和 Host 引用方式。

**Rejected Alternative：**

- 立即新增顶层 `facts`；
- 同时保留字符串 facts 和 `fact_ids`；
- 让 Parser 将所有原文句子转换成 Fact 对象。

**Impact：**

- v1 facts 不是可独立查询的领域对象；
- Host 只能消费 Runtime 确认后的可见结果；
- 需要正式线索网络时，再整体设计 Fact/Clue/Projection。

### Decision 7：Resource

**Decision：**

v1 不新增 `ResourceSpec`。模组物品继续通过 `EntitySpec(kind="object")` 表达。

**Reason：**

- 当前 Runtime 没有 inventory、consume、equip 或 ownership subsystem；
- 现有 Entity 已能表达名称、描述、状态和规则；
- 拆分只会增加分类与引用，没有独立 Runtime 行为收益。

**Rejected Alternative：**

- 同时维护 object Entity 和 Resource；
- 仅根据 PDF 中出现“物品”就建立 Resource；
- 让 Host 用自然语言维护 Inventory。

**Impact：**

- 可交互物品继续是 Entity；
- 复杂持有、消耗和装备机制记录为 CapabilityGap；
- Resource 是否独立，等待 Inventory 用例决定。

### Decision 8：Timeline

**Decision：**

v1 不新增 Timeline。时间推进、定时事件和多日流程不属于当前承诺能力。

**Reason：**

- 当前 Runtime 没有 scheduler、clock 或 timeline state；
- Parser 能提取时间描述，不等于 Runtime 能确定性执行；
- 将 Timeline 只作为数据保存会形成无消费者字段。

**Rejected Alternative：**

- 先加入 Timeline Schema，等待 Runtime 以后支持；
- 将所有时间事件错误转换成 `on_action` Rule；
- 由 Host 自行记忆和推进时间。

**Impact：**

- Parser 遇到影响玩法的时间机制时产生 CapabilityGap；
- 不影响简单线性模组的 v1 导入；
- 后续只有在 scheduler、Validation 和端到端测试完成后才重新评估。

## 6. 三方开发边界

### 6.1 Parser

负责：

- 从原文提取 v1 可表达内容；
- 生成 ModuleDraft；
- 保留来源和未决问题；
- 报告 CapabilityGap。

不负责：

- 发明 Runtime 不支持的字段；
- 执行 Rule；
- 修改 GameState；
- 将复杂机制强行降级成错误的 v1 语义。

### 6.2 Rule Engine

负责：

- 加载正式 ModuleContent；
- 校验并执行 Condition/Operation；
- 执行 Checkpoint Outcome；
- 修改 GameState；
- 记录 Event；
- 求值 WinCondition。

不负责：

- 解析 PDF；
- 猜测未声明状态；
- 执行 Parser provenance；
- 让 Host 直接写状态。

### 6.3 Host

负责：

- 基于安全投影理解玩家意图；
- 从可信 Checkpoint 候选中选择；
- 表达 Runtime 已确认结果；
- 遵守 narration constraints。

不负责：

- 直接读取完整 ModuleContent；
- 读取 secrets 或未发生分支；
- 决定权威骰点结果；
- 执行 Operation；
- 自行结束游戏。

## 7. 建议冻结结论

团队确认后，v1 开发边界冻结为：

```text
ModuleContent v1
= module_id
+ version
+ world_ref
+ scenes
+ entities
+ checkpoints
+ win_conditions
```

嵌套执行能力冻结为：

```text
Condition = path + equals
Operation = allow + modify
Checkpoint Outcome = facts + visible information + narration constraints + ops
```

暂不扩展 PR99/Archive 的一级模型。

在 v1 冻结前，只剩一个必须由 B/C 共同确认的阻塞项：

> `Rule.hook` 是把 v1 正式范围收窄为 `on_action`，还是由 Rule Engine 补齐其他 hook dispatcher。

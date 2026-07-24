# ModuleContent v1 最终契约决议

- 状态：**Accepted / Published**
- 适用范围：Module Parser、Rule Engine 与 Host Agent 的模组内容边界
- 锚定代码：`collaboration_framework/contracts/module.py`
- 生成 Schema：`schemas/module-content.schema.json`

本文只记录当前生效的最终决议，不保留候选模型、字段对比、阶段计划或覆盖率讨论。
若本文与代码或生成 Schema 冲突，以 Pydantic 契约和生成 Schema 为准，并在同一个
PR 中修正文档。

## 1. 边界与权威顺序

Module Parser 先产生私有 `ModuleDraft`，再经过确定性 Validation 构造
`ModuleContent`。Runtime 只能加载验证后的 `ModuleContent`，不得直接读取
`ModuleDraft`。

```text
原文
  -> ParserResult / ModuleDraft
  -> deterministic Validation
  -> ModuleContent
  -> Publish
  -> Runtime
```

权威顺序如下：

1. `collaboration_framework/contracts/module.py`
2. `schemas/module-content.schema.json`
3. `collaboration_framework/module/validation.py`
4. 本文
5. [MODULECONTENT-README.md](MODULECONTENT-README.md) 中的团队阅读示例

所有跨边界模型继承 `ContractModel`，因此拒绝未知字段、创建后不可原地修改，并对
字符串执行统一的边界清理。

## 2. 顶层结构

`ModuleContent` 固定使用以下顶层字段：

| 字段 | 必填 | 决议 |
|---|---:|---|
| `module_id` | 是 | 模组稳定 ID |
| `version` | 是 | 模组内容版本 |
| `world_ref` | 是 | 当前规则系统引用 |
| `background` | 是 | 时代、地点、玩家侧故事前提与叙事基调 |
| `scenes` | 是 | 场景声明 |
| `entities` | 是 | NPC、物件和地点实体声明 |
| `checkpoints` | 是 | 玩家可尝试动作与结果声明 |
| `win_conditions` | 是 | 结局或非终局里程碑声明 |
| `module_rules` | 否，默认空 | 模组级规则 |
| `information_items` | 否，默认空 | 可稳定引用的信息事实 |

不新增 Track、Timeline、Encounter、Faction、Puzzle 等平行顶层集合。此类机制优先
由 Entity 状态、Rule、Condition、Operation、Checkpoint 和 WinCondition 组合表达。
无法由当前语言可靠表达或执行的机制应记录为 Capability Gap，不得临时添加模组专用
字段。

## 3. `background` 的内容与传播

`background` 是面向叙述 Agent 的模组级上下文，必须提炼原文开头的：

- 时代和主要地点；
- 玩家在开场时已知的故事前提；
- 故事类型、气氛和叙事基调；
- 不泄密的世界状态或社会背景。

它会进入每一次 `NarrationContext`，用来稳定整场叙述的语气和时代感，但不会直接
进入玩家可见的 WebSocket 输出，也不能替代 `visible_facts` 成为已揭示事实。
幕后真相、NPC 秘密和未发现线索必须继续放在 `secrets` 或带可见性约束的信息结构中。

## 4. 内容对象

### 4.1 `SceneSpec`

| 字段 | 决议 |
|---|---|
| `id` / `name` / `content` | 场景身份、显示名和叙事内容 |
| `entity_ids` | 场景内实体引用 |
| `checkpoint_ids` | 场景内可用 Checkpoint 引用 |
| `exits` | 可到达的 Scene 引用；空数组表示契约不施加出口限制 |

### 4.2 `EntitySpec`

| 字段 | 决议 |
|---|---|
| `id` / `name` / `aliases` | 稳定身份与语义匹配名称 |
| `kind` | 仅允许 `npc`、`object`、`location` |
| `content` | 玩家可见的基础描述 |
| `secrets` | KP 私密描述，不进入玩家安全投影 |
| `information_item_ids` | 关联的 `InformationItem` 引用 |
| `state` | 声明可被规则引用的合法状态键 |
| `refuse_ops` / `blocked_text` | 静态拒绝能力及玩家提示 |
| `direct_responses` | 无检定交互的直接回应 |
| `rules` | 实体级规则 |
| `stat_block` | 可选 CoC 属性块 |

`state` 用于声明内容契约中的状态槽和默认值；实际运行状态、持久化和并发修改仍由
Rule Engine 的 `GameState` 管理。

### 4.3 `CheckpointSpec`

| 字段 | 决议 |
|---|---|
| `id` / `scene_id` | Checkpoint 身份及所属场景 |
| `action` | IntentParser 的语义提示，不是封闭动词白名单 |
| `target_id` | 当前场景内的目标 Entity |
| `skills` | 允许的标准技能 ID |
| `difficulty` | `regular`、`hard`、`extreme` 或 `null`；`null` 表示运行时裁量 |
| `outcomes` | 必须有 `success` 和 `failure`，可覆盖分级结果 |
| `visibility` | Checkpoint 的受众和发现政策 |

分级结果可分别声明 `critical_success`、`extreme_success`、`hard_success`、
`regular_success` 和 `fumble`。未提供分级覆盖时回退到二元成功/失败结果。

每个 `CheckpointOutcomeSpec` 可包含：

- `facts`：确定性执行确认事实；
- `player_visible_information`：可向指定受众展示的信息；
- `narration_constraints`：Narrator 必须遵守的表达约束；
- `ops`：有序 Operation 列表。

### 4.4 `WinConditionSpec`

`WinConditionSpec` 由 `id`、`when`、`fact`、`player_visible_information` 和
`is_ending` 组成。`is_ending=true` 表示终局；`false` 表示满足条件后只形成里程碑
或状态结果，不结束游戏。

### 4.5 `InformationItem`

`InformationItem` 是可稳定引用的信息事实，包含 `id`、`content` 和静态
`visibility`。动态发现流程必须由 Checkpoint、Rule 和 Outcome 表达，因此
`InformationItem.visibility.requires_discovery` 必须为 `false`。

## 5. 规则语言

### 5.1 `RuleSpec`

Rule 固定由以下字段组成：

| 字段 | 决议 |
|---|---|
| `id` | 在整个 ModuleContent 内唯一 |
| `hook` | 规则触发点 |
| `priority` | 同一触发点的排序依据 |
| `mode` | `append`、`override` 或 `forbid` |
| `when` | 唯一 Condition |
| `then` | 有序 Operation 列表 |
| `facts` | 确认事实 |
| `player_visible_information` | 带可见性政策的玩家信息 |

发布契约允许以下 20 个 Hook：

```text
on_attack_declare      on_difficulty_calc    on_attack_roll
on_dodge_declare       on_dodge_roll         on_hit_resolve
on_damage_roll         on_armor_apply        on_hp_write
on_major_wound         on_death              on_turn_end
on_check_declare       on_check_roll         on_check_resolve
on_scene_enter         on_scene_exit         on_interact
on_state_change        on_time_elapsed
```

### 5.2 `ConditionSpec`

Condition 必须且只能选择一种形式：

```json
{"path": "entities.cabinet.state.opened", "equals": true}
```

或：

```json
{"expr": "clock.turn_elapsed >= 10 and party.size > 2"}
```

实体状态路径必须引用已存在的 Entity 和其 `state` 中已声明的键。`expr` 属于发布
语言，但完整表达式求值能力由 Runtime 实现状态决定。

### 5.3 `OperationSpec`

Operation 使用 `op` discriminator，当前固定为 12 种：

| `op` | 关键字段 | 用途 |
|---|---|---|
| `allow` | `action` | 允许动作 |
| `modify` | `path`, `set` | 兼容式设置状态 |
| `set` | `path`, `value` | 设置状态 |
| `scale` | `value`, `round` | 缩放当前数值 |
| `add` | `path`, `value` | 累加状态 |
| `absorb` | `amount`, `decrement` | 吸收并消耗资源 |
| `forbid` | — | 禁止当前行为 |
| `force` | `action` | 强制受控动作 |
| `apply_condition` | `condition` | 应用规则条件或状态 |
| `trigger_ending` | `ending_id` | 触发已声明 WinCondition |
| `trigger_rule` | `rule_id` | 触发已声明 Rule |
| `transition` | `scene_id` | 转移到已声明 Scene |

发布契约允许的 Operation 不等于占位内核已经完整执行的 Operation。Runtime 不得静默
改写不支持的操作；应明确拒绝、报告能力缺口或由已批准的兼容层处理。

## 6. 可见性

`VisibilityPolicy.audience` 固定为：

- `all`：全体玩家；
- `actor`：当前行动者；
- `ho`：指定 HO，此时必须提供 `ho_ref`；
- `keeper`：仅 KP。

`requires_discovery=true` 时可提供 `discovery_rule`，并由
`discovery_shares_to_party` 决定发现结果是否共享。非 HO 受众不得携带 `ho_ref`；
无需发现时不得携带 `discovery_rule`。

## 7. 确定性校验不变式

Validation 必须至少保证：

1. Scene、Entity、Checkpoint、WinCondition 和 InformationItem 各自 ID 唯一；
2. 模组级与实体级 Rule ID 在整个 ModuleContent 内唯一；
3. Scene 引用的 Entity、Checkpoint 和出口均存在；
4. Checkpoint 的 Scene 和 Target 均存在，且同时列在对应 Scene 中；
5. Entity 引用的 InformationItem 存在；
6. Rule、WinCondition 和状态 Operation 使用的实体状态路径已声明；
7. `transition`、`trigger_ending` 和 `trigger_rule` 的目标存在；
8. 所有可见性组合满足受众与发现规则约束；
9. Parser 使用的技能 ID 可在注入的 Ruleset 快照中解析。

Validation 收集稳定错误码并返回 `pass`、`needs_revision` 或 `blocked`，不得用 LLM
判断替代确定性检查。只有 `pass` 可以进入 Publish。

## 8. Parser、Runtime 与 Host 的职责

- Parser 负责从原文提取 Draft、保留来源信息并报告无法可靠归一化的 Gap。
- Validation 负责结构、引用、状态路径和 Ruleset ID 的确定性校验。
- Publish 只发布验证通过的 `ModuleContent`。
- Rule Engine 负责权威状态、Event、检定和已实现的规则语义。
- Host Agent 只消费玩家安全投影和叙述上下文，不直接修改 ModuleContent 或 GameState。
- `background` 只稳定叙事基调；可见事实仍以 PlayerView、ActionResult 和显式信息政策为准。

## 9. 当前示例

四个当前示例及原文位于
[`examples/module-content-validation/`](examples/module-content-validation/)：

- 幸福蛙蛙村；
- 校园黑色怪谈；
- 追书人；
- 银之锁。

每个目录只保留原文和 `module-content-draft.json`。示例 JSON 必须通过当前
`ModuleDraft` 与完整 `validate_module_json` 校验；示例不构成独立于代码的第二套
字段规范，也不再单独维护容易过期的阶段性映射报告。

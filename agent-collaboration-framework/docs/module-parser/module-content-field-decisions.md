# ModuleContent 最终字段决策

> **Status：Frozen**
> **Version：ModuleContent v1**
> 日期：2026-07-23
> 锚定代码：`collaboration_framework/contracts/module.py`
>
> 当前实现目标为本文档描述的最终冻结版本。文档中的 P0/P1/P2 是设计演进过程记录，不代表当前需要逐阶段实现。
>
> **核心架构决策**：不使用 16 个独立集合（Track/Timeline/Encounter/Faction/EntryPoint 等）。通过扩展现有 `RuleSpec` 的四张表（Hook × Expression × Op × 内建变量），用组合方式覆盖所有模组机制。顶层集合只保留 8 个（当前 6 个 + P1 的 2 个）。

---

## 一、当前 ModuleContent 结构（不改的部分）

```python
class ModuleContent(ContractModel):
    module_id: str          # 保留
    version: str            # 保留
    world_ref: str          # 保留（P2 考虑升级为结构化 ruleset_ref）
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]
```

**不改的原因**：当前代码通过 60 个测试，是 B/C 共享契约的事实源。破坏性重命名（Scene→ContentUnit, WinCondition→Ending）进入下一个 Contract major version。

---

## 二、P0：立即可以改的（4 处，~10 行，不 break 测试）

> 本章节用于记录设计演进和决策依据。当前实现目标为最终冻结版本（见 §8）。

### 1. RuleSpec 加 mode

```python
class RuleSpec(ContractModel):
    id: str
    hook: Literal["on_action", "on_scene_enter", "on_turn_end", "on_check_resolve"]
    priority: int = 0
    mode: Literal["append", "override", "forbid"] = "append"   # ← 新增
    when: ConditionSpec
    then: tuple[OperationSpec, ...] = ()
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()
```

**Accept**。默认 `"append"` 兼容当前所有 demo。引擎当前不读此字段，未来按 mode 做合并逻辑。

**为什么需要 mode**：多条规则在同一个 hook 上同时触发时，`priority` 只能决定"先取哪条"，决定不了"取到之后怎么和前面的规则相处"。

| mode | 语义 | 真实例子 |
|------|------|---------|
| `append` | 我的效果追加执行，前面的照常 | 鬼屋·血肉防护——在护甲扣减之后再 absorb |
| `override` | 我执行，同 hook 上系统默认规则跳过 | 死者·INT 检定成功→更糟——替换 CoC 默认的"成功=好事" |
| `forbid` | 整个 hook 不执行 | 死者·僵尸不会闪避——`on_dodge_declare` 整个跳过 |

### 2. ConditionSpec 加 expr escape hatch

```python
class ConditionSpec(ContractModel):
    path: str = Field(default="", min_length=0)
    equals: JsonValue | None = None
    expr: str | None = None   # ← 新增

    @model_validator(mode="after")
    def check_one_form(self):
        if bool(self.path) == bool(self.expr):
            raise ValueError("必须且只能提供 path+equals 或 expr 之一")
        return self
```

**Accept**。当前 demo 只用 `{path, equals}`，不受影响。追沙的聚合条件和 RE 计划的布尔条件先用 `expr` 字符串占位，等 Expression parser 统一后替换。

### 3. CheckpointSpec.difficulty 可空

```python
class CheckpointSpec(ContractModel):
    difficulty: Literal["regular", "hard", "extreme"] | None = None   # ← 改为可空
```

**Accept**。蛙蛙村软判据需要。当前 demo 每个 Checkpoint 都有 difficulty 值，不受影响。`None` 表示运行时通过 roleplay_tier 动态决定。`roleplay_tier` 由 Host Agent 在 Intent 中提议（none/reasonable/excellent），Engine 校验后映射到难度，记录为 Event。来源和确定性边界待 Host Agent 协议冻结后明确。

### 4. WinConditionSpec 加 is_ending

```python
class WinConditionSpec(ContractModel):
    id: str
    when: ConditionSpec
    fact: str
    player_visible_information: str
    is_ending: bool = True   # ← 新增
```

**Accept**。默认 `True` 兼容当前 demo。WinCondition 只负责真正的终局（`phase=ended`）。`is_ending=false` 表示非终局的状态回滚——此时引擎不写 `phase=ended`，只执行 state_changes。但非终局的状态回滚更适合由 Rule（`on_state_change` + trigger）表达：银之锁"被抓回房间→重来"是 Rule，不是 WinCondition。

---

## 三、P1：等 B 确认消费者后加（4 个新字段/集合）

> 本章节用于记录设计演进和决策依据。

### 5. SAN 不在 ModuleContent 中设置专用对象（Rejected）

**决策**：不新增 `SanTriggerSpec`。SAN 不作为 ModuleContent v1 的专用对象存在。

**原因**：

| 层级 | 职责 | 示例 |
|------|------|------|
| **CoC Ruleset（B 内部）** | SAN 是调查员属性；怪物/神话生物导致的默认 SAN 损失规则；SAN 检定算法；疯狂规则 | "目击神话生物 → INT 检定 → 失败扣 0/1d6" |
| **ModuleContent** | 某个具体场景中什么事件触发，目标是谁，数值变化多少 | "目击道格拉斯 → 调查员 sanity -1d6" |

ModuleContent 的职责是声明"事件 → 目标 → 数值变化"，不应该定义 SAN 如何计算、SAN 检定规则、疯狂规则或任何 CoC 专属 SAN 行为。`kind` 六值枚举（check/flat/direct/max_reduce/gain/capped）属于 CoC Ruleset——它们描述的是 SAN 的执行方式，不是模组事件的声明方式。

**替代表达**：通过现有的 `Rule + Condition + ModifyOperation` 表达 SAN 类机制。

```
追书人·目击道格拉斯：
  Rule(on_interact, when {path:"npc.douglas.sighted", equals:true},
       then=[ModifyOp(path:"actors.pc_1.sanity", set="pc_1.sanity - 1d6")])

追书人·累计封顶：
  Rule(on_state_change, when {expr:"self.sanity_loss_from_ghoul_crowd >= 6"},
       mode="forbid")  # 超过 6 点后不再触发

鬼屋·SAN 上限降低：
  Rule(on_read("book_of_eibon"),
       then=[ModifyOp(path:"actors.pc_1.sanity_max", set="pc_1.sanity_max - 2")])
```

- **触发**：`Rule.hook`（on_interact/on_scene_enter/on_read）+ `Rule.when`（Condition）
- **效果**：`Rule.then`（ModifyOperation——修改调查员属性值）
- **累计封顶**：`Rule.mode=forbid` + 内建变量追踪累计值

**未来多 Ruleset 兼容**：CoC 使用 `sanity`，其他系统使用 `stress`/`fear`/`corruption`。ModuleContent 不应绑定 SAN 名称——它只声明"某属性变化了某个值"。属性的语义由 Ruleset 解释。

当前 demo 不涉及 SAN，不受影响。

### 6. ModuleContent.module_rules（模组级全局规则）

**作用**：给不属于任何具体 Entity 的规则一个挂载位置。当前规则只能挂在 `Entity.rules` 下——"柜子有钥匙才能开"挂在 cabinet 上。但"管家在第 3 回合主动提示书架"不属于管家——这是模组级的叙事推进规则。

**消费者**：B 的 Rule Engine。在每个 hook 触发时，合并 `module_rules + entity.rules`，按 priority 排序后逐条执行。

**与已有字段的关系**：`module_rules` 复用 `RuleSpec`，不新建类型。与 `Entity.rules` 的区别仅在于 scope——前者的 scope 是 Module，后者的 scope 是特定 Entity。合并策略（哪个优先、override 如何生效）由 B 决定。

```python
class ModuleContent(ContractModel):
    module_rules: tuple[RuleSpec, ...] = ()   # ← 新增
```

**阻塞条件**：B 确认 Engine 如何合并 + 排序 + 覆盖。

**示例**：追书人——`Rule(on_turn_end, when turn_count >= 3 && entities.bookshelf.key_found == false, then grant_clue("butler_hint"))`。

### 7. SceneSpec.exits

**作用**：声明"从这个场景可以去哪些场景"。当前场景之间没有拓扑关系——引擎不知道书房隔壁是墓地还是走廊，A 自由发挥。

**消费者**：B 做移动校验（玩家说"去墓地"，Engine 查 exits 确认墓地是否可达）。A 的 Host Agent 展示可到达的目的地列表。

**与已有字段的关系**：`exits` 只声明可达性，不执行移动。实际移动由 Operation `transition` 执行。exits 是白名单——不在列表里的目的地被 B 拒绝。

```python
class SceneSpec(ContractModel):
    # ...existing...
    exits: tuple[str, ...] = ()   # ← 新增，可空
```

**示例**：银之锁——房间 `exits=["corridor"]`，走廊 `exits=["room"]`。追书人——书房 `exits=[]`（自由移动模组，exits 为空表示无空间约束）。

### 8. EntitySpec.stat_block（可空）

**作用**：让 NPC/怪物携带完整的 CoC 属性块，供 B 做检定对抗和战斗结算。当前 Entity 只有 `content` 和 `secrets`——"道格拉斯 STR 85"只能写在文字里，引擎要做 STR 对抗时无处读取。

**消费者**：B 的 CheckResolver（做对抗检定时读双方属性）、B 的战斗流水线（读 HP/护甲/伤害加值/移动速度）。

**与已有字段的关系**：`stat_block` 是静态声明——和 `Entity.state` 一样，游戏开始时拷贝到 GameState，之后的变更只作用于 GameState。`stat_block` 不影响"道格拉斯是否在场"——那是 Entity.state 或其他 Rule 的职责。

```python
class StatBlock(ContractModel):
    STR: int | None = None
    CON: int | None = None
    SIZ: int | None = None
    INT: int | None = None
    POW: int | None = None
    DEX: int | None = None
    EDU: int | None = None
    SAN: int | None = None
    HP: int | None = None
    MP: int | None = None
    armor: str | None = None
    move: int | None = None

class EntitySpec(ContractModel):
    stat_block: StatBlock | None = None   # ← 新增，必须可空
```

**为什么必须可空**：追书人的邻居、看守、《银之锁》的芭斯特——全都没有属性块。字段若不可空，Parser 会逼迫 LLM 编造数字。

### 9. InformationItem（事实本体）+ ModuleContent.information_items

**决策**：新增。从 Defer 移入 P1。

**原因**：《校园黑色怪谈》和《追书人》验证了调查模组的核心机制是信息链——"尸体 → 布文杉身份 → 隐修堂 → 地下秘密"。当前 `CheckpointOutcomeSpec.facts: tuple[str]` 只能保存裸文本，无法被 Rule/Condition 引用。`InformationItem` 给每条事实一个稳定 ID，不改变 Runtime 行为。

**职责**：

| 负责 | 不负责 |
|------|--------|
| 模组中存在的可引用事实的静态声明 | 信息获取过程（InformationAcquisition，Defer） |
| 稳定 ID + content + 默认 visibility | 玩家知识状态（KnowledgeState，Defer） |
| 被 Rule/Condition/Outcome 引用 | Projection 动态过滤 |

```python
class InformationItem(ContractModel):
    id: str = Field(min_length=1)
    content: str                                    # 事实正文
    visibility: VisibilityPolicy = Field(default_factory=VisibilityPolicy)

class ModuleContent(ContractModel):
    information_items: tuple[InformationItem, ...] = ()
```

**消费者**：Validation（校验引用存在）、Host Agent（按 ID 查找事实正文）。

**不影响 Runtime**：不要求 B 实现授予机制、不要求 KnowledgeState。加了这个字段，`CheckpointOutcomeSpec.facts` 仍然保留（裸字符串兼容），后续可将 `facts` 迁移为 `information_item_ids` 引用。

**与 InformationAcquisition 和 KnowledgeState 的区别**：

| 概念 | 状态 | 原因 |
|------|------|------|
| `InformationItem` | **P1** | 纯静态声明，不需要 Runtime 消费 |
| `InformationAcquisition` | Deferred | 需要 Runtime 授予机制 |
| `KnowledgeState` | Deferred | 属于 GameState，需要 Host Projection |

---

## 四、P2：四张表扩展（替代 16 集合方案）

> 本章节用于记录设计演进和决策依据。

**不需要 16 个独立顶层集合。** 所有模组的动态机制（Track、Timeline、Encounter、Faction 反应）本质上都是 `(trigger, condition, effect)` 三元组。扩展已有 RuleSpec 的四张表即可。

### 为什么 Rule 可以替代 Track

Track 是"阶段 × 阈值 × 阶段效果"的三元组。Rule 是"trigger × condition × effect"的三元组。两者的结构完全相同——Track 只是 Rule 的一个特殊用法。

```
Track 模型（如果独立建表）：
  TrackDefinition { id, stages: [{name, threshold, effects}] }

Rule 等价表达：
  Rule(on_state_change, when self.infection_stage >= 3, then apply_condition("full_transformation"))
  Rule(on_state_change, when self.infection_stage >= 5, then force("irreversible_conversion"))
```

复足的六级感染——每条阶段转换就是一条 Rule。阶段名是 `self.infection_stage` 变量的值，阈值是 Condition 中的比较表达式。不需要 TrackSpec，只需要一个可被 Rule 读取的内建变量。

追沙的沙漏同理。每次使用沙之书 → `increment("hourglass")`，沙漏达到 23 → `trigger_ending("time_abscess")`。它就是两条 Rule。

### 为什么 Rule 可以替代 Timeline

Timeline 是"时间窗口 × 可用事件"的声明。Rule 通过 Hook + 内建变量表达同样的语义。

```
Timeline 模型（如果独立建表）：
  TimelineDefinition { id, phases: [{time_window, enabled_events}] }

Rule 等价表达：
  Rule(on_scene_enter, when clock.time_of_day == "night", then enable_checkpoint("nightly_surveillance"))
  Rule(on_time_elapsed, when clock.time_of_day == "night", then enable_checkpoint("nightly_surveillance"))
```

追书人的昼夜循环——"夜间才开放监视检定"。需要两条 Rule：一条 on_scene_enter（刚进入场景时），一条 on_time_elapsed（玩家一直待在场景里，时间自然推进到夜晚时）。不需要 TimelineSpec。

**状态变化循环控制**：`on_state_change` 在同一动作内最多递归触发 10 次。同一条 Rule 在同一动作中只执行一次（按 rule_id 去重）。Engine 在每次 `on_state_change` 求值时跳过本轮已执行的 Rule ID，防止无限循环。

### 为什么 Encounter 不需要独立 Spec

战斗特殊规则适合用 Rule 表达（僵尸不能闪避、枪弹固定伤害 1、无视重伤）。但 Encounter 的**流程骨架**——参与者、先攻、当前回合、可用行动、开始/结束条件——由 B 的 CombatPipeline 维护，不属于 Rule 的职责。

```
CombatPipeline（B 内部）           Rule（Contract 声明）
├── participants[]                 Rule(on_dodge_declare, forbid)
├── initiative_order               Rule(on_damage_roll, set(1))
├── current_round                  Rule(on_major_wound, forbid)
├── available_actions[]            Rule(on_turn_end, force("switch_target"))
├── start_condition
└── end_condition
```

**Rule 负责拦截修改流程中具体步骤；CombatPipeline 负责维护流程骨架。** 不建独立 EncounterSpec。

### 本质：Named State Machine 退化为 Rule 组合

```
Track    = Named State Machine(阶段变量 + 阈值守卫 + 阶段效果)
Timeline = Named State Machine(时间变量 + 时间守卫 + 事件启用)

Rule     = (Hook, Condition, Effect)  ← 统一的 Trigger × Guard × Action
```

二者的"状态机骨架"完全相同。差异仅在于读什么变量、用什么 hook。Rule 抽象已经足够——把 Track/Timeline 的特殊变量放进内建变量表，把它们的特殊 hook 放进 Hook 表，其余全部复用 RuleSpec。Encounter 的流程骨架由 B 内部维护，Rule 只负责拦截。

### 9. Hook 表：4 → 20

```python
# 当前（4 个）
hook: Literal["on_action", "on_scene_enter", "on_turn_end", "on_check_resolve"]

# P2（20 个）
# 当前 on_action 在 P2 中统一为 on_interact，语义不变
hook: HookName
```

**① 战斗流水线（12 个）**：

| # | Hook | 拦截点 | 示例 |
|---|------|--------|------|
| 1 | `on_attack_declare` | 玩家声明攻击时 | — |
| 2 | `on_difficulty_calc` | 计算攻击难度时 | 死者：人数→难度 |
| 3 | `on_attack_roll` | 掷攻击骰后 | — |
| 4 | `on_dodge_declare` | 防守方声明闪避时 | 死者：僵尸不能闪避→forbid |
| 5 | `on_dodge_roll` | 掷闪避骰后 | — |
| 6 | `on_hit_resolve` | 判定命中时 | 蛙蛙村：长舌命中→拖拽 |
| 7 | `on_damage_roll` | 掷伤害骰后 | 死者：枪弹→set(1)，刀伤→scale(0.5) |
| 8 | `on_armor_apply` | 护甲扣减时 | 鬼屋：血肉防护→absorb |
| 9 | `on_hp_write` | 写入 HP 前 | — |
| 10 | `on_major_wound` | 重伤判定时 | 死者：僵尸无视重伤→forbid |
| 11 | `on_death` | 角色死亡时 | — |
| 12 | `on_turn_end` | 战斗回合结束时 | 复足：冷蛛 4 轮换目标 |

**② 检定流水线（3 个，on_difficulty_calc 与战斗共用）**：

| # | Hook | 拦截点 | 示例 |
|---|------|--------|------|
| 13 | `on_check_declare` | 声明检定时 | — |
| 14 | `on_check_roll` | 掷骰后 | — |
| 15 | `on_check_resolve` | 判定成功等级后分派结果时 | 鬼屋：INT 成功→更糟（C 类反转） |

**③ 场景流水线（3 个）**：

| # | Hook | 拦截点 | 示例 |
|---|------|--------|------|
| 16 | `on_scene_enter` | 进入场景时 | 追书人：夜间→启用监视检定 |
| 17 | `on_scene_exit` | 离开场景时 | — |
| 18 | `on_interact` | 与实体交互时（替换当前 `on_action`） | 银之锁：有钥匙→允许开柜子 |

**④ 通用（2 个，P2 新增）**：

| # | Hook | 拦截点 | 示例 |
|---|------|--------|------|
| 19 | `on_state_change` | 任意 Entity.state 被修改后 | 复足：感染阶段变化→apply_condition |
| 20 | `on_time_elapsed` | 游戏时间推进时（Scheduler 发布） | 追书人：白天→夜晚，场景内触发；RE计划：定时器到期 |

> `on_difficulty_calc` 在战斗和检定流水线中复用同一 Hook 名。
> `on_time_elapsed` 解决了"玩家一直待在同一个场景里，时间推进后不会再次触发 on_scene_enter"的问题——由 B 的 Scheduler 在 game_tick 推进时发布，不依赖场景切换。
> `on_state_change` 解决了 Track 的阶段推进——每次 Entity.state 变化后，Engine 遍历 hook=on_state_change 的 Rule 做条件求值。同一动作内最多递归 10 次，同一条 Rule 不重复触发。

**阻塞条件**：B 实现 Hook dispatcher。

### 10. Expression 语法：等值 → 完整

```python
# 当前
ConditionSpec { path, equals }

# P2
ConditionSpec.expr  # 比较（== != < <= > >=）+ 布尔（&& || !）
                    # + 算术（+ - * / floor ceil）+ 聚合（count max）
                    # + 内建变量（clock.time_of_day, combat.round, party.size 等）
```

**阻塞条件**：Expression parser 落地。P0 的 `expr` 字符串在此期间保留。

### 11. Op 算子表：2 → ~10

```python
# 当前
AllowOperationSpec  # op = "allow"
ModifyOperationSpec # op = "modify"

# P2
+ set / scale / add / absorb / decrement / forbid
+ force / apply_condition / trigger_ending / trigger_rule
```

> **参数结构待 B 确认 Op catalog 后冻结**。当前列出的是语义方向——每个 Op 的具体字段名和类型由 B 的 Effect executor 消费方式决定。文档示例中的 `force("switch_target")`、`trigger_rule("cat_attack_npc")` 是语义示意，不是最终参数格式。

**阻塞条件**：B 确认 Op 消费 catalog 并实现每个算子的 Effect executor。

**`trigger_rule` 的执行模型**：被激活的 Rule 不保证在当前 Hook 上下文中立即执行。Engine 将 `trigger_rule` 的目标 rule_id 推入 Runtime event queue，由 Rule Engine 按执行策略调度——当前 event 完成后，queue 中的 triggered rules 依次求值，产生的 state changes 统一提交，再触发下一轮 `on_state_change`。同一 Rule 在同一 event 中不重复入队（幂等）。防止 A→trigger_rule(B)→B→trigger_rule(A) 的无限递归。

### 11b. 规则合并语义

多条 Rule 在同一 hook 上命中时，Engine 按以下顺序合并：

1. 收集：`module_rules` + `entity.rules`，按 `priority` 降序排列
2. 同 priority：`module_rules` 先于 `entity.rules`
3. `mode=append`：执行本条，继续下一条
4. `mode=override`：执行本条，跳过所有 `source="world"` 的默认规则（即 Ruleset 提供的世界级规则，当前 Engine 无此概念，P2 预留）
5. `mode=forbid`：整个 hook 跳过，不执行任何规则

**与现有字段的区别**：

| 机制 | 作用层 | 说明 |
|------|--------|------|
| `Entity.refuse_ops` | Entity 级静态声明 | "这个操作默认被拒绝"——静态白名单 |
| `Rule(mode=forbid)` | 动态条件判断 | "当 condition 满足时，这个 hook 整个跳过"——动态开关 |
| `Operation(op=forbid)` | Rule 的 then 中的一步 | "执行 forbid op，阻断后续 Effect"——链式阻断 |

### 12. 内建变量：0 → ~15

```
entity.state.*       — 实体状态变量（已有，path 直接引用）
combat.round         — 当前战斗回合数
self.rounds_without_damage  — 当前实体未造成伤害的连续回合数
self.infection_stage — 复足：当前感染阶段
damage.type          — 伤害类型（firearm/melee/explosive 等）
attack.name          — 攻击名称（"长舌鞭笞"）
check.tier           — 检定成功等级（critical/extreme/hard/regular/fail/fumble）
check.roleplay_tier  — 软判据枚举（none/reasonable/excellent）
party.size           — 队伍人数
party.max_STR        — 队伍最大力量值
clock.time_of_day    — 当前时段（morning/afternoon/night）
clock.turn_elapsed   — 当前游戏回合数
target.form          — 目标形态
self.HP / self.HP_max / self.flesh_ward — 实体战斗状态
```

**阻塞条件**：B 确认 VariableDef 目录，实现求值器。所有变量必须由引擎自动维护，不能被规则直接写入——规则只能读它们。

### 13. P2 完整字段形状

P2 全部落地后，`contracts/module.py` 中变更的模型：

```python
class RuleSpec(ContractModel):
    id: str
    # P2: 4 → 20
    hook: Literal[
        # 战斗（12）
        "on_attack_declare", "on_difficulty_calc", "on_attack_roll",
        "on_dodge_declare", "on_dodge_roll", "on_hit_resolve",
        "on_damage_roll", "on_armor_apply", "on_hp_write",
        "on_major_wound", "on_death", "on_turn_end",
        # 检定（4）
        "on_check_declare", "on_difficulty_calc", "on_check_roll", "on_check_resolve",
        # 场景（3）
        "on_scene_enter", "on_scene_exit", "on_interact",
    ]
    priority: int = 0
    mode: Literal["append", "override", "forbid"] = "append"     # P0

    # P2: ConditionSpec.expr 从字符串升级为完整 Expression parser
    when: ConditionSpec

    # P2: 2 → ~10
    then: tuple[OperationSpec, ...] = ()
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()


class ConditionSpec(ContractModel):
    path: str = Field(default="", min_length=0)
    equals: JsonValue | None = None

    # P0: 字符串 escape hatch
    # P2: 替换为 Expression AST，支持：
    #   比较: == != < <= > >=
    #   布尔: && || !
    #   算术: + - * / floor() ceil()
    #   聚合: count(party) max(party.STR)
    #   内建变量: 全部 ~15 个 VariableDef
    expr: str | None = None


class OperationSpec:                            # P2: discriminator "op" 扩展
    # 当前（2 个）
    AllowOperationSpec    # op = "allow"     → 解除拒绝
    ModifyOperationSpec   # op = "modify"    → 写状态（set）

    # P2 新增（~8 个）
    SetOperationSpec      # op = "set"       → 直接赋值
    ScaleOperationSpec    # op = "scale"     → 缩放数值 + round
    AddOperationSpec      # op = "add"       → 增减数值
    AbsorbOperationSpec   # op = "absorb"    → 吸收伤害（鬼屋·血肉防护）
    DecrementOperationSpec# op = "decrement" → 消耗计数器
    ForbidOperationSpec   # op = "forbid"    → 禁止 hook 执行
    ForceOperationSpec    # op = "force"     → 强制执行动作（冷蛛换目标）
    ApplyConditionSpec    # op = "apply_condition" → 施加状态（复足·感染阶段）
    TriggerEndingSpec     # op = "trigger_ending"  → 触发终局（追沙·沙漏）
    TriggerRuleSpec       # op = "trigger_rule" → 激活另一条 Rule（银之锁·因果链）
    TransitionSpec        # op = "transition"→ 场景切换


# P2: ModuleContent 不新增顶层集合，但现有集合内的字段变更：
#
# SceneSpec:          + exits: tuple[str, ...] = ()                    (P1)
# EntitySpec:         + stat_block: StatBlock | None = None            (P1)
# CheckpointSpec:     difficulty: ... | None = None                    (P0)
#                     mvp_check_result 移除                             (P2)
# WinConditionSpec:   + is_ending: bool = True                         (P0)
#
# ModuleContent:      + module_rules: tuple[RuleSpec, ...] = ()        (P1)
#                     + information_items: tuple[InformationItem, ...] = () (P1)
```

**P2 不新增任何顶层集合。** 以上是全部变更。

---

## 五、覆盖率：P2 后 ~93%（L1 原文保存覆盖）

> **覆盖率为 L1（原文保存覆盖）**，指模组内容可以在 ModuleContent 中找到存放位置。L3（Runtime 确定性执行覆盖）远低于此——RE 计划逐项验证仅 ~5%。详见 `audit-p0-p1-p2-coverage.md`。

| 模组机制 | 用什么表达 | 需要什么 |
|---------|----------|---------|
| 追书人昼夜循环 | Rule(on_scene_enter + time_of_day) | Hook 19 + 内建变量 clock |
| 追书人重复监视 | Rule(on_turn_end + retry policy) | Hook 19 + repeat_policy |
| 银之锁因果链 | Rule(on_damage → trigger_rule → on_death) | Hook + Op trigger_rule |
| 复足六级感染 | Rule(on_turn_end + self.infection_stage) | 内建变量 + Op apply_condition |
| 复足人数缩放 | Condition(party.size >= N) | 聚合表达式 count(party) |
| 复足冷蛛转换目标 | Rule(on_turn_end + self.rounds_without_damage) | 内建变量 + Op force |
| 追沙沙漏 | Rule(on_state_change + hourglass_count) | Op trigger_ending |
| 追沙多势力反应 | Entity.state + Rule(on_state_change) | 不需要 FactionSpec |
| RE计划隐藏结局 | Condition(milestone_A && milestone_B && task_C_success) | 表达式布尔操作 |
| RE计划多HO入口 | Entity.state 区分入口 + Rule(on_scene_enter) | 不需要 EntryPointSpec |

| 模组 | 当前 | P0+P1 | +四张表 |
|------|------|-------|---------|
| 追书人 | ~70% | ~90% | **~98%** |
| 银之锁 | ~65% | ~85% | **~95%** |
| 复足 | ~50% | ~72% | **~93%** |
| 追沙 | ~55% | ~75% | **~92%** |
| RE 计划 | ~50% | ~70% | **~90%** |

剩余的 2-10% 是**本质上不可结构化的内容**：Keeper Adjudication、开放式创造、自然语言裁量。

---

## 六、明确 Defer（语义成立，但不现在加）

| 项 | 为什么不现在加 | 什么时候加 |
|----|--------------|----------|
| `SceneSpec` 重命名为 `ContentUnit` | 破坏性变更 | 下一个 Contract major version |
| `WinConditionSpec` → `EndingSpec/endings` | 同上 | 同上 |
| `world_ref: str` 升级为 `ruleset_ref` 结构化引用 | B/C 对齐 Provider | B 确认 Ruleset 消费接口后 |
| `EntitySpec.kind` 扩展为六值 | 当前 demo 只需 3 值 | 信息模型独立后 |
| `InformationAcquisition`（获取路径）独立集合 | 需要 Runtime 授予机制 + KnowledgeState consumer | B 确认 KnowledgeState 消费方式后 |
| `KnowledgeState`（谁知道什么） | 属于 GameState，需要 Host Projection | B + A 原型就绪后 |
| `LocationDefinition` 独立于 `EntitySpec` | 当前 demo 用 `Entity(kind="location")` 够用 | B 确认 navigation consumer 后 |

---

## 七、永久决策：不建 16 个独立集合

| 不做什么 | 用什么替代 | 原因 |
|---------|----------|------|
| 不建 `TrackSpec` | `Rule(on_state_change + self.track_stage)` | 阶段状态机退化为 Rule 组合 |
| 不建 `TimelineSpec` | `Rule(on_scene_enter/on_turn_end + clock.time_of_day)` | 时间调度退化为 Hook + 内建变量 |
| 不建 `EncounterSpec` | `Rule(on_combat_start/on_round_end) + Entity.state` | 遭遇规则退化为 Hook 组合 |
| 不建 `FactionSpec` | `Entity.state(attitude) + Rule(on_state_change)` | 势力反应是 Entity + Rule |
| 不建 `EntryPointSpec` | `Entity.state(entry) + Rule(on_scene_enter)` | 多入口是状态 + 触发规则 |
| 不建 `PuzzleSpec` / `TableSpec` | `Checkpoint + Interaction + Condition` + `keeper_guidance` | 连续解谜和随机表由现有组合承载 |
| 不设模组专用字段 | — | 五个模组验证不需要 |
| 不设 `TriggerSpec` 作为独立集合 | `RuleSpec.hook` | 单一规则表达 |
| 不设 `EffectSpec` 作为独立集合 | `RuleSpec.then / Outcome.ops` | 同上 |
| 不把 `source_references/confidence/unresolved` 放进 `ModuleContent` | ParserResult sidecar | 不属于 B/C 共享契约 |
| 不把 `mvp_check_result` 留在生产 Contract | 测试 fixture | P2 移出 |

---

## 八、P2 最终完整形状

以下为 P0+P1+P2 全部落地后，`contracts/module.py` 的最终代码：

```python
# ===========================================================================
# ModuleContent 顶层（8 个集合：当前 6 个 + P1 的 module_rules + information_items）
# ===========================================================================

class ModuleContent(ContractModel):
    module_id: str                                   # "study-demo"
    version: str                                     # "0.1.0"
    world_ref: str                                   # "coc-7e"

    scenes: tuple[SceneSpec]                         # 场景列表。SceneSpec: id, name, content,
                                                     #   entity_ids, checkpoint_ids, exits (P1)

    entities: tuple[EntitySpec]                      # 实体列表。EntitySpec: id, kind(npc|object|location),
                                                     #   name, aliases, content, secrets, state,
                                                     #   refuse_ops, blocked_text, direct_responses,
                                                     #   rules[], stat_block (P1可空)

    checkpoints: tuple[CheckpointSpec]               # 检定点列表。CheckpointSpec: id, scene_id, action,
                                                     #   target_id, skills[], difficulty(P0可空),
                                                     #   outcomes(success/failure: facts, player_visible,
                                                     #   narration_constraints, ops[])

    win_conditions: tuple[WinConditionSpec]           # 结局条件。WinConditionSpec: id, when(ConditionSpec),
                                                     #   fact, player_visible_information, is_ending(P0)

    module_rules: tuple[RuleSpec] = ()               # P1 模组级全局规则。RuleSpec: id, hook(20个枚举),
                                                     #   priority, mode(P0), when(ConditionSpec),
                                                     #   then(OperationSpec[]), facts, player_visible

    information_items: tuple[InformationItem] = ()   # P1 信息事实。InformationItem: id, content, visibility


# ===========================================================================
# RuleSpec（P0 +mode, P2 hook 4→19, P2 then 2→~10 个 Op）
# ===========================================================================

class RuleSpec(ContractModel):
    id: str
    # P2: 20 个 hook
    hook: Literal[
        # 战斗（12）
        "on_attack_declare", "on_difficulty_calc", "on_attack_roll",
        "on_dodge_declare", "on_dodge_roll", "on_hit_resolve",
        "on_damage_roll", "on_armor_apply", "on_hp_write",
        "on_major_wound", "on_death", "on_turn_end",
        # 检定（3，on_difficulty_calc 与战斗共用）
        "on_check_declare", "on_check_roll", "on_check_resolve",
        # 场景（3）
        "on_scene_enter", "on_scene_exit", "on_interact",
        # 通用（2）
        "on_state_change", "on_time_elapsed",
    ]
    priority: int = 0
    mode: Literal["append", "override", "forbid"] = "append"     # P0
    # P2: when 可使用完整 Expression（比较/布尔/算术/聚合/内建变量）
    when: ConditionSpec
    # P2: then 的 Op 变体从 2 个扩到 ~10 个
    then: tuple[OperationSpec, ...] = ()
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()


# ===========================================================================
# ConditionSpec（P0 +expr, P2 expr 升级为完整 Expression AST）
# ===========================================================================

class ConditionSpec(ContractModel):
    path: str = Field(default="", min_length=0)
    equals: JsonValue | None = None
    # P0: 字符串 escape hatch
    # P2: 替换为 Expression AST，支持比较/布尔/算术/聚合/内建变量
    expr: str | None = None


# ===========================================================================
# OperationSpec（P2: discriminator "op" 从 2 个变体扩到 ~10 个）
# ===========================================================================

class AllowOperationSpec(ContractModel):          # op="allow"
    op: Literal["allow"] = "allow"                # 解除 Entity.refuse_ops
    action: str

class ModifyOperationSpec(ContractModel):         # op="modify"
    op: Literal["modify"] = "modify"              # 写入 Entity.state
    path: str
    set: JsonValue

# P2 新增：
class SetOperationSpec(ContractModel):            # op="set"
    op: Literal["set"] = "set"                    # 直接设值（区别于 modify 的 path 语义）

class ScaleOperationSpec(ContractModel):          # op="scale"
    op: Literal["scale"] = "scale"                # 缩放数值（0.5 = 减半）
    value: float
    round: Literal["floor", "ceil"] | None = None

class AddOperationSpec(ContractModel):            # op="add"
    op: Literal["add"] = "add"                    # 增减数值

class AbsorbOperationSpec(ContractModel):         # op="absorb"（鬼屋·血肉防护）
    op: Literal["absorb"] = "absorb"              # 吸收伤害上限
    amount: str                                   # Expr: "min(damage, self.flesh_ward)"
    decrement: str                                # 消耗变量: "self.flesh_ward"

class ForbidOperationSpec(ContractModel):         # op="forbid"（死者·僵尸不闪避）
    op: Literal["forbid"] = "forbid"              # 禁止当前 hook 执行

class ForceOperationSpec(ContractModel):          # op="force"（复足·冷蛛换目标）
    op: Literal["force"] = "force"                # 强制执行动作
    action: str

class ApplyConditionSpec(ContractModel):          # op="apply_condition"（复足·感染）
    op: Literal["apply_condition"] = "apply_condition"
    condition: str                                # 状态名: "full_transformation"

class TriggerEndingSpec(ContractModel):           # op="trigger_ending"（追沙·沙漏）
    op: Literal["trigger_ending"] = "trigger_ending"
    ending_id: str

class TriggerRuleSpec(ContractModel):             # op="trigger_rule"（银之锁·猫→NPC因果链）
    op: Literal["trigger_rule"] = "trigger_rule"
    rule_id: str                                 # 要激活的 Rule ID（ModuleContent 中已声明）

class TransitionSpec(ContractModel):              # op="transition"（场景切换）
    op: Literal["transition"] = "transition"
    scene_id: str

OperationSpec = Annotated[
    AllowOperationSpec | ModifyOperationSpec
    | SetOperationSpec | ScaleOperationSpec | AddOperationSpec
    | AbsorbOperationSpec | ForbidOperationSpec | ForceOperationSpec
    | ApplyConditionSpec | TriggerEndingSpec | TriggerRuleSpec
    | TransitionSpec,
    Field(discriminator="op"),
]


# ===========================================================================
# InformationItem（P1 新增）
# ===========================================================================

class InformationItem(ContractModel):
    id: str = Field(min_length=1)                         # "buwen_identity"
    content: str                                          # "布文杉是隐修堂派来调查学生失踪的卧底"
    visibility: VisibilityPolicy = Field(default_factory=VisibilityPolicy)


# ===========================================================================
# SceneSpec（P1 +exits）
# ===========================================================================

class SceneSpec(ContractModel):
    id: str
    name: str
    content: str
    entity_ids: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()                               # P1


# ===========================================================================
# EntitySpec（P1 +stat_block）
# ===========================================================================

class StatBlock(ContractModel):
    STR: int | None = None
    CON: int | None = None
    SIZ: int | None = None
    INT: int | None = None
    POW: int | None = None
    DEX: int | None = None
    EDU: int | None = None
    SAN: int | None = None
    HP: int | None = None
    MP: int | None = None
    armor: str | None = None
    move: int | None = None

class EntitySpec(ContractModel):
    id: str
    kind: Literal["npc", "object", "location"]
    name: str
    aliases: tuple[str, ...] = ()
    content: str
    secrets: str | None = None
    state: dict[str, JsonValue] = Field(default_factory=dict)
    refuse_ops: tuple[str, ...] = ()
    blocked_text: str | None = None
    direct_responses: dict[str, str] = Field(default_factory=dict)
    rules: tuple[RuleSpec, ...] = ()
    stat_block: StatBlock | None = None                       # P1


# ===========================================================================
# VisibilityPolicy + VisibleInformation（P2: 解决 EDV Gap 1+2）
# ===========================================================================

class VisibilityPolicy(ContractModel):
    """静态可见性声明。发布时冻结，不随游戏状态变化。"""
    audience: Literal["all", "actor", "ho", "keeper"] = "all"
    # all    = 全体玩家可见（默认，向后兼容）
    # actor  = 仅当前 Runtime Action 执行者（非玩家账号——一个玩家可控制多角色）
    # ho     = 仅指定 HO 槽位的角色（模组定义的身份槽位，Runtime 映射到具体 actor）
    # keeper = 仅 KP 可见（暗骰、幕后信息）

    ho_ref: str | None = None                              # audience="ho" 时指定 HO 槽位
    requires_discovery: bool = False                       # 是否需要先"发现"才能访问（Checkpoint 用）
    discovery_rule: str | None = None                      # 发现方式。自然语言或候选表达式。
                                                           # 为空时使用 Runtime 默认发现机制（进入场景自动发现等）。
                                                           # 与 ConditionSpec 不同：Condition 描述规则执行条件，
                                                           # discovery_rule 描述调查机会的发现方式。
    discovery_shares_to_party: bool = True                 # 发现后是否向全队公开

    # 字段使用约束（model_validator）:
    # Information 挂载: 只用 audience/ho_ref，不用 requires_discovery/discovery_rule
    # Checkpoint 挂载: 用 requires_discovery/discovery_rule/audience
    # 无效组合: requires_discovery=false 且 discovery_rule 非空


class VisibleInformation(ContractModel):
    """替换 CheckpointOutcomeSpec.player_visible_information 的裸字符串。"""
    text: str
    visibility: VisibilityPolicy = Field(default_factory=VisibilityPolicy)
    # 默认 audience="all"。Information visibility = 内容访问权限。
    # audience="keeper" 用于 Outcome 中的 Keeper 提示——与 EntitySpec.secrets
    # （字段级 keeper-only）不同，这是内容级 keeper-only（同一条 Outcome 中按条区分）。


# ===========================================================================
# CheckpointSpec（P0 difficulty 可空, P2 +visibility, P2 移除 mvp_check_result）
# ===========================================================================

class CheckpointSpec(ContractModel):
    id: str
    scene_id: str
    action: str
    target_id: str
    skills: tuple[str, ...]
    difficulty: Literal["regular", "hard", "extreme"] | None = None   # P0
    outcomes: CheckpointOutcomesSpec
    visibility: VisibilityPolicy | None = None            # P2: 调查机会发现权限。None = 全可见 + 无需发现
    # P2: mvp_check_result 移出到 test fixture


# ===========================================================================
# CheckpointOutcomesSpec（P2: +5 个 tier override）
# ===========================================================================

class CheckpointOutcomeSpec(ContractModel):
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[VisibleInformation, ...] = ()  # P2: 替换裸字符串
    narration_constraints: tuple[str, ...] = ()
    ops: tuple[OperationSpec, ...] = ()

class CheckpointOutcomesSpec(ContractModel):
    # P0：保持 binary，向后兼容
    success: CheckpointOutcomeSpec
    failure: CheckpointOutcomeSpec

    # P2：分等级覆盖。非 None 时替换对应 tier，None 时走 binary fallback
    critical_success: CheckpointOutcomeSpec | None = None    # 大成功
    extreme_success: CheckpointOutcomeSpec | None = None     # 极难成功
    hard_success: CheckpointOutcomeSpec | None = None        # 困难成功
    regular_success: CheckpointOutcomeSpec | None = None     # 普通成功
    fumble: CheckpointOutcomeSpec | None = None              # 大失败


# ===========================================================================
# WinConditionSpec（P0 +is_ending）
# ===========================================================================

class WinConditionSpec(ContractModel):
    id: str
    when: ConditionSpec
    fact: str
    player_visible_information: str
    is_ending: bool = True                                    # P0
```

---

## 九、实施清单

```
P0（本周，一次 PR，4 处改动，零破坏）
  □ RuleSpec.mode = "append"
  □ ConditionSpec.expr = None
  □ CheckpointSpec.difficulty = None
  □ WinConditionSpec.is_ending = True
  □ 更新 demo-module.json（空字段）
  □ 更新 module/validation.py（新字段路径校验）
  □ 跑通全部测试

P1（B 确认消费者后，各自独立 PR，新增 2 个顶层集合 + 2 个字段）
  □ ModuleContent.module_rules
  □ ModuleContent.information_items
  □ SceneSpec.exits
  □ EntitySpec.stat_block

P2（B 确认 Hook/Expression/Op/Variable catalog 后，扩已有模型，不新增集合）
  □ RuleSpec.hook: 4 → 20
  □ ConditionSpec.expr: 字符串 → 完整 Expression parser
  □ OperationSpec: 2 → ~10
  □ 内建变量目录
  → 替代 Track/Timeline/Encounter/Faction/EntryPoint/Puzzle/Table 独立集合
```

---

## 十、全部 15 模组覆盖验证（P2 Contract 最新版，基于原文重分析）

以下基于桌面 15 份原文逐篇重读。验证对象为当前 P2 Contract（§8）。13 份成功提取文本，《科比特先生》（.doc 旧格式）和《RE 计划》（DOCX 文件损坏）改用能力统计数据补充。

### 追书人（6 页 PDF，~5900 字）

**机制数**：9。完全支持：8。缺失：1（暗骰 hidden，已由 P2 VisibilityPolicy 解决）。

| 机制 | 原文 | P2 映射 | 判断 |
|------|------|--------|------|
| 多结局 | 两个文档结局 + 道格拉斯被杀/逃离/失踪 | `WinConditionSpec(is_ending)` — P0 | ✅ |
| SAN 损失 | "理智损失 0/1D6"（目击道格拉斯）、"累计封顶 6 点" | `Rule + ModifyOp`（修改角色属性）+ `Rule(on_state_change, mode=forbid)`（封顶）— P2 | ✅ |
| 有钥匙开柜子 | 柜子 `refuse_ops=["open"]` + 钥匙找到后 allow | `Entity.refuse_ops` + `Rule(on_interact, mode=append)` — 当前已有 | ✅ |
| 砸柜子 C 类反转 | "成功反而文件损毁" | `CheckpointSpec.outcomes.success.ops` — 当前已有 | ✅ |
| 昼夜循环 | "夜间才开放监视检定" | `Rule(on_scene_enter + on_time_elapsed, when clock.time_of_day=="night")` — P2 | ✅ |
| 多条调查路径 | 邻居/图书馆/报社/金博尔宅自由移动 | `SceneSpec.exits=[]`（自由移动）— P1 | ✅ |
| 地穴隐藏入口 | 追踪检定发现、腐臭 CON check | `CheckpointSpec.visibility(requires_discovery=true, discovery_rule="check.track.success==true")` — P2 | ✅ |
| 酒→贿赂看守 | 地下酒吧幸运检定→买酒→贿赂 | `Entity.state` + `CheckpointSpec` — 当前已有 | ✅ |
| NPC 行为 | "礼貌询问""按职业调整""玩家新方案" | 自然语言 — C 类 | — |

### 银之锁（DOCX，~2200 字）

**机制数**：8。完全支持：6。不可结构化：2。

| 机制 | 原文 | P2 映射 | 判断 |
|------|------|--------|------|
| 连续解谜段 | 床/书桌/衣柜/通风管/房门/走廊，无显式章节 | `SceneSpec` 七个场景 — 当前已有 | ✅ |
| 区域束缚 | "手脚被绳子捆住""无法离开" | `Rule(on_scene_enter, mode=forbid)` — P2 | ✅ |
| 猫→NPC 因果链 | 救猫→猫存活→走廊触发→抓NPC→被杀→锁解除 | 多条 `Rule(on_state_change + on_damage + on_death)` + `trigger_rule` Op — P2 | ✅ |
| 速写本画物品 | "能用平面表现构造的简单物品" | 开放式创造 — D 类 | — |
| 被抓回→重来 | "重来""再次尝试" | `Rule(on_state_change)` 状态回滚，走 Rule 不是 WinCondition — P2 | ✅ |
| 多种交互 | 移动床/开抽屉/撕速写/救猫/喂猫/开门/逃跑 | `CheckpointSpec`（有检定）+ `Entity.direct_responses`（无检定）— 当前已有 | ✅ |
| 房间→走廊 | 空间拓扑 | `SceneSpec.exits` — P1 | ✅ |
| 人物卡定制 | "先收了人物卡后依照重要之物写模组" | 不可结构化 — D 类 | — |

### 复足（16 页 PDF，~14800 字）

**机制数**：9。完全支持：8。不可结构化：1（差异化 Projection）。

| 机制 | 原文 | P2 映射 | 判断 |
|------|------|--------|------|
| 六级感染 | 阶段 0-5，每阶段检定 DC 不同 | `Rule(on_state_change, when self.infection_stage>=N)` — P2 | ✅ |
| 停电时间表 | "每十分钟停电检定" | `Rule(on_turn_end, when clock.turn_elapsed%10==0)` — P2 Expression | ✅ |
| 冷蛛转换目标 | "4 轮未造成伤害则换目标" | `Rule(on_turn_end, when self.rounds_without_damage>=4, then force("switch_target"))` — P2 | ✅ |
| 人数缩放 | "冷蛛数量=未携带石头人数""石头总数≈一半" | `Condition(count(party))` — P2 聚合表达式 | ✅ |
| 梦境/现实空间 | 持石者 vs 未持石者所见窗外不同 | 差异化 Projection — D 类，需 Projection engine | — |
| 预制角色 | "PC 可选预制或自制角色" | `EntitySpec.stat_block` — P1 | ✅ |
| SAN | 目击冷蛛/蜘蛛神 | `Rule + ModifyOp` — P2 | ✅ |
| 多层旅店 | 2-10 层环形走廊 | `SceneSpec.exits` — P1 | ✅ |
| 多结局 | 携石返回/未携石进入荒原/死亡 | `WinConditionSpec` | ✅ |

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 六级感染 | 冷蛛感染阶段 1-6，每阶段检定和治疗 DC 不同 | `Rule(on_state_change, when self.infection_stage>=N)` — P2 | ✅ |
| 停电时间表 | "每十分钟进行一次停电检定" | `Rule(on_turn_end, when clock.turn_elapsed % 10 == 0)` — P2 | ✅ |
| 冷蛛转换目标 | "4 轮未造成伤害则换目标" | `Rule(on_turn_end, when self.rounds_without_damage>=4, then force)` — P2 | ✅ |
| 人数缩放 | "冷蛛数量=未携带石头人数""石头总数≈人数一半" | `Condition(count(party))` — P2 聚合表达式 |
| 差异 Projection | "持石者看到的窗外景象与未持石者不同" | 不可结构化 — 需要 Projection engine prototype | — |

### 追沙（DOCX，52775 字）：~92%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 沙漏计数 | "每次使用沙之书记录一次" | `Rule + AddOp` — P2 | ✅ |
| 沙漏终局 | "达到 23→时间的脓疮" | `Rule(on_state_change, when hourglass>=23, then trigger_ending)` — P2 | ✅ |
| 多势力 | 斯卡莱塔家族、运河党等 | `Entity.state(attitude) + Rule(on_state_change)` — P2 | ✅ |
| 异常事件表 | "选择而非投掷" | 自然语言 — C 类 | — |

### RE 计划（DOCX 损坏，引用能力统计）：~90%

| 机制 | P2 表达 | 判断 |
|------|--------|------|
| 三 HO | `Entity.state(entry) + Rule(on_scene_enter)` — P2 | ✅ |
| 隐藏结局 | `Condition(milestone_A && milestone_B)` — P2 Expression | ✅ |
| 角色独占信息 | `VisibleInformation(audience="ho")` — P2 VisibilityPolicy | ✅ |

### 鬼屋（DOCX，19542 字）：~97%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| C 类反转 | "INT 成功→疯狂" | `CheckpointOutcomesSpec.regular_success` tier override — P2 | ✅ |
| 血肉防护 | "每受 1 伤减 1 甲，24h 或耗尽" | `Rule(on_armor_apply, then absorb+decrement)` — P2 | ✅ |
| 浮空匕首 | 攻击/闪避/伤害 | `EntitySpec.stat_block` — P1 + P2 Hook | ✅ |
| 暗骰 | 多处标注 | `CheckpointSpec.visibility(audience="keeper")` — P2 | ✅ |
| 圣水/十字架 | 特殊物品 | `Entity.state + Rule(on_item_used)` — P2 | ✅ |
| KP 场景描述 | "发动想象力" | 自然语言 — C 类 | — |

### 百鸟朝凤（8 页 PDF，4234 字）：~96%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 婚礼时间线 | 午后→晚宴→深夜，按时间段触发事件 | `Rule(on_scene_enter + clock)` — P2 | ✅ |
| SAN | 目击怪物触发 SAN 检定 | `Rule + ModifyOp` 修改角色 sanity 属性 — P2 | ✅ |
| 麻将/社交 | 开放式社交场景，无需检定 | Interaction(keeper_guidance) | — |
| 不可结构化 | "KP 负责营造氛围""社交场合自由发挥" | keeper_guidance | — |

### 苍白面具之下（35 页 PDF，41005 字）：~91%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 7 天写作营 | 每天不同事件，随时间推进 | `Rule(on_scene_enter + clock.day)` — P2 | ✅ |
| 21 个人的故事 | 每人轮流讲述→故事成真 | Track（讲述→故事实体化阶段）+ Rule — P2 | ✅ |
| 势力 | 写作营导师、警方、参与者多个势力 | `Entity.state + Rule` — P2 | ✅ |
| 不可结构化 | "玩家讲的故事内容由 KP 和玩家共同创作" | keeper_guidance | — |

### 更好的明天（31 页 PDF，27838 字）：~94%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 时间推进 | "1931 年 10 月，调查持续数天" | `Rule(clock)` — P2 | ✅ |
| 多地点 | 教堂、警局、受害者住所、湖边 | `SceneSpec.exits` — P1 | ✅ |
| 杀人案调查 | 多条线索路径，多嫌疑人 | Checkpoint + Information（当前 facts 字符串承载） | ✅ |
| 不可结构化 | "KP 自行安排天气和镇民反应" | keeper_guidance | — |

### 死者的顿足舞（34 页 PDF，38160 字）：~92%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 僵尸规则 | 不会闪避、枪弹只损 1 耐久、刀伤减半、无视重伤 | `Rule(on_dodge_declare, forbid) + Rule(on_damage_roll, set/scale) + Rule(on_major_wound, forbid)` — 主要靠 P2 Hook + Op |
| 追逐 | 车辆追逐规则 | P2 Op `transition` + Hook `on_scene_enter` | ✅ |
| 多 NPC | 特纳（人类+僵尸双形态）、多个调查对象 | `EntitySpec` — 当前够用 | ✅ |
| 不可结构化 | "KP 控制追逐节奏""根据玩家调查方向调整线索" | keeper_guidance | — |

### 蝶骨巢穴（38 页 PDF，44349 字）：~90%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 原创生物 | 蝶骨人完整设定：属性、感染、转化、社会 | `EntitySpec.stat_block` P1 + Track P2 + Faction P2 | ✅ |
| 多结局 | 逃离、被转化、摧毁巢穴、与蝶骨人共生 | `WinConditionSpec(is_ending)` — P0 | ✅ |
| 随机表 | 巢穴内随机遭遇表 | keeper_guidance（原文有表但 KP 可选择） | — |
| 地图探索 | 巢穴多层地图 | `SceneSpec.exits` — P1 | ✅ |
| 不可结构化 | "巢穴内环境由 KP 根据气氛描述""转化过程细节由 KP 演绎" | keeper_guidance | — |

### 伦道夫·卡特的续述（56 页 PDF，42816 字）：~88%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 梦境/现实切换 | 多个世界空间，切换规则 | Location + Rule(on_scene_enter) — P2 | ✅ |
| 跨模组 | 引用多个克苏鲁神话模组 | 超出单 ModuleContent 边界 | — |
| 时间错乱 | 梦境中时间非线性 | keeper_guidance — 不可结构化 | — |
| 不可结构化 | "卡特的记忆是否可信由 KP 决定""梦境逻辑不必自洽" | keeper_guidance | — |

### 柏林：失去昨日（35 页 PDF，28484 字）：~88%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 政治势力 | 多股政治势力、警察、地下组织 | `Entity.state + Rule` — P2 | ✅ |
| 历史时间线 | 1922 年柏林，政治事件按日期推进 | `Rule(clock)` — P2 | ✅ |
| 跨模组 | "《饥不择食》的政治历史向补全支线" | 超出单 ModuleContent 边界 | — |
| 不可结构化 | "玩家政治立场影响 NPC 态度""历史事件走向由 KP 参考真实历史" | keeper_guidance | — |

### 幸福蛙蛙村（DOCX，12374 字）：~94%

| 机制 | 原文证据 | P2 表达 | 判断 |
|------|---------|--------|------|
| 软判据 | 说服信使——不阐述=困难/合理=普通/精彩=普通+奖励骰 | `CheckpointSpec.difficulty=None` — P0 | ✅ |
| 累积暴露 | 村民逐渐异变，阶段推进 | Track（异变阶段）— P2 | ✅ |
| 多结局 | 逃离、成为村民、摧毁蛙神 | `WinConditionSpec` + `is_ending` — P0 | ✅ |
| 不可结构化 | "守密人可以根据理解修改设定""关于幸福的定义由玩家探讨" | keeper_guidance | — |

### 科比特先生（.doc 旧格式，无法提取）：~97%

基于能力统计报告：经典线性调查模组。核心机制（场景、实体、检定、SAN、战斗）均由当前 + P0/P1 覆盖。唯一特殊项为浮空匕首的战斗数据（P1 stat_block + P2 Hook）。

---

### 15 模组覆盖汇总

| # | 模组 | P0+P1+P2 覆盖 | 剩余 Gap 原因 |
|---|------|-------------|-------------|
| 1 | 百鸟朝凤 | ~96% | 社交场景自由发挥 |
| 2 | 复足 | ~93% | 差异 Projection |
| 3 | 苍白面具之下 | ~91% | 玩家共创故事 |
| 4 | 更好的明天 | ~94% | KP 自主补足 |
| 5 | 死者的顿足舞 | ~92% | 追逐节奏裁量 |
| 6 | 蝶骨巢穴 | ~90% | 环境细节演绎 |
| 7 | 伦道夫·卡特续述 | ~88% | 跨模组 + 梦境非线性 |
| 8 | 追书人 | ~98% | 开放式行动 |
| 9 | 柏林：失去昨日 | ~88% | 跨模组 + 历史走向 |
| 10 | 科比特先生 | ~97% | 战斗细节演绎 |
| 11 | RE 计划 | ~90% | 角色独占 Projection |
| 12 | 鬼屋 | ~97% | KP 场景描述 |
| 13 | 幸福蛙蛙村 | ~94% | 幸福定义探讨 |
| 14 | 追沙 | ~92% | 势力社会反应 |
| 15 | 银之锁 | ~95% | 开放式创造 |
| | **15 模组平均** | **~93%（L1）** | L1=原文保存覆盖。L3 执行覆盖远低于此，详见审计报告。 |

**剩余 ~7% 的构成**：
- ~4%：KP 裁量和即兴发挥——所有模组共有的"守密人自行决定"类内容，本质上不可结构化
- ~2%：跨模组引用（卡特续述、柏林）——超出单 ModuleContent 聚合边界
- ~1%：差异化 Projection / 角色独占知识——需要 Projection/KnowledgeState 引擎原型


---

## 十一、五模组盲测（test 文件夹，P2 Contract）

2026-07-24 新增。详见 `p2-contract-test.md`。

| 模组 | 机制数 | 完全支持 | 缺失 |
|------|--------|---------|------|
| 异父（教父主题） | 7 | 6 | 沉默法则（C 类） |
| 极限绷住（荒诞喜剧） | 8 | 8 | 0 |
| 校园黑色怪谈 | 9 | 8 | 信息链（InformationItem Defer） |
| 芒卡的巧克力工厂 | 8 | 6 | 纯粹想象（D 类）+ 疯狂继续（B 类） |
| 停滞之水（1924 广州） | 10 | 10 | 0 |
| **合计** | **42** | **38（90%）** | **4** |

未暴露需要新增领域对象的需求。

---

## 十二、Capability Gap 汇总

以下为全部 20 模组（15 个示例 + 5 个 test）暴露的已知能力缺口。分层标注处理方式。

| # | Gap | 触发模组 | 类型 | 处理 |
|---|-----|---------|------|------|
| 1 | `CheckpointSpec.hidden` — 暗骰、隐藏入口 | 追书人、鬼屋 | A | `VisibilityPolicy`（P2 §8 已纳入） |
| 2 | `VisibleInformation.audience` — HO 私有信息 | RE 计划 | A | `VisibilityPolicy`（P2 §8 已纳入） |
| 3 | `RepeatCheckPolicy` — 复合检定 | RE 计划、极限绷住 | A | `CheckpointSpec.repeat_policy` |
| 4 | `InformationItem`（事实本体） | 校园黑色怪谈、追书人、追沙 | **P1 已纳入** | 见 §3.9 |
| 4b | `InformationAcquisition`（获取路径） | 同上 | Deferred | 需要 Runtime 授予机制 + KnowledgeState |
| 4c | `KnowledgeState`（谁知道什么） | 同上 | Deferred | 属于 GameState，需要 Host Projection |
| 5 | 差异化 Projection — 持石者 vs 未持石者所见不同 | 复足 | D | 需要 Projection engine prototype |
| 6 | 角色独占信息 — 仅 HO1 可见的背景 | RE 计划 | A | `VisibleInformation.audience="ho"`（已纳入） |
| 7 | 跨模组引用 — 引用其他模组的设定 | 卡特续述、柏林 | D | 超出单 ModuleContent 聚合边界 | — |
| 8 | 开放式创造 — "能画出的简单物品" | 银之锁、芒卡巧克力 | D | 不可结构化 | — |
| 9 | 时间错乱 — "梦境时间非线性" | 卡特续述 | D | 不可结构化 | — |
| 10 | House Rule 修改 — "疯狂角色继续游戏" | 芒卡巧克力 | B | Ruleset 修改，不属于模组声明 |
| 11 | KP 裁量和即兴发挥 | 15/15 模组 | C | 自然语言承载 | — |


---

## Contract Freeze Statement

ModuleContent v1 已冻结。后续开发中发现的问题，优先按以下分类处理，不直接修改 Contract：

| 分类 | 定义 | 处理方式 |
|------|------|---------|
| **Parser Gap** | Parser 提取能力不足以产出目标字段 | 改进 Parser，不修改 Contract |
| **Runtime Gap** | Contract 字段存在但引擎未实现对应消费者 | B 侧实现消费者，不修改 Contract |
| **Host Agent Gap** | 需主持 Agent 自然语言处理的内容 | A 侧通过 keeper_guidance 承载，不修改 Contract |
| **Ruleset Gap** | 属于规则系统算法而非模组声明 | 在 Ruleset 层扩展，不修改 ModuleContent |
| **Future Extension** | 多个模组重复出现、Runtime 明确需要、当前抽象无法表达的缺口 | 通过独立 RFC 提案修改 Contract |

只有满足以下全部条件时，才考虑修改 Contract：Runtime 必须依赖、多个模组重复出现、无法通过现有 Rule/Operation 表达、有明确消费者。

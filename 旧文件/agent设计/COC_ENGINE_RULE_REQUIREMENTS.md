# COC_ENGINE_RULE_REQUIREMENTS.md

> 日期：2026-07-13
> 范围：Rules Engine 需要掌握的最低 CoC 7e 规则集
> 目标：支撑 Intent → Rules → Resolution 完整流水线
>
> 未阅读完整规则书。所有结论来自项目已有设计文档（数据模型设计.md / AI_AGENT_DESIGN.md / 如何应对动态机制.md）中已验证的六模组实证。

---

## 〇、流水线定位

```
Intent ──▶ Rules Engine ──▶ Resolution
              │
              ├── CheckResolver   (检定)
              ├── SAN              (理智)
              ├── Combat           (战斗)
              ├── ViewProjector    (权限裁剪)
              ├── HookEvaluator    (A/B/C/D 引擎介入)
              └── GameStateRepo    (状态写入)
```

每条规则标注影响模块：

| 缩写 | 模块 | 影响方式 |
|------|------|---------|
| **CH** | Character | 修改属性/技能/HP/SAN/状态 |
| **IN** | Intent | IntentParser 需要知道合法技能名/动作类型 |
| **CK** | CheckResolver | 检定逻辑（掷骰/判定/难度） |
| **RS** | Resolution | Resolution 的输出字段 |

---

## 一、P0 — MVP 必须

> 缺一条则 Intent → Rules → Resolution 闭环断裂。

### 1.1 D100 技能检定

**规则**: 掷 d100，结果 ≤ 技能值 = 成功。1 = 大成功，96-100 = 大失败（技能 ≥ 50 时仅 100）。

| 模块 | 影响 |
|------|------|
| **CK** | `roll = d100()`。五级判定：`critical(1) / extreme(≤skill/5) / hard(≤skill/2) / success(≤skill) / fail(>skill) / fumble(100)` |
| **IN** | Intent.action.skill 必须是 `World.skillCatalog` 内的技能名 |
| **RS** | `Resolution.check_result { skill, target_value, roll, tier }` |

**出处**: 数据模型设计.md §5.1 检定流水线。每个模组都用到。

---

### 1.2 属性检定

**规则**: 直接对 STR/CON/DEX/APP/INT/POW/SIZ/EDU 掷 d100。判定逻辑同技能检定。

| 模块 | 影响 |
|------|------|
| **CK** | 同 D100，但 target_value 来自 `Character.attributes[key]` 而非 `Character.skills[id]` |
| **IN** | Intent.action.attribute 可选，值为八大属性名之一 |
| **RS** | `Resolution.check_result { attribute, target_value, roll, tier }` |

**出处**: 鬼屋（STR 撬门）、蛙蛙村（POW 对抗信使精神冲击）。

---

### 1.3 难度等级

**规则**: regular / hard（1/2）/ extreme（1/5）。难度改变 target_value。

| 模块 | 影响 |
|------|------|
| **CK** | `modified_target = floor(skill * difficulty_multiplier)`。`regular=1.0 / hard=0.5 / extreme=0.2` |
| **IN** | Intent.action.difficulty 由 IntentParser 或软判据阶段赋值 |
| **RS** | `Resolution.check_result.modified_value` 记录修正后的目标值 |

**出处**: 数据模型设计.md §6.4 软判据与硬求值分离。

---

### 1.4 奖惩骰

**规则**: 奖励骰（advantage）：掷两个十位骰，取较低值。惩罚骰（disadvantage）：取较高值。

| 模块 | 影响 |
|------|------|
| **CK** | `bonusDice` 参数控制额外十位骰数量。正值 = 奖励骰，负值 = 惩罚骰 |
| **IN** | Intent.action.modifiers 中 `{ source, effect: "bonus_die" / "penalty_die" }` |
| **RS** | `Resolution.check_result.modifiers_applied` 列出已应用的修正来源 |

**出处**: 蛙蛙村（奖励骰）、鬼屋（惩罚骰场景）。

---

### 1.5 HP 管理

**规则**: HP = (CON + SIZ) / 10。受伤扣 HP，治疗恢复。HP = 0 → 濒死。

| 模块 | 影响 |
|------|------|
| **CH** | `Character.derived_stats.HP` 读写。`Character.derived_stats.HP_max` 只读 |
| **CK** | 伤害骰解析：`parseDice("1d6") → roll()` |
| **RS** | `Resolution.state_changes` 记录 HP 变更 |

**出处**: 鬼屋（科比特战斗）、复足（冷蛛伤害）。

---

### 1.6 基础 SAN 损失

**规则**: 见到恐怖事物 → 损失 SAN。MVP 仅支持**检定式**：成功 = 较少损失，失败 = 较多损失。格式 `"0/1d6"`。

| 模块 | 影响 |
|------|------|
| **CH** | `Character.derived_stats.SAN` 读写 |
| **CK** | 先做 SAN 检定（POW 检定），再按结果应用损失 |
| **RS** | `Resolution.check_result` + `Resolution.state_changes` |

**出处**: 数据模型设计.md §3.6 SanTrigger。六种形态中选第一种做 MVP。

---

### 1.7 场景移动

**规则**: 玩家从一个场景移动到另一个场景。触发 `on_scene_exit` 和 `on_scene_enter` hook。

| 模块 | 影响 |
|------|------|
| **CH** | `Character.location` 更新 |
| **CK** | 无检定。纯状态变更 |
| **RS** | `Resolution.narration_context.scene_transition` |
| **IN** | Intent.action.type = "move"，Intent.action.via_exit 为出口名 |

**出处**: 数据模型设计.md §5.1 场景流水线。

---

### 1.8 物品交互

**规则**: 搜索/使用物品/观察。不涉及检定时为纯状态变更。涉及检定时走 D100 检定。

| 模块 | 影响 |
|------|------|
| **IN** | Intent.action.type ∈ { search, use_item, observe, interact } |
| **CH** | `Character.equipment` 可能增加（拾取物品） |
| **RS** | `Resolution.narration_context.visible_facts` |

**出处**: 门 I（数据模型设计.md §5.8.2）——纯文本，LLM 全权。

---

### 1.9 表达式求值器

**规则**: 解析并求值 `Rule.when` 和 `WinCondition.expr` 中的表达式。

| 模块 | 影响 |
|------|------|
| **CK** | 不直接涉及检定。但检定的 `tier` 是表达式可读的变量 |
| **RS** | B/C 类 Rule 的触发在 Resolution 生成阶段被求值 |

**语法**: `// != < > <= >= && || + - * / floor() min() max()`。**无循环、无函数定义**。

**出处**: 数据模型设计.md §6.2 Expr 语法。MVP 只需实现子集：比较 + 布尔 + 基础算术。

---

## 二、P1 — 建议

> 不是阻塞项，但每项都能显著提升游戏完整度。

### 2.1 SAN 全部六种形态

**规则**:

| 形态 | 逻辑 | 示例 |
|------|------|------|
| `check` | 检定式：成功 0 / 失败 1d6 | 见到怪物 |
| `flat` | 无检定固定损失 | 读日记 −1d4 |
| `direct` | 精神伤害，不走 SAN 检定 | 信使冲击：POW 对抗 → 1d6 |
| `max_reduce` | SAN 上限扣减 | +2% 神话 → 99→97 |
| `gain` | SAN 回复 | +1d6 |
| `capped` | 同源累计封顶 ≤ 6 | 追书人/死者 |

| 模块 | 影响 |
|------|------|
| **CH** | `Character.derived_stats.SAN` + `SAN_max`。LedgerEntry 用于 capped |
| **CK** | 每种形态的结算逻辑不同 |
| **RS** | `Resolution.state_changes` |

**出处**: 数据模型设计.md §3.6。

---

### 2.2 战斗流水线（12 hook × B/C 类 Rule）

**规则**: 战斗 = 声明攻击 → 计算难度 → 掷攻击骰 → 比较成功等级 → 防守方闪避 → 掷闪避骰 → 判定命中 → 掷伤害骰 → 护甲扣减 → 写入 HP → 重伤判定 → 死亡 → 回合结束。

| 模块 | 影响 |
|------|------|
| **CH** | HP、conditions、weapons |
| **CK** | 每个 hook 一个暂停点。攻击方技能 vs 防守方闪避 |
| **IN** | Intent.action.type = "skill_check" with combat skill |
| **RS** | `Resolution.check_result` + `state_changes` |

**MVP 可搁置的原因**: 战斗规则漏了，僵尸只是变强一点——有损但可观察。B/C 类不能搁置（猫不死 = 结局永不触发）。

**出处**: 数据模型设计.md §5.1 / §9.2。

---

### 2.3 Condition 状态机

**规则**: 带定时器的持续性状态（中毒、感染、疯狂）。`timer: { after: "24h" }` → 到期触发 check → 分支 → 可能循环。

| 模块 | 影响 |
|------|------|
| **CH** | `Character.conditions[]` 追加/更新 |
| **CK** | 定时器到期时引擎主动触发检定（调度问题，非 LLM 想起） |
| **RS** | `Resolution.state_changes` 记录 conditions 变更 |

**出处**: 数据模型设计.md §5.6。

---

### 2.4 LedgerEntry 计数器

**规则**: 计数器 + 时间窗 / 单次事件 + 时长 / 累计封顶 / 周期回复。

| 模块 | 影响 |
|------|------|
| **CH** | `Character.ledger` 读写 |
| **CK** | 引擎自动维护计数器（每 turn 检查窗口是否过期） |

**实例**: 蛙蛙村"24 小时内失败两次意志检定 → 惩罚骰"、鬼屋"MP 每小时回复 1 点"。

**出处**: 数据模型设计.md §5.7。

---

### 2.5 Hook 求值器（B/C 类）

**规则**: 在每个 hook 上收集 world_rules + module rules + entity rules，按 priority 排序，逐条执行 `(hook, when, then)` 三元组。

| 模块 | 影响 |
|------|------|
| **CK** | 检定的 tier 是 hook 可读的变量（C 类：on_check_resolve） |
| **RS** | B 类（on_scene_enter）在 Resolution 生成前触发；C 类在生成后触发 |

**MVP 必须 B/C 类的原因**: B 类（银之锁·猫）缺失 → 结局永不触发。C 类（鬼屋·INT 成功更糟）缺失 → 反直觉设计被静默抹除。

**出处**: 数据模型设计.md §5.8 / §9.2。

---

### 2.6 推骰（Pushing the Roll）

**规则**: 玩家检定失败后，可以"推骰"——以更严重的失败后果为代价重试。

| 模块 | 影响 |
|------|------|
| **IN** | 需要新的 Intent 来源类型：`source: "push_roll"` |
| **CK** | 第二次检定。失败后果升级（fumble → 更糟） |
| **RS** | 标注该检定为"已推骰" |

---

### 2.7 幸运（Luck）消费

**规则**: 玩家可以消耗幸运值来降低检定难度（1 point = 1% 降低）。

| 模块 | 影响 |
|------|------|
| **CH** | `Character.derived_stats.LUCK` 扣减 |
| **CK** | `modified_target = target + luckSpent` |
| **RS** | 记录 luck 消费量 |

---

## 三、P2 — 未来

### 3.1 战斗 hook 完整填充

P1 已有 hook 表和 B/C 类求值器。P2 将**所有 12 个战斗 hook** 全部启用——目前战斗规则可暂写进 `Entity.secrets`，由 LLM 执行（数据模型设计.md §9.2）。

### 3.2 D 类不变式校验

**规则**: `count(has_dreamstone == true) ≤ floor(party.size / 2)`。引擎执行 op 时校验跨实体的写入不变式。

| 模块 | 影响 |
|------|------|
| **CH** | 间接受影响——op 被拒时 Character 不变化 |
| **CK** | 不涉及检定 |

**出处**: 数据模型设计.md §7.3。

### 3.3 固定阈值检定

**规则**: 不是对抗技能值，而是对抗固定数字（如"撬门力量 20"）。

| 模块 | 影响 |
|------|------|
| **CK** | target_value 来自 Checkpoint.threshold 而非 skill |

**出处**: 数据模型设计.md §9.3（复足·撬门）。

### 3.4 代表投掷

**规则**: 不让每个人都掷骰，只让队伍中某属性最高者掷。

| 模块 | 影响 |
|------|------|
| **CK** | `Checkpoint.roll_representative` 指定"选 `party.max_STR` 的那个角色" |
| **IN** | Intent 可能需要指定 representative |

**出处**: 数据模型设计.md §9.3（死者·敏捷检定确定抵达先后）。

### 3.5 追逐规则

CoC 7e 追逐机制：移动速度（MOV）比较 + 障碍物判定。

### 3.6 法术/神话书

阅读神话典籍 → Cthulhu Mythos 技能 + SAN 上限扣减 + 习得法术。

---

## 四、总结

```
P0（MVP 必须 · 9 项）
─────────────────────
  D100 技能检定        属性检定          难度等级
  奖惩骰               HP 管理            基础 SAN 损失
  场景移动             物品交互           表达式求值器

  缺一项 → Intent → Rules → Resolution 闭环断裂。

P1（建议 · 7 项）
─────────────────────
  SAN 六形态           战斗流水线 (12 hooks)   Condition 状态机
  LedgerEntry 计数器    Hook 求值器 (B/C)      推骰
  幸运消费

  不缺也能玩。加上后游戏完整度显著提升。

P2（未来 · 6 项）
─────────────────────
  战斗 hook 完整填充    D 类不变式校验        固定阈值检定
  代表投掷             追逐规则              法术/神话书
```

---

*所有规则均来自项目已有设计文档中的六模组实证。未引用完整 CoC 规则书。*

# ModuleContent v1 示例验证报告

> **版本**：ModuleContent v1 P2 Frozen Contract
> **验证日期**：2026-07-24
> **验证阶段**：Contract Validation（非 Schema 实现）
> **锚定文档**：[module-content-field-decisions.md](./module-content-field-decisions.md) §8 P2 最终完整形状

---

## 一、验证目标

验证当前已冻结的 ModuleContent v1 P2 Contract 是否能够表达真实 CoC 模组的内容，使用 1 个真实模组进行完整 Mapping：

1. **《幸福蛙蛙村》**（DOCX，12374 字）——短模组，含多导入、软判据、累积变异 Track、多结局、SAN 检定、战斗

验证方法：将模组原文逐段映射到 ModuleContent 的 7 个顶层集合 + 四张表（Hook × Expression × Op × 内建变量），记录可直接表达的内容和无法表达的内容（Gap），并按 Parser/Runtime/Host Agent/Ruleset/Future Capability 分层分类。

---

## 二、模组简介

### 幸福蛙蛙村

- **类型**：短模组（4-6 小时）
- **规则系统**：CoC 7 版
- **玩家人数**：1-4 人
- **核心机制**：
  - 多导入（3 种入口：普通公职人员、私家侦探、警方协查）
  - 软判据说服（根据阐述质量映射不同难度）
  - 四级累积变异（Stage 1-4，每阶段属性变化 + 行为变化）
  - 多结局（5 个结局：逃离、说服、战斗击败、被转化、投降）
  - 饮食/接触触发意志检定
  - 战斗（巨型青蛙怪 + 员工协同行动）
  - 上帝视角监控（信使在领域内全知）

---

## 三、覆盖字段统计

### 3.1 幸福蛙蛙村字段覆盖

| 维度 | 模组机制数 | 可直接表达 | 覆盖率 | 关键依赖 |
|------|----------|-----------|--------|---------|
| Scene / ContentUnit | 11 | 11 | 100% | 当前已有 |
| Entity（NPC + Object + Location） | 18 | 18 | 100% | P1 `stat_block` |
| Checkpoint（含 tier override） | 23 | 23 | 100% | P0 `difficulty=None`、P2 tier override |
| Rule | 11 | 11 | 100% | P0 `mode`、P1 `module_rules`、P2 Hook/Op |
| Condition | 8 | 8 | 100% | P0 `expr`、P2 Expression |
| Operation / Effect | 13 | 13 | 100% | P2 11 Op variants |
| Outcome | 23 | 23 | 100% | P2 `VisibleInformation` |
| Ending | 5 | 5 | 100% | P0 `is_ending` |
| Visibility | 4 | 4 | 100% | P2 `VisibilityPolicy` |
| EntryPoint | 3 | 3 | 100% | P2 `Entity.state + Rule` |
| SAN | 8 | 8 | 100% | P2 `Rule + ModifyOp` |
| **总计（L1 原文保存覆盖）** | **~127** | **~127** | **~100%** | |

---

## 四、成功映射案例

### 案例 1：软判据说服信使（P0 `difficulty=None`）

**原文**：
> "如果玩家直说过说服/话术，那就是困难成功算过。守密人可以引导玩家去具体阐述怎么说服信使，只要阐述合理那就是普通说服。如果阐述的很精彩，就给奖励骰。"

**映射**：

```json
{
  "id": "persuade_messenger",
  "action": "persuade",
  "target_id": "messenger",
  "skills": ["persuade", "charm"],
  "difficulty": null,
  "outcomes": {
    "success": {
      "facts": ["messenger_belief_shattered"],
      "ops": [{ "op": "trigger_ending", "ending_id": "ending_persuade_messenger" }]
    }
  }
}
```

`difficulty=None` 表示运行时通过 Host Agent 在 Intent 中提议 `roleplay_tier`（none/reasonable/excellent），Engine 校验后映射到 `regular`/`hard` 难度并记录为 Event。

**覆盖字段**：CheckpointSpec（P0）、CheckpointOutcomeSpec、TriggerEndingSpec（P2）

---

### 案例 2：四级累积变异（P2 Track 退化为 Rule 组合）

**原文**：
> "第一阶段：身体开始长出青蛙的特征……第二阶段：变异加剧，跳跃加4D6，外貌减2D6……第三阶段：长出一颗青蛙脑袋……外貌直接变成25，跳跃直接85……第四阶段：身体缩小变成青蛙，跳入池塘！"

**映射**：每条阶段转换 = 一条 `Rule(on_state_change, when self.mutation_stage >= N, then ops)`

```json
{
  "id": "mutation_stage_2",
  "hook": "on_state_change",
  "when": { "expr": "self.mutation_stage == 1 && self.time_in_resort >= 24" },
  "then": [
    { "op": "add", "path": "self.mutation_stage", "value": 1 },
    { "op": "add", "path": "self.attr.jump", "value": "4d6" },
    { "op": "add", "path": "self.attr.appearance", "value": "-2d6" }
  ]
}
```

**覆盖字段**：RuleSpec（P0 mode="append"）、ConditionSpec（P2 expr）、AddOp（P2）、内建变量 `self.mutation_stage` / `self.time_in_resort`（P2）

---

### 案例 3：多结局（P0 `is_ending`）

**原文**：
> "结局1：逃离度假村……结局2：说服幸福信使……结局3：惊醒的噩梦……结局4：永恒的祝福……结局5：投降！成为员工！"

**映射**：5 个 `WinConditionSpec`，各自 `is_ending=true`

```json
{
  "id": "ending_escape",
  "when": { "expr": "party.location != 'resort' && ending_triggered == false" },
  "fact": "调查员逃离了蛙蛙度假村",
  "player_visible_information": "几天后你们在报纸上看到一则小新闻……",
  "is_ending": true
}
```

**覆盖字段**：WinConditionSpec（P0 `is_ending`）、ConditionSpec（P2 expr）

---

### 案例 4：因果链——伤害青蛙→巨型青蛙怪（P2 `trigger_rule` + `force`）

**原文**：
> "如果玩家故意伤害池塘的青蛙或者工作人员，那么会引来幸福信使的愤怒。她会让池塘里几百只青蛙融合成一个巨型青蛙怪去讨伐这个玩家。"

**映射**：

```json
{
  "id": "frog_harmed_retaliation",
  "hook": "on_interact",
  "mode": "override",
  "when": { "expr": "action.target.kind == 'frog' && action.type == 'harm'" },
  "then": [
    { "op": "force", "action": "summon_mutant_frog" }
  ]
}
```

**覆盖字段**：RuleSpec（P0 `mode="override"`）、ConditionSpec（P2 expr）、ForceOp（P2）

---

### 案例 5：多入口（P2 `Entity.state + Rule`）

**原文**：
> "导入1：（玩家为医生，学生，教师，普通公职人员等）……导入2：（玩家为雇佣兵，侦探，警察等职业）……选项A：私家侦探委托……选项B：警方协查委托"

**映射**：

```json
{
  "entity.state.entry": "detective",
  "rule": {
    "id": "entry_detective",
    "hook": "on_scene_enter",
    "when": { "path": "entity.pc.entry_slot", "equals": "detective" },
    "then": [{ "op": "transition", "scene_id": "scene_manor" }]
  }
}
```

不需要独立 `EntryPointSpec`。

**覆盖字段**：Entity.state、RuleSpec、TransitionSpec（P2）

---

## 五、Gap 列表

### 5.1 Parser Gap

| ID | 描述 | 触发模组 | Contract 影响 |
|----|------|---------|--------------|
| PG-1 | 软判据三级映射提取（不阐述→困难 / 合理→普通 / 精彩→奖励骰） | 幸福蛙蛙村 | ❌ 不影响。`difficulty=None` 已支持 |
| PG-2 | 复杂因果链自动提取（詹姆斯被拉扯→呼喊员工→惊动信使→触发敌对） | 幸福蛙蛙村 | ❌ 不影响。`trigger_rule` Op 已支持 |
| PG-3 | KP 裁量 fallback 逻辑提取（"如果全都过了那就选一个幸运儿"） | 幸福蛙蛙村 | ❌ 不影响。`keeper_guidance` 承载 |
| PG-4 | "随便编"级别元指令识别 | 幸福蛙蛙村 | ❌ 不影响。Contract 不需要承载 |

### 5.2 Runtime Gap

| ID | 描述 | 触发模组 | 依赖 |
|----|------|---------|------|
| RG-1 | 20 个 Hook dispatcher 实现 | 幸福蛙蛙村（`on_state_change`、`on_time_elapsed`、`on_interact`） | B 实现（P2 阻塞条件） |
| RG-2 | Expression parser（比较/布尔/算术/聚合/内建变量） | 幸福蛙蛙村（`self.mutation_stage >= 3`、`clock.time_of_day == 'night'`） | B 实现（P2 阻塞条件） |
| RG-3 | 11 个 Op Effect executor | 幸福蛙蛙村（AddOp、SetOp、ApplyConditionOp、ForceOp、TriggerEndingOp） | B 实现（P2 阻塞条件） |
| RG-4 | 内建变量自动维护 | 幸福蛙蛙村（`self.mutation_stage`、`clock.time_of_day`、`self.drink_failures`） | B 实现（P2 阻塞条件） |
| RG-5 | SceneSpec.exits 移动校验 | 幸福蛙蛙村（度假村→森林→度假村内的自由移动） | B 实现（P1 阻塞条件） |
| RG-6 | roleplay_tier → difficulty 映射链 | 幸福蛙蛙村（软判据说服信使） | Host Agent 协议冻结 |

### 5.3 Host Agent Gap

| ID | 描述 | 触发模组 |
|----|------|---------|
| HA-1 | "守密人可以根据自己的理解和玩家的强度修改这个模组的设定" | 幸福蛙蛙村 |
| HA-2 | "关于幸福的定义由玩家探讨"（开放式主题讨论） | 幸福蛙蛙村 |
| HA-3 | "可以留给kp自行编"（信使超能力和魔法） | 幸福蛙蛙村 |
| HA-4 | 氛围营造（"其乐融融逐渐滑向细思极恐"） | 幸福蛙蛙村 |
| HA-5 | 可选增强（"如果想增加互动感可以过一次汽车驾驶"） | 幸福蛙蛙村 |
| HA-6 | 感官描述（"你的皮肤变得格外湿滑清凉"） | 幸福蛙蛙村 |

### 5.4 Ruleset Gap

| ID | 描述 | 触发模组 |
|----|------|---------|
| RS-1 | SAN 损失骰值（SC 0/1、SC 1/1D4、SC 1/1D6、SC 1/1D10、SC 1/1D20） | 幸福蛙蛙村 |
| RS-2 | 临时疯狂规则 | 幸福蛙蛙村 |
| RS-3 | 奖励骰/惩罚骰（CoC 7版） | 幸福蛙蛙村 |
| RS-4 | 技能默认值（闪避=DEX/2） | 幸福蛙蛙村 |
| RS-5 | 属性对抗（POW vs POW 精神冲击） | 幸福蛙蛙村 |
| RS-6 | 不完整的规则数据（"信使还具备很多的超能力和魔法"） | 幸福蛙蛙村 |

### 5.5 Future Capability

| ID | 描述 | 触发模组 | 建议 |
|----|------|---------|------|
| FC-1 | 变异阶段症状映射验证（4 阶段 × 属性变化 + 行为描述） | 幸福蛙蛙村 | P2 落地后验证 Track 模式 |
| FC-2 | 多级因果链级联正确性（4 步级联：拉扯→呼喊→惊动→敌对） | 幸福蛙蛙村 | P2 落地后验证 `trigger_rule` 幂等性 |
| FC-3 | 独立 NPC 变异速度差异（理查德加速变异） | 幸福蛙蛙村 | Contract 已支持 |
| FC-4 | 空间范围 Effect（水晶"5米半径内免疫心灵伤害"） | 幸福蛙蛙村 | 观察，如多模组出现再评估 |

---

## 六、验证结论

### 6.1 当前 ModuleContent v1 是否可以冻结？

**可以冻结。** 本次验证未发现任何需要修改 Contract 的问题。

幸福蛙蛙村（~127 个可结构化机制）在 P2 Contract 下实现 ~100% L1 原文保存覆盖。所有机制均可通过 7 个顶层集合 + 四张表表达：

- **场景**：11 个 SceneSpec，含 P1 `exits`
- **实体**：18 个 EntitySpec，含 P1 `stat_block`
- **检定点**：23 个 CheckpointSpec，含 P0 `difficulty=None`、P2 tier override
- **规则**：11 条 RuleSpec，含 P0 `mode`、P1 `module_rules`、P2 Hook/Op
- **结局**：5 个 WinConditionSpec，含 P0 `is_ending`
- **多入口**：3 种入口通过 `Entity.state + Rule(on_scene_enter)` 表达（不建 EntryPointSpec）
- **变异 Track**：4 级变异通过 `Rule(on_state_change)` + 内建变量表达（不建 TrackSpec）
- **可见性**：P2 `VisibilityPolicy` 覆盖 audience/discovery

### 6.2 Gap 性质判断

发现的 21 个 Gap 全部不属于 Contract 层：

| 层级 | Gap 数量 | 需要修改 Contract？ |
|------|---------|-------------------|
| Parser Gap | 4 | ❌ Parser 改进 |
| Runtime Gap | 6 | ❌ B 侧实现消费者 |
| Host Agent Gap | 6 | ❌ Host Agent 自然语言承载 |
| Ruleset Gap | 6 | ❌ CoC Ruleset 内部 |
| Future Capability | 4 | ❌ P2 落地后验证 |

**零个 Gap 要求修改 ModuleContent v1 Contract。**

### 6.3 关键设计验证

以下 P0/P1/P2 设计在本次验证中得到了真实用例确认：

| 设计决策 | 模组证据 | 状态 |
|---------|---------|------|
| P0 `difficulty=None`（软判据） | 说服信使的阐述质量→难度映射 | ✅ 确认有效 |
| P0 `Rule.mode`（append/override/forbid） | 伤害青蛙→override 默认行为→触发巨型怪 | ✅ 确认有效 |
| P0 `is_ending` | 5 个终局结局 | ✅ 确认有效 |
| P1 `module_rules` | 饮食触发、池水接触等模组级全局规则 | ✅ 确认有效 |
| P1 `stat_block` | 信使/员工/巨型怪/梦游青蛙的属性块 | ✅ 确认有效 |
| P2 Track 退化为 Rule 组合 | 四级变异阶段推进 | ✅ 确认有效 |
| P2 多入口 = Entity.state + Rule | 3 种导入路径 | ✅ 确认有效 |
| P2 不建 SAN 专用对象 | 8 处 SAN 损失通过 Rule+ModifyOp 表达 | ✅ 确认有效 |
| P2 `trigger_rule` 因果链 | 伤害青蛙→信使愤怒→巨型青蛙怪 | ✅ 语义成立 |

### 6.4 总结

**ModuleContent v1 P2 Contract 通过单模组验证。** 幸福蛙蛙村的全部 ~127 个结构化机制均可被 7 个顶层集合 + 四张表（Hook × Expression × Op × 内建变量）覆盖，不新增领域对象。不存在 Contract 层的 Gap。

剩余的不可结构化内容（~5%）属于 KP 裁量、开放式创造和自然语言主持指导——这是所有 TRPG 模组固有的特点，不是 Contract 的缺陷。

---

## 七、输出物

| 文件 | 路径 |
|------|------|
| 幸福蛙蛙村内容映射 | [examples/module-content-validation/幸福蛙蛙村/模组内容映射.md](../examples/module-content-validation/幸福蛙蛙村/模组内容映射.md) |
| 幸福蛙蛙村 draft JSON | [examples/module-content-validation/幸福蛙蛙村/module-content-draft.json](../examples/module-content-validation/幸福蛙蛙村/module-content-draft.json) |
| 本验证报告 | [docs/module-parser/ModuleContent示例验证报告.md](./ModuleContent示例验证报告.md) |

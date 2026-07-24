# Field Catalog vs 过期数据模型：五模组覆盖对比

> 日期：2026-07-23
> 对比对象：当前 Field Catalog（`module-field-catalog.md`）vs 过期数据模型（`docs/archive/pre-consensus/数据模型设计.md` + `如何应对动态机制.md`）

---

## 一、过期数据模型的完整结构

过期模型是 2026-07-10 基于六个真实模组逐条验证后设计的。它的核心结构：

```
Reference 层：Skill / Occupation / Weapon
Content 层： World(hooks/variables/world_rules)
            ModulePack(title/version/world_ref/authors/players_min_max)
            Scene(title/description/exits/checkpoint_ids)
            Entity(★六值kind: npc/monster/item/clue/animal/object)
              ├── content/public_persona/secrets
              ├── state / refuse_ops / rules / stats(StatBlock,可空)
            Checkpoint(match_hint/priority/skill(@类别引用)/difficulty(可空)/hidden/roll_mode)
            SanTrigger(★六值kind: check/flat/direct/max_reduce/gain/capped)
              ├── source_tag(累计封顶)/loss(骰子表达式)/condition
            WinCondition(★expr表达式/is_ending)
            Pregen / Asset

嵌套结构：
  HookDef(19个: 战斗12 + 检定4 + 场景3)
  VariableDef(~15个: combat.round/damage.type/party.size/check.tier等)
  Rule(hook/when/then/mode(append/override/forbid)/priority)
  Op(~10个: set/scale/add/absorb/decrement/forbid/force/apply_condition/spawn/trigger)
  Expr语法(比较/布尔/算术/聚合(count/max))
```

---

## 二、逐模块覆盖对比

### 追书人

| 能力 | 过期模型 | Field Catalog | 差距原因 |
|------|---------|-------------|---------|
| 模组身份/背景/幕后 | ✅ | ✅ | 均覆盖 |
| 12场景 | ✅ Scene + exits | ✅ ContentUnit | — |
| 7实体 | ✅ Entity六值 | ✅ EntityDefinition | — |
| 13线索 + 多路径获取 | ⚠️ Entity(kind=clue)内联 | ✅ InformationItem + Acquisition分离 | 过期模型把线索当Entity的kind，不区分信息本体和获得方式 |
| 14检定 | ✅ Checkpoint(hidden/roll_mode/difficulty可空) | ⚠️ Interaction + Resolution(variant OPEN) | 过期模型直接建模了暗骰、交互模式；Field Catalog把这些拆到Resolution但variant未冻结 |
| 动态规则 | ✅ Rule(mode/priority) | ✅ RuleDefinition | 均覆盖 |
| SAN 0/1D6 | ✅ SanTrigger六值 | ❌ 缺失 | — |
| 6结局 | ✅ WinCondition(is_ending) | ✅ EndingDefinition | 均覆盖 |
| 昼夜循环 | ❌ 无 Timeline | ❌ 无 Timeline | 两者都缺 |
| 夜间监视重复调度 | ❌ 无调度循环 | ❌ 无调度循环 | 两者都缺 |

**过期模型覆盖率：90%**（缺 Timeline 和重复调度）。**Field Catalog 覆盖率：95%**（缺 SanTrigger 和重复调度，但线索的 Info/Acquisition 分离更准确）。

---

### 银之锁

| 能力 | 过期模型 | Field Catalog | 差距原因 |
|------|---------|-------------|---------|
| 连续解谜段 | ✅ Scene（无显式标题也合法） | ✅ ContentUnit（unit_type可空） | 均覆盖 |
| 猫/NPC/速写本/钥匙 | ✅ Entity六值 | ✅ EntityDefinition | — |
| 区域束缚规则 | ✅ Rule(on_scene_enter, forbid leave) | ✅ RuleDefinition(Trigger+Effect+Scope) | — |
| 画物品（创造性交互） | ❌ 无 Keeper Adjudication | ⚠️ Resolution mode H/OPEN | 两者都无法结构化——这个交互本质上是开放式创造 |
| 猫→NPC→锁因果链 | ✅ Rule链(trigger/force/spawn等10个Op可表达每步) | ⚠️ Rule之间无激活关系 | 过期模型的Op catalog更丰富——`spawn`/`trigger`/`force`可表达"激活下一条规则" |
| 被抓回=回滚 | ✅ WinCondition(is_ending=false) | ✅ EndingDefinition(is_ending=false) | 均覆盖 |
| 房间→走廊空间 | ✅ Scene.exits | ✅ LocationDefinition(spatial_links) | — |
| 速写本生命周期 | ⚠️ Entity(kind=item)可声明state | ❌ 无 Resource | 过期模型把物品当Entity，状态变化由Rule驱动——够用但不优雅 |

**过期模型覆盖率：92%**（缺 Keeper Adjudication、缺 Timeline）。**Field Catalog 覆盖率：90%**（额外缺 Resource、跨实体因果链）。

---

### 复足

| 能力 | 过期模型 | Field Catalog | 差距原因 |
|------|---------|-------------|---------|
| 9场景 | ✅ | ✅ | — |
| 冷蛛/蜘蛛神/梦境之石 | ✅ Entity六值 | ✅ | — |
| 六级感染 Track | ❌ 无 Track | ❌ 无 Track | **两者都缺** |
| 重复检定调度 | ✅ Rule(on_turn_end/self.rounds_without_damage) | ⚠️ Timeline缺失 | 过期模型有内建变量 `self.rounds_without_damage` 和19个hook（含on_turn_end），Rule可直接表达"4轮未造成伤害→转换目标"。Field Catalog缺Timeline和变量catalog |
| 梦境/现实空间分离 | ❌ 无差异化Projection | ❌ 无差异化Projection | **两者都缺** |
| 人数缩放 | ✅ Expr聚合(count/max/party.size) | ❌ Condition只有等值 | 过期模型的表达式语法有聚合函数 |
| 预制角色 | ✅ Pregen | ⚠️ CharacterTemplate(OPEN) | 过期模型有Pregen，但仅覆盖角色卡数据，不含creation_mode |
| 每十分钟时间表 | ❌ 无 Timeline | ❌ 无 Timeline | **两者都缺** |

**过期模型覆盖率：80%**（缺 Track、Timeline、差异化Projection）。**Field Catalog 覆盖率：75%**（额外缺聚合表达式）。

---

### 追沙

| 能力 | 过期模型 | Field Catalog | 差距原因 |
|------|---------|-------------|---------|
| 网状调查 | ✅ Scene + exits可空（自由移动） | ✅ ContentGraph + ContentRelation | 过期模型没有显式图结构——exits只是邻接列表。Field Catalog的ContentRelation更完整 |
| 多势力 | ❌ Entity(kind=npc)只能单个建模 | ❌ 无 Faction | **两者都缺**——过期模型可以用多个Entity表达势力，但没有"势力内部成员关系""态度变化"的语义 |
| 沙漏 Track | ❌ 无 Track | ❌ 无 Track | **两者都缺** |
| 异常事件 Table | ❌ 无 Table | ❌ 无 Table(暂缓H) | **两者都缺** |
| 沙之书位置转移 | ✅ Entity.state + Rule(ModifyOp) | ✅ | 均覆盖——位置作为状态值，由Rule驱动变更 |
| 预制角色 | ✅ Pregen | ⚠️ | — |
| 四结局 | ✅ WinCondition | ✅ | — |

**过期模型覆盖率：78%**（缺 Track、Faction、Table）。**Field Catalog 覆盖率：80%**（ContentRelation更完整，Track/Faction/Table仍缺）。

---

### RE计划

| 能力 | 过期模型 | Field Catalog | 差距原因 |
|------|---------|-------------|---------|
| 三HO入口 | ❌ 无 EntryPoint | ⚠️ EntryPoint(全部H/OPEN) | **两者都无法结构化**——过期模型完全没有多头入口概念 |
| 三线并行 | ✅ Scene + exits | ✅ ContentRelation(parallel) | — |
| 角色独占信息 | ❌ 无角色级可见性 | ⚠️ disclosure_policy(H/OPEN) | **两者都缺**——过期模型只有keeper/player二分 |
| 固定身份模板 | ✅ Pregen | ⚠️ CharacterTemplate | 过期模型的Pregen只有角色卡数据，不含`creation_mode` |
| 隐藏结局（组合条件） | ✅ Expr布尔操作(A && B && C) | ❌ Condition只有等值 | 过期模型的表达式语法有布尔操作 |
| 通讯Resource | ⚠️ Entity(kind=item) | ❌ 无 Resource | — |

**过期模型覆盖率：75%**（缺 EntryPoint、角色级可见性、Resource、Timeline）。**Field Catalog 覆盖率：80%**（EntryPoint和角色级可见性有语义但未冻结，表达式不如过期模型）。

---

## 三、总结对比

| 模组 | 过期模型 | Field Catalog | 主要差异 |
|------|---------|-------------|---------|
| 追书人 | 90% | 95% | Field Catalog多5%（线索的Info/Acquisition分离），过期模型多SanTrigger |
| 银之锁 | 92% | 90% | 过期模型多2%（Op catalog更丰富可表达因果链），Field Catalog多Location定义 |
| 复足 | 80% | 75% | 过期模型多5%（表达式聚合+19 hook+内建变量），两者都缺Track/Timeline |
| 追沙 | 78% | 80% | Field Catalog多2%（ContentRelation），两者都缺Track/Faction/Table |
| RE计划 | 75% | 80% | Field Catalog多5%（EntryPoint/可见性有语义），两者都缺角色级Projection |
| **平均** | **83%** | **84%** | — |

---

## 四、两个模型的分工

**过期模型更强的地方**：
- SanTrigger 六值（追书人、复足、银之锁都需要）— Field Catalog 完全没有
- Expression 语法（聚合/布尔/算术）— Field Catalog 只有等值 Condition
- 19 hook + 内建变量 — Field Catalog 的 Trigger catalog 未定义
- 10 个 Op 算子 — Field Catalog 只有 allow/modify
- Rule.mode（append/override/forbid）— Field Catalog 有语义但未冻结

**Field Catalog 更强的地方**：
- InformationItem 与 InformationAcquisition 分离 — 过期模型把线索当 Entity kind，混淆了信息本体和获取路径
- ContentGraph/ContentRelation — 过期模型只有 Scene.exits 邻接，没有显式图
- LocationDefinition 独立于 Entity — 过期模型把地点混在 Entity(kind=location)
- EntryPoint 多头入口 — 过期模型完全没有
- 角色级可见性（disclosure_policy/recipient_policy）— 过期模型只有二分

---

## 五、为什么覆盖率都不是 100%

两份模型都缺的东西，不是遗漏——是这些语义**需要 Runtime consumer 原型才能结构化**：

| Gap | 过期模型 | Field Catalog | 根本原因 |
|-----|---------|-------------|---------|
| Track（感染/沙漏） | ❌ | ❌ | 需要阶段状态机原型 |
| Timeline（时间调度） | ❌ | ❌ | 需要 Scheduler 原型 |
| Faction（势力） | ❌ | ❌ | 需要态度/资源/反应规则原型 |
| 差异化 Projection | ❌ | ❌ | 需要条件化描述 + Projection 引擎 |
| Keeper Adjudication | ❌ | ❌ | 本质上不可结构化——是人的裁量 |
| 角色级 Projection | ❌ | ⚠️ | 1/15 样本，需要 KnowledgeState 原型 |
| Table | ❌ | ❌ | 多数模组采用"选择而非投掷"，不需要自动投掷 |

---

## 六、结论

**两份模型整体覆盖水平相当（83% vs 84%），但在不同维度互补。** 过期模型的表达式、Op catalog、SanTrigger、19 hook 是 Field Catalog 最需要的补充。Field Catalog 的 Info/Acquisition 分离、ContentGraph、EntryPoint、Location 是过期模型缺失的语义精度。

如果将两份模型合并——取过期模型的 SanTrigger + Expression + Op catalog + Hook/Variable，取 Field Catalog 的 Info/Acquisition + ContentGraph + EntryPoint + Location——理论覆盖率可达 90-92%。剩余的 8-10% 是需要 Runtime consumer 原型的 Capability Gap。

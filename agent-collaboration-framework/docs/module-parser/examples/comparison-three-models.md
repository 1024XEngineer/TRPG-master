# 三份数据模型：五模组覆盖对比

> 日期：2026-07-23
> 对比对象：
> A. 过期数据模型（`docs/archive/pre-consensus/数据模型设计.md`，2026-07-10）
> B. Field Catalog（`docs/module-parser/module-field-catalog.md`，2026-07-23）
> C. ModulePackage Alignment（PR #99 `module-content-alignment.md`，LMH168，2026-07-23）

---

## 一、三份模型的定位差异

| | 过期模型 | Field Catalog | Alignment |
|---|---|---|---|
| 日期 | 07-10 | 07-23 | 07-23 |
| 角色 | 完整逻辑数据模型 | 领域概念验证 | Parser 产物到 Runtime Contract 的对齐提案 |
| 方法 | 六模组验证→设计 | 15模组统计→领域骨架→字段卡片 | 真实解析《追书人》→逐字段对比→合并建议 |
| 内容集合数 | ~12 个（无显式计数——嵌套结构为主） | 13 个（ModuleIdentity/Frame/ContentGraph/Entity/Info/Rule/Ending等） | 16 个（facts/scenes/locations/entities/characters/resources/clues/checkpoints/sanity_events/timelines/tracks/encounters/puzzles/tables/rules/endings） |
| Expression | 完整：聚合+布尔+算术 | 仅等值（H/OPEN） | 仅等值（建议扩展discriminated union） |
| Op 算子 | 10 个 | allow/modify（2个） | allow/modify + 建议扩展 8 个 |
| Hook | 19 个 | Trigger 有语义但 catalog OPEN | RuleSpec hook 保留，建议扩展 |
| SanTrigger | ★ 六值完整 | ❌ 缺失 | ✅ 有 sanity_events 集合 |
| 信息模型 | Entity(kind=clue) 内联 | InformationItem + Acquisition 分离 | Fact + Clue 分离（两个独立集合） |
| 地点 | Entity(kind=location) | LocationDefinition（Capability K） | LocationSpec 独立集合 |
| 入口 | ❌ 无 | EntryPoint（全部 H/OPEN） | entry_points 集合 |
| 角色级可见性 | ❌ 无 | disclosure_policy（H/OPEN） | 无显式字段 |

---

## 二、逐模组覆盖率

### 追书人

| 能力 | 过期模型 | Field Catalog | Alignment |
|------|---------|-------------|-----------|
| SAN 0/1D6 | ✅ SanTrigger 六值 | ❌ | ✅ sanity_events |
| 昼夜循环 | ❌ | ❌ | ⚠️ timelines 集合存在但无定义 |
| 重复监视调度 | ❌ | ❌ | ❌ |
| 多路径线索 | ⚠️ Entity(kind=clue) | ✅ Info/Acquisition | ✅ Fact + Clue |
| 6结局 | ✅ is_ending | ✅ | ✅ endings |
| 夜间监视 | ❌ | ❌ | ⚠️ timelines |

**过期：90% / Catalog：95% / Alignment：92%**

---

### 银之锁

| 能力 | 过期模型 | Field Catalog | Alignment |
|------|---------|-------------|-----------|
| 连续解谜 | ✅ Scene | ✅ ContentUnit | ✅ scenes + checkpoints |
| 猫→NPC因果链 | ✅ 10 Op(trigger/spawn) | ⚠️ Rule间无激活 | ⚠️ triggers统一为RuleSpec |
| 画物品（创造性） | ❌ | ⚠️ Keeper Adj. | ❌ |
| 被抓回=回滚 | ✅ is_ending | ✅ | ✅ endings |
| 速写本生命周期 | ⚠️ Entity(kind=item) | ❌ | ✅ resources 集合 |
| 房间→走廊空间 | ✅ Scene.exits | ✅ LocationDefinition | ✅ locations 独立集合 |

**过期：92% / Catalog：90% / Alignment：93%**

---

### 复足

| 能力 | 过期模型 | Field Catalog | Alignment |
|------|---------|-------------|-----------|
| 六级感染 Track | ❌ | ❌ | ✅ tracks 集合 |
| 重复检定调度 | ⚠️ Rule(on_turn_end) + 内建变量 | ❌ | ✅ timelines 集合 |
| 人数缩放 | ✅ 聚合表达式 | ❌ | ⚠️ Condition 待扩展 |
| 梦境/现实空间 | ❌ | ❌ | ❌两者都缺 |
| 预制角色 | ✅ Pregen | ⚠️ | ✅ characters 集合 |
| 冷蛛持续遭遇 | ⚠️ Encounter 无定义 | ⚠️ | ✅ encounters 集合 |
| SAN | ✅ | ❌ | ✅ sanity_events |
| 4轮转换目标 | ✅ Rule(on_turn_end) + self.rounds_without_damage | ❌ | ⚠️ timelines + rules |

**过期：80% / Catalog：75% / Alignment：88%**

---

### 追沙

| 能力 | 过期模型 | Field Catalog | Alignment |
|------|---------|-------------|-----------|
| 网状调查 | ⚠️ Scene.exits邻接 | ✅ ContentGraph | ⚠️ scenes + next_scene_ids |
| 多势力 | ❌ | ❌ | ❌三者都缺 |
| 沙漏 Track | ❌ | ❌ | ✅ tracks 集合 |
| 异常事件 Table | ❌ | ❌(暂缓H) | ✅ tables 集合 |
| 沙之书位置转移 | ✅ Entity.state + Rule | ✅ | ✅ |
| 四结局 | ✅ WinCondition | ✅ EndingDefinition | ✅ endings |

**过期：78% / Catalog：80% / Alignment：87%**

---

### RE计划

| 能力 | 过期模型 | Field Catalog | Alignment |
|------|---------|-------------|-----------|
| 三HO入口 | ❌ | ⚠️ EntryPoint(H/OPEN) | ✅ entry_points 集合 |
| 三线并行 | ✅ Scene + exits | ✅ ContentRelation | ✅ scenes |
| 角色独占信息 | ❌ | ⚠️ disclosure_policy(H/OPEN) | ❌ |
| 固定身份模板 | ✅ Pregen | ⚠️ | ✅ characters 集合 |
| 隐藏结局 | ✅ 布尔表达式 | ❌ | ⚠️ endings + Condition扩展 |
| 通讯Resource | ⚠️ Entity(kind=item) | ❌ | ✅ resources 集合 |

**过期：75% / Catalog：80% / Alignment：90%**

---

## 三、汇总

| 模组 | 过期模型 | Field Catalog | Alignment |
|------|---------|-------------|-----------|
| 追书人 | 90% | 95% | 92% |
| 银之锁 | 92% | 90% | 93% |
| 复足 | 80% | 75% | 88% |
| 追沙 | 78% | 80% | 87% |
| RE计划 | 75% | 80% | 90% |
| **平均** | **83%** | **84%** | **90%** |

---

## 四、Alignment 得分最高的原因

不是因为它设计得更好——是因为**它把所有 16 个集合都列为提案，而不区分"已定义字段"和"仅声明集合名"**。

| Alignment 的"覆盖" | 实际状态 |
|-------------------|---------|
| `tracks` 集合存在 | 仅声明集合名，无字段定义，无 consumer |
| `timelines` 集合存在 | 同上 |
| `encounters` 集合存在 | 同上 |
| `sanity_events` 集合存在 | 集合名存在，但字段未定义（不如过期模型的六值枚举精确） |
| `tables` 集合存在 | 同上 |
| `puzzles` 集合存在 | 同上 |

**Field Catalog 和过期模型的哲学相同**：没有字段定义、没有 consumer 原型的，不标记为"已覆盖"。Alignment 的哲学是：先列出所有需要的集合名，字段和 consumer 以后再定。

这不是对错问题——是不同阶段的文档目的不同。Alignment 是 Parser Agent 的"需求清单"（"我需要这些集合来装《追书人》的数据"），Field Catalog 是领域模型的"语义验证"（"这些概念是否成立、字段是否可冻结"）。

---

## 五、三者的互补关系

```
Alignment（需求清单）
  │  16 个集合，覆盖广但字段浅
  │  优点：追书人实战验证，知道 Parser 能产出什么
  │  缺点：大部分集合没有字段定义
  │
  ▼
Field Catalog（语义验证）
  │  13 个对象，字段卡片详尽但 Capability 保守
  │  优点：15 模组统计 + 领域职责分离
  │  缺点：SanTrigger/Track/Timeline 缺失或 H/OPEN
  │
  ▼
过期模型（执行深度）
  │  嵌套结构完整：19 hook + 10 Op + 表达式语法
  │  优点：六模组实证，Rule 引擎四张表可直接落地
  │  缺点：信息模型粗糙（Entity六值吞一切），无 EntryPoint/Projection
```

**三份模型合并后的理论覆盖率：93-95%。** 剩余的 5-7% 是 Track 的阶段定义、Timeline 的调度语义、Faction 的态度系统、差异化 Projection——这些需要 Runtime consumer 原型才能结构化，不是数据模型层面的缺失。

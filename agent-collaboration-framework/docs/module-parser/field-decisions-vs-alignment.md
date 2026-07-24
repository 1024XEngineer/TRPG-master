# 最终字段决策 vs Alignment：一致与不一致

> 日期：2026-07-23
> A：`module-content-field-decisions.md`（本文，锚定当前 contracts）
> B：`module-content-alignment.md`（PR #99，锚定 ModulePackage）

---

## 一、一致的部分

### 顶层字段

| 字段 | A | B | 一致 |
|------|---|---|------|
| `module_id` | 保留 | 只保留 ModuleContent 的 | ✅ |
| `version` | 保留 | 只保留 ModuleContent 的 | ✅ |
| `world_ref` | 保留，P2 考虑升级 | 保留，建议升级为 `ruleset_ref` | ✅ 方向一致，时机不同 |
| `ruleset_ref` | Defer——等 B 确认 Provider | P0 就加 | ⚠️ 一致认为需要，但对"什么时候加"不同 |
| `entry_scene_id` | Defer——等 Loader 原型 | P0 就加 | ⚠️ 同上 |

### RuleSpec

| 字段 | A | B | 一致 |
|------|---|---|------|
| `mode`（append/override/forbid） | P0 加 | 没有独立讨论 mode，但要求"Rule 统一为 RuleSpec" | ⚠️ A 直接给出了字段，B 没到这个粒度 |
| Trigger 统一为 RuleSpec | Accept（Rule 自带 hook） | P0 统一 | ✅ |

### CheckpointSpec

| 字段 | A | B | 一致 |
|------|---|---|------|
| `difficulty` 可空 | P0 | 保留，未讨论可空 | ⚠️ A 更明确 |
| `mvp_check_result` 移出 | P2 移除 | P0 移出 | ✅ 一致，时机不同 |
| `outcomes` 统一 | 保留 | 统一为 `outcomes` | ✅ |
| `prerequisites` | Defer | 新增加 | ⚠️ B 要加，A 等原型 |
| `repeat` | Defer | 新增加 | ⚠️ 同上 |
| `time_cost` | Defer | 新增加 | ⚠️ 同上 |

### WinCondition / Ending

| 字段 | A | B | 一致 |
|------|---|---|------|
| 从"胜利"升级为"终局"语义 | Accept | P0 | ✅ |
| `is_ending` | P0 加 | 没这个字段，通过重命名为 `EndingSpec` 隐含 | ⚠️ A 在当前模型上加字段；B 要破坏性重命名 |
| 重命名为 `EndingSpec/endings` | Defer——major version | P0 就改名 | ❌ |

### 信息模型

| 字段 | A | B | 一致 |
|------|---|---|------|
| 线索需要独立于 Entity | Accept | P1 新增 `ClueSpec` | ✅ |
| Fact 需要正式定义 | Defer——等 KnowledgeState | P0 新增 `FactSpec` | ⚠️ 都认为需要，A 等 consumer |

---

## 二、不一致的部分

### 1. 推进节奏：B 激进，A 保守

B 把 16 个集合全部列入 P0/P1，不区分"有字段定义"和"仅集合名占位"。A 只有 4 个 P0 改动，其余全部 Defer 并给出明确的解锁条件。

| 对比项 | A（最终决策） | B（Alignment） |
|--------|-------------|---------------|
| P0 改动 | 4 处（mode/expr/difficulty/is_ending） | 10 处（重命名、新集合、迁移） |
| P1 改动 | 4 处（san_triggers/module_rules/exits/stat_block） | 7 处（Clue/Location/Resource/SanityEvent/keeper_brief/Loader/PlayerView） |
| 新集合数 | P0: 0, P1: 2（san_triggers, module_rules） | P0: ~5, P1: ~7 |
| 破坏性变更 | 0（P0 全向后兼容） | 2（Scene→统一、WinCondition→Ending、Entity→拆Location/Resource） |
| 等 consumer？ | 每个 Defer 标注阻塞条件和原型 | 不标注——先加集合名，以后补字段 |

### 2. ModulePackage 概念：B 有，A 没有

B 设计了 `ModulePackage` 作为 Parser 的完整发布包（含 source_manifest、keeper_brief、runtime_defaults、initial_state、assets、normalization_decisions、validation）。A 认为这些属于 Parser 流水线/Publish 审计层，**不属于 B/C 共享的 ModuleContent 运行契约**——所以 A 的最终决策中没有任何 ModulePackage 字段。

这是两份文档最根本的差异：**B 的"对齐"把 Parser 发布包和 Runtime 运行契约放在同一个文档里对齐；A 的"决策"只覆盖 B/C 共享的 ModuleContent 运行契约。**

### 3. Condition：B 要 discriminated union，A 要 expr escape hatch

B 建议扩展为 discriminated union（StateEquals/ClueOwned/SceneIs/PlayerChoice/CheckResult），先行设计完整 Condition 类型体系。A 只加一个 `expr: str | None` 字段——等 Expression parser 统一后替换，不建设第二套 Condition 类型。

**差异根源**：B 面向 Parser Agent 需要"生成哪种 Condition"；A 面向 Runtime Engine 需要"如何求值一个 Condition"。同一条 Condition，Parser 视角是类型标签，Runtime 视角是表达式 AST。

### 4. Entity：B 要拆 Location/Resource，A 保持现状

B 建议从 Entity 拆出 `LocationSpec` 和 `ResourceSpec` 为独立顶层集合。A Defer——当前 demo 只有一个场景，`Entity(kind="location")` 够用。等 B 的 navigation consumer 和 Resource consumer 原型就绪后再拆。

**差异根源**：B 被追书人的 5 个地点和 4 个 Resource 驱动；A 被"当前代码测试通过"约束。

### 5. Operation：B 要扩展到 8 个，A 保持 2 个

B 建议加 `grant_clue/move_entity/transition_scene/advance_time/request_sanity_check/start_encounter/trigger_ending/consume_resource`。A 当前只有 `allow/modify`，其余 Defer——等 B 确认 Op catalog 消费方式。

**差异根源**：B 面向"Parser 需要声明什么效果"；A 面向"Engine 当前能执行什么操作"。

### 6. 破坏性重命名：B 要 P0 做，A 要 major version 做

B 建议 P0 统一：`Scene→统一字段`、`win_conditions→endings`。A Defer——破坏性重命名进入下一个 Contract major version，当前不引入第二套命名。

---

## 三、根本差异：文档定位不同

| | A（最终字段决策） | B（Alignment） |
|---|---|---|
| 定位 | 当前 contracts 的改动清单 | Parser 产物到 Runtime Contract 的需求对齐 |
| 锚点 | `contracts/module.py` 的行号 | `module-package.template.json` 的字段 |
| 变更粒度 | 4 个 P0 字段改动 | 16 个集合的重组方案 |
| 破坏性 | 零 | 多次（重命名、拆表、新增顶层集合） |
| 消费者约束 | 每个 Defer 标注"等谁的什么原型" | 不标注 |
| 何时合并冲突 | 不改当前概念名 | P0 就重命名 |

**不是谁对谁错。** B 是"如果从头设计，目标态应该长这样"——它画的是终点。A 是"从当前代码开始，现在可以改什么，什么必须等"——它画的是从起点到终点的每一步。两者可以并存：B 的 16 集合结构作为 P2 的目标蓝图；A 的 P0/P1/Defer 作为每次 PR 的实施清单。

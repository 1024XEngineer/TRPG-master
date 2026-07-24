# TRPG Data Contract Specification

- 文档状态：Current v1 Boundary Specification
- 规范版本：1.0.0-draft
- 更新日期：2026-07-23
- 适用范围：Module Parser、Validation、Review、Publish、Rule Engine、Runtime、Host Projection
- 架构决策：`unified-trpg-data-contract-adr.md`
- 当前可执行权威：`agent-collaboration-framework/collaboration_framework/contracts/module.py`

> 文档关系：本文继续描述当前 v1 已实现边界；多模组统一目标模型与候选字段准入分析见 [`../agent-collaboration-framework/docs/architecture/data-model-alignment-rfc.md`](../agent-collaboration-framework/docs/architecture/data-model-alignment-rfc.md)。目标 RFC 尚未成为可执行 Contract。

> 本文定义当前 v1 `ModuleContent` 的职责边界、消费关系和演进门槛，不定义一套脱离代码的最终 JSON Schema。
>
> 当前字段、类型和约束以 `contracts/module.py` 为唯一可执行权威。本文与代码冲突时，以代码为准，并修正文档。
>
> PR99、旧领域模型和真实模组分析用于发现 Capability Gap，不会自动成为 `ModuleContent` 字段。

## 1. 目标与边界

项目目标链路：

```text
PDF / DOCX / Markdown / TXT
→ DocumentAdapter
→ NormalizedDocument / SourceFragment[]
→ ParserResult(ModuleDraft + provenance + gaps)
→ Validation
→ ModuleContent
→ Publish canonical JSON
→ Runtime + GameState
→ ProjectionSnapshot / ActionResult
→ Host Projection
```

`ModuleContent` 是 Parser、Validation 与 Runtime 之间唯一共享的静态模组 Contract。

它只保存：

- 模组身份与 Ruleset 引用；
- Runtime 已支持的静态内容声明；
- 可确定性验证和执行的 Condition、Rule、Operation、Checkpoint 与终局条件；
- Runtime 确认结果后可以安全投影给 Host 的信息和叙事约束。

它不保存：

- 原始文件、OCR、页码、bbox 或 SourceFragment；
- Parser provenance、模型、Prompt、confidence 或 normalization decision；
- ValidationReport、ReviewReport 或发布审批状态；
- Repository rights、visibility 或存储路径；
- Room、GameState、Event、骰点、ActionRequest 或 ExecutionResult；
- 测试专用的强制成功/失败控制。

## 2. 数据层级

### 2.1 Domain Model

Domain Model 描述 TRPG 模组可能包含的领域概念，例如：

- Module、Ruleset；
- Scene、Location；
- Entity、Character、Resource；
- Fact、Clue、Secret；
- Checkpoint、Rule、Condition、Operation、Outcome；
- Timeline、Track、Encounter；
- Ending。

领域概念存在，不代表它必须立即成为 `ModuleContent` 一级模型。

### 2.2 ModuleContent Contract

一个概念只有同时满足以下条件，才能进入受支持的共享 Contract：

1. Parser 有稳定提取方法；
2. Validation 有确定性校验；
3. Runtime 有明确消费者和执行语义；
4. Projection 定义了秘密与玩家可见边界；
5. 端到端测试证明该语义被完整消费；
6. 已确定版本兼容和迁移方式。

### 2.3 Runtime Model

以下数据只属于 Runtime：

- Room、Player、Actor/Character 当前状态；
- 当前 Scene、phase 和 ending_id；
- Entity 当前状态；
- Check result、StateChange 和 EventLog；
- Rule/Hook 编译索引和执行上下文；
- ActionRequest、ActionResult、ExecutionResult；
- 幂等缓存和投影 revision。

这些数据按 Room 变化，不能写回不可变 `ModuleContent`。

### 2.4 Test Fixture

以下数据只用于测试：

- 固定骰值或强制成功/失败；
- Fake RulesetSnapshot；
- 已初始化的 `demo-state.json`；
- 预期 State Diff、EventLog 和终局结果；
- 故意构造的非法引用或字段。

## 3. 生命周期产物

| 产物 | 所有者 | 主要消费者 | 是否进入 Runtime |
|---|---|---|---:|
| RawDocument | Parser Pipeline | DocumentAdapter | 否 |
| NormalizedDocument / SourceFragment | Parser Pipeline | Parser、Review | 否 |
| ModuleDraft | Parser | Validation | 否 |
| ParserResult / provenance | Parser | Review、审计 | 否 |
| ValidationReport | Validation | Publish、Review | 否 |
| ReviewReport | Review | 目标生产发布门禁 | 否 |
| ModuleContent | Parser/Engine 共享 | Publish、Runtime | 是 |
| Canonical JSON | Publish | Runtime | 是 |
| Publication metadata / hash | Publish/Repository | Repository、Loader | 否，不属于内容本体 |
| GameState / Event | Runtime | Runtime、Projection | Runtime 内部 |
| PlayerView / ActionResult | Projection/Runtime | Host | 安全投影 |

## 4. 当前 v1 ModuleContent

### 4.1 顶层字段

当前 v1 只包含以下顶层字段：

| 字段 | 职责 | 生产者 | 消费者 | 当前状态 |
|---|---|---|---|---|
| `module_id` | 模组稳定身份 | Parser/导入流程 | Loader、Runtime | Current |
| `version` | 模组内容版本 | Parser/发布流程 | Loader | Current |
| `world_ref` | 规则系统引用 | Parser | Validation、组合根 | Current；正式 Provider 待接入 |
| `scenes` | 叙事上下文与候选引用 | Parser | Runtime、Projection | Verified |
| `entities` | 可交互对象、初始状态和局部规则 | Parser | Runtime、Projection | Verified |
| `checkpoints` | 模组声明的检定机会与结果模板 | Parser | Runtime、Projection | Verified；真实骰点待实现 |
| `win_conditions` | 当前 v1 的正式终局声明 | Parser | Runtime | Verified |

本文不把 `contract_version`、`content_hash`、`metadata`、`entry_points`、`locations` 或 PR99 的其他集合声明为当前 v1 字段。

### 4.2 Scene

当前 `SceneSpec` 的职责是表达一个叙事和交互上下文。

| 字段 | 职责 | 消费者 |
|---|---|---|
| `id` | 稳定引用 | Validation、Runtime |
| `name` | 展示名称 | Projection |
| `content` | 玩家安全场景描述 | Projection、Host |
| `entity_ids` | 当前 Scene 关联的 Entity | Runtime、Projection |
| `checkpoint_ids` | 当前 Scene 可用的模组 Checkpoint | Runtime、Projection |

Scene 不保存当前是否进入、玩家位置或已发现状态，这些属于 GameState。

### 4.3 Entity

当前 `EntitySpec` 表达具有身份、可交互内容、初始状态或局部规则的模组对象。

| 字段组 | 职责 | 消费者 |
|---|---|---|
| `id/kind/name/aliases` | 身份、分类和目标匹配 | Runtime、Projection |
| `content` | 玩家安全描述 | Projection、Host |
| `secrets` | 未公开的模组知识 | 受控 Context Builder，不进入 PlayerView |
| `state` | 状态键声明及每局初始值 | Validation、未来 Loader |
| `refuse_ops/blocked_text` | 动作拒绝策略及可见结果 | Runtime、Host |
| `direct_responses` | 无检定直接交互结果 | Runtime、Host |
| `rules` | Entity 关联的静态规则 | Runtime |

`Entity.state` 与运行状态的关系：

```text
ModuleContent.Entity.state = 初始状态声明
GameState.entities         = 某个 Room 的当前状态
```

当前 Phase 1 使用外部 `demo-state.json` 提供已初始化 GameState，尚未实现自动 Room 或 Entity state 初始化。

### 4.4 Rule、Condition 与 Operation

当前 v1 使用：

- `ConditionSpec(path, equals)`；
- `AllowOperationSpec`；
- `ModifyOperationSpec`；
- `RuleSpec(id, hook, priority, when, then, facts, player_visible_information)`。

Rule 是模组对 Runtime 执行阶段的声明，不是 Parser 私有对象；Runtime 私有的是 Hook 索引、EvalContext、事务和 Event。

当前 `Rule.hook` 状态：

| 能力 | 状态 |
|---|---|
| Contract 声明四种 hook | Declared |
| Validation hook catalog | Implemented |
| action 流程按 hook 正确过滤 | 未实现 |
| 四种 hook 的独立 dispatcher | 未实现 |
| 完整 Runtime 支持 | 不成立 |

因此 `Rule` 属于 Current，但 hook dispatcher 属于 Runtime Gap。Validation 不得接受 Runtime 无法正确执行的 hook，除非明确记录为 CapabilityGap 并阻断正式发布。

### 4.5 Checkpoint

Checkpoint 是静态的“可检定交互机会”，不是某次 Runtime Action。

```text
CheckpointSpec（模组声明）
→ Intent / ActionRequest（玩家本次动作）
→ CheckResult / Outcome / Events（Runtime 结果）
```

当前字段职责：

| 字段 | 职责 |
|---|---|
| `id` | Checkpoint 身份 |
| `scene_id` | 所属 Scene |
| `action` | Host 语义匹配提示，不是封闭动词枚举 |
| `target_id` | 交互目标 |
| `skills` | 可提议的合法技能候选 |
| `difficulty` | 当前 v1 固定且不可空的难度 |
| `outcomes` | success/failure 的静态结果模板 |
| `mvp_check_result` | 测试过渡字段，不属于生产语义 |

正式生产 Contract 应在具备可注入 CheckResolver 后移除 `mvp_check_result`；本规范不直接修改当前代码。

### 4.6 Outcome 可见信息

`facts`、`player_visible_information` 与 `narration_constraints` 的消费链是：

```text
ModuleContent 声明
→ Runtime 选择实际发生的 Outcome
→ ActionResult 安全转发
→ Host/Narrator 消费
```

- `player_visible_information` 是结果成立后允许公开的信息，不是最终 PlayerView，也不是普通 Prompt metadata；
- `narration_constraints` 是与确定性结果绑定的叙事政策，不是 GameState；
- Host 不得绕过 Runtime 读取尚未发生分支的信息。

### 4.7 WinCondition 与 Ending

当前 v1 使用 `WinConditionSpec/win_conditions`，Runtime 命中后写入 `ending_id` 并将 `phase` 设为 `ended`。

因此当前 `WinConditionSpec` 实际表达的是最小终局声明，不限于“胜利”。

职责规则：

- WinCondition/未来 Ending 只负责正式终局；
- 状态回滚、阶段完成、重试和非终局失败属于 Rule/Operation；
- 当前 v1 继续使用 `win_conditions`；
- 目标版本是否迁移为 `endings` 需要独立破坏性迁移决策；
- 两套终局集合不得长期并存。

## 5. Domain Capability Candidates

真实模组和 PR99 暴露了以下领域能力，但它们目前不是 v1 `ModuleContent` 字段：

| 概念 | 领域职责 | 当前结论 |
|---|---|---|
| Location | 物理空间、层级和连接 | Candidate；等待 navigation 和多人位置用例 |
| Fact/Clue | 真相与获得真相的路径 | Candidate；等待事实投影和防剧透模型 |
| Resource | 持有、消耗、装备或使用的对象 | Candidate；等待 inventory consumer |
| Character/Pregen | 建局角色模板 | Candidate；等待 Loader 与 Ruleset 校验 |
| SanityEvent | CoC 理智机制声明 | Candidate；等待 Ruleset 扩展边界 |
| Timeline | 外部时间和定时事件 | Candidate；等待 scheduler |
| Track | 感染、怀疑、仪式等阶段 | Candidate；等待状态机 consumer |
| Encounter | 持续挑战的编排边界 | Candidate；等待 Runtime Orchestrator |
| Asset | 可发布素材语义引用 | Candidate；等待 Repository 和展示策略 |
| Puzzle/Table | 谜题和随机表 | Deferred |

Candidate 只表示领域需求存在，不表示已经批准为一级模型。

## 6. Scene 与 Location

两者在领域上不同：

- Scene 回答“当前发生什么”；
- Location 回答“发生在哪里”。

两者都不是 Runtime 私有概念，但 v1 只拥有 Scene。当前 `Entity.kind="location"` 可以表达可交互地点对象，不能完整表达空间拓扑。

只有在以下能力出现后，才重新评估独立 Location：

- 地图连接和隐藏路线；
- 同一地点发生多个 Scene；
- 多角色分头位置；
- Runtime navigation；
- 安全地点投影。

## 7. 版本、Hash 与发布

### 7.1 当前版本字段

当前字段名为 `version`，表示模组内容版本。本文不提前将其改名为 `module_version`。

当前 Contract 没有 `contract_version`。是否增加 Contract 版本字段需要单独兼容性决策，不能只通过文档声明。

### 7.2 content_hash

`content_hash` 由 Publish 对规范化 JSON 计算，属于发布记录或 Repository metadata，不属于 `ModuleContent` 内容本体：

```text
ModuleContent
→ canonical JSON
→ content_hash
```

Phase 1 当前不实现 Hash 或 Repository。

### 7.3 发布门禁

当前 Phase 1：

```text
ValidationReport(pass + ModuleContent)
→ minimal Publish
→ canonical JSON
```

目标生产链路：

```text
Validation pass
→ Review pass / no blocking finding
→ Production Publish
```

Review 尚未实现，不能描述为当前已生效门禁。

## 8. 能力状态

文档使用以下状态，避免“字段存在”等于“能力支持”：

| 状态 | 含义 |
|---|---|
| Declared | 字段或类型已在 Contract 声明 |
| Implemented | 至少存在一个真实消费者 |
| Verified | 有测试证明关键执行语义 |
| Supported | Parser、Validation、Runtime、Projection 和端到端测试均完成 |
| Candidate | 只有领域或真实模组需求证据，尚未进入 Contract |
| Deferred | 当前不进入版本计划 |

当前摘要：

| 能力 | 状态 |
|---|---|
| Scene/Entity/Checkpoint 基础闭环 | Verified |
| Condition path/equals | Verified |
| allow/modify Operation | Verified |
| WinCondition 终局 | Verified |
| player visible information / narration constraints | Verified |
| Rule.hook 四种分派 | Declared / Partial，未 Supported |
| 自动 GameState 初始化 | 未实现 |
| 真实骰点与 CheckResolver | 未实现 |
| Location、Resource、Timeline 等 | Candidate |
| Review Gate | Planned |
| Repository / content hash | Deferred for Phase 1 |

## 9. 一致性要求

1. `contracts/module.py` 是当前 v1 唯一可执行 Schema 权威；
2. Runtime 永远不加载 ModuleDraft 或 ParserResult；
3. Validation 是 `ModuleDraft → ModuleContent` 的唯一确定性转换入口；
4. ModuleContent 发布后不可变；
5. Entity 初始状态与 GameState 当前状态必须分离；
6. Checkpoint 声明与某次 Action/CheckResult 必须分离；
7. WinCondition/Ending 只负责终局；
8. `player_visible_information` 和 `narration_constraints` 只能在对应结果实际发生后投影；
9. Parser provenance、Review、rights 和 content hash 不进入 ModuleContent；
10. 未实现概念必须进入 CapabilityGap，不得通过自然语言伪装成已支持硬规则；
11. 同一概念不得同时维护两套顶层集合或两个事实源；
12. 新能力只有达到 Supported 门槛后，才能进入生产发布链。

## 10. 权威声明

事实源优先级：

1. `collaboration_framework/contracts/module.py`；
2. Runtime consumer 和自动化测试；
3. `unified-trpg-data-contract-adr.md` 中已接受的职责决策；
4. 本规范；
5. PR99、旧领域模型和其他讨论稿。

旧领域模型和 PR99 是设计证据，不是可以直接加载的第二套 Runtime Contract。

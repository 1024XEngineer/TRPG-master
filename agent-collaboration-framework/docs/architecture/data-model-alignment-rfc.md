# RFC：统一扩展 ModuleContent 数据模型

- 状态：Proposed，待 Parser / Rule Engine / Host 共同评审
- 日期：2026-07-23
- 目标：定义可覆盖多个 CoC 模组的统一目标 ModuleContent
- 当前实现基线：`collaboration_framework/contracts/module.py`
- 样本依据：追书人、鬼屋、幸福蛙蛙村、银之锁、复足、死者的顿足舞、科比特先生
- 非目标：本文不直接修改代码，不声称目标字段已经 Supported

## 1. 决策方向

团队选择 Contract-first 的统一演进方式：

```text
PDF / DOCX / Markdown
→ ParserResult(ModuleDraft + provenance + gaps)
→ Validation
→ Unified ModuleContent
→ Runtime
→ Host Projection
```

核心决策：

1. `ModuleContent` 继续作为 Parser、Validation、Runtime 之间唯一共享的静态模组 Contract。
2. ModuleContent 不以当前 Fake Runtime 为永久上限；Parser、Validation、Runtime 和 Host 按统一目标共同更新。
3. `ModuleDraft` 与目标 ModuleContent 基本同形，Parser 可以直接生成 Draft。
4. 来源、置信度、模型/Prompt 版本、rights、未决问题和 Capability Gap 放在旁路 `ParserResult`，不进入 ModuleContent。
5. 新增字段必须回答生产者、消费者、消费时机和忽略后果；没有明确消费者的字段不进入目标 Contract。
6. 目标字段分阶段实施；进入文档不等于当前代码已经支持。

## 2. 样本暴露的跨模组能力

| 能力 | 样本证据 | 当前 v1 是否足够 |
|---|---|---:|
| 调查场景与 NPC/物件 | 所有样本 | 部分足够 |
| 物理地点与隐藏路线 | 追书人、鬼屋、银之锁、复足 | 否 |
| Fact/Clue 与多路径调查 | 追书人、鬼屋、死者的顿足舞 | 否 |
| 动态检定、孤注一骰、暗骰和重复检定 | 鬼屋、追书人、幸福蛙蛙村 | 否 |
| SAN 检定、固定损失、恢复和累计上限 | 多个 CoC 样本 | 否 |
| 时间成本、昼夜和多日事件 | 追书人、鬼屋、幸福蛙蛙村、复足 | 否 |
| 感染、怀疑、异变等阶段状态 | 复足、幸福蛙蛙村 | 否 |
| 战斗、追逐、谈判和环境挑战 | 鬼屋、死者、科比特先生 | 否 |
| 可获得、消耗或研读的资源 | 追书人、鬼屋、银之锁、科比特先生 | 部分可用 Entity 表达 |
| 预生成角色或角色背景要求 | 复足、银之锁、追书人 | 否 |
| 多种正式终局 | 追书人、银之锁、科比特先生 | 当前只能表达简单 path/equals 终局 |
| 地图、插图和手稿揭示 | 追书人、复足、鬼屋 | 否 |

这些能力是目标 Contract 的设计输入，不代表全部进入首个实现批次。

## 3. 字段准入规则

每个目标字段必须回答：

1. 谁生产？
2. 谁消费？
3. 什么时候消费？
4. 如果忽略它，模组还能否正确运行？

决策分类：

| 分类 | 含义 |
|---|---|
| Include / Execution | 影响玩法，必须由 Runtime 执行 |
| Include / Load | 建局或加载时消费 |
| Include / Projection | Runtime/Host/UI 安全投影消费 |
| Sidecar | Parser、Review、Publish 或 Repository 信息，不进入 ModuleContent |
| Deferred | 有领域价值，但消费者或语义尚未收敛 |

## 4. 统一目标 ModuleContent 概念结构

以下是目标概念结构，不是最终 JSON Schema：

```text
ModuleContent
├── identity
├── ruleset_ref
├── metadata
├── entry_points
├── scenes
├── locations
├── entities
├── resources
├── character_templates
├── facts
├── clues
├── checkpoints
├── rules
├── sanity_events
├── timelines
├── tracks
├── encounters
├── endings
├── assets
└── initial_state_template
```

具体字段名称、必填性和类型需要在各纵向能力实施前通过子 RFC 冻结。

## 5. 顶层与加载字段评估

### 5.1 identity

候选内容：module ID、内容版本和 Contract 兼容版本。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor 提议，Publish 固化 |
| 谁消费 | Repository、Loader、Runtime compatibility gate |
| 什么时候消费 | 导入、发布和 Runtime load |
| 忽略后果 | 无法识别模组、版本和兼容性；可能加载错误结构 |
| 决策 | Include / Load |

当前 `module_id/version` 保留。Contract 版本字段是否进入内容本体或发布 envelope，需要单独冻结。

### 5.2 ruleset_ref

候选内容：规则系统身份、版本和所需 capability catalog。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser 根据模组声明生成，Ruleset Provider 提供 canonical ID |
| 谁消费 | Validation、Loader、Rule Engine、Host Projection |
| 什么时候消费 | Validation、Runtime load 和检定执行 |
| 忽略后果 | 技能、属性、SAN、Condition 和 Operation 可能按错误规则解释 |
| 决策 | Include / Execution |

当前 `world_ref` 可作为迁移起点；`world_ref` 与 Ruleset 的最终命名和映射需 B/C 共同冻结。

### 5.3 metadata

候选内容：标题、简介、时代、人数、预计时长、角色要求和内容提示。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Repository、开房流程、前端、Host Context Builder |
| 什么时候消费 | 模组选择、建局和 Session 开始 |
| 忽略后果 | 通常不破坏规则执行，但可能导致人数或角色要求不合法、内容提示缺失 |
| 决策 | Include / Load + Projection |

Parser model、confidence、source hash 和 rights 不属于这里，继续放 Sidecar。

### 5.4 entry_points

候选内容：默认入口和可选入口对应的 Scene/Location。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Loader、开房流程、Runtime |
| 什么时候消费 | 创建 GameState 时 |
| 忽略后果 | Runtime 不知道从哪里开始，多入口模组可能错误启动 |
| 决策 | Include / Load |

## 6. 内容对象评估

### 6.1 Scene

职责：叙事和交互上下文，回答“当前发生什么”。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Runtime、Projection、Host |
| 什么时候消费 | Scene 进入、动作候选投影和叙事 |
| 忽略后果 | Host 缺少上下文，Checkpoint 和可见 Entity 无法路由 |
| 决策 | Include / Execution + Projection |

保留当前 Scene 核心能力，目标上允许关联 Location、Fact/Clue、Resource、Encounter 和 Rule。

### 6.2 Location

职责：物理空间、层级、出口和隐藏路线，回答“在哪里”。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser 根据正文和地图提取 |
| 谁消费 | Loader、Runtime navigation、GameState 位置、Map UI、Host Projection |
| 什么时候消费 | 建局、移动、进入/离开地点、地图揭示 |
| 忽略后果 | 银之锁的房间—长廊边界、鬼屋房间拓扑、复足楼层和追书人隐藏入口可能无法正确运行 |
| 决策 | Include / Execution；独立于 Scene |

Scene 与 Location 不重复：同一地点可以发生多个 Scene，一个 Scene 也可能覆盖多个地点。

### 6.3 Entity

职责：NPC、怪物、动物、群体和普通可交互对象。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Runtime、Rule Engine、Projection、Host |
| 什么时候消费 | 目标匹配、规则执行、状态读取和叙事 |
| 忽略后果 | 交互目标、秘密和规则宿主丢失 |
| 决策 | Include / Execution + Projection |

目标 Entity 保留通用身份、公开内容、秘密、初始状态、规则和可选 Ruleset stat block。Character 是否继续作为 Entity kind，还是独立集合，需要在角色纵向切片中冻结。

### 6.4 Resource

职责：可获得、持有、消耗、研读、装备或使用的模组对象。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Loader、Inventory/Resource Runtime、Projection、Host |
| 什么时候消费 | 获得、使用、消耗、研读和检查前置条件时 |
| 忽略后果 | 追书人的酒和日记、银之锁的速写本、鬼屋/科比特先生的典籍与法术无法可靠结算 |
| 决策 | Include / Execution |

普通场景摆件仍可作为 Entity；只有存在 Resource 生命周期的对象进入 Resource。分类规则需子 RFC 固化。

### 6.5 Character Templates

职责：模组要求的预生成角色、背景绑定和建卡约束。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Character creation、Loader、Host |
| 什么时候消费 | 开房和创建角色时 |
| 忽略后果 | 复足预生成角色、银之锁的重要之物绑定和单人模组要求可能丢失 |
| 决策 | Include / Load；运行角色实例仍属于 GameState |

## 7. 调查信息评估

### 7.1 Fact

职责：模组世界中客观成立的真相。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Rule Engine 的事实授权、Projection、Host、Review |
| 什么时候消费 | Clue 获得、规则求值和安全叙事时 |
| 忽略后果 | Host 无法区分真实真相、玩家已知信息和未解锁秘密，容易泄密或漏掉关键因果 |
| 决策 | Include / Execution + Projection |

Fact 必须与某次 Outcome 的 confirmed fact/Event 分离：前者是静态真相定义，后者是运行事实。

### 7.2 Clue

职责：玩家获得 Fact 的观察、材料或路径。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Runtime、Player knowledge state、Projection、Host |
| 什么时候消费 | 调查成功、阅读、对话或自动揭示时 |
| 忽略后果 | 多路径调查被压成线性状态布尔值，核心线索可达性和防剧透无法验证 |
| 决策 | Include / Execution + Projection |

Fact 与 Clue 不合并：Fact 是“真相是什么”，Clue 是“如何获得或证明真相”。

## 8. 规则与检定评估

### 8.1 Rule / Hook / Condition / Operation

职责：用有限声明语言表达模组硬规则。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor；catalog 由 Ruleset/Runtime 提供 |
| 谁消费 | Validation、Rule Engine |
| 什么时候消费 | 对应 Runtime hook 到达时 |
| 忽略后果 | 动态机制不会执行或在错误时机执行 |
| 决策 | Include / Execution |

目标规则语言继续采用有限 catalog，不允许任意脚本。每个 Hook、Condition 和 Operation 必须由 Runtime 注册并由 Validation 使用同一 catalog。

当前四种 hook 只是声明，dispatcher 尚未完整实现；目标 Hook 集合需要按纵向能力逐个落地。

### 8.2 Checkpoint

职责：模组预先声明的检定、对抗或 Keeper 判断节点。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Host Intent、Validation、CheckResolver、Rule Engine |
| 什么时候消费 | 玩家行动匹配、难度计算和结果结算时 |
| 忽略后果 | 技能、难度、代价和作者规定结果会由 Host 临时猜测 |
| 决策 | Include / Execution |

目标能力需要覆盖：

- 技能或属性候选；
- 固定或受限动态难度；
- success/failure/fumble 等 Ruleset 结果；
- bypass 条件；
- repeat/pushed roll；
- time/resource cost；
- hidden/auto/prompt 等交互模式；
- 结构化 Outcome。

某次骰点、成功等级和 CheckResult 仍只属于 Runtime State。`mvp_check_result` 必须移出目标生产 Contract。

### 8.3 Sanity Event

职责：CoC 特有的 SAN 检定、直接损失、固定损失、恢复、上限变化和累计封顶。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser 根据模组原文生成，Ruleset 提供语义类型 |
| 谁消费 | CoC Ruleset Runtime、Character state、Projection、Host |
| 什么时候消费 | 目击、理解、阅读、奖励或规则触发时 |
| 忽略后果 | CoC 核心风险和奖励被丢失，模组无法正确运行 |
| 决策 | Include / Execution，建议作为 Ruleset extension 而非通用硬编码 |

## 9. 时间、阶段与持续挑战

### 9.1 Timeline

职责：绝对/相对时间、昼夜、日程和定时事件。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Runtime scheduler、Rule Engine、Projection |
| 什么时候消费 | 时间推进、进入时间窗口和定时事件触发时 |
| 忽略后果 | 追书人夜间监视、鬼屋研究耗时、复足/蛙蛙村多日事件可能在错误时间发生 |
| 决策 | Include / Execution |

Timeline 静态定义进入 ModuleContent；当前 clock 和 active timeline 进入 GameState。

### 9.2 Track

职责：感染、怀疑、异变、警戒、仪式等阶段状态机。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Runtime state machine、Rule Engine、Projection、Host |
| 什么时候消费 | 相关事件累积、阈值到达和阶段转换时 |
| 忽略后果 | 复足感染和蛙蛙村累积变化等核心机制会退化为不可验证文本 |
| 决策 | Include / Execution |

Track 定义进入 ModuleContent；当前 stage/value 进入 GameState。

### 9.3 Encounter

职责：持续的战斗、追逐、谈判、群体检定或环境挑战边界。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor；核心算法由 Ruleset 提供 |
| 谁消费 | Runtime Orchestrator、Rule Engine、Projection、Host |
| 什么时候消费 | Encounter 开始、回合推进和结束时 |
| 忽略后果 | 对峙、追逐和群体挑战缺少持续状态和结束条件，Host 可能越权裁定 |
| 决策 | Include / Execution |

Encounter 不重新定义 Ruleset 战斗算法，只声明参与者、入口、参数、可选行动和结束条件。

## 10. 终局与素材

### 10.1 Ending

职责：正式结束游戏的终局定义和触发条件。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor |
| 谁消费 | Validation、Rule Engine、Projection、Host |
| 什么时候消费 | 每次可能改变终局条件的提交后 |
| 忽略后果 | 多终局模组无法可靠结束，Host 可能自行决定结局 |
| 决策 | Include / Execution；目标上替换 WinCondition，不并存 |

目标名称采用 `Ending`，因为终局可能是和平解决、逃脱、死亡、失踪、被捕或收容，并非都属于胜利。

当前 `WinConditionSpec` 是迁移起点。迁移必须一次完成：更新 Contract、Fixture、Validation、Runtime 和测试，不能长期保留两套终局集合。

非终局回滚、阶段完成和重试仍属于 Rule/Operation，不属于 Ending。

### 10.2 Asset

职责：Runtime/Frontend 可展示的地图、插图、手稿和素材引用。

| 问题 | 回答 |
|---|---|
| 谁生产 | Document Adapter/Parser 建立关联，Repository 固化引用 |
| 谁消费 | Loader、Projection、Frontend、Host |
| 什么时候消费 | Scene/Clue/NPC 揭示和地图显示时 |
| 忽略后果 | 通常不破坏纯文本规则，但会丢失地图导航、视觉线索或作者要求展示的材料 |
| 决策 | Include / Projection，仅保存可发布语义引用 |

OCR bbox、提取置信度、存储内部路径和 rights workflow 继续放 Sidecar/Repository。

## 11. Initial State Template

职责：声明每个新 Room 的初始 Scene、已授予 Fact/Clue、对象状态、时钟、Track 和 Encounter 初值。

| 问题 | 回答 |
|---|---|
| 谁生产 | Parser/Editor，Validation 校验引用 |
| 谁消费 | Runtime Loader |
| 什么时候消费 | 创建 Room/GameState 时，仅消费一次 |
| 忽略后果 | Runtime 无法确定从哪里开始，也无法自动创建一致 GameState |
| 决策 | Include / Load |

它是不可变初始化模板，不是当前 GameState。实例创建后，所有变化只写 GameState/Event。

对象级初始状态与顶层模板的职责需避免重复：对象定义拥有自身默认状态，顶层模板只拥有跨对象和整局初始状态。

## 12. 不进入 ModuleContent 的信息

| 信息 | 归属 | 原因 |
|---|---|---|
| SourceFragment/page/bbox | ParserResult | Runtime 不需要原文定位 |
| confidence/alternative interpretation | ParserResult | 正式 Contract 不允许歧义 |
| model/prompt/converter version | ParserResult | 解析审计生命周期 |
| normalization decisions | ParserResult/Review | 不属于玩法语义 |
| unresolved questions | ParserResult/Review | 发布前处理或形成 Gap |
| Capability Gap | ParserResult/ValidationReport | 表示未支持能力，不是可执行内容 |
| rights/commercial use | Repository/Publish | 治理生命周期不同 |
| content hash | Publication metadata | 由 canonical JSON 计算，不能是自身内容 |
| ValidationReport/ReviewReport | 对应流程产物 | Runtime 不消费 |
| 当前 GameState/Event/CheckResult | Runtime | 按 Room 变化 |

## 13. 目标数据流与所有权

```text
Raw Document
      ↓
ParserResult
  ├── draft: ModuleDraft（与目标 ModuleContent 同形）
  ├── provenance
  ├── normalization decisions
  ├── unresolved questions
  └── capability gaps
      ↓
Validation
      ↓
ModuleContent
      ↓
Runtime Loader
      ↓
GameState + Event
      ↓
ProjectionSnapshot / ActionResult
      ↓
Host
```

不再要求一套与 ModuleDraft 并行的完整 Parser Domain Model。Parser 无法进入目标 Contract 的信息通过 ParserResult sidecar 和 Capability Gap 保留。

## 14. 实施分层

### Current Baseline

- Scene；
- Entity；
- 最小 Rule/Condition/Operation；
- 最小 Checkpoint；
- WinCondition；
- 外部 demo-state 初始化。

### Target Core

建议优先形成统一 Contract 和端到端实现：

1. identity/ruleset_ref/metadata/entry point；
2. Scene + Location；
3. Entity + Resource + Character Template；
4. Fact + Clue；
5. 扩展 Checkpoint + Ruleset catalogs；
6. Ending；
7. Initial State Template。

### Target Advanced

在核心能力后按样本优先级实施：

1. Sanity extension；
2. Timeline；
3. Track；
4. Encounter；
5. Asset Projection。

Puzzle、Table 和完整通用脚本继续 Deferred，直到出现明确消费者和跨模组稳定语义。

## 15. 能力完成定义

每项能力只有同时完成以下内容，才能标记为 Supported：

1. 三方接受领域语义；
2. `contracts/module.py` 或版本化后继 Contract 已实现；
3. ModuleDraft 已对齐；
4. Parser 能从至少一个真实样本生成；
5. Validation 有稳定错误码；
6. Runtime 有明确 consumer；
7. GameState/Event 边界已定义；
8. Host/Frontend 有安全投影；
9. 正向、负向和端到端测试通过；
10. 迁移和兼容策略已记录。

## 16. 待团队决策

以下问题尚未冻结：

1. 目标 Contract 的版本管理方式；
2. `world_ref` 是否升级为结构化 `ruleset_ref`；
3. Character 是否独立于 Entity；
4. Resource 与 object Entity 的分类线；
5. Fact/Clue 的授权和玩家知识状态；
6. Checkpoint 动态难度的受限表达方式；
7. Sanity 使用通用集合还是 CoC Ruleset extension；
8. Hook catalog 的首个目标范围；
9. Ending 迁移版本和优先级规则；
10. Partially supported 模组是否允许发布。

## 17. 决议摘要

> 统一目标是扩展一套 ModuleContent，而不是长期维护两套竞争的领域模型。

> ModuleDraft 与目标 ModuleContent 同形；Parser 私有的来源、不确定性和 Capability Gap 通过 ParserResult sidecar 保存。

> Location、Fact、Clue、Resource、Timeline、Track、Sanity、Encounter、Ending 和 Asset 只有在三方明确消费者和实现计划后才进入 Supported 状态，但可以现在作为统一目标 Contract 的 Proposed 能力共同设计。

> 新增字段的判断标准不是“当前 Fake Runtime 是否已经支持”，而是“团队是否明确承诺 Parser 生产、Validation 校验、Runtime/Loader/Projection 消费，并完成端到端实现”。

# ADR：统一 TRPG Data Contract

- 编号：ADR-TRPG-DATA-CONTRACT-001
- 状态：Proposed
- 日期：2026-07-23
- 决策范围：Module Parser Agent、Validation、Review、Publish、Rule Engine、Runtime Keeper Agent
- 当前实现基线：`agent-collaboration-framework/collaboration_framework/contracts/module.py`
- 目标状态依据：`module-parser-mvp-prd.md`、`module-parser-pipeline.md`
- 非目标：本文不定义具体 Schema，不设计数据库表

> 演进说明：本文保留为前期数据边界决策记录。面向多个真实模组的统一 `ModuleContent` 扩展提案，以 [`../agent-collaboration-framework/docs/architecture/data-model-alignment-rfc.md`](../agent-collaboration-framework/docs/architecture/data-model-alignment-rfc.md) 为当前讨论入口；在提案冻结并实现前，现行代码 Contract 不变。

## 1. 背景

TRPG 模组从原始文档到 Runtime 执行的目标链路为：

```text
PDF / DOCX / Markdown / TXT
→ DocumentAdapter（确定性）
→ NormalizedDocument / SourceFragment[]
→ Parser Pass（LLM）
→ ModuleDraft（Parser 私有）
→ Validation（确定性）
→ ModuleContent candidate / ValidationReport
→ Review Pass（LLM）
→ 无阻断问题
→ 规范化 JSON Publish
→ Runtime
```

当前项目已经实现最小 `ModuleContent`，能够加载 Scene，并结合外部提供的已初始化 `GameState` 完成 Checkpoint 执行、Rule 状态修改、Event 记录、WinCondition 判断以及 Host 安全投影。当前尚未实现从 `Entity.state` 自动创建 Room 或初始化 `GameState`。

当前实现是第一阶段基线，不是统一 Contract 的最终能力上限。Architecture Decision 需要同时考虑 Parser 是否容易提取、Validation 是否能够确定性校验、Review 是否能够识别遗漏、Rule Engine 是否能够执行，以及 Host 是否能够安全消费。

## 2. Decision Drivers

本 ADR 按以下优先级作出决策：

1. 容易实现；
2. 容易维护；
3. 容易解析；
4. 容易验证；
5. 容易扩展；
6. 能支持完整目标链路；
7. 不让 Parser、Host 或 Review 绕过 Rule Engine；
8. 不把不同生命周期的数据混入同一个 Contract。

本文不追求一次覆盖所有 TRPG 系统，也不追求理论上最通用的规则语言。

## 3. 总体决策

### 决策 1：采用“编译流水线 + 单一 Runtime 发布 Contract”

**状态**：Proposed

**决定**

系统存在多个正式产物，但只有 `ModuleContent` 是 Runtime 加载的正式模组 Contract。

```text
RawDocument
→ NormalizedDocument / SourceFragment
→ ParserResult / ModuleDraft
→ ValidationReport
→ ModuleContent candidate
→ ReviewReport
→ Published JSON
→ Runtime
```

| 产物 | 所有者 | 是否进入 Runtime |
|---|---|---:|
| RawDocument | Parser Pipeline | 否 |
| NormalizedDocument | Parser Pipeline | 否 |
| SourceFragment | Parser/Review | 否 |
| ParserResult | Parser | 否 |
| ModuleDraft | Parser | 否 |
| ValidationReport | Validation | 否 |
| ReviewReport | Review | 否 |
| ModuleContent | Parser 与 Rule Engine 共享 | 是 |
| Published JSON | Publish | 是 |
| GameState/Event | Runtime | Runtime 内部 |

**原因**

这些产物的生产者、消费者和生命周期不同。将来源、Review、发布状态、Runtime 内容和 GameState 合并为一个大型对象，会造成职责混杂和不必要的跨层依赖。

**备选方案**

使用一个完整 `ModulePackage` 同时承载来源、内容、验证、审批、初始状态和 Runtime 数据。

**拒绝原因**

它会把所有模块耦合到同一个对象，使 Parser metadata 和 Review metadata 泄漏到 Runtime。

**权衡**

系统需要通过稳定 ID、run ID、revision 或内容哈希关联多个产物。

**影响**

- Runtime 永远不加载 `ModuleDraft`；
- Runtime 不依赖 SourceFragment、ReviewReport 或 Agent SDK；
- 当前 Phase 1 Publish 只依赖确定性 Validation；目标生产链才将 Review 作为发布门禁；
- 无论门禁阶段如何演进，Publish 都只接受正式 `ModuleContent`，不接受 Draft 或 ParserResult。

### 决策 2：目标 Contract 按完整可运行能力设计，按版本分阶段实现

**状态**：Proposed

**决定**

Architecture Decision 不以当前 Fake Runtime 为最终上限。主要概念分别标记为 Current、Partial、Candidate、Deferred 或 Rejected。

Capability Gap 是版本演进机制，不是永久排除列表。

**原因**

MVP 决定当前交付范围；ADR 决定长期边界；Contract version 决定某项能力何时可用。

**备选方案**

只有当前 Runtime 已实现的概念才允许进入目标架构。

**拒绝原因**

这会把当前实现偶然固化成长期领域边界，无法完成目标 Parser Pipeline。

**权衡**

必须明确区分 Declared、Implemented、Verified 与 Supported，避免将目标能力误报为当前能力。

**影响**

每项共享能力需要分别记录是否已在 Contract 声明、是否存在消费者、是否有端到端验证，以及是否达到完整 Supported 状态。

### 决策 3：Host 不直接消费完整 ModuleContent

**状态**：Accepted

**决定**

`ModuleContent` 是 Parser 与 Rule Engine 的共享发布 Contract。Host 通过 Runtime 产生的安全投影消费模组信息。

```text
ModuleContent + GameState
→ Rule Engine / Projector
→ ProjectionSnapshot / PlayerView / ActionResult
→ Host
```

**原因**

Host 只需要当前可见内容、可信候选、已确认事实、玩家可见结果和叙事约束，不需要完整秘密、未解锁结局、状态写入路径和完整 Rule。

**备选方案**

Host 直接读取完整 `ModuleContent` 并自行过滤。

**拒绝原因**

会扩大泄密面，并使 Host 依赖 Engine 的规则结构。

**权衡**

需要维护明确的 PlayerView、ActionResult 和 Host Context 投影边界。

**影响**

Host 不执行 Rule、不直接修改 GameState，Narrator 只表达 Rule Engine 已确认的结果。

## 4. 发布决策

### 决策 4：区分 Phase 1 Publish 与目标生产发布门禁

**状态**：Phase 1 Current / Production Target Accepted

**决定**

当前 Phase 1 的最小 Publish 只接受 `ValidationReport.status == "pass"` 且携带正式 `ModuleContent` 的输入，并输出规范化 JSON；当前尚未实现 Review、Repository 或 content hash。

目标生产发布必须同时满足：

1. 确定性 Validation 通过；
2. LLM Review Pass 完成；
3. ReviewReport 中不存在阻断级 finding；
4. 不存在未解决的发布阻断问题；
5. 待发布内容与 Validation、Review 检查的版本一致。

目标门禁满足条件后，系统自动形成正式 `ModuleContent` 并发布规范化 JSON，不要求人工审批。

```text
ModuleDraft
   ↓
ValidationReport
   ├── errors → needs_revision → 不发布
   └── pass + ModuleContent
         ↓
ReviewReport
   ├── blocking findings → needs_revision → 不发布
   └── pass / acceptable warnings
         ↓
Publish ModuleContent
         ↓
Runtime
```

**原因**

- Validation 保证结构、类型、引用、状态路径和 Runtime capability 正确；
- Review 检查确定性校验不能发现的遗漏、泄密、结果颠倒和无来源推断；
- 自动发布符合降低人工转写和审核成本的产品目标；
- 强制人工审批会成为规模化导入的吞吐瓶颈。

**备选方案**

所有 LLM Parser 结果必须人工批准后才能发布。

**拒绝原因**

人工审批成本高，不符合已经确定的自动发布策略。

**备选方案**

仅通过确定性 Validation 即可发布。

**拒绝原因**

结构正确不能证明没有遗漏关键规则、秘密泄漏、结果颠倒或无来源推断。

**权衡**

- Review 仍可能遗漏问题；
- Parser 与 Review 可能产生同源偏差；
- 自动发布不等于与原模组完全一致；
- 需要通过黄金样例和预置缺陷集持续评测 Review。

**影响**

- ReviewReport 是自动发布的正式门禁输入；
- Human Approval 不属于基础发布主链；
- 人工审核可用于官方认证、商业审查、抽检和黄金样例建设；
- Review 不直接修改 Draft；发现问题后必须修订并重新执行完整 Validation 与 Review。

## 5. 生命周期边界

### 5.1 DocumentAdapter

保存原始文件、文件哈希、格式、转换器版本、转换 warning 和可识别素材。

它只负责确定性预处理，不理解 Scene、Rule、Checkpoint 或 Ending。

原始文件、OCR 中间结果和布局坐标不进入 Runtime。

### 5.2 SourceFragment

保存稳定 Fragment ID、页码、章节、段落或 block 定位、原始文本和内容分区。

生产者是 DocumentAdapter；消费者是 Parser、Review、Editor 和来源覆盖检查。

SourceFragment 与原始文档哈希和转换器版本绑定，不进入 Runtime。

### 5.3 ParserResult 与 ModuleDraft

`ModuleDraft` 只保存与目标 `ModuleContent` 对应、但尚未通过确定性校验的内容候选。它由 Parser 生产，被 Validation 消费，不得直接发布或交给 Runtime。

`ParserResult` 是 Parser 私有包装对象，负责将 `ModuleDraft` 与字段来源、confidence、unresolved questions、capability gaps、normalization decisions 和 Parser provenance 关联。Validation 只消费其中的 Draft；Review 和审计流程可以消费完整 ParserResult。以上 Parser 私有信息均不得进入 `ModuleContent`。

### 5.4 Validation

负责 Schema、必填字段、枚举、额外字段、ID 唯一性、引用完整性、状态路径、Ruleset ID、Hook、Condition、Operation、可达性和显式循环检查。

Validation 不调用 LLM、不判断作者意图、不自动补造内容，也不直接发布。

### 5.5 Review

负责结合 ParserResult/来源证据审查 Validation 产出的 `ModuleContent` candidate，检查 Scene、Entity、Rule、Checkpoint 和终局是否遗漏，机制是否完整，成功与失败是否颠倒，secret 是否泄漏，是否存在无来源推断，以及 Capability Gap 是否完整。

Review 只生成 ReviewReport，不直接修改 Draft 或 ModuleContent；发现问题后返回修订流程并重新执行 Validation。

### 5.6 ModuleContent

只保存已通过当前发布门禁的静态模组内容、稳定 ID、Ruleset 引用、可执行声明及 Runtime 和安全投影所需内容。Phase 1 门禁为 Validation；目标生产门禁再加入 Review。

它不保存 SourceFragment、confidence、Review finding、Parser model、Prompt version、import job、GameState 或 Event。

### 5.7 Publish

Phase 1 Publish 负责规范化序列化正式 `ModuleContent`。目标生产 Publish 可以进一步固化不可变版本、计算内容哈希、保存发布物并关联 Validation/Review 证据；Hash 和 Repository 当前尚未实现。

Publish 不修改玩法语义。任何修订必须返回 Draft 并重新经过 Validation 和 Review。

### 5.8 Runtime

负责加载兼容的已发布 `ModuleContent`、执行规则、维护状态、写入 Event 并产生安全 ActionResult 和 ProjectionSnapshot。目标 Runtime/Loader 还负责创建独立 GameState；当前 Phase 1 由外部 fixture 提供已初始化 GameState。

Runtime 不读取 Raw PDF、ModuleDraft 或 ReviewReport，也不信任待发布对象中的自述验证状态。

## 6. 主要概念决策

### 决策 5：Scene 保留

**状态**：Accepted / Current

**为什么存在**

Scene 表达当前叙事上下文、可描述内容、相关 Entity、Checkpoint 和后续叙事节点。

**谁生产**：Parser/Editor。

**谁消费**：Rule Engine、Projector、Host 安全投影、Review。

**生命周期**：Source → Draft Scene → Validated Scene → Reviewed Scene → Published Scene → Runtime 只读。

**为什么属于共享 Contract**：Parser 需要生成，Engine 需要路由，Host 需要安全描述。

**为什么不属于 Runtime 私有模型**：Scene 来自模组内容，不是 Engine 执行产物。

**为什么不属于 Parser 私有模型**：发布后 Runtime 必须脱离 Parser 独立加载。

**为什么不属于 Review**：Review 只审查 Scene，不拥有正式定义。

**备选方案**：只保留 Entity 和自由文本。

**拒绝原因**：Checkpoint、可达性和 Host 描述会失去稳定上下文。

**权衡**：Scene 与物理 Location 存在语义重叠。

### 决策 6：区分 Scene 与 Location 的领域职责

**状态**：Open / Capability Candidate

**决定**

Scene 表达叙事和交互阶段；Location 表达物理空间、层级、连接和隐藏路线。两者在领域上不同，但本 ADR 暂不决定 Location 必须成为独立的 `ModuleContent` 一级模型。

**为什么存在**

同一 Location 可以发生多个 Scene；地图连接不等于剧情转场；角色可以分头位于不同地点。

若未来建立独立 Location，其静态定义可以属于 ModuleContent，当前角色位置仍只属于 GameState。但在进入共享 Contract 前，必须先具备 Runtime navigation、多角色位置或隐藏路线的明确用例、确定性 Validation、安全投影和端到端测试。

**备选方案**：Location 永远等同于 Scene 或 `Entity.kind=location`。

**暂不选择原因**：当前 v1 尚未实现地图导航、多 Scene 共址或多人分队的 Runtime 消费语义，立即拆分会形成无消费者字段。

**权衡**：增加 Scene–Location 引用和一致性校验成本。

### 决策 7：Entity 保留为通用对象

**状态**：Accepted / Current

**决定**

Entity 表达 NPC、Monster、Object、Animal 及其他具有身份、状态或规则的内容对象。

**谁生产**：Parser/Editor。

**谁消费**：Rule Engine、Projector、Host、Review。

**生命周期**：静态 Entity 随 ModuleContent 发布；当前状态属于 GameState。

**为什么属于共享 Contract**：Parser、Engine 和 Host 都依赖稳定 Entity ID。

**为什么不属于 Runtime**：Runtime 拥有当前状态和编译索引，不拥有静态定义。

**为什么不属于 Parser**：发布后的 Runtime 必须脱离 Parser 运行。

**为什么不属于 Review**：Review 不执行 Entity 行为。

**备选方案**：立即拆成 NPC、Monster、Object 等多个顶层集合。

**拒绝原因**：会增加 Parser 分类、引用和 Validator 成本，当前收益不足。

**权衡**：需要控制不同 kind 的专用字段数量。

### 决策 8：评估 Resource 是否独立于 Entity

**状态**：Open / Capability Candidate

**决定**

Resource 在领域上表达会被持有、阅读、消耗、装备、使用、破坏或授予能力的内容对象。本 ADR 暂不决定它必须从 Entity 拆为一级模型。

**谁生产**：Parser。

**谁消费**：Runtime inventory/resource subsystem、Host、Review、Editor。

**候选生命周期**：若该能力进入共享 Contract，静态定义属于 ModuleContent；当前持有、消耗和破损状态属于 GameState。

**进入共享 Contract 的条件**：Runtime 已有独立 inventory/resource 语义，Validation 能验证其引用和状态，Host/UI 有安全投影，并有端到端测试证明拆分价值。

**为什么不属于 Runtime**：定义来自模组。

**为什么不属于 Parser**：发布后需要被 Runtime 使用。

**为什么不属于 Review**：Review 只核查忠实度。

**备选方案**：所有 Resource 永远作为 Entity。

**拒绝原因**：完整 Inventory 会依赖大量约定式状态键。

**权衡**：Resource 与特殊 Object 之间需要清晰分类原则。

### 决策 9：评估 Character/Pregen 建局能力

**状态**：Open / Capability Candidate

**决定**

预生成角色和模组角色要求是真实领域能力；运行中的角色卡属于 GameState。本 ADR 暂不决定 Character/Pregen 必须进入 `ModuleContent`，需要先确认建局 Loader、Ruleset 校验和角色投影边界。

**谁生产**：Parser/Editor。

**谁消费**：Character creation、Runtime Loader、Host、Review。

**候选生命周期**：若该能力进入共享 Contract，Pregen template 属于 ModuleContent；玩家选择和当前角色状态属于 GameState。

**进入共享 Contract 的条件**：Parser、建局 Runtime 和 Host 确实需要共享稳定角色模板，并具备 Ruleset 校验和端到端测试。

**备选方案**：Pregen 只保存为图片或 Asset。

**拒绝原因**：Runtime 无法验证技能、装备和状态，也无法建立正式角色实例。

### 决策 10：Rule 保留并升级为有限声明语言

**状态**：Accepted / Planned expansion

**决定**

Rule 明确在哪个 Runtime 阶段生效、满足什么条件、执行什么有限操作、与其他规则的顺序，以及追加、覆盖或禁止语义。

Rule 不允许任意脚本。

**谁生产**：Parser/Editor。

**谁消费**：Validation、Rule Engine、Review；Host 只消费结果。

**生命周期**：Rule 随 ModuleContent 发布；Runtime 可编译和索引，但不修改原始声明。

**为什么属于共享 Contract**：它是 Parser 与 Rule Engine 的核心交接语言。

**为什么不属于 Runtime**：Runtime 私有的是编译结果、EvalContext、事务和 Event。

**为什么不属于 Parser**：若不发布，Runtime 无法执行。

**为什么不属于 Review**：Review 发现遗漏，但不能代替 Rule。

**备选方案**：复杂机制全部写入 Keeper notes，由 Host 解释。

**拒绝原因**：不可验证、不确定，并绕过 Engine 状态权威。

**权衡**：有限语言无法表达所有规则，未支持机制需要 Capability Gap。

**当前缺口**：`RuleSpec.hook` 已在 Contract 声明四种取值，但当前 action 流程没有按 hook 过滤。Rule 模型属于 Current，hook dispatcher 仅为 Partial；在 dispatcher 与 Validation catalog 对齐前，不得宣称四种 hook 均已支持。

### 决策 11：Condition 采用受限表达能力

**状态**：Proposed / Planned

**决定**

目标 Contract 允许组合、比较和有限算术，但不允许任意代码、循环、递归、函数定义、未注册变量或自然语言语义判断。

**谁生产**：Parser/Editor。

**谁消费**：Validation、Rule Engine、Review。

**生命周期**：静态 Condition 随 ModuleContent 发布；求值上下文属于 Runtime。

**为什么属于共享 Contract**：Parser 必须生成，Engine 必须求值。

**备选方案**：永久保持单一状态路径等值比较。

**拒绝原因**：无法表达人数缩放、计数器、时间条件和复杂 Ending。

**权衡**：需要表达式 Parser、变量注册表和更强 Validation。

### 决策 12：Operation 采用有限注册目录

**状态**：Accepted / Planned expansion

**决定**

Operation 必须来自 Runtime 注册的有限目录。Parser 不得发明 Operation、直接生成 GameState patch、写 Event 或调用任意函数。

**谁生产**：Parser/Editor。

**谁消费**：Validation、Rule Engine。

**生命周期**：Operation 声明属于 ModuleContent；StateChange 和 Event 属于 Runtime。

**为什么属于共享 Contract**：Parser 产生，Engine 执行。

**备选方案**：Host 根据叙事直接更新状态。

**拒绝原因**：破坏 Engine 的唯一状态写入口。

**权衡**：新增效果必须协调 Contract 和 Runtime capability version。

### 决策 13：Checkpoint 保留并覆盖完整检定语义

**状态**：Accepted / Planned expansion

**决定**

Checkpoint 是 Host 自由语言与 Rule Engine 确定执行之间的桥梁。目标能力包括可信候选、目标、技能或属性候选、固定或动态难度、暗骰、自动或玩家交互式掷骰、固定阈值、结构化结果以及时间或资源代价。

**谁生产**：Parser/Editor。

**谁消费**：Projector、Host IntentParser、Rule Engine、Review。

**生命周期**：Checkpoint 定义属于 ModuleContent；某次检定请求和结果属于 GameState/Event。

**为什么属于共享 Contract**：Parser、Host 和 Engine 都依赖稳定 Checkpoint ID。

**备选方案**：Host 临时生成检定。

**拒绝原因**：会让 Host 同时决定技能、难度和后果。

**权衡**：完整 Checkpoint 能力需要与 Ruleset 协调。

**影响**：`mvp_check_result` 仅为测试过渡，不属于目标 Contract。

### 决策 14：评估 SanityEvent/SanTrigger 的 CoC 扩展边界

**状态**：Open / Capability Candidate

**决定**

真实 CoC 模组需要表达检定式损失、直接损失、固定损失、上限降低、恢复和同源累计上限等不同语义；是否建立独立模型，还是由 Ruleset 注册的 Condition/Operation 组合表达，仍需 Ruleset Runtime 用例决定。

**谁生产**：Parser。

**谁消费**：Validation、CoC Ruleset Runtime、Host、Review。

**候选生命周期**：若采用独立 SAN 声明，它可以属于 ModuleContent 或 Ruleset extension；当前 SAN 和累计记录属于 GameState。

**进入共享 Contract 的条件**：Parser、Ruleset Runtime 和 Host 确实需要共享独立 SAN 语义，并完成扩展归属决策和端到端测试。

**备选方案**：全部使用自然语言或通用 Operation 表达。

**拒绝原因**：容易丢失是否检定、是否累计封顶等领域语义。

**权衡**：需要决定它属于通用 Contract 还是 CoC Ruleset extension。

### 决策 15：终局定义与非终局规则分离

**状态**：Accepted boundary / Naming migration open

**决定**

终局定义只表达会使游戏进入 `phase="ended"` 的正式结局。状态回滚、阶段完成、重试和非终局失败由 Rule/Operation 表达，不属于 WinCondition 或 Ending。

**谁生产**：Parser/Editor。

**谁消费**：Validation、Rule Engine、Host、Review。

**生命周期**：当前 v1 使用 `WinConditionSpec/win_conditions` 声明终局；当前触发状态属于 GameState。目标版本是否破坏性迁移为 `Ending/endings`，需要单独决策，不能长期保留两套终局集合。

**为什么属于共享 Contract**：Parser 声明，Engine 判断，Host 叙述。

**备选方案**：由 Host 判断故事是否结束。

**拒绝原因**：不可确定、不可审计。

**权衡**：复杂 Ending 依赖受限表达式能力。

### 决策 16：评估 Timeline 和 Track 的共享边界

**状态**：Open / Capability Candidate

**决定**

Timeline 在领域上表达外部时间、日程和定时事件；Track 表达感染、怀疑、异变、警戒和仪式等阶段状态。本 ADR 暂不决定它们必须成为共享一级模型。

**谁生产**：Parser。

**谁消费**：Validation、Runtime scheduler、Rule Engine、Host、Review。

**候选生命周期**：若进入共享 Contract，静态定义属于 ModuleContent；当前时钟、活动 Timeline 和 Track state 属于 GameState。

**进入共享 Contract 的条件**：Parser 能稳定提取，Runtime 有 scheduler/state machine 消费者，Host 有安全投影，并有端到端测试。

**备选方案**：全部使用 Entity state 和 Rule 隐式表达。

**拒绝原因**：会依赖大量隐式命名约定，难以解析和验证。

**权衡**：增加 Scheduler 和状态转换验证复杂度。

### 决策 17：评估 Encounter 的共享边界

**状态**：Open / Capability Candidate

**决定**

Encounter 可以表达需要持续编排的战斗、追逐、谈判、群体检定和环境挑战，但本 ADR 暂不决定它必须成为共享一级模型。核心算法应由 Ruleset 提供，模组不能重新定义算法。

**谁生产**：Parser。

**谁消费**：Runtime Orchestrator、Rule Engine、Host、Review。

**候选生命周期**：若进入共享 Contract，Encounter 定义属于 ModuleContent；当前活动 Encounter 属于 GameState。

**进入共享 Contract 的条件**：Parser、Runtime 和 Host 需要共享稳定 Encounter 边界，并已明确与 Ruleset 算法的分工。

**备选方案**：全部通过 Scene + Rule 隐式表达。

**拒绝原因**：入口、参与者和结束语义难以验证。

**权衡**：必须避免 Encounter 重新定义 Ruleset 的战斗算法。

### 决策 18：Puzzle 和 Table 暂缓进入首个目标版本

**状态**：Deferred

**决定**

确认 Puzzle 和 Table 有领域价值，但当前缺少稳定 Runtime consumer、最小跨模组语义和清晰 Validation 规则。

**备选方案**：立即采用 PR99 的 Puzzle 和 Table。

**拒绝原因**：设计证据不足，容易过早固化单一 Parser 方案。

**权衡**：相关内容暂通过 Resource、Checkpoint、Rule 或 Capability Gap 表达。

### 决策 19：评估 Asset 的 Runtime 引用边界

**状态**：Open / Capability Candidate

**决定**

OCR、bbox、权利审查过程、存储内部路径和 Parser confidence 不进入 ModuleContent。只有当 Runtime/Projection 确实需要稳定素材身份和展示约束时，Asset 的可发布语义引用才可以进入共享 Contract；本 ADR 暂不决定具体模型。

**谁生产**：DocumentAdapter、Parser、Repository。

**谁消费**：Projector、Host、Frontend、Map UI、Review。

**候选生命周期**：文件和权利记录属于 Repository；若建立可发布 Asset 引用，它可以属于 ModuleContent；是否已展示属于 GameState。

**进入共享 Contract 的条件**：Parser 能建立稳定关联，Runtime 能控制展示，Host/UI 有明确消费者，并已有 Repository 边界。

**备选方案**：Asset 只作为 Parser 附件。

**拒绝原因**：Runtime 无法安全展示地图、立绘和线索材料。

**权衡**：需要稳定 Asset Repository 和权限边界。

### 决策 20：Metadata 按生命周期拆分

**状态**：Accepted

| Metadata 类型 | 归属 |
|---|---|
| 内容身份与 Runtime 兼容性 | ModuleContent |
| Parser provenance | ParserResult |
| Validation/Review metadata | 对应 Report |
| Repository/rights metadata | Repository/Publish |

内容身份需要随 ModuleContent 发布；文档哈希、模型、Prompt、转换器、confidence、finding、rights 和 repository visibility 不进入 Runtime Contract。

**备选方案**：全部放入 ModuleContent。

**拒绝原因**：生产者、消费者和生命周期不同。

**权衡**：需要多个关联记录。

## 7. Contract 演进原则

### 决策 21：按纵向能力演进

**状态**：Proposed

每个新概念进入正式 Supported Contract 前必须具备：

1. 至少一个真实模组样例；
2. Parser 提取方案；
3. 确定性 Validation；
4. LLM Review 检查项；
5. Runtime consumer；
6. Host 或 UI 投影策略；
7. 端到端测试；
8. 版本兼容决策。

**原因**

防止出现“Parser 能生成、Schema 能加载，但 Runtime 不消费”的虚假支持。

**备选方案**

先把完整领域字段全部加入 Schema。

**拒绝原因**

会提前固化未经验证的设计。

**权衡**

Contract 扩展速度受纵向实现能力限制。

## 8. 概念状态清单

| 概念 | 职责判断 | 当前状态 |
|---|---|---|
| Scene | ModuleContent | Current / Verified |
| Location | Domain candidate | Candidate |
| Entity | ModuleContent | Current / Verified |
| Resource | Domain candidate | Candidate |
| Character/Pregen | Domain candidate | Candidate |
| Rule | ModuleContent | Current；hook dispatcher 为 Partial |
| Condition/Expr | ModuleContent | 当前仅支持 path/equals；扩展为 Candidate |
| Operation | ModuleContent | 当前仅支持 allow/modify；扩展为 Candidate |
| Checkpoint | ModuleContent | Current / Verified；真实掷骰未实现 |
| SanityEvent/SanTrigger | CoC domain candidate | Candidate |
| WinCondition | 当前终局 Contract | Current / Verified |
| Ending | 目标命名候选 | Candidate；不得与 WinCondition 并存 |
| Timeline | Domain candidate | Candidate |
| Track | Domain candidate | Candidate |
| Encounter | Domain candidate | Candidate |
| Puzzle | Domain candidate | Deferred |
| Table | Domain candidate | Deferred |
| Asset runtime reference | Domain candidate | Candidate |
| SourceFragment | Parser/Review only | Planned |
| ParserResult/provenance | Parser only | Planned |
| ValidationReport | Validation only | Current |
| ReviewReport | Review only | Planned |
| ModuleContent | Runtime 发布 Contract | Current / evolving |
| GameState/Event | Runtime only | Current / evolving |
| Player-visible information / narration constraints | ModuleContent 声明，Runtime 选择，Host 消费 | Current / Verified |

## 9. Consequences

### Positive

- 完整目标链路具有清晰的产物和所有权；
- Parser 和 Review 被正式纳入发布架构；
- Runtime 仍只依赖稳定发布 Contract；
- Host 不直接接触全部秘密和规则；
- 当前 MVP 不会被误认为最终能力上限；
- 新能力可以通过版本和纵向测试逐步引入；
- 自动发布不依赖人工吞吐量；
- Capability Gap 可以持续推动 Contract 演进。

### Negative

- 需要维护多类中间产物；
- Contract 演进需要 Parser、Runtime 和 Host 协同；
- 完整 Runtime 的实现量明显高于当前 Fake；
- 自动发布依赖 Review Pass 的实际质量；
- 目标能力不能一次全部交付。

### Risks

- Planned 字段可能被误报为 Current；
- Parser 和 Review 使用相似模型时可能产生同源偏差；
- 过早扩展 Contract 会形成无消费者字段；
- 过度保守会让关键机制长期停留在 Capability Gap；
- Host narrative guidance 与 Engine hard rule 可能再次混淆。

## 10. 最终决议摘要

```text
Parser Agent
  负责：文档预处理、来源追踪、结构提取
  不负责：规则执行、状态修改

Validation
  负责：确定性结构、引用、表达式和能力检查
  不负责：理解作者意图、自动修复、发布

Review
  负责：遗漏、秘密、来源忠实度和 Capability Gap 检查
  目标生产链中，无阻断问题后允许自动发布
  不负责：直接修改 Draft 或执行规则

ModuleContent
  负责：承载通过当前发布门禁、静态、版本化、Runtime 可执行的模组声明
  不承载：Parser、Review、Repository 或 GameState 数据

Rule Engine
  负责：确定性执行、GameState、Event、Dice 和事务
  不负责：解析原文、语义审查或叙事创作

Host
  负责：意图匹配、回合编排和叙事
  只消费：安全投影、可信候选和 Engine 确认结果
  不负责：直接写状态或解释未注册规则
```

核心决议：

> 以完整可运行模组作为目标 Contract 的设计范围，以当前 `ModuleContent` 作为迁移起点，通过版本化纵向能力逐步实现。

> Source、Draft、Validation 和 Review 都是正式流水线产物，但不进入 Runtime `ModuleContent`。

> 当前 Phase 1 在确定性 Validation 通过后执行最小 Publish；目标生产链在 LLM Review 完成且不存在阻断问题后自动发布，不要求基础人工审批。

> 一个概念只有同时具备 Parser、Validation、Review、Runtime、Host/投影和端到端测试，才能从 Candidate 升级为正式 Supported。

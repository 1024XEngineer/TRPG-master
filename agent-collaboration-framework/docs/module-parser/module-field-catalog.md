# 《ModuleContent Field Catalog》

> 状态：Field Catalog Proposal
> 日期：2026-07-23
> 统计输入：[`CoC模组能力统计与ModuleContent-v1归纳.md`](CoC模组能力统计与ModuleContent-v1归纳.md)
> 领域输入：[`module-domain-model.md`](module-domain-model.md)
> 当前实现事实源：`collaboration_framework/contracts/module.py`
> 非目标：本文不定义 JSON Schema、Python／Pydantic／TypeScript／protobuf，也不修改 Contract、Runtime 或 Schema

## 0. 阅读与决策约定

### 0.1 Field Catalog 不是序列化设计

本文中的字段名是**领域词汇候选**，用于提出并评审语义、所有权和消费关系，不等于最终 wire name，也不表示该字段应成为 ModuleContent 一级字段。对象之间的拥有关系可以在未来采用内嵌、稳定引用或编译索引；本轮不决定物理布局。

“报告正文存在某项内容”只证明需要保真承载。只有同时具备明确 Producer、确定 Consumer、可验证约束、迁移方案和端到端证据的字段，才有资格进入正式 Contract。

### 0.2 两个相互独立的状态维度

字段成熟度使用用户要求的四类：

| 代码 | 类别 | 含义 |
|---|---|---|
| **C** | 核心字段（v1 必须） | 目标 v1 必须保留的字段职责，依据是当前兼容职责或样本最低表达范围与明确消费者；不表示每个对象实例都非空，也不表示新对象名已获准迁移 |
| **R** | 推荐字段 | 有明确领域价值，建议进入下一轮目标模型评审；字段形态或 catalog 仍可能 OPEN，不能据此冻结 |
| **K** | 可选字段（Capability） | 只在相应可选能力对象启用时出现；不能成为逐模组必填 |
| **H** | 暂缓字段 | 领域需求存在，但字段形态、基数、catalog 或消费者尚未冻结 |

为避免与仓库正式的 Candidate → Accepted → Specified → Implemented → Supported 流程混淆，字段卡片中的第二个标签只表示**本报告的分析就绪度**，不是正式决策状态：

| 状态 | 含义 |
|---|---|
| **Current** | 当前 `contracts/module.py` 存在同名或等价职责，并有本文明确列出的现行读取事实；不表示目标重构已 Accepted |
| **Review-ready** | 语义职责足以提交下一轮字段评审，但尚未被团队 Accepted，更不等于 Specified／可冻结 |
| **Candidate** | 有样本和领域证据，仍需消费者原型或职责确认 |
| **OPEN** | 字段形态、基数、catalog 或职责分界至少一项未决定 |

除当前 Contract 中保持原义的精确字段外，本文提出的目标字段在仓库正式决策流程中一律仍是 **Candidate**；本文无权将其升级为 Accepted 或 Specified。`C` 不自动等于可以用新名字直接加入当前 Schema。例如 `ContentUnit.content_unit_id` 与当前 `Scene.id` 语义相近，但 Scene → ContentUnit 仍是破坏性迁移。

成熟度与对象内必填性相互独立。`R` 字段一旦被团队采纳，也可以在其对象内“始终必填”；这不把它追溯升级为当前 v1 的 C。反之，某个 `K`／`H` Capability 对象内部的 ID 可以条件必填，但不能因此成为逐模组核心字段。

对象或执行能力的整体成熟度取其执行关键字段中的最弱状态。Information 的 disclosure／recipient、Timeline 的 clock、Track 的 measure／mutation、Encounter 的 driver／activation 等仍为 OPEN，因此这些能力整体仍是 Candidate／OPEN；个别 ID 或叙事字段达到 Review-ready，不能提升整条执行链。

### 0.3 Producer、来源与生命周期

- **Parser** 只在 ModuleDraft 中生成候选值，并保留来源、置信度和歧义。
- **Normalization** 归一术语、文本和候选分类。
- **Compiler** 分配稳定 ID、解析引用、选择已支持 catalog，并生成待发布字段。
- **Editor** 只对歧义、缺失或内容创作决策进行明确补充，不伪造原文证据。
- **Validation** 只读字段并产生报告，不生成内容值。
- **Publish** 冻结已验证值和版本，不创造领域语义。

来源必须写成“标题段直接提取”“正文背景段归纳”“Compiler 分配”“Editor 明确补充”“引用解析”等具体类别。Parser provenance、页码、bbox 和 confidence 不进入 Published ModuleContent，但继续由 ParserResult／Review sidecar 保留；发布不能删除审计证据。

### 0.4 Consumer 与 Runtime 标记

目录使用以下消费者名称：

- **Loader**：选择发布版本并建立 Runtime 只读定义。
- **Runtime**：导航、交互、规则、状态初始化或终局执行。
- **Projection**：结合 ModuleContent 与 GameState 计算安全视图。
- **Host Agent**：只读取 Projection／受控 Keeper Context，不绕过可见性边界读取原始秘密。
- **Validation**：检查字段、引用、catalog 与不变量。
- **Review**：检查来源忠实度、可达性、泄密和主持可用性。
- **Ruleset**：提供并校验技能、难度、解析器、状态或遭遇算法。

Review 是所有获准字段的横切只读消费者：它逐字段核对来源、对象归属、成熟度、可见性和迁移忠实度。后文字段卡的 Consumer 单元优先列直接业务读取者，可能不重复写 Review；Consumer Matrix 的 Review 列统一给出这项横切职责。

若字段写明“Runtime 不读”，它只能因为 Projection、Host Agent、Validation 或 Review 有明确消费价值而保留；否则不能进入 Contract。

### 0.5 必填与默认值规则

- **始终必填**：对象一旦结构化就必须存在；缺失阻断发布。
- **条件必填**：只有相应 variant、能力或引用方式成立时必填。
- **可选**：缺失具有明确语义，不得由 Runtime 猜造。
- 必填字段通常**无默认值**。
- 可选叙事字段缺失表示“原文未声明或未结构化”，不能默认生成空话术。
- Collection 可以默认空集合，但“空集合”不等于该能力已受支持。
- 自然语言裁量不得默认编译为 Condition 或 Effect。
- 对 **H / OPEN** 字段写出的“获准后条件必填”只是待原型验证的安全门槛，不是已冻结的 Schema cardinality；若缺失语义仍未确定，该字段当前就不可发布，而不是让 Runtime 猜默认。

### 0.6 跨对象单一权威规则

1. ModuleIdentity 是模组身份的唯一权威；ModuleFrame 不复制身份字段。
2. ModuleFrame 只保存模块级叙事摘要；结构化 Fact 的唯一权威是 InformationItem。
3. Information 的执行授予只有一条路径：Outcome／Rule → ordered Effects → InformationAcquisition → InformationItem。
4. Rule 直接拥有 Effects，不产生 Outcome。
5. Outcome 只属于 Interaction、Encounter 或 Ending 的结果语义；自动内容事件直接由 Rule → Effect 表达。
6. ContentRelation 是内容连接的唯一权威；ContentUnit 不保存另一套前驱／后继列表。
7. RuleScope 和 InteractionTargetRef 使用类型化引用；数量与组合仍为 OPEN。
8. 当前状态、已知信息、当前地点、当前 Track 值、当前 Encounter 和 EndingState 都属于 GameState／Event，不进入本目录的静态字段。
9. 不设置任何无明确语义的兜底字段，也不允许任意脚本或未经注册的键值包。
10. EncounterDefinition 拥有其局部 `outcome_definitions`；EncounterEndRule 只能引用父 Encounter 内的 Outcome，不能借用 Interaction 私有 Outcome 或 Ending terminal outcome。

### 0.7 样本证据集索引

字段卡片中的集合简称只引用输入报告已经列出的样本，不增加新统计：

| 简称 | 样本 |
|---|---|
| **All-15** | 百鸟朝凤、复足、苍白面具之下、更好的明天、死者的顿足舞、蝶骨巢穴、伦道夫·卡特的续述、追书人、柏林：失去昨日、科比特先生、RE计划、鬼屋、幸福蛙蛙村、追沙、银之锁 |
| **Focus-5** | 追书人、银之锁、复足、追沙、RE计划 |
| **Timeline-12** | 百鸟朝凤、复足、更好的明天、死者的顿足舞、蝶骨巢穴、伦道夫·卡特的续述、追书人、柏林：失去昨日、科比特先生、RE计划、幸福蛙蛙村、追沙 |
| **Track-7** | 百鸟朝凤、复足、苍白面具之下、蝶骨巢穴、伦道夫·卡特的续述、幸福蛙蛙村、追沙 |
| **Template-4** | 复足、死者的顿足舞、追沙、RE计划；其中《死者的顿足舞》命中依赖套件公共材料，不能等同于模组正文内完整模板 |
| **Graph-2** | 苍白面具之下、追沙 |
| **Role-private-1** | RE计划 |

`15/15` 表示 All-15 中该伞形概念的 E+N 覆盖，不表示同名字段逐模组必填。ID、引用、catalog 和冲突政策等 Compiler／Runtime 字段若没有直接正文形态，证据栏会以当前 Contract 或消费者不变量为依据，不能伪称为样本频次。

证据栏中的裸 `15/15` 与 **All-15** 完全同义；其他子集使用上表简称或直接列出模组名。若某字段仅由引用完整性、事务或消费者协议推出，证据栏必须明确写“无正文直接字段证据”并说明所依赖的不变量，不能把执行设计伪装成样本事实。

## 1. 当前 v1 基线与迁移读法

当前可执行 ModuleContent 仍只有：

| 当前对象 | 当前字段 |
|---|---|
| ModuleContent | `module_id`、`version`、`world_ref`、`background`、`scenes`、`entities`、`checkpoints`、`win_conditions` |
| Scene | `id`、`name`、`content`、`entity_ids`、`checkpoint_ids` |
| Entity | `id`、`kind`、`name`、`aliases`、`content`、`secrets`、`state`、`refuse_ops`、`blocked_text`、`direct_responses`、`rules` |
| Rule | `id`、`hook`、`priority`、`when`、`then`、`facts`、`player_visible_information` |
| Condition | `path`、`equals` |
| Operation | `op=allow/action` 或 `op=modify/path/set` |
| Checkpoint | `id`、`scene_id`、`action`、`target_id`、`skills`、`difficulty`、`mvp_check_result`、`outcomes` |
| CheckpointOutcome | `facts`、`player_visible_information`、`narration_constraints`、`ops` |
| WinCondition | `id`、`when`、`fact`、`player_visible_information` |

其中 `mvp_check_result` 是测试过渡字段，不进入目标 Field Catalog。`facts`、`player_visible_information`、`secrets` 和直接回应等当前字符串字段需要迁移到明确的信息、可见性和交互职责，不能作为多套事实源长期保留。

下文的 `Current` 表示“存在可迁移的当前语义”，不是授权把新对象和旧对象同时加入 Schema。

## 2. 字段卡片格式

每个对象使用两张以“字段”为主键的表：

1. **语义表**给出语义定义、存在理由、为什么属于本对象而不是相邻对象、概念类型、反例、样本证据与成熟度。
2. **运行表**给出具体 Producer、精确来源、Consumer、生命周期、必填性、默认值、Validation 与 Runtime 意义。

两张表中同名行合起来构成完整字段卡片。字段未出现在表中即表示本轮不接受，不能通过实现自行补充。

# ModuleContent

对象结论：ModuleContent 是发布聚合根。这里只目录化稳定的根值对象，不把 Entity、Information、Rule、Ending 和每种 Capability 逐项变成一级集合。它们与聚合的所有权是领域关系，最终采用内嵌、引用还是编译布局仍为 OPEN。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `identity` | 本发布物的模组身份、内容版本和 Ruleset 绑定 | 聚合根必须能被 Loader 唯一识别；它不是 ModuleFrame 的故事内容。不得放标题以外的宣传资料、发布哈希或来源审计 | ModuleIdentity 值对象 | 15/15 有模组身份；**C / Candidate**：`module_id`／版本职责有当前迁移输入，但 `ruleset_ref` 的 Provider 解析链仍未成立 |
| `frame` | 模组级前提、幕后摘要、主持指导及可选进入定义 | 解决跨 ContentUnit 的全局叙事语境；局部场景正文属于 ContentUnit，原子事实属于 InformationItem。不得保存当前开局选择 | ModuleFrame 值对象 | 前提、幕后、进入均 15/15；独立结构未获准，**R / Candidate** |
| `content_graph` | 需要寻址、导航或运行跟踪时形成的可游玩内容定义及关系 | 解决内容单元的所有权和可达关系；物理空间属于 Location，当前进度属于 GameState。不得把纯排版章节强制对象化 | ContentGraph 值对象 | 内容段 E+N 为 15/15，银之锁为 N；**R / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `identity` | Parser 从标题／导入清单提取候选；Compiler 规范 ID、版本和引用；Editor 解决缺失；Publish 冻结 | Loader 选版本；Validation 查兼容；Runtime／Ruleset 读取绑定；Projection／Host 读取可展示身份；Review 对来源 | Draft 出现，Compile 固化，Published 后不变 | 始终必填；无默认 | Module ID 与版本非空；引用可解析；版本兼容 | Runtime 必须知道加载哪个静态发布物以及按哪个 Ruleset 解释 |
| `frame` | Parser 从玩家信息、背景、守秘人信息和主持说明段提取；Normalization 合并重复段；Editor 解决摘要边界 | Host Agent 经受控 Keeper Context 读取；Projection 只读玩家安全部分；Review 查忠实度 | Draft 可带来源与歧义；Published 只留内容和引用；跨局不变 | 可选；缺失不生成摘要；若对象存在至少有一个有效字段 | 玩家安全与 Keeper 内容分区；Information 引用存在；不能含 Parser provenance | Runtime 核心不读；因 Host、Projection 和 Review 有消费者而保留 |
| `content_graph` | Parser 识别显式／隐式内容段；Compiler 仅在消费者要求时分配 ID、建关系和解析引用 | Validation 查图；Runtime navigation 条件读取；Projection／Host 按当前 ContentUnit 读取 | Draft 可只保留文本段；Compile 可结构化；Published 后不变；进度另存 | 条件必填；只有结构化导航 Profile 要求；无默认图 | Unit／Relation 引用闭合；不得产生双向重复事实源；Profile 可要求可达 | 只在导航、交互路由或进度跟踪启用时读取 |

### 明确不是字段

- 不设置统一的任意定义集合；这会把未获准能力伪装成可扩展 Contract。
- 不保存 Publication hash、rights、文件路径、Parser provenance、ValidationReport 或 ReviewReport。
- 不保存当前 ContentUnit、当前 Entity 状态、已知信息、当前时钟或 EndingState。

发布不变量：每个被引用的 Entity、Information、Acquisition、Interaction、Rule、Ending 或 Capability Definition 都必须能从**同一 ModuleContent 聚合所有权边界**解析；采用类型化 registry、父对象内嵌还是编译索引仍为 OPEN，但不得依赖另一个未声明发布物中的偶然对象。

# ModuleIdentity

对象结论：ModuleIdentity 只回答“这是哪个模组的哪个内容版本，并由哪个规则系统解释”。标题属于身份；故事摘要不属于身份。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `module_id` | 跨版本稳定的模组身份 | Loader、引用和存档需要稳定主身份；标题可改名，不能充当 ID。不得使用文件名、绝对路径或内容哈希 | Stable Identifier | 15/15 可识别模组；当前 `module_id`，**C / Current** |
| `content_version` | 同一模组发布内容的版本 | 区分修订后的静态定义并支撑迁移；它不是 Contract 格式版本，也不是 Runtime revision | Version Identifier | 当前 `version` 仅由 Contract 要求非空；目标 Loader／兼容消费仍需实现，**C / Review-ready**（有当前等价必填语义），wire rename OPEN |
| `title` | 面向人类显示的规范模组标题 | Host、Projection 和 Review 需要可读名称；它属于身份展示，不是 ModuleFrame 的剧情摘要。不得塞副标题之外的宣传文案 | String／Display Text | 15/15 有标题；**R / Review-ready** |
| `ruleset_ref` | 指向解释技能、难度和算法的 Ruleset Provider／版本 | Validation、Loader 和 Ruleset 需要确定语义环境；它不是故事世界背景。不得放自然语言时代、地点或任意 Provider 配置 | Ruleset Reference | 当前 `world_ref` 只是非空字符串形式的 Ruleset 身份迁移起点；Provider 形态和解析链未定，**C / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `module_id` | Parser／导入流程从受控清单或 Editor 指定值生成候选；Compiler 规范命名；Publish 冻结 | Loader、Validation、Runtime、Review 读取 | 首次导入产生；跨内容版本稳定；不得因改标题变化 | 始终必填；无默认 | 非空；符合 ID 规范；Repository 作用域唯一 | GameState 与 Event 通过它绑定静态模组 |
| `content_version` | Parser 读取显式版本；缺失时 Editor 明确指定；Compiler 规范；Publish 冻结 | Loader 做版本选择；Validation 做兼容检查；Review 对修订来源 | 每次内容发布可变；单个 Published ModuleContent 内不变 | 始终必填；无默认，不从日期猜造 | 合法版本格式；同 module_id 下发布身份唯一；迁移政策可解析 | Runtime 只读，用于拒绝错误存档或缓存 |
| `title` | Parser 从标题页／文档标题直接提取；Normalization 清理排版；Editor 解决多个标题 | Projection 显示；Host Agent 识别；Review 对原文 | Draft 提取，Published 固化；修订可变但不改变 module_id | R 字段一旦被下一版 Contract 采纳即始终必填；当前 v1 缺字段时不得由 module_id 自动美化；无默认 | 去除纯空白；必须有来源或 Editor 决议；长度与字符政策由 UI 确认 | Runtime 算法不读；因 Projection、Host 和 Review 有直接消费者而保留 |
| `ruleset_ref` | Parser 从模组规则版本／导入配置产生候选；Compiler 解析 Provider；Editor 补充无法提取项 | Loader、Validation、Runtime 组合根、Ruleset 读取 | Draft 可未解析；发布前必须解析；Published 后不变 | 始终必填；无默认，不得默认 CoC 版本 | Provider／版本存在且兼容；字段语义与当前 `world_ref` 迁移一致 | Runtime 用它选择 CheckResolver、状态和规则算法 |

# ModuleFrame

对象结论：ModuleFrame 是模块级叙事框架，不是事实数据库，也不是所有 ContentUnit 正文的拼接。结构化 Fact 存在时，Frame 只摘要并引用。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `summary` | 面向 Keeper／Review 的全模组短摘要 | 让消费者在不遍历全部 Unit 时理解整体结构；它跨越所有 ContentUnit，因此不属于某一个 Unit。不得复制逐场景正文或充当权威 Fact | Keeper Summary | All-15 均可归纳整体内容，但原文未必有摘要；**R / Candidate** |
| `player_premise` | 开局前可安全告知全体玩家的共同前提 | Projection／Host 需要安全导入语境；多入口共享的内容属于 Frame，某入口专有介绍属于 EntryPoint。不得含幕后真相 | Player-safe Narrative | 伞形“前提”E+N 为 15/15，但报告未单独统计玩家安全共同文本；**R / Candidate** |
| `keeper_background` | Keeper 需要理解的幕后因果叙事摘要 | 解释“为什么发生”；它是主持上下文，不是 InformationItem 的原子事实权威。不得保存已知状态或可执行规则 | Keeper Narrative | 幕后信息 15/15；**R / Candidate** |
| `background_information_refs` | 指向已结构化幕后 Fact／InformationItem 的稳定引用 | 防止 Frame 文本与 Fact 形成双权威源；引用属于摘要上下文，信息正文仍属于 InformationItem。不得直接授予玩家信息 | Collection of Information References | Information 15/15；独立信息结构待原型，**H / OPEN** |
| `keeper_guidance` | 适用于整个模组的非执行主持建议 | 保存节奏、即兴和裁量边界；局部建议属于 ContentUnit／Interaction。不得放可机器判定的 Condition 或任意脚本 | Keeper Guidance | Focus-5 均可找到主持说明，但报告未单独统计字段覆盖；**H / Candidate** |
| `entry_points` | 本 Frame 拥有的结构化开局方式 | 多 HO、多职业或多导入需要不同绑定；它属于全局开局语境，不属于 ContentGraph 的路径关系。不得保存本局选中了哪一个 | Collection of EntryPoint | 进入方式 15/15，但独立结构无消费者；**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `summary` | Parser 从显式摘要直接提取，或从背景段生成带 provenance 的推导候选；无原文摘要时必须由 Editor 明确批准／撰写；Compiler 只规范文本和解析引用 | Host Agent Keeper Context、Review 读取 | Draft 可携来源；Published 固化；不随游戏更新 | 可选；无默认，不自动生成 | 不得引入原文外因果；若引用 Fact，摘要不得冲突 | Runtime 不读；Host／Review 需要全局定位 |
| `player_premise` | Parser 从玩家信息、导入前言直接提取；Editor 明确去除泄密内容 | Projection 与 Host Agent 读取；Review 做防泄密检查 | Draft 分类可见性；发布后静态；实际展示事件不写回 | 可选；缺失表示无统一前提 | 必须通过玩家安全审查；不能引用 Keeper-only Information | Runtime 可在建局时转交 Projection，但不解释文本 |
| `keeper_background` | Parser 从守秘人信息、真相、异常原理段提取；Normalization 去重；Editor 解歧义 | 受控 Keeper Context 与 Review 读取；玩家 Projection 忽略 | Draft 带来源；Published 只留摘要；跨局不变 | 可选；无默认 | 与引用 InformationItem 一致；不得进入玩家视图 | Runtime 核心不读；Host 通过受控上下文消费 |
| `background_information_refs` | Compiler 在 InformationItem 已获准结构化时由摘要引用解析生成 | Validation、Review、Keeper Context Builder 读取 | Compile 生成；若信息能力未启用则字段不存在 | 条件必填：摘要引用结构化 Fact 时；默认空集合 | 每个引用存在；不得指向禁止 Keeper 读取的错误作用域 | Runtime 不直接读；Context Builder 解引用 |
| `keeper_guidance` | Parser 从全局 KP 建议直接提取；Editor 可明确补充 | Host Agent、Review 读取 | Draft → Published；不会因某局裁量结果回写 | 可选；无默认 | 必须标记为非执行；不能伪装 catalog Condition／Effect | Runtime 永远不执行；因 Host 消费保留 |
| `entry_points` | Parser 识别不同导入；Compiler 分配 ID 和引用；Editor 解决 HO／角色绑定 | Loader、建局 Runtime、Projection、Host、Validation 读取 | Draft 可只保留叙事；消费者启用后 Compile 结构化；选择结果进 GameState | 可选；默认空集合不代表 EntryPoint 能力 Supported | ID 唯一；目标和角色模板引用存在；多入口基数保持开放 | 只有建局／角色级投影原型启用后读取 |

# EntryPoint

对象结论：EntryPoint 描述一种静态开局方式。本局选择、角色实例和当前 ContentUnit 都不在这里。进入方式 15/15 不等于所有模组都必须建立 EntryPoint 对象。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `entry_point_id` | 一种结构化开局方式的稳定身份 | 多入口可能汇入同一 Unit，不能用 Unit ID 或角色 ID 代替。不得保存玩家或本局选择 ID | Stable Identifier | 《RE计划》多 HO、《幸福蛙蛙村》多导入；**H / OPEN** |
| `label` | 供建局界面、Host 和 Review 区分入口的短名 | 它只标识开局变体，不是模组标题或角色模板名。不得机械生成无语义“入口 1” | Display Text | 多入口样本；**H / Candidate** |
| `player_introduction` | 该入口专有、可安全展示的参与动机与初始处境 | 共享前提属于 ModuleFrame；角色规则数据属于 CharacterTemplate。不得含其他 HO 秘密或当前角色状态 | Player-safe Narrative | 《RE计划》HO 导入、《追书人》委托、《银之锁》醒来处境；**H / Candidate** |
| `start_content_unit_ref` | 选择该入口后进入的首个结构化 ContentUnit | 不属于 ContentGraph 默认根，因为不同入口可有不同起点。不得指向 Location 或保存当前 Unit | ContentUnit Reference | 多入口／汇流内容；**H / OPEN** |
| `eligible_character_template_refs` | 可使用该入口的 CharacterTemplate 引用候选 | 模板本身定义角色准备；EntryPoint 只表达入口适用关系。不得内嵌角色卡或玩家 ID；缺失／空集合究竟表示未声明、全部可用还是无模板可用，必须由 Character Setup 协议决定 | Candidate Collection of CharacterTemplate References | Template-4，其中《死者的顿足舞》可能来自套件公共材料；《RE计划》关系最明确，**K / OPEN** |
| `availability_condition` | 入口可被选择的受限硬条件 | 只表达机器可判定前提；自然语言角色要求仍是 Host guidance。不得保存已求值结果 | Condition Value Object | 固定身份、前置入口存在，但统一求值未证明；**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `entry_point_id` | Compiler 根据导入／HO 锚点分配；Editor 消歧；Publish 冻结 | Loader、Validation、建局 Runtime、Review 读取 | Draft 候选无稳定 ID；Compile 产生；Published 后不变 | EntryPoint 一旦结构化始终必填；无默认 | Frame 内唯一；版本内稳定 | GameState 可记录选中的入口引用；多角色可有多条 EntrySelection |
| `label` | Parser 从 HO／导入标题直接提取；Editor 在无标题时明确补充 | Projection、Host、Review 读取；Runtime 只透传 | Draft → Published | 条件必填：有入口选择 UI 时；否则可选；无默认 | 非空；同一 Frame 内可区分；安全可展示 | Runtime 算法不读；建局选择器需要 |
| `player_introduction` | Parser 从该导入正文提取；Compiler 去除共享前提重复；Editor 做泄密审查 | Projection、Host、Review 读取 | Draft 分类受众；Published 静态 | 可选；无默认 | 只能包含该入口获准内容；不得绕过 Information disclosure | Runtime 建局时交给 Projection，不解释自然语言 |
| `start_content_unit_ref` | Compiler 根据导入和首个可游玩段做引用解析；Editor 处理汇流歧义 | Loader、Runtime navigation、Validation、Host 读取 | Compile 生成；Published 静态；当前 Unit 进入 GameState | 结构化导航 Profile 条件必填；无默认 | 引用存在且可作为入口；ContentGraph 能寻址 | 初始化 ContentProgress／当前上下文 |
| `eligible_character_template_refs` | Compiler 解析导入与模板关系；Editor 确认 | Character Setup Loader、Validation、Ruleset、Projection 读取 | 当前停留 Candidate；Character Setup 的选择基数／互斥／assignment 协议成立后才可 Published | 当前不可发布；未来由 Character Setup 协议决定是否必填及空集合语义；无默认 | 引用存在；与 Module Ruleset 兼容；不能代替队伍选择／席位分配政策 | 仅建局读取；当前是 Capability Gap |
| `availability_condition` | Parser 从明确硬条件产生候选；Compiler 只映射已注册谓词；Editor 确认 | Validation、建局 Runtime、Review 读取 | Draft 可为自然语言；不支持时留 guidance／Gap；可执行值在 Compile 形成 | 可选；缺失表示没有额外机器条件 | 纯谓词；只读注册上下文；不能包含 Host 裁量 | 建局时求值；不产生 Effect |

### 明确不是字段

- 不设置 `selected`、`selected_by`、当前角色或当前 Scene。
- 不在 EntryPoint 内复制 CharacterTemplate、InformationItem 或 ContentUnit 正文。
- 不设置直接 `initial_acquisition_refs`；入口选择必须发出注册 Trigger，由 Rule 的 Effect 激活 InformationAcquisition，保持唯一授予链。
- 自然语言“适合某职业”“KP 可调整”不能进入 `availability_condition`。

# ContentGraph

对象结论：ContentGraph 只拥有 ContentUnit 与 ContentRelation。EntryPoint 决定入口；Location 拥有空间拓扑；GameState 拥有当前进度。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `content_units` | 图内已获准结构化的可寻址内容定义 | Unit 与 Relation 必须在同一图边界校验；不应成为另一个 ModuleContent 顶层数组。不得放原始段落或当前 Unit | Owned Collection of ContentUnit | 内容段 E+N 15/15；**R / Candidate** |
| `content_relations` | 图内内容单元之间的类型化关系 | 关系集中所有可避免每个 Unit 双写前驱／后继。不得放 Location 出口或玩家已走路径 | Owned Collection of ContentRelation | Graph-2（《苍白面具之下》《追沙》）为显式网状调查，线性／并行样本也有关系语义；**R / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `content_units` | Parser 从章节、场景、任务、地点段和连续解谜段提出候选；Compiler 只在寻址消费者成立时分段并分配 ID；Editor 修订 | Validation、Runtime navigation、Projection、Host、Review 读取 | Draft outline 可保持文本；Compile 结构化；Published 静态 | ContentGraph 若用于可执行导航至少一项；不建立无意义空图 | ID 唯一；每个 Unit 有内容；不得保存运行进度 | 按稳定 ID 查找当前静态内容 |
| `content_relations` | Parser 提取显式流程／路线；Compiler 归一包含、顺序、替代、解锁；Editor 确认推导关系 | Validation、Runtime navigation、Host、Review 读取 | Draft 候选 → Compile 边 → Published | 可选；默认空集合 | 端点存在；单一所有权；按 relation kind 校验环与重复；不能把排版顺序自动当剧情强制顺序 | 导航、解锁和图投影启用时读取 |

### 明确不是字段

- 不设置当前 Unit、已访问 Unit、当前分支或已激活关系。
- 不设置第二套 `root_unit_refs`；入口根由 EntryPoint 决定。
- 不保存 Location 连接或地图坐标。

# ContentUnit

对象结论：ContentUnit 是“因寻址、导航、局部上下文或运行跟踪而需要稳定身份的可游玩内容段”。Scene、Event、Task、Chapter、Encounter 和连续解谜段不是六个并列一级模型；它们是否成为 `unit_type`、引用到专用对象，取决于真实消费者。Location 只有在空间身份和拓扑需要独立生命周期时才独立，不应永远等同于 ContentUnit。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `content_unit_id` | 发布版本内稳定的内容段身份 | 导航、交互上下文、状态投影和引用需要寻址 Unit；它不是章节序号或 Location ID。不得使用数组位置、页码或标题作为永久身份 | Stable Identifier | 当前 `Scene.id`；15/15 有显式或隐式内容段，**C / Review-ready**（有当前等价语义） |
| `name` | 供 Keeper、编辑和投影识别该内容段的短名 | 名称不承担内容或类型语义；属于 Unit 而不是 ModuleIdentity。不得用完整场景正文或自动生成的“段落 17”填充 | Display Text | 当前 `Scene.name`；《银之锁》可从床／书桌／衣柜等段落标题提取，**C / Review-ready**（有当前等价语义） |
| `unit_type` | 在消费者已承诺时，对 Unit 的用途作受限分类 | 可帮助 Host／导航区分 scene、task、chapter 等，但样本未证明一个统一全集；Encounter 有专用执行职责时只能被引用，不能仅靠类型字符串替代。不得使用任意标签 | ContentUnit Type Catalog Value | All-15 同时出现 Scene、Location、Task、Chapter、Encounter 与连续解谜等不同分段，边界不一致；**H / OPEN** |
| `player_content` | 进入该 Unit 时允许构建玩家视图的主要叙事内容 | 解决当前 `Scene.content` 的未来玩家呈现职责；Keeper 建议另存 `keeper_guidance`，持久事实属于 InformationItem。不得含幕后答案、当前状态或可执行操作 | Player-safe Narrative Content | 内容段 15/15；当前 `Scene.content` 未做玩家／Keeper 分区，也未被 Player Projection 直接读取，只能作为迁移输入，**C / Candidate** |
| `keeper_guidance` | 仅适用于该 Unit 的主持说明、节奏和自然语言裁量 | 局部指导应随 Unit 定位；全模组建议属于 ModuleFrame，交互裁定属于 Interaction。不得伪装成 Condition／Effect | Keeper Guidance | Focus-5 均有局部主持文本；报告未单独统计字段覆盖，**R / Candidate** |
| `entity_refs` | 该内容段声明的静态参与对象：进入／初始化该 Unit 时预期可在场、可交互或直接参与内容的 EntityDefinition 引用 | Entity 的身份和正文仍由 EntityDefinition 权威定义；Unit 只声明初始参与关系，运行后的在场、离场和位置属于 GameState。仅在文本中被提及的对象属于叙事／Information，不得借此字段进入当前目标集合 | Collection of Entity References | 当前 `Scene.entity_ids` 提供迁移输入，All-15 均有参与对象；初始化／再次进入 Unit 的 placement 语义尚未原型化，**C / Candidate** |
| `information_refs` | 为 Keeper 构造该 Unit 上下文时可定位的信息引用 | 它只表示相关性，不表示玩家已获得，也不替代 Acquisition；信息本体属于 InformationItem。不得把引用列表当自动授予列表 | Collection of Information References | 信息 15/15；独立信息消费链尚待原型，**H / OPEN** |
| `interaction_refs` | 在该 Unit 上下文中可被发现或提出的 InteractionDefinition 引用 | 交互定义不应继续由 `Checkpoint.scene_id` 与 `Scene.checkpoint_ids` 双向维护；目录先表达语义，最终引用方向仍需 Runtime 原型。不得记录本局已尝试交互 | Collection of Interaction References | 当前 `Scene.checkpoint_ids` 与 `Checkpoint.scene_id` 双写；行动触发／后果 15/15，但字段方向未决，**H / OPEN**（ownership） |
| `location_refs` | 与该内容段相关的独立 LocationDefinition 引用 | 仅在 Location 具有跨 Unit 身份或空间拓扑时使用；普通“场景发生地”可留在叙事中。不得借此保存当前角色地点 | Collection of Location References | 《追书人》《追沙》多地点；《银之锁》单地点多对象，**K / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `content_unit_id` | Compiler 根据已确认的可寻址段落锚点分配；Editor 解决合并／拆分；Publish 冻结 | Loader、Validation、Runtime navigation、Projection、Host、Review 读取 | Draft 仅有 SourceFragment；Compile 建 ID；Published 后跨存档引用稳定 | ContentUnit 一旦结构化始终必填；无默认 | 图内唯一；引用闭合；版本迁移不得静默复用给不同语义段 | GameState／Event 通过它引用当前或已访问的静态内容 |
| `name` | Parser 从场景／章节／地点段标题直接提取；Editor 在消费者确需名称且原文无标题时明确补充 | Projection、Host、Review 读取；Runtime 只透传 | Draft → Published；重命名不改变 ID | 可选；列表展示 Profile 条件必填；无默认 | 非空；不得充当 ID；玩家可见时做泄密审查 | Runtime 算法不解释，只供上下文和展示 |
| `unit_type` | Parser 从章节／场景／任务标题、段落用途和可游玩边界提出候选；Normalization 对齐 catalog；Compiler 只输出目标 Profile 支持值 | Validation、Host、可选 navigation policy 读取 | 未获准时停留 Draft／Gap；catalog 冻结后才进 Published | 可选；无默认，不从标题猜造 | 值已注册；类型不得替代专用 Encounter／Location 引用 | 当前 Runtime 不应据自由类型分派；需消费者原型 |
| `player_content` | Parser 从该段玩家可感知正文直接提取；Editor 进行泄密分区 | Projection、Host、Review 读取；Runtime 透传当前 Unit 内容 | Draft 带 provenance；Published 静态；实际展示记录进 Event | 条件必填：该 Unit 需要玩家 Projection 时；否则可选；无默认 | 玩家安全；不能与 Keeper-only Information 混放；不能含执行指令 | Runtime 交给 Projection，不对自然语言作规则解释 |
| `keeper_guidance` | Parser 从该段 KP 提示／幕后处理直接提取；Editor 可明确补充 | 受控 Host Context、Review 读取；玩家 Projection 忽略 | Draft → Published；本局裁量结果不回写 | 可选；无默认 | Keeper-only；不可被 Validation 当可执行规则 | Runtime 不执行；Host 消费使其有保留价值 |
| `entity_refs` | Parser 只从该段明确出场、可交互或直接参与内容的对象提出关系；Compiler 解析到 Entity ID；Editor 区分“出场”与“仅被提及” | Validation、Host Context、Projection、Runtime Unit initializer／entity lookup 读取 | Compile 生成；首次进入／重建上下文时可作为初始参与输入，之后的在场／离场另存 GameState | 可选；默认空集合表示该 Unit 未声明静态参与对象，不表示 Runtime 当前无人 | 引用存在、去重；纯提及不得进入；发布 Profile 必须声明首次进入、重复进入和从既有 GameState 恢复时如何应用初始关系 | 为首次上下文初始化、交互目标解析和安全投影提供静态输入；绝不覆盖已存在的运行状态 |
| `information_refs` | Compiler 仅把已确认的上下文相关信息解析为引用；Parser 不直接产生发布引用 | Validation、Review、Keeper Context Builder 读取 | Information 能力启用时 Compile；获得状态另存 | 可选；默认空集合 | 引用存在；玩家 Projection 不得因该关系自动解引用 | Runtime 核心不读；Context Builder 必须再做可见性检查 |
| `interaction_refs` | Compiler 依据场景内明确行动点建立单向关系；Editor 处理一个 Interaction 多上下文的情况 | Validation、Runtime action discovery、Projection、Host 读取 | Compile 生成；尝试／完成记录进 Event／GameState | 可选；默认空集合；最终所有权方向 OPEN | 引用存在；不得与 Interaction 反向字段形成双权威；顺序若有语义须明确 | Runtime 在当前 Unit 构造候选交互；不能等同“现在一定可用” |
| `location_refs` | Parser 从明确地点段提出；Compiler 仅在 Location capability 启用时解析 | Validation、Host、Projection、可选 spatial runtime 读取 | Capability Compile → Published；当前地点另存 GameState | 可选；默认空集合 | 引用存在；不能把 Unit 和 Location 互相复制成一一对应 | 仅空间消费者启用时用于上下文／导航 |

### 明确不是字段

- 不设置 `current`、`visited`、`completed`、当前参与者或当前 Location。
- 不设置第二套前驱／后继，也不在 Unit 内嵌 ContentRelation 端点。
- 不设置 `rule_refs`；RuleScope 是局部规则关系的权威，Compiler 可生成 Unit→Rule 只读索引。
- 不设置 `encounter_refs`；本目录选择 `EncounterDefinition.context_refs` 作为关系权威，Compiler 可生成 Unit→Encounter 只读索引。
- 不因正文标题叫“Event”就假定它能自动调度；调度属于 Timeline／Trigger。
- 不因正文标题叫“Encounter”就假定战斗／追逐执行已受支持。

# ContentRelation

对象结论：ContentRelation 是两个 ContentUnit 之间的静态语义关系。它不等同于空间出口，也不记录本局是否走过。只有需要被 Effect 激活、Event 引用或独立审计的关系才需要稳定 ID。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `relation_id` | 可独立引用的内容关系身份 | 动态激活、规则效果或审计需要引用关系本身时才有意义；端点组合不一定足以稳定识别。不得用数组下标 | Optional Stable Identifier | 解锁型路线存在，但关系级 Runtime 未实现；**H / OPEN** |
| `relation_type` | 两个内容段之间的受限语义，如顺序、替代、包含或可转场 | 类型决定校验和导航解释，属于关系而不是 Unit；不得把所有排版先后标成强制剧情顺序，也不得使用任意字符串 | ContentRelation Type Catalog Value | 《追沙》网状、《RE计划》并行／汇流、《银之锁》连续谜题；**H / OPEN** |
| `source_content_unit_ref` | 关系的语义起点 | 端点属于 Relation 的单一权威；不应在 source Unit 再写 successors。不得指向 Location | ContentUnit Reference | 《追沙》的网状路线、《RE计划》的并行汇流、《银之锁》的连续谜题提供端点证据；**R / Candidate** |
| `target_content_unit_ref` | 关系的语义终点 | 与起点共同形成有向关系；不应在 target Unit 再写 predecessors。不得保存当前目标 | ContentUnit Reference | 《追沙》网状路线、《RE计划》并行汇流、《银之锁》连续谜题；**R / Candidate** |
| `availability_condition` | 该关系在静态图上何时可用的纯谓词 | 它只限制关系可达性；实际激活状态属于 GameState，产生解锁的操作属于 Effect。不得写“KP 认为合适时” | Condition Value Object | 门、物品、任务与状态条件在样本中存在；统一求值未证明，**H / OPEN** |
| `choice_label` | 当多条安全可见关系形成玩家选择时显示的短提示 | 属于关系的选择呈现，不是 target Unit 名称或 Outcome 反馈；只有 Host／Projection 原型证明需要才保留 | Player-safe Display Text | 《追书人》调查路径、《银之锁》结尾选择；**H / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `relation_id` | Compiler 仅对需独立引用的显式关系分配；Publish 冻结 | Validation、Effect executor、Runtime navigation、Review 读取 | Compile 产生；已激活／已走过状态另存 | 条件必填：被引用或动态激活时；否则可省；无默认 | 图内唯一；被引用关系必须有 ID；不能因排序变化重编号 | 作为解锁 Event 与关系状态的定义键 |
| `relation_type` | Parser 提出关系语义；Normalization 对齐 catalog；Editor 确认隐式关系；Compiler 输出支持值 | Validation、Runtime navigation、Host graph view 读取 | Draft 候选 → catalog 支持后 Published | 始终必填于结构化 Relation；无默认 | 类型受支持；端点方向与类型兼容；包含关系与转场关系不得混用 | 决定 Runtime 是组织、推荐还是可执行导航；catalog 仍需原型 |
| `source_content_unit_ref` | Compiler 从明确流程、解锁或编辑决议解析 | Validation、Runtime、Review、待原型 Host graph view 读取 | Compile → Published | 始终必填；无默认 | 引用存在；与 target 不构成该类型禁止的自环 | Runtime 建立出边索引；Host 图视图原型需证明端点最小暴露 |
| `target_content_unit_ref` | Compiler 从明确后继／目标段解析 | Validation、Runtime、Review、待原型 Host graph view 读取 | Compile → Published | 始终必填；无默认 | 引用存在；类型不允许时禁止重复边 | Runtime 建立可达目标；Host 图视图原型需证明端点最小暴露 |
| `availability_condition` | Parser 从明确硬条件提出；Compiler 仅映射已注册谓词；不支持部分保留为 guidance／Gap | Validation、Condition evaluator、Runtime navigation 读取 | Draft 可能仅自然语言；可执行值在 Compile 形成；求值结果另存 | 可选；缺失表示无额外谓词，不表示已动态激活 | 纯谓词；引用合法；不能产生 Effect | 导航查询时求值，不修改状态 |
| `choice_label` | Parser 从选项文本直接提取；Editor 做玩家安全审查 | Projection、Host 读取；Runtime 透传 | Draft → Published；玩家实际选择另存 Event | 可选；无默认，不用 target name 自动代替 | 非空；不得泄露未解锁内容或 Keeper 条件 | Runtime 算法不读；安全选择 UI 需要 |

### 明确不是字段

- 不设置 `is_active`、`traversed`、`selected_by` 或运行时间戳。
- 不在 Relation 中复制 Location 空间边；空间拓扑属于 LocationDefinition。
- 不把 Outcome 作为关系字段；Outcome 可通过 Effect 激活关系。

# EntityDefinition

对象结论：EntityDefinition 提供可被引用、呈现或持有初始化状态的参与对象定义。NPC、Monster、Organization、Item 和 Environment Object 可以共享身份、名称、描述与状态初始化边界；其专用属性必须由 Ruleset profile 或专用能力承担。Location 只有在仅作为命名实体时可复用普通身份，空间包含、出口和当前位置不能被强塞进通用 Entity。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `entity_id` | 模组发布版本内稳定的参与对象身份 | Unit、Interaction、RuleScope 和状态实例需要引用同一对象；不得用名称、人物卡编号或 Runtime actor ID 替代 | Stable Identifier | 当前 `Entity.id`；参与对象 15/15，**C / Current** |
| `name` | 该实体的规范显示名 | 显示名属于实体身份但不承担引用；不得把称谓变化或当前伪装状态写入规范名 | Display Text | 当前 `Entity.name`；**C / Current** |
| `aliases` | 原文中可安全披露、用于解析同一实体的稳定词面别名 | Parser 消歧和 Host 查找需要；属于同一实体，不应创建重复定义。秘密身份关系必须进入 InformationItem／KnowledgeState 后由 Projection 派生，不得放在这里 | Collection of Player-safe Alias Text | 当前 `Entity.aliases` 是迁移起点；《追书人》人物称谓提供非秘密别名例，**C / Review-ready** |
| `entity_categories` | 对参与对象非互斥语义类别的受限声明 | 同一身份可同时具有 NPC、monster、organization、item 或 environment-object 语义；类别属于 Entity，不是 ContentUnit，专用能力仍由 profile 组合。不得强选单一“主类型”或把 Location 空间能力塞入 | Collection of Entity Category Catalog Values | 当前单值 `Entity.kind` 仅是迁移事实；《追书人》中同一身份跨 NPC／monster 职责证明基数不能冻结，**H / OPEN**（catalog/cardinality） |
| `player_description` | 在可见性允许时可用于玩家视图的实体描述 | 解决当前 `Entity.content` 的玩家呈现职责；秘密和主持解释不应混入。不得存当前伤势、已知关系或 Keeper 战术 | Player-safe Narrative | 当前 `Entity.content` 可迁移部分；参与对象 15/15，**C / Review-ready**（需可见性拆分） |
| `keeper_context` | 仅供 Keeper 理解该实体的静态背景与自然语言扮演建议 | 它是主持上下文，不是 InformationItem 的权威 Fact，也不是 Rule。不得存玩家当前已知、可执行拒绝逻辑或 arbitrary memory | Keeper Narrative | 当前 `secrets`、部分 `content` 的保真去向；**R / Candidate** |
| `ruleset_profile_refs` | 指向该实体所采用的 Ruleset 专用静态档案 | 战斗数值、技能、SAN、法术算法由 Ruleset 定义；Entity 只绑定，避免复制跨规则系统字段。不得放任意属性字典 | Collection of Ruleset Profile References | 《追书人》的 NPC／怪物、《复足》的感染相关角色、《追沙》的势力人物、《RE计划》的预设角色均含规则数据；当前无统一 consumer，**H / OPEN** |
| `initial_state` | 新建 GameState 中该实体实例的类型化初始状态声明 | 静态定义只负责初值；当前值和变化历史属于 GameState／Event。不得使用无约束键值对象、任意 path 或保存运行快照 | Typed State Initializer Value Object | 当前 `Entity.state` 是迁移事实；状态类型目录和 Loader 尚未冻结，**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `entity_id` | Compiler 根据稳定正文锚点和编辑决议分配；Publish 冻结 | Loader、Validation、Runtime、Projection、Host、Review 读取 | Compile 产生；Published 后稳定；Runtime instance 使用另一身份 | Entity 一旦结构化始终必填；无默认 | 模块内唯一；所有引用闭合；不得与 Runtime instance ID 混用 | 绑定静态定义、状态实例和 Event |
| `name` | Parser 从人物／怪物／物品／组织标题或首次正式命名提取；Editor 消歧 | Projection、Host、Validation、Review 读取 | Draft → Published；改名不改变 ID | 始终必填于可呈现 Entity；无默认 | 非空；若名称本身是秘密，需安全显示策略而非复制假名 Entity | Runtime 透传供呈现和目标确认 |
| `aliases` | Parser 从明确别名、非秘密称谓和拼写变体直接提取；Normalization 去重；Editor 确认同一性与披露安全 | Parser reference resolver、Validation、Projection、Host search、Review 读取 | Draft 用于消歧；Published 只保留 player-safe 受控别名；秘密关系另建 Information | 可选；默认空集合 | 规范化后不重复；不得导致引用歧义；任何会揭示隐藏身份的值阻断发布到此字段 | Runtime 核心可忽略；安全解析、Projection 和 Host 查找有消费者 |
| `entity_categories` | Parser 从人物／怪物／组织／物品／环境对象标题、介绍和规则数据块提出候选；Normalization 映射 catalog；Editor 处理重叠职责 | Validation、Ruleset、Runtime target resolver、Projection 读取 | Draft 可多候选；catalog 与组合政策获准后才可 Published | 可选；需要类型过滤或 profile 选择的 Profile 条件必填；无默认 | 每个值已注册；组合与 Ruleset profiles、动作目标约束兼容；不得要求唯一主类别 | 可用于目标过滤和 profile 选择，但不能单独触发算法 |
| `player_description` | Parser 从玩家可感知外观／简介直接提取；Editor 做秘密分区 | Projection、Host、Review 读取 | Draft 分类 → Published；当前外观变化另存状态／Event | 可选；无默认 | 玩家安全；不得与 keeper_context 冲突；不暗含自动授予事实 | Runtime 交给 Projection，不解释文本 |
| `keeper_context` | Parser 从 Keeper-only 人物秘密、动机、战术和扮演建议提取；Editor 明确拆分原子信息 | 受控 Host Context、Review 读取；玩家 Projection 忽略 | Draft 带 provenance；Published 静态；本局记忆不回写 | 可选；无默认 | Keeper-only；若内容被机器引用为 Fact 应拆成 InformationItem | Runtime 不读；Host／Review 消费使其保留 |
| `ruleset_profile_refs` | Parser 识别规则数据块；Compiler 交由 Ruleset adapter 建立类型化 profile 引用；Editor 处理缺项 | Ruleset、Validation、Loader、Runtime 读取 | 专用 profile 通过准入后 Compile；当前数值进 GameState | 可选；默认空集合；需要 Ruleset 算法时条件必填 | 引用存在、版本兼容、profile 类型与 entity categories 组合兼容 | Runtime 交给 Ruleset 解释；ModuleContent 不复制算法 |
| `initial_state` | Parser 从明确初始状态提出；Compiler 解析到已声明状态槽；Editor 确认；Loader 消费 | Validation、Loader、Ruleset 读取；Projection／Host 只看运行状态 | Compile 声明初值；建局复制到 GameState；之后静态值不变 | 可选；无默认；不能普遍假设空或健康状态 | 每个状态槽已声明且类型兼容；不可写任意路径；不得含当前时间／玩家知识 | 初始化实体状态；具体值对象需 Runtime state prototype |

### 当前字段迁移

| 当前 Entity 字段 | 目标职责 |
|---|---|
| `content` | 按受众迁移到 `player_description` 或 `keeper_context`；原子事实另建 InformationItem |
| `secrets` | 不长期作为字符串事实源；拆到 Keeper context 或 InformationItem |
| `state` | 只有类型化初值可迁到 `initial_state`；运行当前值进入 GameState |
| `refuse_ops`、`blocked_text` | 静态可用性迁到 Interaction／Condition；条件许可或拒绝迁到 Rule／`action_authorization` Effect。只有能归属到明确 Interaction Outcome 的拒绝话术才迁为 `OutcomeDefinition.player_feedback`；自动 Action Gate 的即时原因没有合法 Outcome owner，必须由兼容 adapter 保留并记录 ActionDecision／Notification Capability Gap |
| `direct_responses` | 迁到 Interaction + Resolution + Outcome，不留第二套对话执行入口 |
| 内嵌 `rules` | 迁到 RuleDefinition，并用显式 RuleScope 引用 Entity |

# LocationDefinition

对象结论：LocationDefinition 是可选空间能力对象。只有地点需要跨多个 ContentUnit 保持身份、层级或空间连接时才结构化；普通叙事中的地点词不必创建对象。它不继承 Entity 的状态模型，也不保存角色当前位置。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `location_id` | 独立地点定义的稳定身份 | Unit、Entity、Interaction 或空间关系需要引用同一地点时存在；不能用 ContentUnit ID 代替，因为同一地点可承载多个 Unit | Stable Identifier | 《追书人》《追沙》《柏林：失去昨日》多地点；**K / Candidate** |
| `name` | 地点规范名称 | 供 Host、Projection 和引用审阅；属于 Location 身份，不是 Unit 标题。不得存地址、完整描述或当前别名状态 | Display Text | 《追书人》《追沙》《柏林：失去昨日》的多地点内容；**K / Candidate** |
| `aliases` | 原文中指向同一地点的玩家安全稳定别名 | 帮助 Parser 引用解析、Projection 和 Host 搜索；秘密地点名／关系属于 InformationItem。不得把上位地点、房间组成或方向词当别名 | Collection of Player-safe Alias Text | 《追书人》的宅邸／住宅等非秘密称谓；**K / Candidate** |
| `player_description` | 可安全展示的地点静态描述 | 地点跨 Unit 的共同外观属于这里；某时刻发生的场景内容属于 ContentUnit。不得保存 Keeper 秘密或当前破坏状态 | Player-safe Narrative | 《银之锁》房间、《追沙》制革厂等；**K / Candidate** |
| `keeper_context` | 地点级幕后原理、主持说明和自然语言裁量 | 空间秘密若是原子可获得事实应归 InformationItem；可执行出口条件归 Relation／Rule。不得写当前在场实体 | Keeper Narrative | 《银之锁》法术原理、《追书人》地穴真相；**K / Candidate** |
| `parent_location_ref` | 该地点的直接空间包含上级候选引用 | 空间层级属于 Location；ContentGraph 的 chapter／contains 不是空间事实。单父树是否成立尚未确认，因此字段名与基数均不能冻结 | Candidate Location Reference | 《银之锁》的房间—走廊、《追沙》的制革厂区域提供层级证据；**H / OPEN**（cardinality） |
| `spatial_links` | 从该地点到其他地点的类型化静态空间连接 | 只有 Spatial consumer 存在时表达门、通道、邻接等；不能与 ContentRelation 混用。方向、所有权和 link 类型仍未冻结 | Collection of SpatialLink Value Objects | 《银之锁》抽屉／门／走廊、《追书人》宅邸／公墓／地穴；**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `location_id` | Compiler 对确认需要独立寻址的地点分配；Editor 解决同名地点 | Validation、Host、Projection、可选 spatial runtime 读取 | Capability Compile → Published；位置实例状态另存 | Location 一旦结构化始终必填；无默认 | 模块内唯一；引用闭合；不得与 Unit ID 共用身份空间 | 作为静态空间状态和 Event 的定义键 |
| `name` | Parser 从地点标题／地图标签直接提取；Editor 处理玩家安全名称 | Projection、Host、Review 读取 | Draft → Published | 始终必填于 Location；无默认 | 非空；不充当 ID；秘密地点名需投影政策 | Runtime 只透传 |
| `aliases` | Parser 提取明确、非秘密同义称谓；Normalization 去重；Editor 确认 | Parser resolver、Validation、Projection、Host search 读取 | Draft 可参与解析；Published 只保留玩家安全别名 | 可选；默认空集合 | 不与其他地点产生无法消解歧义；不得把 containment 或秘密地点关系当 alias | Runtime 核心忽略；解析、Projection 和 Host 有消费者 |
| `player_description` | Parser 从玩家可感知地点描述提取；Editor 去除泄密 | Projection、Host、Review 读取 | Draft → Published；当前环境变化另存 GameState | 可选；无默认 | 玩家安全；不得复制每个 Unit 的事件叙事 | Runtime 通过 Projection 展示 |
| `keeper_context` | Parser 从地点秘密／主持说明直接提取；Editor 将原子 Fact 拆出 | Host Context、Review 读取 | Draft → Published | 可选；无默认 | Keeper-only；不能用作未声明 Condition | Runtime 不执行 |
| `parent_location_ref` | Compiler 从明确“位于／内部”关系提出候选；Editor 确认跨层级歧义 | Validation、Host map view、可选 spatial runtime 读取 | 当前停留 Draft／OPEN；只有树形单父不变量获确认后才可 Published | 当前不可发布；若单父模型获准则可选且无默认，否则改用新的关系形态 | 候选引用存在；禁止 containment 环；单父假设必须由 consumer 原型确认 | 仅空间层级查询读取；当前字段形态未冻结 |
| `spatial_links` | Parser 提出门／通道候选；Compiler 在 SpatialLink catalog 获准后结构化 | Validation、Host map、可选 spatial runtime 读取 | 未获准时留叙事／Gap；Published 后静态；锁定／走过状态另存 | 可选；默认空集合；方向和 link ID 规则 OPEN | 目标存在；不能与 ContentRelation 双写同一执行事实；条件若可执行走 Condition／Rule | 当前无通用 Runtime consumer；需导航原型后冻结 |

### 明确不是字段

- 不设置坐标、几何、地图资产或文件路径；这些等待 Asset／地图消费者。
- 不设置 `visible`、`discovered`、`occupied_by`、当前门锁状态或实体反向列表。
- 不强制每个 ContentUnit 对应一个 Location，也不强制每个 Location 对应一个 Unit。

# InformationItem

对象结论：InformationItem 是“玩家可能知道什么”的静态语义本体。Fact、Clue／Evidence、Memory 和 Document Content 可以共享信息身份与披露边界；Secret、Player-facing、Keeper-only 是披露政策或当前知识状态问题，不应复制成另一种事实本体。只有需要引用、授予、可见性控制或一致性校验的信息才独立结构化。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `information_id` | 一项结构化信息的稳定身份 | 多来源 Acquisition、知识状态、信息关系和引用需要指向同一语义；不得用正文、页码或载体 ID 代替 | Stable Identifier | 信息 15/15，但当前没有独立 Information 对象；**R / Review-ready** |
| `statement` | 该信息作为权威命题或可知内容的规范表达 | 它是信息本体唯一权威；ModuleFrame／ContentUnit／Entity 只能摘要或引用。不得把来源、获得动作、当前知情人或完整文档载体塞入 | Semantic Statement | 《追书人》的地下通道、《复足》的录像内容、《追沙》的绑架真相、《RE计划》的文件内容；**R / Review-ready** |
| `label` | 供 Keeper、编辑和审阅识别信息的短名 | 名称不承担真值和玩家呈现；属于 InformationItem 而不是载体 Entity。不得以 label 替代 statement | Display Text | 《复足》的录像、《RE计划》的文件、《银之锁》的字条等有标题载体，但非每项信息都有；**R / Candidate** |
| `disclosure_policy` | 信息在静态定义层允许向哪些受众、在何种授权下披露的上界 | Secret／Keeper-only／player-facing 属于披露政策，不是独立本体类型；实际能看到什么仍由 Projection 结合 KnowledgeState 计算。不得保存“玩家 A 已知”或直接生成 ProjectionSnapshot | Disclosure Policy Value／Reference | Role-private-1（《RE计划》）证明角色独占信息；Keeper／玩家分区可由样本文本观察到，但未作统一频次统计，**H / OPEN** |
| `semantic_kind` | 当确定消费者需要时，对 Fact、Clue／Evidence、Memory 等语义用途作受限分类 | 分类可服务 Review、线索图或知识 UI，但不改变同一信息本体；Document 是载体或内容来源，不自动成为 kind。不得使用任意标签 | Information Kind Catalog Value | 《追书人》《银之锁》以调查线索为主，《RE计划》含角色私有信息，《复足》含录像／认知内容，Memory／Fact 边界多样；**H / OPEN** |
| `information_relations` | 信息之间经审阅确认的支持、指向或依赖关系 | 只在图谱／Review／Host 消费者成立时表达；关系属于信息语义，不等于获得路径。不得从文档相邻位置自动推断 | Collection of Typed InformationRelation | 线索网络／网状路线 2/15（《苍白面具之下》《追沙》）；**K / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `information_id` | Compiler 对获准原子化的信息分配；Editor 合并同义项、拆分复合项；Publish 冻结 | Validation、Knowledge Runtime、Projection、Host Context、Review 读取 | Draft 可为候选片段；Compile 产生 ID；KnowledgeState 另存本局状态 | InformationItem 一旦结构化始终必填；无默认 | 模块内唯一；引用闭合；同一权威事实不得多 ID 无理由复制 | KnowledgeState 与 Event 的静态定义键 |
| `statement` | Parser 从明确真相、线索内容、记忆或文档内容直接提取候选；Editor 确认语义粒度；Compiler 去重 | Validation、Review、受控 Host Context、授权后的 Projection 读取 | Draft 带原文来源；Published 静态；被获得／遗忘不修改 statement | 始终必填；无默认 | 非空；不得混入获得条件；与引用摘要不得矛盾；复合命题拆分政策由 Review 确认 | Runtime 不解释自然语言真值，只在 Acquisition 激活后让 Projection 按政策呈现 |
| `label` | Parser 从线索／文件／记忆标题提取；Editor 可补充便于主持识别的非事实名称 | Host、Review、可选 Projection 读取 | Draft → Published | 可选；无默认 | 非空；玩家可见时做泄密检查；不得成为引用键 | Runtime 核心忽略，供人类定位 |
| `disclosure_policy` | Parser 根据“守秘人信息／玩家信息／HO 专属”等显式受众提出；Compiler 映射已注册 policy；Editor 审核 | Validation、Projection、Knowledge Runtime、Review 读取 | Draft 可保留受众候选；policy catalog 未获准前不能发布为可执行 InformationItem；实际授权写 KnowledgeState／Event | 当前不可发布；Knowledge／Projection Profile 获准后应作为安全上界显式必填，但该 requiredness 仍需原型确认；无默认，绝不把缺失视为公开 | policy 已注册；与 Acquisition recipient 兼容；缺失阻断可执行信息发布 | Projection 的强制安全约束，不是最终可见结果 |
| `semantic_kind` | Parser 从“真相／事实”“线索／证据”“记忆”“日记／录像／文件内容”等明确语境提出候选；Normalization 对齐 catalog；Compiler 仅在消费者已承诺时输出 | Validation、Review、可选 clue／knowledge consumer 读取 | 未获准时停留 Draft；catalog 冻结后 Published | 可选；无默认 | 值已注册；一个 Item 是否多 kind 仍需消费者决定 | 核心 Runtime 忽略；不得据 kind 自动授予 |
| `information_relations` | Parser 提出显式“证明／指向”关系；Editor 审阅；Compiler 解析端点和 relation catalog | Validation、Review、Host clue view、可选 graph consumer 读取 | Capability Compile → Published；玩家是否发现关系另存 | 可选；默认空集合 | 端点存在；关系类型受支持；不得形成另一套 Acquisition 或 ContentRelation | 当前 Runtime 不执行；需要线索图原型 |

### 可见性边界

- `statement` 是规范语义，不承诺逐字作为玩家话术；即时措辞属于 Outcome `player_feedback`，长期可见文本的最小形态仍需 Projection／Host 原型。
- `disclosure_policy` 只声明静态上界。某角色当前是否知道、是否忘记、是否已经看过，属于 KnowledgeState／Event。
- 物理日记、录像、字条、文件是 Entity／Asset；其内容可指向 InformationItem，载体被毁不自动删除已获得知识。

# InformationAcquisition

对象结论：InformationAcquisition 是“通过哪条路径、从什么来源、向谁获得哪项信息”的静态关系。信息本体与获得方式必须分离；同一 Item 可以有多条 Acquisition。它不执行检定，也不保存本局是否已经触发。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `acquisition_id` | 一条可被 Effect、Event 或知识来源审计引用的获得路径身份 | 多来源、重复授予和 provenance 需要区别路径；不得用 Information ID 或 Interaction ID 代替 | Stable Identifier | 《追书人》《追沙》多来源路径，《RE计划》初始／任务授予；独立／嵌入形态未定，**R / Candidate** |
| `information_ref` | 该路径授予的唯一 InformationItem | 信息正文属于 Item；Acquisition 只建立关系。不得复制 `statement` 或直接保存可见字符串 | Information Reference | 信息与获得方式分离原则确定，但当前无独立 Acquisition，**R / Candidate** |
| `source_refs` | 对该获得路径具有来源／载体／提供者作用的类型化静态引用 | 同一信息可来自 Entity、Location、ContentUnit、Interaction、EntryPoint 或未来 Asset；来源属于 Acquisition，不属于 Information 本体。不得放自由文本来源或当前 actor | Collection of InformationSourceRef | Focus-5 均有 NPC、地点、物品、文件、交互或入口等来源；**R / Candidate** |
| `context_content_unit_ref` | 该路径被发现或呈现时的可选内容上下文 | 来源与发生上下文不同，例如 NPC 是来源、图书馆 Unit 是上下文；它不表示当前 Unit，也不替代 Effect 激活 | Optional ContentUnit Reference | Focus-5 均存在信息来源与发生场景不完全相同的调查路径；**H / Candidate** |
| `availability_condition` | 在 Host／Runtime 考虑该路径时必须满足的纯谓词 | 获得条件属于路径而非 Information；实际检定由 Interaction Resolution 完成，实际触发由 Effect 完成。不得把“调查充分”这类裁量硬编译 | Condition Value Object | 《银之锁》含持有物／位置条件，《复足》含观察与状态条件，《追沙》《RE计划》含任务前置；**H / OPEN** |
| `recipient_policy` | 路径激活时应向全队、单个行动者、指定角色模板等哪类接收者授予 | 受众属于获得事件，不是 Information 语义类别；静态 disclosure policy 仍提供上界。不得保存真实 player ID 或当前队伍成员 | Recipient Policy Value／Reference | 角色独占信息仅《RE计划》1/15；Focus-5 其余样本提供共同披露实例，但统一默认未证明，**H / OPEN** |
| `keeper_guidance` | 无法机器确定的获得方法、替代路径或裁量说明 | 保真承载自然语言路径；不应变成 Condition 或隐藏执行脚本。不得写信息正文 | Keeper Guidance | 《追书人》的替代调查、《追沙》的信息交流方式、《银之锁》的连续解法提供直接证据；**R / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `acquisition_id` | Compiler 根据“信息 + 来源路径 + 受众”分配；Editor 合并重复路径；Publish 冻结 | Validation、Effect executor、Knowledge Runtime、Review 读取 | Compile 产生；实际触发生成 Event，可多次引用同一定义 | 被 Effect 引用或需审计时始终必填；简单嵌入路径的物理形态 OPEN | 模块内唯一；不得因排序改变；引用闭合 | 作为授予 Event 的定义／provenance 键 |
| `information_ref` | Compiler 将 Parser 候选内容对齐到已确认 InformationItem | Validation、Knowledge Runtime、Projection、Review 读取 | Compile → Published；本局知识另存 | 始终必填；无默认 | 恰好一个有效 Item 引用；不能指向叙事段代替 Item | Effect 激活后确定要授予哪项知识 |
| `source_refs` | Parser 从“谁说／何处发现／何物承载／由何交互或入口获得”提出；Compiler 解析类型化引用；Editor 消歧 | Validation、Host Context、Knowledge provenance、Review 读取 | source catalog 获准后 Compile → Published；实际来源实例另存 Event | 可选；默认空集合明确表示“没有声明独立静态来源，激活 provenance 仅来自父 Effect／Event”，不表示来源能力 Supported | 每项引用存在且 source kind 匹配；禁止自由字符串、重复上下文或互相矛盾来源 | Runtime 可记录声明的来源 provenance；不负责启动 Acquisition |
| `context_content_unit_ref` | Compiler 从发生段落解析；Editor 确认跨 Unit 共用路径 | Validation、Host、可选 Runtime action discovery 读取 | Compile → Published；当前上下文另存 | 可选；无默认 | 引用存在；不得与 ContentUnit 反向关系形成双权威 | 可用于筛选候选路径，但不是激活信号 |
| `availability_condition` | Parser 提出明确硬条件；Compiler 仅发布可执行谓词；其余进入 keeper_guidance／Gap | Validation、Condition evaluator、Knowledge Runtime、Review 读取 | Draft 可为自然语言；Compile 后静态；求值不写回 | 可选；缺失表示无额外硬条件 | 纯谓词；不含 Check 算法；不产生 Effect | Acquisition 被请求激活时作为守卫 |
| `recipient_policy` | Parser 从全体／行动者／HO 专属措辞提出；Editor 审核；Compiler 映射 policy catalog | Validation、Knowledge Runtime、Projection、Review 读取 | Draft 保留受众候选；policy catalog 未获准前不发布可执行 Acquisition；真实 recipient ID 写 Event／KnowledgeState | 当前不可发布；Knowledge Runtime Profile 获准后应显式必填，但 recipient policy 形态与 requiredness 仍需原型确认；无默认 | 不超过 Item disclosure policy；policy 在 Runtime profile 中受支持；缺失阻断可执行授予 | 决定创建哪些 KnowledgeState 变化 |
| `keeper_guidance` | Parser 从替代调查方法、主持裁量和失败补救段直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；本次裁量结果不回写 | 可选；无默认 | Keeper-only；不得由 Runtime 当成可执行条件 | Runtime 不读；Host 只能据此选择已声明 Interaction／result key，再由 Outcome／Rule Effect 激活 Acquisition |

### InformationSourceRef

该值对象没有独立生命周期或 ID，随父 Acquisition 发布。它只表达静态来源关系，不承担执行激活。

| 字段 | 完整字段卡片 |
|---|---|
| `source_kind` | **语义／理由**：声明引用目标的受支持类别，使同名 ID 不产生歧义；属于来源引用而非 Information 分类。**Producer／来源**：Normalization 根据已解析对象类别生成，Editor 消歧。**Consumer**：Validation、Host Context、Knowledge provenance。**生命周期**：Compile → Published。**概念类型**：Closed Source-kind Catalog Value。**必填／默认**：始终必填；无默认。**Validation**：值已注册并与 `source_ref` 目标类型一致。**Runtime 意义**：选择安全解引用器。**反例**：任意“other”、当前玩家角色。**样本证据**：Focus-5 分别出现 NPC、字条／文件、录像、地点、任务结果和初始 HO 等来源。**成熟度**：**H / OPEN**（catalog）。 |
| `source_ref` | **语义／理由**：指向具体静态来源定义；属于 Acquisition，不复制来源正文。**Producer／来源**：Compiler 引用解析生成。**Consumer**：Validation、Host Context、Knowledge provenance。**生命周期**：Compile → Published；实际来源实例可在 Event 中另记。**概念类型**：Typed Reference。**必填／默认**：始终必填；无默认。**Validation**：目标存在且类别匹配。**Runtime 意义**：记录和展示获得来源，不自动执行。**反例**：页码、自然语言“调查获得”。**样本证据**：Focus-5。**成熟度**：**R / Candidate**。 |
| `source_role` | **语义／理由**：当一条路径有多个来源时区分载体、提供者或入口等因果作用；发生 ContentUnit 上下文只由 `context_content_unit_ref` 表达，不在这里重复。**Producer／来源**：Parser 从“由谁提供／由何物承载／由哪个入口初始化”等明确关系提出，Editor 确认，Compiler 映射 catalog。**Consumer**：Validation、Host、Review。**生命周期**：仅多来源消费者成立时发布。**概念类型**：Source-role Catalog Value。**必填／默认**：可选；无默认。**Validation**：值与 source kind 兼容；禁止使用 context 角色复制 ContentUnit 上下文。**Runtime 意义**：核心 Runtime 可忽略；有助于 provenance／Host。**反例**：任意 metadata 标签。**样本证据**：《复足》的录像路径同时涉及摄像机载体和观看交互；**H / OPEN**。 |

### 唯一激活路径

```text
OutcomeDefinition / RuleDefinition
  → ordered Effects
  → Effect(information_acquisition_ref)
  → InformationAcquisition.information_ref
  → InformationItem
```

`source_refs`、`context_content_unit_ref` 和 `availability_condition` 都不是第二条自动激活边。不得重新增加 `facts`、`player_visible_information`、`information_refs_to_grant` 或 Outcome 直连 InformationItem 的旁路。

# InteractionDefinition

对象结论：InteractionDefinition 是模组预先声明的一种可尝试动作或直接交互机会。它连接语义动作、静态目标、可用性、可选 Resolution 和可能 Outcome；不是某次 ActionRequest，也不等同于 Check，更不承担全局剧情编排。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `interaction_id` | 一种可尝试交互定义的稳定身份 | Host 候选、Runtime Attempt、Rule Trigger 和 Event 需要引用；不得用 action 文本或 Checkpoint 数组位置代替 | Stable Identifier | 当前 `Checkpoint.id`；行动触发 15/15，**C / Review-ready**（有当前等价语义） |
| `action_concept` | 玩家意图的规范语义，如 search、ask、open、follow | Host／Intent Router 需要匹配语义动作；属于 Interaction，不是玩家话术。不得使用完整句子、任意未注册动词或 Resolution mode | Action Concept Reference／Catalog Value | 当前 `Checkpoint.action` 只是 Host semantic hint、不是 allow-list；受控 catalog 尚未建立，Focus-5 只证明动作多样，**C / Candidate** |
| `player_prompt` | 可安全呈现的动作机会或操作提示 | 玩家话术与机器动作概念分离；属于交互呈现，不是 Outcome feedback。不得泄露目标秘密或承诺结果 | Player-safe Prompt | 当前 action 同时混有提示职责；**R / Candidate** |
| `target_refs` | 该 Interaction 静态允许或指向的类型化目标引用 | 目标可为 Entity、Location、ContentUnit 或无显式目标；属于 Interaction 而非 Resolution。不得保存本次实际选中对象 | Collection of InteractionTargetRef | 当前 `target_id` 强制单 Entity；样本要求更广，数量 OPEN，**H / OPEN** |
| `availability_condition` | 该交互何时可被提出／尝试的纯谓词 | 可用性属于交互机会；判定成功条件属于 Resolution，解锁后果属于 Effect。不得写开放式 Keeper 判断 | Condition Value Object | 《银之锁》的物品／门条件、《追书人》的位置路径、《RE计划》的任务前置提供实例；报告未统计字段覆盖，**R / Candidate** |
| `resolution` | 该交互在结构化执行时如何得到确定结果 | Check 只是一个 variant；属于 Interaction 的解析策略，不属于 Outcome。开放／纯主持交互可不结构化此字段 | ResolutionDefinition Value Object／Reference | 当前 Checkpoint 仅 Check；样本含直接、选择、检定、对抗、自动和裁量，variant 与物理形态未定，**H / OPEN** |
| `outcome_definitions` | 该结构化交互可能成立的结果定义集合 | Outcome 属于交互结果，不属于 Resolution 算法；开放主持交互可只保留 guidance。不得固定 success／failure 二元，也不得保存本次结果 | Owned Collection of OutcomeDefinition | 当前 `Checkpoint.outcomes`；行动后果 15/15，**C / Review-ready**（有当前等价语义） |
| `keeper_guidance` | 该交互的开放方法、裁定边界和非执行主持建议 | 不能机器化的语义仍需保真；属于 Interaction 而非 Rule。不得以自然语言暗中修改状态 | Keeper Guidance | Focus-5 均含替代行动和主持裁量；**R / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `interaction_id` | Compiler 对已确认可寻址动作分配；Editor 合并同义交互；Publish 冻结 | Validation、Intent Router、Runtime、Projection、Host、Review 读取 | Compile 产生；每次尝试另建 InteractionAttempt／Event | Interaction 一旦结构化始终必填；无默认 | 模块内唯一；引用闭合；不得与某次 Action ID 混用 | Runtime Attempt 的定义键 |
| `action_concept` | Parser 从动作措辞提出；Normalization 对齐受控 Action catalog；Compiler 只输出受支持概念 | Intent Router、Validation、Runtime Action Gate、Host 读取 | Draft 可为自然语言；catalog 支持后 Published | 始终必填于结构化 Interaction；无默认 | Action 已注册；不得仅凭词面误归一；Ruleset 兼容 | 路由玩家意图和动作许可检查，不决定成功 |
| `player_prompt` | Parser 从可见操作提示／选项提取；Editor 做泄密审查 | Projection、Host、Review 读取；Runtime 透传 | Draft → Published；玩家实际输入另存 | 可选；无默认，不从 action_concept 机械翻译 | 玩家安全；不包含隐藏 Condition 或保证 Outcome | Runtime 算法不解释；Host／Projection 原型需验证最小形态 |
| `target_refs` | Parser 提出明确目标；Compiler 解析类型化引用；Editor 处理多目标／无目标歧义 | Validation、Target Resolver、Projection、Host、Runtime 读取 | Compile → Published；本次选择写 ActionRequest／Attempt | 可选；缺失表示没有显式静态目标；基数保持 OPEN；无默认 | 每条引用合法；一个 Interaction 允许多少 target 尚不冻结；不得指向 Runtime instance | 约束／提示候选目标，实际目标由 Target Resolver 解析 |
| `availability_condition` | Parser 从明确硬条件提出；Compiler 仅结构化注册谓词；其余进入 guidance／Gap | Validation、Runtime、Projection／Host availability view 读取 | Draft → Compile；求值结果不写定义 | 可选；缺失表示无额外机器守卫 | 纯谓词；只读已注册上下文；不能调用 Effect | Runtime 在接受 ActionRequest 前求值 |
| `resolution` | Parser 从检定／直接／对抗／自动／裁量措辞提出；Compiler 绑定 Ruleset／resolver catalog；Editor 确认 | Runtime Resolver、Ruleset、Validation、Host 读取 | 可执行 Profile Compile → Published；CheckResult／Decision 另存 | 结构化封闭执行时条件必填；开放主持交互可缺失 | mode 支持；result binding 完整；不得带测试结果 | 选择解析器并输出受控 result key |
| `outcome_definitions` | Parser 从结果段提出；Compiler 按稳定结果键归一；Editor 审查后果边界 | Runtime、Validation、Projection、Host、Review 读取 | Compile → Published；本次选中项写 Event／Attempt | 封闭 Resolution 条件必填且至少一项；开放交互可为空 | ID／key 唯一；Resolution 可产生的结果都有绑定；Effect 有序 | Runtime 选择定义并执行其有序 Effects |
| `keeper_guidance` | Parser 从“其他合理方式／KP 可裁量”等段直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；Host 决策另存受控 Decision／Event | 可选；无默认 | Keeper-only；不得被 Runtime 当自然语言程序 | Runtime 不执行；Host 原型可将裁量映射为受控 outcome key |

### InteractionTargetRef

该值对象没有独立 ID，随父 Interaction 发布。它只声明静态目标，不冻结一个 Interaction 可以有几个目标。

| 字段 | 完整字段卡片 |
|---|---|
| `target_kind` | **语义／理由**：区分 Entity、Location、ContentUnit 等受支持目标类别；属于目标引用而非 `entity_categories`。**Producer／来源**：Normalization 基于解析结果生成；Compiler 输出。**Consumer**：Validation、Target Resolver、Projection。**生命周期**：Compile → Published。**概念类型**：Closed Target-kind Catalog Value。**必填／默认**：每条 TargetRef 必填；无默认。**Validation**：值已注册且与 target_ref 类型一致。**Runtime 意义**：选择安全解析器。**反例**：任意 `other`、当前实例类型猜测。**样本证据**：《追书人》NPC／地点、《银之锁》物品／环境、《追沙》地点／组织；**H / OPEN**（catalog）。 |
| `target_ref` | **语义／理由**：指向具体静态目标定义；避免为每种目标在 Interaction 增加一个字段。**Producer／来源**：Compiler 引用解析生成。**Consumer**：Validation、Target Resolver、Runtime、Host。**生命周期**：Compile → Published；实际目标实例另存。**概念类型**：Typed Reference。**必填／默认**：每条 TargetRef 必填；无默认。**Validation**：引用存在且类别匹配。**Runtime 意义**：限定候选定义。**反例**：玩家 ID、当前 actor instance、自然语言“附近的人”。**样本证据**：Focus-5；**R / Candidate**。 |
| `target_role` | **语义／理由**：多目标交互中区分 recipient、instrument、subject 等语义位置；属于 TargetRef，不属于 Entity。**Producer／来源**：Parser 提出、Editor 消歧、Compiler 映射 catalog。**Consumer**：Intent Router、Validation、Host。**生命周期**：只有多目标原型成立后发布。**概念类型**：Target-role Catalog Value。**必填／默认**：当前不可发布；role catalog 获准后，仅当同一 Interaction 的多个目标无法仅凭 target kind 无歧义绑定时条件必填；否则可选；无默认。**Validation**：role 与 action concept、target kind 兼容。**Runtime 意义**：多目标参数绑定。**反例**：战斗阵营、Entity 身份。**样本证据**：《银之锁》的持物开门／连续解谜和《追沙》的交换／协作关系暗示 instrument、subject、recipient 分工；**H / OPEN**。 |

# ResolutionDefinition

对象结论：ResolutionDefinition 声明 Interaction 如何得到受控结果。Direct、Ruleset Check、Opposed Check、Automatic 和 Keeper Adjudication 是候选 variant；完整集合尚未冻结。它不保存骰点结果，不复制 Ruleset 算法。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `mode` | 该解析策略的受限类别 | Runtime 必须知道由直接映射、Ruleset、对抗、自动事件还是主持裁量得到结果；属于 Resolution，不是 action 或 outcome。不得用任意字符串声称支持 | Resolution Mode Catalog Value | Focus-5 包含直接、检定、选择和主持裁量，当前 Checkpoint 只覆盖 check；catalog 未定，**H / OPEN** |
| `resolver_ref` | 机器解析 variant 所使用的已注册 Resolver／Ruleset 能力 | 算法属于 Runtime／Ruleset，ModuleContent 只绑定；Direct 或主持裁量不一定需要。不得存函数名、脚本或 Provider 私有参数包 | Resolver Reference | 当前 Runtime 直接用测试过渡字段 `mvp_check_result` 选分支，没有 Ruleset Resolver 消费链；`skills`／`difficulty` 只能作为迁移输入，**H / OPEN** |
| `result_bindings` | 将 Resolver／主持裁量产生的受控 result key 映射到 OutcomeDefinition | 成功等级来自 Resolver，不应固定 success／failure；映射属于 Resolution 与 Outcome 的连接。不得保存某次实际结果 | Collection of ResolutionResultBinding | 当前二元 outcomes 是迁移起点；通用映射无现行 consumer，**R / Candidate** |
| `skill_option_refs` | Ruleset Check variant 允许选择的技能／能力引用 | 只属于 Check specialization，不是所有 Resolution 共同字段；不得放自然语言技能名或复制技能定义 | Collection of Ruleset Skill References | 当前 `Checkpoint.skills` 是迁移事实；报告的《RE计划》《苍白面具之下》《更好的明天》《幸福蛙蛙村》《蝶骨巢穴》《银之锁》6 份只统计准备建议，不能当本字段覆盖率，**H / OPEN**（subtype） |
| `difficulty_ref` | Ruleset Check variant 的难度／目标等级引用 | 难度由 Ruleset 定义；不应成为基础 Resolution 通用字段。不得放未经 Ruleset 验证的自由文本或成功结果 | Ruleset Difficulty Reference | 当前 `Checkpoint.difficulty`；**H / OPEN**（subtype） |
| `adjudication_guidance` | Keeper Adjudication 或开放解析的受控裁量说明 | 保留不可机器化方法，并指导 Host 返回已声明 result key；属于 Resolution 而不是 general Interaction guidance。不得直接产生未声明 Effect | Keeper Adjudication Guidance | Focus-5 均出现“其他合理方法”、说辞判断或替代调查等主持裁量；**R / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `mode` | Parser 从检定／直接结果／对抗／自动／主持决定措辞提出；Normalization 映射 catalog；Editor 确认 | Validation、Runtime Resolver、Ruleset、Host 读取 | Draft 候选 → 支持后 Published；本次解析另存 | Resolution 一旦结构化始终必填；无默认 | mode 在目标 Runtime profile Supported；所需字段组合合法 | 选择解析路径 |
| `resolver_ref` | Compiler 依据 mode 和 Module ruleset_ref 解析；Ruleset owner 提供 catalog | Validation、Runtime Resolver、Ruleset 读取 | Compile → Published；resolver 版本随 content compatibility 固定 | 机器解析 variant 条件必填；Direct／Keeper variant 可禁止 | 引用存在、版本兼容、返回 result keys 可校验 | 调用权威解析算法 |
| `result_bindings` | Parser 提出结果分支；Compiler 对齐 Resolver result catalog 与 Outcome IDs；Editor 处理遗漏／合并 | Validation、Runtime、Ruleset、Review 读取 | Compile → Published；选中结果写 Attempt／Event | 封闭 Resolution 始终必填且覆盖所有允许结果；无默认 success/failure | result key 唯一；Outcome 引用存在；覆盖政策明确；不能按数组位置匹配 | 将解析结果确定映射到 Outcome |
| `skill_option_refs` | Parser 从明确检定技能提取；Compiler 经 Ruleset adapter 解析 | Ruleset、Validation、Runtime CheckResolver、Host 读取 | 仅 Check subtype Compile；Published 静态 | Check subtype 条件必填或由 Ruleset 明确允许空；无通用默认 | 引用存在；技能适用于 ruleset；“任选合理技能”不能虚构封闭集合 | 限定 CheckResolver 候选技能 |
| `difficulty_ref` | Parser 从明确难度提取；Compiler 映射 Ruleset catalog；Editor 解决缺失 | Ruleset、Validation、Runtime CheckResolver 读取 | Check subtype Compile → Published | 条件必填：所选 CheckResolver 协议要求难度时必须存在，否则禁止；无默认，不默认普通难度 | 难度存在且与 resolver 兼容 | Ruleset 求值输入 |
| `adjudication_guidance` | Parser 从裁量说明直接提取；Editor 确保可映射到受控 result keys | Host Agent、Review、Validation 读取 | Draft → Published；本次 Decision 另存 | Keeper mode 条件必填；其他 mode 可选或禁止 | 不得含任意操作；必须列明 Host 可返回的已声明结果范围 | Runtime 不解释文本；Host 返回 result key 后继续确定执行 |

### ResolutionResultBinding

| 字段 | 完整字段卡片 |
|---|---|
| `result_key` | **语义／理由**：Resolver 或 Host 返回的受控结果类别；属于 Resolution 协议，不属于 Outcome 内容。**Producer／来源**：Ruleset／Resolver catalog 声明，Compiler 绑定。**Consumer**：Validation、Runtime Resolver、Ruleset adapter。**生命周期**：Compile → Published。**概念类型**：Catalog Result Reference。**必填／默认**：每条 binding 必填；无默认。**Validation**：key 属于 resolver 输出集合且在本 Resolution 内唯一。**Runtime 意义**：查找目标 Outcome；Ruleset adapter 只核对其声明的 result catalog，不拥有 Outcome。**反例**：骰点数值、自由文本“差不多成功”。**样本证据**：当前 success／failure 是迁移事实；Focus-5 的检定、选择、自动和裁量结果证明不能固定二元全集；**R / Candidate**。 |
| `outcome_ref` | **语义／理由**：指向该结果选择的 OutcomeDefinition；Outcome 内容不复制到 binding。**Producer／来源**：Compiler 引用解析。**Consumer**：Validation、Runtime。**生命周期**：Compile → Published。**概念类型**：Outcome Reference。**必填／默认**：每条 binding 必填；无默认。**Validation**：引用属于当前 Interaction 的允许 Outcome 范围。**Runtime 意义**：确定性选择结果。**反例**：Effect 列表、玩家反馈字符串。**样本证据**：Focus-5 的结构化结果分支；**R / Review-ready**。 |

`mvp_check_result` 永远不进入 ResolutionDefinition。它属于 Test Fixture 或注入式 Resolver。

# OutcomeDefinition

对象结论：OutcomeDefinition 是 Interaction、Encounter 结束或 Ending 成立后的静态结果定义。若“内容事件”只是自动反应，应直接使用 Rule → Effect；只有被建模为 Interaction／Encounter／Ending 并具有明确所有者时才使用 Outcome。普通结果、分支结果和终局结果共享“反馈／指导／有序 Effect”语义，但普通 Outcome 不因此获得 `terminal` 标记；终局由 EndingDefinition 负责。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `outcome_id` | 在拥有者范围内稳定的结果分支身份 | Resolution binding、Attempt、Encounter end 或 Ending 需要引用结果；不得用数组位置或玩家文本代替。跨拥有者引用时的限定方式仍待物理布局决定 | Scoped Stable Identifier | 当前 success／failure 键是最小迁移事实，但没有独立 Outcome ID；限定与所有权未定，**R / Candidate** |
| `label` | 供 Keeper、Review 或结果 UI 识别分支的短名 | 结果身份与呈现分离；它不是 Ending 分类或玩家反馈。不得把 success/failure 作为唯一固定全集 | Display Text | 样本有成功、失败、逃离、跟随等多类分支；**R / Candidate** |
| `ordered_effects` | 结果成立后按声明顺序请求执行的有限 Effect | 状态、信息授予、内容激活和终局激活必须走唯一 Effect 路径；属于 Outcome 而不是 Resolution。不得并存 `facts`／直接信息／直接解锁字段 | Ordered Collection of Effect | 当前 `ops` 及多套旁路的目标归并；行动后果 15/15，**C / Review-ready** |
| `player_feedback` | 该结果成立后可立即向授权玩家返回的安全反馈 | 即时结果话术属于 Outcome；持久可知事实必须走 Acquisition，长篇尾声属于 Ending terminal outcome 的叙事。不得用它绕过知识状态 | Player-safe Immediate Feedback | 当前 `player_visible_information` 中仅即时部分可迁移；**R / Candidate** |
| `narration_guidance` | Host 对该结果如何叙述、避免何种断言的非执行约束 | 结果局部叙事政策属于 Outcome，不属于 Effect 或 ModuleFrame。不得改变状态、偷偷选择其他 Outcome 或包含任意脚本 | Keeper Narration Guidance | 当前 `narration_constraints`；Focus-5 有差异化叙述，**C / Review-ready**（有当前等价语义） |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `outcome_id` | Compiler 根据显式结果分支生成稳定键；Editor 合并同义结果；Publish 冻结 | Validation、Runtime、Event writer、Review 读取 | Compile 产生；本次选中结果写 Attempt／Event | 被 binding／规则引用或有多分支时始终必填；无默认 | 在拥有者范围唯一；引用闭合；排序变化不改变 | Runtime／Event 的结果定义键 |
| `label` | Parser 从结果标题或明确分支名提取；Editor 可补充非执行显示名 | Host、Review、可选 Projection 读取 | Draft → Published | 可选；无默认 | 非空；不得作为 resolver result key；玩家可见时安全 | Runtime 算法忽略 |
| `ordered_effects` | Parser 从明确后果提出；Normalization 映射 Operation catalog；Editor 确认执行顺序；Compiler 输出 | Validation、Runtime Effect executor、Ruleset、Review 读取 | Compile → Published；执行产生 StateChange／Event | 可选；默认空序列 | 每个 Effect variant 合法；顺序确定；事务和失败政策由 Runtime profile 声明；显式绑定的 no-op Outcome 可以没有 Effect／反馈／指导，但必须由 Review 确认且仍记录选中结果 | 结果的唯一机器后果；空序列明确表示不请求状态变化 |
| `player_feedback` | Parser 从结果描述中提取即时、安全部分；Editor 区分持久信息与即时话术 | Projection、Host、Review 读取；Runtime 透传 | Draft 安全审查 → Published；展示 Event 另存 | 可选；无默认 | 玩家安全；不得陈述尚未通过 Acquisition 获得的持久 Fact | Runtime 在 Effect 事务结果明确后交给 Projection |
| `narration_guidance` | Parser 从结果叙事约束直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；实际叙述不回写 | 可选；无默认 | Keeper-only；不得被 Effect executor 解释；不得与 player_feedback 冲突 | Runtime 不执行；Host 使用已选择 Outcome 构造回应 |

### 当前字段迁移

| 当前 CheckpointOutcome 字段 | 目标职责 |
|---|---|
| `facts` | 逐项判别：执行确认／状态事实进入 Event 或状态投影；持久可知内容才迁为 InformationItem + Acquisition + Effect；即时反馈进入 `player_feedback` |
| `player_visible_information` | 持久知识走 Acquisition；只有即时安全反馈进入 `player_feedback` |
| `narration_constraints` | 迁到 `narration_guidance` |
| `ops` | 迁到 `ordered_effects`，且操作目录只能有一个权威版本 |

### 明确不是字段

- 不设置 `condition` 或 `trigger`；Interaction Resolution／Rule／Ending 决定何时选择 Outcome。
- 不设置 `is_terminal`、`win` 或 `failure`; 正式终局由 EndingDefinition 激活。
- 不设置直接 `information_refs`、`content_unit_refs_to_unlock` 或事实字符串。

# RuleDefinition

对象结论：RuleDefinition 是“在已注册时机、已声明作用域和可选纯谓词成立时，按顺序请求有限 Effects”的静态规则。它不是简单的 Condition + Effect，也不产生 Outcome。存储上嵌套在 Entity 或 Unit 下不能替代显式 Scope。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `rule_id` | 一条可执行规则定义的稳定身份 | Dispatcher、Event、冲突诊断和 Review 需要引用；不得用 hook、数组位置或自然语言标题代替 | Stable Identifier | 当前 `Rule.id`；状态／时间／行动反应在样本中存在，**C / Current** |
| `label` | 供 Keeper、编辑和诊断识别规则的短名 | 名称不承担 Hook 或条件语义；属于 Rule 而不是 Effect。不得影响执行排序 | Display Text | 当前无对应字段；复杂规则可读性需要，**R / Candidate** |
| `trigger` | 何时考虑这条规则的已注册事件声明 | Trigger 与 Condition 分责；属于 Rule 调度，不属于 Effect。不得用当前状态值或自然语言“合适时”充当 Trigger | Trigger Value Object | 当前 `hook` 是迁移起点；时间／轮次／行动触发广泛，**C / Candidate** |
| `condition` | Trigger 到达后是否允许执行的可选纯谓词 | 条件属于 Rule 守卫；不决定调度时机，也不修改状态。不得包含自然语言裁量或 Operation | Condition Value Object | 当前 `when path/equals`；样本有阈值、持有、位置与组合条件，**C / Candidate** |
| `scope_refs` | 声明规则绑定的 Module、ContentUnit、Entity、Location、Interaction 或 Encounter 语义范围 | Scope 用于索引、隔离和冲突，不应从物理嵌套猜出；它不是 Trigger source 或 Condition subject。一个还是多个 Scope、组合语义均为 OPEN | Logical Slot of RuleScope Values | 当前 Entity 内嵌 rules 隐含 scope；目标需显式化，**H / OPEN** |
| `ordered_effects` | 条件成立后按顺序请求的有限 Effects | Rule 直接拥有 Effect，不应先生成 Outcome；也不得保留 `facts`／玩家字符串旁路 | Ordered Collection of Effect | 当前 `then` 及旁路字段的目标归并；**C / Review-ready** |
| `priority` | 同一调度批次内规则的显式排序值 | 当前 Runtime 只在 Entity allow-rule 选择中排序；目标通用 Dispatcher 的批次语义仍需原型。它属于 Rule 调度而不是 Effect 顺序，不得把文档顺序当优先级 | Priority Value | 当前 `Rule.priority=0` 是有限迁移事实；通用语义未实现，**C / Candidate** |
| `conflict_policy` | 多条 Rule 对同一资源产生冲突时采用的受限政策 | priority 只能排序，不能说明拒绝、合并或覆盖；属于 Rule／Dispatcher 协议。不得使用任意脚本或隐式 last-write-wins | Conflict Policy Reference／Value | 当前未定义冲突语义；复杂轨道／结局可能冲突，**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `rule_id` | Compiler 对获准执行的规则分配；Editor 合并重复反应；Publish 冻结 | Validation、Rule Dispatcher、Event writer、Review 读取 | Compile 产生；每次触发另写 Event | Rule 一旦结构化始终必填；无默认 | 模块内唯一；不得因嵌套位置或排序变化改变 | 执行、审计和幂等诊断键 |
| `label` | Parser 从规则标题提取；Editor 可补充非执行名称 | Host、Review、Validation diagnostics 读取 | Draft → Published | 可选；无默认 | 非空；不得参与匹配／排序 | Runtime 算法忽略 |
| `trigger` | Parser 从“进入／完成／每轮／到期”等措辞提出；Normalization 映射 Hook catalog；Compiler 输出支持值 | Rule Dispatcher、Validation、Runtime indexer 读取 | Draft 候选 → Compile → Published；实际 Event 另存 | 始终必填；无默认 | Hook 在目标 Runtime profile Supported；source 类型兼容 | 建立监听与调度 |
| `condition` | Parser 从明确硬条件提出；Compiler 仅映射已注册 predicate；Editor 确认 | Condition evaluator、Validation、Review 读取 | Draft 可为自然语言；可执行部分 Compile；求值结果不写回 | 可选；缺失表示 Trigger 到达即成立 | 纯谓词；只读可信 EvalContext；无副作用 | Trigger 到达时求值 |
| `scope_refs` | Compiler 从原文宿主、当前嵌套和编辑决议提出显式 Scope；Editor 确认 | Validation、Rule indexer、Dispatcher、Review 读取 | 迁移时生成候选；Published 前需冻结目标 Profile 规则 | 当前不可发布；Scope 协议获准后，可执行 Rule 始终必填且至少一条；数量与组合无默认、保持 OPEN | 目标存在；scope kind 支持；不能依赖物理嵌套；多 Scope 冲突语义未定 | 限定索引和 EvalContext，具体基数需 Runtime prototype |
| `ordered_effects` | Parser 从明确后果提出；Normalization 对齐 Operation catalog；Editor 确认顺序；Compiler 输出 | Validation、Effect executor、Ruleset、Review 读取 | Compile → Published；执行结果写事务／Event | 可执行 Rule 至少一项；无默认空执行 Rule | 每项 variant 合法；顺序确定；不能与信息／事实旁路共存 | Rule 的唯一执行后果 |
| `priority` | Parser 只在原文明确时提取；当前兼容迁移可沿用 `0`；否则 Editor／Runtime owner 明确指定 | 当前 Entity allow-rule selector、未来 Rule Dispatcher、Validation 读取 | Compile → Published | 当前 Contract 可省略并默认 `0`；目标通用 Dispatcher 是继续显式默认、改为必填还是采用其他排序政策尚未冻结，迁移不得静默改变同优先级行为 | 有限整数／受限 priority；相同值时冲突仍可确定或拒绝 | 当前仅决定 allow-rule 候选顺序；通用批次排序需原型 |
| `conflict_policy` | Runtime owner 定义 policy catalog；Editor 仅在模组确需覆盖时选择；Compiler 绑定 | Validation、Rule Dispatcher、Effect transaction engine 读取 | 只有冲突原型支持后 Published | 当前不可发布；policy catalog 获准后，仅当同一调度批次可能产生 priority 无法消解的资源冲突时条件必填；否则可选；无默认，不得暗用 last-write-wins | policy 已实现；与 Effect 类型／事务模型兼容 | 解决同批 Effect 冲突；需 Runtime 原型 |

### RuleScope

RuleScope 是类型化引用值，不保存状态，也不因为 Rule 曾嵌套在某对象下就自动生成确定语义。

| 字段 | 完整字段卡片 |
|---|---|
| `scope_kind` | **语义／理由**：声明 Module、ContentUnit、Entity、Location、Interaction 或 Encounter 等作用域类别；属于 Scope 而不是 Trigger source。**Producer／来源**：Compiler 从原文宿主与编辑决议归一。**Consumer**：Validation、Rule indexer、Dispatcher。**生命周期**：Compile → Published。**概念类型**：Closed Scope-kind Catalog Value。**必填／默认**：每条 RuleScope 必填；无默认。**Validation**：值已注册且目标 Runtime 支持。**Runtime 意义**：选择索引空间。**反例**：Entity type、玩家 ID、任意字符串。**样本证据**：《追书人》的实体反应、《复足》的感染／时间规则、《追沙》的全局沙漏证明 scope 不止一种；**H / OPEN**（catalog）。 |
| `target_ref` | **语义／理由**：指向具体静态作用域目标；Module 全局 scope 是否需要显式 target 由 catalog 决定。**Producer／来源**：Compiler 引用解析，Editor 确认。**Consumer**：Validation、Rule indexer、Runtime。**生命周期**：Compile → Published。**概念类型**：Conditional Typed Reference。**必填／默认**：由 scope_kind 决定；无默认。**Validation**：目标存在且类型匹配。**Runtime 意义**：绑定规则索引和 EvalContext。**反例**：当前 actor instance、Condition subject。**样本证据**：Focus-5；**H / OPEN**。 |

### 当前 Rule 迁移

| 当前字段 | 目标职责 |
|---|---|
| `hook` | `trigger.hook_ref` |
| `when.path/equals` | 仅作为 Condition 叶子迁移起点；任意 path 必须改成类型化 subject |
| `then` | `ordered_effects` |
| `facts` | 语义逐项审阅：执行确认／状态断言进入 Event 或状态投影；持久可知内容才走 InformationAcquisition；不得一概当信息授予 |
| `player_visible_information` | 持久知识走 InformationAcquisition；若能归属到明确 Interaction Outcome，可迁为其 `player_feedback`。自动 Rule 的即时话术没有 Outcome owner，本轮不新增 Rule／Effect 文本字段，须由兼容 adapter 保留并记录 ActionDecision／Notification Capability Gap |
| Entity 内嵌位置 | 只产生待审阅 RuleScope 候选，不是最终 scope 权威 |

# Trigger

对象结论：Trigger 回答“何时考虑 Rule 或自动 Ending”，只描述已注册 Event／Hook 及可选来源。周期、日历、倒计时和阶段参数由 Timeline／Track 等专用对象定义，Trigger 不设置通用参数包。

### 字段卡片

| 字段 | Field Catalog |
|---|---|
| `hook_ref` | **语义定义**：Runtime 已注册的事件时机引用，例如 EntryPoint selected、ContentUnit entered、Interaction resolved、Timeline entry due、Track stage changed 或 Ruleset hook。**为什么存在／归属**：Dispatcher 必须确定何时求值；属于 Trigger，不属于 Condition。**反例**：当前感染值、日期字符串或“KP 认为合适时”。**Producer／来源**：Parser 从时间／事件措辞提出；Normalization 映射 Hook catalog；Compiler 只输出 Supported hook。**Consumer**：Rule／Ending Dispatcher、Validation、Indexer。**生命周期**：Draft → Normalize → Compile → Published；实际 hook Event 属于 Runtime。**概念类型**：Runtime Hook Reference。**必填／默认**：Trigger 一旦存在始终必填；无默认。**Validation**：Hook 在目标 Runtime profile 已实现且版本兼容。**Runtime 意义**：注册监听和调度；入口选择必须通过 EntryPoint-selected Hook 进入统一规则链。**样本证据**：《百鸟朝凤》轮次、《复足》分钟间隔、《追沙》沙漏、《RE计划》HO 入口／任务窗口。**成熟度**：**C / Candidate**，catalog 需 Runtime 原型。 |
| `source_ref` | **语义定义**：在同类 Hook 中限定具体事件来源，如某 EntryPoint、Interaction、Timeline、Track、ContentUnit 或 Encounter。**为什么存在／归属**：它限定“谁发出事件”，不同于 RuleScope 的适用范围和 Condition 的读取目标。**反例**：当前 Event ID、任意时间字符串或反向 Rule 列表。**Producer／来源**：Parser 从明确来源提出；Compiler 解析类型化引用；Editor 消歧。**Consumer**：Dispatcher、Validation、Indexer。**生命周期**：Compile → Published；实际 Event source instance 另存。**概念类型**：Optional Typed Event-source Reference。**必填／默认**：当前不可发布；source catalog 获准后由 hook_ref 协议决定，例如 EntryPoint-selected Hook 必须引用具体 EntryPoint；无默认。**Validation**：来源存在，类型与 Hook 协议兼容。**Runtime 意义**：缩小监听范围，并闭合 EntryPoint Event → Rule → Effect → Acquisition 链。**样本证据**：《RE计划》HO 入口、《复足》感染阶段、《追沙》沙漏。**成熟度**：**H / OPEN**。 |

# Condition

对象结论：Condition 是对 Runtime 已注册求值上下文的无副作用谓词。它不决定何时求值、不调用任意脚本，也不理解自然语言。当前 `path/equals` 只是一种迁移事实，不是目标字段形态。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `predicate_ref` | 叶子条件使用的已注册谓词，如 equals、contains、reached | 谓词属于 Condition 的纯判断语义；不得使用任意函数名、脚本或自然语言 prompt | Predicate Reference | 当前 equals 是起点；样本还有阈值、持有、完成等，**C / Candidate** |
| `subject_ref` | 被读取的已声明状态、关系、知识、时间或 Ruleset 值引用 | 用类型化只读引用替代任意字符串 path；属于 Condition，不属于 Entity 当前状态。不得读取 Host 私有记忆或未声明字段 | Typed Read-only Value Reference | 感染阶段、沙漏、猫存活、物品持有、任务里程碑；**C / Candidate** |
| `comparison_operand` | 谓词需要时使用的类型兼容比较值或稳定引用 | 比较目标属于 Condition，不是 Effect 修改值。不得包含执行脚本或任意未经类型校验的值 | Typed Domain Literal／Reference | 阶段 3、沙漏 23、持有钥匙等；**C / Candidate** |
| `combiner` | 复合 Condition 的 all／any／not 等受限逻辑 | 组合语义属于 Condition，不是 Rule conflict policy。不得使用任意表达式字符串 | Closed Logical Combiner | 《RE计划》隐藏结局链、《追沙》复合终局条件；**H / OPEN** |
| `clauses` | 复合 Condition 拥有的子 Condition | 子句不是 Keeper guidance 文本数组；与叶子字段应互斥。不得构成循环引用或无限嵌套 | Collection of Condition Value Objects | 《RE计划》隐藏结局链、《追沙》复合终局条件；**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `predicate_ref` | Parser 从明确比较语句提出；Normalization 映射 predicate catalog；Compiler 输出 | Condition evaluator、Validation、Review 读取 | Draft → catalog 支持后 Published；求值结果不保存 | 叶子 Condition 必填；无默认 | 谓词已实现；所需操作数数量和类型匹配 | 选择纯函数求值器 |
| `subject_ref` | Parser 提出语义目标；Compiler 解析到已声明状态槽／关系／查询；Editor 确认 | Validation、Condition evaluator、Ruleset 读取 | Compile → Published；当前值从 EvalContext 读取 | 叶子 Condition 通常必填；无默认 | 引用存在、可读、类型符合 predicate；禁止任意 JSONPath | 安全读取可信上下文 |
| `comparison_operand` | Parser 从明确阈值／目标提取；Normalization 类型化；Editor 确认 | Validation、Condition evaluator 读取 | Draft → Compile → Published | 由 predicate 协议条件必填；无默认 | 与 subject／predicate 类型兼容；引用可解析 | 提供纯比较参数 |
| `combiner` | Parser 从明确逻辑连接词提出；Editor 必须确认；Compiler 只输出支持值 | Condition evaluator、Validation、Review 读取 | 复合条件 capability 获准后 Published | 复合形式条件必填；无默认 | combiner 已实现；clauses 数量满足协议 | 确定受限复合求值 |
| `clauses` | Parser 提出子句；Editor 消歧；Compiler 递归输出受支持 Condition | Condition evaluator、Validation 读取 | Draft → Compile → Published | 复合形式条件必填；all／any 至少两项，not 恰一项等由 catalog 决定 | 禁止空组、循环和超限嵌套；每个子句合法 | 递归纯谓词求值 |

### 形态不变量

- 叶子形式使用 `predicate_ref`／`subject_ref`／按需 `comparison_operand`。
- 复合形式使用 `combiner`／`clauses`。
- 两种形式互斥；自然语言“足够谨慎”“说辞精彩”“KP 觉得合适”只能保留为 Keeper Guidance 或 Capability Gap。
- 当前 `Condition.path` 不获准成为目标字段；它必须解析成已声明、可验证的 `subject_ref`。

# Effect

对象结论：Effect 是有限的结果意图值对象，没有独立 ID；顺序由父 Outcome／Rule 中的位置确定。执行 Contract 必须映射到唯一 Operation catalog，不能同时维护 Effect 与 Operation 两套竞争语言。每个 Effect 恰好选择一个专用分支。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `operation_ref` | 声明使用哪个受支持原子操作 | Operation 选择属于 Effect，不属于 Rule／Outcome；不得使用任意函数名、脚本或自然语言动词 | Registered Operation Reference | 当前 allow／modify 是最小迁移集；样本还需授予、解锁、终局，**C / Candidate** |
| `state_change` | 状态修改操作的类型化意图：已声明状态槽、受限修改方式和兼容值 | 初值属于 Definition，当前值属于 GameState；Effect 只声明变化。不得使用任意 path、当前快照或无约束键值 | Typed State Change Intent | 《复足》感染、《追沙》沙漏、《蝶骨巢穴》异变；**K / OPEN**（runtime） |
| `information_acquisition_ref` | 信息授予操作引用的 InformationAcquisition | Acquisition 是来源／受众的唯一权威；不得直接引用 InformationItem 或写事实字符串 | InformationAcquisition Reference | Focus-5 均有信息获得，但当前无此执行链且 Acquisition 物理形态未定；**R / Candidate** |
| `content_relation_ref` | 内容激活／解锁操作引用的 ContentRelation | 图关系是端点的唯一权威；不得在 Effect 复制 from／to 或直接设置当前 Scene | ContentRelation Reference | 《RE计划》任务推进、《银之锁》开门、《追书人》进地穴；**K / Candidate** |
| `ending_ref` | 正式终局激活操作引用的 EndingDefinition | 局部 Outcome 只有通过此受控操作才能终止；不得设置 `is_terminal` 或直接写 phase | Ending Reference | 《追书人》《复足》《追沙》《RE计划》多终局；该 variant 为 **R / Candidate**，但它与 `EndingDefinition.activation_trigger` 的“至少一项激活路线”联合职责为 **C / Candidate** |
| `action_authorization` | 在一次已注册动作许可检查中返回允许／拒绝的受控判定意图 | 条件许可属于 Rule 的 Effect，不应由 `blocked_text` 或 Entity 列表暗示；它不是持久状态变化，也不替代 Interaction availability。不得使用自由文本动词 | Typed Action Authorization Decision | 当前 AllowOperation 是最小迁移事实；`refuse_ops` 还需拆到 availability／默认动作门禁，**K / OPEN**（runtime） |
| `ruleset_effect_ref` | 请求 Ruleset 执行 SAN、伤害、法术等已注册专用效果 | 算法属于 Ruleset，模组只绑定类型化调用；不得复制算法或提供通用 parameters 包 | Ruleset Effect Reference／Typed Invocation | 样本普遍有规则系统效果；**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `operation_ref` | Parser 从明确后果提出；Normalization 映射 catalog；Editor 确认；Compiler 只输出支持 operation | Validation、Effect executor、Ruleset、Review 读取 | Draft → Compile → Published；执行生成 Event／StateChange | Effect 始终必填；无默认 | Operation Supported；恰好出现匹配的一个专用分支 | 选择原子执行器 |
| `state_change` | Parser 从明确数值／状态后果提取；Compiler 解析声明状态槽；Editor 确认 | Validation、Effect transaction engine、Event writer、Ruleset 读取 | Compile → Published；结果写 GameState／Event | state-change operation 条件必填，其他 operation 禁止 | 目标槽存在且可写；修改方式和值类型兼容；事务政策明确 | 执行原子状态变化；需 State Definition／事务原型 |
| `information_acquisition_ref` | Compiler 根据信息后果建立／解析 Acquisition 后写入；Parser 只提出语义关系 | Validation、Knowledge Runtime、Projection 读取 | Compile → Published；授予结果写 KnowledgeState／Event | grant-information operation 条件必填，其他 operation 禁止 | 引用存在；recipient 不越权；不得与直接信息字段并存 | 唯一信息授予入口 |
| `content_relation_ref` | Parser 从明确解锁／转场后果提出；Compiler 建立 Relation 并解析引用 | Validation、Navigation Runtime、Review 读取 | Compile → Published；已激活关系状态另存 | relation operation 条件必填 | 引用存在；关系支持动态激活；事务失败政策明确 | 改变可达性而不修改静态图 |
| `ending_ref` | Parser 从“进入结局”提出；Editor 确认为正式终局；Compiler 解析 | Validation、Termination handler、Projection 读取 | Compile → Published；命中写 EndingState | activate-ending operation 条件必填 | 引用存在；普通失败不得误接；若父 Outcome 是 Ending 的 `terminal_outcome`，本 variant 禁止出现 | 唯一显式终局激活路径 |
| `action_authorization` | Parser 从明确许可／禁止规则提出；Normalization 映射 Action；Compiler 输出 | Validation、Runtime Action Gate、Projection 读取 | Compile → Published；本次许可判定写 ActionResult／Event，不回写静态定义 | 对应 operation 条件必填 | Action 已注册；allow／deny 值受限；同次判定冲突政策可确定 | 为当前受控动作请求返回许可结果；需 Runtime 原型 |
| `ruleset_effect_ref` | Compiler 通过 Ruleset adapter 绑定已注册 typed effect | Ruleset、Runtime、Validation 读取 | 专用 subtype 获准后 Published；结果写 Event／GameState | 对应 operation 条件必填 | 版本兼容；专用调用完整；禁止任意参数包 | 调用权威规则算法 |

### 明确不是字段

- 不保存叙事文本、玩家反馈、当前状态值、Event ID 或执行结果。
- 不设置通用 `parameters`、`payload`、`data` 或脚本字段。
- 一个 Effect 不能同时以两个分支表达同一后果；多项后果应使用父对象中的多个有序 Effects。
- 自动 Rule／Action Gate 的即时拒绝原因不能塞入 Effect；在受控 ActionDecision／Notification 呈现协议获得消费者前，这类现行文本只允许由兼容 adapter 保真并记录 Capability Gap。

# EndingDefinition

对象结论：EndingDefinition 是正式终局的静态定义，不是普通失败 Outcome，也不预设“胜利”。它可以被 Effect 显式激活，或在声明 Trigger 上检查 Condition；两条路线最终都只能产生受控 Runtime termination。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `ending_id` | 一个正式终局定义的稳定身份 | Effect、EndingState、Projection 和审计需要引用；不得使用 `win=true`、标题或发生时间代替 | Stable Identifier | 终局 15/15；当前 `WinCondition.id`，**C / Review-ready**（有当前等价语义） |
| `title` | Keeper／玩家界面可用的终局名称 | 名称属于 Ending 展示，不属于 ModuleFrame 或 classification。不得放完整尾声正文或泄露未命中条件 | Display Text | 《追书人》《银之锁》《复足》《追沙》《RE计划》均有可区分的结局段／名称；**R / Candidate** |
| `activation_trigger` | 自动监测型 Ending 在何种 Hook 上检查 | 何时检查属于 Ending 激活协议；Effect 直接激活路线可不需要。不得把成立谓词写在 Trigger | Trigger Value Object | 当前 Runtime 在 action 后检查；样本还有轮次／时间终局；该 variant 为 **R / Candidate**，但它与 inbound `Effect.ending_ref` 的“至少一项激活路线”联合职责为 **C / Candidate** |
| `activation_condition` | Trigger 到达时该 Ending 是否成立的纯谓词 | 成立条件属于 Ending，不属于 terminal Outcome；Effect 直接激活路线通常不应重复同一条件 | Condition Value Object | 当前 `WinCondition.when` 与《RE计划》《追沙》条件链；**R / Candidate** |
| `terminal_outcome` | Ending 命中后执行并呈现的最终 OutcomeDefinition | 终止结果属于 Ending；普通 Outcome 不因此获得 terminal 属性。不得直接保留 `fact`／玩家字符串旁路 | Owned OutcomeDefinition／Outcome Reference | 当前 `fact/player_visible_information` 的目标迁移；终局结果 15/15，但 owned／reference 形态未定，**C / Candidate** |
| `termination_scope` | 该 Ending 终止 Room、Session、Actor 或其他运行作用域的声明 | 它决定 EndingState 归属，不是 RuleScope 或分类；当前只支持 Room／Session，不能据角色尾声直接冻结更广值域 | Termination Scope Value／Reference | 《RE计划》角色差异提示潜在细粒度；**H / OPEN** |
| `classification` | 在真实 UI／统计消费者需要时，对胜利、失败、逃离、异化等结果分类 | 分类属于终局结果，不是 Resolution success 等级；不得默认二元胜负 | Ending Classification Catalog Value | 《追书人》《复足》《追沙》显示多类结果；**H / OPEN** |
| `precedence` | 多个自动 Ending 同时满足时的确定优先关系 | 数组顺序不是领域政策；属于 Ending Dispatcher，不是 Rule priority。不得默认 first-match | Ending Priority／Conflict Value | 当前 first-match 行为暴露缺口；隐藏结局可能与普通结局并发，**H / OPEN** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `ending_id` | Parser 从结局段提出候选；Compiler 分配；Editor 合并同义终局；Publish 冻结 | Validation、Runtime、Projection、Host、Review 读取 | Compile 产生；命中 ID 写 EndingState | Ending 一旦结构化始终必填；无默认 | 模块内唯一；引用闭合；不得与 Outcome ID 混用 | 终止状态和 Event 的定义键 |
| `title` | Parser 从结局标题提取；Editor 确认公开安全性 | Projection、Host、Review 读取 | Draft → Published；命中前是否可见由 Projection 控制 | 可选；无默认 | 非空；不得泄露隐藏结局条件 | Runtime 透传用于结果展示 |
| `activation_trigger` | Parser 从定时／行动后／事件后终局文本提出；Compiler 映射 Hook；Editor 确认 | Ending Dispatcher、Validation、Runtime 读取 | Compile → Published；实际 Hook Event 另存 | 自动监测路线条件必填；Effect 直接激活路线可缺失 | Hook Supported；若 condition 需主动检查则必须有 Trigger；每个可执行 Ending 必须至少有本字段或一个可解析的 inbound `Effect.ending_ref`，两者并存时须有幂等协议 | 决定何时检查终局 |
| `activation_condition` | Parser 从明确终局条件提取；Editor 确认；Compiler 仅输出受支持 Condition | Validation、Ending Runtime、Review 读取 | Draft → Compile → Published；求值不写回 | 可选；Trigger 无 condition 表示 Hook 到达即成立 | 纯谓词；引用合法；直接 Effect 路线不应重复冲突条件 | 自动终局判断 |
| `terminal_outcome` | Parser 从尾声与终局后果提取；Editor 确认；Compiler 解析信息／Effect 关系 | Runtime、Projection、Host、Validation、Review 读取 | Draft → Published；执行写 State／Event | 始终必填于结构化 Ending；无默认 | terminal outcome 内禁止任何 `Effect.ending_ref`，不开放 Ending→Ending 链；信息仍经 Acquisition；为兼容当前空字符串／空集合，可允许经 Review 明确确认的 no-op terminal outcome，终止本身仍由 Ending transaction 记录 | 在受控 termination transaction 中产生最后后果 |
| `termination_scope` | Runtime owner 与 Editor 根据产品语义决定；Compiler 只输出目标 Profile 支持值 | Runtime、Projection、Validation 读取 | 多 scope 原型成立后 Published | 当前不可发布；Scope 协议获准后每个可执行 Ending 条件必填；无通用默认；兼容 Profile 只能显式写 Room／Session | Scope 受支持；EndingState 基数和终止传播规则明确 | 决定谁或什么进入 ended |
| `classification` | Parser 从结局段中显式“逃离／死亡／异化／加入／失败／成功”等措辞提出候选；Editor 确认；只有 UI／统计消费者承诺后 Compiler 输出 | Projection UI、统计、Review 读取；核心 Runtime 可忽略 | 消费者成立后 Published | 可选；无默认 | 值域由消费者定义；不得从标题盲猜 | 默认无终止算法意义 |
| `precedence` | Parser 仅在原文明确时提取；否则 Runtime owner／Editor 定义；Compiler 输出 | Ending Dispatcher、Validation 读取 | 冲突原型成立后 Published | 条件必填：同一 scope 存在多个可能同时命中的自动 Ending 时；否则可选；无默认 | 同一 scope 同时命中时必须能确定拒绝／选择／并行政策 | 避免隐式 first-match；需 Runtime 原型 |

### 终局边界

- 被抓回房间、重试、任务失败但故事继续、阶段完成都只是普通或分支 Outcome。
- EndingDefinition 数量、一个 Ending 影响多少 Scope、同一局可记录多少 EndingState 均保持 OPEN。
- 每个可执行 Ending 必须存在至少一条静态可验证的激活路线；terminal outcome 不得再激活任何 Ending，因此本轮不接受自环或跨 Ending 终止链。
- 胜利、失败、逃离、加入敌方、失踪、死亡、异化只是可选分类；没有分类字段时，终局语义仍由 title／terminal outcome 保真。
- 当前 `WinCondition` 迁移为 EndingDefinition；名称不再预设结果一定是“Win”。

# Optional Capability Objects

以下四类对象由样本提出真实表达需求，但当前 Contract、Runtime 和 Projection 均没有完整消费链。它们的最高状态是 **Candidate／OPEN**，不能据此新增 Schema 字段，也不能成为逐模组必填项：

| Capability | 样本统计 | 当前结论 |
|---|---:|---|
| Timeline | Timeline-12（12/15） | 高频不等于已具备 Scheduler；先冻结静态时间语义候选 |
| Track | Track-7（7/15） | 需要通用 TrackState／阶段事件原型，不能增加感染、异变等模组专用字段 |
| CharacterTemplate | Template-4（4/15） | 四者模板范围不完全相同，且《死者的顿足舞》命中来自套件公共材料；需建局／Ruleset／Projection 原型 |
| EncounterDefinition | 报告未形成统一可复核计数 | 战斗、追逐、谜题、社会冲突不能只凭“遭遇”一词合并执行语义 |

## Deferred Capability Gaps（本轮不设计字段）

输入报告还统计出三类真实但低频的能力需求。本轮没有足够的确定消费者、状态模型或执行协议来推导稳定领域对象，因此**不为它们设计字段**；这不是依据低频删除需求，而是把未解决问题显式保留为 Capability Gap：

| 能力缺口 | 样本证据 | 为什么本轮不能形成字段目录 | 当前保真与后续准入 |
|---|---:|---|---|
| 随机事件／内容表 | 2/15：百鸟朝凤、追沙 | 自动抽取需要明确骰式／抽取 catalog、随机源、可复现策略及“已用项”状态消费者；样本没有证明权重、去重或有放回等统一语义 | 表格正文继续作为 Narrative／Keeper Guidance 保真；只有 Random Resolver、Event 记录和重放测试成立后，才评审独立能力对象 |
| 多势力反应 | 3/15：追沙、柏林：失去昨日、RE计划 | Organization 可先共享 Entity 身份，但当前态度、资源、反应选择和行动历史属于尚未定义的 Faction State／Reaction Engine；不能把它们塞进 Entity 的任意扩展字段 | 势力身份进入 EntityDefinition，反应说明保留自然语言并记录 Gap；只有状态与反应消费者原型成立后再目录化 |
| 跨模组组合／插入 | 2/15：伦道夫·卡特的续述、柏林：失去昨日 | 依赖、插入点、命名空间、版本兼容和冲突合并主要是 Package／Repository／Loader 责任，不应借 ModuleContent 兜底字段提前固化 | 继续由包清单／导入 sidecar 保真并记录 Gap；待组合 Loader、兼容诊断和迁移策略成立后，在正确边界另行建模 |

显式调查网已由 `ContentGraph` 与可选 `InformationItem.information_relations` 承接候选职责；角色独占信息已由 `InformationAcquisition.recipient_policy` 的 H／OPEN 受众能力承接，因此不在此重复建立新对象。

# Timeline

对象结论：Timeline 是可选静态时间调度定义，表达时间坐标、日程项和主持指导；当前时钟、推进原因、到期队列与已触发项属于 Runtime。不是每个有“之前／之后”的模组都需要 Timeline，也不要求统一全局时钟。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `timeline_id` | 一条静态时间轴定义的稳定身份 | Rule Trigger、ClockState 和 Review 需要无歧义引用；不得用标题或当前日期代替 | Stable Identifier | Timeline-12 提供时间表／日程／倒计时；ID 本身来自 Scheduler／引用不变量，**K / Candidate** |
| `label` | 供 Host、编辑和投影识别时间轴的名称 | 名称不承担时间单位或引用职责；不得据名称猜算法 | Display Text | “时间线一览”“沙漏”“三日结构”等；**K / Candidate** |
| `scope_ref` | 时间轴适用的 Module、ContentUnit、Entity 或 Encounter 静态范围 | 不同时间轴可能是全局日期、场景轮或 NPC 日程；作用域属于 Timeline，不应从嵌套猜出。不得存当前参与者 | Typed Scope Reference | 《百鸟朝凤》场景轮、《死者的顿足舞》NPC 日程；**H / OPEN** |
| `clock_binding` | 时间轴使用的坐标基准、单位、起点和推进 Hook 声明 | 绝对日期、相对时长、轮次和有序阶段不能混成普通数字；属于 Timeline，不属于 Trigger 参数 | ClockBinding Value Object | 《柏林：失去昨日》历史日期、《复足》分钟、《百鸟朝凤》轮次；**H / OPEN** |
| `entries` | 该时间轴拥有的静态时间项 | 日程项需要稳定位置和到期语义；不得把 EventLog 或已触发队列塞入 | Owned Collection of TimelineEntry | Timeline-12 提供时间表／日程／倒计时项；**K / Candidate** |
| `keeper_guidance` | 时间调整、节奏和不可执行裁量的保真说明 | 主持裁量不能丢失，也不能伪装成 Scheduler 条件。不得含任意脚本 | Keeper Guidance | 《追书人》的监视日程、《死者的顿足舞》的 NPC 日程、《追沙》的每日推进均含人工调整空间；**K / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `timeline_id` | Compiler 根据明确时间表／倒计时锚点分配；Editor 合并重复轴 | Validation、未来 Scheduler、Rule indexer、Review 读取 | Capability Compile → Published；ClockState 另存 | Timeline 一旦结构化始终必填；无默认 | 模块内唯一；引用闭合；排序变化不改 ID | ClockState／到期 Event 的定义键；当前无 Supported consumer |
| `label` | Parser 从时间线标题提取；Editor 可补充非执行名称 | Host、Review、可选 Projection 读取 | Draft → Published | 可选；无默认 | 非空；不得充当 basis 或 ID | Runtime 核心忽略 |
| `scope_ref` | Compiler 从时间轴宿主和原文适用范围解析；Editor 确认 | Validation、Loader、未来 Scheduler 读取 | Compile → Published；实例基数在 Runtime 创建 | 可执行 Timeline 条件必填；无默认，不默认全局 | scope kind／target 存在且 Scheduler 支持 | 决定创建一个全局、每场景或每实体时钟实例 |
| `clock_binding` | Parser 从明确日期／时长／轮次提取；Compiler 绑定 unit／hook catalog；Editor 处理模糊时间 | Validation、Scheduler、Ruleset、Loader 读取 | Draft → Compile → Published；当前时间另存 | 可执行 Timeline 始终必填；无默认 | basis、unit、origin、advance hook 组合可解析且受支持 | 初始化和推进 ClockState；需 Scheduler 原型 |
| `entries` | Parser 从时间表、日程、倒计时项提取；Compiler 分配 Entry ID 并规范时间 | Validation、Scheduler、Host 读取 | Compile → Published；到期状态／Event 另存 | 可执行 Timeline 至少一项；无默认空执行轴 | Entry ID 唯一；time spec 可比较；重复／错过政策闭合 | 建立到期索引并发出注册 Hook |
| `keeper_guidance` | Parser 从时间调整和节奏建议直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；本局调整写 Event／ClockState | 可选；无默认 | Keeper-only；不得由 Scheduler 解释 | Runtime 不执行；手动 Profile 由 Host 使用 |

### ClockBinding

| 字段 | 完整字段卡片 |
|---|---|
| `basis` | **语义／理由**：声明绝对日期、相对时长、轮次或有序阶段等时间坐标语义；属于 ClockBinding 而非 Timeline label。**Producer／来源**：Parser 从明确时间表达提出；Normalization 对齐 catalog；Compiler 输出。**Consumer**：Validation、Scheduler。**生命周期**：Compile → Published。**概念类型**：Clock-basis Catalog Value。**必填／默认**：可执行 Timeline 必填；无默认。**Validation**：basis 已实现。**Runtime 意义**：选择比较／推进算法。**反例**：任意“剧情时间”。**样本证据**：《柏林：失去昨日》《百鸟朝凤》《更好的明天》；**H / OPEN**（catalog）。 |
| `unit_ref` | **语义／理由**：日、小时、分钟、轮或行动窗口等单位／历法引用；通用换算属于 catalog／Ruleset。**Producer／来源**：Parser 提取，Compiler 解析。**Consumer**：Validation、Scheduler、Ruleset。**生命周期**：Compile → Published。**概念类型**：Time Unit／Calendar Reference。**必填／默认**：由 basis 条件必填；无默认。**Validation**：与 basis 兼容。**Runtime 意义**：时间加减和格式化。**反例**：所有数字默认分钟。**样本证据**：《百鸟朝凤》用轮、《复足》用分钟、《柏林：失去昨日》用日期／天；**H / OPEN**。 |
| `origin` | **语义／理由**：相对时间零点或绝对起点的静态声明；属于定义初值，不是运行中的“现在”。**Producer／来源**：Parser 从明确起点提取；Editor 确认；Compiler 类型化。**Consumer**：Loader、Scheduler、Validation。**生命周期**：Published 静态；建局复制到 ClockState。**概念类型**：Typed Time Origin Value。**必填／默认**：由 basis 条件必填；无默认。**Validation**：与 basis／unit 可解析。**Runtime 意义**：初始化时钟。**反例**：当前日期回写。**样本证据**：《柏林：失去昨日》6 月 21 日、《百鸟朝凤》场景轮起点；**K / Candidate**。 |
| `advance_hook_ref` | **语义／理由**：声明哪个注册 Hook 推进时钟，如回合结束、场景结束、游戏日结束；属于 ClockBinding，不是任意 Trigger 参数。**Producer／来源**：Compiler 绑定 Runtime hook catalog；Editor 确认推进政策。**Consumer**：Validation、Dispatcher、Scheduler。**生命周期**：Compile → Published。**概念类型**：Hook Reference。**必填／默认**：自动推进 Profile 条件必填；手动 Profile 可缺失；无默认。**Validation**：Hook Supported 且适用 scope。**Runtime 意义**：确定推进信号。**反例**：“KP 觉得差不多”。**样本证据**：《百鸟朝凤》每轮、《追沙》每日结束；**H / OPEN**（runtime）。 |

### TimelineEntry

| 字段 | 完整字段卡片 |
|---|---|
| `entry_id` | **语义／理由**：单个时间项身份，供到期 Event／Trigger／Review 引用。**反例**：数组位置或某次到期 Event ID。**Producer／来源**：Compiler 分配，Editor 消歧。**Consumer**：Validation、Scheduler、Rule Dispatcher。**生命周期**：Compile → Published；到期状态另存。**概念类型**：Scoped Stable Identifier。**必填／默认**：Entry 一旦结构化必填；无默认。**Validation**：Timeline 内唯一。**Runtime 意义**：到期 Event 的定义键。**样本证据**：《柏林：失去昨日》的逐日事件、《死者的顿足舞》的 NPC 日程；**K / Candidate**。 |
| `time_spec` | **语义／理由**：时间点、窗口或有序阶段位置；属于 Entry，不是 Trigger。**Producer／来源**：Parser 从明确时间提取；Compiler 按 ClockBinding 类型化。**Consumer**：Validation、Scheduler。**生命周期**：Compile → Published。**概念类型**：Time Mark／Window Value Object。**必填／默认**：始终必填；无默认。**Validation**：与 ClockBinding 一致；窗口上下界合法。**Runtime 意义**：判断到期。**反例**：“合适时”“尽快”。**样本证据**：《柏林：失去昨日》的 6 月 23 日夜、《百鸟朝凤》的 18 轮和多个样本的第二日事件；**K / Candidate**。 |
| `repeat_spec` | **语义／理由**：一次性或按受限周期重复；属于日程定义。**反例**：通用 cron、任意脚本或根据空值猜测的重复政策。**Producer／来源**：Parser 从明确重复措辞提取；Compiler 映射支持 policy；Editor 确认。**Consumer**：Validation、Scheduler。**生命周期**：仅重复 consumer 成立时 Published。**概念类型**：Repeat Policy Value Object。**必填／默认**：当前不可发布；Scheduler 必须先决定“每个 Entry 显式声明 once/repeat”或“缺失严格等于 once”两种协议之一，之后才能冻结必填性；当前无默认。**Validation**：周期与单位兼容；禁止零间隔／任意脚本。**Runtime 意义**：生成后续到期点。**样本证据**：《追书人》每晚监视、NPC 日程；**H / OPEN**。 |
| `presentation_ref` | **语义／理由**：到期时供 Host／Projection 定位的 ContentUnit 或安全叙事定义引用；展示内容与执行 Effect 分离。**Producer／来源**：Compiler 从定时事件正文解析；Editor 确认受众。**Consumer**：Validation、Host、Projection。**生命周期**：Compile → Published。**概念类型**：Typed Presentation Reference。**必填／默认**：可选；无默认。**Validation**：引用存在且可见性安全。**Runtime 意义**：到期后构造上下文。**反例**：直接状态修改。**样本证据**：《追沙》的定时结局、《柏林：失去昨日》的逐日场景；**H / OPEN**（target types）。 |
| `missed_policy` | **语义／理由**：时间窗口被跳过时采用跳过、补发或主持裁量的受限政策；属于 Entry 调度语义。**Producer／来源**：原文明确时 Parser 提取，否则 Editor／Scheduler owner 决定。**Consumer**：Validation、Scheduler、Host。**生命周期**：policy 支持后 Published。**概念类型**：Missed-window Policy Reference。**必填／默认**：有窗口跳时风险时条件必填；无默认。**Validation**：policy 已实现且确定。**Runtime 意义**：处理 reload／time jump。**反例**：Scheduler 默默补发。**样本证据**：《柏林：失去昨日》的历史日程和《死者的顿足舞》的 NPC 日程存在跳过窗口风险；**H / OPEN**。 |

TimelineEntry 不设置 `effects`。到期只发出注册 Hook；状态变化统一由 RuleDefinition → Effect 执行。

# Track

对象结论：Track 是可选的静态度量／阶段状态机定义。感染、异变、沙漏、记忆恢复和故事计数可以共享“量值—阶段—转换”边界，但不共享模组专用字段。当前值、当前阶段和转换历史属于 TrackState／Event。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `track_id` | 一条 Track 定义的稳定身份 | Effect、Rule、TrackState 和 Event 需要引用；不得为每个模组增加 `infection`／`sand` 字段 | Stable Identifier | Track-7 提供明确计数／阶段轨道；ID 本身来自 TrackState／Event 引用不变量，**K / Candidate** |
| `label` | Host／玩家安全视图可用的轨道名称 | 名称不决定算法或状态槽；不得作为 ID | Display Text | Track-7 中《复足》的感染、《蝶骨巢穴》的异变、《追沙》的沙漏等提供名称候选；**K / Candidate** |
| `scope_ref` | Track 按角色、队伍、Entity、Location 或 Module 建立实例的范围 | 感染可每角色一条，沙漏可全局；属于 Track 定义，不是当前 owner ID | Typed Scope Reference | 《复足》角色感染、《追沙》全局沙漏；**H / OPEN** |
| `measure` | Track 的量值类别、单位、合法域和可选派生查询 | 数值、序数阶段和派生计数不能都假定“整数 +1”；属于 Track，不属于 Effect | TrackMeasure Value Object | Track-7 中《复足》的感染阶段、《追沙》的沙漏计数、《苍白面具之下》的故事数语义不同；**H / OPEN** |
| `initial_value` | 新局 TrackState 的静态初值 | 初值属于定义，当前值属于 GameState；不得普遍默认 0 或保存运行快照 | Typed Initial Track Value | 《复足》《追沙》明确 0，但不是通用事实；**K / Candidate** |
| `stages` | 可识别阶段及其匹配与呈现定义 | 阶段说明属于 Track，阶段进入效果仍由 Rule 处理。不得保存当前阶段 | Owned Collection of TrackStage | Track-7 中《复足》《蝶骨巢穴》《幸福蛙蛙村》《追沙》提供明确阶段／阈值；**K / Candidate** |
| `transitions` | 非单纯数值或受限状态机的合法阶段转换 | 不能假定所有 Track 单调上升；属于静态定义，不是历史。不得在其中复制 Effect | Owned Collection of TrackTransition | 《复足》的感染治疗归零与《蝶骨巢穴》的异变恢复提出非单调转换候选；**H / OPEN** |
| `keeper_guidance` | 调节速度、豁免和模糊恢复规则的保真说明 | 主持裁量不应自动变成阈值或 Effect。不得执行 | Keeper Guidance | 《复足》《蝶骨巢穴》《追沙》的轨道均带主持处理说明；**K / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `track_id` | Compiler 对明确轨道分配；Editor 合并重复量值 | Validation、Loader、未来 Track Engine、Rule indexer 读取 | Capability Compile → Published；TrackState 另存 | Track 一旦结构化必填；无默认 | 模块内唯一；引用闭合 | TrackState 和 Event 的定义键 |
| `label` | Parser 从轨道／阶段表标题提取；Editor 审核可见性 | Host、Projection、Review 读取 | Draft → Published | 可选；无默认 | 非空；若玩家可见不得泄密 | Runtime 只透传 |
| `scope_ref` | Compiler 从“每名角色／全局／某实体”等措辞解析；Editor 确认 | Validation、Loader、Track Engine 读取 | Compile → Published；Runtime 按 scope 建实例 | 可执行 Track 条件必填；无默认 | scope 类型受支持；实例基数确定 | 决定 TrackState 键和数量 |
| `measure` | Parser 从阶段表、计数规则提取；Compiler 对齐 measure catalog；Ruleset owner 提供派生查询 | Validation、Track Engine、Ruleset、Projection 读取 | Compile → Published | 可执行 Track 始终必填；无默认 | kind、unit、bounds、derived query 组合合法 | 决定修改／比较／阶段解析算法 |
| `initial_value` | Parser 从明确起始值提取；Editor 确认；Compiler 类型化 | Validation、Loader、Track Engine 读取 | Published 静态；建局复制到 TrackState | 由 `measure.kind` 决定：存储型 Track 条件必填；derived metric 禁止；无默认，不假定 0 | 存储型初值落入合法域且可映射阶段；派生型不得同时声明 | 初始化存储型 TrackState；派生型从注册查询重算 |
| `stages` | Parser 从阶段表提取；Compiler 分配 ID、归一匹配范围；Editor 审核叙事 | Validation、Track Engine、Projection、Host 读取 | Compile → Published；当前阶段另存 | 阶段型 Track 至少一项；纯计数 Track 可为空 | ID 唯一；match 不冲突或冲突政策明确；必要时完整覆盖 | 解析阶段并发出 stage-enter／leave Hook |
| `transitions` | Parser 从治疗、恢复、升级等明确转换提取；Compiler 建关系；Editor 确认 | Validation、Track Engine 读取 | Compile → Published；转换历史另存 Event | 条件必填：不能仅由数值合法域表达时；无默认 | 端点存在；无非法自环；遗漏政策明确 | 供 Track Engine 校验状态转换；发起转换的 Operation／目标引用形态仍是 Capability Gap |
| `keeper_guidance` | Parser 从调节与裁量说明直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；本局调整另存 | 可选；无默认 | Keeper-only；不得被 Engine 解析 | Runtime 不执行；手动处理能力保真 |

### TrackMeasure

| 字段 | 完整字段卡片 |
|---|---|
| `kind` | **语义／理由**：声明 numeric-counter、ordinal-stage 或 derived metric 等受限量值语义；属于 Measure，不是 Track label。**Producer／来源**：Parser 从“阶段表”“累计次数”“已完成故事数”等规则段提出，Compiler 映射 catalog。**Consumer**：Validation、Track Engine。**生命周期**：Compile → Published。**概念类型**：Measure-kind Catalog Value。**必填／默认**：始终必填；无默认。**Validation**：kind Supported。**Runtime 意义**：选择修改／重算方式。**反例**：所有 Track 默认整数。**样本证据**：《复足》感染阶段、《追沙》沙漏计数、《苍白面具之下》九故事进度；**H / OPEN**（catalog）。 |
| `unit_ref` | **语义／理由**：次数、阶段、故事数等单位引用；属于量值解释，不是 player label。**Producer／来源**：Parser 提取，Compiler 绑定 catalog。**Consumer**：Validation、Projection、Track Engine。**生命周期**：Compile → Published。**概念类型**：Measure Unit Reference。**必填／默认**：可选；无默认。**Validation**：与 kind 兼容。**Runtime 意义**：格式化与操作校验。**反例**：把阶段当 HP。**样本证据**：Track-7 分别使用感染阶段、异变阶段、累计故事数或沙漏计数等单位；**H / OPEN**。 |
| `bounds` | **语义／理由**：合法下界、可选上界或有限域；属于静态量值定义。**Producer／来源**：Parser 从阶段／计数规则提取；Compiler 类型化；Editor 确认。**Consumer**：Validation、Track Engine。**生命周期**：Compile → Published。**概念类型**：Range／Finite-domain Value Object。**必填／默认**：受限量值条件必填；开放上界允许明确缺失，但不能由 Runtime 猜造；无默认。**Validation**：若有上界则下界≤上界；覆盖存储型初值；越界政策不能由 Runtime 猜。**Runtime 意义**：拒绝非法修改。**反例**：Runtime 静默截断；把《追沙》的开放阶段 `21+` 当成上界。**样本证据**：《复足》感染 0–5 提供有限范围；《追沙》提供下界／阈值与 `23` 终局条件，但 `21+` 证明上界可能开放；**K / Candidate**。 |
| `derived_metric_ref` | **语义／理由**：从注册状态查询重算 Track 值；派生 Track 不能同时手工修改。**Producer／来源**：Compiler 绑定 Ruleset／Runtime query catalog。**Consumer**：Validation、Track Engine。**生命周期**：查询原型成立后 Published。**概念类型**：Registered Read-only Query Reference。**必填／默认**：derived kind 条件必填；无默认。**Validation**：查询存在、返回类型兼容、无副作用。**Runtime 意义**：重算而非接受 modify。**反例**：自然语言查询、任意代码。**样本证据**：《苍白面具之下》已上演故事数；**H / OPEN**。 |

### TrackStage

| 字段 | 完整字段卡片 |
|---|---|
| `stage_id` | **语义／理由**：阶段稳定身份，供 Hook、Rule、Projection 引用。**反例**：数组下标、阶段显示名或当前阶段值。**Producer／来源**：Compiler 分配。**Consumer**：Validation、Track Engine、Rule Dispatcher。**生命周期**：Compile → Published；当前阶段另存。**概念类型**：Scoped Stable Identifier。**必填／默认**：每个 Stage 必填；无默认。**Validation**：Track 内唯一。**Runtime 意义**：阶段 Event 的定义键。**样本证据**：Track-7 的阶段／计数定义；**K / Candidate**。 |
| `match_spec` | **语义／理由**：值、范围或有限域成员与该阶段的受限匹配；属于 Stage，不是通用 Condition。**Producer／来源**：Parser 从阶段阈值提取；Compiler 类型化。**Consumer**：Validation、Track Engine。**生命周期**：Compile → Published。**概念类型**：Restricted Stage Matcher。**必填／默认**：数值／派生阶段条件必填；无默认。**Validation**：当前目录只允许互不重叠；需要时完整覆盖。若样本确需重叠，必须先新增并证明集合级优先协议，当前记录 Capability Gap。**Runtime 意义**：解析当前阶段。**反例**：LLM 判断“看起来严重”。**样本证据**：《复足》的感染 0–5 与《追沙》的分段阈值提供范围候选；**K / Candidate**。 |
| `presentation` | **语义／理由**：阶段名称、状态描述和规则提示的静态叙事；自然语言惩罚不自动成为 Effect。**反例**：当前阶段、已发生的状态变化或可执行惩罚脚本。**Producer／来源**：Parser 从阶段表直接提取；Editor 分区受众。**Consumer**：Host、Projection、Review。**生命周期**：Draft → Published。**概念类型**：Stage Presentation Value Object／Narrative。**必填／默认**：可选；无默认。**Validation**：可见性和内容一致；不得被 Engine 执行。**Runtime 意义**：当前阶段安全呈现。**样本证据**：《复足》的感染症状、《蝶骨巢穴》的异变描述和《伦道夫·卡特的续述》的感染／认知信息；**K / Candidate**。 |
| `disclosure_policy_ref` | **语义／理由**：该阶段是否向全队、相关角色或仅 Keeper 可见；属于静态呈现政策，当前可见性由 Projection 计算。**Producer／来源**：Parser 从秘密感染／记忆恢复等明确受众措辞提出，Editor 审核，Compiler 绑定 policy。**Consumer**：Validation、Projection。**生命周期**：policy 原型成立后 Published。**概念类型**：Disclosure Policy Reference。**必填／默认**：当前不可发布；Projection Profile 获准后，带 `presentation` 的 Stage 应显式声明披露上界，但字段形态与 requiredness 尚未冻结；无默认。**Validation**：policy 已支持且不泄露 Keeper 内容。**Runtime 意义**：过滤 TrackState 视图。**反例**：当前角色是否已察觉。**样本证据**：《复足》的感染症状、《伦道夫·卡特的续述》的逐步感染／认知信息；**H / OPEN**。 |

### TrackTransition

| 字段 | 完整字段卡片 |
|---|---|
| `transition_id` | **语义／理由**：需要被 Event／审计记录时的转换身份；属于静态转换，不是历史记录。当前 Effect 目录没有 TrackTransition 引用，不能据此声称可执行。**Producer／来源**：Compiler 分配。**Consumer**：Validation、未来 Track Engine、Event writer。**生命周期**：Compile → Published。**概念类型**：Scoped Stable Identifier。**必填／默认**：被 Event／索引引用时条件必填；无默认。**Validation**：Track 内唯一。**Runtime 意义**：候选转换 Event 定义键；Operation 链仍为 Gap。**反例**：数组位置。**样本证据**：《复足》的治疗归零、《蝶骨巢穴》的恢复；**H / OPEN**。 |
| `from_stage_ref` | **语义／理由**：合法来源阶段；属于转换端点，不复制阶段内容。**Producer／来源**：Compiler 引用解析。**Consumer**：Validation、Track Engine。**生命周期**：Compile → Published。**概念类型**：TrackStage Reference。**必填／默认**：转换一旦结构化必填；无默认。**Validation**：同 Track 阶段存在。**Runtime 意义**：验证当前阶段。**反例**：当前状态值。**样本证据**：《复足》的感染治疗与《蝶骨巢穴》的异变恢复；**H / Candidate**。 |
| `to_stage_ref` | **语义／理由**：合法目标阶段；属于转换端点。**Producer／来源**：Compiler 引用解析。**Consumer**：Validation、未来 Track Engine。**生命周期**：Compile → Published。**概念类型**：TrackStage Reference。**必填／默认**：Transition 获准后始终必填；无默认。**Validation**：同 Track 阶段存在；无意义自环按 policy 拒绝。**Runtime 意义**：校验候选状态转换；当前没有可执行 Operation 链。**反例**：直接内嵌目标阶段。**样本证据**：《复足》的治疗归零、《蝶骨巢穴》的恢复；**H / Candidate**。 |

TrackStage 不设置 `effects`。Track Engine 只在阶段进入／离开时发出注册 Hook，实际后果继续由 RuleDefinition → Effect 唯一表达。

# EncounterDefinition

对象结论：EncounterDefinition 是可选的“持续挑战执行入口”，只在内容具有参与槽位、专用 Ruleset／Runtime driver、局部结果和结束条件时成立。简单对峙仍可由 ContentUnit + Interaction 表达；正文出现战斗、追逐、SAN、谜题或社会冲突，不自动证明它们共享同一种 Encounter 执行模型。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `encounter_id` | 一个持续挑战定义的稳定身份 | Orchestrator、RuleScope、EncounterState 和 Event 需要引用；不得用 Scene 名称或当前战斗 ID 代替 | Stable Identifier | 《鬼屋》地下室对抗、《伦道夫·卡特的续述》空中追逐、《蝶骨巢穴》Boss 战提供候选；报告无统一计数，**K / Candidate** |
| `label` | Keeper／编辑可读的遭遇名称 | 名称不决定 driver 或规则；不得根据“追逐”“Boss”词面自动选算法 | Display Text | 《鬼屋》地下室对抗、《伦道夫·卡特的续述》空中追逐、《蝶骨巢穴》Boss 战均有可定位段名；**K / Candidate** |
| `context_refs` | 遭遇所处 ContentUnit／Location 等静态上下文引用 | Encounter 不等于场景或地点；上下文属于 Encounter，不应复制对象身份。不得保存当前参与者位置 | Collection of Typed Context References | 《鬼屋》地下室、《伦道夫·卡特的续述》空中追逐；**K / Candidate** |
| `driver_ref` | 负责战斗、追逐或其他持续挑战算法的已注册 Runtime／Ruleset driver | 通用算法不属于模组；Encounter 只绑定。不得用自由 `kind` 字符串声称支持执行 | Encounter Driver Reference | 《鬼屋》《蝶骨巢穴》的战斗与《伦道夫·卡特的续述》的追逐证明算法类别有差异；没有样本证明统一 driver，**H / OPEN** |
| `driver_binding` | 对所选 driver 已声明、专用、类型化输入的绑定 | 某些 driver 需要回合上限、距离区间等静态输入；它属于 Encounter 与 driver 的接口，不是通用配置包。不得是任意键值、脚本或跨 driver 共用参数容器 | Driver-specific Typed Binding | 《复足》的按调查员人数缩放提出 driver-specific 输入需求；无正文证明统一字段，依据具体 driver consumer 不变量保留为 **H / OPEN** |
| `participant_slots` | 对遭遇静态角色槽位、候选与数量的声明 | 定义候选，不保存本局实际参与者；属于 Encounter，不属于 Entity。不得放当前 HP、先攻或已退出状态 | Owned Collection of ParticipantSlot | 《蝶骨巢穴》的 Boss 与调查员、《伦道夫·卡特的续述》的追逐双方、《复足》的人数缩放提供候选；**K / Candidate** |
| `availability_condition` | Encounter 可被启动的额外纯谓词 | 只作启动守卫，不定义“谁在何时启动”；当前 Effect 目录没有 start-Encounter 操作，激活边仍是 Capability Gap。不得在 Condition 中执行开始效果 | Condition Value Object | 《复足》中物品持有与遭遇行为相关、《银之锁》中走廊遭遇依装备由 Keeper 调整；均不足以推出统一机器守卫，**H / Candidate** |
| `interaction_refs` | 遭遇期间可提出的既有 InteractionDefinition 引用 | 行动语义仍由 Interaction 权威定义；不得复制一套 encounter actions 或本回合已用动作 | Collection of Interaction References | 《复足》的战斗／逃离、《银之锁》的走廊应对、《伦道夫·卡特的续述》的追逐行动提供候选；**K / Candidate** |
| `outcome_definitions` | 该 Encounter 拥有、可由局部结束规则选择的非终局 OutcomeDefinition 集合 | EncounterEndRule 需要指向有明确 owner 的局部结果；结果后果仍由 Outcome → Effect 唯一表达。不得引用另一个 Interaction 的私有 Outcome，也不得把 Module Ending 混入 | Owned Collection of OutcomeDefinition | 《复足》的撤离／死亡、《银之锁》的逃脱／被抓回和《蝶骨巢穴》的 Boss 处理提供局部结果候选；统一 Encounter consumer 尚未成立，**K / Candidate** |
| `end_rules` | 局部遭遇何时结束以及采用何种局部 Outcome 的定义 | Encounter 结束不等同 Module Ending；属于局部 Orchestrator。不得直接终止 Session 或复制 Effect | Owned Collection of EncounterEndRule | 《复足》的撤离／死亡、《银之锁》的逃脱／被抓回、《蝶骨巢穴》的 Boss 处理提供结束条件候选；**K / Candidate** |
| `end_conflict_policy` | 多条 EncounterEndRule 同时成立时的集合级选择／并行政策 | 冲突发生在父集合，不属于某一条 EndRule；不得依赖数组顺序或把它写成 Rule priority | Encounter-end Conflict Policy Value／Reference | 无正文直接证明统一政策；《复足》《蝶骨巢穴》的多种局部结束候选只证明需要由 Orchestrator 原型决定，**H / OPEN** |
| `player_brief_ref` | 遭遇开始时可安全展示的说明内容引用 | 玩家说明与 Keeper 战术分离；属于 Encounter 呈现，不应从 keeper_guidance 直接投影。不得作为执行 driver 输入 | Player-safe Presentation Reference | 《鬼屋》地下室、《伦道夫·卡特的续述》空中追逐存在玩家可感知说明，但没有独立引用形态的正文证据，**H / Candidate** |
| `keeper_guidance` | 氛围、战术、替代处理和开放行动的保真说明 | 大量遭遇语义只能由 Host 裁量；不得变成任意脚本或第二套 Effect 语言 | Keeper Guidance | 《鬼屋》的地下室对抗、《伦道夫·卡特的续述》的空中追逐、《蝶骨巢穴》的 Boss 战提供直接证据；**K / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `encounter_id` | Compiler 对确需持续 Orchestrator 的内容分配；Editor 确认不只是普通 Scene | Validation、未来 Encounter Orchestrator、Rule indexer、Review 读取 | Capability Compile → Published；EncounterState 另存 | Encounter 一旦结构化必填；无默认 | 模块内唯一；引用闭合 | EncounterState 与 Event 的定义键 |
| `label` | Parser 从战斗／追逐／高潮标题提取；Editor 补充非执行名 | Host、Projection、Review 读取 | Draft → Published | 可选；无默认 | 非空；不得据 label 选择 driver | Runtime 只透传 |
| `context_refs` | Compiler 从所在 Unit／Location 解析；Editor 处理一个 Encounter 多场地情况 | Validation、Host Context、Orchestrator 读取 | Compile → Published；当前地点另存 | 可选；默认空集合 | 引用存在；不得形成 Unit／Location 的重复身份 | 激活时构造静态上下文 |
| `driver_ref` | Compiler 通过 Module ruleset_ref 绑定已注册 driver；Ruleset owner 提供协议 | Validation、Encounter Orchestrator、Ruleset 读取 | Driver 原型和版本冻结后 Published | 自动执行 Profile 始终必填；手动叙事不应创建伪 Encounter | Driver Supported、版本兼容、能够解释 binding／slots／end rules | 选择权威执行器；当前无 Supported 通用 driver |
| `driver_binding` | Parser 从明确 driver 输入提出；Compiler 只填入该 driver 专用值对象；Ruleset owner 定义字段 | Validation、Ruleset、Orchestrator 读取 | 专用 driver contract 成立后 Published | 由 driver 协议条件必填；无默认 | 必须由具体 driver 类型校验；基础 Catalog 禁止任意字段 | 初始化执行器；字段形态不能在本轮冻结 |
| `participant_slots` | Parser 从参与角色／数量描述提出；Compiler 解析候选 Entity／Template；Editor 确认 | Validation、Loader、Orchestrator、Projection 读取 | 具体 driver 协议成立后 Compile → Published；实际 participants 写 EncounterState | 由具体 driver 协议决定是否必填及最低基数；当前无通用默认 | 槽位 ID 唯一；候选和 cardinality 合法；基础 Encounter 不预设至少一项 | 激活时解析实际参与者 |
| `availability_condition` | Parser 从明确启动前提提出；Compiler 只输出支持谓词 | Validation、Condition evaluator、Orchestrator 读取 | Draft → Compile → Published；求值不回写 | 可选；缺失表示无额外机器守卫 | 纯谓词；不能包含启动 Effect，也不能代替尚未定义的激活边 | 未来 Orchestrator 用于拒绝非法启动；当前不能自行启动 Encounter |
| `interaction_refs` | Compiler 将遭遇特有动作解析到既有 Interaction；Editor 审核 scope | Validation、Host、Orchestrator、Projection 读取 | Compile → Published；本次可用性仍结合状态计算 | 可选；默认空集合 | 引用存在；不得复制 Interaction 内容；scope 兼容 | 构造当前候选动作 |
| `outcome_definitions` | Parser 从局部结束后果提出候选；Compiler 分配局部 ID 并解析 Effect；Editor 区分普通局部结果与 Module Ending | Validation、Orchestrator、Projection、Host、Review 读取 | 具体 driver 协议成立后 Compile → Published；选中结果与执行事件另存 | 由具体 driver 协议决定是否必填及最低基数；无通用默认 | Outcome ID 在父 Encounter 内唯一；每个 EndRule 引用只能解析到本集合；不得包含 terminal scope | 为 Encounter 结束提供有明确所有者的局部结果 |
| `end_rules` | Parser 从局部结束条件与结果提出；Compiler 结构化 Condition／Outcome 引用；Editor 处理并发条件 | Validation、Orchestrator、Review 读取 | 具体 driver 协议成立后 Compile → Published；ended 状态另存 | 由具体 driver 协议决定是否必填及最低基数；当前无通用默认 | Condition 可判定；Outcome scope 合法；若可能并发则父 Encounter 必须有获准的集合级政策 | 结束局部 Encounter，不直接结束 Module |
| `end_conflict_policy` | Orchestrator owner 定义受控政策；Parser 仅在原文明示优先关系时提出；Editor 确认；Compiler 绑定 | Validation、Orchestrator、Review 读取 | 冲突原型后 Published | 当前不可发布；存在两条可能同时成立的 EndRule 时条件必填；否则可选；无默认 | policy Supported；集合结果确定；不得依赖 EndRule 数组顺序 | 解决同一检查批次的局部结束冲突 |
| `player_brief_ref` | Parser 从玩家安全遭遇说明提取；Compiler 建 presentation 引用；Editor 审查 | Projection、Host、Validation 读取 | Draft → Published | 可选；无默认 | 引用存在且安全；不得指向 Keeper 战术内容 | 激活时构建 PlayerView |
| `keeper_guidance` | Parser 从战术、氛围和替代处理段直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；本局裁量另存 | 可选；无默认 | Keeper-only；Orchestrator 不解释 | Runtime 不执行；手动补充 Host 上下文 |

### ParticipantSlot

| 字段 | 完整字段卡片 |
|---|---|
| `slot_id` | **语义／理由**：参与槽位身份，用于同类多批敌人、加入／退出 Event 和状态分组。**反例**：Entity ID、数组位置或本局 ParticipantState ID。**Producer／来源**：Compiler 分配，Editor 消歧。**Consumer**：Validation、Orchestrator。**生命周期**：Compile → Published；实际 participant state 另存。**概念类型**：Scoped Stable Identifier。**必填／默认**：每个 Slot 必填；无默认。**Validation**：Encounter 内唯一。**Runtime 意义**：ParticipantState 分组键。**样本证据**：《蝶骨巢穴》的 Boss 槽、《伦道夫·卡特的续述》的追逐双方和《复足》的人数缩放；**K / Candidate**。 |
| `role_side` | **语义／理由**：声明该槽在本遭遇中的职责／局部阵营；属于 Encounter 关系，不是 Entity 的善恶类型。**Producer／来源**：Parser 提出、Editor 确认、Compiler 映射 catalog。**Consumer**：Validation、Orchestrator、Projection。**生命周期**：具体 driver 协议成立后 Compile → Published。**概念类型**：Encounter Role／Side Value。**必填／默认**：由具体 driver 协议决定；当前不能冻结；无默认。**Validation**：值受限且与 driver 协议兼容。**Runtime 意义**：目标、胜负或行动范围判定。**反例**：永久角色阵营。**样本证据**：《伦道夫·卡特的续述》的追逐双方、《蝶骨巢穴》的 Boss 与调查员；**H / OPEN**（catalog）。 |
| `candidate_refs` | **语义／理由**：可填入槽位的静态 Entity／CharacterTemplate 引用或已注册选择器；属于槽位，不是当前 participants。**Producer／来源**：Parser 提出，Compiler 解析。**Consumer**：Validation、Loader、Orchestrator。**生命周期**：Compile → Published。**概念类型**：Typed Candidate References／Restricted Selector。**必填／默认**：driver 协议决定；无默认。**Validation**：目标存在；选择器封闭且 Supported。**Runtime 意义**：激活时解析参与者。**反例**：“附近所有敌人”、玩家 ID。**样本证据**：《蝶骨巢穴》的固定 Boss、《伦道夫·卡特的续述》的追逐者、《复足》的调查员人数；**H / OPEN**。 |
| `cardinality` | **语义／理由**：槽位允许的最少／最多参与数；属于静态参与约束。**Producer／来源**：Parser 从明确数量提取；Editor 确认；Compiler 类型化。**Consumer**：Validation、Orchestrator。**生命周期**：具体 driver 协议成立后 Compile → Published。**概念类型**：Cardinality Value Object。**必填／默认**：由具体 driver 协议决定；当前不能冻结；无默认。**Validation**：min≤max 且非负；与 candidate 范围兼容。**Runtime 意义**：验证启动／加入。**反例**：按数组长度暗示规则。**样本证据**：《复足》的按调查员人数缩放和《蝶骨巢穴》的单一 Boss 提供不同数量语义；**K / Candidate**。 |

### EncounterEndRule

| 字段 | 完整字段卡片 |
|---|---|
| `condition` | **语义／理由**：局部 Encounter 结束的纯谓词；属于 EndRule，不是 Module Ending Condition。**Producer／来源**：Parser 从明确退出／击败／轮次条件提出；Compiler 结构化；Editor 确认。**Consumer**：Validation、Condition evaluator、Orchestrator。**生命周期**：Compile → Published。**概念类型**：Condition Value Object。**必填／默认**：每条 EndRule 必填；无默认。**Validation**：可判定、引用合法。**Runtime 意义**：每个受支持 Hook 上检查局部结束。**反例**：“玩家表现够好”。**样本证据**：《银之锁》的逃脱／被抓回、《复足》的撤离／死亡、《蝶骨巢穴》的 Boss 处理；**K / Candidate**。 |
| `outcome_ref` | **语义／理由**：指向父 EncounterDefinition 拥有的局部 OutcomeDefinition；后果仍由 Outcome → Effect 唯一执行。**Producer／来源**：Compiler 引用解析；Editor 审核 scope。**Consumer**：Validation、Orchestrator、Projection。**生命周期**：Compile → Published。**概念类型**：Encounter-local Outcome Reference。**必填／默认**：有结构化结束后果时条件必填；无默认。**Validation**：引用必须解析到父 Encounter 的 `outcome_definitions`，且不得指向 terminal outcome。**Runtime 意义**：选择局部结果。**反例**：跨 Interaction 私有 Outcome 引用、在 EndRule 复制 Effects。**样本证据**：《银之锁》的逃脱／被抓回、《复足》的撤离结果、《蝶骨巢穴》的 Boss 处理；**K / Candidate**。 |

### 明确不是字段

- 当前回合、先攻、HP、临时状态、实际参与者和已退出角色属于 EncounterState／Event。
- 战斗、追逐、SAN、技能和伤害算法属于 Ruleset／driver。
- 简单危险或单次检定不因“遭遇”一词自动建立 EncounterDefinition。
- Encounter 的启动 Hook／Operation／目标引用形态尚未获准；本目录不临时增加 `encounter_ref` 或通用启动字段。发布自动执行 Encounter 前必须先关闭此 Capability Gap。

# CharacterTemplate

对象结论：CharacterTemplate 是可选的静态角色准备定义，表达预制调查员、固定身份或受约束角色构建输入。它不是 CharacterInstance，也不存当前属性、装备、知识或状态。Template-4 的模板粒度不同，且《死者的顿足舞》命中依赖套件公共材料，不能据此冻结唯一模板种类。

### 语义表

| 字段 | 语义定义 | 为什么存在／为什么属于这里／反例 | 概念类型 | 样本证据与成熟度 |
|---|---|---|---|---|
| `character_template_id` | 一种角色模板的稳定身份 | EntryPoint、建局选择、CharacterInstance provenance 和 Review 需要引用；不得用角色姓名或玩家 ID 代替 | Stable Identifier | Template-4（《复足》《死者的顿足舞》《追沙》《RE计划》）；其中《死者的顿足舞》来自套件公共材料，**K / Candidate** |
| `label` | 玩家／Keeper 可识别的模板名称 | 名称不承担实例身份或入口关系；不得用 label 做规则绑定 | Display Text | Template-4 提供预制人物名、HO 名或固定身份名；《RE计划》的 HO1—3 最明确，**K / Candidate** |
| `role_association` | 将模板关联到模组内 HO／固定角色职责的候选语义关系 | 用于 EntryPoint 适配与 Host 上下文，不等于模板类型或玩家席位；一个模板对应一个还是多个 role 尚未确定，因此不以单数 `role_key` 偷冻基数。不得保存当前由谁选择 | Candidate Module-local Role Association | 《RE计划》HO1—3 最明确；关系形态和基数未定，**H / OPEN** |
| `template_kind` | 当建局消费者需要时，区分完整预制、固定身份框架或受约束构建等模板方式 | 模板粒度决定 Loader 行为；属于 CharacterTemplate，不是 Ruleset profile 类型。不得以自由标签宣称支持 | Character Template Kind Catalog Value | Template-4 中《复足》的预制角色、《RE计划》的固定 HO 与《追沙》的人物背景粒度不同；**H / OPEN** |
| `player_description` | 可在选择模板时展示的背景、动机和角色说明 | 玩家导入属于模板呈现；Keeper-only 秘密和当前角色记忆不应混入。不得复制 EntryPoint 的共同开场 | Player-safe Character Brief | 《RE计划》HO、《复足》预制角色、《追沙》人物背景；**K / Candidate** |
| `ruleset_profile_ref` | 指向该模板使用的 Ruleset 角色构建／基础档案 | 属性、技能和派生算法属于 Ruleset；模板只绑定。不得内嵌任意角色卡字典 | Ruleset Character Profile Reference | 《复足》的预制角色与《死者的顿足舞》套件公共调查员包含 CoC 数据；当前无统一 Loader，**H / OPEN** |
| `build_bindings` | 对 Ruleset 已声明角色字段给出的固定值、默认值或可编辑约束 | 模组需要表达预制／受约束构建，但不得复制 Ruleset 字段系统；属于模板，不属于 CharacterInstance。不得使用无语义的任意键值字典 | Collection of RulesetBuildBinding | Template-4，其中《死者的顿足舞》为套件公共材料证据；**H / OPEN** |
| `keeper_guidance` | 仅适用于该模板的扮演、替换和人工调整建议 | 不能机器化的准备说明需保真；全模组指导属于 Frame。不得暗中授予知识或修改角色实例 | Keeper Guidance | Template-4 中《RE计划》的固定身份／HO 说明和《死者的顿足舞》套件公共角色材料提供候选；具体替换政策仍需 Review，**K / Candidate** |

### 运行表

| 字段 | Producer 与精确来源 | Consumer 与读取方式 | 生命周期 | 必填／默认 | Validation | Runtime 意义 |
|---|---|---|---|---|---|---|
| `character_template_id` | Compiler 根据预制人物／HO／固定身份锚点分配；Editor 合并重复模板 | Validation、未来 Character Setup Loader、EntryPoint resolver、Review 读取 | Capability Compile → Published；CharacterInstance 另存 | Template 一旦结构化必填；无默认 | 模块内唯一；引用闭合；不得与 instance ID 混用 | CharacterInstance 的 template provenance 键 |
| `label` | Parser 从角色／HO 标题提取；Editor 做玩家安全审查 | Projection、Host、Character Setup UI、Review 读取 | Draft → Published | 选择 UI 存在时条件必填；无默认 | 非空；不得充当 ID | 建局展示 |
| `role_association` | Parser 从明确 HO／固定职责提出；Compiler 规范 module-local role 候选；Editor 确认 | EntryPoint resolver、Validation、Host 读取 | 当前停留 Draft／OPEN；实际席位另存 | 当前不可发布；Character Setup 必须先决定一对一／一对多基数、模板选择互斥和 assignment 政策；无默认 | role 在模组内稳定且不与 player ID 混用；不能用该关系代替队伍席位分配 | 建局匹配和角色级上下文索引；当前是 Capability Gap |
| `template_kind` | Parser 从完整预制角色卡、固定身份／HO 说明、受约束构建或可调整段落提出候选；Normalization 对齐 catalog；Compiler 只输出 Loader Supported 值 | Validation、Character Setup Loader、Ruleset 读取 | Loader 原型后 Published | 可执行模板条件必填；无默认 | kind Supported；所需 profile／bindings 完整 | 选择完整复制、受约束构建等建局流程 |
| `player_description` | Parser 从角色背景／动机／HO 玩家段直接提取；Editor 去除其他角色秘密 | Projection、Host、Review 读取 | Draft → Published；角色本局经历另存 | 可选；无默认 | 仅向适用模板／入口受众展示；不得混入 Keeper-only 信息 | Loader／Projection 展示，不解释自然语言 |
| `ruleset_profile_ref` | Parser 识别角色数据块；Compiler 通过 Ruleset adapter 建 profile 引用 | Ruleset、Validation、Character Setup Loader 读取 | Ruleset profile 获准后 Published | 完整预制模板条件必填；纯叙事身份模板可缺失 | 引用存在、版本兼容、profile 类型为 character | 提供权威角色构建结构 |
| `build_bindings` | Parser 从固定／推荐／可自选角色字段提出；Compiler 解析到 Ruleset field catalog；Editor 确认 | Ruleset、Validation、Character Setup Loader、Review 读取 | 当前停留 Draft／OPEN；专用建局协议后才可 Published；实际选择写 CharacterInstance | 当前不可发布；未来若字段可选，缺失只表示“模组未声明字段级构建绑定”，不得被解释为无限制或无约束；是否采用空集合默认由 Loader 协议冻结 | 每个 field ref 合法且不重复；值／约束类型兼容 | 初始化或限制 CharacterInstance 构建；需 Loader 原型 |
| `keeper_guidance` | Parser 从角色替换、扮演、人工调整建议直接提取；Editor 确认 | Host Agent、Review 读取 | Draft → Published；实际调整另存 | 可选；无默认 | Keeper-only；不得被 Loader 当隐式 binding | Runtime 不执行；Host 原型消费 |

### RulesetBuildBinding

| 字段 | 完整字段卡片 |
|---|---|
| `ruleset_field_ref` | **语义／理由**：指向 Ruleset 已声明的角色构建字段；属于 binding，不在 ModuleContent 重定义字段。**Producer／来源**：Compiler 经 Ruleset adapter 解析。**Consumer**：Validation、Ruleset、Character Setup Loader。**生命周期**：Compile → Published。**概念类型**：Ruleset Field Reference。**必填／默认**：每条 binding 必填；无默认。**Validation**：引用存在、版本兼容、允许由模组绑定。**Runtime 意义**：定位构建目标。**反例**：任意 path、自建 `STR` 字符串。**样本证据**：《复足》的预制角色与《死者的顿足舞》套件公共调查员数据；field reference 形态来自 adapter 不变量，**H / OPEN**。 |
| `declared_value` | **语义／理由**：原文明示的固定值或建议初值，类型由 field ref 决定；属于模板静态声明，不是当前角色值。**Producer／来源**：Parser 从角色卡直接提取；Compiler 类型化；Editor 确认。**Consumer**：Validation、Ruleset、Loader。**生命周期**：Compile → Published；建局复制或作为建议。**概念类型**：Ruleset-typed Domain Value。**必填／默认**：由 binding policy 条件必填；无默认。**Validation**：类型和范围符合 field。**Runtime 意义**：构建输入。**反例**：任意 JSON 值、运行中 HP。**样本证据**：《复足》的预制角色与《死者的顿足舞》套件公共调查员提供声明值；**H / OPEN**。 |
| `editability_policy` | **语义／理由**：声明该值固定、可选、可替换或仅推荐的受限政策；属于模板构建协议。**Producer／来源**：Parser 从明确“可调整／固定”措辞提出；Editor 确认；Compiler 映射 Loader policy。**Consumer**：Validation、Loader、Projection。**生命周期**：Loader 原型后 Published。**概念类型**：Editability Policy Value。**必填／默认**：存在 declared value 时是否必填由 Loader contract 决定；无默认。**Validation**：policy Supported 且与 field 兼容。**Runtime 意义**：限制 UI／建局操作。**反例**：无约束“自定义”标记。**样本证据**：《RE计划》的固定 HO 与 Template-4 中可调整角色材料证明固定／可调语义并存；统一 policy 无直接字段证据，**H / OPEN**。 |
| `constraint` | **语义／理由**：对可编辑字段使用 Ruleset 已注册约束的引用／类型化值；属于 build binding，不是自然语言建议。**Producer／来源**：Parser 从明确范围／选择集提出；Compiler 绑定 Ruleset constraint catalog。**Consumer**：Validation、Ruleset、Loader。**生命周期**：Constraint 原型后 Published。**概念类型**：Ruleset Constraint Reference／Typed Value。**必填／默认**：可选；无默认。**Validation**：约束已实现且与 field 类型兼容。**Runtime 意义**：校验玩家构建选择。**反例**：“做一个有趣角色”、任意表达式。**样本证据**：Template-4 的固定身份／受约束准备需求提供候选；无正文证明统一 constraint catalog，**H / OPEN**。 |

### 明确不是字段

- 不设置玩家 ID、CharacterInstance ID、当前属性、当前装备、当前知识或状态。
- 不在 CharacterTemplate 再设置 `entry_point_refs`；EntryPoint 的 `eligible_character_template_refs` 是关系权威。
- 不在 CharacterTemplate 设置直接初始信息授予字段；入口选择由 `EntryPoint selected` Trigger 对应的 Rule Effect 激活 InformationAcquisition，避免授予旁路。
- 《死者的顿足舞》若模板来自套件公共材料，仍需 provenance 审阅；Template-4 只证明可选准备需求，不证明每个命中样本都有同等粒度的模组内模板。

# Consumer Matrix

## 矩阵读法

下表是**目标职责矩阵**，不是“当前代码已经实现”的声明。每个字段仍须结合前文字段卡片中的 Current／Review-ready／Candidate／OPEN 分析标签判断是否值得继续评审。

| 代码 | 含义 |
|---|---|
| `Wᴰ` | Parser 只写 ModuleDraft 候选及 provenance，不写 Published ModuleContent |
| `Wᴾ` | Compiler 读取 Draft／Editor 决议并写 Published 值 |
| `R` | Read：字段获准后有确定读取职责；若未在第 1 节列出现行实现证据，其正式 consumer 状态仍是 Proposed |
| `R?` | Read（待证）：消费方向需要原型确认，正式 consumer 状态为 UNKNOWN；不能作为当前 Contract 准入证据 |
| `I` | 明确忽略；不得依赖该字段 |

矩阵只在逐字段核对后，才把读写关系完全相同的字段并为一行；逗号分隔的每个字段仍保留前文独立语义与 Validation。这里的 Runtime 包含 Loader、Router、Dispatcher、Evaluator、Executor 与 Orchestrator 等运行组件；`I` 表示该领域角色不应依赖字段语义，即使底层反序列化器会机械经过该值。

本轮没有发现任何对新增字段的正式 Committed consumer 决议。因此，只有另有当前代码 read-site 证据的旧字段职责才可标为 Existing；第 1 节的字段清单本身不构成读取证据。表中 `Wᴰ`／`Wᴾ`／`R` 均按 Proposed 处理，`R?` 按 UNKNOWN 处理；同名旧字段扩展出的新语义也仍是 Proposed。这些标记都不能单独支持 Schema 准入。

## 聚合、身份、框架与内容图

| 字段 | Parser | Compiler | Validation | Runtime | Projection | Host | Review | Ruleset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `ModuleContent.identity` | Wᴰ | Wᴾ | R | R? | R | R | R | R? |
| `ModuleContent.frame` | Wᴰ | Wᴾ | R | I | R | R | R | I |
| `ModuleContent.content_graph` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `ModuleIdentity.module_id` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ModuleIdentity.content_version` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ModuleIdentity.title` | Wᴰ | Wᴾ | R | I | R | R | R | I |
| `ModuleIdentity.ruleset_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `ModuleFrame.summary`, `keeper_background`, `keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `ModuleFrame.player_premise` | Wᴰ | Wᴾ | R | I | R | R | R | I |
| `ModuleFrame.background_information_refs` | I | Wᴾ | R | I | I | R | R | I |
| `ModuleFrame.entry_points` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `EntryPoint.entry_point_id` | I | Wᴾ | R | R? | I | I | R | I |
| `EntryPoint.label`, `player_introduction` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `EntryPoint.start_content_unit_ref` | I | Wᴾ | R | R? | I | R | R | I |
| `EntryPoint.eligible_character_template_refs` | I | Wᴾ | R | R? | R? | I | R | R? |
| `EntryPoint.availability_condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ContentGraph.content_units` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `ContentGraph.content_relations` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `ContentUnit.content_unit_id` | I | Wᴾ | R | R? | R? | R | R | I |
| `ContentUnit.name`, `player_content` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `ContentUnit.unit_type` | Wᴰ | Wᴾ | R | R? | I | R? | R | I |
| `ContentUnit.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `ContentUnit.entity_refs` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `ContentUnit.information_refs` | I | Wᴾ | R | I | I | R? | R | I |
| `ContentUnit.interaction_refs` | I | Wᴾ | R | R? | R? | R | R | I |
| `ContentUnit.location_refs` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `ContentRelation.relation_id` | I | Wᴾ | R | R? | I | I | R | I |
| `ContentRelation.relation_type` | Wᴰ | Wᴾ | R | R? | I | R? | R | I |
| `ContentRelation.source_content_unit_ref`, `target_content_unit_ref` | I | Wᴾ | R | R? | I | R? | R | I |
| `ContentRelation.availability_condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ContentRelation.choice_label` | Wᴰ | Wᴾ | R | I | R? | R | R | I |

## Entity、Location、Information 与 Interaction

| 字段 | Parser | Compiler | Validation | Runtime | Projection | Host | Review | Ruleset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `EntityDefinition.entity_id` | I | Wᴾ | R | R | R | R | R | I |
| `EntityDefinition.name`, `aliases` | Wᴰ | Wᴾ | R | I | R | R | R | I |
| `EntityDefinition.entity_categories` | Wᴰ | Wᴾ | R | R? | R? | I | R | R? |
| `EntityDefinition.player_description` | Wᴰ | Wᴾ | R | I | R | R | R | I |
| `EntityDefinition.keeper_context` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `EntityDefinition.ruleset_profile_refs`, `initial_state` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `LocationDefinition.location_id` | I | Wᴾ | R | R? | R? | R | R | I |
| `LocationDefinition.name`, `aliases`, `player_description` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `LocationDefinition.keeper_context` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `LocationDefinition.parent_location_ref` | I | Wᴾ | R | R? | I | R? | R | I |
| `LocationDefinition.spatial_links` | Wᴰ | Wᴾ | R | R? | I | R? | R | I |
| `InformationItem.information_id` | I | Wᴾ | R | R? | R? | R | R | I |
| `InformationItem.statement` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `InformationItem.label` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `InformationItem.disclosure_policy` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `InformationItem.semantic_kind` | Wᴰ | Wᴾ | R | I | I | I | R | I |
| `InformationItem.information_relations` | Wᴰ | Wᴾ | R | I | I | R? | R | I |
| `InformationAcquisition.acquisition_id` | I | Wᴾ | R | R? | I | I | R | I |
| `InformationAcquisition.information_ref` | I | Wᴾ | R | R? | R? | I | R | I |
| `InformationAcquisition.source_refs` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `InformationAcquisition.context_content_unit_ref` | I | Wᴾ | R | R? | I | R | R | I |
| `InformationAcquisition.availability_condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `InformationAcquisition.recipient_policy` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `InformationAcquisition.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `InformationSourceRef.source_kind` | I | Wᴾ | R | R? | I | R | R | I |
| `InformationSourceRef.source_ref` | I | Wᴾ | R | R? | I | R | R | I |
| `InformationSourceRef.source_role` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `InteractionDefinition.interaction_id` | I | Wᴾ | R | R? | R? | R | R | I |
| `InteractionDefinition.action_concept` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `InteractionDefinition.player_prompt` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `InteractionDefinition.target_refs` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `InteractionDefinition.availability_condition` | Wᴰ | Wᴾ | R | R? | R? | R? | R | I |
| `InteractionDefinition.resolution` | Wᴰ | Wᴾ | R | R? | I | R | R | R? |
| `InteractionDefinition.outcome_definitions` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `InteractionDefinition.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `InteractionTargetRef.target_kind` | I | Wᴾ | R | R? | R? | I | R | I |
| `InteractionTargetRef.target_ref` | I | Wᴾ | R | R? | I | R | R | I |
| `InteractionTargetRef.target_role` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `ResolutionDefinition.mode` | Wᴰ | Wᴾ | R | R? | I | R | R | R? |
| `ResolutionDefinition.resolver_ref` | I | Wᴾ | R | R? | I | I | R | R? |
| `ResolutionDefinition.result_bindings` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `ResolutionDefinition.skill_option_refs` | Wᴰ | Wᴾ | R | R? | I | R | R | R? |
| `ResolutionDefinition.difficulty_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `ResolutionDefinition.adjudication_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `ResolutionResultBinding.result_key` | I | Wᴾ | R | R? | I | I | R | R? |
| `ResolutionResultBinding.outcome_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `OutcomeDefinition.outcome_id` | I | Wᴾ | R | R? | I | I | R | I |
| `OutcomeDefinition.label` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `OutcomeDefinition.ordered_effects` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `OutcomeDefinition.player_feedback` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `OutcomeDefinition.narration_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |

## Rule、Condition、Effect 与 Ending

| 字段 | Parser | Compiler | Validation | Runtime | Projection | Host | Review | Ruleset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `RuleDefinition.rule_id` | I | Wᴾ | R | R | I | I | R | I |
| `RuleDefinition.label` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `RuleDefinition.trigger`, `condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `RuleDefinition.scope_refs` | I | Wᴾ | R | R? | I | I | R | I |
| `RuleDefinition.ordered_effects` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `RuleDefinition.priority` | Wᴰ | Wᴾ | R | R | I | I | R | I |
| `RuleDefinition.conflict_policy` | I | Wᴾ | R | R? | I | I | R | I |
| `RuleScope.scope_kind`, `target_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `Trigger.hook_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `Trigger.source_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `Condition.predicate_ref`, `comparison_operand`, `combiner`, `clauses` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `Condition.subject_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `Effect.operation_ref`, `state_change` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `Effect.information_acquisition_ref` | I | Wᴾ | R | R? | R? | I | R | I |
| `Effect.content_relation_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `Effect.ending_ref` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `Effect.action_authorization` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `Effect.ruleset_effect_ref` | I | Wᴾ | R | R? | I | I | R | R? |
| `EndingDefinition.ending_id` | I | Wᴾ | R | R? | R? | R | R | I |
| `EndingDefinition.title` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `EndingDefinition.activation_trigger`, `activation_condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `EndingDefinition.terminal_outcome` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `EndingDefinition.termination_scope` | I | Wᴾ | R | R? | R? | I | R | I |
| `EndingDefinition.classification` | Wᴰ | Wᴾ | R | I | R? | I | R | I |
| `EndingDefinition.precedence` | Wᴰ | Wᴾ | R | R? | I | I | R | I |

## Optional Capability 字段

此表中的所有 Runtime `R?` 都是**待原型职责**；没有任何一行据此获得当前 Schema 准入。

| 字段 | Parser | Compiler | Validation | Runtime | Projection | Host | Review | Ruleset |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `Timeline.timeline_id` | I | Wᴾ | R | R? | I | I | R | I |
| `Timeline.label` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `Timeline.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `Timeline.scope_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `Timeline.clock_binding` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `Timeline.entries` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `ClockBinding.basis` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ClockBinding.unit_ref` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `ClockBinding.origin` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ClockBinding.advance_hook_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `TimelineEntry.entry_id` | I | Wᴾ | R | R? | I | I | R | I |
| `TimelineEntry.time_spec`, `repeat_spec` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `TimelineEntry.missed_policy` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `TimelineEntry.presentation_ref` | I | Wᴾ | R | R? | R? | R | R | I |
| `Track.track_id` | I | Wᴾ | R | R? | I | I | R | I |
| `Track.label` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `Track.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `Track.scope_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `Track.measure` | Wᴰ | Wᴾ | R | R? | R? | I | R | R? |
| `Track.initial_value` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `Track.stages` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `Track.transitions` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `TrackMeasure.kind`, `bounds` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `TrackMeasure.derived_metric_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `TrackMeasure.unit_ref` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `TrackStage.stage_id` | I | Wᴾ | R | R? | I | I | R | I |
| `TrackStage.match_spec` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `TrackStage.presentation` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `TrackStage.disclosure_policy_ref` | Wᴰ | Wᴾ | R | I | R? | I | R | I |
| `TrackTransition.transition_id` | I | Wᴾ | R | R? | I | I | R | I |
| `TrackTransition.from_stage_ref`, `to_stage_ref` | I | Wᴾ | R | R? | I | I | R | I |
| `EncounterDefinition.encounter_id` | I | Wᴾ | R | R? | I | I | R | I |
| `EncounterDefinition.label` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `EncounterDefinition.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `EncounterDefinition.context_refs` | I | Wᴾ | R | R? | I | R | R | I |
| `EncounterDefinition.driver_ref` | I | Wᴾ | R | R? | I | I | R | R? |
| `EncounterDefinition.driver_binding` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `EncounterDefinition.participant_slots` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `EncounterDefinition.availability_condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `EncounterDefinition.interaction_refs` | I | Wᴾ | R | R? | R? | R | R | I |
| `EncounterDefinition.outcome_definitions` | Wᴰ | Wᴾ | R | R? | R? | R | R | I |
| `EncounterDefinition.end_rules` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `EncounterDefinition.end_conflict_policy` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `EncounterDefinition.player_brief_ref` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `ParticipantSlot.slot_id` | I | Wᴾ | R | R? | I | I | R | I |
| `ParticipantSlot.role_side` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |
| `ParticipantSlot.candidate_refs` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `ParticipantSlot.cardinality` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `EncounterEndRule.condition` | Wᴰ | Wᴾ | R | R? | I | I | R | I |
| `EncounterEndRule.outcome_ref` | I | Wᴾ | R | R? | R? | I | R | I |
| `CharacterTemplate.character_template_id` | I | Wᴾ | R | R? | I | I | R | I |
| `CharacterTemplate.label`, `player_description` | Wᴰ | Wᴾ | R | I | R? | R | R | I |
| `CharacterTemplate.keeper_guidance` | Wᴰ | Wᴾ | R | I | I | R | R | I |
| `CharacterTemplate.role_association` | Wᴰ | Wᴾ | R | R? | I | R | R | I |
| `CharacterTemplate.template_kind` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `CharacterTemplate.ruleset_profile_ref`, `build_bindings` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `RulesetBuildBinding.ruleset_field_ref` | I | Wᴾ | R | R? | I | I | R | R? |
| `RulesetBuildBinding.declared_value`, `constraint` | Wᴰ | Wᴾ | R | R? | I | I | R | R? |
| `RulesetBuildBinding.editability_policy` | Wᴰ | Wᴾ | R | R? | R? | I | R | I |

## Matrix 结论

1. Parser 对稳定 ID、最终引用和执行 catalog 没有 Published 写权限；它只能提出 Draft 候选。
2. Compiler 是 Published 字段的主要写入者，但不能自行创作缺失叙事或把自然语言裁量升级成可执行字段。
3. Validation 对所有获准字段有读取职责；“能校验”仍不等于 Runtime 会执行。
4. Runtime、Projection、Host 和 Ruleset 的 `R?` 是当前最大的技术缺口，`R` 也仍需 consumer owner 从 Proposed 升为 Committed；没有对应承诺／原型的字段不能因 Parser 能提取而进入 Contract。
5. Host 不得直接把 Keeper-only `statement`、`keeper_context` 或 guidance 投影给玩家；它必须经受控上下文和 Projection。

# 字段成熟度汇总

成熟度回答“字段在目标领域中的必要性”，不回答“现在能否直接加到 Schema”。同一行中若某个 catalog、基数或物理所有权仍为 OPEN，会在备注中保留。

## ① 核心字段（C：v1 必须）

| 对象 | 字段 | 统计／现行依据 | 尚存边界 |
|---|---|---|---|
| ModuleContent | `identity` | 当前已有 module/version/world_ref 必填身份输入 | world_ref 尚未成为已解析 Provider；聚合物理内嵌方式随 major migration 决定 |
| ModuleIdentity | `module_id`, `content_version`, `ruleset_ref` | 当前 Contract 要求 `module_id/version/world_ref` 非空；`world_ref` 只是 Ruleset 绑定迁移输入 | Runtime/Loader 尚未消费 version/provider；wire name、Provider 解析与引用形态待迁移 |
| ContentUnit | `content_unit_id`, `name`, `player_content`, `entity_refs` | 当前 Scene 提供 ID／名称／内容／实体关系迁移输入；内容段、参与对象 All-15（15/15） | Scene→ContentUnit 破坏性迁移；`Scene.content` 不证明玩家安全分区；`Scene.entity_ids` 具有现行在场／目标行为，目标初始化语义仍需原型 |
| EntityDefinition | `entity_id`, `name`, `aliases`, `player_description` | 当前 Entity 有等价必填／可选字段；参与对象 15/15 | description 的可见性拆分仍需审阅；分类字段另列 H |
| InteractionDefinition | `interaction_id`, `action_concept`, `outcome_definitions` | 当前 Checkpoint 提供身份、Host action hint 和结果迁移输入；触发和后果 15/15 | action catalog、target 基数、开放交互是否有封闭 outcomes 未冻结 |
| OutcomeDefinition | `ordered_effects`, `narration_guidance` | 当前 `ops` 有执行路径；`narration_constraints` 只有 Runtime 搬运事实，尚无 Host 读取实现，目标职责依据样本与 Proposed Host／Review consumer | 独立 Outcome ID 另列 R；no-op 分支必须显式审阅；Host consumer 原型未成立前不得据此准入 |
| RuleDefinition | `rule_id`, `trigger`, `condition`, `ordered_effects`, `priority` | 当前 Rule 有迁移字段和部分 Operation 执行路径 | priority 当前只用于 Entity allow-rule；Hook 只是 Declared，Dispatcher 不完整；Trigger／Condition 目标形态和 scope 需迁移 |
| Trigger | `hook_ref` | 当前 `Rule.hook` 和 action 后 WinCondition 检查提供最小语义 | 完整 Hook catalog 与 Supported dispatcher 需 Runtime 原型 |
| Condition | `predicate_ref`, `subject_ref`, `comparison_operand` | 当前 equals 提供最小语义；样本需要阈值／持有等 | `path` 不保留；predicate／subject catalog 未完成 |
| Effect | `operation_ref` | 当前 allow／modify Operation 提供最小执行语义 | 完整 Operation catalog、类型化 target 和事务未完成 |
| EndingDefinition | `ending_id`, `terminal_outcome` | 当前 WinCondition 等价职责；终局 15/15 | Ending 数量、scope、冲突和激活方式保持 OPEN |
| EndingDefinition／Effect | 激活路线联合职责：`activation_trigger` 或 inbound `ending_ref` 至少一项 | 当前 `WinCondition.when` 及 action 后检查提供自动路线迁移事实；样本中的局部 Outcome 进入终局提供显式路线候选 | 这是 C / Candidate 不变量，不是新增兜底字段；两个 variant 各自仍为 R，Hook／Operation catalog 与幂等协议未冻结 |

`condition` 在 Rule 中是“核心可选”：Rule 必须允许表达 Condition，但每条 Rule 不必都有 Condition。C 只表示目标 v1 应保留该职责；对象内部的 requiredness 仍以前文字段卡为准，也不表示字段已获 Accepted。

## ② 推荐字段（R：建议）

| 对象 | 字段 | 推荐理由 | 当前阻碍 |
|---|---|---|---|
| ModuleContent | `frame`, `content_graph` | 分离全局叙事与可寻址内容 | 物理布局与 Runtime profile 未冻结 |
| ModuleIdentity | `title` | 15/15 有标题，Projection／Host 有直接用途 | 当前 v1 缺失，需迁移和 UI 约束 |
| ModuleFrame | `summary`, `player_premise`, `keeper_background` | 前提、幕后 15/15，且受众职责明确 | 不要求原文必须已有摘要；需 Review 流程 |
| ContentGraph | `content_units`, `content_relations` | 统一内容所有权与关系校验 | 不是所有 Narrative Profile 都需结构化图 |
| ContentUnit | `keeper_guidance` | 保存局部不可执行裁量 | Host 最小上下文待原型 |
| ContentRelation | `source_content_unit_ref`, `target_content_unit_ref` | 一旦结构化 Relation，端点不可缺 | relation type catalog 尚未冻结 |
| EntityDefinition | `keeper_context` | 当前 secrets／主持说明需要保真去向 | 与 InformationItem 的拆分需 Review |
| InformationItem | `information_id`, `statement`, `label` | 一旦信息独立结构化，身份和唯一 statement 不可缺；Host／Review 还需要定位 | 当前无 Knowledge/Projection 端到端；不要求每句背景都原子化 |
| InformationAcquisition | `acquisition_id`, `information_ref`, `source_refs`, `keeper_guidance` | 分离本体与获得路径，支撑多来源与审计 | 当前无独立模型；ID 物理形态、source catalog、Host 流程待确认 |
| InformationSourceRef | `source_ref` | 来源关系不能靠自由文本 | source kind catalog 未冻结 |
| InteractionDefinition | `player_prompt`, `availability_condition`, `keeper_guidance` | 分离动作语义、可见提示、硬守卫和裁量 | Intent Router／Host 原型 |
| InteractionTargetRef | `target_ref` | 目标必须是类型化引用 | target kind／数量／角色 OPEN |
| ResolutionDefinition | `result_bindings`, `adjudication_guidance` | 去除固定二元结果，并保留受控主持裁量 | result catalog 与 Host decision 原型 |
| ResolutionResultBinding | `result_key`, `outcome_ref` | 去除固定 success/failure 并绑定已有 Outcome | 由 Resolver／Ruleset catalog 定义 |
| OutcomeDefinition | `outcome_id`, `label`, `player_feedback` | 提供稳定分支键，并区分分支定位与即时安全反馈 | ID 限定方式、Projection／持久知识边界需 E2E |
| RuleDefinition | `label` | 改善 Host／诊断／Review 可读性 | 非执行必需 |
| Effect | `information_acquisition_ref`, `ending_ref` | 分别闭合持久信息授予和显式局部结果进入终局 | Knowledge／Ending Runtime 尚未实现 |
| EndingDefinition | `title`, `activation_trigger`, `activation_condition` | 支持可展示终局和自动监测路线 | Dispatcher、复合条件、两种激活路线需原型 |

## ③ 可选字段（K：Capability）

| Capability／对象 | 字段 | 准入条件 |
|---|---|---|
| EntryPoint ↔ CharacterTemplate | `eligible_character_template_refs` | Character Setup 和角色级 Knowledge Projection 同时原型化 |
| ContentUnit ↔ Location | `location_refs` | Location identity／spatial consumer 获准 |
| LocationDefinition | `location_id`, `name`, `aliases`, `player_description`, `keeper_context` | 多地点身份有真实 Host 或 navigation consumer |
| Information graph | `InformationItem.information_relations` | 线索网络／Review／Host 图谱 consumer 成立 |
| Effect state/navigation/action | `state_change`, `content_relation_ref`, `action_authorization` | 对应 State Definition、Navigation、Action Gate Runtime 支持 |
| Timeline | `timeline_id`, `label`, `entries`, `keeper_guidance`，以及 `ClockBinding.origin`、`TimelineEntry.entry_id/time_spec` | Scheduler、ClockState、到期 Event 与 Projection E2E |
| Track | `track_id`, `label`, `initial_value`, `stages`, `keeper_guidance`，以及 `TrackMeasure.bounds`、`TrackStage.stage_id/match_spec/presentation` | TrackState、合法转换、stage Hook、Projection E2E |
| EncounterDefinition | `encounter_id`, `label`, `context_refs`, `participant_slots`, `interaction_refs`, `outcome_definitions`, `end_rules`, `keeper_guidance`，以及已标 K 的 Slot／EndRule 字段 | 至少一个具体 driver 完成端到端原型；EndRule 只能引用父 Encounter 拥有的局部 Outcome |
| CharacterTemplate | `character_template_id`, `label`, `player_description`, `keeper_guidance` | Character Setup Loader、Ruleset profile、角色级 Projection E2E |

K 字段永远是“能力启用时条件存在”，不是 15 个模组逐项必填。Timeline 的 12/15 高频也不能改变这一点。

## ④ 暂缓字段（H：等待消费者或形态）

| 对象 | 暂缓字段 | 不能冻结的原因 |
|---|---|---|
| ModuleFrame | `background_information_refs`, `keeper_guidance`, `entry_points` | 信息独立化粒度、Host 上下文和 EntryPoint 物理结构未定 |
| EntryPoint | `entry_point_id`, `label`, `player_introduction`, `start_content_unit_ref`, `availability_condition` | 单／多入口基数、建局 consumer 和导航根未原型化 |
| ContentUnit | `unit_type`, `information_refs`, `interaction_refs` | 类型全集、信息上下文 consumer 与 Interaction 关系方向未确定 |
| ContentRelation | `relation_id`, `relation_type`, `availability_condition`, `choice_label` | ID 条件、类型 catalog、动态激活和选择 UI 未原型化 |
| EntityDefinition | `entity_categories`, `ruleset_profile_refs`, `initial_state` | 分类 catalog／基数、Profile 类型、状态槽和 Loader 尚未冻结 |
| LocationDefinition | `parent_location_ref`, `spatial_links` | 层级基数、方向、所有权、link 类型及地图 consumer 均 OPEN |
| InformationItem | `disclosure_policy`, `semantic_kind` | recipient／Projection policy 与分类 consumer 未冻结 |
| InformationSourceRef | `source_kind`, `source_role` | 来源类型／作用目录未冻结 |
| InformationAcquisition | `context_content_unit_ref`, `availability_condition`, `recipient_policy` | 激活上下文、Knowledge Runtime 与角色级受众未完成 |
| InteractionDefinition／TargetRef | `resolution`, `target_refs`, `target_kind`, `target_role` | Resolution variant／物理形态、零／一／多目标、目标全集与多目标 role OPEN |
| ResolutionDefinition | `mode`, `resolver_ref`, `skill_option_refs`, `difficulty_ref` | mode／Resolver catalog 与 Ruleset Check subtype 未冻结 |
| Trigger | `source_ref` | Event-source catalog、类型及各 Hook 的必填协议未冻结 |
| RuleDefinition／RuleScope | `scope_refs`, `scope_kind`, `target_ref`, `conflict_policy` | Scope 数量／组合／索引与事务冲突政策 OPEN |
| Condition | `combiner`, `clauses` | 复合表达范围、深度与短路政策未原型化 |
| Effect | `ruleset_effect_ref` | 专用 effect subtype 与调用参数必须由 Ruleset 定义 |
| EndingDefinition | `termination_scope`, `classification`, `precedence` | scope、EndingState 基数、统计 consumer 与同时命中政策 OPEN |
| Timeline | `scope_ref`, `clock_binding`，以及 `ClockBinding.basis/unit_ref/advance_hook_ref`、`TimelineEntry.repeat_spec/presentation_ref/missed_policy` 等标 H 字段 | Scheduler 协议和值域未冻结 |
| Track | `scope_ref`, `measure`, `transitions`，以及 `TrackMeasure.kind/unit_ref/derived_metric_ref`、`TrackStage.disclosure_policy_ref`、TrackTransition 全部字段 | Track Engine、派生查询、可见性与转换协议未冻结 |
| EncounterDefinition | `driver_ref`, `driver_binding`, `availability_condition`, `end_conflict_policy`, `player_brief_ref` 及标 H 的 Slot 字段 | 没有统一 driver、启动协议或集合级冲突政策；报告也没有可复核统一频次 |
| CharacterTemplate | `role_association`, `template_kind`, `ruleset_profile_ref`, `build_bindings` 及 RulesetBuildBinding 全部字段 | Loader／Ruleset adapter／角色选择基数、互斥、assignment 与自定义政策未冻结 |
| Deferred capabilities | 本轮不接纳随机表、势力反应、跨模组组合字段 | 分别缺少 Random Resolver、Faction State／Reaction Engine、Package／Composition Loader；需求已登记为 Capability Gap，不能用兜底字段代替 |

# Schema 准入与字段冻结结论

## 1. 哪些字段现在可以进入 Schema

结论分三层，避免把“当前存在”“语义可评审”和“候选职责可讨论”误报为同一成熟度，更避免把其中任何一层误报为已获准改 Contract。

### 1.1 当前共享 Schema

**本轮没有任何新增字段可以直接加入当前共享 Schema。** 原因不是样本不足，而是尚未同时完成对象物理所有权、消费者原型、迁移、错误模型、版本兼容和端到端测试。本报告也没有修改 Schema。

当前 `module-content.schema.json` 中已有的字段仍按第 1 节基线继续工作；其消费事实必须逐字段核对，不能由“当前必填”推断 Runtime 已使用。例如 `world_ref` 当前只提供待迁移的非空身份输入，并未形成 Provider 解析链。“继续存在于 v1”不表示这些字段都是目标模型的最终形态。尤其 `mvp_check_result`、多套事实字符串、任意 `path` 和 WinCondition 命名不能被当作新设计依据。

### 1.2 可以进入下一轮 Schema 设计评审的语义

下列字段的**单项语义职责**达到 Current 或 Review-ready，可以进入下一轮正式字段规格评审；在评审完成前仍不得直接落 Schema。这里不提升其父对象或执行链：例如 `ResolutionResultBinding.outcome_ref` 的引用职责可评审，不代表 `result_bindings` 的集合形态已冻结。

| 可提交评审的字段职责 | 进入 Specified 前仍须决定 |
|---|---|
| `ModuleIdentity.module_id`, `content_version`, `title` | 扁平兼容还是聚合；`version` 的 wire migration |
| `ContentUnit.content_unit_id`, `name` | Scene→ContentUnit migration；Unit 所有权 |
| `EntityDefinition.entity_id`, `name`, `aliases`, `player_description` | 可见性拆分和当前 `content` migration |
| `InformationItem.information_id`, `statement` | definition 的物理所有权与原子化政策 |
| `ResolutionResultBinding.outcome_ref` | 父集合 `result_bindings` 的物理形态、Result catalog 与 Outcome scope |
| `OutcomeDefinition.ordered_effects`, `narration_guidance` | Effect transaction contract；显式 no-op Outcome 的审阅协议 |
| `RuleDefinition.rule_id`, `ordered_effects` | Hook／scope／predicate 迁移与 Effect transaction contract |
| `EndingDefinition.ending_id` | Ending 所有权、激活路线与 WinCondition migration |

“进入设计评审”只表示可以正式写字段规格，不表示现在已有 Runtime 支持；若所在执行链仍含 Candidate／OPEN 字段，整条能力继续按最弱环节处理。

### 1.3 只能进入语义确认、尚不能进入字段规格评审的候选职责

下列职责有样本或迁移依据，但仍是 Candidate。团队可以确认“是否由该对象负责”，不能据此冻结字段名、类型、基数或序列化形态：

| 候选字段职责 | 先决问题 |
|---|---|
| `ModuleIdentity.ruleset_ref` | Provider／Ruleset 引用解析、版本兼容和 `world_ref` migration |
| `ContentUnit.player_content`, `entity_refs` | Player／Keeper 内容分区；Scene.content migration；参与对象首次／重复进入初始化及 GameState placement 边界 |
| `EntityDefinition.keeper_context` | 与 InformationItem 的去重政策及受控 Host Context |
| `InformationAcquisition.acquisition_id`, `information_ref`, source relation | 独立对象、内嵌关系或编译索引，以及 Knowledge Runtime |
| `InteractionDefinition.action_concept` | Action／Intent catalog 和上下文引用方向 |
| `ResolutionDefinition.result_bindings` | Resolver result catalog、集合基数与 binding 物理形态 |
| `OutcomeDefinition.outcome_id`, `player_feedback` | ID scope、即时反馈与持久知识边界 |
| `RuleDefinition.trigger`, optional `condition`, `priority` | Hook／predicate catalog、Dispatcher、scope 与冲突协议 |
| `Effect.operation_ref`, `information_acquisition_ref` | Operation catalog、类型化目标与 Knowledge transaction |
| Ending activation route：`EndingDefinition.activation_trigger` 或 inbound `Effect.ending_ref` 至少一项 | Hook／Operation catalog、静态 inbound 引用校验、双路线并存时的幂等协议 |
| `EndingDefinition.terminal_outcome` | Ending 激活、termination transaction 及 Outcome scope |

这些候选职责均不能进入当前 Schema，也不应在 Specified 文档中伪装成已冻结字段。

## 2. 仍然不能冻结的字段与决策

以下项目不能通过命名技巧提前冻结：

1. ModuleContent 下 Definition 的物理集合／内嵌／索引布局。
2. EntryPoint 是否独立、每模组／每角色的入口基数及 ContentGraph 根；EntrySelection、EntryPoint-selected Hook、Rule source／scope、授予 Effect、Acquisition recipient 与首个 Projection 的事务顺序必须由同一原型决定。
3. `ContentUnit.unit_type`、`ContentRelation.relation_type` 和关系 ID 的完整政策。
4. ContentUnit ↔ Interaction 的可编辑关系权威、多上下文／Encounter 复用基数和 Compiler 反向索引。
5. `EntityDefinition.entity_categories` 的值域／基数、Ruleset profile subtype 与类型化初始状态槽。
6. Location 空间关系的所有权、方向、隐藏／发现状态、条件边，以及 SpatialLink 与 ContentRelation 的去重政策。
7. Information kind、information relation、disclosure policy 和 recipient policy 值域。
8. InformationAcquisition 的独立／嵌入形式与 source role catalog。
9. Interaction 允许零个、一个还是多个 target；目标类型全集与 target role。
10. Resolution mode 全集、Resolver 引用协议、Check subtype 的 skill／difficulty 字段形态。
11. Condition predicate 全集、typed subject 空间和复合 Condition 能力。
12. Effect／Operation 完整 catalog、状态事务、动作许可／Action Gate 协议和 Ruleset effect 调用。
13. RuleScope 数量、组合语义、索引方式与 conflict policy。
14. 一个模组结构化 Ending 的数量、termination scope、EndingState 基数、classification 和 precedence。
15. Timeline 的 clock basis／unit／推进／重复／错过政策。
16. Track 的 measure、派生查询、转换与阶段披露政策；不得假定通用 `state_change` 已覆盖 Track，Operation 如何寻址 Track 实例／Transition 仍未确定。
17. Encounter driver、driver-specific binding、参与选择器、局部 Outcome／EndRule 基数与并发结束政策；`context_refs` 和 `availability_condition` 都不是启动边，唯一启动 Hook／Operation、目标引用和幂等政策仍未确定。
18. CharacterTemplate kind、role、Ruleset profile、构建绑定与可编辑政策。

跨对象执行能力按最弱环节准入。即使单个字段已达到 Review-ready，只要 Trigger source、RuleScope、Effect operation、目标引用、状态事务或 Projection 中任一环仍为 OPEN，整条能力就不能标为可执行 Supported；仅做内容保真时必须明确采用 Manual／Narrative Profile。

## 3. 需要 Runtime 原型验证的字段

| 原型 | 必须验证的字段／行为 | 通过标准 |
|---|---|---|
| Definition Loader + 版本迁移 | `ModuleContent.identity`、稳定 ID、旧 Scene／Entity／Checkpoint 引用迁移 | 旧存档／Event 可诊断迁移；无双身份、无静默重绑 |
| Entry bootstrap transaction | `EntryPoint.availability_condition`, EntrySelection, `start_content_unit_ref`, EntryPoint-selected Hook, Rule source／scope, grant-information Effect, Acquisition recipient, KnowledgeState, 首个 Projection | 一次事务完成每局或每角色入口选择、内容初始化、唯一 Hook、唯一授予 Event 和安全首屏；重试幂等；初始持久信息不能从 EntryPoint／CharacterTemplate 直写 KnowledgeState |
| Content navigation | `ContentGraph.content_units`, `content_relations`, `EntryPoint.start_content_unit_ref`, relation activation | 可达性确定；静态图不被回写；Effect 激活状态有 Event |
| Content participant initialization | `ContentUnit.entity_refs`、Unit 首次进入／重复进入／存档恢复、Entity presence／location state | 当前 Scene 投影与目标候选可无损迁移；仅静态参与者用于初始化，纯提及不生成 presence；已有 GameState 永不被静态引用覆盖 |
| Interaction context ownership | `ContentUnit.interaction_refs`、一个 Interaction 跨多 Unit 复用、Encounter-only 与 Unit+Encounter 上下文、反向索引 | 只有一个可编辑关系权威；反向关系由 Compiler 生成；当前上下文与 availability 共同决定候选，无双写漂移或定义复制 |
| Location／Spatial navigation | `ContentUnit.location_refs`, `LocationDefinition.parent_location_ref`, `spatial_links`、隐藏／发现、角色当前位置、条件出口 | ContentRelation 与 SpatialLink 不双写；当前位置／已发现路线只在 GameState；同一 Location 可承载多个 Unit；未发现地点不经 Projection／Host 泄露 |
| Knowledge Runtime | `InformationItem`, `InformationAcquisition`, `recipient_policy`、重复授予、遗忘／已知状态 | 所有授予只走 Outcome／Rule → Effect → Acquisition；角色级与全队投影不越权 |
| Interaction Router | `InteractionDefinition.action_concept`, `target_refs`, `availability_condition`; `InteractionTargetRef.target_role` | 玩家意图能映射到唯一受控 Interaction 或明确拒绝／裁量 |
| Resolution | `ResolutionDefinition.mode`, `resolver_ref`, `result_bindings`, `skill_option_refs`, `difficulty_ref` | Resolver 只返回 catalog key；每个 key 有确定 Outcome |
| Rule Dispatcher | `RuleDefinition.trigger`, `scope_refs`, `condition`, `priority`, `conflict_policy` | 监听、索引、求值和同时触发行为确定且可审计 |
| Effect transaction | `Effect.operation_ref`, `OutcomeDefinition.ordered_effects`, `RuleDefinition.ordered_effects`、失败／回滚、`state_change` | 无部分静默提交；每项 StateChange／Event 可追踪到定义 |
| Action Gate + decision presentation | `Effect.action_authorization`、受控 ActionRequest／ActionDecision、同批冲突，以及拒绝原因的受众安全呈现协议 | allow／deny 只影响本次注册动作判定；不产生隐式持久 policy，不与 Interaction availability 混责；自动 Rule 的即时原因无需伪造 Outcome，也不经 Rule／Effect 文本旁路 |
| Ending Runtime | `activation_trigger`, `activation_condition`, `Effect.ending_ref`, `termination_scope`, `precedence` | 只发生一次受控 termination；同时命中政策明确 |
| Entity state Loader | `EntityDefinition.ruleset_profile_refs`, `initial_state` | 只复制初值到 GameState，不回写静态定义 |
| Timeline Scheduler | `Timeline.clock_binding`, `ClockBinding.advance_hook_ref`, `TimelineEntry.repeat_spec`, `missed_policy` | reload／跳时／重复调度确定且不重复漏发 |
| Track mutation transaction | 类型化 Track 实例目标、modify／set／transition 语义、Transition 引用、合法域、跨阶段 Hook、Event | Effect 不用任意 path 修改 Track；非法转换原子拒绝；值与阶段同事务提交；stage leave／enter Hook 次数和顺序确定；转换可追踪到定义；`to_stage_ref` 是否足以确定具体值有唯一答案 |
| Encounter activation／Orchestrator | 唯一启动 Operation／Hook、Encounter target、`availability_condition`, `context_refs`, `participant_slots`, `driver_ref`, `interaction_refs`, `outcome_definitions`, `end_rules`, `end_conflict_policy` | context 不会自行启动；守卫通过后只创建一个 EncounterState／Started Event；EndRule 只选择父 Encounter 拥有的局部 Outcome；失败无部分状态；重复请求按明确政策拒绝或幂等；至少一个具体 driver 端到端支持 |
| Character Setup Loader | `CharacterTemplate.template_kind`, `role_association`, `ruleset_profile_ref`, `build_bindings`; `EntryPoint.eligible_character_template_refs` | 生成 CharacterInstance，静态模板不被运行修改；选择基数、互斥、席位 assignment 和“缺失 eligibility”的语义确定 |

## 4. 需要 Host Agent 原型验证的字段

| 原型问题 | 涉及字段 | 需要证明 |
|---|---|---|
| 全局与局部上下文预算 | `ModuleFrame.summary`, `keeper_background`, `keeper_guidance`; `ContentUnit.keeper_guidance`; `EntityDefinition.keeper_context` | Host 获得足够信息且不会把全文或秘密无界注入 |
| EntryPoint／HO 初始信息 | `EntryPoint.player_introduction`; EntryPoint-selected Trigger; `Effect.information_acquisition_ref`; `InformationAcquisition.recipient_policy` | Host 只直接展示安全 introduction；持久 HO 信息必须等统一授予链完成后从 Projection 获得，不能从 Keeper Context 旁路告知 |
| 动作语义与话术分责 | `action_concept`, `player_prompt` | Host 能从自然语言意图找到受控动作，提示不被当执行命令 |
| Action Gate 拒绝反馈 | 受控 ActionDecision／Notification 呈现协议；现行 `blocked_text`／Rule 即时话术迁移 | Host 只能呈现 Runtime 已判定且通过受众审查的原因；协议未成立时兼容文本不进入 Rule／Effect，也不伪造 Outcome |
| 交互上下文发现 | `ContentUnit.interaction_refs`, `EncounterDefinition.interaction_refs`, `InteractionDefinition.availability_condition` | Host 只经唯一权威关系或 Compiler 索引取得候选；跨上下文复用不复制 Interaction |
| 开放／无检定 Interaction | `InteractionDefinition.resolution`, `keeper_guidance`, `outcome_definitions` | 无封闭解析时 Host 能明确走人工裁量而非伪造 Check |
| Keeper adjudication | `ResolutionDefinition.adjudication_guidance`, `result_bindings` | Host 只返回已声明 result key，不生成任意 Effect |
| 多目标语义 | `InteractionDefinition.target_refs`; `InteractionTargetRef.target_role` | instrument、subject、recipient 等角色可稳定路由 |
| 即时反馈与持久知识 | `OutcomeDefinition.player_feedback`; `InformationItem.statement`; `InformationAcquisition` | Host 不用反馈旁路授予持久 Fact |
| 可见性隔离 | disclosure policy、recipient policy、player premise／brief | Host 只读 Projection／受控 Keeper Context，不泄露其他 HO／隐藏 Ending |
| Location 安全上下文 | `LocationDefinition.player_description`, `keeper_context`, `spatial_links`; `ContentUnit.location_refs` | Host 只获得当前 Projection 允许的地点描述和已发现连接，不根据完整拓扑泄露隐藏地点／出口 |
| 叙事约束 | Outcome narration guidance、Keeper guidance | 指导能改善叙述且不会形成第二套规则系统 |
| Timeline／Track／Encounter 手动 Profile | 各 Capability guidance／presentation 及受控 Decision 请求 | Host 可请求已注册的推进／转换／启动决策，但不能直写 ClockState／TrackState／EncounterState；无对应操作时只能叙事保真并显式显示 Capability Gap |
| CharacterTemplate 选择 | `CharacterTemplate.label`, `player_description`, `role_association`; `EntryPoint.eligible_character_template_refs` | 角色级信息和入口关系不会因模板展示而泄露；选择基数、互斥和 assignment 有唯一权威 |

# 与当前 ModuleContent v1 的冲突与迁移

| 当前形态 | 目标冲突 | 迁移要求 |
|---|---|---|
| `module_id/version/world_ref` 平铺 | 目标归 ModuleIdentity；`world_ref` 语义需澄清为 Ruleset provider | major migration 中一次性映射，不能同时维护两套权威 |
| 以 `scenes[0]`、数组顺序或首个 Checkpoint 推断入口 | 排版位置不等于 EntryPoint 或每角色 HO 选择 | 只有原文／Editor 决议能确定入口与起始 Unit；无法确定时保留 Narrative Profile。初始玩家文本逐项拆为安全 `player_introduction` 或 Information + Acquisition + Rule Effect，禁止入口直接授予 |
| `scenes` | Scene 混合内容段、呈现与交互反向索引 | 迁为 ContentGraph／ContentUnit；无导航 consumer 时仍可保留叙事，不强造图 |
| `Scene.entity_ids` | 当前列表同时影响场景投影和动作目标，不等于“仅相关对象”引用 | 只把明确出场／可交互／直接参与者迁为 `ContentUnit.entity_refs`；纯提及留在叙事／Information。Loader 必须原型化首次进入、重复进入和存档恢复的初始 placement 规则；现有 GameState 一旦存在，静态引用不得覆盖在场／离场状态 |
| `Scene.checkpoint_ids` + `Checkpoint.scene_id` | 双向关系可能漂移 | 迁移前先校验两侧一致；冲突时阻断并定位，不静默任选。Profile 必须声明唯一可编辑权威，另一方向只生成 Compiler 索引；保留 Checkpoint 稳定身份，不自动跨 Scene 合并，多上下文复用须经 Review |
| `Scene.content` | 玩家内容、Keeper 指导和原子信息混在一起 | 按受众拆到 Unit narrative／guidance；只有需引用的 Fact 原子化 |
| `entities` + `Entity.kind` | 通用实体类别与 Ruleset profile／Location 边界未分 | 保留共享身份；Location 空间能力独立；专用算法走 Ruleset |
| `Entity.kind="location"` | 简单复制会产生 Entity 与 Location 两个可写身份 | 建立稳定旧 ID → 新 Location ID 映射并原子重写 Unit、Interaction、RuleScope 引用；地点叙事／空间职责进入 Location，发现／占用／门锁进 GameState。兼具对象行为时须人工决定保留单一可交互 Location 或显式拆分并建立关系 |
| `Entity.content/secrets` | 叙事、秘密和事实存在多权威源 | 玩家描述、Keeper context、InformationItem 按职责迁移 |
| `Entity.state` | 无约束静态字典与当前状态边界不清，也可能被误认成 Track | 只迁已声明类型化初值；当前状态进 GameState。仅在原文明确量值、初值、合法域／阶段且 Track consumer 已获准时生成 Track 候选；旧 modify 必须解析成类型化 Track Operation，否则保留兼容语义或记录 Gap |
| `refuse_ops/blocked_text` | 默认动作门禁、条件许可和叙事拒绝混合 | 静态可用性走 Interaction／Condition，条件判定走 Rule／`action_authorization` Effect；只有明确 Interaction Outcome 拥有的话术才进 `player_feedback`，自动拒绝原因由兼容 adapter 保真并记录 ActionDecision／Notification Gap |
| `direct_responses` | 无检定交互成为 Entity 专用旁路 | 迁到统一 Interaction／Resolution／Outcome 或保留非执行 guidance |
| Entity 内嵌 `rules` | 存储位置暗示 scope | 建立显式 RuleScope 候选并人工审阅 |
| `Rule.hook/when/then` | Trigger、Condition、Effects 尚未分责 | 分别迁移；`then` 保持有序 |
| `Condition.path/equals` | 当前可校验 path 是否指向已声明 `Entity.state` key，但仍是缺少静态类型与谓词协议的字符串路径 | equals 可映射 predicate；path 必须解析为 typed subject，否则 Gap |
| `Rule.facts` | 当前可能混合执行确认、状态断言和持久信息，语义不能一刀切 | 执行确认进入 Event／状态投影；持久可知内容才走 Acquisition；逐项 Review |
| `Rule.player_visible_information` | 即时反馈与持久知识混合，并形成直出旁路 | 持久知识走 Acquisition；可归属 Interaction Outcome 的即时话术进入其 `player_feedback`；其余自动 Rule 话术在 ActionDecision／Notification consumer 成立前由兼容 adapter 保真并记录 Gap，不新增 Rule／Effect 文本字段 |
| `Checkpoint` 强制 scene／target／skills／difficulty | Interaction、上下文、目标、Check Resolution 混在一起 | 拆职责；支持无目标、无检定、Direct 和 Keeper Adjudication |
| Scene 标题含“战斗／追逐／高潮” | 标题词面不能证明统一 Encounter driver | 仅在具体 driver、参与槽、唯一启动路径和结束政策全部确定时迁为自动 Encounter；否则继续使用 ContentUnit + Interaction + Keeper Guidance |
| `mvp_check_result` | 测试控制进入内容定义 | 从 ModuleContent 删除，改为 Test Fixture／注入 Resolver |
| `Checkpoint.outcomes.success/failure` | 固定二元而 Ruleset 可有多结果 | 迁为 `ResolutionDefinition.result_bindings` + `InteractionDefinition.outcome_definitions` |
| Outcome 的 `facts/player_visible_information/narration_constraints/ops` | 信息、反馈、叙事和执行混合 | 分别迁为 Acquisition chain、`OutcomeDefinition.player_feedback`、`narration_guidance`、`ordered_effects` |
| `win_conditions` | 名称预设胜利，且 trigger／condition／terminal outcome 混合 | 迁为 EndingDefinition；不默认二元胜负；scope／precedence 保持 OPEN |
| 当前 Outcome 的空 tuple 或空字符串 | 当前 Contract 允许 no-op 分支；目标限制若更严会造成破坏性迁移 | 保留可审阅的显式 no-op Outcome；不得由 Compiler 虚构反馈或 Effect |
| 当前 `Rule.then=()`，可能同时含 `facts/player_visible_information` | 目标可执行 Rule 要求 Effect，但当前空 `then` 不一定等于可删除 | 先按 Event／状态确认、持久信息、即时反馈逐项分类；若仍无可执行 Effect，不虚构 Effect，也不静默丢弃，须由兼容 adapter 保留或经 Review 明确弃用并记录迁移诊断 |
| 顶层必填但可为空的 collections | 字段存在或空集合不证明对应能力真正 Supported | 发布 Profile 必须单独声明能力支持；Validation 不得把空集合当能力证据 |
| frozen Contract 中的 `Entity.state` 可变 dict | 外层 frozen 不提供深不可变保证 | 目标初值必须是深不可变、类型化值；Loader 复制到 GameState，禁止共享可变引用 |

迁移期间不能让旧字段和新字段同时可写。可采用只读兼容 adapter 或一次性 Compiler migration，但必须指定唯一权威方向、弃用版本和冲突错误。

# 关键所有权复核

| 问题 | 结论 |
|---|---|
| 为什么 `title` 属于 ModuleIdentity，而不是 ModuleFrame | title 用于人类识别同一模组；修改故事摘要不应改变身份。Frame 只描述“故事是什么”。 |
| 为什么 `summary` 属于 ModuleFrame，而不是 ContentUnit | summary 跨越整个模组，不是某个可寻址内容段；它也不能成为原子 Fact 的权威源。 |
| 为什么 `disclosure_policy` 属于 InformationItem，而不是 Projection | ModuleContent 声明静态披露上界；Projection 结合 KnowledgeState 和请求者计算这一次真正可见的结果。 |
| 为什么来源属于 InformationAcquisition，而不是 InformationItem | 同一信息可有多个来源；把来源塞入本体会复制 Item 或丢失多路径。 |
| 为什么 Check 字段属于 Resolution，而不是 Interaction 根 | Interaction 的共同本质是可尝试动作；Check 只是得到结果的一种策略。 |
| 为什么 `ordered_effects` 属于 Outcome／Rule，而不是 Resolution | Resolution 只选择结果；Outcome／Rule 声明选中或成立后发生什么。 |
| 为什么 Rule 直接拥有 Effect，不拥有 Outcome | Rule 的语义是 Hook 上的自动反应，不是玩家交互的一次分支解析。 |
| 为什么终止范围属于 Ending，而不是 RuleScope | RuleScope 决定规则在哪个上下文适用；termination scope 决定谁进入 ended。 |
| 为什么 Location 不能总是 Entity | 可共享名字／引用能力，但空间层级、出口和当前位置具有不同消费者与状态模型。 |
| 为什么 Encounter context／availability 不能承担启动 | context 只描述静态所在位置，availability 只作纯守卫；启动必须经过唯一注册 Operation／Hook，并原子创建 EncounterState／Event。 |
| 为什么 EncounterEndRule 只引用父 Encounter 的 Outcome | 局部结束结果必须有唯一 owner；父 Encounter 拥有 `outcome_definitions`，EndRule 只做 Condition→Outcome 选择，既不复制 Effect，也不借用 Interaction 私有结果或 Module Ending。 |
| 为什么 ContentUnit 与 Interaction 只能有一个关系权威 | 双向可编辑会重现 Scene／Checkpoint 漂移；另一方向只能由 Compiler 建索引，多上下文复用由权威关系表达。 |
| 为什么 TimelineEntry 不拥有 Effects | 到期应发出 Trigger；所有机器后果继续走 Rule → Effect，避免第二套执行语言。 |
| 为什么 TrackStage 不拥有 Effects | 阶段进入／离开产生 Hook；Rule 是阶段后果的唯一权威。 |
| 为什么 EntryPoint／CharacterTemplate 不直接拥有初始信息授予列表 | 入口选择发出 Trigger，Rule Effect 激活 Acquisition；直接列表会绕过唯一信息授予链。 |

# 最终结论

根据 15 个样本统计与既有领域模型，ModuleContent 的字段目录应围绕以下稳定职责展开：

```text
Identity
+ Frame
+ ContentGraph(ContentUnit, ContentRelation)
+ referenced Definitions
   (Entity, Information, Interaction, Rule, Ending)
+ optional Capability Definitions
   (Location, Timeline, Track, Encounter, CharacterTemplate)
```

这不是顶层字段清单。十项 15/15 最低表达范围被归并为身份、框架、内容、参与对象、信息与获得路径、交互解析及结果、规则反应和终局；没有把十项逐一映射成十个一级数组。

随机表、势力反应和跨模组组合也没有因低频而消失：它们以 Deferred Capability Gap 保留，但在专用消费者成立前不产生 ModuleContent 字段。

当前可执行结论是：

1. 保持现行 v1 Schema／Contract 不变。
2. 第 1.2 节的 Current／Review-ready 单项职责可进入正式字段评审；第 1.3 节的 Candidate 只做对象归属和职责确认，不冻结字段名、类型、基数或物理形态。
3. 在 Runtime／Projection／Host／Ruleset 原型前，不冻结状态为 OPEN 的 catalog、基数或可选 Capability 执行字段。
4. 不可执行的自然语言继续由 Narrative／Keeper Guidance 保真，并在影响正确运行时记录 Capability Gap。
5. 只有完成 Producer、Consumer、Validation、迁移和 E2E 的字段，才能从本 Field Catalog 进入正式 Schema。

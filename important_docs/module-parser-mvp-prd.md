# Module Parser MVP PRD

> 状态：Draft v0.1
> 日期：2026-07-22
> 产品主责：成员 C
> 适用范围：Module Parser 产品目标与 MVP 范围
> 当前可执行 Schema 权威：`agent-collaboration-framework/collaboration_framework/contracts/module.py`

## 1. 文档目的

本文定义 Module Parser 的用户价值、产品流程、MVP 范围、验收方式和阶段边界，用于指导需求排序与验收。

本文回答“为什么做、给谁用、第一版做到什么程度”。本文不重新设计 `ModuleContent`，不替代共享 Contract、技术 Pipeline 或架构 ADR。

### 1.1 文档权威关系

| 文档/代码 | 回答的问题 | 权威范围 |
|---|---|---|
| 本 PRD | 为什么做、用户流程、MVP 范围、验收标准 | 产品范围权威 |
| `contracts/module.py` | Runtime 当前允许接收什么字段 | 当前唯一可执行 Schema 权威 |
| `module-parser-contract-rfc.md` | 契约演进候选与跨团队决策 | RFC，不代表已实现能力 |
| `module-parser-pipeline.md` | Module Parser 完整目标流程 | 技术目标设计 |
| `module-content-capability-matrix.md` | Contract、Validation、Runtime 和测试实际证明了什么 | 当前能力事实基线 |
| 架构 ADR | 为什么选择某个 SDK、接口或编排方式 | 已批准技术决策 |

发生冲突时，当前代码行为以 `contracts/module.py` 和自动化测试为准；产品范围冲突回到本 PRD 评审，不在实现中自行扩展 Schema。

## 2. 背景与问题

Runtime 只能消费严格、可引用且可执行的 `ModuleContent`。目前可运行模组主要依靠开发者人工把原文改写成 JSON，存在以下问题：

- 转写成本高，难以规模化导入较长模组；
- Scene、Entity、Checkpoint、Rule 和 WinCondition 容易遗漏或错误关联；
- 原文依据没有稳定定位，字段存疑时难以回查；
- 结构正确不等于忠于原文，秘密泄漏、成功/失败结果颠倒等问题无法由 Schema 发现；
- 当前 Contract 无法表达的机制可能在导入时被静默丢弃。

Module Parser 的产品目标是把“人工手写 Runtime JSON”变为“机器辅助编译 + 确定性校验 + 语义审查 + 明确发布决策”。

## 3. 产品目标

用户提交一个受支持的模组文件后，系统应生成：

1. 可追溯的结构化解析候选；
2. 确定性的 Validation 结果；
3. LLM Review 结果；
4. 对当前 Contract 无法表达内容的明确缺口报告；
5. 经发布策略允许后，可被 Runtime 加载的规范化 `ModuleContent` JSON。

目标链路：

```text
PDF / DOCX / Markdown / TXT
→ DocumentAdapter（确定性）
→ NormalizedDocument / SourceFragment[]
→ Parser Pass（LLM）
→ ModuleDraft（Parser 私有）
→ Validation（确定性）
→ Review Pass（LLM）
→ Approval Policy（TBD）
→ ModuleContent
→ 规范化 JSON Publish
→ Runtime
```

## 4. 用户与使用场景

### 4.1 主要用户

| 用户 | 需求 |
|---|---|
| 模组导入者 | 上传模组并获得可运行结果，不手工编写完整 JSON |
| 内容审核者 | 查看来源、错误、遗漏风险和能力缺口，决定是否接受 |
| Module Parser 开发者 | 用稳定样例评测 Parser、Review 和文档转换质量 |
| Runtime/规则引擎开发者 | 只接收已通过边界的 `ModuleContent`，不依赖 Parser 私有对象 |

玩家不是 Module Parser MVP 的直接用户；玩家体验由 Runtime Keeper Agent 和客户端负责。

### 4.2 核心用户故事

- 作为模组导入者，我希望上传模组文件并看到明确的处理结果，而不是处理失败后只得到模型原始异常。
- 作为审核者，我希望每个关键结构都能回到页码、章节或段落来源。
- 作为审核者，我希望系统区分“Schema/引用错误”“疑似遗漏”“当前 Contract 不支持”。
- 作为 Runtime 开发者，我希望 Runtime 永远只依赖正式 `ModuleContent`。
- 作为 Parser 开发者，我希望使用固定黄金样例比较不同预处理方案、Prompt 和模型。

## 5. 已完成基线

以下能力已经存在，不作为新 Parser Agent 的重复开发内容：

- 当前 Phase 1 `ModuleContent` Contract；
- Parser 私有 `ModuleDraft`；
- `ModuleDraft → ValidationReport → ModuleContent` 确定性 Validation；
- 稳定 Validation 错误码；
- 规范化 JSON Publish；
- 已有 JSON 文件的 `读取 → Validation → Publish` 应用工作流；
- Publish 产物进入 Runtime，执行 Checkpoint、修改 EntityState、记录 Event 并命中 WinCondition 的闭环测试；
- 测试专用最小 Check Candidate Catalog 快照；
- ModuleContent Capability Matrix。

当前尚未存在真实的 LLM Parser Pass，因此“导入 JSON”不能被描述为“已经支持 PDF/Word 模组自动解析”。

## 6. MVP 范围

### 6.1 文件输入与预处理

MVP 必须建立统一 `DocumentAdapter` 边界，并将输入转换为稳定、可追溯的 `SourceFragment[]`。

支持等级：

| 输入类型 | MVP 目标 | 说明 |
|---|---|---|
| Markdown | 支持 | 保留标题和段落定位 |
| TXT | 支持 | 以稳定段落规则分片 |
| 文本型 PDF | 支持 | 首个黄金样例为《追书人》；保留页码与 block 顺序 |
| DOCX | 目标支持 | 是否纳入首个可交付版本由 Adapter Spike 确认 |
| 扫描型 PDF | 有限支持或明确拒绝 | 先建立 OCR 探测、warning 和失败策略 |
| 复杂双栏/图文 PDF | 有限支持 | 允许文字提取结合复杂页视觉输入，不承诺无损转换 |

预处理必须保留：

- 输入文件 SHA-256；
- MIME/格式；
- 转换器名称与版本；
- 页码、章节、段落或 block 定位；
- 原始文本；
- warnings；
- 可识别的图片/地图引用。

### 6.2 Parser Pass

MVP 使用一个 Module Parser Agent 内部的 Parser Pass，将 `SourceFragment[]` 转为 Parser 私有 `ModuleDraft`。

第一版只提取当前 Contract 可表达的顶层内容：

- `module_id`、`version`、`world_ref`；
- `Scene[]`；
- `Entity[]`；
- `Entity.rules[]`；
- `Checkpoint[]`；
- `WinCondition[]`。

Parser 必须遵守：

- 不得直接产生可供 Runtime 加载的发布物；
- 不得绕过 Validation；
- 不得把原文没有的机制当成事实补造；
- 关键字段必须能够关联来源；
- 不确定内容必须进入 unresolved questions 或等价私有元数据；
- 当前 Contract 不支持的 SanTrigger、Pregen、Asset、复杂 Expr 等进入 Capability Gap，不得静默塞入额外字段。

Parser 私有 provenance 的最终包装结构仍需 ADR 确认，但不得进入共享 `contracts/`。

### 6.3 Ruleset 只读数据

Parser/Validation 至少需要按 `world_ref` 获取只读 Ruleset Snapshot，用于识别属性和技能候选。

最小逻辑需求：

- Ruleset canonical ID/slug；
- version；
- Attribute：id、name、aliases、enabled；
- Skill：id、name、aliases、category、enabled、specialization/family；
- 统一 Check Candidate 的 `id` 与 `kind = attribute | skill`。

Module Parser 不直接依赖数据库、ORM 或具体 HTTP API。生产 Provider 与数据库映射尚待 Issue #91 确认；测试允许注入不可变最小 Snapshot。

### 6.4 Deterministic Validation

继续复用现有 Validation，不让 LLM 替代可证明的检查。

MVP 至少保证：

- Schema、必填字段、枚举和额外字段检查；
- 同类 ID 唯一性；
- Scene、Entity、Checkpoint 引用完整性；
- Checkpoint target/scene 关系；
- Rule/Operation/WinCondition 状态路径；
- Check Candidate 合法 ID（在 Catalog 可用时）；
- 一次返回完整问题集合；
- 稳定错误码，不直接暴露 Pydantic 原始异常。

Validation 成功是构造正式 `ModuleContent` 的必要条件，但不自动等同于语义审查通过。

### 6.5 LLM Review Pass

Review Pass 是 Module Parser Agent 的内部 LLM 阶段，不是独立一级 Agent。它在 Validation 通过后，对 Draft 与原文的一致性进行审查。

MVP Review 关注：

- Scene、Entity、Checkpoint、Rule、WinCondition 是否明显遗漏；
- 成功与失败结果是否颠倒；
- 玩家可见信息与秘密是否混淆；
- 是否存在无来源支持的推断；
- 来源引用是否支持对应字段；
- 当前 Contract 无法表达的机制是否被记录为 Capability Gap；
- 是否存在需要人工判断的 unresolved questions。

Review 输出应为 Parser 私有 `ReviewReport`，至少包括：

- `status`；
- `findings`；
- `severity`；
- 稳定 `code`；
- `draft_path`；
- `source_references`；
- `message`；
- `suggested_action`；
- `unresolved_questions`。

Review 不直接修改 Draft，不绕过 Validation，不直接操作 Runtime。

### 6.6 Approval 与 Publish

Publish 只接受正式 `ModuleContent`。规范化 JSON 必须能重新构造等价 `ModuleContent`，并能被 Runtime 加载。

以下发布策略尚未统一，MVP 开发前需形成 ADR：

- Option A：Validation + Review 通过后自动发布；
- Option B：Validation + Review 通过后要求人工确认；
- Option C：按质量层级发布，但清晰标记是否经过 Review/人工确认。

在决策完成前，LLM 生成的 Draft 默认不得无人工确认进入生产发布。现有人工 JSON 的 Phase 1 测试链路可继续直接使用 Validation → Publish。

## 7. 非目标

MVP 不实现：

- 修改当前 `contracts/module.py` 以加入 Phase 2 字段；
- 完整 Expr、Dice、SAN Resolver 或全部 Hook dispatcher；
- SanTrigger、Pregen、Asset 的正式 Runtime 模型；
- Parser 自动修改 Runtime 或 GameState；
- Parser 自动创建 Room 或初始化 EntityState；
- 自动修复所有 Validation/Review 问题；
- ApprovedModule、内容 Hash、Repository 和完整版本管理；
- 保证所有扫描件、双栏 PDF 和复杂地图都能无损转换；
- 多一级 Agent、Supervisor Agent 或自由自治的多 Agent 对话；
- 在没有评测证据时提前拆成 Multi-Pass Parser。

## 8. 技术边界与框架原则

产品流程由确定性 Python 编排，Agent SDK 只进入模型调用 Adapter：

```text
ModuleParserUseCase（Python）
├── DocumentAdapterPort
├── ParserModelPort
├── Validation
├── ReviewModelPort
├── ApprovalPolicy
└── Publish
```

当前候选决策：

- OpenAI Agents SDK：Parser/Review 模型 Adapter 的候选默认方案，便于与主持 Agent 技术栈保持一致；
- LangGraph：当前不引入；只有出现复杂循环、持久化状态、跨进程暂停恢复等明确需求时再评估；
- PydanticAI：保留为模型中立、结构化输出 Adapter 的对比候选；
- Validation、Publish、Runtime 不依赖任何 Agent SDK。

最终框架选择必须记录为 ADR，而不是由旧设计文档中的示例代码决定。

## 9. 用户流程与状态

### 9.1 正常流程

```text
uploaded
→ preprocessing
→ parsing
→ validating
→ reviewing
→ awaiting_approval / approved
→ published
```

### 9.2 异常结果

| 类型 | 示例 | 期望结果 |
|---|---|---|
| 预处理失败 | 文件不支持、文本为空、需要 OCR | 返回稳定错误码，不调用 Parser |
| Parser 输出不满足 Draft Schema | 缺字段、枚举错误、额外字段 | Schema Gate 拒绝；允许受限重试或进入 blocked |
| Validation 失败 | 悬空引用、未知状态路径 | `needs_revision`，不得发布 |
| Review 失败 | 明显遗漏、秘密泄漏、无来源推断 | `needs_revision` 或等待人工裁决 |
| Ruleset 不可用 | 无法确认技能/属性 ID | Demo 可用测试 Snapshot；生产策略为 TBD，默认不得静默通过 |
| 能力缺口 | 原文含 SAN 或复杂分支 | 写入 Capability Gap，不伪造为已支持能力 |

## 10. 验收标准

### 10.1 功能验收

- 支持的文件能够稳定转换为 `SourceFragment[]`；
- 同一文件重复预处理得到稳定 fragment ID 和来源定位；
- Parser 能输出严格的私有 `ModuleDraft`；
- Parser 输出必须经过现有 Validation；
- Validation 通过后构造正式 `ModuleContent`；
- Review 能输出结构化 `ReviewReport`，且不会直接修改 Draft；
- 发布 JSON 与发布前 `ModuleContent` 等价；
- Runtime 从 Publish 产物加载，而不是绕过发布读取 Parser 输出；
- 全流程不让 Runtime 依赖 `ModuleDraft`、`SourceFragment` 或 Agent SDK。

### 10.2 黄金样例验收

以《追书人》为首个 Parser Evaluation Golden Case，至少维护：

```text
parse-report.md
extraction-expectations.json
phase1-module-content.json
capability-gaps.md
```

评测指标：

- Scene、Entity/NPC、Checkpoint、Rule、WinCondition 召回率；
- 当前 Contract 字段准确率；
- 无来源推断数量；
- 来源引用准确率；
- Schema Gate 通过率；
- Validation 通过率与错误分布；
- Review 对人工已知错误的检出率；
- 相同输入多次运行的一致性；
- Token、延迟与失败重试次数。

首轮具体阈值需在人工黄金答案完成后设定，不在没有基线数据时虚构百分比。

### 10.3 回归验收

- 当前 Contract、Validation、Publish、Runtime 测试继续通过；
- 新增行为必须有单元测试或集成测试；
- 不修改 Runtime 语义来迁就 Parser 输出；
- Contract 无法表达的内容必须进入 Capability Gap 或阻断，不允许静默丢弃。

## 11. 里程碑

| 里程碑 | 交付物 | 完成条件 |
|---|---|---|
| M0 已完成 | Phase 1 人工 JSON 闭环 | Validation、Publish、Runtime 集成测试通过 |
| M1 产品与架构冻结 | PRD、Ruleset ADR、Parser 技术 ADR | 输入输出、Provider、SDK 边界与发布策略明确 |
| M2 Document Adapter | `NormalizedDocument`、`SourceFragment[]`、文本型 PDF Spike | 《追书人》文本完整、顺序和来源可核查 |
| M3 最小 Parser Pass | `ParserModelPort`、模型 Adapter、严格 Draft 输出 | 黄金样例产生第一份可校验 Draft |
| M4 Review Pass | `ReviewModelPort`、`ReviewReport`、错误样例 | 能检出预置遗漏/泄漏问题且不修改 Draft |
| M5 MVP 闭环 | 文件 → Parser → Validation → Review → Approval → Publish | 发布物可被 Runtime 加载并通过回归测试 |

## 12. 依赖与风险

| 风险/依赖 | 影响 | MVP 应对 |
|---|---|---|
| Ruleset Catalog 所有权未定 | 技能和属性无法生产级校验 | 测试 Snapshot 继续开发；生产发布策略默认保守 |
| `world_ref` 映射未定 | 无法选择正确 Ruleset | Issue #91 优先形成 ADR |
| 当前 Contract 表达能力有限 | 原文机制可能无法编译 | Capability Gap，不擅自扩 Schema |
| PDF 阅读顺序或 OCR 错误 | Parser 基于错误原文生成 Draft | SourceFragment 保留页码/block/warning，建立视觉 fallback |
| LLM 遗漏或编造 | 生成内容不忠于原文 | 来源约束、Validation、Review、黄金样例和发布门禁 |
| Review 与 Parser 同源偏差 | Review 可能重复 Parser 错误 | 人工预置缺陷集；必要时比较不同模型/Prompt |
| 文档之间存在历史冲突 | 开发者误把目标设计当成当前能力 | 使用本文的权威关系与 ADR 决策记录 |

## 13. 待决策事项

以下问题在对应实现前必须完成决策，但不阻塞无关的 Document Adapter 工作：

1. `world_ref="coc-7e"` 到 GameSystem/Ruleset 的稳定映射；
2. `spot-hidden`/`spot_hidden`、`STR`/`strength` 的 canonical ID 与 alias 策略；
3. RulesetSnapshot 的生产 Provider、版本与缺失策略；
4. OpenAI Agents SDK 是否作为团队统一模型运行层；
5. Parser 私有 provenance 使用 `ParserResult` 包装，还是与同形 `ModuleDraft` 并行存储；
6. Review Pass 的模型、稳定错误分类与失败降级策略；
7. LLM 解析结果是否必须人工确认才能生产发布；
8. 首版是否承诺 DOCX，扫描型 PDF 的支持等级如何标注；
9. Prompt、模型、Ruleset 和转换器版本如何记录进解析报告；
10. 黄金样例的人工答案与准确率阈值由谁批准。

## 14. 下一步

按以下顺序推进：

1. 评审本 PRD，确认 MVP 产品范围；
2. 完成 Issue #91 最小 Ruleset 边界；
3. 形成 Module Parser 技术 ADR；
4. 将 Issue #98 收敛为《追书人》黄金样例；
5. 实现文本型 PDF → `SourceFragment[]` Spike；
6. 实现最小 Parser Agent Adapter；
7. 接入现有 Validation，并基于真实错误实现 Review Pass；
8. 确认 Approval Policy 后完成文件导入 MVP 闭环。

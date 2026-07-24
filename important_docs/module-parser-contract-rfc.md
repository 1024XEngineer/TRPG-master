# Module Parser Contract RFC

> 类型：RFC（Request for Comments）
> 日期：2026-07-17（对齐 codex/agent-collaboration-aligned 架构）
> 定位：Module Parser Agent 的 Stage IO Contract 与 ModuleContent 数据契约
> 消费者：成员 B（确定性引擎，消费 ModuleContent）
> 生产者：成员 C（Module Parser Agent）
>
> **框架对齐说明**：本文档同时记录“Current Contract（Phase 1）”与“Target Contract（Phase 2）”。Phase 1 的唯一可执行权威是当前 `contracts/module.py`；Phase 2 字段只有在 B/C 共同评审、实现并升级 `schema_version` 后才可进入发布物。`ModuleDraft`、`ValidationReport`、`ReviewReport` 是 C 私有模型，应定义在 `module/` 目录，不进入 `contracts/`。

---

## 〇、文档约定

本文档定义 Module Parser Agent 的**外部契约**——每个阶段的输入输出对象、ModuleContent 的字段语义、以及 Runtime 如何消费这些数据。内部实现（Prompt 设计、代码组织、校验算法）不在本文范围。

**术语对齐**：

| 术语 | 定义 |
|------|------|
| ModulePack | 数据库中的发布元数据（title, authors, version, players_min/max）。不直接被 Runtime 加载。 |
| ModuleContent | Runtime 实际加载的完整模组数据。包含 scenes, entities, checkpoints, win_conditions 等。 |
| ModuleDraft | Parser Pass 通过结构 Schema Gate 后的候选内容。携带来源、置信度和未解决问题；不可被 Runtime 加载。 |
| ValidationReport | Validation 阶段的产物。errors 阻断，warnings 提醒。确定性代码生成。 |
| ReviewReport | Review Pass 的产物。包含 A/B/C/D 覆盖度评估和 human_review_checklist。LLM 生成。 |
| ApprovedModule | 通过全部质量门（或显式接受 warnings）的 ModuleContent。版本化、不可变。 |

### 契约版本与范围矩阵

本文档采用“当前可执行基线 + 显式版本扩展”，不把尚未实现的目标字段描述为当前能力。

| 能力 | Current Contract / Phase 1（隐式 `1.0`） | Target Contract / Phase 2（拟 `schema_version="2.0"`） |
|------|------|------|
| 权威来源 | 当前 `contracts/module.py` | B/C 共同评审后的新版 `contracts/module.py` |
| 输入 | 人工 `demo-module.json` | Markdown → SourceFragment → Parser Pass |
| ModuleContent 集合 | scenes, entities, checkpoints, win_conditions | 在 Phase 1 基础上增加 san_triggers；Pregen、Asset 仍需另行评审 |
| Entity.kind | `npc \| object \| location` | 默认保持 Phase 1；细分类型不在本 RFC 本轮冻结 |
| Condition | `{path, equals}` | 可升级为完整 Expr，但不在本 RFC 本轮冻结 |
| Operation | `allow \| modify` | 增加 `apply_san`，作为 SanTrigger 的唯一确定性执行入口 |
| Rule | 当前 `RuleSpec` | 沿用 Phase 1 结构；允许 `then` 使用 `apply_san` |
| Checkpoint | 当前 `CheckpointSpec` | 沿用 Phase 1 核心结构；可新增 hidden、roll_mode、priority |
| WinCondition | 条件满足即结束 | 仍只表达终局；非终局后果由 Rule + Operation 表达 |
| Pregen / Asset | 不支持 | 设计候选，未进入本轮 Target Contract |

**版本规则**：未进入对应版本 `ModuleContent` 顶层 schema 的对象，不得由 Parser 输出、不得通过 Validation、不得被 Runtime 假定存在。Phase 2 的实现不得静默改变 `schema_version="1.0"` 的字段语义。

---

## Part 1: Stage IO Contract

### 1.1 Preprocess

| 属性 | 值 |
|------|-----|
| Purpose | 将原始模组文件转换为干净的、结构化分段的文本，为 Parser Pass 提供可追溯的输入。 |
| Input | `RawDocument`（PDF/Markdown/TXT 文件路径 + SHA256 checksum） |
| Output | `SourceFragment[]`（分段的文本块列表） |
| Owner | 确定性代码（PyMuPDF + 分段算法） |
| LLM | 否 |
| Failure Strategy | 阻断。PDF 无法解析 → 报告错误，停止流水线。 |
| Persisted | 否。SourceFragment 是流水线内部对象，Parser Pass 完成后可丢弃。 |
| Runtime Visible | 否 |

**SourceFragment 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 稳定可引用的片段 ID，格式 `src_{chapter}_{page}_{seq}` |
| locator | string | 人类可读的定位信息，如"第三章 / 第12页 / 第5段" |
| text | string | 段落原文 |
| section | "keeper_info" \| "player_info" \| "unclassified" | 原文区域分类 |

**设计说明**：SourceFragment 的 ID 必须稳定——同一份 PDF 两次运行的 ID 必须相同。这是来源追溯的基础。LLM 不能做分段，因为 LLM 的输出不可复现。

---

### 1.2 Parser Pass

| 属性 | 值 |
|------|-----|
| Purpose | 从模组原文中提取结构化数据。单次 LLM 调用，输出 ModuleDraft。 |
| Input | `SourceFragment[]` + skill catalog + hook catalog + op catalog |
| Output | `ModuleDraft`（携带 source_references + confidence_scores + unresolved_questions） |
| Owner | Module Parser Agent（LLM 调用） |
| LLM | **是**。PydanticAI Agent，model: Claude Opus 4。 |
| Failure Strategy | LLM 调用失败 → 重试（最多 2 次）。重试仍失败 → 标记为 blocked，等待人工介入。Parser 输出不合法 JSON 或不满足 `ModuleContentDraft` 的结构 schema → Output Schema Gate 拒绝并打回 LLM 重试；失败输出不构成 ModuleDraft。 |
| Persisted | 否。ModuleDraft 是候选结构，不应进入 Content Repository。 |
| Runtime Visible | **禁止。** ModuleDraft 未通过 Validation，绝不可被 Runtime 加载。 |

**ModuleDraft 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| draft | `ModuleContentDraft` | 与当前 ModuleContent 字段同形且结构严格，但尚未执行跨引用/状态路径校验的候选内容 |
| source_references | `dict[str, tuple[str, ...]]` | 稳定字段路径 → 一个或多个 SourceFragment.id |
| confidence_scores | `dict[str, float]` | 字段路径 → 置信度（0.0-1.0） |
| unresolved_questions | `list[str]` | Parser 无法确定、需要人工介入的段落描述 |

**ModuleDraft 与 ModuleContent 的边界**：

```text
LLM 原始输出
  ↓ Output Schema Gate（JSON、必填字段、字段类型、枚举、extra=forbid）
失败：重试或 blocked，不产生 ModuleDraft
  ↓ 成功
ModuleDraft(draft=结构严格的 ModuleContentDraft + provenance)
  ↓ Validation（引用完整性 + 可确定的静态语义）
  ↓ 成功后构造正式 ModuleContent
  ↓ Review / Publish
ApprovedModule.content
```

`ModuleContentDraft` 不是宽松 `dict`：它仍严格检查字段类型、必填项、枚举和额外字段，只是不运行正式 `ModuleContent` 的跨引用 `model_validator`。因此 Draft 可以保留悬空引用和无效 state path，交由 Validation 形成完整的结构化报告。Validation 通过后，流水线必须使用同一份数据构造正式 `ModuleContent`；如果构造失败，视为 Validator 与共享契约不一致并阻断发布。Runtime 只能加载 Publish 产出的 `ApprovedModule.content`。

**硬约束**：
1. 原文不含的信息不得凭空补造
2. `Entity.secrets` 和 `Entity.public_persona`（如果模型支持）必须分离
3. Parser 不得因为"这样更好玩"而补造 Rule 或结局

---

### 1.3 Validation

| 属性 | 值 |
|------|-----|
| Purpose | 发现确定性的错误。所有错误在数学上可证明——不需要"理解"模组，只检查数据结构。 |
| Input | `ModuleDraft.draft`（已经 Output Schema Gate 构造成功的结构严格 `ModuleContentDraft`） |
| Output | `ValidationReport`（errors 阻断 + warnings 警告 + status） |
| Owner | 确定性代码。无 LLM。 |
| LLM | 否 |
| Failure Strategy | errors 不为空 → status = `needs_revision` 或 `blocked`，打回 Parser 或人工修订。warnings 仅为提醒，不阻断。 |
| Persisted | 否。但 ValidationReport 可在 Review Pass 和 Human Approval 中引用。 |
| Runtime Visible | 否 |

**ValidationReport 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| status | `"pass"` \| `"needs_revision"` \| `"blocked"` | pass: 无 error；needs_revision: 有 error 但可修；blocked: 缺少关键信息无法修 |
| errors | `list[ValidationIssue]` | 阻断项。必须修复才能进入 Review Pass。 |
| warnings | `list[ValidationIssue]` | 提醒项。可接受，但需要显式记录。 |

**ValidationIssue 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| severity | `"error"` \| `"warning"` | 严重级别 |
| code | string | 稳定错误码，如 `"scene.ref.entity_not_found"`。用于统计回归。 |
| path | string | 出错字段路径，如 `"scenes[0].entity_ids[2]"` |
| message | string | 人类可读的错误描述 |

**两道 Gate、三类检查**：

| 层级 | 检查内容 | 阻断？ | 示例 |
|------|---------|--------|------|
| Output Schema Gate（原 L1） | 字段类型、必填项、枚举值、额外字段拒绝；发生在 ModuleDraft 产生之前 | 阻断且不产生 ModuleDraft | `Entity.kind` 不在枚举中 |
| L2 Reference | 跨引用完整性：Scene→Entity、Checkpoint→target、Rule→State、WinCondition→State | 阻断 | Scene 引用了不存在的 entity_id |
| L3 Semantic | 未使用 state key、可由结构化 Condition/Operation 证明的可达性与冲突 | 默认警告；明确违反执行约束时阻断 | WinCondition 引用路径存在但没有任何 Operation 可写成目标值 |

ValidationReport 只报告 L2/L3。Output Schema Gate 的失败使用独立的 parser/schema error 记录，因为此时不存在合法 ModuleDraft。

---

### 1.4 Review Pass

| 属性 | 值 |
|------|-----|
| Purpose | 对已通过 Validation 的 ModuleDraft 进行语义审查——检测 Parser 无法自检的遗漏（B/C 类规则、秘密泄漏、过度结构化）。 |
| Input | `ModuleDraft` + 原始 `SourceFragment[]`（或原文） |
| Output | `ReviewReport`（errors + warnings + human_review_checklist + mechanism_abcd_coverage） |
| Owner | Module Parser Agent（LLM 调用） |
| LLM | **是**。PydanticAI Agent，model: Claude Sonnet 5。 |
| Failure Strategy | errors 不为空 → status = `needs_revision`，打回 Parser 或标记为待人工修订。LLM 调用失败 → 降级：标注"Review 未完成"，自动发布为 Layer 1。 |
| Persisted | 否。但 ReviewReport 应保留至 Human Approval 完成。 |
| Runtime Visible | 否 |

**ReviewReport 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| status | `"pass"` \| `"needs_revision"` \| `"blocked"` | 同 ValidationReport |
| errors | `list[ValidationIssue]` | 阻断项（如秘密泄漏到公开字段） |
| warnings | `list[ValidationIssue]` | 提醒项（如过度结构化） |
| human_review_checklist | `list[ChecklistItem]` | 需要人工逐条核查的 B/C 类遗漏提示 |
| mechanism_abcd_coverage | `dict[str, bool]` | A/B/C/D 四类机制是否都有示例 |

**ChecklistItem 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| category | `"A"` \| `"B"` \| `"C"` \| `"D"` \| `"hook_gap"` | 遗漏类型 |
| entity_id | string \| null | 关联的 Entity ID |
| question | string | 人工需要回答的问题，如"管家在玩家进入书房后是否必须主动开口？" |

---

### 1.5 Human Approval

| 属性 | 值 |
|------|-----|
| Purpose | 对 Review Pass 无法确定的问题做人工最终裁决。B/C 类遗漏 LLM 漏报率最高，需要人类的反事实想象能力兜底。 |
| Input | `ReviewReport`（特别是 human_review_checklist）+ 原始 `ModuleDraft` + 原文 |
| Output | Human Approval Decision：`批准` \| `打回` \| `有条件批准` |
| Owner | 人工审核员 |
| LLM | 否 |
| Failure Strategy | 打回 → 返回 Parser 或人工修订，重新跑 Validation + Review Pass。 |
| Persisted | 审批记录应持久化（谁、何时、批准了什么、接受了哪些 warnings）。 |
| Runtime Visible | 否（审批元数据不进入 Runtime） |

**质量分层**（Human Approval 是可选 Layer 3，不是发布前置条件）：

| 层级 | 触发条件 | 标注 | 体验 |
|------|---------|------|------|
| Layer 1 | Validation 通过 | "可运行" | 结构正确，能跑 |
| Layer 2 | + Review Pass 通过 | "AI 已审查" | B/C 遗漏率降低 |
| Layer 3 | + Human Approval 通过 | "人工认证" | 作者意图 100% 保留 |

---

### 1.6 Publish

| 属性 | 值 |
|------|-----|
| Purpose | 将通过质量门的 ModuleContent 版本化、冻结、交付给 Runtime。 |
| Input | `ModuleContent`（通过 Validation，可能也通过 Review Pass 和 Human Approval） + 质量标注 |
| Output | `ApprovedModule`（版本化的 ModuleContent + content_hash + 质量标注 + 冻结的 fixtures/evals） |
| Owner | 确定性代码 |
| LLM | 否 |
| Failure Strategy | 版本冲突（同 module_id + version 已存在）→ 拒绝，要求更新版本号。 |
| Persisted | **是。** ApprovedModule 存入 Content Repository，是 Runtime 加载的权威来源。 |
| Runtime Visible | **是。** 这是 Module Parser Agent 对外的唯一交付物。 |

**ApprovedModule 结构**：

| 字段 | 类型 | 说明 |
|------|------|------|
| content | `ModuleContent` | 通过质量门的完整模组数据 |
| version | string | 语义版本号（如 "1.0.0"） |
| content_hash | string | `ModuleContent` 序列化后的 SHA256 |
| quality_level | `"layer_1"` \| `"layer_2"` \| `"layer_3"` | 通过的最高质量层级 |
| approved_by | string \| null | Layer 3 时为审批人标识，Layer 1/2 为 null |
| frozen_fixtures | `list[string]` | 随此版本冻结的 fixture 文件列表 |

---

### 1.7 Stage IO 总览

```text
C 私有（module/）                        B/C 共享（contracts/module.py）
─────────────────────────                ─────────────────────────────

RawDocument                   外部输入，只读
    ↓ Preprocess
SourceFragment[]              C 私有，Parse 完成后可丢弃
    ↓ Parser Pass
ModuleDraft                   C 私有，不可进入 Runtime
    ↓ Validation
ValidationReport              C 私有，确定性代码生成
    ↓ Review Pass
ReviewReport                  C 私有，LLM 生成
    ↓ Human Approval
Human Approval Decision       审批记录，持久化
    ↓ Publish
ApprovedModule                对外交付物，持久化，Runtime 可加载
    ↓
ModuleContent                 B/C 共享契约（contracts/module.py）
                              被 B 消费执行规则
```

---

## Part 2: ModuleContent Contract

### 2.0 ModuleContent 顶层 Schema

**Phase 1 当前契约（可执行权威）**：

```python
class ModuleContent(ContractModel):
    module_id: str
    version: str
    world_ref: str
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]
```

以上与当前 `contracts/module.py` 一致。当前文件没有 `schema_version` 字段，本文将其内容形态记为“隐式 1.0”。正式增加版本字段需 B/C 共同评审；在此之前不得要求现有 fixture 提供该字段。

**Phase 2 目标扩展**：

```python
class ModuleContentV2(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    module_id: str
    version: str
    world_ref: str
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpecV2, ...]
    win_conditions: tuple[WinConditionSpec, ...]
    san_triggers: tuple[SanTriggerSpec, ...] = ()
```

`Pregen`、`Asset`、`public_persona`、`stats` 和完整 Expr 暂列设计候选，不属于本轮已冻结的 Phase 2 schema。所有集合使用 `tuple`，发布模型 `extra="forbid"`。

### 2.1 Scene

**Purpose**：描述游戏中的一个空间位置。Runtime 通过 Scene 确定当前玩家可以看到什么。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| name | string | 场景名称 |
| content | string | 场景的文学描述。自由文本，LLM 可演绎。 |

**Optional Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| entity_ids | `list[string]` | 本场景包含的 Entity ID 列表 |
| checkpoint_ids | `list[string]` | 本场景可触发的 Checkpoint ID 列表 |

**Runtime Usage**：

- ContextAssembler 根据当前 `Character.location` 加载对应 Scene，组装 `TurnContext.visible_entities` 和 `TurnContext.checkpoint_options`
- Scene.content 进入 Planner 和 Narrator 的上下文，作为场景氛围描述

**Initialization**：不参与。Scene 是静态内容。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| entity_ids | Entity.id | 确定场景中有哪些实体可见 |
| checkpoint_ids | Checkpoint.id | 确定场景中有哪些动作可用 |

**Lifecycle**：

```text
Parser 创建 → Validation 校验引用完整性 → Publish 固化 → Runtime 加载
```

---

### 2.2 Entity

**Purpose**：描述游戏世界中的一个可交互对象——NPC、怪物、物品、线索、动物、场景物体。Entity 是内容层最核心的模型：Rule 挂在 Entity 上，EntityState 由 Entity.state 初始化。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| kind | `"npc"` \| `"object"` \| `"location"` | Phase 1 当前实体类型；Phase 2 本轮不扩展 |
| name | string | 实体名称 |
| content | string | 玩家可见的表面描述。自由文本。 |

**Optional Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| secrets | string \| null | NPC 的真实底牌或隐藏信息。🔴 绝不可进入 Planner/Narrator 上下文。 |
| state | `dict[str, Primitive]` | D 类键的初始值。游戏开始时拷贝到 Room.entity_states。 |
| refuse_ops | `list[string]` | A 类：引擎必须拒绝的操作类型列表。 |
| blocked_text | string \| null | 操作被默认拒绝时的玩家可见说明。 |
| direct_responses | `dict[str, string]` | 动作名到确定性直接响应的映射。 |
| rules | `list[Rule]` | B/C 类规则，完整结构见 2.3。 |
| aliases | `list[string]` | 别名列表，用于 Intent 匹配（如 "书架" 匹配 "藏书架"）。 |

**Runtime Usage**：

- `content` → 进入 Planner 上下文（可见实体描述）
- `secrets` → 仅引擎可读。玩家发现后由引擎写入 Event，Narrator 通过 Event 间接触达
- `state` → Room 初始化时拷贝到 `Room.entity_states`
- `refuse_ops` → 引擎在执行 Op 前校验
- `rules` → 引擎在每个 hook 上收集并求值
- `aliases` → IntentParser 匹配玩家输入中的别名

**Initialization**：

- **EntityState 初始化**：Room 创建时，引擎遍历 `ModuleContent.entities`，将每个 `Entity.state` 的键值拷贝到 `Room.entity_states[entity.id]`。
- **不参与 Character 初始化**。Character 的属性来自车卡过程，不来自 Entity。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| Rule.hook | World.hooks | 校验 hook 名是否在合法列表中 |
| Rule.when 中的 state path | Entity.state 的键空间 | 校验表达式引用的键是否存在 |

**Lifecycle**：

```text
Parser 创建 → Validation 校验（kind 枚举、state 键名、Rule 引用完整性）
→ Publish 固化 → Runtime: Room 初始化时 state → entity_states
```

---

### 2.3 Rule、Condition 与 Operation

#### Phase 1 当前 Schema

```python
class ConditionSpec(ContractModel):
    path: str
    equals: JsonValue

class AllowOperationSpec(ContractModel):
    op: Literal["allow"] = "allow"
    action: str

class ModifyOperationSpec(ContractModel):
    op: Literal["modify"] = "modify"
    path: str
    set: JsonValue

OperationSpec = AllowOperationSpec | ModifyOperationSpec

class RuleSpec(ContractModel):
    id: str
    hook: Literal["on_action", "on_scene_enter", "on_turn_end", "on_check_resolve"]
    priority: int = 0
    when: ConditionSpec
    then: tuple[OperationSpec, ...] = ()
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()
```

Phase 1 不存在 `mode` 字段，不支持完整布尔 Expr。当前引擎按 `priority` 降序选择规则；相同 priority 目前保留声明顺序。若未来需要跨序列化实现完全一致，应另行冻结同优先级排序规则。Condition 和 `modify.path` 必须引用已由某个 `Entity.state` 声明的路径。

#### Phase 2 SAN 扩展

```python
class ApplySanOperationSpec(ContractModel):
    op: Literal["apply_san"] = "apply_san"
    trigger_id: str
    target: Literal["actor"] = "actor"

OperationSpecV2 = AllowOperationSpec | ModifyOperationSpec | ApplySanOperationSpec
```

`apply_san` 是触发 SanTrigger 的唯一权威入口，只能出现在 `Rule.then` 或 `CheckpointOutcome.ops` 中。Phase 2 首版只允许 `target="actor"`，表示当前动作/检定/规则上下文中的角色；群体或指定角色目标留待后续扩展。Planner 可以帮助匹配 Checkpoint，但不能直接决定或执行 SAN 损失。

---

### 2.4 Checkpoint

**Purpose**：描述一个可由玩家触发的技能检定——成功和失败各自产生什么事实、什么状态变更、什么叙事约束。Checkpoint 是 Intent → Engine 的关键桥梁。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| scene_id | string | 所属 Scene ID |
| action | string | Host Agent 使用的语义动作提示，不是穷举式动词白名单 |
| target_id | string | 检定目标 Entity ID |
| skills | `tuple[string, ...]` | 一个或多个候选技能，至少一个 |
| difficulty | `"regular"` \| `"hard"` \| `"extreme"` | Phase 1 必填且不可空 |
| outcomes | `CheckpointOutcomes` | 包含 success 与 failure 两个 Outcome |

**Optional Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| mvp_check_result | `"success"` \| `"failure"` | 仅 Phase 1 Demo fixture 使用；生产检定结果由引擎权威产生 |

`CheckpointOutcome` 的完整结构：

```python
class CheckpointOutcomeSpec(ContractModel):
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()
    narration_constraints: tuple[str, ...] = ()
    ops: tuple[OperationSpec, ...] = ()

class CheckpointOutcomesSpec(ContractModel):
    success: CheckpointOutcomeSpec
    failure: CheckpointOutcomeSpec
```

Phase 2 可以在不改变上述核心结构的前提下增加 `hidden`、`roll_mode`、`priority`；`difficulty` 可空性另行评审，不在本轮冻结。

**Runtime Usage**：

- `action` / `skills` → Host Agent 匹配候选 Checkpoint，CheckResolver 确定技能
- `difficulty` → CheckResolver 确定检定难度
- `outcomes.success/failure` → 引擎根据权威检定结果执行 ops，并产生 facts、player_visible_information 和 narration_constraints
- Phase 2 的 `hidden` / `roll_mode` → 决定是否创建 PendingCheck

**Initialization**：不参与。Checkpoint 是静态内容，引擎根据 Intent 动态加载。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| scene_id | Scene.id | 确定 Checkpoint 归属哪个场景 |
| target_id | Entity.id | 确定检定目标实体 |
| skills | Skill catalog | 确定候选技能是否合法 |
| outcomes.ops.modify.path | Entity.state 路径 | 确定写入目标已声明 |
| outcomes.ops.apply_san.trigger_id（Phase 2） | SanTrigger.id | 确定 SAN 触发器存在 |

**Lifecycle**：

```text
Parser 创建 → Validation 校验（scene_id、target_id、skills、difficulty、Operation 引用）
→ Publish 固化 → Runtime: Planner 匹配 → Engine 执行 → Narrator 接收 Outcome
```

---

### 2.5 SanTrigger（Phase 2 Target）

**Purpose**：描述一个 SAN 检定触发器——玩家在什么条件下、以什么方式、损失多少 SAN。CoC 7e 有 6 种 SAN 损失形态，SanTrigger 承载其结构化表达。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| kind | `"check"` \| `"flat"` \| `"direct"` \| `"max_reduce"` \| `"gain"` \| `"capped"` | SAN 损失形态 |
| loss | `SanExpr` | SAN 损失表达式，如 "0/1d6"（成功/失败）或 "1d4"（固定） |

**Optional Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| source_tag | string \| null | 累计封顶的分组键。kind="capped" 时必须提供。 |
| cap | int \| null | 累计损失上限。kind="capped" 时必须提供且大于等于 0。 |
| once_per_character | bool | 每名角色是否最多执行一次，默认 false。 |
| description | string \| null | 供审核和叙事理解的说明；不参与权威触发判断。 |

**Runtime Usage**：

- SANManager 根据 `kind` 选择处理逻辑
- `loss` → 确定 SAN 损失的具体数值
- `source_tag` + `cap` → LedgerEntry 累计封顶：同 source_tag 的多次 SAN 损失合计不超过 cap
- `Rule.then` 或 `CheckpointOutcome.ops` 中的 `apply_san(trigger_id=...)` → 唯一权威执行入口
- `once_per_character` → SANManager 使用 Ledger/EventLog 幂等检查，避免重复执行

**Initialization**：不参与。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| `ApplySanOperation.trigger_id` | SanTrigger.id | Validation 必须确认目标存在 |

SanTrigger 不再携带自由文本 `condition`。触发条件由承载它的 Rule.when 或 Checkpoint 的确定性成功/失败分支表达；`description` 不能触发状态变更。

**Lifecycle**：

```text
Parser 创建 → Validation 校验（kind、loss、source_tag/cap 条件必填、apply_san 引用与 target）
→ Publish 固化 → Runtime 执行 Rule/Checkpoint Operation → SANManager 按 trigger_id 处理
```

---

### 2.6 WinCondition

**Purpose**：描述一个结局条件——当特定状态满足时触发结局事实与玩家可见信息，并结束游戏。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| when | `Condition` | 触发条件。引用 entity_states 中的键。 |
| fact | string | 引擎确认的结局事实。 |
| player_visible_information | string | 可交给 Narrator 的玩家可见结局信息。 |

**Runtime Usage**：

- WinConditionEvaluator 在每个回合结束时求值 `when`
- 条件满足 → 触发结局，Room phase → "ended"
- `fact` → 写入权威结果/Event
- `player_visible_information` → Narrator 生成结局叙事

**边界约束**：WinCondition 只表达终局，不承担状态回滚或非终局剧情节点。“被抓回房间”“重置机关”“强制移动”等非终局后果必须建模为 `Rule.when + Rule.then Operations`；如需玩家可见说明，使用 Rule 的 `facts` / `player_visible_information`。

**Initialization**：不参与。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| when 中的 path | Entity.state 的键空间 | 校验表达式引用的键是否存在 |

**Lifecycle**：

```text
Parser 创建 → Validation 校验（when 引用的 state key 存在）
→ Publish 固化 → Runtime: WinConditionEvaluator 每回合求值
```

---

### 2.7 Pregen（设计候选，未进入本轮 Phase 2 Schema）

**Purpose**：模组附带的预设角色卡。玩家可选择预设角色快速开始游戏。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| name | string | 角色名称 |
| attributes | `dict[str, int]` | 八大属性值 |
| skills | `dict[str, int]` | 技能值 |

**Optional Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| occupation | string \| null | 职业名称或引用 |
| equipment | `list[string]` \| null | 初始装备 |

**Runtime Usage**：Character 创建时作为模板填充初始属性、技能和装备。

**Initialization**：参与 Character 初始化。`Character.based_on_pregen_id` 指向 Pregen.id。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| occupation | Occupation.id | 职业引用 |

**Lifecycle**：

```text
Parser 创建 → Validation 校验（attributes 八大属性齐全、skills 键合法）
→ Publish 固化 → Runtime: 玩家选角色 → Character 初始化
```

---

### 2.8 Asset（设计候选，未进入本轮 Phase 2 Schema）

**Purpose**：模组附带的资源文件引用——地图、图片、文字材料（Handout）。Asset 本身不包含二进制数据，只包含引用指针。

**Required Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 唯一标识 |
| ref | string | 资源引用。指向 blob_assets 的 storage_key。 |

**Optional Fields**：

| 字段 | 类型 | 说明 |
|------|------|------|
| kind | `"image"` \| `"map"` \| `"handout"` \| `"other"` | 资源类型 |
| label | string \| null | 人类可读的标签，如"一楼地图""文字材料 1" |

**Runtime Usage**：按需通过 `ref` 加载二进制数据，投递给客户端展示。

**Initialization**：不参与。

**References**：

| 引用 | 指向 | 用途 |
|------|------|------|
| ref | blob_assets.storage_key | 获取实际文件 |

**Lifecycle**：

```text
Parser 创建 → Validation 校验（ref 格式合法）
→ Publish 固化 → Runtime: 客户端按需加载
```

---

## 特别回答

### 1. Runtime Keeper 如何消费 ModuleContent？

```text
ModuleContent 经 Publish 后成为 ApprovedModule，存入 Content Repository。

Room 创建时：
  Room.module_pack_id → 加载对应的 ApprovedModule.content

每回合开始时：
  ContextAssembler 根据 Character.location 定位 Scene
  → 遍历 Scene.entity_ids，组装 VisibleEntity 列表
  → 遍历 Scene.checkpoint_ids，组装 CheckpointOption 列表
  → 返回 TurnContext

引擎执行时：
  根据 Intent.check 加载对应的 Checkpoint
  → CheckResolver 执行检定
  → RuleEvaluator 收集 Entity.rules + World.world_rules，按 priority 求值
  → StateManager / SANManager 校验并执行 Op，写入权威状态
  → EventLogger 写入 Event
  → WinConditionEvaluator 求值 WinCondition.when

Narrator 生成时：
  接收 ActionResult（含 confirmed_facts、player_visible_information、narration_constraints）
  → 生成自然语言叙事
```

### 2. Scene 如何驱动 Runtime？

```text
Scene 是 Runtime 的空间组织单元：

1. 玩家所在 Scene 决定了可见实体集合和可用动作集合
2. 场景切换：Intent.action_type = "move" → 引擎更新 Character.location
   → 下一回合 ContextAssembler 加载新 Scene
3. Scene 的出口关系（Scene.exits）决定了玩家可以去哪些场景
4. Scene.checkpoint_ids 决定了当前场景有哪些模组预设动作可用

注意：不需要全局场景图。并非所有模组都有严格的邻接约束——
《追书人》《鬼屋》《蛙蛙村》都是城市/园区内自由移动，exits 恒为空。
```

### 3. Checkpoint 如何推进剧情？

```text
Checkpoint 不直接推进剧情——它不生成叙事，不写入状态。

Checkpoint 提供的是"玩家做 X → 引擎判定 Y → 事实 Z 成立"的映射：

1. Planner 匹配 Checkpoint → 生成 Intent
2. Engine 根据 Intent.check 加载 Checkpoint → 执行检定
3. 检定结果（success/fail）→ 引擎执行对应 Outcome 中的 ops
4. ops 写入 entity_states → 产生 Event
5. Event 可能触发 B 类 Rule（hook 上的必然事件）
6. WinConditionEvaluator 读取 entity_states 判断结局

剧情推进是 Rule + Event + WinCondition 协作的结果。
Checkpoint 只是检定入口，不是剧情引擎。
```

### 4. EntityState 如何由 Entity 初始化？

```text
Room 创建时（SessionManager.create_room）：

1. 加载 ApprovedModule.content
2. 遍历 ModuleContent.entities
3. 对每个 Entity e：
     Room.entity_states[e.id] = deep_copy(e.state)
4. 之后所有 entity_states 变更由引擎执行（经校验的 Op）

注意：
- Entity.state 是 Content 层，只读，由 Parser 在导入时定义
- Room.entity_states 是 GameState 层，可变，仅引擎可写
- EntityState 的当前值是物化视图——可从 EventLog 重建
```

### 5. 哪些对象属于静态内容？哪些对象属于运行时状态？

```text
静态内容（Content 层，Parser 创建，Publish 固化，只读）：
  Phase 1: Scene, Entity, Checkpoint, WinCondition
  Phase 2 Target: + SanTrigger
  设计候选（尚未进入 schema）: Pregen, Asset
  Rule（挂在 Entity.rules 或 World.world_rules 上）

运行时状态（GameState 层，引擎创建和修改）：
  Room.entity_states（从 Entity.state 初始化，后续由引擎修改）
  Character.attributes / skills / conditions / ledger / equipment / location
  Character.derived_stats（HP / SAN / MP / LUCK，引擎修改）
  Player.pending_check（引擎创建，玩家提交后引擎消费）

权威历史（EventLog 层，引擎写入，只增）：
  Event（每条 event 携带 type + payload + cause + visibility）
```

---

## Open Questions

1. **ModulePack 归属**：`ModulePack` 的 Pydantic Model 应在 `contracts/module.py` 中定义，还是作为数据库层的 ORM Model？当前仅 `ModuleContent` 存在，缺失 `ModulePack`。Parser Pass 提取的 title、authors、players_min/max 目前无 Pydantic Model 承载。

2. **Entity.public_persona 和 Entity.stats**：`contracts/module.py` 的 `EntitySpec` 中缺失；本 RFC 暂列设计候选，不再默认承诺 Phase 2 必须补充。

3. **SanTrigger 落地评审**：Phase 2 需共同评审 `SanTriggerSpec`、`ApplySanOperationSpec`、SANManager 幂等策略以及 `ModuleContentV2.san_triggers`。Pregen、Asset 独立评审，不阻塞 SAN 扩展。

4. **CheckpointSpec.difficulty 的可空性**：当前契约保持不可空。是否允许 null 作为未来独立决策，需先定义软判据的权威执行者和可复现语义。

5. **RuleSpec.when / WinConditionSpec.when**：当前保持 `ConditionSpec {path, equals}`。完整 Expr 作为后续版本候选，需 B 共同评审升级路径。

6. **contracts/module.py 修改审批**：`architecture.md` 规定 `contracts/module.py` 是 B/C 共同评审区——C 的任何字段修改需 B 审批。

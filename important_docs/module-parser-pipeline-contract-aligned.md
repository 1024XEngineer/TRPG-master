# Module Parser Pipeline 设计（契约对齐版）

> 日期：2026-07-15
> 定位：Module Import Pipeline——将非结构化 CoC 模组编译为 Runtime 可执行的 `ModuleContent`
> 主责：成员 C
> 前置：数据模型设计.md / 成员C-模组解析与审查Agent流程架构.md / agent-framework-selection.md

---

## 〇、系统定位

### 〇.1 项目中只有两个一级 Agent

```text
Arkham Case Files
├── Module Parser Agent（离线）    ← 本文档
│   输入: Phase 1 人工 JSON / Phase 2 Markdown
│   输出: ModuleContent + ValidationReport + 可选 ReviewReport
│   内部: Preprocess → Parser Pass → Validation → Review Pass → Publish
│
└── Runtime Keeper Agent（在线）
    内部: ContextAssembler → Intent/Narration → AtomicActionEngine
```

本期只实现一个 `Module Parser Agent`。Parser Pass 和 Review Pass 是它内部的两个 LLM 阶段，不是两个一级 Agent，不引入 Reviewer Agent 或 Supervisor Agent。

框架可预留 Parser/Reviewer 两个内部实现接口，便于以后根据评测结果拆分；但当前对外只暴露一个 Module Parser Agent 边界，`review_module()` 与 `publish_module()` 都是内部步骤。

### 〇.2 本质是编译器，不是聊天机器人

```
编译器类比：

  源码（模组原文）
    → 词法/语法分析（Preprocess + Parser Pass）
    → 语义分析（Validation）
    → 优化 + 警告（Review Pass）
    → 人工审批（Human Approval）
    → 目标代码（ModuleContent）

不是：

  用户提问 → LLM 回答
```

---

## 一、完整 Pipeline（Mermaid）

```mermaid
flowchart TB
    subgraph ENTRY["入口"]
        MANUAL["✍️ Phase 1: 人工编写 demo-module.json"]
        PDF["📄 Phase 2: 模组 PDF / Markdown"]
    end

    subgraph PREPROCESS["预处理（确定性代码）"]
        PDF_EXTRACT["PDF → Markdown<br/>PyMuPDF"]
        CHUNK["分段 + 来源编号<br/>生成 SourceFragment"]
    end

    subgraph PARSER["Module Parser Agent：Parser Pass（LLM）"]
        PARSER_NODE["Parser Pass<br/>提取 Scene / Entity / Checkpoint<br/>Entity.rules / SanTrigger<br/>WinCondition / Pregen / Asset"]
    end

    subgraph VALIDATE["Validation（确定性代码）"]
        V1["Schema: 类型/枚举/必填项"]
        V2["Reference: 跨引用完整性"]
        V3["Semantic: Expr语法/State引用/可达性"]
    end

    subgraph REVIEW["Module Parser Agent：Review Pass（LLM）"]
        REV["Review Pass<br/>遗漏检测 / 秘密隔离<br/>可达性 / 过度结构化"]
    end

    subgraph APPROVAL["Human Approval"]
        HUMAN["人工审批<br/>A/B/C/D 逐条复核<br/>当前 4-hook 能力检查"]
    end

    subgraph PUBLISH["发布"]
        PUB["版本化 ModuleContent<br/>冻结 fixtures/evals"]
    end

    %% Phase 1
    MANUAL --> DRAFT

    %% Phase 2
    PDF --> PDF_EXTRACT --> CHUNK --> PARSER_NODE --> DRAFT

    %% 汇合
    DRAFT["ModuleDraft<br/>携带 source_references<br/>+ confidence"] --> V1
    V1 -->|"通过"| V2
    V1 -->|"失败"| FIX["🔴 打回修正"]
    V2 -->|"通过"| V3
    V2 -->|"阻断"| FIX
    V3 -->|"通过"| REV
    V3 -->|"警告"| REV
    REV -->|"Layer 2: 自动发布"| PUB
    REV -->|"ReviewReport / 可选 Layer 3"| HUMAN
    HUMAN -->|"批准"| PUB
    HUMAN -->|"打回"| FIX
    FIX --> DRAFT

    classDef llm fill:#dbeafe,stroke:#2563eb,color:#172554,stroke-width:2px
    classDef code fill:#1f2937,stroke:#111827,color:#ffffff,stroke-width:2px
    classDef human fill:#fef3c7,stroke:#d97706,color:#78350f,stroke-width:2px
    classDef output fill:#dcfce7,stroke:#16a34a,color:#14532d,stroke-width:2px
    classDef failure fill:#fee2e2,stroke:#dc2626,color:#7f1d1d,stroke-width:2px
    classDef draft fill:#f3e8ff,stroke:#7e22ce,color:#581c87,stroke-width:2px

    class PARSER_NODE,REV llm
    class PDF_EXTRACT,CHUNK,V1,V2,V3 code
    class HUMAN human
    class PUB output
    class FIX failure
    class DRAFT draft
```

**关键设计**：`PARSER_NODE` 是 Parser Pass，`REV` 是 Review Pass，两者同属一个 Module Parser Agent。框架中即使为两个阶段预留不同接口，当前也不改变 Agent 数量。Parser Pass 本期按 Issue #57 采用单次 LLM 调用；后续只在真实模组评测显示遗漏率过高时再考虑拆分。

---

## 二、两阶段策略

```text
Phase 1（当前 MVP）：人工编写 demo-module.json
  → Validation → Review Pass → Human Approval → ModuleContent
  → 目标：跑通校验 + 审批管线，给 Runtime Keeper Agent 提供稳定数据契约
  → 不涉及 Parser Pass（数据是人工写的）

Phase 2（Runtime 稳定后）：模组原文自动导入
  → 预处理 → Parser Pass → ModuleDraft
  → 然后汇入与 Phase 1 完全相同的 Validation → Review → Human Approval → 发布管线
  → 目标：让任意 CoC 模组自动编译为可执行内容
```

---

## 三、每个阶段的详细设计

### 3.0 导入契约与 Runtime 契约

Pipeline 使用两层模型，不将导入证据直接塞入 Runtime JSON：

```text
ModuleDraft（导入侧富模型）
├── runtime_candidate
├── source_references
├── confidence_notes
├── unresolved_questions
└── import_extensions
    └── ModulePack / SanTrigger / Pregen / Asset 等尚未进入 Runtime 的信息

                 ↓ Human Approval + deterministic lowering

ModuleContent（Runtime 窄契约）
├── module_id / version / world_ref
├── scenes: Scene[]
├── entities: Entity[]
├── checkpoints: Checkpoint[]
└── win_conditions: WinCondition[]
```

Runtime 契约以 `agent-collaboration-framework/collaboration_framework/contracts.py` 中的 Pydantic `ModuleContent` 为唯一事实源，当前具体限制为：

- `Entity.kind` 仅支持 `npc | object | location`。
- `Rule.hook` 仅支持 `on_action | on_scene_enter | on_turn_end | on_check_resolve`。
- `Rule.when` 是 `{path, equals}` Condition，不是通用 Expr 字符串。
- `Rule.then` 仅支持 `allow` 和 `modify` Operation。
- `Checkpoint.skills` 是非空列表，`difficulty` 必须是 `regular | hard | extreme`。
- `Checkpoint.outcomes.success/failure` 必须是结构化 Outcome。
- `WinCondition` 使用 `when + fact + player_visible_information`，当前不支持 `expr` 或 `is_ending=false`。
- 公共契约使用 `extra="forbid"`，`source_references` 等草稿字段不得进入 Runtime JSON。

Phase 2 的最终边界必须是：

```python
draft = ModuleDraft.model_validate(payload)
review = review_module(draft, source_documents)
approved = approve(draft, review)
runtime_payload = lower_to_runtime_content(approved)
content = ModuleContent.model_validate(runtime_payload)
```

Lowering 不得凭空补造设定，也不得把引擎不支持的机制静默降级为自由文本。无法表达的机制必须成为阻断问题，或作为经人工显式接受的 warning 保留。

### 3.1 预处理（Preprocess）——确定性代码

**职责**：将原始文件转为干净的、可追溯的结构化文本。

| 步骤 | 工具 | 输入 | 输出 |
|------|------|------|------|
| PDF 提取 | PyMuPDF | 模组 PDF | Markdown 文本 |
| 章节识别 | 标题层级解析 | Markdown | 章节树（h1/h2/h3） |
| 段落编号 | 确定性分片算法 | 章节树 | `SourceFragment[]`（稳定 ID） |
| 边界识别 | 关键词匹配 | SourceFragment[] | 标注"守秘人信息"/"玩家信息" |

**SourceFragment**：

```python
class SourceFragment(BaseModel):
    id: str          # "src_ch3_p12_005" — 稳定可引用
    locator: str     # "第三章 / 第12页 / 第5段"
    text: str
    section: Literal["keeper_info", "player_info", "unclassified"]
```

**为什么用确定性代码而不是 LLM**：段落编号必须稳定（同一 PDF 两次运行得到相同 ID）。LLM 输出不可复现。章节边界识别用 h1-h6 就够了。

---

### 3.2 Parser Pass（LLM）——Module Parser Agent 的第一个内部阶段

**职责**：从模组原文中提取结构化数据，输出 `ModuleDraft`。

**为什么先单 Pass？**

本期采用单次 LLM 调用完成 Parser Pass。两 Pass 会带来级联错误、双倍延迟和更高 Token 成本；Pass 1 遗漏的实体，Pass 2 也无法稳定引用。Prompt 内部仍按“基础信息 → 机制信息”两步组织。是否改为 Multi-Pass，留待 Phase 2 真实模组评测后决定。

**提取目标（按提取顺序组织 prompt）**：

**基础信息（高置信度）**：

| 提取目标 | 置信度 | 说明 |
|---------|--------|------|
| ModulePack 元信息（title, authors, players_min/max, difficulty） | 🟢 高 | 模组标识和发布元数据 |
| ModuleContent 基础字段（module_id, version, world_ref） | 🟢 高 | 模组标识和规则系统绑定 |
| Scene[] | 🟢 高 | 场景名称、描述、出口关系 |
| Entity[]（基本信息） | 🟢 高 | 当前 Runtime 字段：name, kind, aliases, content, secrets, state 等 |
| Checkpoint[]（文本描述） | 🟢 高 | match_hint, skill, on_success/on_fail 的自然语言描述 |
| Pregen[] | 🟢 高 | 预设角色卡，格式规整 |
| Asset[] | 🟢 高 | 模组附带的图片、地图、文字材料引用 |
| SanTrigger.loss/condition | 🟢 高 | 原文通常直接写 "0/1d6" |

**机制信息（需要领域知识，易错——Review Pass 和人工复核兜底）**：

| 提取目标 | 置信度 | 说明 |
|---------|--------|------|
| Entity.rules[] | 🟡 中 | `(hook, when, then)` 三元组。LLM 不愿生成 forbid 类 |
| Entity.refuse_ops[] | 🟡 中 | A 类：绝不可执行的操作 |
| Entity.state{} | 🟡 中 | D 类：被 Rule/Expr 引用的值 |
| Checkpoint.difficulty | 🟡 中 | Runtime 候选必须是 regular/hard/extreme；不确定时进 unresolved_questions |
| SanTrigger.kind | 🟠 低 | 六值枚举，direct 和 check 易混淆 |
| SanTrigger.source_tag | 🟠 低 | 累计封顶的分组键 |
| WinCondition.when | 🟠 低 | 当前映射为 Condition(path, equals) |
| WinCondition 终局语义 | 🟠 低 | 当前 WinCondition 都是终局；回滚属于未来扩展 |

**Parser Pass 的硬约束**：

1. 每个字段必须携带 `source_references`（追溯到 SourceFragment.id）
2. 原文不含的信息不得凭空补造
3. 不确定的字段标记在 `unresolved_questions` 中
4. `Entity.secrets` 和玩家可见的 `Entity.content` 必须严格分离

**技术实现**：

```python
from pydantic_ai import Agent

parser_pass = Agent(
    model="claude-opus-4",
    result_type=ModuleDraft,
    system_prompt="""你是 CoC 模组的结构化解析器。

从模组原文中按以下顺序提取：

一、基础信息
- ModulePack 元信息（title, authors, players_min/max, difficulty）
- Scene（名称、描述、出口关系）
- Entity（当前 Runtime 字段 + 导入侧扩展）
- Checkpoint（match_hint, skill, on_success/on_fail 描述）
- Pregen（预设角色卡）、Asset（附件引用）
- SanTrigger（loss 值、触发条件描述）

二、机制信息（基于已提取的基础信息）
- Entity.rules（hook-when-then 三元组，hook 从 19 个中选）
- Entity.refuse_ops（A 类：绝不可执行的操作）
- Entity.state（仅 D 类：被 Rule/Expr 引用的键）
- Checkpoint.difficulty（regular/hard/extreme；不确定时记入 unresolved_questions）
- SanTrigger.kind（六值枚举：check/flat/direct/max_reduce/gain/capped）
- WinCondition.when + fact + player_visible_information

约束：
1. 每个字段携带 source_references
2. 原文不含的信息不得凭空补造
3. 不确定的字段标为 null，记入 unresolved_questions
4. secrets 和 content 必须严格分离
5. Rule.when 必须是当前 Condition(path, equals)
6. Rule.hook 和 Operation 不得超出当前 Runtime 契约
7. 无法下沉的机制必须记入 unresolved_questions""",
    tools=[query_skill_catalog, query_hook_catalog, query_op_catalog],
)
```

---

### 3.3 Validation（确定性代码）——零 LLM

**职责**：发现确定性的错误。所有错误在数学上可证明——不需要"理解"模组，只需要检查数据结构。

#### Layer 1：Schema 校验

```python
def validate_schema(draft: dict) -> list[ValidationIssue]:
    """Pydantic model_validate。阻断。"""
    try:
        ModuleContent.model_validate(draft)
    except ValidationError as e:
        return [_to_issue(err) for err in e.errors()]
```

| 检查项 | 示例 |
|--------|------|
| 字段类型 | `Entity.kind` 必须是 npc/object/location 之一 |
| 必填项 | `Checkpoint.skill` 不可为空 |
| 枚举值 | `Rule.hook` 必须是当前四个 hook 之一 |
| 额外字段 | Model 中未定义的字段 → 拒绝 |
| ID 格式 | `entity_id` 不能含空格 |

#### Layer 2：引用完整性校验

```python
def validate_references(content: ModuleContent) -> list[ValidationIssue]:
    """跨引用完整性。阻断。"""
    issues = []
    entity_ids = {e.id for e in content.entities}
    scene_ids = {s.id for s in content.scenes}
    checkpoint_ids = {c.id for c in content.checkpoints}
    state_keys = _collect_all_state_keys(content)

    # Scene → Entity / Checkpoint
    for scene in content.scenes:
        for eid in scene.entity_ids or []:
            if eid not in entity_ids:
                issues.append(error("scene.ref.entity_not_found", scene.id, eid))
        for cid in scene.checkpoint_ids or []:
            if cid not in checkpoint_ids:
                issues.append(error("scene.ref.checkpoint_not_found", scene.id, cid))

    # Checkpoint → Scene / Entity
    for cp in content.checkpoints:
        if cp.scene_id not in scene_ids:
            issues.append(error("checkpoint.ref.scene_not_found", cp.id))
        if cp.target_id and cp.target_id not in entity_ids:
            issues.append(error("checkpoint.ref.target_not_found", cp.id))

    # Rule → State
    for entity in content.entities:
        for rule in entity.rules or []:
            if rule.when.path not in state_keys:
                issues.append(error("rule.ref.state_not_found", entity.id, rule.when.path))

    # WinCondition → State
    for wc in content.win_conditions:
        if wc.when.path not in state_keys:
            issues.append(error("wincon.ref.state_not_found", wc.id, wc.when.path))

    # 顶层禁止 rules
    if hasattr(content, 'rules') and content.rules:
        issues.append(error("top_level.rules_forbidden", "module", None))

    return issues
```

#### Layer 3：当前能力边界

当前 `Scene` 契约没有起始 Scene、出口图和完整状态转移关系，因此场景/Checkpoint/WinCondition 可达性、语义依赖环和剧情断路不能被当作数学上可证明的确定性校验。在 Schema 补齐前，这些项由 Reviewer 生成启发式 warning，交人工裁决。

**Validation 与 Review Pass 的边界**：

| 问题 | 属于 | 原因 |
|------|------|------|
| Entity ID 引用了不存在的对象 | Validation | 数学上可证明——做集合差运算 |
| WinCondition.when 引用不存在的 state path | Validation | 状态路径集合比对 |
| 柜子需要钥匙、钥匙在柜子里 | Review Pass | 当前契约没有完整状态转移图 |
| 起始 Scene 或场景路径缺失 | Review Pass | 当前 Scene 没有起点/出口契约 |
| **NPC 的秘密被误放在 content 中** | Review Pass | 需要语义理解——"这个信息玩家该知道吗" |
| **B 类规则遗漏（管家进入没有 Hook）** | Review Pass | 需要理解"什么事件必须主动触发" |
| **C 类规则遗漏（INT 成功 → 更糟）** | Review Pass | 需要理解"成功不一定是好事" |
| **模组剧情是否流畅** | Review Pass | 需要理解叙事——机器做不了 |
| **是否过度结构化（普通抽屉做成了 Rule）** | Review Pass | 需要判断"这个真的需要引擎接管吗" |

---

### 3.4 Review Pass（LLM）——Module Parser Agent 的第二个内部阶段

**职责**：对已通过所有确定性校验的 ModuleDraft 进行语义审查。输出 ReviewReport。**只审查，不发布。**

**为什么 Review 不能合并进 Validation？**

Validation 只能回答"结构对不对"——引用是否存在、类型是否匹配、状态是否有环。它回答不了"玩起来对不对"——NPC 的秘密是否泄漏、B 类事件是否遗漏、C 类反转是否标注。这些问题需要语义理解。

**为什么 Review 不用 Human 替代 LLM？**

一次模组导入产出数百个 Entity/Checkpoint/Rule。人工逐条审查成本太高。LLM 先扫一遍，产出结构化的 `human_review_checklist`，人工只需要逐条打勾——而不是从零开始审查。

```python
review_pass = Agent(
    model="claude-sonnet-5",
    result_type=ReviewReport,
    system_prompt="""你是 Module Parser Agent 的 Review Pass。

对已通过所有确定性校验的 ModuleDraft 进行语义审查。

审查维度：
1. 来源忠实度——有无凭空补造的设定？
2. 机制 A 遗漏——存在"绝不出售"的 NPC 但 refuse_ops 为空？
3. 机制 B 遗漏——存在条件满足后必须触发但缺失的 Hook？★
4. 机制 C 遗漏——存在检定成功反而坏结果但未标注？★
5. 机制 D 遗漏——被 Rule/Expr 引用的值是否都已落 entity_states？
6. 秘密隔离——secrets 是否混入公开字段？
7. 可执行性——Rule 的 Op/Hook 是否在引擎支持范围内？
8. 可达性——关键 Checkpoint 和结局是否有合理路径？
9. 过度结构化——是否有纯文本对象被错误做成 Rule/Checkpoint？

输出 ReviewReport（errors 阻断 + warnings 警告 + human_review_checklist）。
""",
    tools=[query_engine_capabilities, query_hook_catalog],
)
```

---

### 3.5 Human Approval（人工审批）——可选 Layer 3

**定位**：按 Issue #57 的本期决策，人工审批不是发布前置条件。Layer 1 保障结构可运行，Layer 2 增加 Review Pass 后可自动发布并标注“AI 已审查”，Layer 3 增加人工复核后标注“人工认证”。

```text
┌──────────────────────────────────────────────────┐
│ Layer 1: 结构正确（Validation，全自动，即时）      │
│                                                   │
│ 引用完整、类型正确、状态无环。                      │
│ → 标注“可运行”，可按发布策略进入 Runtime。             │
│ → 体验：能跑。可能缺 B/C 类机制，模组变简单。        │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Layer 2: 语义完整（+ Review Pass，全自动，数分钟）  │
│                                                   │
│ Layer 1 + LLM 扫描 A/B/C/D 覆盖度、秘密隔离。       │
│ → 标注“AI 已审查”，可自动发布。                     │
│ → 体验：大部分机制正确。B/C 遗漏率降低但非零。       │
└──────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────┐
│ Layer 3: 人工认证（+ Human Review，人工，可能数天）  │
│                                                   │
│ Layer 2 + 人工逐条复核 A/B/C/D + 当前 4-hook 能力。 │
│ → 标注“人工认证”，作为最高质量层级。               │
│ → 适合：官方模组、比赛模组、付费模组。               │
└──────────────────────────────────────────────────┘
```

**为什么 Layer 3 是可选的**：

- B 类遗漏（猫必须死）→ 玩家最终会卡关 → 可检测，可修复
- C 类遗漏（INT 成功反而疯狂）→ 玩家不会发现 → 游戏变简单，但不影响可玩性
- Layer 1 保障能跑，Layer 2 显著降低 B/C 遗漏，Layer 3 用人工成本换取更高的作者意图保真度。

**Phase 1 仍建议走人工审批**：书房 Demo 只有 5 个实体，5 分钟即可完成，目的是建立审批流程和 checklist 模板，为 Phase 2 做准备。

**审批清单**：

```text
□ A 类：每个 Entity——玩家索要/夺取时，是否无论如何都不能得手？
□ B 类：每个 Entity——是否存在无论如何都必须发生的 Hook？★
□ C 类：每个 Checkpoint——成功是否反而导致坏结果？★
□ D 类：每个 state key——是否被 Rule/Expr 引用且合法落库？
□ 当前 4-hook 能力：是否存在无法映射的原文机制
□ 结局可达性：所有 WinCondition 的前置状态是否可能达成？
```

**三种审批结果**：
- `批准` → 版本化发布
- `打回` → 返回 Parser Pass 或人工修订，重新跑 Validation
- `有条件批准` → 接受 warnings，记录审批人及理由

---

### 3.6 发布（Publish）

```text
Layer 1 通过（Validation）   → 标注“可运行”
Layer 2 通过（+ Review Pass）→ 标注“AI 已审查”，自动发布
Layer 3 通过（+ Human Approval）→ 标注“人工认证”

批准后的 ModuleContent:
  1. 赋予不可变版本号
  2. 计算 content_hash（SHA256）
  3. 存入 Content Repository
  4. 冻结 fixtures/evals
  5. 通知 Runtime Keeper Agent 可加载
```

---

## 四、中间产物

```text
RawDocument
  │  PDF 路径 + SHA256 + MIME 类型
  │  只读，不修改
  │
  ▼
SourceFragment[]
  │  分段的文本块 + 稳定 ID + 页码定位
  │  用于来源追溯
  │  确定性代码生成
  │
  ▼
ModuleDraft
  │  Parser Pass 输出
  │  携带 source_references（字段→SourceFragment.id）
  │  携带 confidence_notes（字段→置信度）
  │  携带 unresolved_questions
  │  ⚠️ 不可被 Runtime 加载
  │
  ▼
ValidationReport
  │  errors[]: 阻断项（必须修）
  │  warnings[]: 提醒项（可接受）
  │  status: pass | needs_revision | blocked
  │  确定性代码生成
  │
  ▼
ReviewReport
  │  errors[]: 阻断项
  │  warnings[]: 提醒项
  │  human_review_checklist[]: 待人工逐条核查
  │  mechanism_abcd_coverage: {A: true, B: false, ...}
  │  Review Pass（LLM）生成
  │
  ▼
ModuleContent
  │  通过全部校验 + 审查 + 人工审批
  │  版本化、不可变
  │  存入 Content Repository
  │  同步冻结 fixtures/evals
```

---

## 五、Parser Pass 与 Review Pass 的职责边界

```text
┌──────────────────────────────────────────────────────────────┐
│                    Parser Pass（LLM）                         │
│                                                               │
│  回答："模组里写了什么？"                                      │
│                                                               │
│  输入: SourceFragment[]（原文段落）                            │
│  输出: ModuleDraft（结构化 JSON + 来源引用）                   │
│                                                               │
│  做的事:                                                      │
│    · 从自然语言中提取 Scene / Entity / Checkpoint / Rule       │
│    · 区分玩家可见 content 和 secrets                      │
│    · 识别 SanTrigger 的 loss 值和触发条件                      │
│    · 提取 WinCondition 的文本描述                              │
│                                                               │
│  不做的事:                                                    │
│    · 判断提取结果是否正确（那是 Validation 的事）               │
│    · 判断是否有遗漏（那是 Review Pass 的事）                   │
│    · 修改原文（必须忠实提取）                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│                    Review Pass（LLM）                         │
│                                                               │
│  回答："这个模组能跑吗？有遗漏吗？"                             │
│                                                               │
│  输入: ModuleDraft + 原文                                     │
│  输出: ReviewReport（errors + warnings + checklist）           │
│                                                               │
│  做的事:                                                      │
│    · 检测 A/B/C/D 四类机制的遗漏                               │
│    · 检测秘密泄漏（secrets 混入 public fields）                │
│    · 检测过度结构化（纯文本对象被做成 Rule）                    │
│    · 检测剧情流程断裂                                          │
│    · 生成 human_review_checklist                              │
│                                                               │
│  不做的事:                                                    │
│    · 修改 ModuleDraft（只提建议，不改内容）                    │
│    · 替代人工审批（checklist 需要人打勾）                      │
│    · 检查引用完整性（那是 Validation 的事）                    │
└──────────────────────────────────────────────────────────────┘
```

**一句话总结**：Parser Pass 负责提取，Review Pass 负责审查；两者是同一个 Module Parser Agent 的内部工序，框架预留的接口不等于当前拆成多个 Agent。

---

## 六、Validation、Review Pass、Human Approval 的分工

| 问题类型 | Validation | Review Pass | Human Approval |
|---------|------------|-------------|---------------|
| 引用不存在的 Entity | ✅ 阻断 | — | — |
| 类型/枚举错误 | ✅ 阻断 | — | — |
| Condition / Operation 路径不存在 | ✅ 阻断 | — | — |
| 语义状态依赖环 | 当前不做严格证明 | ✅ 启发式 | 复核 |
| 场景不可达 | 当前不做严格证明 | ✅ 启发式 | 复核 |
| 秘密泄漏到公开字段 | — | ✅ 阻断 | 复核 |
| B 类规则遗漏 | — | ✅ 标记 | ★ 逐条复核 |
| C 类规则遗漏 | — | ✅ 标记 | ★ 逐条复核 |
| A 类 refuse_ops 遗漏 | — | ✅ 标记 | 逐条复核 |
| D 类 state 遗漏 | — | ✅ 标记 | 逐条复核 |
| 过度结构化 | — | ✅ 警告 | 接受/拒绝 |
| 剧情流程断裂 | — | ✅ 警告 | 接受/拒绝 |
| 当前 4-hook 能力缺口 | 契约外形状阻断 | ✅ 语义检测 | ★ 逐条复核 |
| 可玩性判断 | — | — | ✅ 最终裁决 |

---

## 七、Phase 1 落地计划

Phase 1 没有 Parser Agent 和 `ModuleDraft`——人工直接编写 Runtime `ModuleContent` 候选 JSON：

```text
人工编写 demo-module.json
    │
    ▼
Validation（L1+L2+L3）
    │
    ▼
Review Pass（LLM 审查 A/B/C/D 覆盖度）
    │
    ▼
Human Approval（可选 Layer 3：A/B/C/D 逐条复核）
    │
    ▼
发布 → 通知成员 A、B
```

对应的三个 Issue（按依赖顺序）：

```text
Issue 1: 保持 contracts.py 为当前 Runtime 唯一事实源
  → 未有验收案例前不扩展 19 hook / Expr / SanTrigger

Issue 2: 补齐 demo-module.json 的 A/B/C/D 四类机制覆盖
  → 影响: fixtures/demo-module.json + demo-cases.json + demo-state.json

Issue 3: 建立 ValidationReport + Reviewer fixture + ApprovalRecord
  → 影响: modules/validation.py + fixtures/evals + publication boundary
```

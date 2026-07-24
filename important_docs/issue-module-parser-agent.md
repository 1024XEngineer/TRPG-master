# Design Issue: Module Parser Agent

> 类型：Design Issue（RFC）
> 里程碑：MS1 · 战略决策与首尾可跑版本
> 主责：成员 C
> 日期：2026-07-17（对齐 codex/agent-collaboration-aligned 架构）
>
> **框架对齐说明**：本 Issue 中 `ModuleContent` 对应 `contracts/module.py`（B/C 共享契约，`ContractModel` 使用 `frozen=True` + `tuple`）。C 私有模型（`ModuleDraft`、`ValidationReport`、`ReviewReport`）定义在 `module/` 目录，不进入 `contracts/`。`contracts/module.py` 的修改需 B 共同评审。

---

## 一、动机 / 背景

AI DM 能主持跑团，但前提是有可运行的模组。目前模组只能由熟悉数据模型的开发者手写 JSON 录入——一个 50 页模组需要数天。Module Parser Agent 的目标是：用户上传 Markdown /PDF/Word等动编译为 Runtime 可加载的 `ModuleContent`，上传即玩。


**核心痛点**：

| 问题 | 影响 |
|------|------|
| 人工转写耗时巨大 | 无法规模化 |
| B/C 类规则遗漏无法自动检测 | 模组能跑但核心机制静默丢失（猫必须死、INT 成功反而疯狂） |
| 引用完整性靠人工保证 | Scene 引用不存在的 Entity、Checkpoint 悬空——人工容易漏 |
| 秘密泄漏无自动检查 | `secrets` 误放 `public_persona`，玩家提前知道真相 |
| 无来源追溯 | 字段存疑时无法快速定位原文出处 |

---

## 二、本期范围与明确不做

### 本期范围

```text
Phase 1（当前）：人工编写 demo-module.json
  → Validation（Layer 1）+ Review Pass（Layer 2）
  → 目标：跑通校验 + 审查管线，Review Pass 通过即自动发布

Phase 2（后续）：模组 Markdown 自动导入
  → 预处理 → Parser Pass（单次 LLM 调用）→ ModuleDraft
  → 汇入与 Phase 1 完全相同的 Validation → Review → 自动发布管线
  → 目标：上传 Markdown → 自动编译为 ModuleContent
```

**输入端**：Phase 1 人工 JSON，Phase 2 Markdown 文件。

**输出端**：`ModuleContent`——通过 Validation 的结构化模组数据，附带 `ValidationReport` 和可选的 `ReviewReport`。

**Pipeline 结构**：

```text
入口: 人工 demo-module.json / Markdown 模组
    │
    ▼
预处理（Phase 2，确定性代码）: Markdown 清洗 + 分段 + SourceFragment 生成
    │
    ▼
Parser Pass（Phase 2，LLM，单次调用）: 原文 → ModuleDraft
    │
    ▼
Validation（确定性代码，三层）:
  L1 Schema 校验: 类型/枚举/必填项/额外字段拒绝
  L2 引用完整性: Scene→Entity、Checkpoint→target、Rule→State、WinCondition→State
  L3 语义校验: Expr 语法、State 引用完整性、可达性、循环依赖
    │
    ▼
Review Pass（LLM）: A/B/C/D 覆盖度、秘密隔离、过度结构化、可执行性 → ReviewReport
    │
    └── 自动发布: 版本化 ModuleContent + 冻结 fixtures/evals（标注"AI 已审查"）
```

**质量分层**：

| 层级 | 触发条件 | 标注 | 体验 |
|------|---------|------|------|
| Layer 1 | Validation 通过 | "可运行" | 结构正确，能跑 |
| Layer 2 | + Review Pass 通过 | "AI 已审查" | B/C 遗漏显著降低，自动发布 |

**关键设计决策**：

1. **Parser Pass 用单次 LLM 调用，不拆两 Pass。** 两 Pass 的级联错误风险和双倍延迟抵消了拆分关注点的收益。单 Pass 所有信息在同一注意力窗口，Prompt 内分"基础信息 → 机制信息"两步。后续实测如果遗漏率过高，再考虑拆分。

2. **Parser 和 Review 是同一个 Module Parser Agent 的内部阶段。** 项目中只有两个一级 Agent：Module Parser Agent 和 Runtime Keeper Agent。不引入独立的 Reviewer Agent 或 Supervisor Agent。

3. **Validation 全部是确定性代码，零 LLM。** 引用完整性、类型检查、循环依赖检测——这些都是数学上可证明的，不需要语义理解。

### 明确不做

| 不做 | 原因 |
|------|------|
| PDF OCR 输入 | Phase 2 仅支持 Markdown。PDF 转 Markdown 有成熟工具链（PyMuPDF），作为预处理步骤而非 Parser 核心能力 |
| Multi-Pass Extraction | 先用单 Pass 实测，数据驱动决策 |
| 自动修复 Parser 错误 | Parser 输出错误 → 打回人工或重新生成，不自动修改 ModuleDraft |
| Multi-Agent 协作 | Parser 和 Review 是同一个 Agent 的内部阶段，不是多个 Agent |
| 完整 CoC 7e 规则校验 | Rule 的 Op 是否合法、hook 是否在 19 个内——这些是 Reviewer 和 Validation 的检查项，但完整规则实现属于 Runtime Keeper Agent 和引擎 |
| 数据库持久化 | Phase 1 以 JSON 文件为存储介质。PG 接入属于引擎侧（成员 B） |
| 在线编辑 / Web UI | CLI + JSON 文件。Web 界面属于后续迭代 |

---

## 三、关键决策与依据

### 决策 1：Module Parser 是一个 Agent，不是多个

| 选项 | 描述 | 结论 |
|------|------|------|
| Parser Agent + Reviewer Agent 两个独立 Agent | 更强的职责隔离 | ❌ 不采用 |
| 单一 Module Parser Agent，内含 Parser Pass + Review Pass | 更简单的接口，更低的编排成本 | ✅ 采用 |

**依据**：Parser 和 Reviewer 之间是单向数据流（ModuleDraft → ReviewReport），不是对话，不需要 Agent 间通信。拆成两个 Agent 只会增加接口数量和编排复杂度，不增加能力。

### 决策 2：Parser Pass 单次 LLM 调用

| 选项 | 描述 | 结论 |
|------|------|------|
| 两 Pass（Pass 1 基础 + Pass 2 机制） | 拆分关注点 | ❌ 不采用 |
| 单 Pass | 一次调用完成全部提取 | ✅ 采用 |

**依据**：
- 两 Pass 的级联错误风险：Pass 1 遗漏的实体，Pass 2 无法引用，产生断裂
- 两 Pass 的双倍延迟：串行等待，用户等待时间翻倍
- 两 Pass 的双倍 Token 开销：原文 + Pass 1 输出 + Pass 2 输出 > 原文 + 单次输出
- 单 Pass 内 Prompt 分两步组织（基础信息 → 机制信息），LLM 在同一个注意力窗口完成全部提取
- 若后续实测遗漏率过高，再拆——这是数据驱动的决策，不是提前的过早优化

### 决策 3：Validation 全部确定性代码

| 选项 | 描述 | 结论 |
|------|------|------|
| LLM 辅助校验 | 用 LLM 检查引用完整性和语义 | ❌ 不采用 |
| 纯代码校验 | Pydantic + 符号表 + 图算法 | ✅ 采用 |

**依据**：引用完整性（A 引用了 B，B 是否存在）是集合差运算。循环依赖（柜子需要钥匙，钥匙在柜子里）是图论。Expr 语法检查是解析器。这些不需要"理解自然语言"——它们需要"精确且可复现"。LLM 做不到精确，代码做不到理解。各管各的。

### 决策 4：Review Pass 通过后自动发布，不设人工审批

| 选项 | 描述 | 结论 |
|------|------|------|
| 人工审批作为发布前置条件 | 所有模组必须人工审核 | ❌ 不采用 |
| Review Pass 通过即自动发布 | AI 审查后直接发布 | ✅ 采用 |

**依据**：
- Layer 1（Validation）保障结构正确——能跑
- Layer 2（+ Review Pass）自动扫描 A/B/C/D 覆盖度——遗漏率显著降低但非零
- B 类遗漏（猫必须死）的后果是玩家卡关，可检测可修复
- C 类遗漏（INT 成功反而疯狂）的后果是游戏变简单，玩家不会立即发现
- 去除人工审批实现"上传 Markdown → 数分钟后可玩"的全自动体验
- 未来如需人工复核，作为独立的离线审计工具，不嵌入发布管线

---

## 四、基本概念与信息结构

### 6.1 核心术语

| 术语 | 定义 | 归属 |
|------|------|------|
| **ModuleContent** | 编译后的完整可执行模组数据。定义在 `contracts/module.py`（B/C 共享契约）。B 消费它执行规则。 | B/C 共享 |
| **ModulePack** | 模组的发布元数据。包含 title、authors、version、players_min/max、difficulty。存储在数据库中。当前无 Pydantic 模型。 | 物理层（DB 表） |
| **ModuleDraft** | Parser Pass 的原始输出。C 私有，定义在 `module/`。⚠️ 不可被 Runtime 加载。 | C 私有 |
| **ValidationReport** | Validation 阶段的输出。C 私有，确定性代码生成。 | C 私有 |
| **ReviewReport** | Review Pass 的输出。C 私有，LLM 生成。 | C 私有 |
| **Parser Pass** | Module Parser Agent 的第一阶段。LLM 调用，原文 → ModuleDraft。 | Agent 内部阶段 |
| **Review Pass** | Module Parser Agent 的第二阶段。LLM 调用，ModuleDraft + 原文 → ReviewReport。 | Agent 内部阶段 |
| **Rule** | `(hook, when, then, mode, priority)` 五元组。只能挂在 `Entity.rules` 或 `World.world_rules` 上。不存在顶层 Rule。 | 数据模型 |
| **SourceFragment** | 预处理阶段生成的文本块。携带稳定 ID 和原文定位，用于来源追溯。 | 中间产物 |

### 6.2 ModuleContent 结构

```python
# contracts/module.py — B/C 共享契约。frozen=True，tuple 不可变。
class ModuleContent(ContractModel):
    module_id: str
    version: str
    world_ref: str          # → World.id（如 "coc-7e"）
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]
    # 注意：没有顶层 rules。Rule 挂在 EntitySpec.rules 上。
    # 内含 validate_references() 校验跨引用完整性。
```

### 6.3 中间产物流转

```text
RawDocument          PDF/Markdown 原文 + 哈希
    ↓
SourceFragment[]    预处理产物。稳定 ID + 文本 + 定位
    ↓
ModuleDraft         Parser Pass 输出。source_references + confidence + unresolved_questions
    ↓
ValidationReport    Validation 输出。errors[] + warnings[] + status
    ↓
ReviewReport        Review Pass 输出。errors[] + warnings[] + human_review_checklist[]
    ↓
ModuleContent       最终产物。版本化，不可变。B/C 共享，B 消费执行规则。
```

### 6.4 三个核心接口

> 对本 Issue 的 Module Parser Agent 而言，`validate_module()` 是对外统一入口（与 Issue #48 的核心接口表一致）。`review_module()` 和 `publish_module()` 是其内部步骤，不暴露为跨系统接口。

| 接口 | 输入 | 输出 | 调用方 |
|------|------|------|--------|
| `validate_module(payload)` | ModuleContent JSON dict | `ModuleContent`（校验通过）或 `ValidationError` | 模组导入流程（对外统一入口，内部包含 Validation L1+L2+L3 → Review Pass） |
| `review_module(draft: ModuleDraft, source: str)` | ModuleDraft + 原文 | `ReviewReport` | Module Parser Agent 内部 |
| `publish_module(content: ModuleContent)` | 通过校验的 ModuleContent | 版本化 ModuleContent + 冻结 fixtures | Module Parser Agent 内部 |

---

## 五、原型 / Demo

### 7.1 Phase 1 原型

```text
输入: fixtures/demo-module.json（人工编写的书房场景）
  - 1 个 Scene（书房）
  - 5 个 Entity（管家、书架、柜子、文件、窗户）
  - 2 个 Checkpoint（调查书架、砸开柜子）
  - 2 个 WinCondition（找到文件、文件损毁）
  - A 类: cabinet.refuse_ops = ["open"]
  - D 类: bookshelf.key_found, cabinet.opened, document.obtained

流程:
  1. ModuleContent.model_validate(demo-module.json)     → Schema 校验
  2. validate_references(content)                       → 引用完整性
  3. validate_semantics(content)                        → 语义校验
  4. review_pass.run(draft, source=None)                → Review Pass

输出:
  - ModuleContent（通过全部质量门，自动发布）
  - ValidationReport { status: "pass" }
  - ReviewReport（包含 A/B/C/D 覆盖度）
```

### 7.2 Phase 2 原型（目标形态）

```text
输入: 模组 Markdown 文件

流程:
  1. 预处理: 分段 + SourceFragment 生成
  2. Parser Pass: 单次 LLM 调用 → ModuleDraft
  3. Validation: L1 + L2 + L3
  4. Review Pass: LLM 审查 → ReviewReport
  5. 发布: Review Pass 通过 → 自动发布（标注"AI 已审查"）

输出: 可被 Runtime Keeper Agent 直接加载的 ModuleContent
```

### 7.3 CLI 使用方式

```bash
# Phase 1: 校验人工 Demo
uv run agent-collab-validate --input fixtures/demo-module.json

# Phase 2: 自动导入模组
uv run agent-collab-parse --input module.md --output module-content.json

# 带 Review Pass
uv run agent-collab-parse --input module.md --review --output module-content.json
```

---

## 六、验收标准

### Phase 1（当前）

- [ ] `contracts/module.py` 中的 `RuleSpec` 结构对齐 `数据模型设计.md §5.3`（Issue 1，需 B 共同评审）
- [ ] `fixtures/demo-module.json` 覆盖 A/B/C/D 四类机制，每一项有对应的测试用例（Issue 2）
- [ ] `module/validation.py` 扩展为 Validation Layer 1+2：对合法 Demo 返回 pass，对非法输入（重复 ID、悬空引用、顶层 rules）返回明确的 error code（Issue 3）
- [ ] Review Pass 可对 `demo-module.json` 产出 `ReviewReport`，包含 `human_review_checklist`
- [ ] 成员 B 可基于 Phase 1 产出的 `ModuleContent` 执行 Rule/Checkpoint/WinCondition
- [ ] 10+ 条 fixture case 覆盖：合法 Demo 通过、非法枚举拒绝、重复 ID 拒绝、悬空引用拒绝、顶层 rules 拒绝

### Phase 2（后续）

- [ ] Markdown 输入 → Parser Pass（单次 LLM 调用）→ ModuleDraft 可运行
- [ ] Parser Pass 输出的每个字段携带 `source_references`
- [ ] `unresolved_questions` 正确标记 Parser 无法确定的段落
- [ ] Review Pass 对真实模组产出有效的 `human_review_checklist`
- [ ] "上传 Markdown → Layer 2 自动发布"端到端流程跑通
- [ ] 至少 1 个真实 CoC 模组通过完整 Pipeline 并可在 Runtime 中运行
- [ ] Parser 输出的 `ModuleContent` 与人工标准答案的结构一致（字段级对比）

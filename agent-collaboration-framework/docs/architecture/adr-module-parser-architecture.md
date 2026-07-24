# ADR: Module Parser 实施架构

- 编号：ADR-MODULE-PARSER-ARCH-001
- 状态：Accepted
- 日期：2026-07-23
- 决策范围：Module Parser Agent 的完整链路、技术选型和模块边界
- 替代：`important_docs/unified-trpg-data-contract-adr.md`、`docs/architecture/data-model-alignment-rfc.md`（两者内容已吸收进本文）

---

## 1. 完整链路（已冻结）

```
PDF / DOCX / Markdown / TXT
    │
    ▼
DocumentAdapter（确定性 Python，非 LLM）
    │  格式统一转换 → NormalizedDocument
    │  分段 + 来源编号 → SourceFragment[]
    ▼
ParserModelPort（LLM Adapter 边界）
    │  Input:  SourceFragment[] + RulesetSnapshot
    │  Output: ParserResult { draft: ModuleDraft, provenance, gaps }
    ▼
ModuleDraft（C 内部，与 ModuleContent 同形，可带缺失字段）
    │
    ▼
Validation（确定性 Python，三层，非 LLM）
    │  L1 Schema · L2 引用完整性 · L3 语义
    │  Output: ValidationReport { pass | needs_revision | blocked }
    │
    ├── pass ──────────────────────────────────────────┐
    │                                                   ▼
    ├── needs_revision ──→ 打回修正 ──→ ModuleDraft ──→ Validation（重新校验）
    │                                                   │
    └── blocked ──→ 人工介入（原文缺失、Schema 不支持等）    │
                                                        ▼
                                              ModuleContent（通过校验）
                                                        │
                                                        ▼
                                              Review Pass（LLM，Phase 2）
                                                        │
                                              ┌─ pass ──→ Publish → Runtime
                                              │
                                              └─ needs_revision ──→ 打回修正
```

**三层回环**：

| 回环 | 触发条件 | 回到哪里 |
|------|---------|---------|
| Validation → Parser | `needs_revision`：结构/引用/语义错误 | 回到 ModuleDraft，修正后重新校验 |
| Validation → 人工 | `blocked`：原文缺失、Schema 不支持、关键规则无法表达 | 人工判断：补充原文、扩展 Schema 或接受为 Capability Gap |
| Review → Parser | Review Pass 发现遗漏（B/C 类规则缺失、秘密泄漏） | 回到 ModuleDraft，修正后重新跑 Validation → Review |

**关键约束**：
- `ModuleDraft` 不能被 Runtime 直接加载。Validation 是唯一转换入口。
- Agent 不得绕过 Validation、直接修改 Runtime 或发布未通过的 Draft。
- Review Pass 在 Phase 2 实现；Phase 1 人工编写的 Draft 通过 Validation 后直接 Publish。
- 相同输入每次校验产生相同结果（Validation 是确定性纯函数）。

---

## 2. 技术选型（已冻结）

| 层 | 用什么 | 不用什么 |
|----|--------|---------|
| 预处理 | 普通 Python（PyMuPDF 等） | 非 LLM |
| Parser Pass | LLM，通过 `ParserModelPort` Adapter | — |
| Review Pass | LLM，通过 `ReviewModelPort` Adapter | 仅在最小 Parser 产生真实结果后实现 |
| Validation | 普通 Python + Pydantic | 非 LLM |
| Publish | 普通 Python | 非 LLM |
| 编排 | 普通 Python async（当前 Orchestrator） | 不引入 LangGraph |
| Agent SDK | 候选默认 OpenAI Agents SDK；PydanticAI 为对比候选 | 不侵入 Validation / Publish / Runtime |

**LangGraph 引入条件**：仅当出现以下至少一项时重新评估——跨进程暂停恢复、复杂循环编排、持久化 Human-in-the-loop 恢复。当前所有流程均为线性单次执行，不需要。

**Agent SDK 边界**：仅进入 `host/adapters/` 和未来的 `module/adapters/`，作为 `ParserModelPort` / `NarrationModelPort` 的 Adapter 实现。不进入 `contracts/`、`engine/`、`module/validation.py`。

---

## 3. ParserModelPort 接口

```
Input:
  · SourceFragment[]       — 预处理后的文本段，携带稳定 ID 和原文定位
  · RulesetSnapshot        — CheckCandidateSnapshot，仅含合法候选 ID 集合

Output:
  · ParserResult
      ├── draft: ModuleDraft          — 与 ModuleContent 同形
      ├── provenance                  — 字段 → SourceFragment 映射
      ├── normalization_decisions     — Parser 自动处理的歧义及依据
      ├── unresolved_questions        — 无法自信提取的段落
      └── capability_gaps             — 当前 Contract 无法表达的内容
```

**设计决策**：
- `ModuleDraft` 与目标 `ModuleContent` 同形——Parser 直接生成目标结构，不经过中间 Domain Model 再转换
- 来源引用、置信度、模型/ Prompt 版本等审计信息放在 `ParserResult` sidecar，不进入 `ModuleContent`
- Capability Gap 记录"原文有、但当前 Contract 装不下"的机制，供后续 Contract 扩展参考

---

## 4. Review Pass 定位与发布门禁

Review Pass 没有取消。它在最小 Parser 和黄金样例产生真实结果后实现。

| 阶段 | Review Pass 状态 |
|------|-----------------|
| Phase 1（当前） | 不实现。人工编写的 demo-module.json 直接经 Validation 发布 |
| Phase 2（Parser 接入后） | 实现。Parser 输出 → Validation → Review Pass → 自动发布 |
| Review Pass 输入 | ModuleDraft + 原文 |
| Review Pass 输出 | ReviewReport { errors, warnings, human_review_checklist } |

### 发布门禁策略（已冻结）

```
Validation 通过
    │
    ▼
Review Pass
    │
    ├── pass ──→ 自动发布（标注"AI 已审查"）
    │
    └── needs_revision ──→ 打回 Parser，修正后重新跑 Validation → Review
```

**不设人工审批**。依据：
- Layer 1（Validation）保障结构正确——能跑
- Layer 2（+ Review Pass）自动扫描 A/B/C/D 覆盖度——遗漏率显著降低但非零
- B 类遗漏（猫必须死）的后果是玩家卡关，可检测可修复
- C 类遗漏（INT 成功反而疯狂）的后果是游戏变简单，玩家不会立即发现
- 去除人工审批实现"上传 Markdown → 数分钟后可玩"的全自动体验
- 未来如需人工复核，作为独立的离线审计工具，不嵌入发布管线

---

## 5. 模块边界

```
contracts/module.py       B/C 共享，ModuleContent + Spec 定义
module/                    C 内部：validation.py / models.py / publish.py / import_workflow.py
module/adapters/           未来 Parser Pass / Review Pass 的 LLM Adapter
engine/                    B 内部：确定性执行，不 import host 或 module
host/                      A 内部：不 import engine 或 module
ports/                     A/B 跨组件接口：ActionExecutor / PlayerViewSource
bootstrap/                 组合根：唯一知道具体实现并完成装配
```

---

## 6. 与后端的关系

```
前端 / SDK / 后端 API（trpg-backend）
    │
    │  POST /modules/import（未来异步 Job）
    │  GET /systems/{systemId}/ruleset → RulesetRead
    │
    ▼
组合根（bootstrap）
    │  world_ref → GameSystem 映射
    │  RulesetRead → CheckCandidateSnapshot 转换
    │  注入 Validation
    ▼
agent-collaboration-framework（本仓库）
```

- Module Parser 不直接调用后端 API。组合根负责 world_ref 到 GameSystem 的映射和 Snapshot 注入。
- 后端 `coc7_content.py` 是属性/技能标准 ID 的权威源。框架侧 Demo 已对齐（`STR` / `spot-hidden`）。
- LLM 调用由 Agent Framework 侧管理，不经过后端 API。

---

## 7. 能力完成定义

每项能力同时满足以下条件才算 Supported：

1. 三方接受领域语义
2. `contracts/module.py` 已实现
3. ModuleDraft 已对齐
4. Parser 能从至少一个真实样本生成
5. Validation 有稳定错误码
6. Runtime 有明确 consumer
7. 正向、负向和端到端测试通过

---

## 8. P1 完成标准

```
✅ 完整链路已冻结（DocumentAdapter → SourceFragment → Parser → Validation → Publish → Runtime）
✅ 技术选型已冻结（何处 Agent SDK、何处普通 Python、不引入 LangGraph）
✅ ParserModelPort 输入输出已定义
✅ Review Pass 定位已明确（Phase 2 实现，不取消）
✅ Agent SDK 边界已明确（仅模型 Adapter，不侵入 Validation/Publish/Runtime）
✅ Module Parser Agent 是一级业务边界，Parser/Review Pass 是内部阶段
```

团队能够明确回答：**预处理和校验用普通 Python，Parser Pass 和 Review Pass 用 LLM Adapter，Review Pass 在 Phase 2 Parser 产出真实结果后接入，当前不引入 LangGraph。**

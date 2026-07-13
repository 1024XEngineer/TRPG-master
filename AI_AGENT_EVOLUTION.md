# AI_AGENT_EVOLUTION.md — AI Agent 最终架构方案

> 日期：2026-07-13
> 角色：AI Agent 架构负责人
> 基础：AI_AGENT_DESIGN.md + 数据模型设计.md + 如何应对动态机制.md
> 原则：**确定性的归代码，叙事表达的归 AI，真相(God View)只有一个出口**

---

## 〇、架构宪法（不可协商）

```
┌────────────────────────────────────────────────────────────┐
│                      代码负责（永远）                        │
│                                                             │
│  · 状态修改 (GameState 的唯一切入点)                          │
│  · 规则裁决 (D100 检定、SAN 计算、战斗结算)                    │
│  · 权限判断 (ViewProjector: GodView → PlayerView)            │
│  · 骰子检定 (随机数生成 + 六级判定)                           │
│  · Event 记录 (append-only，权威真相)                         │
│  · A/B/C/D 四类引擎介入 (refuse_ops / Rule / entity_states)   │
│  · Hook 求值 ((hook, when, then) 三元组)                     │
│  · Scope 裁剪 (Resolution.narration_context 的组装)           │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│                      AI 负责（永远）                         │
│                                                             │
│  · 自然语言理解 (utterance → 结构化意图)                     │
│  · 叙事表达 (Resolution + PlayerView → 沉浸式文本)            │
│  · NPC 对话 (基于 publicPersona 的角色扮演)                   │
│  · 氛围塑造 (场景描述、感官细节、情绪渲染)                     │
│  · 软判据求值 (roleplay 质量 → 枚举，供代码读)                 │
│  · 模组解析 (PDF → ModulePack，离线，有人工审核)               │
│  · 复盘生成 (EventLog → 叙事性复盘，离线，游戏结束后)             │
└────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────┐
│                   AI 永远不能做的事                           │
│                                                             │
│  · 接收 GameState（类型级强制：只接受 PlayerView）             │
│  · 写 GameState（Narrator 只返回文本流）                      │
│  · 看到 secrets（PlayerView 不含此字段）                      │
│  · 决定检定结果（那是 Rules 的事）                            │
│  · 决定谁能看到什么（那是 ViewProjector 的事）                 │
│  · 发明新动作类型（Intent.action.type 是有限枚举）              │
│  · 发明新技能名（只能引用 World.skillCatalog 内的技能）          │
│  · 编造 entity_states 的键（只能提议 op，引擎校验后执行）       │
└────────────────────────────────────────────────────────────┘
```

---

## 一、AI Agent 最终能力地图

### 1.1 能力全景

```
                         ┌───────────────────────────┐
                         │      AI Agent 系统         │
                         │                           │
                         │  ┌─────────────────────┐  │
                         │  │   Runtime（在线）     │  │
                         │  │                     │  │
           玩家 utterance │  │  IntentParser  P0   │  │
          ───────────────▶│  │  IntentValidator P1 │  │
                         │  │  Narrator      P0   │  │
          Resolution ───▶│  │  ContextBuilder P0  │  │
                         │  │  PromptRegistry P0  │  │
                         │  │  LLMAdapter    P0   │  │
                         │  │  RAGRetriever  P1   │  │
                         │  │  Summarizer    P1   │  │
                         │  └─────────────────────┘  │
                         │                           │
                         │  ┌─────────────────────┐  │
                         │  │   Offline（离线）     │  │
                         │  │  ModuleParser   P2   │  │
                         │  │  ReplayWriter   P2   │  │
                         │  └─────────────────────┘  │
                         └───────────────────────────┘
```

### 1.2 每个能力的判定：要还是不要

| 能力 | 存在？ | 理由 |
|------|--------|------|
| **IntentParser** | ✅ 必要 | NL → Intent 是 AI Agent 的唯一入口。没有它，玩家只能点按钮 |
| **Narrator** | ✅ 必要 | Resolution → 叙事是 AI Agent 的唯一出口。没有它，引擎输出的是裸 JSON |
| **ContextBuilder** | ✅ 必要 | 每次 LLM 调用前的上下文组装。纯确定性代码，不是 LLM 调用 |
| **LLMAdapter** | ✅ 必要 | 供应商抽象。不可绑死一家 |
| **PromptRegistry** | ✅ 必要 | System Prompt 模板管理。人格（旁白/NPC/答疑）各自独立 |
| **IntentValidator** | ✅ 必要 | LLM 生成的 Intent 不可信。必须过 7 项校验才能进引擎 |
| **RAGRetriever** | ✅ 需要 | 规则书知识库。P1 而非 P0——MVP 可不依赖规则书检索 |
| **Summarizer** | ✅ 需要 | 长对话必然要压缩历史。但它不是独立 Agent，是 ContextBuilder 的子组件 |
| **ModuleParser** | ✅ 需要 | 离线能力。降低模组导入成本。但 MVP 可手写 JSON |
| **ReplayWriter** | ✅ 需要 | 离线能力。EventLog → 叙事性复盘。与 Summarizer 不同：Summarizer 是给 LLM 的压缩上下文，ReplayWriter 是给人读的故事性复盘。P2——V3 实现。但 EventLog 从 Day 1 就记录，历史数据不会丢 |
| **Director** | ❌ 不要 | 这是最危险的模块。AI 不能决定"剧情该往哪走"——那是模组作者+引擎的事。AI 只能**表达**结果，不能**选择**方向 |
| **MemoryManager** | ❌ 不要 | 不是独立模块。EventLog（代码层）+ rolling_summary（GameState）+ ContextBuilder（上下文组装）已覆盖 |
| **NPCActor** | ❌ 不要 | 不是独立模块。Narrator 通过 `persona="npc:{id}"` 路由到 NPC 人格 Prompt 即可。同一套 LLM，不同 System Prompt |
| **GuidanceAgent** | ❌ 不要 | 玩家卡关提示。本质上是一次特殊的 Narrator 调用（`persona="hint"`）+ ContextBuilder 注入未发现线索列表。复用，不新建 |

### 1.3 为什么 Director 必须砍掉

Director 的诱惑很大：让 AI 理解剧情走向，在玩家迷茫时主动推进。但这会打开一个**不可逆的边界溃烂**：

```
Director 说"该进入下一幕了"
    → 它需要知道"下一幕是什么" → 它需要读 ModulePack 的剧情图
    → 它需要判断"条件满足了吗" → 它需要读 entity_states 和 WinCondition.expr
    → 它需要写"现在进入场景 X" → 它需要写 GameState

这是链条式的越权。每一步单独看都合理，但最终 AI 变成了引擎。
```

**Director 的合法功能已经被拆解**：

| Director 想做 | 谁真正在做 | 怎么做 |
|---|---|---|
| 决定下一幕 | Orchestrator + WinCondition.expr | 表达式求值，不是 LLM |
| 推动剧情 | B 类 Rule (on_scene_enter) | 引擎主动触发，不是 AI 想起来 |
| 给提示 | Narrator persona="hint" | LLM 只生成文本，不决定内容 |
| 判断进度 | ContextBuilder 注入未发现线索列表 | 代码组装，LLM 只看不写 |

---

## 二、MVP 阶段模块清单（2 周跑通闭环）

### 2.1 MVP 目标

> **输入一句话，走完整条链路，输出一句话。**

```
玩家说："我搜索书房的抽屉"
    → IntentParser  → { action: "search", target: "desk_drawer" }
    → Rules Engine  → Resolution { check_result: {...}, narration_context: {...} }
    → Narrator      → "你在抽屉夹层里摸到一个泛黄的信封……"
```

### 2.2 MVP 模块清单

| # | 模块 | 级别 | 实现策略 | 产出 |
|---|------|------|---------|------|
| 1 | **LLMAdapter** | P0 基础 | 对接单一供应商（DeepSeek 或 Claude），支持流式输出 | `async generate_stream(prompt) -> AsyncIterator[str]` |
| 2 | **PromptRegistry** | P0 基础 | 两个模板：旁白人格 + 基础意图解析。加载机制（文件/代码内嵌） | 两个 `.md` prompt 模板 |
| 3 | **IntentParser** | P0 核心 | LLM 模式（System Prompt 约束输出 Intent JSON）+ **关键词兜底**（LLM 不可用时降级为规则匹配） | `parse_intent(utterance, playerView, sceneContext, history) -> Intent` |
| 4 | **Narrator** | P0 核心 | 单一旁白人格，流式输出 | `narrate(resolution, playerView, persona, sceneContext) -> AsyncIterator[str]` |
| 5 | **ContextBuilder** | P0 核心 | MVP 简化版：不做摘要，直接截断最近 6 轮 TurnRecord | `build_context(playerView, sceneContext, history) -> LLMContext` |
| 6 | **IntentValidator** | P0 基础 | MVP 只做技能名白名单校验（对照 World.skillCatalog） | 不合法 Intent → 返回澄清请求 |

### 2.3 MVP 不做什么

| 不做 | 理由 |
|------|------|
| Summarizer（历史摘要） | MVP 对话短，截断就够 |
| RAGRetriever | 规则书检索不是跑通闭环的前提 |
| NPC 多人格 | MVP 只需要旁白 |
| ModuleParser | 模组手写 JSON |
| 模型路由（小模型意图/强模型旁白） | MVP 一个模型全包 |
| 成本计量 | 先跑通再说 |
| 评测集 | 先跑通再说 |

### 2.4 MVP 的硬边界

```
IntentParser 只能：
  · 接收 PlayerView（不是 GameState）
  · 输出 action.type ∈ { skill_check, move, interact, use_item, observe, talk }
  · 引用的 skill 必须在 World.skillCatalog 内
  · 引用的 target 必须在当前 PlayerView 可见范围内

Narrator 只能：
  · 接收 Resolution + PlayerView（不是 GameState）
  · 返回文本流
  · 不能提议 op（MVP 阶段 Narrator 纯输出文本，不承担状态变更建议）
```

---

## 三、每个 Agent 模块的输入/输出/依赖

### 3.1 IntentParser

```
┌─────────────────────────────────────────────────────────────┐
│ IntentParser                                                 │
│                                                              │
│ 输入:                                                        │
│   utterance     string           玩家原始自然语言              │
│   playerView    PlayerView       经 ViewProjector 裁剪的视角   │
│   sceneContext  SceneContext     当前场景信息                  │
│                 {                                                 │
│                   sceneId: SceneId                                 │
│                   title: string                                    │
│                   description: text   ← 供 LLM 理解场景            │
│                   interactables: []   ← 当前场景可交互实体列表       │
│                 }                                                 │
│   history       TurnRecord[]      最近 N 轮（MVP: ≤6 轮）        │
│                 {                                                 │
│                   intent: Intent                                   │
│                   resolution: Resolution                           │
│                   narration: string  ← 已生成的叙事文本             │
│                 }                                                 │
│                                                              │
│ 输出:                                                        │
│   intent        Intent            结构化游戏动作               │
│                                                              │
│ 依赖的稳定模型:                                                │
│   ✅ PlayerView       (只读)                                  │
│   ✅ Intent           (产出)                                  │
│   ✅ World.skillCatalog  (技能合法性校验用)                     │
│   ❌ GameState        (禁止——类型级强制)                       │
│   ❌ Entity.secrets   (PlayerView 不含此字段，天然隔离)         │
│                                                              │
│ 降级策略:                                                     │
│   关键词匹配 + 场景可交互对象列表 → 生成菜单选项给玩家选择        │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Narrator

```
┌─────────────────────────────────────────────────────────────┐
│ Narrator                                                     │
│                                                              │
│ 输入:                                                        │
│   resolution    Resolution       引擎裁决结果                 │
│                 {                                                 │
│                   narration_context: {                              │
│                     scope: "location" | "private" | "party"         │
│                     outcome: "success" | "fail" | ...               │
│                     visible_facts: string[]   ← 已过 Scope 裁剪     │
│                     reveal_text?: string                            │
│                     style_hint: string                              │
│                   }                                                 │
│                   ai_private?: {                                    │
│                     npc_mood?: string                               │
│                     foreshadowing?: string                          │
│                   }                                                 │
│                 }                                                 │
│   playerView    PlayerView       更新后的视角（检定/移动后的状态）  │
│   persona       "narrator"       旁白/NPC/答疑 人格标识             │
│                 | "npc:{id}"                                       │
│                 | "qa"                                              │
│                 | "hint"                                            │
│   sceneContext  SceneContext     当前场景信息                       │
│                                                              │
│ 输出:                                                        │
│   narration     AsyncIterator[str]  流式叙事文本               │
│                                                              │
│ 依赖的稳定模型:                                                │
│   ✅ Resolution      (只读——只读 narration_context + ai_private)│
│   ✅ PlayerView      (只读)                                   │
│   ❌ GameState       (禁止)                                   │
│   ❌ Resolution.state_changes  (禁止——叙事不需要知道状态怎么变) │
│   ❌ Entity.secrets  (禁止——PlayerView 不含此字段)             │
│                                                              │
│ 人格路由:                                                     │
│   persona="narrator"    → 旁白人格 System Prompt              │
│   persona="npc:{id}"    → 加载 Entity.publicPersona           │
│                           注入 NPC 名字/年龄/性格/已知信息      │
│                           System Prompt 约束"用角色语气说话"    │
│   persona="qa"          → 答疑人格（规则问题回答）              │
│   persona="hint"        → 引导人格（晦涩提示，不直接给答案）    │
│                                                              │
│ 降级策略:                                                     │
│   LLM 超时 → 返回预设过渡文本（如"守秘人沉思中……"）             │
│   流式中断 → 已生成的 chunk 正常下发，末尾加省略号               │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 ContextBuilder

```
┌─────────────────────────────────────────────────────────────┐
│ ContextBuilder（纯确定性代码，不调 LLM）                       │
│                                                              │
│ 输入:                                                        │
│   playerView    PlayerView       玩家当前视角                 │
│   sceneContext  SceneContext     当前场景                     │
│   history       TurnRecord[]     完整历史（MVP：最近 6 轮）    │
│   persona       string           目标人格（用于选择裁剪策略）  │
│   moduleContext ModuleContext    模组世界观/风格文本（可选）    │
│                                                              │
│ 输出:                                                        │
│   llmContext    LLMContext       组装好的 LLM 调用上下文       │
│                 {                                                 │
│                   systemPrompt: string    ← 从 PromptRegistry 取  │
│                   userMessages: [{role, content}]                  │
│                   tokenBudget: { used, max }                       │
│                 }                                                 │
│                                                              │
│ 核心逻辑:                                                     │
│   1. 从 PromptRegistry 取人格对应的 System Prompt              │
│   2. 注入 sceneContext.description（场景描述，可缓存）          │
│   3. 注入 moduleContext.worldTone（世界观风格，可缓存）         │
│   4. 注入 playerView 的可见信息（角色状态、已知线索）            │
│   5. 注入 history（最近的 TurnRecord，截断至 token 预算内）     │
│   6. 注入 Entity.publicPersona（仅当 persona="npc:{id}"）      │
│                                                              │
│ Token 预算:                                                   │
│   MVP：硬截断最近 6 轮，不做摘要                               │
│   V2：Summarizer 压缩早期历史                                  │
│   上限 ~2500 token                                            │
│                                                              │
│ 依赖的稳定模型:                                                │
│   ✅ PlayerView      (只读)                                   │
│   ✅ SceneContext    (只读)                                   │
│   ✅ EventLogEntry   (只读，用于组装 history)                  │
│   ✅ Entity.publicPersona  (只读，NPC 人格需要)               │
│   ❌ GameState       (禁止)                                   │
│   ❌ Entity.secrets  (禁止——永远不进上下文)                    │
└─────────────────────────────────────────────────────────────┘
```

### 3.4 LLMAdapter

```
┌─────────────────────────────────────────────────────────────┐
│ LLMAdapter（纯确定性代码，不调 LLM——它是 LLM 调用的封装）      │
│                                                              │
│ 输入:                                                        │
│   llmContext    LLMContext      ContextBuilder 的产出          │
│   options       CallOptions     调用选项                      │
│                 {                                                 │
│                   stream: bool          ← 是否流式                │
│                   timeoutMs: int       ← 超时 (默认 8000)         │
│                   retries: int         ← 重试次数 (默认 2)         │
│                   temperature: float                              │
│                 }                                                 │
│                                                              │
│ 输出:                                                        │
│   (流式)        AsyncIterator[str]                             │
│   (非流式)      string                                         │
│                                                              │
│ 抽象接口:                                                     │
│   class BaseLLMAdapter:                                        │
│       async def generate(prompt, options) -> str               │
│       async def generate_stream(prompt, options) -> AsyncIterator│
│                                                              │
│ 实现:                                                        │
│   DeepSeekAdapter   ← MVP 推荐（成本低、中文好）               │
│   ClaudeAdapter     ← 高质量叙事场景                            │
│                                                              │
│ 不依赖任何数据模型——它是纯传输层。                               │
└─────────────────────────────────────────────────────────────┘
```

### 3.5 PromptRegistry

```
┌─────────────────────────────────────────────────────────────┐
│ PromptRegistry（纯确定性代码）                                 │
│                                                              │
│ 管理人格 → System Prompt 模板的映射。                           │
│                                                              │
│ MVP 人格清单:                                                 │
│                                                              │
│   narrator (旁白)                                              │
│     输入上下文: sceneContext + resolution.narration_context    │
│     风格约束: 克苏鲁式模糊不安，多用感官描写，50-150 字/段      │
│     C 类风格基调: 1920s 侦探档案美学                           │
│                                                              │
│   intent_parser (意图解析)                                     │
│     输入上下文: playerView + sceneContext.interactables        │
│     输出约束: Intent JSON Schema，action.type 有限枚举          │
│     防御约束: 只能引用 World.skillCatalog 内的技能               │
│                                                              │
│ V2 扩展:                                                      │
│   npc:{id} (NPC 对话)     ← 注入 Entity.publicPersona           │
│   qa (规则答疑)           ← 注入 RAG 检索结果                   │
│   hint (引导提示)         ← 注入未发现线索列表                   │
│                                                              │
│ 依赖的稳定模型: 无（只加载模板文本）                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.6 IntentValidator

```
┌─────────────────────────────────────────────────────────────┐
│ IntentValidator（纯确定性代码）                                │
│                                                              │
│ 输入:                                                        │
│   intent        Intent           LLM 生成的 Intent            │
│   playerView    PlayerView       当前玩家视角                  │
│   sceneContext  SceneContext     当前场景                      │
│   skillCatalog  SkillDef[]       World.skillCatalog 的技能列表 │
│                                                              │
│ 输出:                                                        │
│   result        ValidationResult                              │
│                 | { valid: true, intent: Intent }              │
│                 | { valid: false, reason: string }             │
│                                                              │
│ MVP 校验项（4 项）:                                            │
│   1. action.type ∈ 合法枚举 {skill_check,move,interact,        │
│                              use_item,observe,talk}            │
│   2. skill（如有）∈ skillCatalog                              │
│   3. target（如有）∈ sceneContext.interactables                │
│   4. confidence ≥ 阈值（如 0.5）                               │
│                                                              │
│ V2 扩展（完整 7 项，继承 LMX-1 §6.4）:                          │
│   5. 物品持有校验（use_item 要求 item ∈ playerView.inventory）  │
│   6. 出口合法校验（move 要求 via_exit ∈ sceneContext.exits）    │
│   7. 修正来源校验（modifiers 的来源必须合法）                   │
│                                                              │
│ 校验失败的处理:                                                │
│   → 返回澄清请求给前端，让玩家重新表述                          │
│   → 不调用 Rules（不浪费引擎资源）                              │
│                                                              │
│ 依赖的稳定模型:                                                │
│   ✅ Intent          (校验目标)                                │
│   ✅ PlayerView      (校验依据)                                │
│   ✅ World.skillCatalog  (技能白名单)                          │
│   ❌ GameState       (不需要)                                  │
└─────────────────────────────────────────────────────────────┘
```

### 3.7 Summarizer（V2）

```
┌─────────────────────────────────────────────────────────────┐
│ Summarizer（V2，可调 LLM 小模型 或 纯规则）                    │
│                                                              │
│ 输入:                                                        │
│   history       TurnRecord[]     完整历史                     │
│   maxTokens     int              目标摘要长度                  │
│                                                              │
│ 输出:                                                        │
│   summary       string           压缩后的历史摘要              │
│                 "第1-3轮：调查员进入书房，发现锁着的抽屉。       │
│                  第4-6轮：撬锁成功，找到日记……"                 │
│                                                              │
│ 策略（渐进式）:                                               │
│   V2.1：纯规则合并——同场景连续事件合并为一句                    │
│   V2.2：调小模型做摘要                                        │
│   V2.3：滚动窗口 + 关键事件锚点（EventLog 有标记的重要事件保留） │
│                                                              │
│ 依赖的稳定模型:                                                │
│   ✅ EventLogEntry    (只读)                                  │
│   ❌ GameState        (不需要)                                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.8 RAGRetriever（V2）

```
┌─────────────────────────────────────────────────────────────┐
│ RAGRetriever（V2，纯确定性代码 + Embedding 模型）              │
│                                                              │
│ 输入:                                                        │
│   query         string            玩家的规则问题               │
│   worldId       WorldId           规则系统标识 (如 "coc-7e")  │
│                                                              │
│ 输出:                                                        │
│   passages      RulePassage[]     检索到的规则段落              │
│                 [{ source: "CoC7e_zh.pdf", chapter: "战斗",     │
│                    content: "近战攻击中……", relevance: 0.92 }] │
│                                                              │
│ 调用时机:                                                     │
│   1. 玩家问规则问题 → 注入 Narrator persona="qa" 的上下文      │
│   2. AI 需要参考怪物特殊能力 → 注入 ContextBuilder 的上下文    │
│                                                              │
│ 依赖的稳定模型: 无（它只读向量数据库）                          │
└─────────────────────────────────────────────────────────────┘
```

### 3.9 ReplayWriter（V3）

```
┌─────────────────────────────────────────────────────────────┐
│ ReplayWriter（V3，离线，游戏结束后一次调用）                    │
│                                                              │
│ 职责: EventLog + 叙事文本 → 故事性复盘                         │
│                                                              │
│ 与 Summarizer 的本质区别:                                      │
│   Summarizer: 压缩历史 → 给 LLM 看（降低 token 成本）          │
│   ReplayWriter: 重组历史 → 给人读（终局体验）                   │
│                                                              │
│ 输入:                                                        │
│   eventLog      EventLogEntry[]  完整的事件序列                │
│                 （每轮含: utterance → Intent → Resolution     │
│                           → 生成的叙事文本 → timestamp）       │
│   characters    Character[]      参与玩家的角色卡               │
│   moduleMeta    ModulePack.meta  模组标题/作者/简介            │
│   winCondition  WinCondition     触发的结局条件                │
│                                                              │
│ 输出:                                                        │
│   replay        string           故事性复盘文本                │
│                 结构:                                          │
│                   ## 案件档案                                   │
│                   ## 调查员                                     │
│                   ## 事件时间线（叙事化，非裸数据）               │
│                   ## 关键抉择                                   │
│                   ## 结局                                       │
│                   ## 数据统计（可选）                            │
│                                                              │
│ 禁止访问:                                                     │
│   ❌ GameState — 游戏已结束，从 EventLog 重建即可               │
│   ⚠ Entity.secrets — 仅当 WinCondition 显式标记                │
│      reveal_on_ending: true 时才注入                           │
│                                                              │
│ 依赖的稳定模型:                                                │
│   ✅ EventLogEntry    (只读，权威真相)                          │
│   ✅ Character        (只读，角色信息)                          │
│   ✅ ModulePack.meta  (只读，模组信息)                          │
│   ✅ WinCondition     (只读，决定揭示哪些秘密)                   │
│   ❌ GameState        (不需要)                                  │
│                                                              │
│ 独立模型？                                                     │
│   是。使用强模型（与 Narrator 相同级别）                         │
│   理由: 复盘是游戏体验的终章，质量影响整体印象                    │
│                                                              │
│ 降级策略:                                                     │
│   事件时间线纯文本（EventLog 按时间排列，不加修饰）               │
│                                                              │
│ MVP 状态: ❌ 不在 MVP。但 EventLog 数据从 Day 1 就开始记录      │
│           V3 上线后可对历史对局批量生成复盘                      │
└─────────────────────────────────────────────────────────────┘
```

---

## 四、模型访问边界（类型级强制）

### 4.1 允许进入 Agent 的模型

| 模型 | 哪个 Agent 用 | 访问方式 | 约束 |
|------|-------------|---------|------|
| **PlayerView** | IntentParser, Narrator, ContextBuilder | 只读 | ViewProjector 是唯一出口。Agent 不能绕过它 |
| **Intent** | IntentValidator | 读写（校验+修改） | IntentParser 产出，Validator 校验后传给引擎 |
| **Resolution** | Narrator | 只读 | 只能访问 `narration_context` + `ai_private`。不能读 `state_changes` |
| **EventLogEntry** | ContextBuilder, Summarizer | 只读 | 用于组装历史上下文 |
| **SceneContext** | IntentParser, Narrator, ContextBuilder | 只读 | 从 ModulePack 提取，不含 secrets |
| **Entity.publicPersona** | ContextBuilder (NPC 人格) | 只读 | NPC 对话时注入 |
| **World.skillCatalog** | IntentValidator | 只读 | 技能白名单 |
| **TurnRecord** | ContextBuilder | 只读 | 历史记录（Intent + Resolution + 已生成叙事） |

### 4.2 绝对禁止进入 Agent 的模型

| 禁止模型 | 原因 | 强制方式 |
|---------|------|---------|
| **GameState** | AI 不能看到 God View。信息泄漏不可逆 | 函数签名只接受 PlayerView 类型——TypeScript/Python 类型检查即可拦截 |
| **Entity.secrets** | NPC 的真实底牌、幕后真相。AI 一旦读到就无法"假装不知道" | PlayerView 类型不包含此字段 |
| **Room.entity_states** | 全局实体状态。AI 只能通过 PlayerView 看到自己该看的 | 同上 |
| **Database ORM / Repository** | AI 不能直接查库 | AI Agent 模块不 import 任何 Repository |
| **Resolution.state_changes** | 状态变更细节。叙事不需要知道引擎写了什么 | Narrator 函数签名不暴露此字段 |
| **Checkpoint.hidden** | 暗骰的检定配置。AI 知道这是暗骰后会"假装"不知道结果 | ContextBuilder 过滤 hidden=true 的 Checkpoint |

### 4.3 灰色地带：ai_private

`Resolution.ai_private` 是唯一**只给 AI 看、不进玩家视野**的字段。它不等同于 `secrets`——前者是引擎在裁决后**主动选择**给 AI 的提示，后者是模组作者写死的底牌。

```
ai_private 的内容：
  npc_mood: "wary"              ← 引擎裁决后告诉 AI "这个 NPC 现在很警觉"
  foreshadowing: "玩家即将发现地下室入口"  ← 引擎预判的剧情方向

ai_private 不能包含：
  ❌ Entity.secrets 的原文       ← 那是模组作者写的底牌
  ❌ 其他玩家的 PlayerView       ← 信息隔离
  ❌ entity_states 的当前值       ← 那是 God View
```

---

## 五、必须永远由代码实现的能力

### 5.1 为什么

AI 在以下场景中具有**系统性偏向**，不能靠 prompt 约束：

| 代码能力 | LLM 的偏向 | 漏掉的后果 | 严重程度 |
|---------|-----------|-----------|---------|
| SAN 变化计算 | 想让玩家"有惊无险" | SAN 掉少了，恐怖感消失 | 🔴 破坏体验 |
| D100 检定 | 想让玩家成功 | 检定永远偏向成功，游戏无挑战 | 🔴 破坏公平性 |
| 状态修改 | 想让玩家开心 | 猫活了，模组结局永不触发 | 🔴 无法通关 |
| 权限判断 | 想让信息更透明 | 泄露其他玩家的秘密 | 🔴 信任崩塌 |
| Event 记录 | 不会主动想起要记 | 审计链断裂，无法复盘 | 🟡 可修复 |
| A 类拒绝 (refuse_ops) | 会被说服 | 玩家拿到了不该拿的东西 | 🟡 通常不致命 |
| B 类必然 (on_scene_enter) | 不会主动想起来触发 | 猫没死，结局条件永不满足 | 🔴 无法通关 |
| C 类反转 (on_check_resolve) | 成功=好结果的先验相反 | 反直觉设计被静默抹除 | 🔴 体验扭曲 |
| D 类值保护 (不变式) | 是唯一写入者，有动机写错 | 手拉手都活着出去了 | 🔴 静默失败 |
| 骰子随机数 | 无法生成真正的随机数 | 检定可预测 | 🟡 可审计 |

### 5.2 完整清单

```
┌─────────────────────────────────────────────────────────────┐
│                    代码的不可剥夺职责                          │
│                                                              │
│ 规则裁决层:                                                   │
│   ☑ D100 检定（掷骰、六级判定、奖惩骰）                        │
│   ☑ SAN 机制（六种形态结算、疯狂判定）                         │
│   ☑ 战斗流水线（12 hook 调度）                                 │
│   ☑ 伤害计算（骰式解析：1d6, 1d10+2, 6+1d4+2）               │
│   ☑ HP 管理（扣除、治疗、死亡判定）                            │
│   ☑ 表达式求值（§6.2 Expr 语法: Rule.when + WinCondition.expr）│
│                                                              │
│ 状态管理层:                                                   │
│   ☑ GameState 读写（唯一入口 GameStateRepo）                   │
│   ☑ entity_states 修改（仅引擎可写，key ∈ Entity.state 的键空间）│
│   ☑ Character 属性/技能/HP/SAN/LUCK 修改                      │
│   ☑ Condition 状态机调度（定时器：after/every/at）              │
│   ☑ LedgerEntry 计数器维护（count/window/cap/regen）           │
│   ☑ D 类写入不变式校验（count(has_dreamstone) ≤ floor(party/2)）│
│                                                              │
│ 权限与隔离层:                                                  │
│   ☑ ViewProjector: GodView → PlayerView                      │
│   ☑ Scope 裁剪: Resolution.narration_context 的组装            │
│   ☑ secrets 隔离: 永不进入 LLM 上下文                          │
│   ☑ 消息分发: 按 scope 定向推送（private/location/party/global）│
│                                                              │
│ 事件与审计层:                                                  │
│   ☑ Event 记录（append-only, cause 字段标注来源）               │
│   ☑ Event.payload 可重建性（from→to, 不是语义事件）             │
│   ☑ 物化视图更新（与 event 在同一事务内）                       │
│                                                              │
│ 引擎介入层（A/B/C/D）:                                         │
│   ☑ A 类: refuse_ops 黑名单校验                                │
│   ☑ B 类: on_scene_enter / on_turn_end hook 求值              │
│   ☑ C 类: on_check_resolve hook 求值                          │
│   ☑ D 类: entity_states 写入不变式 + 符号表校验                │
│                                                              │
│ AI 输入校验层:                                                 │
│   ☑ IntentValidator 的 7 项校验                                │
│   ☑ 软判据 → 枚举的桥接（LLM 求值 roleplay_tier → 代码写 slot）│
└─────────────────────────────────────────────────────────────┘
```

---

## 六、MVP → V2 → V3 演进路线

### 6.1 核心约束：不推翻 MVP 架构

```
每个阶段的接口保持不变。V2 的 Narrator 签名与 MVP 完全相同。
V3 只是增加了新的可选参数和新的 persona 值。
升级是从"桩实现 → 真实实现"或"简单实现 → 复杂实现"，不是重写。
```

### 6.2 MVP（第 1-2 周）：一句话闭环

```
目标：utterance → Intent → Resolution → narration
      整条链路跑通，Mock 模式可演示

模块:
  LLMAdapter      单供应商 + 流式输出
  PromptRegistry   2 个模板（旁白 + 意图解析）
  IntentParser     LLM 模式 + 关键词兜底
  Narrator         单一旁白人格
  ContextBuilder   硬截断最近 6 轮
  IntentValidator  4 项基础校验

不包含:
  Summarizer / RAG / NPC 多人格 / 模型路由 / 成本计量

验收标准:
  输入"我搜索书房抽屉" → 控制台输出完整 Intent JSON + 流式叙事文本
```

### 6.3 V2（第 3-6 周）：完整游戏体验

```
目标：单人可从头跑完一个模组

增量:
  V2.1  IntentValidator 补全 7 项校验
  V2.2  ContextBuilder + Summarizer（规则合并，长历史不丢上下文）
  V2.3  Narrator 多人格路由
         - persona="npc:{id}"  NPC 对话
         - persona="qa"        规则答疑
         - persona="hint"      引导提示
  V2.4  RAGRetriever（规则书向量化 + 检索）
  V2.5  脱本导回策略（Intent 超出模组范围 → 引导回场景可交互列表）
  V2.6  降级策略完善（超时重试 → 兜底文案 → 玩家无感知）
  V2.7  评测集建立（20 条 Intent + 10 条叙事用例）
  V2.8  Model Router（意图=小模型、旁白=强模型、NPC=另配）

签名不变:
  parse_intent()  签名不变，内部从关键词→LLM→LLM+兜底 升级
  narrate()       签名不变，persona 参数从 "narrator" 扩展到 "npc:{id}"
  build_context() 签名不变，内部增加 Summarizer
```

### 6.4 V3（第 7-8 周 + 持续迭代）：生产就绪

```
目标：多人联机 + 模组导入 + 成本可控

增量:
  V3.1  ModuleParser（PDF → ModulePack，有人工审核界面）
  V3.2  流式输出优化（逐句/逐段下发，打字机效果）
  V3.3  Prompt 缓存（场景描述/世界观固定文本标记为缓存前缀）
  V3.4  成本计量与预警（按房间/场次统计 token 消耗）
  V3.5  多种 LLM 供应商混用（DeepSeek 意图 + Claude 旁白 + ...）
  V3.6  Narrator 风格一致性追踪（同一 NPC 前后对话不崩人设）
  V3.7  AI 输出质量评测体系（10 场真实跑团日志人工评分）

签名扩展（向后兼容）:
  narrate()        新增可选参数 style_consistency?: NPCMemory
  build_context()  新增可选参数 moduleContext?: ModuleContext
  parse_intent()   不变
```

### 6.5 演进路线图

```
Week 1-2 (MVP)          Week 3-6 (V2)              Week 7-8+ (V3)
┌─────────────────┐    ┌─────────────────────┐    ┌──────────────────┐
│ 单模型            │    │ 模型路由             │    │ 多供应商混用       │
│ 单一旁白人格       │    │ 多人格路由           │    │ 风格一致性追踪     │
│ 关键词兜底         │    │ LLM + 7项校验        │    │ 完整评测体系       │
│ 4项基础校验        │    │ 摘要压缩             │    │ 成本计量           │
│ 6轮截断           │    │ RAG 检索             │    │ Prompt 缓存       │
│                   │    │ 脱本导回             │    │ ModuleParser      │
│                   │    │ 降级策略             │    │                   │
│ 接口:             │    │ 接口:                │    │ 接口:             │
│  parse_intent()   │    │  签名不变             │    │  新增可选参数       │
│  narrate()        │    │  能力升级             │    │  旧参数全部兼容     │
│  build_context()  │    │                       │    │                   │
└─────────────────┘    └─────────────────────┘    └──────────────────┘
```

---

## 七、关键设计决策

### 7.1 为什么 Director 被拒绝（再次强调）

```
这是整个架构中最危险的提议。Director 看起来像"聪明的 AI 主持人"——
它能判断节奏、推动剧情、在玩家迷茫时引导。但这些事应该由谁做？

  判断"该进入下一幕了"    → WinCondition.expr 求值（代码）
  推动"猫必须死"          → B 类 on_scene_enter（代码）
  感知"玩家卡住了"        → Player.unknown_streak（代码计数器）
  生成"给点提示吧"        → Narrator persona="hint"（AI）

Director 是把这四件事揉进一个 LLM 调用。一旦这样做了：
  1. 它需要读 ModulePack 的剧情图 → 读 Content 层
  2. 它需要知道当前进度 → 读 entity_states
  3. 它需要写"现在进入场景 X" → 写 GameState

这就是 AI 变成了引擎。而且它的失败是静默的——玩家不会发现剧情被跳过了。
```

### 7.2 为什么 Summarizer 不是独立 Agent

Summarizer 是被 ContextBuilder 调用的工具函数，不是独立 Agent。它没有自己的 LLM 调用循环，不需要独立的状态管理。把它独立出来只会增加不必要的模块边界。

### 7.3 为什么 NPCActor 合并进 Narrator

NPC 对话与旁白叙事共享同一套底层机制：
- 同一个 LLMAdapter
- 同一个 ContextBuilder（只是注入不同的 prompt + persona）
- 同一个流式输出协议

差异仅在于 System Prompt 和注入的 NPC 信息（publicPersona）。这不是架构层面的差异，是配置层面的差异。

### 7.4 软判据与硬求值的分离线

```
《蛙蛙村》说服信使的三档难度：

  ❌ 全交给 AI：
     "玩家说得好 → 成功"  ← AI 永远是好人，永远判成功

  ❌ 全交给代码：
     "检测到关键词'证据'+'威胁' → 成功"  ← 玩家可以敷衍了事

  ✅ 分层：
     阶段 1  AI 求值 roleplay 质量 → 输出枚举 {none, reasonable, excellent}
     阶段 2  代码读枚举 → 查表得 difficulty → 掷骰

  AI 的输出是枚举，不是检定结果。
  枚举的值由 PromptRegistry 定义（硬编码三档），AI 只能选，不能造第四档。
```

---

## 八、AI Agent 与其他层的接口契约

```
┌──────────────────────────────────────────────────────────────┐
│                    Orchestrator (L3)                          │
│                                                               │
│  handleTurn(roomId, playerId, utterance):                     │
│                                                               │
│    playerView = ViewProjector.project(gameState, playerId)     │
│                       │                                       │
│                       ▼                                       │
│    intent = AIAgent.parse_intent(           ← ① AI 调用       │
│      utterance, playerView, sceneContext, history              │
│    )                                                           │
│                       │                                       │
│                       ▼                                       │
│    intent = IntentValidator.validate(intent, ...) ← 校验层     │
│                       │                                       │
│                       ▼                                       │
│    resolution = Rules.resolveAction(gameState, playerId, intent)│
│                       │                                       │
│                       ▼                                       │
│    playerView2 = ViewProjector.project(gameState, playerId)     │
│                       │                                       │
│                       ▼                                       │
│    stream = AIAgent.narrate(                ← ② AI 调用       │
│      resolution, playerView2, persona, sceneContext            │
│    )                                                           │
│                       │                                       │
│                       ▼                                       │
│    Gateway.broadcast(stream, resolution.narration_context.scope)│
│                                                               │
│  注意：AI Agent 只参与步骤 ① 和 ④。                            │
│        ②  ViewProjector 是引擎的事                             │
│        ③  Rules 是引擎的事                                    │
│        ⑤  Gateway 是通信层的事                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 九、目录结构（最终态）

```
server/src/ai_agent/
├── __init__.py                    # 公开 API: parse_intent / narrate
│
├── intent/
│   ├── __init__.py
│   ├── parser.py                  # IntentParser 主逻辑
│   ├── prompts.py                 # 意图解析 System Prompt
│   └── validator.py               # IntentValidator（7 项校验）
│
├── narrator/
│   ├── __init__.py
│   ├── narrator.py                # Narrator 主逻辑（流式输出 + 人格路由）
│   ├── personas.py                # 人格定义：旁白/NPC/答疑/引导
│   └── prompts.py                 # 各人格的 System Prompt 模板
│
├── context/
│   ├── __init__.py
│   ├── builder.py                 # ContextBuilder：上下文组装
│   ├── summarizer.py              # Summarizer：历史摘要（V2）
│   └── token_budget.py            # Token 预算管理
│
├── llm/
│   ├── __init__.py
│   ├── adapter.py                 # BaseLLMAdapter 抽象基类
│   ├── deepseek_adapter.py        # DeepSeek 适配器
│   ├── claude_adapter.py          # Claude 适配器（V2+）
│   ├── router.py                  # ModelRouter（V2+）
│   └── fallback.py                # 超时/降级/兜底策略
│
├── rag/                           # V2
│   ├── __init__.py
│   ├── indexer.py                 # 文档索引
│   ├── retriever.py               # 运行时检索
│   └── knowledge_base.py          # 知识库管理
│
└── module_parser/                 # V3
    ├── __init__.py
    ├── extractor.py               # PDF/文档提取
    ├── structurer.py              # AI 结构化解析
    └── validator.py               # 解析结果校验
```

---

## 附录 A：与其他文档的关系

| 本文 | 对应 | 关系 |
|------|------|------|
| §一 能力地图 | AI_AGENT_DESIGN.md §1.2 | 本文是最终裁定——砍掉了 Director、MemoryManager、NPCActor、ReplayGenerator、GuidanceAgent |
| §三 模块 I/O | AI_AGENT_DESIGN.md §2.1 | 本文直接继承 Intent/Resolution/PlayerView 契约，补充了 SceneContext、TurnRecord 等 |
| §四 模型边界 | 数据模型设计.md §7.3 | 本文用类型级强制落实数据模型的"状态写入口唯一"约束 |
| §五 代码不可剥夺 | 数据模型设计.md §5.8 | 本文直接将 A/B/C/D 四类引擎介入标注为"代码永远负责" |
| §七.1 Director | 数据模型设计.md §5.8.9 B 类 | Director 试图用 AI 替代 B 类，这是架构级越权 |

---

*本文为 AI Agent 模块最终架构方案。MVP 阶段即按此结构启动，V2/V3 在相同接口上增量演进。*

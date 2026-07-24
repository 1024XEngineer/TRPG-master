# Agent Framework 技术选型与架构设计

> 日期：2026-07-14
> 定位：AI DM 系统的 Agent Framework 选型分析、运行时架构设计与完整系统方案
> 前置：agent-module-design.md / 数据模型设计.md / COC_ENGINE_RULE_REQUIREMENTS.md

---

## 〇、选型之前：系统本质再确认

在分析任何框架之前，必须先回答一个问题：**这个系统到底长什么样？**

```
这个系统不是：

  ✗ 聊天机器人（Chatbot）
  ✗ Multi-Agent 办公自动化
  ✗ RAG 问答系统
  ✗ AI 客服

这个系统是：

  ✓ 一个状态驱动的世界模拟器
  ✓ 一个游戏运行时（Game Runtime）
  ✓ 一个规则引擎（Rule Engine）
  ✓ 一个运行在规则引擎之上的 AI 叙事层
  ✓ 一个模组内容的结构化提取与审查系统
```

从软件架构角度看，它最接近的是：

```text
传统 MUD / 文字 MMO 服务器
        +
现代 LLM 增强的叙事层
        +
结构化工作流引擎
        +
离线 ETL 数据处理流水线（模组导入侧）
```

**这个定位决定了框架选型的核心判据：**

> 框架必须擅长"LLM 与确定性系统的结构化交互"，而不是"多个 LLM 之间的自由对话"。

### 〇.1 项目的实际 Agent 架构：两个 Agent 系统 + 一个确定性引擎

本项目并非只有一个 Agent。按照 `agent-implementation-team-plan.md` 的三人分工，系统由 **两个 Agent 系统** 和 **一个确定性引擎** 组成：

```text
┌─────────────────────────────────────────────────────────────┐
│                     离线（游戏开始前）                        │
│                                                              │
│  Module Parser Agent 系统（成员 C）                           │
│  ┌────────────┐    ┌────────────┐    ┌──────────────┐      │
│  │ Parser     │ →  │ Reviewer   │ →  │ 人工审核      │      │
│  │ Agent      │    │ Agent      │    │ + 批准        │      │
│  │ (LLM)      │    │ (LLM)      │    │ (Human)      │      │
│  └────────────┘    └────────────┘    └──────────────┘      │
│                                                              │
│  输入: PDF/Markdown 模组原文                                  │
│  输出: ModuleContent (结构化 JSON，存入 Content 层)           │
│  消费者: Runtime Keeper Agent + Game Engine                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                     在线（游戏进行中）                        │
│                                                              │
│  Runtime Keeper Agent 系统（成员 A）                          │
│  ┌────────────┐         ┌────────────┐                     │
│  │ Planner    │         │ Narrator   │                     │
│  │ (LLM)      │         │ (LLM)      │                     │
│  └─────┬──────┘         └──────▲─────┘                     │
│        │ ActionPlan             │ ConfirmedOutcome          │
│        ▼                        │                           │
│  ┌─────────────────────────────────────┐                    │
│  │        Game Engine（成员 B）         │                    │
│  │  确定性代码。无 LLM。                 │                    │
│  │  · CheckResolver · RuleEvaluator    │                    │
│  │  · StateManager  · EventLogger      │                    │
│  │  · SANManager    · CombatPipeline   │                    │
│  │  · WinConditionEvaluator            │                    │
│  └─────────────────────────────────────┘                    │
│                                                              │
│  输入: 玩家自然语言                                           │
│  输出: AI 叙事 + 状态更新                                     │
└─────────────────────────────────────────────────────────────┘
```

**两个 Agent 系统的本质差异：**

| 维度 | Module Parser Agent | Runtime Keeper Agent |
|------|--------------------|--------------------|
| 生命周期 | 离线，一次执行 | 在线，每回合执行 |
| 触发方式 | 用户上传模组 | 玩家输入自然语言 |
| 延迟要求 | 可等待数十秒 | 2-3 秒内响应 |
| LLM 调用次数 | 2-3 次（Parser Pass 1/2 + Reviewer） | 2 次（Planner + Narrator） |
| 核心输出 | ModuleContent（全局结构化数据） | 自然语言叙事 |
| 编排复杂度 | 低——线性流水线 + 确定性校验步骤 | 低——每个回合是线性流水线 + 一个 if 分支 |
| 上下文大小 | 极大（整个模组 PDF，可达 100 页） | 小（当前场景 + 角色状态，~2-4K tokens） |
| 模型需求 | 强模型 + 大上下文（Claude Opus 200K） | 推理用强模型 + 叙事用快模型 |
| 失败模式 | 漏字段 → 人工审核发现并修正 | 漏规则 → 游戏体验受损 |

**这意味着：两个 Agent 系统可能需要不同的框架选择——或者同一个框架的两个不同用法。**

### 〇.2 LLM 在 Runtime 系统中的实际角色

在 Runtime 侧，LLM 在每次玩家回合中**只被调用两次**：

```text
调用 1（上游）：玩家输入 → Intent + ActionPlan（结构化 JSON）
调用 2（下游）：ConfirmedOutcome → 自然语言叙事
```

其余所有环节——检定、规则求值、状态变更、事件记录、结局判断——全部由确定性引擎执行，**LLM 一行代码都不该碰**。

### 〇.3 LLM 在 Module Parser 系统中的实际角色

在 Module Parser 侧，LLM **也只被调用两次**：

```text
调用 1（Parser Agent）：模组原文 → ModuleDraft（结构化 JSON）
调用 2（Reviewer Agent）：ModuleDraft + 原文 → ReviewReport（结构化 JSON）
```

中间的预处理（PDF→Markdown）、后处理（Schema 校验、引用完整性检查、符号表检查）和最终的人工审批——全部是确定性代码或人类判断。

**两个 Agent 系统的共同特征：LLM 的职责都是"非结构化输入 → 结构化输出"。** 这正是 PydanticAI 的核心设计目标。

---

## 一、十四维度框架分析

### 1.1 框架概览

| 框架 | 类型 | 语言 | 核心理念 |
|------|------|------|---------|
| **PydanticAI** | 结构化 Agent SDK | Python | 类型安全的 LLM 交互 + Tool Calling |
| **LangGraph** | 状态机工作流引擎 | Python/JS | Graph-based State Machine for LLM workflows |
| **PydanticAI + LangGraph** | 组合方案 | Python | PydanticAI 做 LLM 层，LangGraph 做编排层 |
| **LangChain** | 全栈 LLM 框架 | Python/JS | 高度抽象的 LLM 应用开发框架 |
| **Mastra** | TS 工作流 + Agent | TypeScript | LangGraph 的 TS 替代品 |
| **CrewAI** | 多 Agent 协作 | Python | Role-based Multi-Agent Team |
| **AutoGen** | 多 Agent 对话 | Python | Agent-to-Agent Conversation |
| **OpenAI Agents SDK** | Agent SDK | Python | OpenAI 官方的轻量 Agent 构建工具 |

---

### 1.2 PydanticAI

**定位**：Python-native、类型安全的 Agent 开发 SDK。由 Pydantic 团队维护。

**核心理念**：

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class ActionPlan(BaseModel):
    route: Literal["narrative", "engine"]
    action_type: Literal["talk", "inspect", "check", "use_item", "move"]
    actor_id: str
    target_id: str
    checkpoint_id: str | None
    narrative_intent: str

planner = Agent(
    model="claude-sonnet-5",
    result_type=ActionPlan,  # ← 输出强制为此 Pydantic Model
    system_prompt="你是 CoC 守秘人..."
)

# 调用：输入自然语言，输出已验证的 ActionPlan
result = await planner.run("我仔细调查书架")
# result.data 是 ActionPlan 实例，已通过 Pydantic 校验
```

**逐维度分析**：

| 维度 | 评分 | 分析 |
|------|------|------|
| 学习成本 | ★★★★★ | Python 开发者几乎零学习成本。API 就是普通的 async function call。Agent 定义 = Pydantic Model + system_prompt。1 天上手。 |
| 开发效率 | ★★★★★ | 极高。`result_type=ActionPlan` 一行代码解决"LLM 输出 JSON → 校验 → 重试"整条链路。Tool 定义用 `@agent.tool` 装饰器，与 FastAPI 依赖注入同风格。 |
| 可维护性 | ★★★★★ | 类型即文档。所有 LLM 输入/输出都有 Pydantic Model 约束。改 Schema → 改 Model → 类型检查器告诉你所有受影响位置。 |
| 类型安全 | ★★★★★ | 整个 Python 生态最强。`result_type` 保证 LLM 输出通过 Pydantic 校验，校验失败自动重试（可配置重试次数）。 |
| 调试体验 | ★★★★☆ | 类型错误有明确路径。但 LLM 调用链路追踪不如 LangGraph 可视化。可搭配 Logfire（Pydantic 团队出品）补强。 |
| 多 Agent 支持 | ★★★☆☆ | 不擅长。PydanticAI 的 `Agent` 是单例模式。多 Agent 需要手动编排。这不是它的设计目标。 |
| Workflow 支持 | ★★☆☆☆ | 薄弱。没有内建的 graph/state machine。需要自己写 game loop。但 MVP 的 game loop 本就简单——一个 while 循环 + 条件分支，不需要 graph。 |
| 长期演进 | ★★★★☆ | Pydantic 团队维护，生态健康。但框架较新（2024 末发布），API 可能变动。 |
| 状态机契合度 | ★★★☆☆ | 自身不提供状态机。需要外部实现。但 Pydantic Model 天然适合建模状态（`GameState`、`EntityState` 都可以是 Pydantic Model）。 |
| 结构化 JSON 契合度 | ★★★★★ | 完美匹配。项目核心接口（ActionPlan、ConfirmedOutcome、ModuleContent）都是强类型 JSON。PydanticAI 的设计目标就是"让 LLM 输出可靠的结构化数据"。 |
| TRPG 场景适合度 | ★★★★☆ | 非常适合 LLM 调用层。但缺少编排能力——需要自己写 Game Loop。对 MVP 来说这不是问题，对长期来说需要补充。 |
| 社区成熟度 | ★★★☆☆ | 较新。文档质量高但社区较小。遇到冷门问题可能没有现成解答。 |
| 生产稳定性 | ★★★★☆ | Pydantic 团队出品，工程品质有保证。但框架本身新，生产案例少。 |
| 框架锁定风险 | ★★★★☆ | 低。核心依赖只是 Pydantic Model + LLM 调用封装。即使未来换框架，Model 定义完全可复用，Agent.run() 替换为其他调用方式成本很低。 |

**核心优势总结**：当系统接口已经是 Pydantic Model 时（ActionPlan、ConfirmedOutcome、ModuleContent 都是强类型结构），PydanticAI 消除了 LLM 输出解析这一整类 bug。

**核心劣势总结**：不做编排。Game Loop、状态流转、条件分支需要自己实现。但对于一个状态机本就不复杂的游戏回合循环，这可能不是劣势——自己写的 while 循环比 graph framework 的隐式状态迁移更容易调试。

---

### 1.3 LangGraph

**定位**：有状态的大模型工作流引擎。Graph-based State Machine。

**核心理念**：

```python
from langgraph import StateGraph, TypedDict

class GameState(TypedDict):
    player_input: str
    action_plan: dict | None
    confirmed_outcome: dict | None
    narration: str | None
    route: str | None

def intent_node(state: GameState) -> GameState:
    """LLM: 玩家输入 → 意图识别 + ActionPlan"""
    ...

def engine_node(state: GameState) -> GameState:
    """确定性引擎: 执行 ActionPlan → ConfirmedOutcome"""
    ...

def narrate_node(state: GameState) -> GameState:
    """LLM: ConfirmedOutcome → 叙事"""
    ...

graph = StateGraph(GameState)
graph.add_node("intent", intent_node)
graph.add_node("engine", engine_node)
graph.add_node("narrate", narrate_node)

graph.add_conditional_edges("intent", lambda s: s["route"], {
    "narrative": "narrate",   # 自由叙事 → 跳过引擎
    "engine": "engine"        # 规则行为 → 先执行引擎
})
graph.add_edge("engine", "narrate")
graph.set_entry_point("intent")
```

**逐维度分析**：

| 维度 | 评分 | 分析 |
|------|------|------|
| 学习成本 | ★★★☆☆ | 需要理解 Graph、Node、Edge、State、Reducer、Conditional Edge、Checkpoint。1-3 天入门。团队中如果有成员不熟悉状态机概念，学习曲线更陡。 |
| 开发效率 | ★★★★☆ | 图结构定义后，框架自动处理状态流转。Conditional Edge 让分支逻辑声明式表达。但调试一个跑错的图比调试一个跑错的 while 循环慢。 |
| 可维护性 | ★★★★☆ | 图结构 = 文档。新人看 graph definition 就能理解整个回合流程。但当节点数超过 15-20 个时，图变得难以阅读。 |
| 类型安全 | ★★★☆☆ | TypedDict 比 Pydantic Model 弱。没有运行时校验、没有嵌套模型约束。需要额外引入 Pydantic 做输出校验。 |
| 调试体验 | ★★★★☆ | LangSmith 提供节点级别的可视化追踪。每个节点的输入/输出都可检查。但断点调试比普通 Python 代码困难——状态在框架内部流转。 |
| 多 Agent 支持 | ★★★★☆ | 天然支持。每个节点可以是不同的 LLM 调用（Subgraph 机制）。未来增加 NPC Agent/Combat Agent 就是增加节点。 |
| Workflow 支持 | ★★★★★ | 核心卖点。Conditional Edge、Parallel Node、Subgraph、Checkpoint、Human-in-the-Loop——这些都是 LangGraph 的一等公民。 |
| 长期演进 | ★★★★★ | LangChain 生态最核心的项目。大团队维护。版本迭代快。企业级功能（LangGraph Platform）在收费路上——需关注。 |
| 状态机契合度 | ★★★★★ | 完美匹配。StateGraph 就是状态机。每个 Node = 状态，Edge = 迁移，Conditional Edge = 守卫条件。游戏回合循环是状态机的经典用例。 |
| 结构化 JSON 契合度 | ★★★☆☆ | 本身不提供结构化输出校验。需要自己写 JSON Schema 校验或引入 Pydantic。Tool Calling 的输出解析需要手动处理。 |
| TRPG 场景适合度 | ★★★★☆ | 状态机模型天然匹配游戏回合。但需要额外工作保证 LLM 输出的结构化可靠性（这是 PydanticAI 的强项）。 |
| 社区成熟度 | ★★★★★ | Python Agent 框架中社区最大、案例最多。遇到问题有大量参考。 |
| 生产稳定性 | ★★★★☆ | 被多家公司用于生产环境。但版本迭代激进（0.x → 1.0 迁移可能 breaking）。 |
| 框架锁定风险 | ★★★☆☆ | 中等。StateGraph 的编程模型独特——迁移到其他框架需要重写编排层。但核心业务逻辑（engine 节点内的代码）可以保持独立。 |

**核心优势总结**：当系统是多步骤、有分支、状态驱动的流水线时，LangGraph 提供了最自然的表达方式。游戏回合循环恰好就是这种东西。

**核心劣势总结**：引入了一个重量级依赖来解决一个 MVP 阶段本可以用 20 行 while 循环解决的问题。工具的复杂度不应超过问题的复杂度。

---

### 1.4 PydanticAI + LangGraph 组合

**定位**：PydanticAI 负责 LLM 交互层（类型安全的输入/输出），LangGraph 负责编排层（状态机流转）。各取所长。

**核心理念**：

```python
# ──── PydanticAI 定义 LLM 层 ────
from pydantic_ai import Agent
from pydantic import BaseModel

class ActionPlan(BaseModel):
    route: Literal["narrative", "engine"]
    action_type: Literal["talk", "inspect", "check", "use_item", "move"]
    target_id: str
    checkpoint_id: str | None
    narrative_intent: str
    roleplay_tier: Literal["none", "reasonable", "excellent"] | None

planner = Agent(
    model="claude-sonnet-5",
    result_type=ActionPlan,
    system_prompt="...",
    tools=[query_scene, query_entity, query_character]  # 只读工具
)

class Narration(BaseModel):
    text: str
    npc_dialogue: str | None
    sensory_details: list[str]

narrator = Agent(
    model="claude-haiku-4-5",
    result_type=Narration,
    system_prompt="..."
)

# ──── LangGraph 定义编排层 ────
class TurnState(TypedDict):
    player_input: str
    context: dict
    action_plan: ActionPlan | None  # ← Pydantic Model，非 dict
    confirmed_outcome: dict | None
    narration: Narration | None     # ← Pydantic Model，非 dict

def intent_node(state: TurnState) -> TurnState:
    result = await planner.run(state["player_input"], deps=state["context"])
    state["action_plan"] = result.data  # ← 已校验的 ActionPlan
    state["route"] = result.data.route
    return state

def narrate_node(state: TurnState) -> TurnState:
    result = await narrator.run(
        f"Outcome: {state['confirmed_outcome']}",
        deps=state["context"]
    )
    state["narration"] = result.data
    return state
```

**逐维度分析**：

| 维度 | 评分 | 分析 |
|------|------|------|
| 学习成本 | ★★☆☆☆ | 需要同时学习两个框架。对 1-3 人团队是显著负担。建议 MVP 先用 PydanticAI 独跑，确认编排复杂度确实需要 LangGraph 后再引入。 |
| 开发效率 | ★★★★☆ | 两个框架各司其职后，代码边界清晰。PydanticAI 消除 LLM 输出解析 bug，LangGraph 消除状态流转 bug。 |
| 可维护性 | ★★★★★ | 分离关注点到达极致：LLM I/O 类型 vs 状态流转图。修改一个不影响另一个。最清晰的长期架构。 |
| 类型安全 | ★★★★★ | PydanticAI 的类型安全 + LangGraph 的状态类型 = 全链路类型覆盖。 |
| 调试体验 | ★★★★☆ | PydanticAI 的校验失败有明确路径，LangGraph 有可视化追踪。但两层框架的交互处（Pydantic Model 在 Graph State 中流转）是调试盲区。 |
| 多 Agent 支持 | ★★★★★ | 每个 Agent = PydanticAI Agent 实例，挂在不同 LangGraph 节点上。天然解耦。 |
| Workflow 支持 | ★★★★★ | 继承了 LangGraph 的全部 workflow 能力。 |
| 长期演进 | ★★★★★ | 两个框架独立演进。即使未来换掉其中一个，另一个不受影响。架构耦合度最低。 |
| 状态机契合度 | ★★★★★ | 同上。 |
| 结构化 JSON 契合度 | ★★★★★ | 项目的每个 JSON 接口都是 Pydantic Model——从 ModuleContent 到 ActionPlan 到 ConfirmedOutcome 到 Event。PydanticAI 验证 LLM 侧，Pydantic 验证引擎侧。同一个类型系统贯穿全栈。 |
| TRPG 场景适合度 | ★★★★★ | 各取所长后没有明显短板。 |
| 社区成熟度 | ★★★★☆ | 两者的社区都健康，但组合使用的案例还少。 |
| 生产稳定性 | ★★★★☆ | 两个独立稳定的组件组合。耦合点在应用层，可控。 |
| 框架锁定风险 | ★★★☆☆ | LangGraph 的锁定风险仍在（这是编排层，迁移成本高）。PydanticAI 锁定风险低——Pydantic Model 是纯数据，不依赖框架。 |

**核心优势总结**：这是"各司其职"最彻底的方案。PydanticAI 管"LLM 说什么"，LangGraph 管"什么时候说"，Game Engine 管"什么是对的"。

**核心劣势总结**：两个框架的学习成本 + 两个依赖的版本管理。对 1-3 人 MVP 团队过于沉重。适合"先用 PydanticAI 跑通 MVP，确认编排复杂度后再引入 LangGraph"的分阶段策略。

---

### 1.5 LangChain

**定位**：全栈 LLM 应用开发框架。曾是 Python LLM 生态的事实标准。

**逐维度分析**：

| 维度 | 评分 | 分析 |
|------|------|------|
| 学习成本 | ★☆☆☆☆ | 极高。高度抽象的 Chain/LCEL/Runnable 概念。文档曾经混乱（2024 年后有改善）。"做一个简单的事情需要理解 5 层抽象"。 |
| 开发效率 | ★★☆☆☆ | 简单场景（单次 LLM 调用）可以很快。但一旦需要自定义逻辑，抽象层开始泄漏，你需要理解内部实现来调试。 |
| 可维护性 | ★★☆☆☆ | 抽象泄漏导致维护困难。版本升级频繁 breaking。大量 deprecated 警告。 |
| 类型安全 | ★☆☆☆☆ | 弱。大量 `dict` 传递，运行时才知道类型错误。 |
| 调试体验 | ★☆☆☆☆ | 抽象层太多，报错信息深埋在框架内部。一个简单错误可能抛出 200 行 traceback，其中 180 行是 LangChain 内部。 |
| 多 Agent 支持 | ★★★☆☆ | 有但重。AgentExecutor 抽象不透明。 |
| Workflow 支持 | ★★★☆☆ | LCEL 可以表达顺序/并行。但复杂分支很吃力——这正是 LangGraph 从 LangChain 中拆出来的原因。 |
| 长期演进 | ★★★☆☆ | LangChain 团队重心已转移到 LangGraph。LangChain 本身进入维护模式。 |
| 状态机契合度 | ★★☆☆☆ | 不擅长状态管理。这正是 LangGraph 被创造的原因。 |
| 结构化 JSON 契合度 | ★★★☆☆ | 有 OutputParser 但笨重。需要定义 Format Instructions → Parser → 手动错误处理。远不如 PydanticAI 的 `result_type` 优雅。 |
| TRPG 场景适合度 | ★★☆☆☆ | 过重。项目需要的是薄胶水层，LangChain 提供的是厚抽象层。 |
| 社区成熟度 | ★★★★★ | 曾经最大。但大量内容已过时（deprecated）。 |
| 生产稳定性 | ★★☆☆☆ | 版本碎片化严重。0.1.x / 0.2.x / 0.3.x 之间大量 breaking。 |
| 框架锁定风险 | ★☆☆☆☆ | 极高。整个应用逻辑嵌入 LangChain 抽象中，迁移成本巨大。 |

**结论**：不推荐。LangChain 在 2023 年是必要之恶（没有更好的选择），在 2026 年是不必要之重。它的抽象层厚度远超本项目需要的胶水层厚度。**LangChain 团队自己都已经把重心转移到 LangGraph 了。**

---

### 1.6 Mastra

**定位**：TypeScript 生态的 Workflow + Agent 框架。可视为"TS 版 LangGraph Lite"。

**逐维度分析**：

| 维度 | 评分 | 分析 |
|------|------|------|
| 学习成本 | ★★★★☆ | TS 开发者友好。API 现代化。文档清晰度中等。 |
| 开发效率 | ★★★★☆ | Workflow 定义简洁。但 Tool 定义比 PydanticAI 繁琐（需要 Zod schema 单独定义）。 |
| 可维护性 | ★★★★☆ | TS 类型系统提供一定安全性。 |
| 类型安全 | ★★★★☆ | Zod + TypeScript 提供较好的类型推断。 |
| 调试体验 | ★★★☆☆ | 较新的框架，调试工具不如 LangGraph+LangSmith 成熟。 |
| 多 Agent 支持 | ★★★★☆ | 原生支持。 |
| Workflow 支持 | ★★★★☆ | Step/When 模式，类似 LangGraph 的简化版。 |
| 长期演进 | ★★★☆☆ | 较新（2024 发布）。社区在增长但远小于 LangChain 生态。 |
| 状态机契合度 | ★★★★☆ | Workflow 模式天然适合状态流转。 |
| 结构化 JSON 契合度 | ★★★★☆ | Zod schema 可以定义结构化输出。 |
| TRPG 场景适合度 | ★★★★☆ | 如果项目是 TS 技术栈，会是强有力竞争者。 |
| 社区成熟度 | ★★☆☆☆ | 较新。文档有空白区，社区案例少。 |
| 生产稳定性 | ★★★☆☆ | 较新，生产案例有限。 |
| 框架锁定风险 | ★★★☆☆ | 中等。API 设计现代化，但生态绑定 TS/Mastra 生态。 |

**结论**：技术上不错，但**技术栈不匹配**。项目技术栈是 Python/FastAPI/PostgreSQL。引入 Mastra 意味着在 Python 后端之外增加一个 TS 服务层——对于 1-3 人团队，多语言运维成本远超框架本身带来的收益。**如果项目是 TypeScript 全栈，Mastra 值得认真考虑；但它是 Python 全栈，Mastra 不适合。**

---

### 1.7 CrewAI

**定位**：Role-based Multi-Agent 协作框架。

**核心理念**：定义多个有角色的 Agent（产品经理、程序员、测试），让它们像团队一样协作。

**为什么不推荐**：

```text
CrewAI 解决的问题：
  "多个专家 Agent 如何分工协作完成复杂任务"
  → 办公自动化、代码生成、研究分析

TRPG-master 的问题：
  "单个 LLM 如何与确定性规则引擎安全交互"
  → 状态机 + 工作流 + Tool Calling
```

**这不是"哪个更好"的问题——是解决完全不同的问题。** CrewAI 的核心抽象（Agent 之间互相聊天、委派任务）在 TRPG 场景中不仅无益，反而有害：
- 游戏不需要"多个 KP 讨论后决定"——每次裁决必须是确定性的
- Agent 之间的自由对话是不可审计的——你不知道为什么某个状态被改了
- CrewAI 没有内建的状态机——它假设任务通过 Agent 对话推进，而不是通过确定性的状态迁移

**评分**：不适合。方向性不匹配。

---

### 1.8 AutoGen

**定位**：微软的多 Agent 对话框架。

**核心理念**：多个 Agent 通过结构化消息相互通信，支持 Human-in-the-Loop。

**为什么不推荐**：

与 CrewAI 类似的问题——AutoGen 的核心抽象是 Agent-to-Agent Conversation。它假设智能体之间需要协商、辩论、多轮对话。TRPG 系统不需要这些：

- Planner 和 Narrator 不需要"对话"——它们是同一个流水线的不同阶段
- 引擎不是 Agent——它不"聊天"，它执行确定性函数
- 引入 Agent 对话模型会模糊"谁是 State 的权威来源"这条最关键的边界

AutoGen 的另一个问题是：它的设计前提是 LLM 调用的主要成本在推理时间，所以让 Agent 多轮对话来"思考"是可接受的。但 TRPG 的玩家在等待——每增加一轮 Agent 间对话，延迟翻倍。

**评分**：不适合。方向性不匹配 + 延迟模型不匹配。

---

### 1.9 OpenAI Agents SDK

**定位**：OpenAI 官方的轻量 Agent 构建 SDK。前身是 Swarm。

**核心理念**：

```python
from agents import Agent, Runner, function_tool

@function_tool
def roll_d100() -> dict:
    """执行 D100 检定"""
    ...

gm_agent = Agent(
    name="Keeper",
    instructions="你是 CoC 守秘人...",
    tools=[roll_d100, query_entity, query_scene],
)

result = await Runner.run(gm_agent, "玩家调查书架")
```

**逐维度分析**：

| 维度 | 评分 | 分析 |
|------|------|------|
| 学习成本 | ★★★★★ | 极低。Agent + Tool + Runner 三个概念。10 分钟上手。 |
| 开发效率 | ★★★★☆ | 简单场景极快。但缺少结构化输出约束（没有 `result_type` 等价物）。需要自己解析和校验 LLM 输出。 |
| 可维护性 | ★★★☆☆ | 简单但有隐式行为：Agent 之间的 handoff 是隐式的（LLM 决定），不可显式控制。调试困难。 |
| 类型安全 | ★★☆☆☆ | 没有强类型输出约束。LLM 返回 dict，需要手动校验。 |
| 调试体验 | ★★★☆☆ | OpenAI Dashboard 有基础追踪。但没有 LangSmith 级别的可视化。 |
| 多 Agent 支持 | ★★★★☆ | Handoff 机制原生支持。但 handoff 由 LLM 决策，不可显式编排——这对需要确定性流转的游戏场景是问题。 |
| Workflow 支持 | ★★☆☆☆ | 不是设计目标。没有 graph/state machine/conditional branch 概念。 |
| 长期演进 | ★★★★☆ | OpenAI 官方维护。与 OpenAI API 同步更新。 |
| 状态机契合度 | ★★☆☆☆ | 没有状态机概念。需要外部实现 game loop。 |
| 结构化 JSON 契合度 | ★★☆☆☆ | 没有内建的结构化输出校验。需要自己写 JSON Schema + 手动重试逻辑。 |
| TRPG 场景适合度 | ★★★☆☆ | 适合简单的 LLM+Tool 场景。但缺少结构化输出保证（对引擎接口至关重要）和确定性编排（对游戏逻辑至关重要）。 |
| 社区成熟度 | ★★★☆☆ | 较新但增长快。OpenAI 官方背书。 |
| 生产稳定性 | ★★★☆☆ | 较新。API 仍在变动。 |
| 框架锁定风险 | ★☆☆☆☆ | 最高。完全绑定 OpenAI API。无法切换模型提供商。 |

**核心问题**：OpenAI Agents SDK 的 handoff 机制让 LLM 决定"下一步调用哪个 Agent"。这在 TRPG 场景中是有害的——**游戏流程的下一步应该由确定性的状态机决定，不是由 LLM 决定。** 我们不希望 LLM "决定"跳过引擎直接叙事，或者"决定"在检定前就修改状态。

**结论**：如果项目只需要简单的 Tool Calling 且完全绑定 OpenAI，它是一个可用的轻量选择。但项目的两个核心需求——结构化输出保证 + 确定性编排——它都不提供。

---

### 1.10 综合评分矩阵

| 维度 | PydanticAI | LangGraph | Pyd+Lang | LangChain | Mastra | CrewAI | AutoGen | OpenAI SDK |
|------|-----------|-----------|----------|-----------|--------|--------|---------|------------|
| 学习成本 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 开发效率 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| 可维护性 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 类型安全 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |
| 调试体验 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 多 Agent | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| Workflow | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |
| 长期演进 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| 状态机契合 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |
| 结构化JSON | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐ |
| TRPG适合度 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ | ⭐ | ⭐ | ⭐⭐⭐ |
| 社区成熟度 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 生产稳定性 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| 锁定风险(逆) | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | ⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐ |
| **加权总分** | **55** | **54** | **56** | **27** | **47** | **31** | **31** | **36** |

> 权重分配：TRPG 适合度 ×3，结构化 JSON ×2，状态机契合 ×2，Workflow ×2，类型安全 ×2，其余 ×1。总分范围 14-70。
>
> **注意：以上评分矩阵针对的是 Runtime Keeper Agent 系统。** Module Parser Agent 系统的需求差异较大，下面单独分析。

---

### 1.11 专项分析：Module Parser Agent 系统需要什么框架？

上面的评分矩阵以 Runtime Keeper Agent 为基准。但 Module Parser Agent 系统（Parser Agent + Reviewer Agent + 确定性校验流水线）的框架需求**完全不同**：

#### 1.11.1 Module Parser Agent 的本质特征

```text
Module Parser Agent 系统本质上是：

  一个离线 ETL 数据处理流水线
      +
  需要大上下文的 LLM 结构化提取
      +
  确定性的多层校验
      +
  人工审批发布流程
```

关键特征：

| 特征 | Module Parser Agent | 对框架的要求 |
|------|--------------------|-------------|
| **离线** | 不参与游戏循环，可以等几十秒 | 不需要低延迟，可以用最强模型 |
| **大上下文** | 一次读取整个模组（可达 100 页） | 需要 200K token 上下文窗口（模型能力，非框架能力） |
| **结构化输出是核心** | Parser 输出 `ModuleDraft`，Reviewer 输出 `ReviewReport` | 强类型约束 + 校验失败自动重试 |
| **流水线是线性的** | 预处理 → Parser → 后处理 → Reviewer → 人工审批 | 不需要复杂分支/graph |
| **确定性校验步骤多** | Schema 校验、引用完整性、符号表检查、Expr 语法检查 | 纯代码，不需要 LLM，不需要框架 |
| **需要来源追溯** | 每个字段必须携带 `source_references` | 框架不需要参与——这是 Pydantic Model 的字段设计 |
| **有人工审核节点** | Reviewer 输出后必须人工批准 | 框架本身不需要支持 Human-in-the-Loop——这是流水线设计 |

#### 1.11.2 逐个框架分析（Module Parser 视角）

**PydanticAI — ★★★★★（完美匹配）**

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class ModuleDraft(BaseModel):
    """Parser Agent 的结构化输出。"""
    world_ref: str
    scenes: list[SceneDraft]
    entities: list[EntityDraft]
    checkpoints: list[CheckpointDraft]
    san_triggers: list[SanTriggerDraft] = []
    win_conditions: list[WinConditionDraft] = []
    source_references: dict[str, str]  # 字段 → 来源片段映射
    confidence_notes: dict[str, float]  # 字段 → 置信度
    unresolved_questions: list[str]

class ReviewReport(BaseModel):
    """Reviewer Agent 的结构化输出。"""
    status: Literal["pass", "needs_revision", "blocked"]
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    mechanism_abcd_coverage: dict[str, bool]
    human_review_checklist: list[ChecklistItem]

# Parser Agent: 模组原文 → ModuleDraft
parser = Agent(
    model="claude-opus-4",  # 需要大上下文 + 强提取能力
    result_type=ModuleDraft,
    system_prompt="""你是 CoC 模组的结构化解析器。
    
从模组原文中提取所有场景、实体、检定、规则、SAN 触发器和结局条件。

关键约束：
1. 每个字段必须携带 source_references（追溯到原文段落）
2. 原文不含的信息不得凭空补造
3. 无法确定的字段标记在 unresolved_questions 中
4. Entity.secrets 必须与 Entity.public_persona 严格分离""",
    tools=[query_skill_catalog, query_hook_definitions],  # 只读参考工具
)

# Reviewer Agent: ModuleDraft + 原文 → ReviewReport
reviewer = Agent(
    model="claude-sonnet-5",
    result_type=ReviewReport,
    system_prompt="""你是 CoC 模组的质量审查员。
    
检查 ModuleDraft 的完整性、正确性和可执行性。

审查维度：
- A 类：是否存在应设为 refuse_ops 但未设置的实体？
- B 类：是否存在条件满足后必须触发但缺失的 Hook？
- C 类：是否存在成功反而产生代价但未标注的检定？
- D 类：被 Rule/Expr 引用的状态是否都已落库？
- 秘密隔离：secrets 是否混入公开字段？
- 引用完整性：所有 ID 引用是否可解析？
- 可执行性：Rule/Op 能否被引擎执行？""",
    tools=[query_engine_capabilities],  # 查询引擎支持哪些 Op/Hook
)
```

为什么 PydanticAI 是 Module Parser 的最佳选择：

1. **结构化输出是核心。** Parser 和 Reviewer 的本质都是"非结构化文本 → 结构化 JSON"。PydanticAI 的 `result_type` 是这把刀的刀刃——输出不合法 → 自动重试 → 不需要手动写 retry + validation 逻辑。
2. **大上下文支持来自模型，不是框架。** Claude Opus 200K 直接作为 `model` 参数。框架不限制上下文大小。
3. **不需要编排。** 离线流水线是线性的：预处理 → Parser → 后处理 → Reviewer → 人工审批。每个步骤的输出是下一个步骤的输入。不需要 StateGraph。一个简单的 Python script 或 FastAPI endpoint 就够。
4. **Pydantic Model 全栈复用。** `ModuleContent` 的定义同时用于：(a) Parser 的 `result_type`，(b) 后处理的 Schema 校验基准，(c) 引擎加载 Content 层的类型定义。**同一套类型，三个用途。**

**LangGraph — ★★★☆☆（过度设计）**

Module Parser 的流水线是严格线性的。预处理 → Parser → 后处理 → Reviewer → 人工审批。没有条件分支（除了"校验失败 → 打回"这个循环），没有并行执行，不需要状态恢复。

为线性流水线引入 StateGraph 是过度设计——一个 async function 调用序列完全足够。**LangGraph 解决的是"复杂的、有分支的、可能需要回滚的状态机"——Module Parser 不是这种场景。**

**OpenAI Agents SDK — ★★★☆☆（可行但不推荐）**

缺少 `result_type` 等价物——需要自己写 JSON Schema 校验 + 重试逻辑。对于 Parser Agent（输出数百个字段的复杂 JSON），手动重试+校验的代码量远大于 PydanticAI 的一行声明。

**LangChain — ★☆☆☆☆（不推荐）**

同上，过于厚重。Module Parser 不需要 Chain/LCEL/Runnable 抽象。

**CrewAI / AutoGen — ☆☆☆☆☆（完全不适用）**

Module Parser 不需要两个 Agent 互相聊天。Parser 输出 → Reviewer 输入，这是单向数据流，不是对话。

**Mastra — ★★☆☆☆（技术栈不匹配）**

同上，Python 项目引入 TS 服务的运维成本远超收益。

#### 1.11.3 Module Parser Agent 的框架结论

```text
Parser Agent:     PydanticAI ✅（零其他依赖）
Reviewer Agent:   PydanticAI ✅（零其他依赖）
编排流水线:        纯 Python async function（零框架依赖）
确定性校验:        纯 Python + Pydantic（零框架依赖）
人工审批:         简单的 Web UI 或 CLI（与框架无关）
```

**整个 Module Parser 系统只需要一个框架：PydanticAI。** 它处理两个 LLM 调用点（Parser + Reviewer），其余全部是纯代码。

---

## 二、推荐方案

### 2.1 三阶段推荐

```text
MVP 阶段（现在 → 跑通 Demo）
  ├── 方案: PydanticAI + 自定义 Game Loop
  ├── 依赖: PydanticAI + FastAPI + PostgreSQL
  └── 理由: 最小学习成本，最快开发速度，最少依赖。PG 单数据库足够。

中期阶段（Demo 稳定 → 复杂模组）
  ├── 方案: PydanticAI + LangGraph
  ├── 新增: LangGraph 做编排层（仅在 game loop 复杂度确实需要时）
  └── 理由: 当 while 循环变成 50+ 行且有嵌套分支时，引入 graph 有净收益

长期阶段（多模组 → 产品化）
  ├── 方案: PydanticAI + LangGraph + 自定义 Engine 微服务
  ├── 新增: 独立 Engine Service（FastAPI）、Module Parser Service、Reviewer Service
  └── 理由: 引擎成为独立可测试的确定性服务；Agent 层仅保留 LLM 调用逻辑
```

### 2.2 为什么不是其他方案

**为什么不是 LangGraph 一上来就用？**

MVP 的 game loop 是这样的：

```python
async def game_loop(player_input: str, context: GameContext) -> str:
    # Step 1: Intent → ActionPlan
    action_plan = await planner.run(player_input, deps=context)
    
    # Step 2: Route
    if action_plan.route == "narrative":
        return await narrator.run(
            f"玩家做了: {action_plan.narrative_intent}", 
            deps=context
        )
    
    # Step 3: Engine
    outcome = engine.execute(action_plan, context.game_state)
    
    # Step 4: Narration
    return await narrator.run(
        f"引擎结果: {outcome.model_dump()}", 
        deps=context
    )
```

这是一个 **20 行的 async function，有 1 个 if 分支**。为它引入 LangGraph（StateGraph + TypedDict + Node + Edge + ConditionalEdge + Compile）是**用大炮打蚊子**。工具的复杂度不应超过问题的复杂度。

当这个函数变成：多个条件分支 + 重试逻辑 + 超时处理 + 并行检定 + 子流程（战斗回合）——那时再引入 LangGraph，迁移成本可控（Pydantic Model 完全复用）。

**为什么不是 LangChain？**

LangChain 的抽象层厚度远超本项目的胶水层厚度。一个 20 行的 async function 用 LangChain 写可能需要 100+ 行 Chain 定义 + 5 个 Runnable。且 LangChain 团队已把重心转到 LangGraph。

**为什么不是 OpenAI Agents SDK？**

两个致命问题：
1. 完全绑定 OpenAI。项目应该保留切换模型提供商的自由（Claude 在结构化输出和叙事生成上各有优势）。
2. Handoff 让 LLM 决定流程——而游戏流程必须由确定性的状态机决定。

**为什么不是 Mastra？**

技术栈不匹配。项目是 Python/FastAPI。引入 TypeScript 服务的运维成本远超框架收益。

**为什么不是 CrewAI / AutoGen？**

它们解决的是"多 Agent 对话协作"问题，本项目需要的是"单 Agent + 确定性引擎"模式。方向性不匹配。

---

## 三、推荐运行时架构

### 3.1 架构总览

```text
                        ┌──────────────────────┐
                        │     WebSocket / REST  │
                        │    (FastAPI 传输层)    │
                        └──────────┬───────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    ▼                     │
              │         ┌──────────────────┐            │
              │         │  Session Manager  │            │
              │         │  · Room 生命周期   │            │
              │         │  · Player 连接     │            │
              │         │  · Turn 管理       │            │
              │         └────────┬─────────┘            │
              │                  │                       │
              │    ┌─────────────▼─────────────┐        │
              │    │     Game Loop (编排层)      │        │
              │    │                             │        │
              │    │  ① ContextAssembler        │        │
              │    │     组装 LLM 上下文          │        │
              │    │     (仅公开信息！)           │        │
              │    │         │                   │        │
              │    │         ▼                   │        │
              │    │  ② Planner (LLM 调用)       │        │
              │    │     Input → ActionPlan      │        │
              │    │     PydanticAI Agent        │        │
              │    │         │                   │        │
              │    │         ▼                   │        │
              │    │  ③ RouteDispatcher          │        │
              │    │     narrative? → 跳到 ⑤     │        │
              │    │     engine?    → 进入 ④     │        │
              │    │         │                   │        │
              │    │         ▼                   │        │
              │    │  ④ Game Engine (确定性)      │        │
              │    │     · CheckResolver         │        │
              │    │     · RuleEvaluator         │        │
              │    │     · StateManager          │        │
              │    │     · EventLogger           │        │
              │    │     · WinConditionEval      │        │
              │    │         │                   │        │
              │    │         ▼                   │        │
              │    │  ⑤ Narrator (LLM 调用)      │        │
              │    │     ConfirmedOutcome        │        │
              │    │     → Natural Language      │        │
              │    │     PydanticAI Agent        │        │
              │    │                             │        │
              │    └─────────────┬───────────────┘        │
              │                  │                       │
              │                  ▼                       │
              │         ┌──────────────────┐            │
              │         │   数据层（MVP: PG）  │            │
              │         └──────────────────┘            │
              │                                          │
              │         ┌──────────────────┐            │
              │         │  离线导入流水线    │            │
              │         │  · ModuleParser   │            │
              │         │  · ModuleReviewer │            │
              │         │  (独立进程)        │            │
              │         └──────────────────┘            │
              └──────────────────────────────────────────┘
```

### 3.2 为什么这样设计

**核心原则：LLM 只被调用两次，中间是纯确定性代码。**

```text
玩家输入
    │
    ▼
[LLM 调用 1: Planner]          ← 唯一允许 LLM "思考"的时刻
    │ 输出: ActionPlan (结构化 JSON)
    │ 权限: 只读（可查询 Entity/Scene/Character，不可修改任何状态）
    ▼
[Route Dispatcher]             ← 纯代码。if/else。确定性的。
    │
    ├── narrative → 跳过引擎
    │
    └── engine → 
        ▼
[Game Engine]                  ← 纯代码。无 LLM。确定性。
    │ · CheckResolver: d100 检定
    │ · RuleEvaluator: (hook, when, then) 求值
    │ · StateManager: 校验 op → 执行 → 写入 GameState
    │ · EventLogger: append Event（权威真相）
    │ · WinConditionEval: 表达式求值 → 判断结局
    │ 输出: ConfirmedOutcome (结构化 JSON)
    ▼
[LLM 调用 2: Narrator]         ← LLM 只负责"怎么描述"
    │ 输入: ConfirmedOutcome + 公开上下文（不含 secrets！）
    │ 输出: 自然语言叙事
    │ 硬约束: 不可改写引擎结果
    ▼
返回玩家
```

**为什么 Planner 和 Narrator 必须是两个独立的 LLM 调用，而不是一个？**

1. **不同职责需要不同的系统提示词。** Planner 需要"你是守秘人，你需要判断玩家意图并生成动作计划"。Narrator 需要"你是叙述者，你需要根据引擎结果生成沉浸式叙事"。合并会导致提示词臃肿且行为不可预测。

2. **不同的模型需求。** Planner 需要强推理能力（分析玩家意图、匹配合适的 Checkpoint）→ Claude Sonnet/Opus。Narrator 需要快速生成流畅文本 → Claude Haiku 或 GPT-4o-mini。分开调用允许为每个环节选择最优性价比模型。

3. **安全问题——Narrator 绝不能看到 secrets。** Planner 的上下文包含 Checkpoint 信息（用于匹配），但不包含 `Entity.secrets`。Narrator 的上下文则更严格——只包含 `ConfirmedOutcome` 中标记为 `player_visible` 的信息。如果两个调用合并，信息隔离边界会模糊。

4. **引擎在中间。** Planner 输出 ActionPlan → 引擎执行 → Narrator 输入 ConfirmedOutcome。引擎的执行结果会改变传给 Narrator 的上下文（例如新增了 `player_visible_information`）。这不是一次 LLM 调用能完成的。

### 3.3 Game Loop 实现（MVP 版本，PydanticAI + 自定义循环）

```python
from pydantic_ai import Agent
from pydantic import BaseModel, Field
from typing import Literal
from enum import Enum

# ──── Pydantic Models: 核心接口定义 ────

class Route(str, Enum):
    NARRATIVE = "narrative"
    ENGINE = "engine"

class ActionType(str, Enum):
    TALK = "talk"
    INSPECT = "inspect"
    CHECK = "check"
    USE_ITEM = "use_item"
    MOVE = "move"

class RoleplayTier(str, Enum):
    NONE = "none"
    REASONABLE = "reasonable"
    EXCELLENT = "excellent"

class ActionPlan(BaseModel):
    """Planner Agent 的结构化输出。通过 Pydantic 强制校验。"""
    route: Route
    action_type: ActionType
    actor_id: str
    target_id: str | None = None
    checkpoint_id: str | None = None
    narrative_intent: str = Field(description="玩家想要做什么，用自然语言描述")
    proposed_skills: list[str] = Field(default_factory=list)
    roleplay_tier: RoleplayTier | None = None

class Narration(BaseModel):
    """Narrator Agent 的结构化输出。"""
    text: str = Field(description="旁白/场景叙述")
    npc_dialogue: str | None = None
    sensory_details: list[str] = Field(default_factory=list)
    visible_changes: list[str] = Field(default_factory=list)


# ──── PydanticAI Agents: LLM 调用封装 ────

planner = Agent(
    model="claude-sonnet-5",
    result_type=ActionPlan,
    system_prompt="""你是 CoC 7e 的守秘人（Keeper）。

你的职责是理解玩家意图并生成 ActionPlan。

路由规则:
- narrative: 自由对话、提问、观察（不涉及技能检定或状态变更）
- engine: 调查、检定、战斗、使用物品、移动

行动类型:
- talk: 与 NPC 对话/说服/恐吓
- inspect: 调查/搜索/观察物体或场景
- check: 明确声明技能检定
- use_item: 使用物品/开门/撬锁
- move: 移动到另一个场景

软判据 (roleplay_tier):
- none: 玩家只说"我说服他"，没有阐述理由
- reasonable: 玩家给出了合理的理由
- excellent: 玩家有精彩的演绎

重要：你只能读取游戏状态，不能提议修改。任何状态变更必须由引擎执行。""",
)

narrator = Agent(
    model="claude-haiku-4-5",  # 叙事用更快更便宜的模型
    result_type=Narration,
    system_prompt="""你是 CoC 7e 的氛围叙述者。

根据引擎返回的 ConfirmedOutcome 生成沉浸式叙事。

规则:
1. 引擎判定的事实不可改写。成功就是成功，失败就是失败。
2. 用感官细节增强氛围（视觉、听觉、触觉、嗅觉）。
3. 如果涉及 NPC，用符合其人设的语气生成对话。
4. 不要泄露玩家尚未发现的信息。
5. 不要在叙事中暗示暗骰的存在。""",
)


# ──── Game Loop: 编排层（纯 Python，无框架依赖） ────

class GameLoop:
    """主持编排 Agent 的核心循环。
    
    MVP 用简单的 async function 实现。
    未来复杂度增长可迁移至 LangGraph StateGraph。
    """
    
    def __init__(self, engine: GameEngine, context_builder: ContextBuilder):
        self.engine = engine
        self.context_builder = context_builder
    
    async def process_turn(
        self,
        player_input: str,
        room_id: str,
        character_id: str,
    ) -> TurnResult:
        """处理一个玩家回合。六步流水线。"""
        
        # Step 1: 构建上下文（纯代码，仅包含公开信息）
        # secrets、hidden checkpoints、未发现实体的 content 不在此处
        context = await self.context_builder.build(
            room_id=room_id,
            character_id=character_id,
        )
        
        # Step 2: Planner — 意图识别 + ActionPlan 生成（LLM 调用 1）
        plan_result = await planner.run(
            f"玩家输入: {player_input}\n\n"
            f"当前场景: {context.scene_description}\n"
            f"可见实体: {context.visible_entities}\n"
            f"可用动作: {context.available_checkpoints}\n"
            f"角色状态: {context.character_status}",
        )
        action_plan: ActionPlan = plan_result.data  # ← Pydantic 已校验
        
        # Step 3: 路由分发（纯代码）
        if action_plan.route == Route.NARRATIVE:
            # 自由叙事：跳过引擎，直接生成回复
            narration = await self._narrate_free(
                player_intent=action_plan.narrative_intent,
                context=context,
            )
            return TurnResult(
                narration=narration,
                action_plan=action_plan,
                outcome=None,
            )
        
        # Step 4: 引擎执行（纯代码，确定性）
        outcome = self.engine.execute(
            action_plan=action_plan,
            game_state=context.game_state,
        )
        # outcome 是 ConfirmedOutcome——包含 success/facts/state_changes/events
        
        # Step 5: Narrator — 根据引擎结果生成叙事（LLM 调用 2）
        narration = await self._narrate_outcome(
            outcome=outcome,
            action_plan=action_plan,
            context=context,
        )
        
        # Step 6: 检查结局（纯代码）
        ending = self.engine.check_win_conditions(context.game_state)
        
        return TurnResult(
            narration=narration,
            action_plan=action_plan,
            outcome=outcome,
            ending=ending,
        )
    
    async def _narrate_free(self, player_intent: str, context) -> Narration:
        """自由叙事模式：玩家不涉及规则，直接生成回复。"""
        result = await narrator.run(
            f"玩家: {player_intent}\n"
            f"场景: {context.scene_description}\n"
            f"在场的 NPC: {context.npcs_present}",
        )
        return result.data
    
    async def _narrate_outcome(
        self, outcome, action_plan: ActionPlan, context
    ) -> Narration:
        """根据引擎 ConfirmedOutcome 生成叙事。
        
        硬约束：
        - 只传入 player_visible_information
        - 不可改写 engine 的 success/fail 判定
        """
        result = await narrator.run(
            f"玩家尝试: {action_plan.narrative_intent}\n"
            f"检定结果: {'成功' if outcome.success else '失败'}\n"
            f"玩家可见信息: {outcome.player_visible_information}\n"
            f"状态变化: {outcome.state_changes}\n"
            f"场景: {context.scene_description}",
        )
        return result.data
```

**为什么 MVP 用自定义循环而不是 LangGraph？**

这个 GameLoop 类目前约 80 行。它有：
- 1 个 if 分支（narrative vs engine）
- 2 个 LLM 调用
- 纯代码引擎调用

为它引入 LangGraph 会增加：
- StateGraph 定义（~30 行）
- TypedDict 定义（~20 行）
- Node 函数包装（~20 行/每个节点）
- ConditionalEdge 定义
- 编译步骤

净增 ~100+ 行框架代码，换来与 80 行业务代码等价的行为。**不合算。**

当 GameLoop 出现以下信号时，引入 LangGraph：
1. 分支超过 3 层嵌套（例如 combat 子循环、SAN 子循环、结局子循环各有不同分支）
2. 需要并行执行（例如同时处理多个玩家的检定请求）
3. 需要 Checkpoint/Resume（例如引擎执行到一半等待玩家掷骰，然后从暂停点恢复）
4. 需要 Human-in-the-Loop 暂停（pending_check 等待客户端提交掷骰结果）

那时迁移：Pydantic Model 全部复用，只需将函数体包进 LangGraph Node。

---

## 四、完整系统架构设计

如果我是这个项目的架构负责人，以下是我设计的完整系统。

### 4.1 系统分层全景

```text
┌─────────────────────────────────────────────────────────────────┐
│                        Transport Layer                          │
│                                                                  │
│  WebSocket: 玩家实时通信（输入/输出/检定交互）                     │
│  REST:      房间管理、角色创建、模组列表                           │
│  FastAPI:   统一路由、中间件、依赖注入                             │
└────────────────────────────────┬────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                     Orchestration Layer                          │
│                                                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐   │
│  │ GameLoop    │  │ SessionMgr   │  │ PendingCheckHandler  │   │
│  │ (回合主循环) │  │ (房间生命周期) │  │ (玩家掷骰交互)        │   │
│  └──────┬──────┘  └──────────────┘  └──────────────────────┘   │
│         │                                                        │
│         │ 每个回合:                                               │
│         │   ContextAssembler → Planner → RouteDispatch           │
│         │   → [Engine] → Narrator → Output                       │
└─────────┼────────────────────────────────────────────────────────┘
          │
┌─────────▼────────────────────────────────────────────────────────┐
│                       Agent Layer (LLM)                          │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │ Planner          │  │ Narrator         │                    │
│  │ Model: Sonnet    │  │ Model: Haiku     │                    │
│  │ Output: ActionPlan│  │ Output: Narration│                   │
│  │ Tools: Read-only │  │ Tools: None      │                    │
│  └──────────────────┘  └──────────────────┘                    │
│                                                                  │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │ ModuleParser     │  │ ModuleReviewer   │                    │
│  │ (离线)            │  │ (离线)            │                    │
│  │ Model: Opus      │  │ Model: Sonnet    │                    │
│  └──────────────────┘  └──────────────────┘                    │
│                                                                  │
│  所有 Agent 都是 PydanticAI Agent 实例。                          │
│  输入/输出都是 Pydantic Model——类型安全贯穿始终。                  │
└──────────────────────────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                     Engine Layer (Deterministic)                 │
│                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │CheckResolv │ │SANManager  │ │CombatPipe  │ │RuleEval    │  │
│  │· d100      │ │· 6 种 SAN  │ │· 12 hooks  │ │· Expr 求值  │  │
│  │· 难度等级  │ │· source_tag│ │· 伤害/护甲 │ │· Op 执行   │  │
│  │· 奖惩骰    │ │· capped    │ │· 闪避/重伤 │ │· priority  │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
│                                                                  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │StateMgr    │ │EventLogger │ │WinCondEval │ │ViewProject │  │
│  │· op 校验   │ │· append    │ │· expr 求值  │ │· secrets   │  │
│  │· 不变式    │ │· 事件溯源   │ │· is_ending │ │  过滤      │  │
│  │· 物化视图  │ │· cause 追踪│ │· 结局触发   │ │· hidden    │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
│                                                                  │
│  所有模块是纯 Python 函数或类。无 LLM 依赖。完全可单元测试。       │
└──────────────────────────────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼────────────────────────────────┐
│                       Data Layer                                 │
│                                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │Reference │  │Content   │  │GameState │  │EventLog  │       │
│  │只读      │  │只读      │  │可写      │  │只增      │       │
│  │          │  │          │  │          │  │          │       │
│  │Skill     │  │World     │  │Room      │  │Event     │       │
│  │Occupation│  │ModulePack│  │Character │  │(权威真相) │       │
│  │Weapon    │  │Scene     │  │Player    │  │          │       │
│  │          │  │Entity    │  │Note      │  │          │       │
│  │          │  │Checkpoint│  │          │  │          │       │
│  │          │  │SanTrigger│  │          │  │          │       │
│  │          │  │WinCond   │  │          │  │          │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│                                                                  │
│  PostgreSQL: 持久化所有数据。事件溯源以 events 表为权威。          │
│  （中期引入 Redis：pending_check TTL、会话缓存、热状态加速。）        │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Runtime Layer 详细设计

#### 4.2.1 Game Loop（核心编排）

Game Loop 是系统的中枢。MVP 阶段实现为带状态的 async function，未来可迁移至 LangGraph。

```python
class GameLoop:
    """TRPG 回合处理器。
    
    设计决策：
    - MVP: 自定义 async loop（当前实现）
    - 未来: 当分支复杂度超过阈值 → 迁移至 LangGraph StateGraph
    - PydanticAI Agent 是 LLM 调用的稳定抽象，迁移不影响 Agent 定义
    """
    
    def __init__(
        self,
        planner: Agent[None, ActionPlan],
        narrator: Agent[None, Narration],
        engine: GameEngine,
        context_builder: ContextBuilder,
    ):
        self.planner = planner
        self.narrator = narrator
        self.engine = engine
        self.context_builder = context_builder
    
    async def process_turn(self, input: TurnInput) -> TurnOutput:
        ...
```

#### 4.2.2 ContextAssembler（信息隔离的关键）

这是系统中最容易被忽视、但也最重要的组件。它决定了**哪些信息进入 LLM 的上下文窗口**。

```python
class ContextBuilder:
    """组装 LLM 调用所需的上下文。
    
    硬约束：
    - Entity.secrets NEVER 进入 Planner 或 Narrator 上下文
    - 未发现的 Entity 的 content NEVER 进入上下文
    - hidden=true 的 Checkpoint 结果 NEVER 进入 Narrator 上下文
    - 其他玩家的私有 Note NEVER 进入上下文
    """
    
    async def build_for_planner(
        self, room_id: str, character_id: str
    ) -> PlannerContext:
        """为 Planner 构建上下文——比 Narrator 宽一些，
        因为 Planner 需要知道哪些 Checkpoint 可匹配。
        但仍然不包含 secrets。"""
        scene = await self.get_current_scene(character_id)
        return PlannerContext(
            scene_description=scene.description,
            visible_entities=self.filter_visible(scene.entities, room_id),
            available_checkpoints=self.filter_available(
                scene.checkpoint_ids, character_id
            ),
            character_status=await self.get_character_public_status(character_id),
            recent_player_visible_events=await self.get_recent_events(
                room_id, visibility="player_visible"
            ),
            party_status=await self.get_party_public_status(room_id),
        )
    
    async def build_for_narrator(
        self, outcome: ConfirmedOutcome, context: PlannerContext
    ) -> NarratorContext:
        """为 Narrator 构建上下文——比 Planner 更严格。
        只包含 ConfirmedOutcome 中的 player_visible 信息。"""
        return NarratorContext(
            player_intent=outcome.action_narrative,
            check_result=outcome.check_result_if_visible,
            player_visible_info=outcome.player_visible_information,
            scene_description=context.scene_description,
            npcs_present=context.npcs_present,
            # secrets NOT here
            # hidden check results NOT here
            # other players' private notes NOT here
        )
```

#### 4.2.3 Session Manager

```python
class SessionManager:
    """管理游戏房间的生命周期。
    
    职责：
    - 房间创建/加入/离开/销毁
    - 玩家连接状态（WebSocket 心跳）
    - 回合顺序管理
    - 游戏阶段流转（lobby → playing → ended）
    """
    
    async def create_room(self, module_id: str, host_id: str) -> Room:
        """创建房间：加载 ModuleContent → 初始化 GameState → 返回房间码"""
        ...
    
    async def start_game(self, room_id: str) -> None:
        """开始游戏：校验人数 → 初始化 entity_states → 广播开场叙事"""
        ...
    
    async def end_game(self, room_id: str, ending: WinCondition) -> None:
        """结束游戏：写入结局 Event → 广播结局叙事 → 更新房间 phase"""
        ...
```

#### 4.2.4 PendingCheck Handler

当检定 `roll_mode='prompt'` 时，引擎暂停，等待玩家在客户端完成掷骰交互：

```python
class PendingCheckHandler:
    """处理需要玩家交互的检定。
    
    流程：
    1. 引擎创建 PendingCheck → 写入 Player.pending_check
    2. 向目标客户端投递 check.request 事件
    3. 玩家点击"检定" → 提交 request_id + skill_id
    4. Handler 校验 → 调用 CheckResolver 结算 → 写 Event
    5. 清空 pending_check → 游戏继续
    """
    
    async def create_pending_check(
        self, checkpoint: Checkpoint, character: Character
    ) -> PendingCheck:
        """创建挂起检定。同时启动超时计时器。"""
        ...
    
    async def resolve_pending_check(
        self, request_id: str, selected_skill_id: str, player_id: str
    ) -> CheckResult:
        """玩家提交检定选择 → 校验 → 结算 → 写 Event。"""
        ...
    
    async def handle_timeout(self, request_id: str) -> None:
        """超时处理：auto_roll / cancel / reprompt。"""
        ...
```

### 4.3 Agent Layer 详细设计

#### 4.3.1 Planner Agent

```python
from pydantic_ai import Agent, Tool

planner = Agent(
    model="claude-sonnet-5",  # 或在配置中切换 openai:gpt-4o
    result_type=ActionPlan,
    system_prompt="""...""",
    tools=[
        Tool(query_scene, name="查询场景"),
        Tool(query_entity, name="查询实体"),
        Tool(query_character, name="查询角色状态"),
        Tool(query_checkpoints, name="查询可用动作"),
    ],
    # 所有工具都是只读的。Planner 不能修改任何状态。
    # ActionPlan 是它的唯一输出。
)
```

**为什么 Planner 的工具都是只读的？**

因为 Planner 的职责是"理解玩家想做什么"——它需要查询游戏世界来做出正确的判断，但它不应直接修改世界。修改世界是引擎的职责。如果 Planner 有写工具，就会出现"LLM 绕过引擎直接改了 cat.alive"的 bug。

ActionPlan 是 Planner 与引擎之间唯一的接口。引擎收到 ActionPlan 后，自行决定是否执行、如何执行。

#### 4.3.2 Narrator Agent

```python
narrator = Agent(
    model="claude-haiku-4-5",  # 叙事对推理要求低，用更快更便宜的模型
    result_type=Narration,
    system_prompt="""...""",
    # Narrator 没有任何工具——它只做文本生成
    # 这确保它不能偷偷查询 secrets 或修改状态
)
```

#### 4.3.3 模型选择策略

| Agent | MVP 模型 | 为什么 | 降级模型 |
|-------|---------|--------|---------|
| Planner | Claude Sonnet 5 | 需要强推理：意图分析、Checkpoint 匹配、软判据评估 | GPT-4o |
| Narrator | Claude Haiku 4.5 | 低延迟叙事生成，推理需求低 | GPT-4o-mini |
| ModuleParser | Claude Opus 4 | 需要大上下文 + 精确字段提取 + 理解复杂模组结构 | Claude Sonnet 5 |
| ModuleReviewer | Claude Sonnet 5 | 需要强推理：检查逻辑一致性、机制 A/B/C/D 审查 | GPT-4o |

关键原则：**不锁定单一模型提供商。** PydanticAI 支持通过 `model` 参数切换提供商（Anthropic / OpenAI / Google / 兼容 OpenAI API 的任何服务）。这让团队可以根据每个环节的需求选择最优模型，且未来不被任何供应商锁定。

### 4.4 Tool Layer 详细设计

#### 4.4.1 Tool 分层原则

```text
读工具（Planner 可用）:
  query_scene      查询场景描述、出口、可用 Checkpoint
  query_entity     查询实体公开信息（不含 secrets！）
  query_character  查询角色卡、HP/SAN/技能/装备
  query_checkpoints 查询可用动作列表
  search_inventory 搜索背包

写工具（只有引擎可用——LLM 永远不可直接调用！）:
  modify_entity_state   修改实体状态
  modify_character      修改角色属性
  add_event             写入事件
  create_pending_check  创建挂起检定

混合工具（引擎内部调用，LLM 不可见）:
  roll_d100             引擎使用——骰子结果必须是服务端权威的
  evaluate_rule         引擎使用——规则求值
  check_win_condition   引擎使用——结局判断
```

#### 4.4.2 Tool 实现示例

```python
from pydantic_ai import Tool

# 注意：返回类型是 Pydantic Model，确保 LLM 拿到的是结构化数据
class SceneInfo(BaseModel):
    id: str
    title: str
    description: str
    exits: list[str]
    available_checkpoints: list[CheckpointSummary]

async def query_scene(scene_id: str, room_id: str) -> SceneInfo:
    """查询场景信息。只返回公开内容。"""
    scene = await scene_repo.get(scene_id)
    checkpoints = await checkpoint_repo.get_by_scene(scene_id)
    return SceneInfo(
        id=scene.id,
        title=scene.title,
        description=scene.description,
        exits=scene.exits or [],
        available_checkpoints=[
            CheckpointSummary(id=c.id, match_hint=c.match_hint)
            for c in checkpoints
            if not c.hidden  # ← 暗骰不在 Planner 上下文中
        ],
    )

# 注册为 PydanticAI Tool
query_scene_tool = Tool(
    query_scene,
    name="查询场景",
    description="获取当前场景的公开信息，包括可用的行动选项",
)
```

### 4.5 Memory Layer 详细设计

本项目不使用 LLM 原生的"Memory"（向量数据库、对话历史总结）。所有"记忆"由确定性的事件溯源系统承载。

```text
┌──────────────────────────────────────────────────┐
│               Memory = EventLog                   │
│                                                   │
│  短期记忆（当前会话）:                               │
│    · 物化视图: 可从 events 重建                    │
│    · 生命周期: 单次游戏会话                         │
│    · MVP: 直接从 PG 读取（单房间 ~19KB）             │
│    · 中期: Redis 缓存热状态                         │
│                                                   │
│  长期记忆（跨会话）:                                 │
│    · PostgreSQL events 表                          │
│    · 每条 event 携带: room_id, ts, type, payload   │
│    · 事件溯源: 状态 = reduce(events)               │
│    · 断线重连: 回放 events 重建完整状态              │
│                                                   │
│  叙事上下文（每回合）:                                │
│    · ContextAssembler 从 events + entity_states    │
│      动态构建，不依赖 LLM "记住"                     │
│    · 每次 LLM 调用的上下文是独立构建的               │
│    · 不依赖上一轮 LLM 的"记忆"                      │
└──────────────────────────────────────────────────┘
```

**为什么不用向量数据库做 Memory？**

1. 游戏状态不需要"相似性搜索"——需要的是精确的"player_001 是否拥有钥匙"。
2. 向量数据库适合"语义相似"，游戏状态需要"事实精确"。
3. 事件溯源提供了可审计、可回放、可调试的记忆机制——每个状态变化都有时间戳和 cause。

### 4.6 State Layer 详细设计

```python
# 游戏状态的全量类型定义（Pydantic Models）

class GameState(BaseModel):
    """一个房间的完整游戏状态。物化视图——可从 Events 重建。"""
    room_id: str
    phase: Literal["lobby", "playing", "ended"]
    entity_states: dict[str, dict[str, Primitive]]
    characters: dict[str, CharacterState]
    turn_number: int
    current_active_character: str | None
    pending_checks: dict[str, PendingCheck]

class CharacterState(BaseModel):
    id: str
    name: str
    attributes: Attributes
    derived_stats: DerivedStats
    skills: dict[str, int]
    equipment: list[str]
    weapons: list[str]
    conditions: list[Condition]
    ledger: dict[str, LedgerEntry]
    location: str  # SceneId
    flags: list[str]

class Primitive(BaseModel):
    """entity_states 中的值类型"""
    value: bool | int | str

# 状态写入口唯一：所有修改必须通过 StateManager
class StateManager:
    """状态的唯一写入口。
    
    所有 op 必须经过：
    1. 路径校验（key 存在于 entity_states 键空间）
    2. 权限校验（op 类型在 allowed_ops 内）
    3. 不变式校验（跨实体约束，如 D 类的 count 限制）
    4. 执行 + Event 写入（同一事务）
    """
    
    def execute_op(self, op: Op, room_id: str) -> StateChange:
        ...
```

### 4.7 Module Layer 详细设计

离线导入流水线——独立于游戏运行时的独立进程：

```text
┌────────────────────────────────────────────────────┐
│              Module Import Pipeline                 │
│                                                    │
│  Input: PDF / Markdown                              │
│     │                                               │
│     ▼                                               │
│  ┌──────────────┐                                   │
│  │ Preprocessor │  纯代码: PDF → 分段 Markdown       │
│  └──────┬───────┘  输出: SourceFragment[]            │
│         │                                           │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │ ParserAgent  │  PydanticAI Agent                 │
│  │ (Pass 1+2)   │  model: Claude Opus              │
│  └──────┬───────┘  输出: ModuleDraft                │
│         │                                           │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │ PostProcessor│  纯代码:                           │
│  │ + Validator  │  · Schema 校验                     │
│  └──────┬───────┘  · 引用完整性校验                  │
│         │         · 符号表检查                       │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │ReviewerAgent │  PydanticAI Agent                 │
│  │              │  model: Claude Sonnet             │
│  └──────┬───────┘  输出: ReviewReport               │
│         │                                           │
│         ▼                                           │
│  ┌──────────────┐                                   │
│  │ Human Review │  人工 A/B/C/D 质询                 │
│  │ + Approval   │  + 19-hook 空位检查                │
│  └──────┬───────┘                                   │
│         │                                           │
│         ▼                                           │
│  Output: ModuleContent (versioned, immutable)        │
└────────────────────────────────────────────────────┘
```

### 4.8 Workflow Layer 详细设计

对于"一个回合"这个核心 workflow，MVP 阶段用 GameLoop 类直接实现。随着系统演进，可能出现的子 workflow 及其处理方式：

| 子流程 | MVP 处理 | 未来处理 | 为什么 |
|--------|---------|---------|--------|
| 普通回合 | GameLoop.process_turn() | 同上（或 LangGraph StateGraph） | 线性主流程 |
| 战斗回合 | 暂不做 | LangGraph Subgraph | 12 个 hook 的多步流水线 |
| SAN 结算 | SANManager 纯函数 | 同上 | 6 种形态的确定性逻辑，不需要 LLM |
| 等待玩家掷骰 | PendingCheckHandler | LangGraph Human-in-the-Loop | 需要暂停 → 等待 → 恢复 |
| 结局触发 | WinConditionEval 纯函数 | 同上 | 布尔表达式求值，确定性 |
| 模组导入 | 独立脚本 | 独立 FastAPI 服务 | 离线任务，独立于运行时 |
| NPC 自主行为 | 暂不做 | B 类 Rule 触发 + Narrator | 由引擎 hook 驱动，不需要独立 Agent |

**核心原则：能用纯函数就别上 Workflow，能用 if/else 就别上 Graph。**

### 4.9 未来扩展分析

用户提到未来可能增加：NPC Agent、Combat Agent、Investigation Agent、Emotion Agent、Module Parser Agent。

逐个分析它们应该成为什么：

| 功能 | 应该成为 | 理由 |
|------|---------|------|
| **Module Parser Agent** | ✅ 独立 Agent（离线） | 确实是 LLM 的强项（PDF → 结构化数据）。PydanticAI Agent，离线运行。 |
| **Module Reviewer Agent** | ✅ 独立 Agent（离线） | 同上。与 Parser 在同一离线流水线中。 |
| **NPC Agent** | ❌ 不需要独立 Agent | NPC 行为由两部分驱动：(1) B 类 Rule 触发——引擎 hook 自动触发，(2) NPC 对话——Narrator 的一个子功能。独立 NPC Agent 意味着"多个 LLM 同时运行"，延迟翻倍且引入 Agent 间通信复杂度。把 NPC 对话视为 Narrator 调用时的一段特殊 prompt 即可。 |
| **Combat Agent** | ❌ 不需要独立 Agent | 战斗是 12 个 hook 的确定性流水线，由 CombatPipeline（引擎模块）执行。LLM 只在战斗开始（生成战斗叙事）和结束（描述结果）时介入——这是 Narrator 的职责。战斗中间不需要 LLM。 |
| **Investigation Agent** | ❌ 不需要独立 Agent | 调查是 Planner 的一个 action_type (`inspect`)。引擎根据 Checkpoint 执行检定 → 返回可见线索 → Narrator 描述。不需要单独 Agent。 |
| **Emotion Agent** | ❌ 不需要独立 Agent | 情感/氛围/NPC 语气是 Narrator 的自然职责。Narrator 的 system prompt 已经要求它"用感官细节增强氛围"。独立 Emotion Agent 会导致两个 LLM 生成的内容需要"拼接"，结果可能不协调。 |
| **Summary Agent** | ⚠️ 可选的独立 Agent（离线/异步） | 如果需要在回合之间生成剧情摘要（例如玩家断线重连时看到"目前为止发生了什么"），这可以是独立的轻量 Agent。但它不参与实时游戏循环——异步运行，结果写入 `rooms.rolling_summary`。 |

**结论：不需要更多运行时 Agent。** 系统只需要两个运行时 LLM 调用（Planner + Narrator），其余全部由确定性引擎处理。这是架构简洁性的核心保障。

### 4.10 项目目录结构

```text
arkham-case-files/
├── src/
│   ├── core/                     # 共享内核
│   │   ├── models/               # Pydantic Models（全栈共享）
│   │   │   ├── content.py        #   ModuleContent, Scene, Entity, ...
│   │   │   ├── runtime.py        #   ActionPlan, ConfirmedOutcome, ...
│   │   │   ├── rules.py          #   Rule, Hook, Op, Expr, ...
│   │   │   └── events.py         #   Event, CheckRequested, ...
│   │   └── expr.py               # Expr 表达式求值器
│   │
│   ├── engine/                   # 确定性引擎（无 LLM 依赖）
│   │   ├── check_resolver.py     # D100 检定
│   │   ├── san_manager.py        # SAN 计算（6 种形态）
│   │   ├── combat_pipeline.py    # 战斗流水线（12 hooks）
│   │   ├── rule_evaluator.py     # Rule 三元组求值
│   │   ├── state_manager.py      # 状态管理（op 校验 + 不变式）
│   │   ├── event_logger.py       # 事件溯源写入
│   │   ├── win_condition.py      # 结局判断
│   │   └── view_projector.py     # 信息隔离投影
│   │
│   ├── agents/                   # Agent 定义（PydanticAI）
│   │   ├── planner.py            # 主持 Agent: 意图 → ActionPlan
│   │   ├── narrator.py           # 主持 Agent: Outcome → 叙事
│   │   ├── module_parser.py      # 离线: PDF → ModuleDraft
│   │   ├── module_reviewer.py    # 离线: Draft → ReviewReport
│   │   └── prompts/              # System prompts（单独管理，便于迭代）
│   │       ├── planner.md
│   │       ├── narrator.md
│   │       ├── module_parser.md
│   │       └── module_reviewer.md
│   │
│   ├── runtime/                  # 运行时编排
│   │   ├── game_loop.py          # 主回合循环
│   │   ├── context_builder.py    # 上下文组装（信息隔离）
│   │   ├── session_manager.py    # 房间/会话管理
│   │   └── pending_check.py      # 玩家检定交互处理
│   │
│   ├── transport/                # 传输层
│   │   ├── ws_handler.py         # WebSocket 实时通信
│   │   ├── rest_rooms.py         # REST: 房间管理
│   │   └── rest_modules.py       # REST: 模组列表/导入
│   │
│   ├── data/                     # 数据访问层
│   │   ├── repo_scene.py
│   │   ├── repo_entity.py
│   │   ├── repo_character.py
│   │   ├── repo_event.py
│   │   └── ...
│   │
│   └── db/                       # 数据库
│       ├── migrations/
│       └── models.py             # SQLAlchemy / SQLModel
│
├── fixtures/                     # 测试数据
│   ├── demo-module.json          # 书房 Demo
│   └── demo-cases.json           # 测试输入-预期输出对
│
├── tests/
│   ├── test_engine/              # 引擎单元测试（无 LLM）
│   ├── test_agents/              # Agent 评测
│   └── test_integration/         # 端到端集成测试
│
├── pyproject.toml
└── docker-compose.yml            # PG + App（MVP 不需要 Redis）
```

### 4.11 依赖清单（MVP）

```toml
[project]
name = "arkham-case-files"
requires-python = ">=3.12"
dependencies = [
    # ──── 全栈共享 ────
    "pydantic>=2.0",             # 数据校验（所有 Pydantic Model 的基础）

    # ──── Agent 层（两个 Agent 系统共用 PydanticAI）────
    "pydantic-ai>=0.0.20",       # Agent SDK
                                  # Runtime: Planner + Narrator 的结构化输出
                                  # Module:  Parser + Reviewer 的结构化输出

    # ──── Runtime 传输层 ────
    "fastapi>=0.115.0",          # Web 框架
    "uvicorn[standard]",          # ASGI 服务器
    "websockets",                 # WebSocket（玩家实时通信）

    # ──── 数据层 ────
    "sqlalchemy[asyncio]>=2.0",  # ORM
    "asyncpg",                    # PostgreSQL 异步驱动

    # ──── Module Parser 预处理 ────
    "pymupdf>=1.24.0",           # PDF → Markdown

    # ──── 通用工具 ────
    "httpx",                      # HTTP 客户端
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio",
    "pytest-cov",
    "ruff>=0.5.0",
    "mypy>=1.0",
]
```

**注意：MVP 依赖中故意没有 Redis、LangChain、LangGraph、CrewAI、AutoGen。**

- **Redis**：MVP 无 pending_check（`roll_mode: "auto"`），单房间单 PG 实例足够。等需要 TTL 自动超时取消挂起检定时再引入。
- **LangGraph**：Runtime 的 Game Loop MVP 版是 20 行 async function + 1 个 if。Module Parser 是线性流水线。当编排复杂度确实需要时再引入。
- **LangChain / CrewAI / AutoGen**：方向性不匹配，永久排除。

**注意：两个 Agent 系统共享同一个 `pydantic-ai` 依赖。** Parser Agent、Reviewer Agent、Planner Agent、Narrator Agent——四个 Agent 都是 PydanticAI 的 `Agent` 实例。它们只是 `model`、`result_type`、`system_prompt` 和 `tools` 不同。

### 4.12 两 Agent 系统的框架选择总结

| 组件 | 框架 | 理由 |
|------|------|------|
| **Parser Agent** | PydanticAI | 大上下文结构化提取。`result_type=ModuleDraft`。 |
| **Reviewer Agent** | PydanticAI | 结构化审查报告。`result_type=ReviewReport`。 |
| **模块导入编排流水线** | 纯 Python async function | 线性流水线，无分支。不需要 graph 框架。 |
| **确定性校验（Schema/引用/符号表）** | 纯 Python + Pydantic | 无 LLM 参与。纯代码。 |
| **Planner Agent** | PydanticAI | 意图识别 + 结构化 ActionPlan。`result_type=ActionPlan`。 |
| **Narrator Agent** | PydanticAI | 引擎结果 → 结构化叙事。`result_type=Narration`。 |
| **Runtime Game Loop** | 纯 Python async function（MVP）→ LangGraph（中期可选） | MVP 线性流水线 + 1 个 if，不需要 graph。 |
| **Game Engine** | 纯 Python | 确定性代码。无 LLM。无框架。 |

```text
整个系统的框架依赖只有一句话：

  所有需要 LLM 的地方 → PydanticAI Agent
  所有不需要 LLM 的地方 → 纯 Python 代码

  一个框架，四个 Agent 实例，零冗余依赖。
```

---

## 五、总结

### 5.1 核心决策

| 决策 | 选择 | 核心理由 |
|------|------|---------|
| **全栈 Agent 框架** | **PydanticAI** | 四个 Agent（Parser、Reviewer、Planner、Narrator）都是 PydanticAI 实例。一个框架覆盖两个 Agent 系统的全部 LLM 调用点。 |
| **Module Parser 编排** | **纯 Python 线性流水线** | 预处理→Parser→后处理→Reviewer→人工审批。无分支，不需要 graph。 |
| **Runtime 编排（MVP）** | **自定义 Game Loop** | 回合循环是 20 行 async function + 1 个 if。 |
| **Runtime 编排（中期）** | **PydanticAI + LangGraph** | 当分支复杂度超过阈值（战斗子循环、并行检定、Human-in-the-Loop）时引入。 |
| 不用的框架 | LangChain, CrewAI, AutoGen, Mastra, OpenAI Agents SDK | 方向性不匹配、技术栈不匹配、供应商锁定。 |
| 模型策略 | **不锁定供应商** | PydanticAI 支持多模型提供商。Parser 用 Opus、Planner 用 Sonnet、Narrator 用 Haiku——各取所需。 |
| 信息隔离 | **ContextAssembler（纯代码）** | 不依赖 LLM "自觉"不泄露——架构层面保证。 |

### 5.2 一个框架，四个 Agent，两个系统

```text
┌─────────────────────────────────────────────────────────┐
│                   PydanticAI（唯一 Agent 框架）           │
│                                                          │
│  Module Parser 系统（离线）        Runtime Keeper 系统（在线）│
│  ┌──────────────────────┐       ┌──────────────────────┐ │
│  │ Parser Agent         │       │ Planner Agent        │ │
│  │ model: Opus          │       │ model: Sonnet        │ │
│  │ result_type:         │       │ result_type:         │ │
│  │   ModuleDraft        │       │   ActionPlan         │ │
│  ├──────────────────────┤       ├──────────────────────┤ │
│  │ Reviewer Agent       │       │ Narrator Agent       │ │
│  │ model: Sonnet        │       │ model: Haiku         │ │
│  │ result_type:         │       │ result_type:         │ │
│  │   ReviewReport       │       │   Narration          │ │
│  └──────────────────────┘       └──────────────────────┘ │
│                                                          │
│  共享：同一套 Pydantic Model 类型系统                      │
│  ModuleContent, ActionPlan, ConfirmedOutcome, Event...   │
└─────────────────────────────────────────────────────────┘
                              │
                              │ 结构化 JSON
                              ▼
┌─────────────────────────────────────────────────────────┐
│              确定性 Game Engine（无框架，纯 Python）       │
│                                                          │
│  CheckResolver · RuleEvaluator · StateManager           │
│  EventLogger · SANManager · CombatPipeline              │
│  WinConditionEvaluator · ViewProjector                  │
└─────────────────────────────────────────────────────────┘
```

### 5.3 架构哲学

```text
这个系统的成功不在于 LLM 有多聪明，而在于：

1. LLM 不能做什么（不能直接改状态、不能看到 secrets、不能改写骰子结果）
2. 引擎必须做什么（每次检定可审计、每次状态变更可追溯、每个结局可验证）
3. 信息隔离是否严密（secrets 绝对不进入 LLM 上下文，由代码层保证，不由 prompt 保证）
4. 类型的边界就是系统的边界（Pydantic Model 定义了什么是对的，引擎负责只有对的能发生）

好的架构不是让 LLM 更强大，而是让 LLM 的失败不会摧毁系统。
```

### 5.4 MVP 第一周任务（对齐团队计划）

按照 `agent-implementation-team-plan.md` 的开发顺序，MVP 先跑通 Runtime 闭环（人工 Demo 模组 + 假引擎），Module Parser 后期再做：

```
Day 1: 项目骨架 + 核心 Schema
  · pyproject.toml + FastAPI + PG
  · core/models/ 定义三个核心协议:
    ModuleContent, ActionPlan, ConfirmedOutcome
  · （三人共同确定——这是第 1 步的交付物）

Day 2: 假引擎 + 人工 Demo 模组
  · 成员 B: engine.execute() 固定返回结果
  · 成员 C: demo-module.json（书房场景，人工编写）
  · （不需要任何 Agent 框架）

Day 3: Runtime Game Loop + Planner + Narrator
  · 成员 A: PydanticAI Planner（result_type=ActionPlan）
  · 成员 A: PydanticAI Narrator（result_type=Narration）
  · 成员 A: ContextAssembler + GameLoop.process_turn()
  · 首次跑通: 玩家输入 → 假引擎 → AI 回复

Day 4: 替换真实引擎模块
  · 成员 B: CheckResolver（d100）+ StateManager + EventLogger
  · 成员 A: 接入真实引擎，验证 ConfirmedOutcome

Day 5: 集成测试 + Demo 演示
  · 10+ 条测试输入验证（自由叙事 + 检定成功 + 检定失败 + 非法操作）
  · 验证: 引擎失败时 Agent 不会叙述为成功
  · 演示: 书房 Demo 端到端

---
Phase 2（Runtime 稳定后）:
  成员 C 开始 Module Parser Agent 开发
  · Parser Agent（PydanticAI, result_type=ModuleDraft）
  · Reviewer Agent（PydanticAI, result_type=ReviewReport）
  · 确定性校验流水线
  · 目标: 自动生成的 ModuleContent 与人工 demo-module.json 结构一致
```

---

*本文档基于对 8 个 Agent 框架的 14 维度分析，对齐 `agent-implementation-team-plan.md` 的两 Agent + 一引擎架构，结合项目的数据模型设计、A/B/C/D 四类引擎介入机制、事件溯源架构和 1-3 人团队约束。核心结论：全栈统一使用 PydanticAI 作为唯一的 Agent 框架——四个 Agent（Parser、Reviewer、Planner、Narrator）都是 PydanticAI 实例。MVP 不需要任何编排框架。中期仅在 Runtime 侧按需引入 LangGraph。*

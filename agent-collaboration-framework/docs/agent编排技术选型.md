# 主持编排 Agent 技术选型补充：三层实现、工作流模式与玩家接口

> 状态：proposal / 技术选型补充
> 日期：2026-07-20
> 关联：[Issue #86](https://github.com/1024XEngineer/TRPG-master/issues/86)
> 适用范围：`agent-collaboration-framework` 中成员 A 的主持编排；不改变 B 的确定性规则权威和 A/B/C 公共契约。

## 1. 本文结论

Issue #86 的 MVP 决策仍然有效：当前主持回合是固定线性流程，继续采用普通 Python 显式 `async` 编排，并先建立框架无关、安全的流事件协议。

本次补充不是把“普通 Python 或 LangGraph”改成二选一，而是明确 Agent 实现有三个细度层次：

| 层次 | 实现方式 | 适合的问题 | 主要代价 |
| --- | --- | --- | --- |
| 1. 供应商 Agent Runtime | OpenAI Agents SDK、Anthropic SDK tool runner / Managed Agents 等 | 单一供应商、少量工具、希望快速验证多轮工具循环 | 供应商耦合、运行与追踪数据边界、抽象可控性 |
| 2. 显式 Python 编排 | 模型 SDK + `async` + 自己维护消息、工具与循环 | 固定、线性或很小的流程；需要完全掌握协议与安全边界 | Schema、工具回填、循环、重试、状态和可观测性需要自己实现 |
| 3. 图工作流 Runtime | LangGraph `StateGraph`、`ToolNode`、子图与 reducer | 条件路由、循环、多工具、多 Agent、fan-out/fan-in、checkpoint 或 interrupt | 更重依赖、状态模型和图语义的学习与升级成本 |

**选型的首要依据不是“能否流式输出”，而是工具调用复杂度和工作流拓扑：是否需要工具、是否会多轮调用工具、是否存在动态路由/并行/恢复。** 三层都能流式输出；任何一层都不能绕过本项目的事实校验和玩家可见性边界。

## 2. 三层实现模型

### 2.1 层 1：供应商提供的 Agent Runtime

这一层的目标是最少的 Agent 样板代码。以 OpenAI 为例，`openai-agents`（不是仅调用 Chat Completions 的基础 `openai` 客户端）提供 Agent、工具、handoff、guardrail、session、流式事件和 tracing；Runner 会自动执行“模型请求工具 → 执行工具 → 回填工具结果 → 再次调用模型”的循环。[OpenAI Agents SDK](https://openai.github.io/openai-agents-python/)

Anthropic Python SDK 也提供 `@beta_tool` 和 `beta.messages.tool_runner`：它会运行工具、处理请求/响应循环、管理对话状态、包装错误和类型校验；该 API 仍标记为 beta。[Claude Tool Runner](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-runner)

概念上可以写成：

```python
agent = Agent(
    name="host",
    instructions=HOST_PROMPT,
    tools=[look_up_rule, roll_check],
)

result = await Runner.run(agent, player_message)
```

适合：

- 只想快速验证“模型是否会选对工具”；
- 工具数量少、流程是标准 ReAct 循环；
- 使用单一供应商模型；
- 不需要复杂的自定义状态图。

限制与约束：

1. 当前实验用的是 Qwen 的 OpenAI 兼容 Chat Completions 接口；“接口兼容”不等于它可无修改接入 OpenAI Agents SDK 默认的 Responses API / provider 配置。接入前必须做模型适配、工具调用、流事件和错误行为的真实验证。
2. OpenAI Agents SDK 的 tracing 默认开启；接入前必须确认 trace 中是否含玩家输入、工具参数、模型输出和游戏秘密，并显式配置敏感数据策略。[OpenAI Agents SDK Tracing](https://openai.github.io/openai-agents-python/tracing/)
3. Anthropic 的 tool runner / Managed Agents 和 OpenAI 的 Agent Runtime 都有供应商特定的模型、托管工具、会话和数据边界；它们不应成为 A/B/C 公共协议。
4. 该层可以减少循环代码，但不能取代规则引擎、权限校验、事实验证或玩家可见性投影。

### 2.2 层 2：普通 Python + 直接模型 SDK

普通 Python 路线不是“没有 Agent”，而是主动拥有 Agent runtime：

```text
模型请求工具
  → 组装工具参数
  → 执行本地工具
  → 追加 tool message
  → 再次调用模型
  → 无工具调用时结束
```

它适合当前 MVP：`PlayerView → Intent → ActionExecutor.execute() → Narration` 是固定主链，且本项目需要在模型输出进入玩家可见层前执行 Schema 与 `claimed_fact_ids` 校验。

普通 Python 在以下条件下仍是最小、最清晰的选择：

- 不调用工具，或只有一两个固定工具；
- 工具调用轮数有限，且不需要动态工作流；
- 不需要暂停恢复、跨进程 checkpoint、图级可视化；
- 业务安全门必须显式、逐行可审计；
- 团队正在学习模型工具调用的底层协议。

本仓库的 [`experiments/plain-python-tool-agent`](../experiments/plain-python-tool-agent/) 展示了显式流式工具参数拼接、工具注册、错误回填和最大轮数保护。它是理解和回归测试协议的基线，不要求未来生产实现永远停留在这一层。

### 2.3 层 3：LangGraph 图工作流

当“模型—工具—模型”不再是唯一拓扑，而变成分支、循环、并行和多个上下文隔离的 Agent 时，LangGraph 的价值来自工作流 runtime，而非简单的 token 流。

LangGraph 节点仍然可以是普通 Python 函数或 LLM 调用；边定义顺序和条件路由；状态 schema 与 reducer 定义并发结果如何合并。它原生支持条件边、并行 super-step、`Send` 动态 fan-out、`ToolNode`、子图、checkpoint 与 interrupt。[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)

适合迁移到 LangGraph 的触发条件：

- 主 Agent 的工具调用需要在执行前由另一个审核 Agent 审核；
- 一个任务会多轮选择、执行、拒绝或重试不同工具；
- 需要 fan-out/fan-in 或动态数量的 Worker；
- 多 Agent 有不同私有上下文、权限或持久化策略；
- 需要 checkpoint、长任务恢复、人工审批、节点级状态观察；
- 手写的状态机、并发、恢复和事件排序成本开始超过框架成本。

[`experiments/langgraph-tool-agent`](../experiments/langgraph-tool-agent/) 使用 LangChain 当前推荐的 `create_agent`，展示标准工具循环。对于需要在工具执行前插入审核节点或实现 fan-out/fan-in 的工作流，应从 `create_agent` 下沉到 `StateGraph + ToolNode`，而不是把完整的标准 Agent 循环当成不可打断的黑盒。

## 3. 以“工具与拓扑”而不是框架偏好做选择

| 问题 | 推荐起点 | 原因 |
| --- | --- | --- |
| 没有工具，只需一次结构化 LLM 输出 | 直接模型 SDK | 不需要 Agent loop |
| 一个供应商、少量工具、标准多轮 ReAct | 供应商 Agent Runtime | 快速得到工具循环、stream、trace 和基础 guardrail |
| 固定线性主链、强业务安全门、Qwen 兼容接口 | 显式 Python | 完全控制消息、验证和失败语义 |
| 多轮工具选择、工具拒绝/重试、动态可用工具 | LangGraph | 条件路由、ToolNode、state 与 middleware 更可维护 |
| 审核 Agent、研究 Worker、聚合 Agent 并行协作 | LangGraph | 子图、`Send`、reducer 和 checkpoint 降低编排复杂度 |
| 需要长期会话、暂停、恢复、人工批准 | LangGraph 或经验证的供应商 Runtime | 不能只靠简单 `asyncio.gather()` 补齐运行时语义 |

这不是单向升级链：同一个系统可以同时使用三层。

```text
普通 Python：规则校验、数据转换、工具业务函数、外部事件协议
    ↓
供应商 Runtime：某个独立、短生命周期的标准 Agent
    ↓
LangGraph：跨 Agent 的路由、并发、恢复与工作流状态
```

关键原则是：**框架只拥有内部编排状态；`PlayerInput`、`PlayerView`、`Intent`、`ActionRequest`、`ActionResult`、`TurnOutput` 和玩家可见事件仍是稳定业务边界。**

## 4. ReAct：一个 Agent 内的工具闭环，而非“公开思维过程”

ReAct 可以理解为 Agent 在解决任务时反复进行：

```text
依据当前上下文选择动作（Action）
    → 调用工具
    → 获得观察结果（Observation）
    → 根据新结果决定下一步
```

对于主持编排，典型的 Action 不是直接写游戏状态，而是：

- 读取经脱敏的 `PlayerView`；
- 提议一个 `Intent`；
- 读取可信 Checkpoint 候选；
- 调用唯一权威入口 `ActionExecutor.execute()`；
- 读取执行后的玩家可见事实；
- 生成受事实约束的叙事。

这里有两个不可破坏的边界：

1. Agent 的工具调用只是**提议**；B 的确定性引擎才拥有规则、骰子、状态和 Event 权威。
2. ReAct 的内部推理或原始模型 token 不是玩家可见事件。玩家只能看到经过安全投影的阶段状态、工具执行进度和通过 Pydantic / 事实校验的最终结果。

因此，流式协议应继续采用语义事件，如 `turn.phase_changed`、`tool.started`、`tool.completed`、`turn.completed`，而不是暴露原始 reasoning 内容。

## 5. 审核 ReAct Agent：何时从标准 Agent 下沉到图

若需求是“主 Agent 产生 tool call 后、工具真正执行前，交给第二个 LLM 审核”，结构应是：

```mermaid
flowchart LR
    INPUT["PlayerInput"] --> MODEL["主模型：产生 ToolCall 提议"]
    MODEL --> HAS_TOOL{"有工具调用？"}
    HAS_TOOL -->|"否"| OUTPUT["校验后的 TurnOutput"]
    HAS_TOOL -->|"是"| POLICY["确定性权限/Schema/预算门"]
    POLICY --> REVIEW["审核 Agent"]
    REVIEW --> APPROVED{"批准？"}
    APPROVED -->|"是"| TOOL["ToolNode / ActionExecutor"]
    TOOL --> MODEL
    APPROVED -->|"否"| FEEDBACK["将拒绝原因作为 ToolMessage"]
    FEEDBACK --> MODEL
```

审核 Agent 可以判断语义合理性，例如“此时搜索是否必要”“查询是否过宽”；但不能成为唯一安全门。工具白名单、用户权限、参数 schema、速率/费用限制、`ActionExecutor` 唯一入口和玩家可见性必须在确定性代码中校验。

这类流程可以手写，但必须自行处理：未执行的 tool call 如何回填、拒绝后如何让主模型重试、最大审核轮数、并发工具、错误分支、事件排序和恢复。达到此复杂度时，`StateGraph` 的条件边、`ToolNode` 和 node-level retry 会比手写循环更合适。

## 6. fan-out / fan-in 与 multi-agent

### 6.1 固定并行

例如一个玩家问题同时触发三种独立分析：规则核对、玩家可见事实核对、叙事风格草案：

```mermaid
flowchart LR
    P["Planner / Router"] --> R["规则 Worker"]
    P --> V["PlayerView Worker"]
    P --> N["叙事 Worker"]
    R --> S["Synthesizer"]
    V --> S
    N --> S
```

这是固定 fan-out/fan-in。普通 Python 可以用 `asyncio.gather()` 手写；LangGraph 通过多个并行边与 reducer 聚合状态。并行并不自动意味着安全：每个 Worker 仍必须只接收其被授权的上下文。

### 6.2 动态 Worker

如果 Planner 先拆出未知数量的子任务，例如根据玩家行动生成若干可核对的线索或检索任务，再为每个子任务创建 Worker，则是动态 fan-out。LangGraph 的 `Send` API 专为 map-reduce / orchestrator-worker 模式设计：每个 Worker 获得自己的输入，输出写入带 reducer 的共享结果，再由聚合节点生成最终答案。[LangGraph Workflows and Agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)

### 6.3 何时才值得拆成多个 Agent

不要为了“多 Agent”而机械拆分。一个职责值得成为独立 Agent，通常至少满足一项：

- 需要不同的上下文可见范围；
- 需要不同模型、提示词、温度或评测标准；
- 需要独立的工具权限；
- 能并行带来确定的延迟收益；
- 有独立失败模式、重试策略或长期状态；
- 输出可以被明确的强类型契约消费。

否则它更适合保留为同一 Agent 内的普通函数或提示词步骤。子图应按上下文和权限隔离，而不是按“听起来像一个角色”的名称拆分；LangGraph 子图可作为父图节点，并支持不同的 state schema 与持久化策略。[LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)

## 7. “万物皆可 Agent”：玩家行为如何指导接口梳理

“玩家是一个 Agent”应理解为一种接口设计视角，而不是把真人玩家误当成可直接执行内部工具的 LLM：玩家、测试脚本、未来 AI 玩家都可以是同一个游戏交互协议的调用方。

玩家在游戏中的每一种可见意图都可被建模为一个受限动作（概念上的 tool call）：

| 玩家要做什么 | 需要的可见信息 | 对应稳定接口 / 契约 | 权威结果 |
| --- | --- | --- | --- |
| 看周围、查看线索 | 当前可见场景、目标、线索 | `PlayerViewSource.read()` → `PlayerView` | 仅玩家可见投影 |
| 宣告行动 | 可选目标、技能、Checkpoint | `PlayerInput` → `Intent` | 仅提议，尚未改变状态 |
| 检定、交互、对话、移动、使用物品 | 已校验的意图与可信候选 | `ActionExecutor.execute(ActionRequest)` | `ActionResult`、权威 Event / StateChange（内部） |
| 知道发生了什么 | 执行后可见事实 | `TurnOutput` / 玩家可见 WebSocket 事件 | 已校验叙事和安全状态 |

所以梳理“玩家玩一回合时需要查询什么、能提出什么动作、动作后期待什么反馈”，就是梳理系统需要提供的查询、命令和事件接口。

这带来四个实现要求：

1. 人类玩家与未来 AI 玩家都只通过 `PlayerInput` 等公开命令边界进入系统，不能直接调用内部 `ActionExecutor` 或读取 `GameState`。
2. 模型产生的 `Intent` 与玩家 UI 选择的动作一样，都必须通过可信候选和确定性引擎校验。
3. 工具以玩家能力（看、问、行动、等待结果）建模，而不是以数据库表或内部对象直接暴露。
4. 每个动作都应有明确的输入 schema、权限、幂等语义、超时/失败语义和玩家可见输出；这使真人、Bot、自动化测试和未来多 Agent 都能复用同一协议。

## 8. 对当前 MVP 的行动项

本补充不修改 Issue #86 的近期实施范围。当前应继续：

1. 用普通 Python 实现 `Orchestrator.astream()` 与安全 `TurnEvent`；
2. 保持 `run()` 和 `astream()` 共用一条业务主链；
3. 将模型 SDK、供应商 Agent Runtime、LangGraph state 都留在成员 A 的内部 adapter / application 范围；
4. 保持 `ActionExecutor.execute()` 的唯一权威执行语义；
5. 先为玩家动作、玩家可见查询和安全事件建立清晰的接口清单；
6. 持续记录工具调用轮数、失败率、耗时、上下文大小和人工介入次数，作为未来升级的证据。

重新评估顺序建议如下：

```text
无工具 / 单次输出
    → 直接模型 SDK

少量标准工具、单一供应商
    → 验证供应商 Agent Runtime

固定安全主链、需精确控制 Qwen 兼容协议
    → 普通 Python

审核循环、动态工具、多 Agent、fan-out/fan-in、恢复
    → LangGraph StateGraph
```

## 9. 与已有实验的关系

本仓库已有两套隔离、业务无关的学习实验：

- [`plain-python-tool-agent`](../experiments/plain-python-tool-agent/)：展示手写流式工具调用循环；
- [`langgraph-tool-agent`](../experiments/langgraph-tool-agent/)：展示 `create_agent`、`@tool` 和 LangGraph 运行时；
- [`COMPLEXITY_REPORT.md`](../experiments/agent-orchestration-evaluation/COMPLEXITY_REPORT.md)：记录相同通用工具、真实 Qwen 调用、代码量、依赖和扩展成本对比。

实验结论仍为：两条路线都能流式输出；普通 Python 的纯编排开销更低；LangGraph 对工具 schema、循环和多 Agent 扩展显著减少本地样板代码。加入供应商 Agent Runtime 后，团队有了一个更轻的第一层试验选项，但其模型/服务耦合与数据边界需要单独评估。

## 10. 本期不做

- 不把 OpenAI、Anthropic、LangGraph 或任何真实模型 SDK 加入生产依赖；
- 不将 Qwen OpenAI 兼容接口直接假定为 OpenAI Agents SDK 兼容；
- 不把玩家、模型或 Agent 赋予绕过 `ActionExecutor` 的状态写权限；
- 不向玩家流式发送模型的原始 reasoning、未验证 token 或内部 ToolMessage；
- 不因“万物皆可 Agent”而把所有普通函数拆成 Agent；
- 不因本文件立即改变 Issue #86 的 MVP 普通 Python 决策。

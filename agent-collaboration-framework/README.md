# Agent 协作框架

核心代码按架构职责组织，不按当前成员编号组织。成员是可变化的维护者，目录和模块名
则应持续表达系统边界，避免人员调整后出现 `member_a.py` 名称与实际职责不一致。

本框架采用以下技术与职责边界：

```text
Pydantic v2        JSON 契约、步骤数据校验、LLM 结构化输出
Python 异步函数     单回合流程编排与条件分支
PydanticAI         运行时主持 Agent 的可选 LLM 实现
确定性规则引擎      游戏事实、Event 和事务的唯一执行权威
```

不连接数据库。`FakeAtomicEngine` 只在内存中模拟权威状态，方便各组件并行开发。

## 代码结构

```text
collaboration_framework/
├── agents/                 # 使用模型或确定性替身完成理解与叙事
│   └── runtime_host.py     # 运行时主持 Agent
├── engine/
│   └── atomic.py           # Context 组装与原子规则执行边界
├── modules/
│   └── validation.py       # 模组导入、校验与发布边界
├── contracts.py            # 跨组件 Pydantic 数据契约
├── ports.py                # 框架无关的组件接口
├── routing.py              # 模型路由提议的确定性硬化
└── workflow.py             # Python 异步函数单回合编排
```

`agents/` 只放真正承担 Agent 行为的实现；确定性引擎不为了对应某位成员而被命名成
Agent。`engine/` 和 `modules/` 分别保留规则执行、模组处理的独立演进空间。

## 单回合流程

```text
run_turn -> _assemble_context -> _interpret + harden_intent_routing
                                                  |-- 不明确 ----------> _clarify -> return
                                                  |-- execution=narrative -> _narrate -> _prepare_summary_outbox -> return
                                                  `-- execution=engine ---> _execute_engine
                                                                              |
                                                                              `-> _refresh_context -> _narrate -> _prepare_summary_outbox -> return
```

`Intent.execution` 和 `Intent.check` 都是解释器提议。`_interpret` 使用可信
`TurnContext` 调用 `harden_intent_routing()`：只有列入目标 `narrative_actions` 的动作
可以保留 `execution=narrative`，其他已匹配动作默认硬化为 `execution=engine`。
硬化后的 `execution` 决定是否进入引擎；`check.route=none/module/default` 只决定引擎内
是否检定以及检定来源。因此 `execution=engine + check.route=none` 是合法的确定性动作，
不能因为“不检定”而绕过规则边界。

`run_turn()` 通过普通异步 Python 函数依次推进步骤，每次只处理一个玩家输入，结束后
丢弃 `TurnState`。`TurnState` 只含 `PlayerInput / Context / Intent / ActionResult /
Narration` 等过程数据，不含 `GameState`。

## 三条硬约束

1. **引擎是一个步骤、一个调用。** `_execute_engine` 只调用一次
   `await engine.execute_action(request)`。生产实现必须在该调用内部完成权限、幂等、
   规则检定、append Event、更新物化视图和事务提交。Python 工作流只编排步骤，不编排事务。
   事务返回后，`_refresh_context` 只重新读取已提交的玩家可见投影，不参与规则执行或状态写入。
   同一 `client_action_id` 重放时返回完全相同的 `ActionResult`（含原 Event 引用），
   但不重复执行规则、追加 Event 或修改状态。
2. **MVP 不使用图运行时或流程持久化。** EventLog 与物化视图仍是游戏事实的唯一权威，
   普通 Python 工作流不持有可恢复的持久游戏状态。
3. **第二阶段先评审 pending_check。** MVP 的引擎调用只返回 `ActionResult`，不实现流程
   挂起与恢复；需要手动掷骰时，先将骰值作为下一回合输入。

## 输出与 Summary outbox 边界

`run_turn()` 返回的 `TurnOutput` 是宿主内部结果，含可信输入、Intent、ActionResult 和
outbox 命令，禁止直接发送给玩家。当前玩家侧投影只使用
`TurnOutput.to_player_output()` 返回的 `NarrationOutput`；后续可由 ViewProjector 另行
附加允许公开的视图。

`_prepare_summary_outbox` 只创建 `SummaryOperation`，不执行持久化。宿主在回合成功结束后
通过 `SummaryOutbox` 投递它；消费者只能按 `(room_id, client_action_id)` 幂等更新非权威
会话摘要，禁止写 `GameState` 或 `EventLog`。

## 框架隔离

[`contracts.py`](collaboration_framework/contracts.py)、
[`ports.py`](collaboration_framework/ports.py) 和
[`routing.py`](collaboration_framework/routing.py) 不依赖具体编排框架。五个公共 Protocol 是：

- `ContextAssembler.assemble_context()`
- `IntentInterpreter.interpret()`
- `AtomicActionEngine.execute_action()`
- `Narrator.narrate()`
- `SummaryOutbox.enqueue()`（由宿主在回合函数外消费）

[`workflow.py`](collaboration_framework/workflow.py) 使用普通 Python 函数封装这些接口与
确定性路由策略。替换编排方式时，各组件实现、路由策略和 JSON 契约不需要改变。

## 当前维护分工

下面的表只记录当前人员涉及的文件，不参与包结构或导入路径设计。人员职责变化时更新
本表，不重命名架构模块。

| 成员 | 主要涉及的文件 | 当前职责 |
| --- | --- | --- |
| A | `collaboration_framework/agents/runtime_host.py`、`collaboration_framework/workflow.py` | Intent、Narration 与回合编排；不得写状态、Event 或决定骰值 |
| B | `collaboration_framework/engine/atomic.py` | Context、原子规则引擎、幂等与未来数据库事务 |
| C | `collaboration_framework/modules/validation.py`、`fixtures/` | ModuleContent 导入、来源/秘密/可达性审查、发布门与验收样例 |
| 共同 | `collaboration_framework/contracts.py`、`collaboration_framework/ports.py`、`collaboration_framework/routing.py`、`tests/` | 先改契约与公共路由策略，再同步 Schema、Fixture 和测试 |

## JSON 示例与运行

安装依赖：

```bash
uv sync
```

无网络运行一个 `module` 路由回合：

```bash
uv run agent-collab \
  --agent-mode fake \
  --module fixtures/demo-module.json \
  --state fixtures/demo-state.json \
  --input fixtures/demo-turn.json
```

澄清分支只需把输入替换为 `fixtures/clarification-turn.json`。正式模型模式使用
`--agent-mode pydantic-ai --model <provider:model>`，并设置相应 API Key。

生成 JSON Schema 与运行测试：

```bash
uv run agent-collab-export-schemas
uv run python -m unittest discover -s tests -v
```

`collaboration_framework/contracts.py` 中的 Pydantic `ModuleContent` 是当前模组输入的
唯一事实源；`schemas/module-content.schema.json` 由它生成，不应手改。文档示例和
`fixtures/demo-module.json` 都必须通过该模型校验。

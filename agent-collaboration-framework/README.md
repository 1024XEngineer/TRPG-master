# Agent 协作框架

核心代码按架构职责组织，不按当前成员编号组织。成员是可变化的维护者，目录和模块名
则应持续表达系统边界，避免人员调整后出现 `member_a.py` 名称与实际职责不一致。

本框架采用以下技术与职责边界：

```text
Pydantic v2        JSON 契约、节点数据校验、LLM 结构化输出
LangGraph          单回合流程编排与条件路由
PydanticAI         运行时主持 Agent 的可选 LLM 实现
确定性规则引擎     游戏事实、Event 和事务的唯一执行权威
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
└── workflow.py             # LangGraph 单回合编排
```

`agents/` 只放真正承担 Agent 行为的实现；确定性引擎不为了对应某位成员而被命名成
Agent。`engine/` 和 `modules/` 分别保留规则执行、模组处理的独立演进空间。

## 单回合流程

```text
assemble_context -> interpret
                       |-- 不明确 ----------> clarification -> END
                       |-- execution=narrative -> narrate -> prepare_summary_outbox -> END
                       `-- execution=engine ---> engine_node
                                                  |
                                                  `-> refresh_context -> narrate -> prepare_summary_outbox -> END
```

`Intent.execution` 只决定是否进入引擎；`Intent.check.route=none/module/default`
只决定引擎内是否检定以及检定来源。因此 `execution=engine + check.route=none`
是合法的确定性动作，不能因为“不检定”而绕过规则边界。

图通过 `compile()` 创建，**不传 checkpointer**。每次 `ainvoke()` 只处理一个玩家输入，
结束后丢弃 `TurnState`。`TurnState` 只含 `PlayerInput / Context / Intent /
ActionResult / Narration` 等过程数据，不含 `GameState`。

## 三条硬约束

1. **引擎是一个节点、一个调用。** `engine_node` 只调用一次
   `await engine.execute_action(request)`。生产实现必须在该调用内部完成权限、幂等、
   规则检定、append Event、更新物化视图和事务提交。LangGraph 编排步骤，不编排事务。
   事务返回后，`refresh_context` 只重新读取已提交的玩家可见投影，不参与规则执行或状态写入。
   同一 `client_action_id` 重放时返回完全相同的 `ActionResult`（含原 Event 引用），
   但不重复执行规则、追加 Event 或修改状态。
2. **MVP 不挂 checkpointer。** EventLog 与物化视图仍是游戏事实的唯一权威，图没有
   可恢复的持久游戏状态。
3. **第二阶段先评审 pending_check。** 若使用 `interrupt()`，checkpointer 只能保存
   “流程执行到哪里”的可丢弃缓存，不能保存任何游戏事实的唯一副本；否则将掷骰结果
   作为下一回合输入，不启用 interrupt。

## 输出与 Summary outbox 边界

`run_turn()` 返回的 `TurnOutput` 是宿主内部结果，含可信输入、Intent、ActionResult 和
outbox 命令，禁止直接发送给玩家。当前玩家侧投影只使用
`TurnOutput.to_player_output()` 返回的 `NarrationOutput`；后续可由 ViewProjector 另行
附加允许公开的视图。

`prepare_summary_outbox` 只创建 `SummaryOperation`，不执行持久化。宿主在回合成功结束后
通过 `SummaryOutbox` 投递它；消费者只能按 `(room_id, client_action_id)` 幂等更新非权威
会话摘要，禁止写 `GameState` 或 `EventLog`。

## 框架隔离

[`contracts.py`](collaboration_framework/contracts.py) 和
[`ports.py`](collaboration_framework/ports.py) 不导入 LangGraph。五个公共 Protocol 是：

- `ContextAssembler.assemble_context()`
- `IntentInterpreter.interpret()`
- `AtomicActionEngine.execute_action()`
- `Narrator.narrate()`
- `SummaryOutbox.enqueue()`（由宿主在图外消费）

[`workflow.py`](collaboration_framework/workflow.py) 只是这些接口的薄包装。替换编排器时，
各组件实现和 JSON 契约不需要改变。

## 当前维护分工

下面的表只记录当前人员涉及的文件，不参与包结构或导入路径设计。人员职责变化时更新
本表，不重命名架构模块。

| 成员 | 主要涉及的文件 | 当前职责 |
| --- | --- | --- |
| A | `collaboration_framework/agents/runtime_host.py`、`collaboration_framework/workflow.py` | Intent、Narration 与回合编排；不得写状态、Event 或决定骰值 |
| B | `collaboration_framework/engine/atomic.py` | Context、原子规则引擎、幂等与未来数据库事务 |
| C | `collaboration_framework/modules/validation.py`、`fixtures/` | ModuleContent 导入、来源/秘密/可达性审查、发布门与验收样例 |
| 共同 | `collaboration_framework/contracts.py`、`collaboration_framework/ports.py`、`tests/` | 先改契约，再同步 Schema、Fixture 和测试 |

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

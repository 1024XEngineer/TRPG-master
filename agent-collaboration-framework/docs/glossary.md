# 最小术语表

- **Contract**：`contracts.py` 中框架无关的 Pydantic Model，是 JSON 与结构化输出的事实源。
- **TurnState**：只在一次 LangGraph 调用中存在的过程状态，不是游戏事实仓库。
- **GameState**：成员 B/后端拥有的权威状态；当前仅由 Fake 在内存模拟。
- **ActionResult**：原子引擎调用完成后返回的已确认结果和 Event。
- **execution=narrative**：纯叙事分支，不进入规则引擎，且 `check.route` 必须为 `none`。
- **execution=engine**：进入唯一的 `engine_node`；`check.route` 可以是 `none/module/default`。
- **check.route**：只表达检定来源；`none` 表示不检定，不表示绕过引擎。
- **checkpointer**：LangGraph 流程持久化组件；MVP 禁用。
- **interrupt**：第二阶段候选能力；启用前必须完成权威边界评审。

# 最小术语表

- **Contract**：`contracts.py` 中框架无关的 Pydantic Model，是 JSON 与结构化输出的事实源。
- **TurnState**：只在一次 LangGraph 调用中存在的过程状态，不是游戏事实仓库。
- **GameState**：成员 B/后端拥有的权威状态；当前仅由 Fake 在内存模拟。
- **ActionResult**：原子引擎调用完成后返回的已确认结果和 Event。
- **route=none**：不改变权威状态，直接叙事。
- **route=module/default**：必须进入唯一的 `engine_node`。
- **checkpointer**：LangGraph 流程持久化组件；MVP 禁用。
- **interrupt**：第二阶段候选能力；启用前必须完成权威边界评审。

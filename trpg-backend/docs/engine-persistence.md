# 规则引擎持久化与房间运行时

Issue #89 建立数据库结构、ORM、迁移和内置发布数据；Issue #121 在不修改引擎
Protocol 和 RuleKernel 的前提下，实现 `SqlAlchemyEngineStore`、正式开局和房间
运行时生命周期。WebSocket `action.submit`、主持编排、SDK 与前端接入仍由后续
Issue 实现。

## 模组目录与发布内容

`scenarios` 是模组目录，保存身份、推荐版本和展示信息。`Scenario.id` 同时是规则
引擎的 `module_id`；`Scenario.version` 只表示当前推荐版本。

`module_versions` 以 `(module_id, version)` 为主键，保存通过当前
`ModuleContent.model_validate()` 的完整不可变发布 JSON。同一个 Scenario 可以有
多个发布版本。房间选择模组后使用 `rooms.scenario_id + rooms.module_version` 固定
到明确版本，不跟随目录推荐版本变化。

## 权威运行数据

- `game_sessions`：`room_id` 同时是主键和 Room 外键，因此一个 Room 只能运行一局；
  `state_json` 保存完整 `GameState`，`state_version` 保存当前 revision。
- `game_events`：按 `(room_id, sequence)` 保存规则引擎只追加的权威状态变化事件，
  并按 `(room_id, event_id)` 去重。
- `action_executions`：按 `(room_id, request_id)` 保存首次完整 `ActionRequest` 和
  `EngineExecutionResult`，供 Store 在服务重建后幂等重放。

领域 JSON 均使用 SQLAlchemy 通用 `JSON`。ModuleContent、GameState、Event、
ActionRequest 和 EngineExecutionResult 各自具有独立 schema version，首版为 `1`。

## SQLAlchemy Store

`SqlAlchemyEngineStore` 为每次规则引擎调用创建独立的异步数据库 Session，并在
一个事务内：

1. 加载并校验固定的 `ModuleContent`、`GameState` 和 revision；
2. 查询 `(room_id, request_id)` 对应的 CompletedAction；
3. 以 `WHERE state_version = expected_revision` 条件更新 GameSession；
4. 追加 GameEvent 并保存 ActionExecution；
5. 一并提交，任一步失败则全部回滚。

Store 只允许 `InGame` 房间提交新动作。`Suspended` 房间仍可读取投影和重放已经
完成的幂等请求，但新动作无法提交。规则结局把 GameState 和 Room 在同一事务中
分别更新为 `ended` 与 `Completed`。

## 开局与生命周期

选择模组时，Room 同时固定 `scenario_id` 和当前已发布的 `module_version`。正式
开局按稳定的 Player 加入顺序分配 `actor_1`、`actor_2` 等房间内 Actor ID，将
完成的 Character 内容、ID 和版本复制到独立 ActorState，并以模组第一个 Scene
和 Entity 初始状态创建唯一 GameSession。

```text
Lobby → Building → InGame ⇄ Suspended → Completed
                         └──────────────→ Completed
```

- 开局、GameSession 创建和 Room 进入 `InGame` 原子提交；
- 开局后 Character 冻结，修改、完成或重新掷骰均返回冲突；
- `Suspended` 只改变 Room，GameState 保持 `playing`；
- 恢复复用原 GameSession，不重建 Actor ID 或状态；
- 房主手动结束同时将 GameState 设为 `ended`，允许 `ending_id = null`；
- 已经 `Completed` 的房间不能恢复或重新开局。

## 两类 Event

`events` 与 `game_events` 不可互换：

| 表 | 用途 |
|---|---|
| `events` | WebSocket、叙事和回放流水；动作叙事可按关联键去重 |
| `game_events` | 规则引擎权威状态变化 |

旧 `events` 不参与 GameState 重建、不提供规则动作幂等，也不能替代
`game_events`。规则引擎的状态恢复只能读取 `game_sessions` 和 `game_events`。

`events.correlation_id` 是可空字符串。后续动作链路写入 `narration.push` 时使用
`clientActionId`，并由 `UNIQUE(room_id, event_type, correlation_id)` 保证同一房间、
同一事件类型和同一动作关联键至多落一条记录。历史事件及不关联动作的普通事件保持
`NULL`，数据库允许多条 `NULL`。该约束只提供持久化的“至多记录一次”闸门，不承诺
WebSocket exactly-once 投递；是否发送、重试时是否重发由后续 Issue 的业务流程决定。

## 迁移安全

迁移在执行任何 DDL 前检查：

- `characters` 是否存在重复 `(room_id, player_id)`；
- `room_sessions` 是否存在历史记录。

任一检查命中都会中止迁移并要求人工处理，不会静默删除、覆盖或合并业务数据。历史
Character 的 `version` 初始化为 `1`；历史 Room 的 `module_version` 和历史 Event 的
`correlation_id` 保持 `NULL`，无需回填。

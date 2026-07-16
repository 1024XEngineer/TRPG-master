# 文档归档索引

这里的文件都不是当前实现依据。日常开发请返回：

- [`../../README.md`](../../README.md)：项目入口和运行说明；
- [`../architecture.md`](../architecture.md)：唯一现行架构文档；
- [`../数据模型设计.md`](../数据模型设计.md)：唯一现行数据模型文档；
- [`../../schemas/`](../../schemas/)：由 Pydantic 自动生成的边界 Schema。

## `pre-consensus/`：三人统一之前的提案

| 文件 | 原用途 | 为什么归档 |
|---|---|---|
| `agent-architecture-design.md` | 早期总体 Agent 架构设计 | 包含已废弃的 `Intent.execution`、叙事旁路和旧端口 |
| `agent-implementation-team-plan.md` | 早期多人实施计划 | 部分任务拆分和公共契约已被最终共识替代 |
| `数据模型设计.md` | 早期完整后端数据模型提案 | 公共/内部边界已重新拆分；现行版本在 `docs/数据模型设计.md` |

这些文件只用于查看当时为什么产生争议，不能据此新增接口。

## `role-notes/`：按成员拆分的阶段性说明

| 文件 | 内容 | 当前状态 |
|---|---|---|
| `成员A-主持编排Agent流程架构.md` | A 的应用服务和 Gateway 说明 | 内容已合并进现行 `architecture.md`，停止单独维护 |
| `成员B-确定性规则引擎流程架构.md` | B 的执行边界说明 | 内容已合并进现行 `architecture.md`，停止单独维护 |
| `成员C-模组解析与审查Agent流程架构.md` | C 的发布边界说明 | 内容已合并进现行 `architecture.md`，停止单独维护 |
| `glossary.md` | 阶段性术语表 | 关键术语已经由 Pydantic Schema 和现行架构文档固定 |

这些文件保留是为了方便按成员回顾讨论，不应与现行文档同步更新。架构决议修改 `docs/architecture.md`；模型字段和不变式修改 `docs/数据模型设计.md`，并同步代码、测试和生成的 Schema。

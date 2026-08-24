# Issue #225 真实模型脱敏验收记录

- 日期：2026-08-04（Asia/Shanghai）
- 入口：`PromptHostTurnDecisionModel`，使用本地 `.env` 当前生产 provider 配置
- Provider / model：DeepSeek / `deepseek-chat`
- 安全约束：未记录 API key、原始模型输出、PlayerView、玩家身份或隐藏模组内容

| 脱敏用例 | 预期能力 | 结构化结果 | Schema 校验 |
| --- | --- | --- | --- |
| `single` | 一个当前场景观察目标 | `single_action`，1 个动作 | 通过 |
| `compound_two` | 观察后询问 | `action_plan`，2 步 | 通过 |
| `compound_four` | 四个顺序目标 | `action_plan`，4 步 | 通过 |

该 smoke 只证明当前生产模型能够稳定通过严格结构化边界，选择单动作或可变长度
`ActionPlan`。CI 使用 scripted/fake client，不依赖外部模型和 API key。

## Issue #246 脱敏验收（2026-08-06）

- Provider / model：DeepSeek / `deepseek-chat`
- 入口：`PromptHostTurnDecisionModel`，使用当前 `.env` provider 配置
- 执行方式：离线构造玩家安全 `PlayerView`，逐条提交自然语言输入；只记录
  `HostTurnDecision` 的 kind、步骤数和 Schema/策略错误分类
- 安全约束：未记录 API key、原始模型响应、隐藏上下文、PlayerView 内容或思维链；
  本次调用不进入 CI

| 用例类别 | 输入类别（脱敏） | 结构化结果 | 步骤数 | 结论 |
| --- | --- | --- | ---: | --- |
| `go_find` | `去 X 找 Y` | `single_action` | 1 | Schema 通过 |
| `ask_destination` | `到 X 问 Y` | `action_plan` | 2 | Schema 通过 |
| `enter_search` | `进入 X 搜索` | `single_action` | 1 | Schema 通过 |
| `synonym` | `前往/调查` 同义表达 | `single_action` | 1 | Schema 通过 |
| `omitted_subject` | 省略主语的地点行动 | `single_action` | 1 | Schema 通过 |
| `two_steps` | 两个连续动作 | `action_plan` | 4 | Schema 通过，模型将紧凑短语展开为 4 步 |
| `three_steps` | 三个连续动作 | `action_plan` | 4 | Schema 通过，模型将短语展开为 4 步 |
| `four_steps` | 四个连续动作 | `single_action` | 1 | Schema 通过，模型选择单动作解释 |
| `over_policy` | 超过当前策略上限的长串动作 | `action_plan` | 6 | Provider 输出通过 Schema；策略层随后按配置拒绝超限计划 |

本次真实模型记录验证了自然语言输入能够到达严格的单动作/ActionPlan 契约边界；
最终是否执行由 `ActionPlanPolicy` 再次校验，Engine 仍只接收单个
`ActionAdjudication`。步骤数不是产品固定值，当前默认技术上限为 32，可由策略配置调整。

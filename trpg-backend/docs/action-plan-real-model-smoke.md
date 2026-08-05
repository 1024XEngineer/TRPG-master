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

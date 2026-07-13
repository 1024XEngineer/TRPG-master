# GitHub 过程管理规范

用 GitHub 原生功能管理全部开发生命周期，无需外部工具。

## Milestone

每个 MS 一个 GitHub Milestone，含目标和关联 Issue。

## Issue

承载三种内容：
- 工程文档草案
- 任务拆分
- 设计澄清

Issue 必须有：背景、目标、验收标准。

## Pull Request

- 必须关联 Issue
- 合并条件：关联 Issue、已测试、作者可解释变更、已 Review（AI 检查 + 人工 Review）
- 小而频繁，避免大 PR

### Review

- 由助教和导师执行
- 鼓励同行 Review
- 设计草案可用不合并的 PR 做逐行评审

## Release

每个 Milestone 结束时创建 Tagged Release。

## Label 体系

| 维度 | 标签 |
|------|------|
| 产品设计 | `proposal` |
| 决策结果 | `Proposal-Accepted` / `Proposal-Denied` / `Proposal-NoPlan` |
| 规格粒度 | `FullSpec` / `MiniSpec` |
| 文档状态 | `Need-Document` / `Documented` |
| 类别 | `architecture` / `design` / `documentation` / `research` / `prototype` / `bug` / `enhancement` |
| 里程碑 | `ms1` / `ms2` / `ms3` / `ms4` |

## 典型生命周期

```
proposal → 讨论 → Proposal-Accepted + FullSpec/MiniSpec
→ 开发 → Need-Document → 文档 → Documented
```

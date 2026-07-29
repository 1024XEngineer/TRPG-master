# GitHub Engineering Workflow Reference

## Contents

1. Core rules
2. Issue standard
3. Bug Issue standard
4. Commit standard
5. Pull Request standard
6. Review and merge standard
7. Labels and milestones
8. Reusable templates

## 1. Core rules

- Follow `Proposal -> Design (Issue) -> Coding (PR) -> Review -> Merge`.
- Write all GitHub-facing text in Chinese, including Issue content and Markdown section headings, PR titles and content, Commit messages, review comments, and release or status notes. Keep technical identifiers and required GitHub keywords such as branch names, Conventional Commit types, `Closes #N`, and `Refs #N` in their conventional English form. Preserve repository-mandated formats and required sections. Use another language only when the user explicitly requests it for the current task.
- Design before coding. Do not start implementation without a clarified Issue.
- Route all code changes through an Issue-driven PR and human review. Do not directly modify the main repository branch.
- Prefer `Fork + PR` when the project uses that collaboration model: develop on a branch in the contributor's fork, keep it synchronized with upstream, and open a PR to the main repository.
- Keep each Issue, PR, and Commit focused on one bounded topic. Separate unrelated changes.
- Preserve engineering-document history. Once implementation begins, treat the agreed design as a read-only baseline; record later changes separately instead of overwriting history.
- Never fabricate Issue numbers, PR numbers, URLs, checks, approvals, or test results.

## 2. Issue standard

An Issue may hold a product or architecture draft, design clarification, defect, or implementation task.

The required-field list below applies to non-Bug Issues. For a Bug Issue, the lightweight rules in section 3 override this list.

Require:

- A concrete title describing a problem or outcome. Reject vague titles such as "optimize X" or "fix issues".
- Background: current behavior, user pain, and why the work matters now.
- Goal: the observable result to achieve.
- Scope: explicit included and excluded work.
- Design or implementation notes: affected modules, data structures, interfaces, compatibility, dependencies, alternatives, and risks. Mark genuinely irrelevant fields as not applicable.
- Verifiable acceptance criteria, preferably a checklist.
- A size that maps to one or a few reviewable PRs. Split larger work into sub-tasks.
- The relevant Milestone and labels when GitHub access permits.
- Team alignment before publishing a Proposal or externally visible decision.

For a substantial product Proposal, also require:

- Motivation and real user stories
- Target users
- Existing approaches and shortcomings
- Key decisions, alternatives, and rationale
- Core domain concepts and information structure
- Prototype or interactive demo for UI products
- Concrete examples defining normal, boundary, and invalid behavior

## 3. Bug Issue standard

Keep Bug reporting lightweight. Add only two Bug-specific mandatory rules:

1. **Complete reproduction process**: provide numbered steps starting from a known state. Include the actions, inputs, commands, or navigation needed for another person to reproduce the problem without relying on unstated context. Sanitize all example data.
2. **Private security reporting**: do not publish a suspected security vulnerability in a public Issue. Use the repository's private security-reporting process.

Environment details, prerequisites, expected and actual behavior, impact, frequency, logs, screenshots, cause analysis, repair targets, regression-test notes, and workarounds are optional. Include them only when they are known and materially help reproduction, diagnosis, or implementation. Do not delay filing a reproducible non-security Bug merely because optional information is unavailable.

For an intermittent problem, make the reproduction process describe the attempts made and the conditions under which the problem appeared. Never invent steps or claim that a problem was reproduced when it was not.

## 4. Commit standard

Make each Commit an understandable, reversible, atomic step serving the current Issue.

Use:

```text
<type>(<scope>): <summary> (#<issue>)
```

`scope` is optional. A real Issue number is mandatory.

Allowed types:

- `feat`: add user-visible functionality
- `fix`: correct a defect
- `docs`: change documentation only
- `test`: add or adjust tests
- `refactor`: restructure code without intended behavior change
- `perf`: improve performance
- `style`: change formatting without behavior change
- `build`: change build tooling or dependencies
- `ci`: change continuous integration
- `chore`: perform repository maintenance
- `revert`: revert an earlier Commit

Write a specific Chinese verb-object summary. Avoid empty descriptions such as “更新代码” or “修复问题”. Add a Chinese body when the reason, trade-off, migration, or compatibility effect is not obvious.

Examples:

```text
feat(auth): 支持手机号验证码登录 (#12)
fix(parser): 处理空输入导致的崩溃 (#27)
test(order): 补充订单取消场景测试 (#35)
docs(readme): 补充本地启动说明 (#41)
```

Before committing:

- Run relevant tests, checks, or builds.
- Inspect staged changes and exclude unrelated formatting or refactors.
- Exclude credentials, tokens, passwords, personal data, temporary files, and unintended generated artifacts.
- Ensure AI-generated code has necessary tests and is understood well enough to explain and maintain.

## 5. Pull Request standard

Use a focused title with the same semantic type style as the Commit title.

Require the PR description to contain:

- Linked Issue: `Closes #N` for complete resolution or `Refs #N` for partial work.
- Main changes.
- Why the chosen approach was used and important trade-offs.
- Tests and validation with actual results.
- Compatibility, migration, risks, and rollback plan.
- Screenshots or recordings for UI changes.
- A self-review checklist.
- For core modules developed with AI: a concise summary of key prompts and an explicit human-review statement.

Keep PRs small and frequent. Do not let them accumulate into changes too large to review. Move unrelated work to a separate Issue and PR.

Design-draft PRs are a special case: use them for line-by-line discussion, do not merge them, copy the approved result back to the Issue, and link the draft PR from the Issue. Real architecture skeleton code is not a design-draft PR and should be reviewed and merged normally.

## 6. Review and merge standard

Review for:

- Alignment with the Issue goal and agreed design
- Controlled scope and absence of unrelated changes
- Correctness, maintainability, duplication, and hidden risks
- Necessary tests and accurate documentation
- Security, privacy, compatibility, migration, and rollback concerns
- Whether the author can explain what changed and why

Require AI-assisted quality checks and at least one human review before merge. Resolve directional problems and obvious hazards. Never bypass required checks or branch protection. Prefer repository rulesets and CI checks as enforcement gates.

## 7. Labels and milestones

When applicable, use:

- `proposal`: product proposal
- `Proposal-Accepted`, `Proposal-Denied`, `Proposal-NoPlan`: decision state
- `FullSpec`, `MiniSpec`: specification size
- `Need-Document`, `Documented`: user-documentation state
- `sub-task`: implementation slice from a larger proposal

Attach all work for an iteration to its Milestone. State the iteration goal, use linked Issues to show progress, and summarize completed Issues at the end.

## 8. Reusable templates

### Engineering Issue

```markdown
## 背景

## 目标

## 范围

### 包含

-

### 不包含

-

## 设计与实现说明

## 验收标准

- [ ]
- [ ]

## 相关信息
```

### Bug Issue

```markdown
## Bug 描述

<!-- 一句话说明在什么条件下发生了什么异常。 -->

## 复现过程

<!-- 必填。从已知状态开始，完整写明操作、输入、命令或页面路径；示例数据必须脱敏。 -->
1.
2.
3.

## 补充信息（可选）

<!-- 可按需补充环境、预期与实际行为、影响、频率、日志、截图、原因分析、修复目标或关联资料。 -->

## 安全检查

- [ ] 该问题不涉及需要私下报告的安全漏洞
```

### Pull Request

```markdown
## 关联 Issue

Closes #N

## 主要改动

-

## 采用该方案的原因

## 测试与验证

- [ ] 测试已完成
- [ ] 手动验证已完成
- [ ] 构建或静态检查已完成

## 风险与回滚

## UI 证据

## AI 使用情况

## 自检

- [ ] 改动范围符合 Issue
- [ ] 不包含无关改动
- [ ] 已包含必要的测试和文档
- [ ] 不包含密钥、个人信息或非预期生成物
- [ ] 已完成 AI 辅助质量检查和人工 Review
```

# GitHub 工程协作 Skill

本分支只存放 `github-engineering-workflow` Skill 及其使用说明，不包含 `TRPG-master` 项目代码。

该 Skill 用于按需执行以下 GitHub 协作流程：

```text
Proposal → Design (Issue) → Coding (PR) → Review → Merge
```

包括 Issue、Bug Issue、Commit、PR 和 Review 规范。Skill 默认不会自动启用，只有显式调用时才对当前任务生效。

## 安装

下载本分支：

```bash
git clone --branch skill --single-branch https://github.com/LMH168/TRPG-master.git
```

将 Skill 目录复制到个人 Codex Skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R TRPG-master/github-engineering-workflow "${CODEX_HOME:-$HOME/.codex}/skills/"
```

如果已经安装过，请先确认是否需要保留本地修改，再用本分支中的目录更新。

## 使用

在任务中显式调用：

```text
使用 $github-engineering-workflow 按规范管理本次开发任务。
```

例如：

```text
使用 $github-engineering-workflow 为登录异常创建 Bug Issue。
```

```text
使用 $github-engineering-workflow 完成 Issue #12，并准备 Commit 和 PR。
```

不提及 `$github-engineering-workflow` 时，该 Skill 不会自动套用。

## Bug Issue 的最小要求

Bug Issue 只额外强制两项：

1. 提供完整、编号的复现过程。
2. 疑似安全漏洞不得公开提交，必须使用仓库的私密安全报告渠道。

环境、影响、日志、截图、原因分析和修复目标等信息均为可选。

## 目录

```text
github-engineering-workflow/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── workflow.md
```

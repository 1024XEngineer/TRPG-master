# GitHub 工程协作 Skill

`github-engineering-workflow` 是一套供 Codex 按需调用的 GitHub 工程协作规范，用于让一次开发任务按照下面的链路推进：

```text
Proposal → Design (Issue) → Coding (PR) → Review → Merge
```

本分支是独立的 Skill 分发分支，只包含 Skill 和本说明文件，不包含 `TRPG-master` 的项目代码，也不需要合并到 `main`。

## 这个 Skill 能做什么

显式调用后，Codex 会在当前任务中：

- 先查找、创建或整理对应 Issue，再开始实现。
- 检查 Issue 的目标、范围、设计说明和验收标准是否清晰。
- 为 Bug Issue 补充完整、编号的复现过程。
- 遇到疑似安全漏洞时停止公开提交，改用仓库的私密安全报告渠道。
- 将实现范围控制在关联 Issue 内，不夹带无关改动。
- 运行并如实汇报相关测试、检查和构建结果。
- 按统一格式准备原子 Commit：

  ```text
  <type>(<scope>): <summary> (#<issue>)
  ```

- 准备关联 Issue 的小型 PR，并区分：

  ```text
  Closes #N
  ```

  与：

  ```text
  Refs #N
  ```

- 在合并前检查改动范围、测试、风险、敏感信息和人工 Review 状态。
- 默认使用中文编写 Issue、PR、Commit 和 Review 内容；技术标识及 GitHub 关键字保留英文。

## 这个 Skill 不会做什么

- 不会自动影响每一个项目或每一次任务。
- 不会在没有显式调用时自行启用。
- 不会虚构 Issue、PR、测试、检查或 Review 结果。
- 不会因为调用了 Skill 就自动获得推送、创建 PR、合并或修改仓库设置的权限。
- 不会绕过分支保护、必需检查或人工审批。
- 不会在未获得授权时自动向远程仓库写入内容。

## 安装前提

- 已安装支持个人 Skills 的 Codex。
- 可以访问本 GitHub 仓库。
- 使用命令行安装时，需要安装 Git。

个人 Skill 默认安装在：

```text
~/.codex/skills/
```

如果设置了 `CODEX_HOME`，则安装在：

```text
$CODEX_HOME/skills/
```

## 安装方法一：使用 Git（推荐）

### macOS / Linux

1. 只克隆本仓库的 `skill` 分支：

   ```bash
   git clone \
     --branch skill \
     --single-branch \
     --depth 1 \
     https://github.com/LMH168/TRPG-master.git \
     github-engineering-workflow-skill
   ```

2. 确定个人 Skills 目录并创建它：

   ```bash
   SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
   mkdir -p "$SKILLS_DIR"
   ```

3. 复制 Skill：

   ```bash
   cp -R \
     github-engineering-workflow-skill/github-engineering-workflow \
     "$SKILLS_DIR/github-engineering-workflow"
   ```

4. 重新打开 Codex，或者新建一个任务，让 Codex 重新扫描 Skills。

### Windows PowerShell

1. 只克隆 `skill` 分支：

   ```powershell
   git clone `
     --branch skill `
     --single-branch `
     --depth 1 `
     https://github.com/LMH168/TRPG-master.git `
     github-engineering-workflow-skill
   ```

2. 确定并创建个人 Skills 目录：

   ```powershell
   if ($env:CODEX_HOME) {
     $SkillsDir = Join-Path $env:CODEX_HOME "skills"
   } else {
     $SkillsDir = Join-Path $HOME ".codex\skills"
   }

   New-Item -ItemType Directory -Force -Path $SkillsDir
   ```

3. 复制 Skill：

   ```powershell
   Copy-Item `
     -Recurse `
     "github-engineering-workflow-skill\github-engineering-workflow" `
     (Join-Path $SkillsDir "github-engineering-workflow")
   ```

4. 重新打开 Codex，或者新建一个任务。

## 安装方法二：下载 ZIP

1. 打开 [`skill` 分支](https://github.com/LMH168/TRPG-master/tree/skill)。
2. 选择 **Code → Download ZIP**。
3. 解压下载的文件。
4. 找到其中的 `github-engineering-workflow` 文件夹。
5. 将整个文件夹复制到个人 Codex Skills 目录：

   ```text
   ~/.codex/skills/
   ```

6. 最终确认存在以下文件：

   ```text
   ~/.codex/skills/github-engineering-workflow/SKILL.md
   ```

7. 重新打开 Codex，或者新建一个任务。

## 检查是否安装成功

安装后的目录应为：

```text
~/.codex/skills/
└── github-engineering-workflow/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    └── references/
        └── workflow.md
```

在新的 Codex 任务中输入 `$`，检查候选 Skill 中是否出现：

```text
github-engineering-workflow
```

也可以直接发送：

```text
使用 $github-engineering-workflow 帮我整理本次开发任务的 Issue。
```

如果 Codex 能识别并按规范处理，说明安装成功。

## 基本用法

这个 Skill 必须显式调用，并且只对调用它的当前任务生效。

通用调用方式：

```text
使用 $github-engineering-workflow 按规范管理本次开发任务。
```

不提及 `$github-engineering-workflow` 时，不会自动套用这套规范。

### 只创建 Issue

```text
使用 $github-engineering-workflow，为用户头像上传功能整理一份 Issue，暂时不要写代码。
```

### 创建 Bug Issue

```text
使用 $github-engineering-workflow，为“登录成功后页面仍停留在登录页”创建 Bug Issue。
复现过程是：打开登录页，输入有效账号，点击登录，接口返回成功，但页面没有跳转。
```

Bug Issue 只额外强制两项：

1. 提供完整、编号的复现过程。
2. 疑似安全漏洞不得公开提交，必须使用仓库的私密安全报告渠道。

环境、影响、日志、截图、原因分析、修复目标和回归测试说明等内容均为可选。

### 根据 Issue 开发

```text
使用 $github-engineering-workflow 完成 Issue #12，运行相关测试，并准备 Commit 和 PR。
```

Codex 会以真实的 Issue 编号约束实现范围。Issue 编号未知时，不会虚构编号并创建 Commit。

### 只生成 Commit message

```text
使用 $github-engineering-workflow，根据当前暂存区改动和 Issue #12 生成 Commit message，不要提交。
```

示例结果：

```text
fix(auth): 修复登录成功后页面未跳转的问题 (#12)
```

### 只准备 PR

```text
使用 $github-engineering-workflow，根据当前分支和 Issue #12 准备 PR 标题与描述，不要推送。
```

### 检查现有改动

```text
使用 $github-engineering-workflow 检查当前改动是否符合 Issue #12，并指出提交 PR 前还缺什么。
```

## 权限和执行边界

调用 Skill 代表要求 Codex 遵循这套流程，但不等于授权所有远程操作。

如果希望 Codex 实际执行远程操作，请在请求中明确说明，例如：

```text
使用 $github-engineering-workflow 完成 Issue #12，提交代码、推送分支并创建草稿 PR。
```

如果只希望获得文案，应明确说明：

```text
使用 $github-engineering-workflow 生成 Issue 和 PR 文案，不要修改文件，不要执行远程操作。
```

## 更新 Skill

如果之前通过 Git 克隆了本分支：

```bash
git -C github-engineering-workflow-skill pull
```

更新安装目录前，建议先备份当前版本：

```bash
SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
mv \
  "$SKILLS_DIR/github-engineering-workflow" \
  "$SKILLS_DIR/github-engineering-workflow.backup"
cp -R \
  github-engineering-workflow-skill/github-engineering-workflow \
  "$SKILLS_DIR/github-engineering-workflow"
```

确认新版本正常后，再自行删除备份目录。

通过 ZIP 安装的用户需要重新下载 `skill` 分支，并重新复制 `github-engineering-workflow` 文件夹。

## 卸载

关闭 Codex 后，将下面的文件夹移出个人 Skills 目录或删除：

```text
~/.codex/skills/github-engineering-workflow
```

重新打开 Codex 后，该 Skill 将不再出现在可用 Skills 中。

## Skill 文件结构

```text
github-engineering-workflow/
├── SKILL.md
├── agents/
│   └── openai.yaml
└── references/
    └── workflow.md
```

- `SKILL.md`：定义触发方式、主流程和执行边界。
- `agents/openai.yaml`：定义 Skill 在 Codex 中的名称、说明和显式调用策略。
- `references/workflow.md`：保存 Issue、Bug、Commit、PR 和 Review 的详细规范与模板。

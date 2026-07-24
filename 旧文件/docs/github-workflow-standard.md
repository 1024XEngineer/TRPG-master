# GitHub 小组操作流程标准参考（内部版）

> 来源：https://github.com/1024XEngineer/TRPG-master/wiki
> 最后编辑：WELT, 2026-07-16
> 适用范围：README、使用说明、安装指南、FAQ 等需要进入代码仓库的用户文档
> 不适用：产品方案、架构决策、设计文档等工程文档（这些应保留在 Issue 描述及编辑历史中）

---

## 一、流程总览

```
创建 Issue
  ↓
关联标签与 Milestone
  ↓
Fork 主仓库并同步 main
  ↓
在 Fork 创建独立分支
  ↓
只修改目标文档并自检
  ↓
Conventional Commit
  ↓
推送到 Fork
  ↓
向主仓库创建 Draft PR
  ↓
Review → Ready for review → 合并
  ↓
关闭 Issue / 标记 Documented
```

**核心原则**：不在主仓库直接创建开发分支，不直接推送主仓库 main，所有变更通过 Fork + PR。

---

## 二、创建文档 Issue

**标题示例**：`[Document] 更新 README 以匹配 MS1 实际实现`

**建议结构**：

- **## 背景** — 说明为什么文档需要更新，旧内容造成了什么问题
- **## 修改范围** — 列出要新增什么、删除或修正什么，明确本次不包含代码变更
- **## 验收标准** — checklist，例如：
  - 文档描述与当前代码一致
  - 启动命令和配置说明可执行
  - 未完成的功能不被描述为已完成
  - PR 只包含目标文档
  - Markdown diff 检查通过

**标签和 Milestone**：

- 文档工作开始前：`Need-Document`
- 文档完成并合并后：`Documented`
- 如标签不存在，使用 `documentation` + 当前阶段标签（如 `ms1`）
- 关联 Issue 到对应 Milestone

---

## 三、准备 Fork 和本地仓库

1. 在 GitHub 上 Fork 主仓库
2. 本地设置两个 remote：
   - `origin` — 主仓库，仅用于同步
   - `fork` — 个人 Fork，用于推送分支

```bash
git remote add fork https://github.com/<用户名>/<仓库名>.git
git fetch origin main
git fetch fork main
git remote -v
```

验证本地 main 与主仓库一致：

```bash
git rev-list --left-right --count main...origin/main
# 输出 0 0 表示两边一致
```

---

## 四、确认修改范围

```bash
git status -sb
git diff -- README.md
```

如果存在无关文件，不要使用 `git add -A`。只暂存目标文件：

```bash
git add -- README.md
```

---

## 五、创建独立分支

```bash
git switch -c agent/update-ms1-readme
```

**推荐格式**：`agent/<简短任务描述>` 或 `docs/<简短任务描述>`。

一个分支处理一个明确的文档任务。

---

## 六、本地自检

至少执行：

```bash
git diff --check
git diff --cached --check
git diff --cached --stat
```

对于 README 文件，人工确认：
- 当前功能状态是否与代码一致
- 计划中的功能是否被误描述为已完成
- 启动顺序、端口、环境变量是否正确
- 链接和 Markdown 渲染是否正常
- 密钥、账号、本地敏感路径是否暴露
- 团队信息是否准确
- diff 是否仅包含目标文件

如果 README 改了构建或启动说明，实际跑一次相关命令验证。

---

## 七、提交

遵循 Conventional Commits：

```bash
git commit -m "docs(readme): align documentation with MS1 implementation"
```

**常用格式**：`docs(<范围>): <修改目的>`

不要使用 "update" 或 "改一下" 等模糊信息。

---

## 八、推送到个人 Fork

确认推送目标是 `fork`，不是主仓库 `origin`：

```bash
git push -u fork agent/update-ms1-readme
```

推送后确认远程跟踪关系：

```bash
git status -sb
```

---

## 九、创建 Draft PR

**PR 目标设置**：
- Base: 主仓库 `main`
- Head: `<个人用户名>:<个人分支>`
- 初始状态: Draft

**标题示例**：`docs(readme): align documentation with MS1 implementation`

**PR 描述模板**：

```markdown
## What changed
- 重写或更新了哪些文档内容
- 补充了哪些启动、配置或限制说明

## Why
说明旧文档与当前代码存在什么不一致

## Impact
本次仅修改文档，不改变前端、后端、SDK、API 或运行行为

## Validation
- `git diff --check` 通过
- 已对照当前代码核验功能和限制
- 已验证相关构建或启动命令

Closes #<Issue 编号>
```

`Closes #编号` 会在 PR 合并后自动关闭对应 Issue。

---

## 十、Review 与合并

1. 创建 Draft PR 后，先自行检查 "Files changed"
2. 确认只包含目标文档
3. 添加 `documentation` 标签和当前 Milestone 标签
4. 邀请队友、导师或 TA 审查
5. 处理反馈后切换为 "Ready for review"
6. Review 和仓库检查通过后合并
7. 不绕过分支保护，不直接推送主仓库 main

---

## 十一、合并后收尾

- 确认 PR 已合并
- 确认关联 Issue 已自动关闭
- 标记 Issue 为 `Documented`
- 如果仓库没有 `Documented` 标签，保留 `documentation`
- 删除 Fork 上已合并的临时分支
- 本地切回 main 并同步主仓库：

```bash
git switch main
git fetch origin main
git pull --ff-only origin main
```

---

## 十二、禁止事项

- 直接推送主仓库 `main` 分支
- 在主仓库创建个人开发分支
- 无关代码和文档混在同一个 PR
- 不检查暂存内容就使用 `git add -A`
- 将工程设计文档作为普通用户文档直接提交到仓库
- Review 未完成自行合并
- 在 README 中将 Mock、计划功能、概念入口描述为已完成功能

---

## 个人示例

- **主仓库**：`1024XEngineer/TRPG-master`
- **Fork**：`WELT5350/TRPG-master`
- **Issue**：[#70 README更新](https://github.com/1024XEngineer/TRPG-master/issues/70)
- **分支**：`WELT5350:agent/update-ms1-readme`
- **Commit**：`6bb4a82`
- **Draft PR**：[#72 docs(readme): align documentation with MS1 implementation](https://github.com/1024XEngineer/TRPG-master/pull/72)

流程：Issue → Fork 分支 → Conventional Commit → Draft PR → Review → 合并

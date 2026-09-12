# #516 / #518 随行与委托人交互验收

日期：2026-09-07。实现位于 PR #526 的 `fix/issue-516-accompanying-entities` 分支，包含上游 main 的 #483 规则检定权威修复。

## 行为

- 真实模型负责当前步骤的语义识别；travel 与 dialogue 不再被确定性快路提前成交。每一步仍由引擎校验和提交。
- travel 可以选择随行相关模组规则。已发布规则拥有检定和效果，Fake 也通过同一规则构造入口使用 `check_skill_id`。
- Host 不再为随行自动追加一次性 `MoveEntityEffect`。建立/解除随行走规则或受校验的角色状态裁决，后续移动由引擎根据 `accompanying` 处理。
- 模组初始化的布尔随行状态对可见实体公开；其他未公开的模组私有状态仍不投影。
- 莱恩先生 `richard_lane`、莱恩夫人 `mrs_lane` 是庄园中的公开 NPC，具备公开别名和音色。玩家离开后返回，仍可与他们对话。
- 《幸福蛙蛙村》升级为 `3.0.10`。构建脚本、生成产物和 loader 版本同步；旧 `3.0.9` 内容保持不可变，既有房间继续使用其绑定版本，新建房间使用新版。

模组中“未解除影响便强行带离詹姆斯”的原有悲剧后果保持成立。随行回庄园不等于完成安全救援，测试也没有改写这一剧情规则。

## 端到端证据

`e2e/tests/accompanying.e2e.ts` 使用发布模组，从注册、选模组、建卡、开局开始，经真实 SDK、WebSocket、Host、SQL 存储与引擎执行，不直接修改游戏状态。

1. 庄园初始可见两名委托人；分别向他们发言，收到独立 `dialogue.npc`，speaker 和 source action 绑定正确。
2. 接受委托、进入度假村与接待大厅、把詹姆斯带出度假村后，提交原故障话语“拽着詹姆斯回到莱恩庄园”；詹姆斯出现在庄园可见 NPC 列表中，父母仍在场且可以对话。
3. 再提交一次没有重复要求同行的普通移动，詹姆斯继续跟随；断线重连后状态仍然成立，对话历史不重复。
4. 扛起詹姆斯建立随行；“不要放下詹姆斯”不解除；进入被锁员工区时人队不分离；“扶着詹姆斯去客房”可继续跟随；明确放下后再次移动不跟随，返回原地仍可见他。

这套 E2E 默认使用 Fake。生产模型适配器另由 `test_accompanying_host.py` 的离线结构化客户端验证：模型确实被调用、否定不会被快路改成移动、travel 步能选择随行规则、后续步骤读取已提交的新视图、门禁与单次移动事件正确。未执行外部真实模型在线验收，因此不将离线结果表述为真实模型的语义成功率。

## 验证结果

- 完整 SDK → 后端 E2E：**44 passed，3 skipped**；跳过项为已有的真实模型/已知阻塞用例。
- 框架：569 个用例完成验证。整套运行 568 passed；提示词版本断言随版本升级更新后，14 个架构用例重跑通过。
- 后端规则匹配及模组加载：原有范围 53 passed、1 skipped；因模型现在必须被调用而更新的一个适配器测试重跑通过。
- 新增后端验证：4 个模型路径用例及 1 个旧数据库升级用例通过。
- 后端 `ruff check`、`ruff format --check`、`ty check` 通过；SDK 构建和类型检查、E2E 类型检查通过。
- 重新运行蛙蛙村构建脚本后，三个模组产物的 SHA-256 保持一致。

### 变异检验

- 临时禁用引擎 `_move_accompanying`，新增 E2E 在客房的詹姆斯可见性断言处失败。
- 临时从发布模组删掉两名莱恩家长，新增 E2E 在开局 NPC 列表断言处失败。
- 两次验证均在 `finally` 中按原始字节恢复文件，再运行新增 E2E 确认恢复后的实现通过。

## 复现

使用 Python 3.13 和 Node.js 22，与仓库 CI 一致：

```bash
cd trpg-backend
uv sync --locked
uv run pytest tests/test_rule_match_adjudication.py tests/test_accompanying_host.py tests/test_builtin_module_loader.py
uv run ruff check .
uv run ruff format --check .
uv run ty check
cd ../agent-collaboration-framework
../trpg-backend/.venv/bin/python -m pytest -q
cd ../trpg-sdk
npm ci
npm run build
cd ../e2e
npm ci
npm run typecheck
E2E_ONLY=tests/accompanying.e2e.ts npm run test:e2e
npm run test:e2e
```

E2E 启动独立的本地后端并重建 `e2e.db`，不使用开发数据库。已有版本的数据库兼容性由专门的 loader 用例验证。

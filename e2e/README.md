# trpg-e2e

核心流程的端到端验证（[issue #94](https://github.com/1024XEngineer/TRPG-master/issues/94)）。

跨 `trpg-backend` / `trpg-sdk` / `trpg-frontend` 三层，用真实浏览器走一遍真实用户路径：
**注册 → 创建房间 → 选择游戏/规则/模组 → 大厅 → 建卡 → 完成 → 查看角色卡**。

## 为什么需要它

三个单包 CI（backend / sdk / frontend）各自覆盖各自那一层，但**这个项目的缺陷集中住在集成缝隙里**——以下都是 pytest + ruff + ty + eslint + tsc 全部通过、只有人工点浏览器才发现的：

- 角色卡只读视图不显示幸运（三处硬编码属性列表各自「合法」）
- 加幸运后旧角色无法编辑（localStorage 持久化态 × 后端校验的交互）
- `RoomPage` 的 `room.join` 漏传 `reconnectToken`（被 `as` 断言掩盖，类型检查通过）
- 大厅「全员已就绪」把房主自己算了进去，按钮永远点不亮

这套测试把那些原本只能靠人工点、结果不可复现的验证，固化成机器可重复的断言。

## 怎么跑

```bash
npm ci
npx playwright install chromium   # 首次需要
npm run test:e2e
```

**不需要先手工起后端和前端**——`playwright.config.ts` 里的 `webServer` 会自己把两个服务拉起来，本地和 CI 走的是同一份配置。前置条件只有两个：

- `trpg-backend` 已经 `uv sync`（配置直接调 `.venv/bin/` 里的可执行文件）
- `trpg-sdk` 已经 `npm run build`、`trpg-frontend` 已经 `npm ci`（前端把 SDK 作为 `file:../trpg-sdk` 本地依赖）

失败时看回放：

```bash
npx playwright show-trace test-results/<用例目录>/trace.zip
```

CI 上这些产物会作为 artifact 上传（`playwright-report`），可以下载下来用同样的命令回放。

## 两个容易踩的坑

**① 前端必须跑在 `localhost:9877`。** 后端 `cors_origins` 默认值是 `["http://localhost:9877"]`，浏览器判 origin 是逐字符比对的——用 `vite preview` 默认的 4173、或者把 `localhost` 写成 `127.0.0.1`，请求都会被 CORS 拦掉。所以配置里把 preview 端口固定成了 9877。

**② 每次跑都用全新的 `e2e.db`。** 用例会注册账号、建房间，复用旧库会让结果取决于「之前跑过几次」，是最典型的 flaky 来源。同时它刻意不用开发用的 `app.db`，免得跑个测试把本地开发数据清掉。

## 写用例的约定

- **断言具体数值，不要只断言「没报错」。** 一个只检查页面没崩的用例几乎抓不到真问题。比如属性页要断言加点网格正好 8 项、总点数 `400/480`——后者能钉死「幸运不占属性点预算」这条规则（幸运若被计入会变成 `450/480`）。
- **禁止固定 `sleep`。** 一律用 Playwright 的自动等待断言（`expect(locator).toHaveText(...)` 等）。固定等待是 e2e 变成随机红灯的头号原因，而**一个会随机变红的测试很快就会被所有人无视，比没有更糟**。
- **禁止 `if (await locator.isVisible()) { ... }` 这种条件式操作。** `isVisible()` 是即时检查、不等待，在慢一点的机器上会在元素出现前返回 `false`，于是**静默跳过**那一步，测试一路跑到很远的地方才以一个跟根因无关的现象失败。`click()` / `fill()` 本身就会自动等待元素可交互，直接操作即可。（这套测试第一次在 CI 上跑挂就是这个原因，而本地跑 10 次全绿——本地快、CI 慢，条件式判断的结果正好相反。）如果某一步真的「可能有也可能没有」，说明流程本身不确定，那才是该先想清楚的问题。
- **配置里 `retries: 0`。** 重试会把偶发失败洗成绿色、把 flaky 藏起来。红了就应该是真的坏了。
- **加了新用例，做一次变异检验**：故意把它该守住的东西改坏，确认它真的会变红。一个永远不会失败的测试是零价值的。

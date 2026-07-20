import { defineConfig, devices } from '@playwright/test'

/**
 * 端到端验证配置（issue #94）。
 *
 * 设计目标是「一条命令在本地跑出跟 CI 一模一样的行为」，所以后端和前端都由
 * `webServer` 拉起来，而不是要求先手工把两个服务开好——CI 里也走同一份配置。
 *
 * 两个容易踩的点，都在下面对应位置写清楚了：端口必须是 9877（CORS），
 * 以及每次跑都要用全新数据库。
 */

const BACKEND_PORT = 8000
const FRONTEND_PORT = 9877

/**
 * ⚠️ 前端必须跑在 9877、且用 `localhost` 而不是 `127.0.0.1`。
 *
 * 后端 `app/core/config.py` 的 `cors_origins` 默认值是
 * `["http://localhost:9877"]`，浏览器判同源是**逐字符比对 origin 字符串**的，
 * `http://127.0.0.1:9877` 跟它不相等一样会被 CORS 拦掉。所以这里不用
 * `vite preview` 的默认端口 4173，直接对齐后端已经放行的那个 origin，
 * 免得为了跑测试再去改后端配置。
 */
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`

export default defineConfig({
  testDir: './tests',

  // CI 上禁止 `test.only` 漏提交（会让别的用例被静默跳过）。
  forbidOnly: !!process.env.CI,

  /**
   * 不重试。
   *
   * 重试能把偶发失败洗成绿色，等于把 flaky 藏起来——而 issue #94 明确要求这套
   * 测试必须稳定（验收标准 6：连续跑 10 次全绿、不允许出现固定 sleep）。
   * 红了就应该是真的坏了，而不是"再跑一次看看"。
   */
  retries: 0,

  // 本地并行、CI 单 worker：这套用例共用同一个后端和同一个数据库，
  // 并行跑会互相干扰（房间码、账号、房间状态都是全局的）。
  workers: 1,

  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: FRONTEND_URL,

    // 失败时留下可回放的证据——这正是 issue #94 的核心诉求：
    // reviewer 要能在 GitHub 上下载下来自己看挂在哪一步，而不是只看一句报错。
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',

  },

  /**
   * 手机视口 + Chromium。
   *
   * 产品是手机端形态，所以视口用 iPhone 13；但浏览器内核**显式覆盖成 chromium**
   * ——`devices['iPhone 13']` 自带的 `defaultBrowserType` 是 webkit，直接用会要求
   * CI 额外下载并维护 webkit 运行时（还要装一堆系统依赖），启动更慢也更容易因
   * 环境问题挂掉。v1 先用 chromium 把这条链路稳定跑绿；等真的出现只在 Safari
   * 复现的问题，再单独加一个 webkit project（那时是有据可依地加，而不是一开始
   * 就为"可能有用"付出 CI 时间）。
   */
  projects: [
    {
      name: 'chromium-mobile',
      use: { ...devices['iPhone 13'], browserName: 'chromium' },
    },
  ],

  webServer: [
    {
      /**
       * 后端：每次都用**全新数据库**。
       *
       * 用例会注册账号、建房间，跑完这些数据都留在库里；复用旧库的话，第二次
       * 跑就可能撞上重名账号/房间数量变化之类的干扰，测试结果取决于跑过几次，
       * 这是最典型的 flaky 来源。所以先删掉 e2e.db 再跑迁移。
       *
       * 另外这里刻意用独立的 `e2e.db` 而不是开发用的 `app.db`——跑一次测试就
       * 把本地开发数据清空是很讨厌的副作用。
       */
      /**
       * 直接调 `.venv/bin/` 里的可执行文件，而不是 `uv run ...`：
       * `uv sync` 本来就会在 trpg-backend/.venv 建出这个虚拟环境（CI 和本地
       * 都一样），这样就不额外要求 `uv` 本身在 PATH 上——本机上它就不在，
       * 写成 `uv run` 会直接 `uv: command not found` 起不来。
       */
      command: [
        'rm -f e2e.db',
        '.venv/bin/alembic upgrade head',
        `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT}`,
      ].join(' && '),
      cwd: '../trpg-backend',
      env: { DATABASE_URL: 'sqlite+aiosqlite:///./e2e.db' },

      /**
       * 就绪探测用 `GET /api/v1/games`：它是免鉴权的（controller 里只依赖
       * get_db，没有 Authorization 校验），而且后端没有专门的健康检查端点。
       */
      url: `http://127.0.0.1:${BACKEND_PORT}/api/v1/games`,

      // 永远不复用已在跑的后端：复用就意味着用的是别人的数据库，
      // 上面「全新数据库」这条保证会失效。
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      /**
       * 前端：跑构建产物而不是 dev server。
       *
       * 一是更接近真实部署形态（dev server 的 HMR、按需编译会引入额外时序噪声），
       * 二是能顺带把 `tsc -b` 的类型检查也跑到（`npm run build` 里含它）。
       */
      command: `npm run build && npm run preview -- --port ${FRONTEND_PORT} --strictPort`,
      cwd: '../trpg-frontend',
      url: FRONTEND_URL,

      // 本地允许复用已经开着的 preview，省掉每次重复构建的 30s；
      // CI 上必须自己构建，保证测的就是这次提交的代码。
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})

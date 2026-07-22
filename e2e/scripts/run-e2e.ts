/**
 * E2E 编排脚本：起后端 → 等就绪 → 跑测试 → 收摊。
 *
 * 做成一个脚本而不是「请先手动起后端再 npm test」，是为了让本地跑的和 CI 跑的
 * 是同一条路径——两套流程迟早会分叉，然后出现「CI 绿本地红」这类最浪费时间的
 * 问题。
 */
import { spawn, type ChildProcess } from 'node:child_process'
import { rmSync } from 'node:fs'
import { createServer } from 'node:net'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const BACKEND_DIR = resolve(HERE, '../../trpg-backend')

/**
 * 刻意**不用**开发默认的 8000 端口。
 *
 * 早先用 8000，结果只要本地开着开发后端（很常见），这里 spawn 的 uvicorn 就绑不上
 * 端口、当场退出，而下面的就绪探测只是「GET 这个端口能不能应答」——开发后端答得
 * 好好的，于是整套用例**静默地跑在了开发后端 + 开发库 `app.db` 上**，既没用到
 * 全新的 `e2e.db`，也测不到当前工作区的后端代码。发现它是因为一次变异检验：
 * 把后端改坏之后测试竟然还是绿的。
 */
const PORT = Number(process.env.E2E_PORT ?? 8099)
const BASE_URL = `http://127.0.0.1:${PORT}`

/**
 * 每次跑都用**全新的 e2e.db**。
 *
 * 用例会注册账号、建房间、建角色卡，复用旧库会让结果取决于「之前跑过几次」，
 * 是最典型的 flaky 来源。另外刻意不用开发用的 `app.db`——跑个测试就把本地开发
 * 数据清掉是很讨厌的副作用。
 */
const DB_FILE = resolve(BACKEND_DIR, 'e2e.db')
const backendEnv = {
  ...process.env,
  DATABASE_URL: 'sqlite+aiosqlite:///./e2e.db',
}

/**
 * 直接调 `.venv/bin/` 里的可执行文件，而不是 `uv run ...`：`uv sync` 本来就会
 * 建出这个虚拟环境（CI 和本地都一样），这样不额外要求 `uv` 本身在 PATH 上——
 * 开发机上它经常就不在，写成 `uv run` 会直接 command not found。
 */
const VENV_BIN = resolve(BACKEND_DIR, '.venv/bin')

function run(command: string, args: string[], label: string): Promise<void> {
  return new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, { cwd: BACKEND_DIR, env: backendEnv, stdio: 'inherit' })
    child.on('exit', (code) =>
      code === 0 ? resolvePromise() : rejectPromise(new Error(`${label} 退出码 ${code}`))
    )
    child.on('error', rejectPromise)
  })
}

/**
 * 轮询到后端真的能应答为止，而不是 sleep 固定秒数。
 *
 * 固定等待在慢一点的机器上必然翻车，快的机器上又白等——这类「本地绿、CI 红」
 * 的坑踩过一次就够了。探测用 `GET /api/v1/games`：它免鉴权，而且后端没有专门
 * 的健康检查端点。
 */
async function waitForBackend(timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    // 先看我们自己起的那个进程还活着没有。少了这一条，uvicorn 因为端口被占
    // 之类的原因秒退时，这里只会一直轮询到超时，报「后端没有就绪」——离真正
    // 的原因很远；更糟的是端口上要是有别人的服务，探测反而会成功。
    if (backendExitCode !== undefined) {
      throw new Error(`后端进程启动失败，退出码 ${backendExitCode}（stderr 见上）`)
    }
    try {
      const response = await fetch(`${BASE_URL}/api/v1/games`)
      if (response.ok) return
    } catch {
      // 还没起来，继续等
    }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error(`后端在 ${timeoutMs}ms 内没有就绪`)
}

/**
 * 端口必须是空的——占用就直接失败，不要退化成「连到别人的后端上」。
 *
 * 这条断言比它看起来重要：探测就绪用的是 HTTP 应答，而 HTTP 应答**不能证明
 * 应答的是我们刚起的那个进程**。宁可报错让人去关掉占端口的进程，也不要让一
 * 整套 e2e 悄悄验证了另一个后端。
 */
function assertPortFree(port: number): Promise<void> {
  return new Promise((resolvePromise, rejectPromise) => {
    const probe = createServer()
    probe.once('error', () =>
      rejectPromise(
        new Error(
          `端口 ${port} 已被占用。e2e 需要独占它来确保跑的是当前工作区的后端 + 全新的 e2e.db；` +
            `请关掉占用它的进程，或用 E2E_PORT 指定另一个端口。`
        )
      )
    )
    probe.once('listening', () => probe.close(() => resolvePromise()))
    probe.listen(port, '127.0.0.1')
  })
}

let backend: ChildProcess | undefined
let backendExitCode: number | undefined

async function main(): Promise<number> {
  await assertPortFree(PORT)
  rmSync(DB_FILE, { force: true })
  await run(`${VENV_BIN}/alembic`, ['upgrade', 'head'], 'alembic')

  backend = spawn(
    `${VENV_BIN}/uvicorn`,
    ['app.main:app', '--host', '127.0.0.1', '--port', String(PORT)],
    { cwd: BACKEND_DIR, env: backendEnv, stdio: ['ignore', 'ignore', 'inherit'] }
  )
  backend.on('exit', (code) => {
    backendExitCode = code ?? 1
  })
  await waitForBackend()

  return await new Promise<number>((resolvePromise) => {
    const tests = spawn(
      'npx',
      ['tsx', '--test', '--test-reporter=spec', process.env.E2E_ONLY ?? 'tests/*.e2e.ts'],
      { cwd: resolve(HERE, '..'), env: { ...process.env, E2E_BASE_URL: BASE_URL }, stdio: 'inherit' }
    )
    tests.on('exit', (code) => resolvePromise(code ?? 1))
  })
}

function shutdown(): void {
  backend?.kill('SIGTERM')
}

process.on('SIGINT', () => {
  shutdown()
  process.exit(130)
})

main()
  .then((code) => {
    shutdown()
    process.exit(code)
  })
  .catch((error) => {
    console.error(error)
    shutdown()
    process.exit(1)
  })

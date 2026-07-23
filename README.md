<p align="center">
  <img src="https://img.shields.io/badge/milestone-MS1-brass?style=flat-square" alt="MS1" />
  <img src="https://img.shields.io/badge/frontend-React_19_|_Vite_7-61dafb?style=flat-square" alt="React 19 and Vite 7" />
  <img src="https://img.shields.io/badge/backend-FastAPI_|_Python_3.12+-teal?style=flat-square" alt="FastAPI and Python 3.12+" />
  <img src="https://img.shields.io/badge/realtime-WebSocket-7050a0?style=flat-square" alt="WebSocket" />
</p>

# 🎲 TRPG-master

> **有人就能跑。** 面向移动端的多人在线 TRPG 应用，目标是由 AI 承担守秘人（KP）的叙事工作。

当前仓库是一个已经完成前后端联调的 **MS1 可运行版本**，包含 React 前端、TypeScript SDK 和 FastAPI 后端。用户可以完成注册登录、创建或加入房间、选择模组、创建角色、进入大厅、开始游戏和房间内互动等基础流程。

当前版本仍属于阶段性实现：AI 叙事、复盘摘要和部分游戏数据使用占位内容，账号、房间与角色等核心业务数据暂存在后端内存中。后端重启后，这些数据会被清空。

## 当前功能

| 模块 | 当前实现 |
| --- | --- |
| 账号 | 注册、登录、退出登录、获取个人信息、修改昵称 |
| 首页 | 创建房间、输入房间码加入、查看我的房间、个人资料 |
| 房间 | 房主选择模组、玩家列表、准备状态、房主开始与结束游戏 |
| 角色 | CoC 风格建卡流程、属性与技能配置、装备和背景信息、完成建卡 |
| 实时通信 | WebSocket 会话绑定、准备、开始游戏、提交行动、房间叙事广播 |
| 游戏界面 | 对话区、角色卡、技能、地图、笔记和 D100/D20/D6 本地投骰交互 |
| API SDK | 封装认证、房间、角色和房间 WebSocket；与后端 DTO 对应的类型由 `npm run codegen` 生成 |

### 当前限制

- AI 尚未接入真实大模型。开始游戏和提交行动后返回的是后端固定占位叙事。
- 账号、会话、房间、玩家和角色使用内存存储，后端重启后会丢失。
- SQLite 与异步 SQLAlchemy 基础设施已经接入（用于建表），但核心业务（账号、房间、角色）仍是内存存储，尚未接入实际的数据库读写路径。
- 后端当前只提供一个内置模组「追书人」。前端展示的其他规则系统和场景中，部分仍是概念入口或静态数据。
- 投骰目前在前端本地执行，尚未接入后端统一规则引擎。
- 复盘摘要、完整事件记录、语音输入等能力尚未完成。

## 系统结构

```text
trpg-frontend (React)
        │
        ▼
trpg-sdk (REST + WebSocket)
        │
        ▼
trpg-backend (FastAPI)
        ├── /api/v1/*       REST API
        ├── /ws/{roomId}    房间实时通道
        ├── 内存业务存储     账号、房间、角色、会话
        └── SQLite          SQLAlchemy 基础设施（已接入，业务尚未接数据库）
```

统一 REST 响应格式如下：

```json
{
  "success": true,
  "data": {},
  "error": null
}
```

WebSocket 使用独立事件信封：客户端发送 `{ "type", "playerId", "payload" }`，服务端发送 `{ "type", "payload" }`。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | React 19、TypeScript 5、Vite 7、Tailwind CSS 3、Zustand 5、React Router 7 |
| SDK | TypeScript、Rollup 4 |
| 后端 | Python 3.12+、FastAPI、Pydantic 2、SQLAlchemy Async、Uvicorn |
| 实时通信 | WebSocket |
| 数据与安全 | SQLite、PostgreSQL 异步驱动、bcrypt |
| 工程质量 | pytest、ruff、ty、GitHub Actions |

## 项目目录

```text
TRPG-master/
├── trpg-frontend/        # 移动端 React 应用
├── trpg-sdk/             # 前后端通信 SDK，前端通过本地依赖引用
├── trpg-backend/         # FastAPI 服务、REST API、WebSocket 和测试
├── .github/workflows/    # 三个独立 CI：后端、SDK、前端
└── README.md
```

## 本地运行

### 环境要求

- Git
- Node.js 与 npm（版本需支持 Vite 7）
- Python 3.12 或更高版本；仓库的 `.python-version` 当前指定 3.13
- 推荐安装 [uv](https://docs.astral.sh/uv/) 管理后端环境

### 1. 克隆仓库

```bash
git clone https://github.com/1024XEngineer/TRPG-master.git
cd TRPG-master
```

### 2. 构建 SDK

前端通过 `file:../trpg-sdk` 引用 SDK，因此首次启动前需要先生成 `dist`。

```bash
cd trpg-sdk
npm ci
npm run build
cd ..
```

### 3. 启动后端

```bash
cd trpg-backend
uv sync --locked
uv run alembic upgrade head   # 建表：首次启动、以及之后表结构有变更时都要先跑
uv run uvicorn app.main:app --reload
```

> 建表由 Alembic 迁移负责（不再由应用启动时自动 `create_all`）。跳过
> `alembic upgrade head` 直接启动会因为表不存在、种子数据写入失败而崩溃。
>
> **如果你之前跑过旧版本、本地已有 `trpg-backend/app.db`**：旧版本靠应用启动时
> `create_all` 建表、没有 Alembic 迁移历史，直接 `alembic upgrade head` 会因为
> `rooms` 等表已存在而报错。旧版本的业务数据存在内存里（重启即丢），那个 `app.db`
> 里只有空的历史表、没有真实数据，**直接删掉重新迁移即可**（`rm trpg-backend/app.db`
> 再 `alembic upgrade head`）。

后端默认地址：<http://127.0.0.1:8000>

- 健康检查：<http://127.0.0.1:8000/api/v1/health>
- Swagger API 文档：<http://127.0.0.1:8000/docs>
- ReDoc API 文档：<http://127.0.0.1:8000/redoc>

复制 `.env.example` 为 `.env` 后可以覆盖默认配置；不复制也可以使用代码内置的本地开发默认值。

### 4. 启动前端

另开一个终端：

```bash
cd trpg-frontend
npm ci
npm run dev
```

浏览器打开：<http://localhost:9877>

默认后端 CORS 配置允许 `http://localhost:9877`。如果修改前端地址或端口，需要同步调整后端的 `CORS_ORIGINS`。

## 环境变量

### 后端 `trpg-backend/.env`

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `development` | 运行环境：`development`、`production` 或 `test` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./app.db` | SQLAlchemy 异步数据库地址 |
| `ENABLE_DOCS` | `true` | 是否开放 `/docs`、`/redoc` 和 `/openapi.json` |
| `LOG_LEVEL` | `INFO` | 后端日志级别 |
| `CORS_ORIGINS` | `["http://localhost:9877"]` | 允许跨域访问的前端来源列表 |

### 前端 `trpg-frontend/.env`

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api/v1` | REST API 根地址；WebSocket 地址由 SDK 自动推导 |

## 构建与检查

### SDK

```bash
cd trpg-sdk
npm ci
npm run lint
npm run typecheck
npm run build
npm test
```

### 前端

```bash
cd trpg-frontend
npm ci
npm run lint
npm run build   # 内部先跑 tsc -b 做类型检查，再用 vite build 打包
```

### 后端

```bash
cd trpg-backend
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

## 类型生成（codegen）

`trpg-sdk/src/generated/dto.ts` 里跟后端 DTO 对应的 TS 类型，是从
`trpg-backend/app/dto/*.py` 的 Pydantic 模型自动生成的，不再手写。**改了后端
DTO（REST 请求/响应体，或 `app/dto/ws.py` 里的 WebSocket 事件 payload）之后**，
需要依次跑：

```bash
# 1. 后端：把 DTO 导出成 JSON Schema（临时中间产物，不进 git）
cd trpg-backend
uv run python scripts/export_schema.py

# 2. SDK：从 JSON Schema 生成 TS 类型，写入 src/generated/dto.ts
cd ../trpg-sdk
npm run codegen
```

然后把 `trpg-sdk/src/generated/dto.ts` 的改动**跟 DTO 改动一起提交**——这个
文件是生成产物但会进 git（跟 `dist/` 不同：`dist/` 的消费者是机器，这个文件
的消费者是人和 CI，见 issue #75 的决策记录）。忘记重新生成会被 Backend CI 的
`codegen-drift` job 拦下（见下面「持续集成」）。

## 持续集成

`.github/workflows/` 下有三个互相独立的 workflow，各自按路径过滤器触发，只有
真正改到对应目录才会跑：

| Workflow | 触发路径 | 检查内容 |
| --- | --- | --- |
| `trpg-backend-ci.yml`（Backend CI） | `trpg-backend/**`；另外 `trpg-sdk/scripts/generate-types.ts` 和 `trpg-sdk/src/generated/**` 也会触发（见下） | `ruff check`、`ruff format --check`、`ty check`、`pytest`；另有 `codegen-drift` job：重新跑一遍 DTO → JSON Schema → TS 生成管线，用 `git diff` 确认 `trpg-sdk/src/generated/` 跟提交的一致，不一致就报错 |
| `trpg-sdk-ci.yml`（SDK CI） | `trpg-sdk/**` | `npm run lint`、`npm run typecheck`、`npm run build` |
| `trpg-frontend-ci.yml`（Frontend CI） | `trpg-frontend/**` | `npm run lint`、`npm run build` |

`codegen-drift` 放在 Backend CI 而不是 SDK CI：它要在"改了 DTO 却忘记重新
生成"的那个 PR 上就亮红灯，而 SDK CI 只在 `trpg-sdk/**` 变化时触发——一个纯
改后端 DTO 的 PR 根本不会碰 `trpg-sdk/**`，放在 SDK CI 里等于没测。这也是
Backend CI 的路径过滤器额外加了两条 `trpg-sdk/` 路径的原因。

## 团队

| 成员 | GitHub |
| --- | --- |
| 高俊周 (GJZ) | [@WELT5350](https://github.com/WELT5350) |
| 凌铭辉 (LMH) | [@LMH168](https://github.com/LMH168) |
| 李敏譞 (LMX) | [@Ximaohu-LMX](https://github.com/Ximaohu-LMX) |
| 张家豪 (ZJH) | [@JoshuaZ16](https://github.com/JoshuaZ16) |
| 黄女珊 (HNS) | [@badadal](https://github.com/badadal) |
| 卢玮晨 (LWC) | [@Lyltrum](https://github.com/Lyltrum) |

## 协作约定

- 通过 fork + Pull Request 提交变更，不直接向主仓库主分支提交。
- Commit message 遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)。
- 后端 DTO（REST 或 WebSocket）发生变化时，按上面「类型生成（codegen）」的步骤重新生成 `trpg-sdk` 的类型并把生成结果一起提交，不再手动改 `trpg-sdk/src/types.ts`。

---

[1024 XEngineer Camp](https://github.com/1024XEngineer) Season 6

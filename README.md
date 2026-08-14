<p align="center">
  <img src="https://img.shields.io/badge/status-MS3_稳定测试版-c58b3b?style=flat-square" alt="MS3 稳定测试版" />
  <img src="https://img.shields.io/badge/frontend-React_19_|_Vite_7-61dafb?style=flat-square" alt="React 19 and Vite 7" />
  <img src="https://img.shields.io/badge/backend-FastAPI_|_Python_3.12+-teal?style=flat-square" alt="FastAPI and Python 3.12+" />
  <img src="https://img.shields.io/badge/realtime-WebSocket-7050a0?style=flat-square" alt="WebSocket" />
</p>

<h1 align="center">TRPG-master</h1>

<p align="center">
  由 AI 担任守秘人的在线 TRPG 游戏。
  <br />
  创建房间、制作调查员，然后直接用自然语言开始冒险。
</p>

<p align="center">
  <a href="http://218.11.5.114:10005"><strong>立即体验</strong></a>
  ·
  <a href="https://github.com/orgs/1024XEngineer/projects/28">开发进度</a>
  ·
  <a href="https://github.com/1024XEngineer/TRPG-master/issues">问题反馈</a>
</p>

<p align="center">
  <img src="docs/screenshots/product-hero.webp" alt="TRPG-master 侦探猫调查桌主题插画" />
</p>

## 在线体验

### [进入 CI Preview](http://218.11.5.114:10005)

CI Preview 始终部署 `main` 分支的最新版本，团队成员和访客可以随时进入试玩。

> 这是持续更新的预览环境，不是正式生产服务器。部署更新时数据可能重置，请勿保存重要资料。

## 关于 TRPG-master

TRPG-master 希望让一场跑团更容易开始。玩家不必等待守秘人到场：AI 主持人负责理解行动、描述场景和组织回合，规则引擎负责检定、资源与游戏状态的权威结算。

目前可以体验完整的基础流程：

- 注册登录，创建或加入游戏房间；
- 选择模组并创建 CoC 7th 调查员；
- 使用自然语言调查、交谈、移动和采取行动；
- 完成技能检定、幸运消耗与强推；
- 查看角色卡、地图、线索、物品和游戏记录；
- 在手机或桌面浏览器中继续同一局游戏。

## 当前可玩内容

### 《追书人》 / Paper Chase

禁酒令时期的阿诺兹堡，调查员受托找回五本失窃藏书，并调查一位藏书家一年前的失踪。

| 项目 | 内容 |
| --- | --- |
| 规则 | Call of Cthulhu 7th Edition |
| 人数 | 单人模组 |
| 时长 | 约 1-2 小时 |
| 内容版本 | `3.0.6` |
| 内容协议 | `content_schema_version=3` |

《追书人》当前由 `module-content-v3.json` 加载。仓库中的其他模组文件主要用于内容解析与 Schema 回归，不代表已经开放游玩。

## 它如何工作

```text
玩家输入自然语言行动
        ↓
AI 主持人理解意图并生成有限行动计划
        ↓
规则引擎校验目标、检定与游戏效果
        ↓
服务端权威掷骰并持久化状态
        ↓
AI 主持人根据已提交结果继续叙事
```

模型负责理解和叙事，不能直接修改游戏状态。目标、技能、场景与模组事实会在应用边界重新校验，最终结果只由规则引擎提交。

## 技术架构

```text
trpg-frontend (React)
        ↓
trpg-sdk (REST + WebSocket)
        ↓
trpg-backend (FastAPI)
        ├── Host / Narrator
        ├── Rule Engine
        ├── ModuleContent
        └── SQL Store
```

| 层 | 技术 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite 7、Tailwind CSS、Zustand |
| SDK | TypeScript、Rollup、REST、WebSocket |
| 后端 | Python 3.12+、FastAPI、Pydantic、SQLAlchemy |
| AI | Fake、OpenAI、Qwen、DeepSeek 适配器 |
| 质量 | pytest、Vitest、ruff、ty、GitHub Actions、E2E |

## 本地运行

需要 Node.js、npm、Python 3.12+ 和 [uv](https://docs.astral.sh/uv/)。仓库当前使用 Python 3.13。

### 1. 克隆并构建 SDK

```bash
git clone https://github.com/1024XEngineer/TRPG-master.git
cd TRPG-master/trpg-sdk
npm ci
npm run build
```

### 2. 启动后端

```bash
cd ../trpg-backend
uv sync --locked
uv run alembic upgrade head
uv run python scripts/load_paper_chase.py
uv run uvicorn app.main:app --reload \
  --reload-dir app --reload-dir ../agent-collaboration-framework/collaboration_framework
```

后端默认运行在 <http://127.0.0.1:8000>。模型、角色生图和主持人语音等配置以 [`trpg-backend/.env.example`](trpg-backend/.env.example) 为准；不配置远程模型时默认使用离线 Fake Provider。

### 3. 启动前端

```bash
cd ../trpg-frontend
npm ci
npm run dev
```

浏览器打开 <http://localhost:9877>。

## 开发与检查

```bash
# SDK
cd trpg-sdk
npm run lint && npm run typecheck && npm run build && npm test

# Frontend
cd ../trpg-frontend
npm run lint && npm run build && npm run test

# Backend
cd ../trpg-backend
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run pytest
```

后端 DTO 变化后，需要重新生成 SDK 类型并提交更新后的 `trpg-sdk/src/generated/dto.ts`：

```bash
cd trpg-backend
uv run python scripts/export_schema.py
cd ../trpg-sdk
npm run codegen
```

## 项目进展

- [项目看板](https://github.com/orgs/1024XEngineer/projects/28)：当前开发安排与状态
- [Issues](https://github.com/1024XEngineer/TRPG-master/issues)：缺陷、需求与设计讨论
- [Pull Requests](https://github.com/1024XEngineer/TRPG-master/pulls)：正在评审的实现

欢迎通过 Issue 提交复现步骤、体验反馈和改进建议。代码变更通过 fork + Pull Request 提交，并使用 Conventional Commits。

## 团队

[@WELT5350](https://github.com/WELT5350) ·
[@LMH168](https://github.com/LMH168) ·
[@Ximaohu-LMX](https://github.com/Ximaohu-LMX) ·
[@JoshuaZ16](https://github.com/JoshuaZ16) ·
[@badadal](https://github.com/badadal) ·
[@Lyltrum](https://github.com/Lyltrum)

---

[1024 XEngineer Camp](https://github.com/1024XEngineer) Season 6

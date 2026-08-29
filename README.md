<p align="center">
  <img src="https://img.shields.io/badge/release-v1.0-c58b3b?style=flat-square" alt="v1.0" />
  <img src="https://img.shields.io/badge/frontend-React_19_|_Vite_7-61dafb?style=flat-square" alt="React 19 and Vite 7" />
  <img src="https://img.shields.io/badge/backend-FastAPI_|_Python_3.12+-teal?style=flat-square" alt="FastAPI and Python 3.12+" />
  <img src="https://img.shields.io/badge/realtime-WebSocket-7050a0?style=flat-square" alt="WebSocket" />
</p>

<h1 align="center">TRPG-master</h1>

<p align="center">
  由 AI 担任守秘人的在线多人 TRPG 游戏。
  <br />
  创建房间、邀请朋友，用自然语言共同推进一个会记住行动、遵守规则的故事世界。
</p>

<p align="center">
  <a href="http://218.11.5.114:10005"><strong>打开试玩版</strong></a>
  ·
  <a href="https://github.com/orgs/1024XEngineer/projects/28">开发看板</a>
  ·
  <a href="https://github.com/1024XEngineer/TRPG-master/issues">问题反馈</a>
</p>

<p align="center">
  <img src="docs/screenshots/product-hero.webp" alt="TRPG-master 侦探猫调查桌主题插画" />
</p>

## 这是什么

TRPG 是一种由玩家共同参与的故事游戏。玩家直接说出角色想做什么，守秘人负责描述世界、扮演 NPC、执行规则，并根据大家的行动继续故事。

现实中的守秘人难找，几个人同时组局也不容易。TRPG-master 希望让玩家创建一个在线房间后，就能由 AI 接手主持工作，随时开始一场冒险。

它不只是在聊天室里续写故事。我们的核心判断是：**会讲故事，不等于会主持游戏。** 因此，模型负责理解和表达，骰子、时间、位置、线索、物品与结局等事实由规则引擎统一处理。AI 不能自行改写已经发生的结果，也不能提前泄露玩家尚未发现的信息。

## 现在能做什么

- 创建房间或用房间码加入，让多名玩家进入同一个游戏世界；
- 选择模组，创建自己的调查员并查看角色卡；
- 用自然语言调查、交谈、移动和采取行动；
- 在多人房间中区分角色扮演聊天与提交给守秘人的行动；
- 完成技能检定、幸运消耗和强推，结果写入共享状态；
- 查看地图、线索、物品和游戏记录；
- 刷新或短暂断线后重新回到当前房间；
- 按需使用角色头像生成和主持人语音。

当前版本为 `v1.0`。在线试玩环境会随版本持续更新，部署时数据可能重置，请勿保存重要资料。

## 内置模组

| 模组 | 人数 | 预计时长 | 无剧透简介 |
| --- | ---: | ---: | --- |
| 《追书人》 | 1–4 人 | 1–2 小时 | 调查五本藏书失窃案，以及一位藏书家一年前的失踪。 |
| 《银之锁》 | 1 人 | 1–2 小时 | 在昏暗的银色房间醒来后，解开束缚与谜题，寻找逃离的方法。 |
| 《幸福蛙蛙村》 | 1–4 人 | 4–6 小时 | 受托寻找失踪青年，前往一座以“幸福”为名的林间度假村。 |
| 《常暗之厢》 | 2–3 人 | 约 1 小时 | 在驶入黑暗的末班电车上醒来，沿车厢寻找线索与出路。 |

模组内容统一转换为可校验的结构化数据。场景、人物、线索、秘密、规则和结局会在加载前检查，只有通过校验的内容才能进入游戏。

## 一次行动怎样完成

```text
玩家用自然语言描述行动
        ↓
AI 守秘人理解玩家想做什么，并组织本轮主持
        ↓
规则引擎判断是否需要检定，计算并写入结果
        ↓
AI 根据已经确定的事实继续叙述
        ↓
所有玩家看到同一个世界继续变化
```

简单说，AI 可以理解和表达，但不能自行决定事实。这让我们既能保留自然语言交互，又能避免模型编造骰子结果、忘记状态或前后矛盾。

## 技术架构

```text
trpg-frontend (React)
        ↓
trpg-sdk (REST + WebSocket)
        ↓
trpg-backend (FastAPI)
        ├── AI Host / Narrator
        ├── Rule Engine
        ├── ModuleContent
        └── SQL Store
```

| 部分 | 主要技术 |
| --- | --- |
| 前端 | React 19、TypeScript、Vite 7、Tailwind CSS、Zustand |
| SDK | TypeScript、Rollup、REST、WebSocket |
| 后端 | Python 3.12+、FastAPI、Pydantic、SQLAlchemy |
| AI | OpenAI、Qwen、DeepSeek 兼容适配器，以及离线 Fake Provider |
| 质量保障 | pytest、Vitest、ruff、ty、GitHub Actions、E2E、真人试玩 |

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
uv run uvicorn app.main:app --reload --reload-dir app --reload-dir ../agent-collaboration-framework/collaboration_framework
```

后端默认运行在 <http://127.0.0.1:8000>，启动时会自动加载仓库内置模组。

模型、角色生图和主持人语音等配置以 [`trpg-backend/.env.example`](trpg-backend/.env.example) 为准。不配置远程模型时会使用离线 Fake Provider，便于开发和自动化测试；真人试玩需要配置实际模型服务。

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

## 项目记录

- [研发看板](https://github.com/orgs/1024XEngineer/projects/28)：当前安排和进度
- [Issues](https://github.com/1024XEngineer/TRPG-master/issues)：需求、缺陷和设计讨论
- [Pull Requests](https://github.com/1024XEngineer/TRPG-master/pulls)：实现、评审和验收记录

欢迎通过 Issue 提交复现步骤和体验反馈。代码变更通过 Fork + Pull Request 提交，并使用 Conventional Commits。

## 团队

[@WELT5350](https://github.com/WELT5350) ·
[@LMH168](https://github.com/LMH168) ·
[@Ximaohu-LMX](https://github.com/Ximaohu-LMX) ·
[@JoshuaZ16](https://github.com/JoshuaZ16) ·
[@badadal](https://github.com/badadal) ·
[@Lyltrum](https://github.com/Lyltrum)

---

[1024 XEngineer Camp](https://github.com/1024XEngineer) Season 6

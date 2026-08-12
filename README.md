<p align="center">
  <img src="https://img.shields.io/badge/milestone-MS1-brass?style=flat-square" alt="MS1" />
  <img src="https://img.shields.io/badge/frontend-React_19_|_Vite_7-61dafb?style=flat-square" alt="React 19 and Vite 7" />
  <img src="https://img.shields.io/badge/backend-FastAPI_|_Python_3.12+-teal?style=flat-square" alt="FastAPI and Python 3.12+" />
  <img src="https://img.shields.io/badge/realtime-WebSocket-7050a0?style=flat-square" alt="WebSocket" />
</p>

# 🎲 TRPG-master

> **有人就能跑。** 面向移动端的多人在线 TRPG 应用，目标是由 AI 承担守秘人（KP）的叙事工作。

当前仓库是一个已经完成前后端联调的 **MS1 可运行版本**，包含 React 前端、TypeScript SDK 和 FastAPI 后端。用户可以完成注册登录、创建或加入房间、选择模组、创建角色、进入大厅、开始游戏和房间内互动等基础流程。

当前版本仍属于阶段性实现：主持人意图理解与叙事支持离线 Fake、OpenAI 和阿里云百炼千问三种模式，默认使用不访问网络的 Fake；复盘摘要等非主链能力仍未实现。账号、房间、角色、模组内容、规则 Runtime、事件和已完成动作均由 SQL Store 持久化。

## 当前功能

### 在线体验

`main` 有新提交（包括 PR 合并）后会自动更新持久预览环境，前端入口固定使用
网关端口 `10005`，地址不会随着部署变化：

- [TRPG-master 持久预览](http://218.11.5.114:10005)

该环境只保留面向用户的前端入口，`/api` 和 `/ws` 由 Caddy 反向代理到后端；
数据库随容器重建而重置，未配置 Preview 专用 DeepSeek key 时使用 Fake Provider。

| 模块 | 当前实现 |
| --- | --- |
| 账号 | 注册、登录、退出登录、获取个人信息、修改昵称 |
| 首页 | 创建房间、输入房间码加入、查看我的房间、个人资料 |
| 房间 | 房主选择模组、玩家列表、准备状态、房主开始与结束游戏 |
| 角色 | CoC 风格建卡流程、属性与技能配置、装备和背景信息、完成建卡 |
| 实时通信 | WebSocket 会话绑定、准备、开始游戏、提交行动、房间叙事广播 |
| AI 主持 | 玩家安全上下文、结构化意图解析、确定性规则执行、结果叙事；支持 OpenAI 与千问 3.7 Plus |
| 游戏界面 | 对话区、角色卡、技能、地图、笔记和 D100/D20/D6 本地投骰交互 |
| 语音输入 | 支持浏览器原生语音识别，转写结果回填行动或讨论区输入框，由玩家编辑确认后发送 |
| API SDK | 封装认证、房间、角色和房间 WebSocket；与后端 DTO 对应的类型由 `npm run codegen` 生成 |

### 当前限制

- 默认 `HOST_MODEL_PROVIDER=fake`，不会访问真实大模型；远程 Host Agent 或 Narrator 失败时当前回合安全中止并允许重试，不会静默回退到 Fake。
- 当前唯一承诺可运行的模组是「追书人」；另外三个示例 JSON 只用于解析与 Schema 回归，不会自动写入运行数据库。
- 技能检定保留 `check.request → check.roll → check.result` 两阶段协议；玩家提交 D100 点数，后端规则引擎权威结算并持久化结果。
- Director、世界知识检索、长期记忆、主动剧情推进、RAG、持久即兴内容和完整重连恢复不在当前阶段。
- 复盘摘要和完整事件记录等能力尚未完成。
- 语音输入不需要项目配置第三方 Key，项目后端不会接收或保存原始录音；部分浏览器可能使用厂商远程服务完成识别，数据处理方式受浏览器服务条款约束。
- 语音输入依赖浏览器 Web Speech API 和安全上下文。localhost 或 HTTPS 可用；当前纯 HTTP 的持久预览会明确显示语音输入不可用，键盘输入不受影响。

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
        ├── TurnApplication   Host Agent → 两阶段检定 → RuleEngine → Narrator
        ├── 模型适配器        Fake / OpenAI Responses / Qwen Agents SDK
        └── SQL Store         业务数据、模组、Runtime、事件与幂等记录
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
| AI 主持 | Host Orchestrator、OpenAI Responses API、阿里云百炼千问 JSON Mode |
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
uv run uvicorn app.main:app --reload \
  --reload-dir app --reload-dir ../agent-collaboration-framework/collaboration_framework
```

> 两个 `--reload-dir` 都不能省。`--reload` 默认只监视当前工作目录，而规则引擎
> （`collaboration_framework`）是以 editable 方式装进来的**兄弟目录**——改了它
> 不会触发重载，后端会一直跑着旧引擎，表现为"代码明明改了、游戏里没变化"。

> 建表由 Alembic 迁移负责（不再由应用启动时自动 `create_all`）。跳过
> `alembic upgrade head` 直接启动会因为表不存在、种子数据写入失败而崩溃。
>
> **如果你之前跑过旧版本、本地已有 `trpg-backend/app.db`**：旧版本靠应用启动时
> `create_all` 建表、没有 Alembic 迁移历史，直接 `alembic upgrade head` 会因为
> `rooms` 等表已存在而报错。旧版本的业务数据存在内存里（重启即丢），那个 `app.db`
> 里只有空的历史表、没有真实数据，**直接删掉重新迁移即可**（`rm trpg-backend/app.db`
> 再 `alembic upgrade head`）。

应用 Seed 只会创建 COC7 规则系统和 `wip` 状态的追书人目录，不会内嵌简化版
模组内容。执行固定的本地加载命令，将仓库中的追书人
ModuleContent 经过 Validation 后原子写入数据库，并把目录标记为 `ready`：

```bash
cd trpg-backend
uv run python scripts/load_paper_chase.py
```

该命令只读取
`agent-collaboration-framework/docs/module-parser/examples/module-content-validation/追书人/module-content-draft.json`。
脚本可直接在刚迁移的空数据库运行：缺少 Seed 时会先执行同一套幂等 Seed。重复
执行相同内容会返回 `unchanged`；同一版本已有不同内容时会拒绝覆盖。

追书人当前发布版本为 `1.0.3`，使用 `content_schema_version=2`；原始 `1.0.1`
归档仍可供已固定版本的房间读取。玩家可见的模组简介、推荐人数和开局页来自发布内容的
`presentation` 字段，不读取面向叙述 Agent 的 `background`；升级旧数据库后需要重新执行
上述加载命令，已有固定到旧版本的游戏不会被改写。

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
| `HOST_MODEL_PROVIDER` | `fake` | 主持模型：`fake`、`openai`、`qwen` 或 `deepseek` |
| `OPENAI_API_KEY` | 空 | `openai` 提供商的 API 密钥 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI Responses API 根地址 |
| `OPENAI_MODEL` | `gpt-5.6-luna` | OpenAI 模型名称 |
| `OPENAI_TIMEOUT_SECONDS` | `30` | OpenAI 请求超时秒数 |
| `QWEN_API_KEY` | 空 | 阿里云百炼 API 密钥 |
| `QWEN_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 千问 OpenAI 兼容接口根地址 |
| `QWEN_MODEL` | `qwen3.7-plus` | 千问模型名称 |
| `QWEN_TIMEOUT_SECONDS` | `30` | 千问请求超时秒数 |
| `DEEPSEEK_API_KEY` | 空 | DeepSeek 或其他兼容 provider 的 API 密钥 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI-compatible Chat Completions 根地址 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 模型名称 |
| `DEEPSEEK_TIMEOUT_SECONDS` | `30` | DeepSeek 请求超时秒数 |
| `MODEL_CLIENT_MAX_ATTEMPTS` | `2` | 结构化输出请求的总尝试次数（含首次），三个 provider 共用；只重试超时、连接错误、5xx 与 429。**开场叙事不适用**：它另有总预算 `OPENING_NARRATION_TIMEOUT_SECONDS`，容不下第二次尝试，该路径固定只试一次 |
| `MODEL_CLIENT_RETRY_BACKOFF_SECONDS` | `0.5` | 首次重试前的等待秒数，之后按 2 倍指数退避 |
| `CHARACTER_BACKGROUND_PROVIDER` | `deterministic` | 一键建卡装备与背景：`deterministic` 或 `deepseek`；模型失败会整体回退内置模板 |
| `HOST_SPEECH_PROVIDER` | `disabled` | 主持人语音：`disabled`、`fake` 或 `doubao`；`fake` 仅用于测试 |
| `DOUBAO_TTS_API_KEY` | 空 | 新版豆包语音控制台 API Key（按 SecretStr 读取且禁止写日志） |
| `DOUBAO_TTS_RESOURCE_ID` | `seed-tts-2.0` | DouBao TTS 2.0 固定服务标识 |
| `DOUBAO_TTS_VOICES` | `[]` | 房间允许选择的音色 JSON，如 `[{"voiceType":"...","label":"旁白"}]` |
| `DOUBAO_TTS_DEFAULT_VOICE_TYPE` | 空 | 部署默认音色，必须包含在音色白名单中 |
| `DOUBAO_TTS_TIMEOUT_SECONDS` | `15` | 单句合成超时；失败不自动重试，避免重复计费 |
| `HOST_AGENT_MAX_TURNS` | `6` | 单次 Host Agent 最大模型轮数 |
| `HOST_AGENT_MAX_TOOL_CALLS` | `8` | 单次 Host Agent 最大工具调用数 |
| `HOST_AGENT_TOOL_TIMEOUT_SECONDS` | `5` | 单工具超时秒数 |
| `HOST_AGENT_TIMEOUT_SECONDS` | `30` | Host Agent 整轮超时秒数 |
| `OPENING_NARRATION_MODE` | `model` | 权威开场生成方式：`model` 或确定性 `template` |
| `OPENING_NARRATION_TIMEOUT_SECONDS` | `10` | 开场模型生成的独立总超时秒数；失败后使用安全模板 |
| `RECENT_HISTORY_ENABLED` | `true` | 是否向 Host/Narrator 提供玩家安全的近期回合 |
| `RECENT_HISTORY_MAX_TURNS` | `6` | 近期历史最多保留的回合数 |
| `RECENT_HISTORY_MAX_CHARS` | `6000` | 近期历史文本总字符预算 |
| `CHARACTER_PORTRAIT_ENABLED` | `true` | 是否启用角色生图后端接口；前端入口默认显示 |
| `PORTRAIT_PROMPT_PROVIDER` | `deterministic` | 提示词生成：`deterministic` 或 `deepseek` |
| `PORTRAIT_IMAGE_PROVIDER` | `auto` | 图片 provider：自动选择 `sufy` / `dashscope` / `mock`，也可显式指定 |
| `DASHSCOPE_API_KEY` | 空 | 阿里云百炼 API Key；只存在后端环境变量中 |
| `DASHSCOPE_BASE_URL` | `https://dashscope.aliyuncs.com/api/v1` | 通义万相 API 根地址 |
| `DASHSCOPE_IMAGE_MODEL` | `wan2.2-t2i-flash` | 通义万相文生图模型 |
| `SUFY_API_KEY` | 空 | Sufy API Key；只存在后端环境变量中 |
| `SUFY_BASE_URL` | `https://openai.sufy.com/v1` | Sufy OpenAI-compatible API 根地址 |
| `SUFY_IMAGE_MODEL` | `google/gemini-3-pro-image` | Sufy 高质量图片生成模型 |
| `PORTRAIT_GENERATION_TIMEOUT_SECONDS` | `120` | 图片生成和任务轮询的总超时秒数 |
| `PORTRAIT_MAX_IMAGE_BYTES` | `5242880` | 持久化角色头像允许的最大原始文件字节数（默认 5 MiB） |
| `PORTRAIT_IMAGE_DOWNLOAD_TIMEOUT_SECONDS` | `15` | 下载上游临时图片的独立超时秒数 |
| `PORTRAIT_REFERENCE_IMAGE_PATH` | `app/assets/portrait-style-reference.png` | 后端内置漫画风格参考图路径；留空或不可读时使用纯提示词 |

生图入口由前端默认显示，不再配置前端环境变量。后端默认启用且使用 `auto`：依次检查 `SUFY_API_KEY` 和 `DASHSCOPE_API_KEY`，自动选择可用的真实 provider；两者都未填写时使用 mock。如需禁用后端生图，只需设置 `CHARACTER_PORTRAIT_ENABLED=false`。

生图成功后，后端会下载或解码 provider 返回的图片，使用 Pillow 校验为不超过
4096×4096 的 PNG、JPEG 或 WebP，再把当前头像二进制保存到
`character_portraits` 表。每名角色只保留一张当前头像，重新生成成功后覆盖旧图；
下载、校验或保存失败时旧图保持不变。头像进入数据库备份，角色数量较多时需要同时
评估数据库容量、备份耗时和恢复时间；需要历史图库或大规模分发时应迁移到对象存储。

### 主持模型配置

`HOST_MODEL_PROVIDER` 决定意图理解和结果叙事使用的模型路径：

| 值 | 请求方式 | 适用场景 |
| --- | --- | --- |
| `fake` | 不发送网络请求 | 默认值；本地开发、自动化测试和无密钥运行 |
| `openai` | OpenAI Responses API + 严格 JSON Schema | 使用原生支持 `text.format=json_schema` 的模型 |
| `qwen` | 千问 Chat Completions JSON Mode + 本地 Pydantic 校验 | 阿里云百炼千问 3.7 Plus |
| `deepseek` | OpenAI-compatible Chat Completions + JSON Mode + 本地 Pydantic 校验 | DeepSeek；兼容同一协议的 provider 可复用 |

无论使用哪种远程模型，模型只负责提出结构化意图或叙事候选；目标、场景、技能和事实引用仍会在应用边界重新校验，最终状态只由规则引擎修改。

#### 使用千问 3.7 Plus

1. 在[阿里云百炼控制台](https://bailian.console.aliyun.com/)创建 API Key，并取得业务空间的 `WorkspaceId`。
2. 复制本地配置文件：

   ```bash
   cd trpg-backend
   cp .env.example .env
   ```

   PowerShell 可使用：

   ```powershell
   Copy-Item .env.example .env
   ```

3. 只在本地 `.env` 中填写以下配置：

   ```dotenv
   HOST_MODEL_PROVIDER=qwen
   QWEN_API_KEY=你的百炼_API_Key
   QWEN_BASE_URL=https://你的WorkspaceId.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
   QWEN_MODEL=qwen3.7-plus
   QWEN_TIMEOUT_SECONDS=30
   ```

   新加坡地域将地址替换为：

   ```dotenv
   QWEN_BASE_URL=https://你的WorkspaceId.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1
   ```

   其他地域及最新端点以[阿里云百炼 OpenAI 兼容接口文档](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-responses)为准。`.env` 已被 Git 忽略；不要把真实密钥写入 `.env.example`、README 或提交记录。

4. 重启后端使配置生效：

   ```bash
   uv run uvicorn app.main:app --reload \
     --reload-dir app --reload-dir ../agent-collaboration-framework/collaboration_framework
   ```

健康检查只能确认后端存活，不会调用模型。请进入房间提交一次自然语言行动进行验证。
远程 provider 模式缺少 Key 时后端启动失败；Host Agent 超时、预算耗尽、非法输出或越权候选
会发送玩家安全的 `turn.failed`，规则引擎不会执行。Narrator 失败不会重跑 Host
Agent、重新掷骰或重复写入状态；使用同一 `clientActionId` 重试只会复用已提交结果。

#### 使用 DeepSeek 或兼容 provider

复制 `trpg-backend/.env.example` 为 `.env`，填写：

```dotenv
HOST_MODEL_PROVIDER=deepseek
CHARACTER_BACKGROUND_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的_API_Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_SECONDS=30
```

Host Agent 工具调用和结构化 Narrator 都使用 OpenAI-compatible Chat Completions。
其他厂商如果遵循同一协议，可复用这组配置和 adapter；使用私有协议时应新增独立
provider adapter，而不是把私有字段混入通用请求。

#### Preview 环境切换兼容 Provider

PR Preview 和 Main Preview 共用一套 Preview 专用模型配置。API key 使用 GitHub
Repository Secret，非敏感的 API 根地址和模型名使用 Repository Variables：

| GitHub 配置 | 类型 | 示例值 |
| --- | --- | --- |
| `PREVIEW_DEEPSEEK_API_KEY` | Repository Secret | 新服务商签发的 Preview 专用 key（不要写入仓库或日志） |
| `PREVIEW_DEEPSEEK_BASE_URL` | Repository Variable | `https://api.qnaigc.com/v1` |
| `PREVIEW_DEEPSEEK_MODEL` | Repository Variable | `deepseek/deepseek-v4-pro-202606` |
| `PREVIEW_SUFY_API_KEY` | Repository Secret | 与 `PREVIEW_DEEPSEEK_API_KEY` 使用同一把支持两个模型的 key |
| `PREVIEW_SUFY_BASE_URL` | Repository Variable | `https://openai.sufy.com/v1`，可留空使用默认值 |
| `PREVIEW_SUFY_IMAGE_MODEL` | Repository Variable | `google/gemini-3-pro-image`，可留空使用默认值 |

`PREVIEW_DEEPSEEK_BASE_URL` 必须是 OpenAI-compatible API 根地址，不能填完整的
`https://api.qnaigc.com/v1/chat/completions`；客户端会自行追加 `/chat/completions`。

两份 Preview workflow 遵循同一配置规则：

- key 为空时使用 `HOST_MODEL_PROVIDER=fake`，其余预览功能仍可验证；
- DeepSeek 和 Sufy key 必须成对存在；只有一套 key 时部署立即失败，避免出现半真实链路；
- 两套 key 都存在时，`DEEPSEEK_MODEL` 生成一键建卡背景并整理角色图片提示词，`SUFY_IMAGE_MODEL` 再生成图片；
- 当前推荐的两套模型分别为 `deepseek/deepseek-v4-pro-202606` 和 `google/gemini-3-pro-image`；
- DeepSeek key 非空时，其 Base URL 和模型名必须同时存在，否则部署立即失败；Sufy 的 Base URL 和模型名可留空使用上述默认值；
- 配置真实 provider 时不会静默使用代码中的旧厂商默认值；
- fork PR 不执行部署 job，也不能读取 Repository Secret。

部署服务器不会直接执行仓库中的 `docker-compose.preview.yml`，而是复制受信任的
固定模板 `~/trpg-previews/compose-template/docker-compose.yml`。模板中的 backend
service 必须透传相同配置。两份 workflow 会在拉取镜像前检查这个变量已经解析为
期望值；模板未更新时部署会明确失败，不会误把预览标成已启用模型：

```yaml
environment:
  HOST_MODEL_PROVIDER: ${HOST_MODEL_PROVIDER:-fake}
  DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}
  DEEPSEEK_BASE_URL: ${DEEPSEEK_BASE_URL:-https://api.qnaigc.com/v1}
  DEEPSEEK_MODEL: ${DEEPSEEK_MODEL:-deepseek/deepseek-v4-pro-202606}
  CHARACTER_BACKGROUND_PROVIDER: ${CHARACTER_BACKGROUND_PROVIDER:-deterministic}
  CHARACTER_PORTRAIT_ENABLED: ${CHARACTER_PORTRAIT_ENABLED:-true}
  PORTRAIT_PROMPT_PROVIDER: ${PORTRAIT_PROMPT_PROVIDER:-deterministic}
  PORTRAIT_IMAGE_PROVIDER: ${PORTRAIT_IMAGE_PROVIDER:-mock}
  SUFY_API_KEY: ${SUFY_API_KEY:-}
  SUFY_BASE_URL: ${SUFY_BASE_URL:-https://openai.sufy.com/v1}
  SUFY_IMAGE_MODEL: ${SUFY_IMAGE_MODEL:-google/gemini-3-pro-image}
  PORTRAIT_REFERENCE_IMAGE_PATH: ${PORTRAIT_REFERENCE_IMAGE_PATH:-app/assets/portrait-style-reference.png}
  PORTRAIT_GENERATION_TIMEOUT_SECONDS: ${PORTRAIT_GENERATION_TIMEOUT_SECONDS:-120}
```

切换或轮换服务商时按以下顺序操作，避免 workflow 已更新但外部配置尚未就绪：

1. 先更新服务器固定 compose 模板，确认 `DEEPSEEK_*`、`SUFY_*` 和 `PORTRAIT_*` 环境变量都会进入 backend。
2. 在主仓库创建或更新 `PREVIEW_DEEPSEEK_BASE_URL`、`PREVIEW_DEEPSEEK_MODEL`、`PREVIEW_SUFY_BASE_URL` 和 `PREVIEW_SUFY_IMAGE_MODEL`。
3. 新建 `PREVIEW_SUFY_API_KEY`，其值暂时复用 `PREVIEW_DEEPSEEK_API_KEY`；两套 Secret 按用途分别映射。
4. 合并 workflow 改动后重新运行 Main Preview，并用同仓库测试 PR 验证 PR Preview。
5. 在两个预览环境各完成一次自然语言行动和一次角色生图，确认 DeepSeek v4 Pro 与 Sufy Gemini 都返回真实结果。

健康检查只证明容器和 HTTP 服务可用，不会产生计费模型请求，也不能证明模型配置
正确。真实验证必须覆盖一次 Host Agent 工具调用和最终结构化输出。轮换期间不要在
Issue、PR、Actions 参数或服务器命令历史中粘贴明文 key。

公共 WebSocket 只发送安全进度：`turn.started`、`turn.phase_changed`、
`tool.started`、`tool.completed`、`turn.failed` 和 `view.updated`。内部 call id、
工具参数/结果、Prompt、raw model output、reasoning、异常栈和模组秘密不会进入浏览器。

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

`.github/workflows/` 下有多个互相独立的 workflow，各自按路径过滤器触发，只有
真正改到对应目录才会跑：

| Workflow | 触发路径 | 检查内容 |
| --- | --- | --- |
| `trpg-backend-ci.yml`（Backend CI） | `trpg-backend/**`；另外 `trpg-sdk/scripts/generate-types.ts` 和 `trpg-sdk/src/generated/**` 也会触发（见下） | `ruff check`、`ruff format --check`、`ty check`、`pytest`；另有 `codegen-drift` job：重新跑一遍 DTO → JSON Schema → TS 生成管线，用 `git diff` 确认 `trpg-sdk/src/generated/` 跟提交的一致，不一致就报错 |
| `trpg-sdk-ci.yml`（SDK CI） | `trpg-sdk/**` | `npm run lint`、`npm run typecheck`、`npm run build` |
| `trpg-frontend-ci.yml`（Frontend CI） | `trpg-frontend/**` | `npm run lint`、`npm run build` |
| `pr-preview.yml`（PR Preview） | PR 打开、更新、重开、关闭 | 部署或回收 PR 专属预览环境 |
| `main-preview.yml`（Main Preview） | PR 合并到 `main` | 更新固定端口的持久预览环境 |

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

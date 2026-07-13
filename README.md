# TRPG-master

## 环境变量

后端和前端各有一份 `.env.example`（`./` 和 `trpg-app/`），复制成 `.env` 并填入真实值：

```bash
cp .env.example .env               # 后端：填 DATABASE_URL 密码 + DEEPSEEK_API_KEY
cp trpg-app/.env.example trpg-app/.env   # 前端：本地开发一般不用改
```

`.env` 不提交 git，密码/API Key 找项目负责人要。

## 数据库（共用服务器）

Postgres 跑在共用服务器上的 Docker 容器里，只绑 `127.0.0.1`，不对公网暴露。本地开发前先起一条 SSH 隧道（服务器地址/端口找项目负责人要）：

```bash
ssh -p <SSH端口> -N -L 5433:127.0.0.1:5432 <你的服务器账号>@<服务器地址>
```

这条隧道要在开发期间一直保持连接（也可以配成 launchd/systemd 常驻服务，不用每次手动开）。隧道通了之后 `.env` 里的 `DATABASE_URL`（`postgresql+asyncpg://aidm:<密码>@localhost:5433/aidm`）就能连上。

## 后端开发环境（`packages/`）

依赖用 [uv](https://docs.astral.sh/uv/) 管理，`uv.lock` 已提交，保证团队成员安装到完全一致的版本。

```bash
uv sync              # 创建 .venv 并按 uv.lock 安装依赖
uv run alembic upgrade head                # 建表/跑迁移（第一次跑或有新迁移时）
uv run uvicorn server.main:app --reload    # 启动开发服务器（默认 http://localhost:8000）
```

新增/升级依赖用 `uv add <package>`（会自动更新 pyproject.toml 和 uv.lock），不要手改版本号后忘记锁定。

## 前端开发环境（`trpg-app/`）

```bash
cd trpg-app
npm install
npm run dev           # 默认 http://localhost:9877，需要后端(8000)同时跑着
```


# syntax=docker/dockerfile:1
#
# CI Preview 用（issue #200）。构建上下文必须是**仓库根目录**，不是
# trpg-backend/ 自己——trpg-backend/pyproject.toml 的 [tool.uv.sources] 把
# agent-collaboration-framework 声明成 `path = "../agent-collaboration-framework"`
# 的本地依赖（同时 load_paper_chase.py 也要读它的 docs/module-parser/examples/
# 下的模组草稿数据），两个目录必须以同样的相对布局一起拷进镜像，`uv sync` 才能
# 解出这个依赖。
FROM python:3.13-slim AS runtime

# uv 官方发布的镜像里已经打包好 uv/uvx 二进制，直接复制过来用，不用另装。
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

WORKDIR /workspace

COPY agent-collaboration-framework/ ./agent-collaboration-framework/
COPY trpg-backend/ ./trpg-backend/

WORKDIR /workspace/trpg-backend

# --locked：和 CI（trpg-backend-ci.yml）用的选项一致——uv.lock 与 pyproject.toml
# 对不上时直接报错，而不是静默装一个不一致的版本。--no-dev：预览镜像不需要
# ruff/ty/pytest 这些开发期工具，保持镜像精简。
RUN uv sync --locked --no-dev

# `uv run` 默认每次都会重新核对/同步依赖环境（不管前面是不是已经 sync 过），
# 这在容器运行时是双重问题：①entrypoint 里连续三次 `uv run` 会重新装一遍
# --no-dev 排除掉的 pytest/ruff 等开发依赖，白白抵消上面 --no-dev 的效果；
# ②容器运行时不一定有出网权限（本来就不需要，构建时已经把依赖全装进
# venv 了），一旦没网这个隐式 sync 会直接连接失败，把整个容器启动搞挂
# （实测复现：`uv run alembic` 卡在下载 pytest/pygments，DNS 解析失败）。
# UV_NO_SYNC=1 让所有 `uv run` 完全不碰 venv 同步这一步，直接用构建时已经
# 装好的环境跑。注意不是 UV_FROZEN——那个只是"不更新 uv.lock 文件"，命中
# 同一个 bug 时同样会去下 dev 依赖，实测验证过仍会失败。
ENV UV_NO_SYNC=1

EXPOSE 8000

RUN chmod +x docker-entrypoint.sh

ENTRYPOINT ["./docker-entrypoint.sh"]

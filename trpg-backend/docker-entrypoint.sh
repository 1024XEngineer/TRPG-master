#!/bin/sh
# CI Preview 容器启动入口（issue #200）。顺序对应 README「启动后端」一节的
# 手动步骤：迁移建表 → 发布全部内置模组种子 → 起服务。加载脚本是
# 幂等的（重复执行返回 unchanged），每次容器启动重跑一次
# 没有副作用，不需要额外判断"是不是第一次启动"。
set -e

uv run alembic upgrade head
uv run python scripts/load_builtin_modules.py
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

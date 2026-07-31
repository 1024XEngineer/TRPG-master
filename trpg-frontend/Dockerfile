# syntax=docker/dockerfile:1
#
# CI Preview 用（issue #200）。构建上下文必须是**仓库根目录**——
# trpg-frontend 通过 `file:../trpg-sdk` 引用 SDK（README「构建 SDK」一节：
# "前端通过 file:../trpg-sdk 引用 SDK，因此首次启动前需要先生成 dist"），
# 必须先把 trpg-sdk build 出 dist/，再给前端 npm ci。

FROM node:22-slim AS sdk-build
WORKDIR /workspace/trpg-sdk
COPY trpg-sdk/package.json trpg-sdk/package-lock.json ./
RUN npm ci
COPY trpg-sdk/ ./
RUN npm run build

FROM node:22-slim AS frontend-build
WORKDIR /workspace/trpg-sdk
COPY --from=sdk-build /workspace/trpg-sdk ./
WORKDIR /workspace/trpg-frontend
COPY trpg-frontend/package.json trpg-frontend/package-lock.json ./
RUN npm ci
COPY trpg-frontend/ ./
# 相对路径：/api、/ws 由本容器自己的 Caddy 同源反代到 backend（见同目录
# Caddyfile）。VITE_ 变量是构建期打进静态产物的，用相对路径就不需要在构建
# 镜像时预先知道这个 PR 最终会被分配到哪个外部端口——构建和部署解耦。
# WebSocket 端走 trpg-sdk 的 deriveWsBaseUrl()，对相对路径会退化成
# `/ws/{roomId}`，浏览器原生支持 WebSocket 构造函数传相对 URL（按当前页面
# origin 解析），不需要额外处理。
ENV VITE_API_BASE_URL=/api/v1
RUN npm run build

FROM caddy:2-alpine AS runtime
COPY trpg-frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend-build /workspace/trpg-frontend/dist /srv
EXPOSE 80

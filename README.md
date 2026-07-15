<p align="center">
  <img src="https://img.shields.io/badge/milestone-MS1-brass?style=flat-square" />
  <img src="https://img.shields.io/badge/rules-CoC_7th-darkred?style=flat-square" />
  <img src="https://img.shields.io/badge/frontend-React_19_|_TypeScript-61dafb?style=flat-square" />
  <img src="https://img.shields.io/badge/backend-FastAPI_|_Python-teal?style=flat-square" />
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" />
</p>

# 🎲 TRPG-master

> **有人就能跑。** AI 担任守秘人，多人联机，打开手机就能跑一把克苏鲁的呼唤。

TRPG-master 是一个手机端多人跑团应用。用大模型替代真人 KP（守秘人），解决跑团圈最大的痛点——**想玩，但没人愿意当主持人。**

规则引擎硬编码执行 D100 检定和 SAN 机制，保证骰子公平可验证。AI 只负责叙事和氛围——他不碰骰子。

---

## 进度

**MS1 / 第 1–2 周** — 方向锁定，并行开发中。

```
产品方向 ✅ ── 战略决策文档 + 产品提案 + 三个窄提案
原型设计 ✅ ── 纯 HTML 交互原型 + 前端 7 屏 React 应用
架构设计 🚧 ── Schema 设计 + 四层数据模型 + 动态规则引擎
后端开发 ⬜ ── FastAPI 骨架
联调贯通 ⬜ ── 首尾可跑版本
```

---

## 团队

| 成员 | GitHub |
|------|--------|
| 高俊周 (GJZ) | [@WELT5350](https://github.com/WELT5350) |
| 凌铭辉 (LMH) | [@LMH168](https://github.com/LMH168) |
| 李敏譞 (LMX) | [@Ximaohu-LMX](https://github.com/Ximaohu-LMX) |
| 张家豪 (ZJH) | [@JoshuaZ16](https://github.com/JoshuaZ16) |
| 黄女珊 (HNS) | [@badadal](https://github.com/badadal) |
| 卢玮晨 (LWC) | [@Lyltrum](https://github.com/Lyltrum) |
| 曹明鸣 | [@mingmingtsao](https://github.com/mingmingtsao) |

---

## 三个核心决策

**1. 规则引擎硬编码**

D100 六档检定（大成功 → 大失败）、SAN 机制、衍生属性——全部在后端代码中确定执行。AI 只建议"是否需要检定"，不碰判定的骰子。

**2. AI 输出结构化 JSON**

```json
{
  "narration": "走廊尽头的门缓缓打开...",
  "skill_check": { "skill": "spot-hidden", "difficulty": "normal", "target": 50 },
  "san_change": { "loss": "1d3" },
  "private_info": { "targetPlayer": "player-2", "content": "你注意到墙上有一行血字..." },
  "suggestions": ["调查门后的房间", "检查墙上的划痕"]
}
```

叙事与规则解耦。AI 不能直接宣布"你成功了"——结果由引擎裁定后广播。

**3. 云端 LLM 叙事**

调用大模型 API 生成中文 CoC 恐怖叙事。多轮对话上下文管理（最近 6 轮 + 当前场景 + 角色状态 + 已获线索）。

---

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React 19 · TypeScript · Vite 8 · Tailwind CSS 3 · Zustand · React Router 7 |
| 后端 | Python FastAPI（计划） |
| AI | 云端 LLM API（待选定：DeepSeek / Claude） |
| 数据库 | PostgreSQL（计划） |
| PWA | vite-plugin-pwa |

---

## 快速开始

```bash
# 后端
cd backend
cp .env.example .env
uv sync
uv run uvicorn app.main:app --reload   # → http://127.0.0.1:8000，本地默认开启 /docs

# SDK（前端依赖它调用后端，需先构建一次）
cd sdk
npm install
npm run build

# 前端
cd trpg-app
cp .env.example .env
npm install
npm run dev        # → http://localhost:9877
```

---

## 路线图

| 里程碑 | 时间 | 目标 |
|--------|------|------|
| **MS1** | 第 1–2 周 | 方向锁定 + 架构骨架 + 首尾可跑版本 |
| **MS2** | 第 3–4 周 | MVP 深化：AI 叙事集成 + 真实后端 |
| **MS3** | 第 5–6 周 | 功能闭环：多人在线 + 语音输入 + 好友系统 |
| **MS4** | 第 7–8 周 | 打磨、交付、发布 |

---

## 许可

MIT · [1024 XEngineer Camp](https://github.com/1024XEngineer) Season 6

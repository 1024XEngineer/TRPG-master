# 🦑 Arkham Case Files — AI 守秘人

AI 驱动的克苏鲁的呼唤（CoC 7th）多人跑团主持人。手机端 React Native 应用，AI 担任守秘人，玩家用手机加入房间，即开即玩。

## 这是什么

传统的 CoC 跑团需要一个真人守秘人（KP）——读规则书、准备模组、即兴叙事、执行检定。大多数想玩的人找不到 KP。

Arkham Case Files 用 AI 解决这个问题：玩家打开 App 进入房间，AI 自动主持游戏——推进剧情、执行 D100 检定、管理 SAN 值变化、分发私密线索。

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | React Native（TypeScript） |
| 后端 | Python FastAPI |
| AI | DeepSeek / Claude（待评估） |
| 规则引擎 | CoC 7th，硬编码 + RAG 检索 |

## 开发状态

> 🚧 **MS1（第 1-2 周）**：产品提案草案 + 架构骨架

- [x] 产品提案初稿
- [ ] 架构骨架入库
- [ ] 前端概念原型 → React Native 重建
- [ ] AI 模型调研与选型

## 团队

6 人 · 1024 Techcamp 第 6 期 · 2026 年 7–8 月

## 许可

MIT

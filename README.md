# TRPG-master

> AI 担任守秘人 · 手机端多人克苏鲁的呼唤跑团

用大模型替代真人 KP，让 3-5 人的小团体打开手机就能跑一局 CoC。规则引擎硬编码执行 D100 检定，AI 不碰骰子。

---

## MS1 状态

**第 1-2 周 · 战略决策 + 首尾可跑版本**

| 模块 | 状态 |
|------|:--:|
| 战略决策文档 | ✅ |
| 产品提案 FullSpec | ✅ |
| 窄提案 ×3（规则引擎 / AI 输出 / AI 叙事） | ✅ |
| API 契约文档 | ✅ |
| 前端 10 屏原型（React 19 + Vite） | ✅ |
| 后端骨架（FastAPI + DeepSeek 集成） | ✅ |
| 前后端联调贯通 | ✅ |
| 路演准备 | 🚧 |

---

## 仓库导航

| 位置 | 内容 |
|------|------|
| 本分支 `GJZ-1-Folder` | 产品文档、API 契约、工程规范 |
| `LMH-1-Folder` | 前端 React 应用 |
| `LWC-1-Folder` | 后端 FastAPI + AI 编排 |

---

## 产品文档

| 文档 | 说明 |
|------|------|
| [战略决策 v1.0](战略决策-产品方向与范围-v1.0.md) | 动机、目标用户、竞品分析、范围边界 |
| [产品提案 v1.0](产品提案-v1.0.md) | 关键决策、数据模型、规则引擎、AI 交互、验收标准 |
| [API 契约](docs/api-contract.md) | 反向分析前端生成的接口规范 |
| [规则引擎提案](docs/proposals/proposal-01-规则引擎.md) | D100 检定 / SAN 机制 |
| [AI 输出格式提案](docs/proposals/proposal-02-AI输出格式.md) | 结构化 JSON vs 自由文本 |
| [AI 叙事方案提案](docs/proposals/proposal-03-AI叙事方案.md) | 云端 LLM vs 本地 vs 无 AI |

---

## 团队

高俊周 (GJZ) · 凌铭辉 (LMH) · 李敏譞 (LMX) · 张家豪 (ZJH) · 黄女珊 (HNS) · 卢玮晨 (LWC) · 曹明鸣（导师）

1024 XEngineer Camp · Season 6 · MIT

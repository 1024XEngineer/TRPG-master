# Proposal #2：AI 输出格式 —— 结构化 JSON vs 自由文本

状态：draft（proposal / MiniSpec）

日期：2026-07-10

作者：高俊周

依赖：Proposal #1（硬编码规则引擎必须先确定）

---

## 动机 / 用户故事

如果 AI 用自然语言自由发挥——"你成功了！投出了极限成功！"——那么规则引擎就形同虚设。AI 不能拥有宣布检定结果的权力。

本决策确定 AI 与规则引擎之间的**接口契约**：AI 怎么告诉后端"需要检定"、后端怎么接收和裁定。

## 目标用户

后端开发者、AI Prompt 工程师。这份契约决定了系统各层的边界。

## 现有做法及其不足

| 方案 | 不足 |
|------|------|
| 自由文本 | AI 可能直接宣布"你成功了"，违规；解析 fragile，边界 case 多；无法保证 AI 不越权 |
| 结构化 JSON | 需要 prompt 工程约束 AI 输出格式，增加 prompt 复杂度 |

## 关键决策与依据

| 方案 | 描述 | 优劣 |
|------|------|------|
| **A. 结构化 JSON（选中）** | AI 返回 `{narration, skill_check, san_change, private_info, suggestions}` | ✅ 叙事与规则解耦、后端可拦截非法检定 ❌ prompt 复杂度高 |
| B. 自由文本 + 后解析 | AI 返回自然语言，后端用正则提取检定指令 | ✅ prompt 简单 ❌ 解析脆弱、易遗漏 |

**选择 A 的依据：** Proposal #1 决定规则引擎硬编码，结构化的接口是这个解耦成立的前提。没有这套 JSON schema，AI 就可以绕过引擎直接宣布结果。

## AI 响应格式

```json
{
  "narration": "铁门在生锈的铰链上发出一声刺耳的呻吟…",
  "skill_check": {
    "triggered": true,
    "skill": "spot_hidden",
    "skill_name": "侦察",
    "target": 65,
    "reason": "你注意到脚印的排列有些奇怪"
  },
  "san_change": null,
  "private_info": [
    {"player": "p1", "content": "你在门框缝隙发现了一片灰色布料"}
  ],
  "suggestions": ["检查脚印", "进入会客室", "上楼"]
}
```

## AI 交互上下文

每次请求发给 AI：
- 玩家输入
- 当前场景（地点、时间、在场 NPC）
- 角色状态（HP / SAN / 持有物品）
- 最近 6 轮对话历史
- 已获取的线索摘要

## 验收标准

- [ ] AI 返回的 JSON 可被后端成功解析，5 个字段均存在
- [ ] `skill_check.target` 不带判定结果——AI 只能建议，不能宣布
- [ ] 端到端流程验证通过（AI → JSON → 规则引擎 → 玩家投骰 → 结果广播）
- [ ] 公共叙事与私密信息分别推送到正确目标

# 《常暗之厢》ModuleContentV3 审查报告

## 发布身份与来源

- `module_id`: `constant-darkness-box-zh-coc7`
- `version`: `3.0.1`
- `world_ref`: `coc-7e`
- 原作：86式《常闇の箱》
- 6 版繁体翻译：lordcj（CJ）
- 简体化、7 版转化及修正：zuo死菌
- 权威输入：桌面 `示例模组/常暗之厢（7版规则，简体修正版）(1).pdf`，共 17 页

## Phase A：原文状态机

`6号车厢醒来与便签 → 5号车厢次日报纸 → 4号车厢乘务员证词 → 3号车厢黑包钥匙 → 2号车厢潜行/声响分支 → 先头车厢与驾驶室 → 加速 A / 减速 B / 午夜被吞噬 C`

修正版明确把事件解释为超自然共同梦境，并把追逐大嘴设定为奈亚化身。公开背景只保留 2013 年末班电车、开局车厢、无信号和窗外黑暗；上述真相均在受控 Information 中。

## Runtime capability mapping

| 原文机制 | 映射 | 说明 |
| --- | --- | --- |
| 顺序车厢、锁门、驾驶室 | native | `Location` + 有向 `location_edges` + gated access point |
| 便签、报纸、证词、钥匙、操作知识 | native | `Information`、状态条件与 `reveal_information` |
| 取回黑包、乘务员随行 | native | 黑包 `move_entity` + 独立 `retrieved/present` 状态；随行由引擎保留键 `accompanying` 驱动 |
| 2 号车厢潜行 | native | 主动 `coc7.skill` 检定，所有成功等级显式路由 |
| 制造更大声响引开循声者 | lowerable | 原文规定此法自动成功，压成一次原子规则 |
| 每车厢 3–4 次行动限制 | lowerable | 无行动计数器；降为 23:00→次日 00:00 的 `time.point_entered` 终点 |
| 肢体/大嘴 SAN 检定 | adjudicated | `coc7.sanity` 会真实发起检定，但当前不会扣 SAN |
| 自由战斗、两轮对抗与 1d3 敌人数 | unsupported | 不生成胜利、死亡、控制或随机数量状态 |
| 氛围文字与非权威恐怖描写 | narrative_only | 仅由 Narrator 基于已提交事实表现，不能改变世界状态 |

## Phase B：结构设计

- hierarchy：`dream_train` 与 `reality_after_dream` 仅作 UI/语义父节点，不进入 travel graph。
- travel graph：6→5→4→3 是普通前进；6→7、3→2→先头车厢、先头车厢→驾驶室均有真实边界。
- 2 号车厢不是普通 travel：潜行成功或制造声响规则先提交 `crossing_resolved`，随后同一原子序列 `enter_location(lead_car)`。
- 黑包是 Canon portable item；取得时真实进入行动者 inventory，不用台词代替持有状态。
- 乘务员的 `awake`、`accompanying`、`present`、`maw_believed`、`allows_acceleration` 分开保存；`accompanying` 是引擎保留键，为真时由 `enter_location` 把他带到队伍实际到达的地点，模组不再逐个目的地手工同步。
- A/B/C 各提交唯一 `train_chase.outcome`、结果 Information、`mark_core_resolved`、`set_ending_availability` 和结局场景迁移。所有分支以 `outcome=none && core_resolved=false` 互斥。
- 午夜 C 由世界时间进入 D1 00:00 自动触发，并以 `deadline_reached` 和 `outcome` 保证重放幂等。

## Essential Information 安全性

- 便签背面可通过明确翻面动作无检定取得。
- 报纸日期、急救、黑包搜索、潜行等检定失败均不写成功状态，也不关闭候选，可重试。
- 黑包另有“乘务员同行自动找到 + 说服交付”路径。
- 2 号车厢潜行失败会开放原文明确的制造声响恢复路径。
- 控制杆说明在面板解锁后通过确定性观察取得。

## Capability gaps

1. Runtime 没有按行动/车厢计数的 deadline；一小时时间终点是公开记录的 lowering。
2. 主动检定没有原文的 ±5/±10/±20 百分比修正、半值幸运或照明加值。
3. 没有通用对抗检定、自由战斗轮、敌人数骰或按敌人数改变 STR 结果的能力。
4. 条件谓词不能读取 Actor STR/CON 阈值，故搬运一律 lower 为一次 regular STR 检定，不能只对低于 70 的角色要求掷骰。
5. `coc7.sanity` profile 识别损失参数但不写 Actor SAN；结局禁止 Narrator 宣称 Runtime 已提交精确 SAN 变化。
6. 作者规则的 `holder_actor_id` 不能绑定当前行动者，NPC custody 也不存在；黑包因此保存 `retrieved/carried` 并在每次已知场景迁移时真实 `move_entity`，但不会伪称已进入动态调查员 inventory。
7. 自然中文到 `agent_match` 的语义选择由 Host Agent 完成；Engine 只确定性强制地点、目标、when、rule_id 与 option_id。

## 来源覆盖

| 对象 | 数量 | 已映射 |
| --- | ---: | ---: |
| Location | 12 | 12 |
| Information | 22 | 22 |
| Rule | 28 | 28 |
| KnowledgeGoal | 3 | 3 |
| EndingAnchor | 3 | 3 |

## 秘密隔离

- `presentation` 与 `background` 不含共同梦境、奈亚、大嘴、循声者弱点、钥匙位置或结局答案。
- Keeper 真相只在 `keeper_content`、keeper 实体名或条件未满足的 Canon 节点中。
- 未揭示 Information 不进入 PlayerView；隐藏结局地点只在对应 outcome 提交后通过 concealed edge 可达。

## 自动验证入口

- 生成脚本内置 `ModuleContentV3.model_validate`、`validate_module_v3`、`audit_runtime_capabilities`。
- `tests/test_constant_darkness_box_v3_fixture.py` 覆盖来源、秘密、候选边界、失败重试、时间事件、NPC/物品移动、三结局、互斥性、中文 hints 与开局投影。

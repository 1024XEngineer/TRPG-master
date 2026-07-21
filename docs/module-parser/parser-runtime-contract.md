# Parser Agent 运行时交付契约

本文明确模组解析 Agent 必须产出什么，才能让规则引擎、AI 主持和游戏编排器正常运行。《追书人》的具体解析结果见 [`paper-chase/module-draft.json`](paper-chase/module-draft.json)。

## 1. 交付边界

Parser Agent 可以产生多个审计和审查产物，但运行时只加载审核通过的 `ModuleContent`：

| 消费方 | 从 `ModuleContent` 读取什么 | 不应读取什么 |
|---|---|---|
| AI 主持 | 场景描述、秘密事实、NPC 知识/目标/行为、线索、叙事结果、资源解锁条件 | 原始 PDF、未解决的解析推断 |
| 规则引擎 | 规则版本、角色数值、检定、理智事件、条件、效果、触发器、结局判定 | 自然语言剧情段落、模型置信度 |
| 游戏编排器 | 当前场景、稳定 ID、引用关系、可见性、入口和转场、初始状态 | 无结构的规则描述 |

Parser Agent 的职责是把原文转换成三类数据：

```text
叙事数据：告诉 AI 主持“知道什么、能说什么、人物如何行动”
规则数据：告诉规则引擎“何时判定、如何计算、产生什么效果”
编排数据：告诉系统“对象如何引用、场景如何连接、状态如何变化”
```

## 2. `ModuleContent` 必需结构

以下是 Parser Agent 最终应交付的最小结构。字段名可以随首版 Schema 调整，但语义不能缺失。

```json
{
  "schema_version": "1.0.0",
  "module_id": "paper-chase-zh-coc7",
  "metadata": {},
  "ruleset_ref": {},
  "keeper_brief": {},
  "facts": [],
  "scenes": [],
  "entities": [],
  "clues": [],
  "checkpoints": [],
  "sanity_events": [],
  "triggers": [],
  "endings": [],
  "assets": [],
  "initial_state": {}
}
```

| 部分 | 必需内容 | 主要消费者 |
|---|---|---|
| `metadata` | 标题、作者、人数、时长、语言、题材和无剧透简介 | 产品、AI 主持 |
| `ruleset_ref` | `system_id`、规则版本、技能/属性目录版本 | 规则引擎 |
| `keeper_brief` | 核心真相、主持目标、主题、基调、禁止误读项 | AI 主持 |
| `facts` | 稳定 ID、事实内容、可见性、获知条件 | AI 主持 |
| `scenes` | 稳定 ID、公开描述、Keeper 说明、参与实体、可用线索/检定、入口和转场 | AI 主持、编排器 |
| `entities` | 类型、公开/秘密描述、知识边界、目标、行为、初始状态、可选数值 | AI 主持、规则引擎 |
| `clues` | 摘要、重要级别、可见性、来源、揭示事实、获得效果 | AI 主持、编排器 |
| `checkpoints` | 场景、技能、难度、前置条件、重复规则、成本及各结果效果 | 规则引擎 |
| `sanity_events` | 触发条件、成功/失败损失、上限、附加效果 | 规则引擎 |
| `triggers` | 事件名、条件、优先级、效果、是否只执行一次 | 规则引擎、编排器 |
| `endings` | 条件、优先级、结构化结果、玩家摘要、Keeper 摘要 | 规则引擎、AI 主持 |
| `assets` | 资源键、类型、用途、解锁条件 | AI 主持、前端 |
| `initial_state` | 入口场景、NPC/物品/地点状态、初始线索和计时器 | 编排器、规则引擎 |

所有可被引用的对象必须有稳定 ID。秘密内容必须有明确可见性，例如 `public`、`keeper_only` 或带条件的 `locked`，不能依靠字段位置猜测。

## 3. AI 主持需要的内容

AI 主持需要的不只是剧情摘要，还需要防止幻觉和剧透的边界：

```text
Scene
- public_description：当前可以直接描述给玩家的内容
- keeper_notes：仅主持可见的场景真相
- available_entity_ids：当前可交互对象
- available_clue_ids：本场景可能获得的线索
- checkpoint_ids：可能触发的规则检定
- next_scene_ids：允许进入的后续场景

NPC Entity
- public_description / keeper_description
- knowledge_fact_ids / knowledge_clue_ids
- goals
- behavior.default_attitude
- behavior.will_not_initiate_combat
- behavior.conversation_constraints
- speech_style

Clue
- visibility
- reveals_fact_ids
- acquisition_conditions
- player_facing_text
- keeper_explanation
```

AI 主持只能根据当前状态检索可用场景和信息，不能直接把完整 Keeper 真相放进玩家上下文。

## 4. 规则引擎需要的内容

规则引擎不理解模糊叙事，每条可执行规则必须结构化。以检定为例：

```json
{
  "id": "check.search_study",
  "scene_id": "scene.kimball_house",
  "skills": ["spot_hidden"],
  "difficulty": "regular",
  "prerequisites": [],
  "repeat": null,
  "costs": [{"type": "time", "value": "1 day"}],
  "outcomes": {
    "success": [
      {"type": "set_state", "path": "object.douglas_diary.found", "value": true},
      {"type": "grant_clue", "clue_id": "clue.diary_decision"}
    ],
    "failure": [],
    "fumble": []
  }
}
```

技能必须使用规则系统的规范 ID，例如 `spot_hidden`，不能只保存“进行一次侦察”这样的自然语言。Condition 和 Effect 也必须来自受控类型集合，例如：

```text
Condition：state_eq、clue_owned、scene_is、player_choice、check_result
Effect：set_state、grant_clue、request_check、request_san_check、damage、transition、trigger_ending
```

模组可以引用规则，但不能在每个模组里重新定义骰点和成功等级算法。`ruleset_ref` 应指向规则引擎已有的 CoC7、DND 等规则适配器。

## 5. 规则引擎调用边界

AI 主持负责把玩家自然语言转换为候选行动，游戏编排器负责校验，规则引擎负责执行：

```text
玩家行动
  -> AI 主持提出 action/checkpoint_id
  -> 编排器检查当前场景、权限和 prerequisites
  -> 规则引擎执行检定、Condition 和 Effect
  -> 状态提交成功
  -> AI 主持根据结构化结果生成叙事
```

以下情况由编排器自动调用规则引擎，不依赖 AI 自由判断：

- 已触发的 `sanity_event`；
- 状态变化命中的 `trigger`；
- 战斗轮次、伤害和持续效果；
- 状态满足的结局检查。

纯对话和没有规则后果的环境描述不调用规则引擎。AI 主持不能修改骰点、绕过前置条件或自行应用状态效果。

## 6. Parser Agent 验收清单

- [ ] 产出 `SourceManifest`、`ModuleDraft`、`ValidationReport` 和 `ModuleContentCandidate`；
- [ ] 每个 Scene、Entity、Clue、Checkpoint、Trigger 和 Ending 有唯一稳定 ID；
- [ ] 所有对象引用均存在，不使用仅靠名称匹配的关联；
- [ ] 玩家信息、Keeper 秘密和条件解锁信息有明确可见性；
- [ ] NPC 有知识边界、目标和关键行为约束；
- [ ] 每个关键事实至少有来源页码或章节；
- [ ] 每个检定有技能、难度、前置条件和各结果效果；
- [ ] 每个 Condition、Effect 和技能使用受控类型或规则系统规范 ID；
- [ ] 核心线索存在可达路径，失败不会无意中永久锁死主线；
- [ ] Trigger 不会无限循环，结局优先级不存在冲突；
- [ ] 所有无法确定的解释进入 `review_items`，没有被模型静默补全；
- [ ] 审查通过后生成不可变 `ModuleContent`，Runtime 不加载 Draft。

## 7. 《追书人》当前 Draft 的差距

当前 Draft 已包含场景、实体、线索、检定、理智事件、触发器、结局、资源、来源引用和人工问题，可以作为 Parser Agent 的黄金样例。

正式冻结 Schema 前仍需补齐或统一：

- 独立的 `keeper_brief` 和主持禁止误读项；
- Scene/Clue 的统一可见性和玩家侧文案字段；
- 聚合后的 `initial_state`；
- Condition、Effect、技能和事件类型注册表；
- `failure/fumble` 等完整检定结果结构；
- Trigger 的优先级、一次性执行和幂等语义；
- `ruleset_ref` 与后端规则目录的自动校验。

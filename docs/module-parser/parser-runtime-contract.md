# Module Parser Agent 产物契约

工作项：[Issue #98](https://github.com/1024XEngineer/TRPG-master/issues/98)

黄金样例：[`paper-chase/module-package.json`](paper-chase/module-package.json)

框架评审：[`module-package-review.md`](module-package-review.md)

## 1. 核心结论

`ModuleDraft` 只存在于 Agent 内部过程。正式导入只有两种结果：

```text
ready  -> 输出可直接运行的 ModulePackage 1.1
failed -> 不创建可运行模组，返回结构化错误
```

玩家不负责审核解析结果。Agent 必须自动完成归一化、交叉检查、规则校验和有限次数修复；无法安全解决的 blocker 应使导入失败。

## 2. 完整产物链

### 2.1 内部产物

| 产物 | 内容 |
|---|---|
| `SourceManifest` | 文件哈希、文档分段、页码、语言、权利声明和提取质量 |
| `ExtractedDocument` | 文本块、章节、表格、图片、地图标签、OCR 和版面信息 |
| `ModuleDraft` | 第一次结构化结果，可带置信度和待修复诊断 |
| `ValidationReport` | Schema、引用、规则、可见性、可达性、时间线和循环检查 |
| `RepairTrace` | 自动修复前后差异、策略、模型和重试次数 |

这些产物可以进入 `module_import_artifacts`，但不被游戏运行时加载。

### 2.2 正式产物

`ModulePackage` 是唯一正式交付物，必须满足：

- `package_schema_version = 1.1.0`；
- `package_status = ready`；
- 不包含开放问题或占位符；
- 固定规则系统及版本；
- 文档分段、来源引用和权利状态完整；
- 具有可创建游戏的初始状态；
- 通过 Schema、引用和规则能力校验；
- 发布后不可原地修改，修改必须创建新 revision。

## 3. 顶层结构

```json
{
  "package_schema_version": "1.1.0",
  "package_id": "module-package.paper-chase-zh-coc7.v2",
  "package_status": "ready",
  "source_manifest": {},
  "module": {},
  "keeper_brief": {},
  "runtime_defaults": {},
  "content": {
    "facts": [],
    "scenes": [],
    "locations": [],
    "entities": [],
    "characters": [],
    "resources": [],
    "clues": [],
    "checkpoints": [],
    "sanity_events": [],
    "timelines": [],
    "tracks": [],
    "encounters": [],
    "puzzles": [],
    "tables": [],
    "triggers": [],
    "endings": []
  },
  "initial_state": {},
  "assets": [],
  "normalization_decisions": [],
  "validation": {}
}
```

所有 `content` 集合必须存在但允许为空。空集合表示原文没有该玩法；Agent 必须通过来源覆盖检查证明不是漏解析。

## 4. 来源、分段和权利

`source_manifest` 至少包含：

```text
filename / page_count / language / document_type
text_extraction / layout_reviewed / runtime_included
segments
extraction_quality.text_confidence
extraction_quality.layout_confidence
extraction_quality.asset_coverage
rights.declaration_status
rights.commercial_use
rights.redistribution
```

`segments` 必须区分模组正文、规则附录、预生成角色、玩家手册和其他模组。每个正式包只包含被选中的模组及其依赖分段。

权利状态未知时可以作为私有导入或开发样例，但不能自动标记为允许商业发布。

## 5. 模组与角色配置

`module` 除身份、设定、人数和入口外，还必须包含：

```json
{
  "estimated_duration": "<duration>",
  "character_setup": {
    "creation_mode": "custom",
    "requirements": [],
    "recommended_skills": [],
    "party_relationships": [],
    "pregenerated_character_ids": [],
    "personalization_slots": []
  },
  "content_advisories": [],
  "entry_scene_id": "scene.entry",
  "entry_points": []
}
```

`entry_scene_id` 是默认入口；`entry_points` 可以表达职业、委托或玩家背景不同造成的多个导入。预生成角色必须进入 `content.characters`，不能只作为 PDF 图片保存。

## 6. AI 主持所需内容

### 6.1 KeeperBrief

必须明确：

- `core_truth`：完整真相；
- `experience_goal`：目标体验；
- `tone`：叙事基调；
- `must_preserve`：不可违反的剧情和人物约束；
- `must_not_reveal_before_granted`：禁止提前透露的 Fact ID。

### 6.2 Scene、Location 和 Entity

Scene 保存叙事节点：

```text
id / name / kind
player_description / keeper_notes
location_ids / entity_ids / resource_ids
clue_ids / checkpoint_ids / encounter_ids / trigger_ids
next_scene_ids / source_refs
```

Location 保存物理世界：

```text
id / name / kind / parent_location_id
scene_ids / connections / asset_ids
initial_state / source_refs
```

Entity 保存 NPC、怪物或群体：

```text
public_description / keeper_description
knowledge_fact_ids / knowledge_clue_ids
goals / behavior / speech_style
initial_state / stat_block / source_refs
```

Scene 和 Location 必须分开。前者控制叙事和转场，后者控制空间层级、出口、隐藏路线和地图关联。

### 6.3 Fact 和 Clue

Fact 保存真实世界状态及可见性。Clue 保存玩家如何获得事实，至少包含：

```text
id
summary 或 player_facing_text
criticality
reveals_fact_ids
effects
source_refs
```

核心线索必须至少有一条可达路径；失败不能让主线永久中断，除非原文明确把它定义为结局。

## 7. 可执行玩法对象

### 7.1 Resource

`resources` 保存道具、手册、典籍、法术、机关、武器和消耗品。它可以声明：

```text
location_id / owner_entity_id
charges / uses / study
granted_clue_ids / granted_ability_ids
initial_state / source_refs
```

资源的持有、消耗、阅读和破损状态必须写入 GameState，不能只出现在叙述中。

### 7.2 Timeline

`timelines` 保存外部时间推进：

```text
clock.unit / clock.phases
events[].schedule
events[].conditions
events[].effects
events[].scene_ids
events[].available_checkpoint_ids
```

NPC 日程、每天固定事件和每若干回合发生的效果都属于 Timeline。

### 7.3 Track

`tracks` 保存阶段进度：

```text
scope / initial_state
states[].id / states[].effects
transitions[].from / transitions[].to
transitions[].conditions / transitions[].effects / priority
```

感染、异变、怀疑、警戒和仪式进度使用同一套 Track。规则引擎执行转换，AI 主持只叙述结果。

### 7.4 Encounter

`encounters` 统一表达战斗、追逐、谈判、群体检定和环境挑战：

```text
id / name / kind
scene_ids / participant_entity_ids
start_conditions / scaling
player_options / resolution
on_start / on_end / source_refs
```

`scaling` 可以根据调查员人数、资源或 Track 状态调整敌人数量和难度。核心算法仍由 Ruleset 提供，模组只能声明参数和公式。

### 7.5 Puzzle 和 Table

Puzzle 至少表达：

```text
goal / nodes / dependencies
interactions / hint_levels
alternative_solutions / failure_policy
```

Table 至少表达：

```text
roll / selection_mode / entries
```

谜题节点引用 Resource、Checkpoint、Clue 和 Effect；随机表结果必须是结构化值或已注册 Effect，不能要求 AI 临时编造关键规则。

## 8. 规则系统接口

`module.ruleset_ref` 必须固定：

```text
system_id
version
required_capabilities
required_condition_types
required_effect_types
```

模组不能重新定义骰点、成功等级、伤害和战斗算法。技能、属性、Condition 和 Effect 必须使用规则系统注册的规范 ID。

Checkpoint 至少包含：

```json
{
  "id": "check.search_study",
  "scene_id": "scene.kimball_house",
  "skills": ["spot_hidden"],
  "difficulty": "regular",
  "prerequisites": [],
  "repeat": null,
  "time_cost": "1 day",
  "on_success": [
    {"type": "grant_clue", "clue_id": "clue.diary_decision"}
  ],
  "on_failure": [],
  "on_fumble": []
}
```

SanityEvent、Timeline、Track、Encounter、Trigger 和 Ending 中的 Condition 与 Effect 同样必须注册。未声明结果使用 `runtime_defaults`，不能交给 AI 临场补写。

## 9. 初始状态

`initial_state` 必须足以直接创建游戏实例：

```text
current_scene_id
discovered_scene_ids
granted_clue_ids
completed_checkpoint_ids
fired_trigger_ids
active_timeline_ids
track_states
inventory_resource_ids
active_encounter_id
active_ending_id
clock
variables
```

Location、Entity、Character 和 Resource 的初始状态由 Loader 合并进第一份 GameState。

## 10. 素材语义

Asset 除文件元数据外，应根据类型声明：

```text
linked_location_ids
linked_entity_ids
reveal_after_clue_ids
source_page / source_bbox
runtime_use
```

地图需要关联地点和标签；玩家手册需要关联 Clue 及展示条件；NPC 立绘需要关联 Entity 和防剧透条件。素材识别失败但影响运行时理解时，导入必须失败。

## 11. 自动处理歧义

解析 Agent 按以下顺序自动决策：

1. 明确原文优先；
2. Ruleset 规范优先；
3. 保持作者意图；
4. 保护玩家选择和多种解法；
5. 不推断原文没有的地图距离、人物动机和规则效果；
6. 非关键装饰信息可以保守省略；
7. 关键规则、线索、结局或权利状态无法确定时失败而不是猜测。

所有自动决策写入 `normalization_decisions`，必须包含 `status=resolved`、结果、策略和来源。

## 12. 调用流程

```text
玩家行动
  -> AI 主持选择候选 Scene、Checkpoint、Encounter 或自由叙事
  -> 编排器校验地点、时间线、Track、权限和前置条件
  -> 规则引擎执行检定、Condition 和 Effect
  -> 运行时提交 GameState
  -> AI 主持根据结构化结果生成叙事
```

定时事件、Track 转换、SAN、Encounter 结束和 Ending 检查由编排器自动调用规则引擎。AI 主持不能绕过前置条件或直接写状态。

## 13. 自动发布门禁

一个包只有通过以下检查才能成为 `ready`：

- [ ] 顶层结构符合 `ModulePackage 1.1`；
- [ ] 文档分段、来源覆盖和权利状态完整；
- [ ] 所有对象 ID 唯一且引用存在；
- [ ] 入口场景、角色配置和初始状态有效；
- [ ] Scene 与 Location 连接一致，隐藏路线有发现条件；
- [ ] 玩家描述不包含未解锁 Keeper Fact；
- [ ] NPC 具有知识边界和关键行为约束；
- [ ] 技能、Condition、Effect 和 Ruleset 能力均受支持；
- [ ] 核心线索和关键结局可达；
- [ ] Timeline、Track 和 Trigger 不存在无限循环；
- [ ] Encounter 和 Puzzle 的关键结果确定；
- [ ] 素材具有语义关联和展示条件；
- [ ] 所有归一化决策已解决；
- [ ] 不包含 `review_items`、TODO 或 unresolved 占位符；
- [ ] Validator 为 `passed` 且 `errors=[]`。

## 14. Parser Agent 完成标准

针对受支持格式的任意模组，Parser Agent 应能够：

1. 识别一个文档中的模组、附录、手册、地图和角色卡边界；
2. 生成与黄金样例相同协议版本的 `ModulePackage`；
3. 让 Loader 无需读取原文即可创建 GameState；
4. 让 AI 主持只凭包内容完成描述、NPC 对话、信息控制和候选行动选择；
5. 让规则引擎只凭包内容执行检定、时间线、轨道、遭遇、效果和结局；
6. 对无法安全解析的模组返回结构化失败；
7. 保存来源、置信度和自动决策，使问题可以复现和调试。

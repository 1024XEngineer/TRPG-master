# ModulePackage 1.1 框架与《追书人》成品对照

工作项：[Issue #98](https://github.com/1024XEngineer/TRPG-master/issues/98)

空框架：[`module-package.template.json`](module-package.template.json)

预设模组：[`paper-chase/module-package.json`](paper-chase/module-package.json)

产物契约：[`parser-runtime-contract.md`](parser-runtime-contract.md)

## 1. 评审结论

`ModulePackage 1.1` 保留了 1.0 的调查叙事骨架，并补充角色配置、物理地点、时间线、状态轨道、遭遇、资源、谜题、随机表和预生成角色。

Parser Agent 的正式目标是生成一个通过自动门禁、可直接创建游戏实例的 `ready ModulePackage`。它不能只把复杂玩法写进 `keeper_notes`，也不能把未决问题交给玩家审核。

《追书人》仍是第一个黄金预设模组。它只填写原文确实存在的结构：地点、资源、昼夜时间线和对峙遭遇；原文没有预生成角色、阶段轨道、谜题和随机表，因此对应数组为空。

## 2. 1.1 的样本依据

仅用《追书人》会把协议限制在“场景、线索、检定、结局”型短篇。补充样本证明以下内容必须可结构化：

| 样本 | 暴露的通用需求 |
|---|---|
| 《科比特先生》 | NPC 行程与怀疑、跟踪追逐、延迟效果、典籍和法术 |
| 《复足》 | 固定时间线、感染阶段、人数缩放、楼层地图、预生成角色 |
| 《鬼屋》 | 顺序线索、孤注一骰代价、隐藏房间、环境机关和互动道具 |
| 《幸福蛙蛙村》 | 多入口、多日进程、累积暴露、阶段异变和多种解决方式 |
| 《死者的顿足舞》 | 文档分段、追逐、群体检定、人群事件和后续战役钩子 |
| 《银之锁》 | 玩家背景绑定、机关依赖、提示层级、消耗道具和开放解法 |

这些能力被归并为少量通用对象，避免为每个模组发明专用字段。例如感染和异变都使用 `tracks`，战斗和追逐都使用 `encounters`。

## 3. 顶层结构

| 部分 | Agent 需要填入的内容 | 《追书人》成品 |
|---|---|---|
| `source_manifest` | 文件、分段、提取质量和权利声明 | 1 个模组分段，6 页，文本/版面/素材覆盖完整，商业权利未核验 |
| `module` | 身份、规则、人数、时长、角色配置、内容提示和入口 | CoC7、单人、自建角色、单一委托入口 |
| `keeper_brief` | 真相、体验目标、行为底线和防剧透 Fact | 道格拉斯主动成为食尸鬼且默认不敌对 |
| `runtime_defaults` | 未声明结果、未知行动、轨道和时间线冲突策略 | 使用确定性的保守默认值 |
| `content` | 16 类可引用运行对象 | 见下一节 |
| `initial_state` | 场景、时间线、轨道、背包、遭遇和变量初值 | 委托场景、昼夜循环、无活动遭遇 |
| `assets` | 素材用途、关联对象和展示条件 | 道格拉斯插图与地点地图 |
| `normalization_decisions` | Agent 已解决的歧义及来源 | 人数、战斗、腐臭、SAN、书籍和地图共 6 项 |
| `validation` | 自动检查和错误 | `module-package-validator/0.2.0` 通过 |

## 4. 内容对象

### 4.1 16 类集合

| 集合 | 作用 | 《追书人》数量 |
|---|---|---:|
| `facts` | Keeper 世界真相和可见性 | 5 |
| `scenes` | 叙事节点、玩家描述、主持说明和转场 | 12 |
| `locations` | 物理地点、层级、连接、隐藏路线和地图绑定 | 5 |
| `entities` | NPC、怪物和群体的知识、目标、行为与数值 | 6 |
| `characters` | 预生成调查员及其运行时角色卡 | 0 |
| `resources` | 道具、手册、典籍、机关和消耗品 | 4 |
| `clues` | 玩家获得的信息、重要性和揭示的 Fact | 13 |
| `checkpoints` | 技能、难度、前置、耗时和结构化结果 | 14 |
| `sanity_events` | 理智检定及累计上限 | 4 |
| `timelines` | 日程、阶段和定时可用事件 | 1 |
| `tracks` | 感染、异变、怀疑和仪式等状态进度 | 0 |
| `encounters` | 战斗、追逐、群体检定、谈判和环境挑战 | 1 |
| `puzzles` | 机关依赖、交互动作、提示和替代解法 | 0 |
| `tables` | 随机遭遇、目标、数值或叙事结果 | 0 |
| `triggers` | 事件发生后的 Condition 和 Effect | 7 |
| `endings` | 带优先级的确定性结局 | 6 |

所有集合都必须存在，但允许为空。空数组表示原文没有该玩法，不表示解析遗漏；`validation` 负责区分二者。

### 4.2 角色配置

空框架要求：

```json
{
  "creation_mode": "<custom|pregenerated|required_pregenerated|mixed>",
  "requirements": [],
  "recommended_skills": [],
  "party_relationships": [],
  "pregenerated_character_ids": [],
  "personalization_slots": []
}
```

《追书人》使用一名自建调查员，不绑定预生成角色，也不需要根据背景替换谜题内容。其他模组可以通过 `pregenerated_character_ids` 引用 `content.characters`，通过 `personalization_slots` 声明要从玩家背景注入的内容。

### 4.3 Scene 与 Location

`Scene` 是“正在发生什么”，`Location` 是“事情在哪里发生”。两者不能继续混为同一种 Entity。

《追书人》的 `location.cemetery` 保存墓地的物理结构，并连接常坐墓碑和隐藏地穴；`scene.cemetery` 保存玩家搜索墓地时能听到的描述、线索、检定和转场。

```json
{
  "id": "location.cemetery",
  "kind": "outdoor_site",
  "connections": [
    {"location_id": "location.favorite_grave", "kind": "within_area"},
    {
      "location_id": "location.crypt_entrance",
      "kind": "hidden_route",
      "discovery_clue_id": "clue.crypt_entrance"
    }
  ],
  "asset_ids": ["asset.local_map"]
}
```

地图只建立原文明确支持的连接。原图注明不按比例，因此不生成距离和移动时间。

### 4.4 Resource

`resources` 保存会被阅读、持有、消耗或操作的对象。对象状态仍可以通过 Effect 写入 GameState。

《追书人》包含：

- 道格拉斯日记：关联阅读检定和两条线索；
- 书房窗户：保存上锁和破损状态；
- 看守的酒瓶：观察后可改变交涉路径；
- 一品脱酒：可购买并用于贿赂。

这使规则引擎不需要从 `keeper_notes` 猜测“日记是否读过”或“酒是否持有”。

### 4.5 Timeline 与 Track

`timelines` 表示外部时间推进和定时事件，`tracks` 表示某个对象的阶段性状态推进。

《追书人》的昼夜循环规定夜间才开放监视检定。它没有感染、异变或怀疑阶段，因此 `tracks=[]`。类似《复足》的感染 0～5 阶段应放入 Track，而不是拆成六个 Scene。

### 4.6 Encounter

`encounters` 统一表达谈判、战斗、追逐、群体检定和环境挑战，并声明参与者、人数缩放、可选行动及结束方式。

《追书人》的 `encounter.douglas_confrontation` 明确：

- 道格拉斯默认不主动攻击；
- 玩家可以呼喊、交谈、跟随、攻击或离开；
- 攻击食尸鬼群不是可获胜的普通战斗；
- 结构化结果引用四种相关 Ending。

### 4.7 Puzzle 与 Table

《追书人》没有真正的机关依赖图或随机表，所以两者为空。其他模组中：

- 密室钥匙、抽屉和出口的依赖关系进入 `puzzles`；
- 随机遭遇、目标选择和动态怪物数据进入 `tables`；
- 谜题检定仍引用 `checkpoints`，谜题结果仍通过 Effect 改变状态。

## 5. 初始状态

1.1 的初始状态除原有场景、线索、Trigger 和时钟外，还必须包含：

```text
active_timeline_ids
track_states
inventory_resource_ids
active_encounter_id
```

《追书人》启动时激活 `timeline.investigation_cycle`，没有活动 Track、背包资源和 Encounter。Loader 合并 Location、Entity 和 Resource 的 `initial_state` 后即可创建第一份 GameState。

## 6. 素材与权利

素材不能只记录“有一张图”，还要声明它关联什么以及何时展示：

- 地图通过 `linked_location_ids` 连接金博尔宅、墓地和地穴入口；
- 道格拉斯插图通过 `linked_entity_ids` 关联 NPC，并在获得真相线索后展示；
- 来源文档必须分段，避免把角色卡、规则附录或另一个模组误并入当前包；
- `rights` 必须记录商业使用和再分发状态，未核验不能视为可商业发布。

## 7. Agent、规则系统和运行时边界

| 内容 | Parser Agent | 规则系统 | 运行时 |
|---|---:|---:|---:|
| 识别文档边界、地图、手册和角色卡 | 是 | 否 | 否 |
| 提取 Scene、Location、NPC、资源和线索 | 是 | 否 | 消费 |
| 生成 Timeline、Track、Encounter 和 Puzzle 声明 | 是 | 校验能力 | 编排执行 |
| 定义骰点、成功等级和战斗算法 | 否 | 是 | 调用 |
| 将技能、Condition 和 Effect 映射到规范 ID | 是 | 提供目录并校验 | 否 |
| 创建和保存 GameState | 生成初始值 | 计算变化 | 是 |
| 决定素材展示时机和玩家可见性 | 生成约束 | 否 | 执行过滤 |
| 解决原文歧义并记录依据 | 是 | 提供规则依据 | 否 |

AI 主持可以提出行动和叙事，但不能自行改变 Track、跳过 Timeline、修改骰点或创建未声明的关键道具。

## 8. 从空框架到成品

```text
上传原始文档
  -> 识别文档分段、版权声明、文本、表格和图片
  -> 提取角色配置、地点、场景、实体、资源和线索
  -> 生成检定、时间线、轨道、遭遇、谜题、Trigger 和 Ending
  -> 绑定 Ruleset 并生成 initial_state
  -> 自动归一化歧义
  -> Schema、引用、可达性、规则和权利门禁
  -> ready ModulePackage 或 failed ImportJob
```

`ModulePackage 1.1` 是后续 Loader、规则引擎、AI 主持和 Parser Agent 共同对齐的协议。《追书人》是该协议的首个可运行黄金样例，而不是协议能力的上限。

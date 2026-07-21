# 《追书人》模组解析与入库报告

工作项：[Issue #98](https://github.com/1024XEngineer/TRPG-master/issues/98)

可运行模组包：[`module-package.json`](module-package.json)

产物契约：[`Module Parser Agent 产物契约`](../parser-runtime-contract.md)

框架对照：[`ModulePackage 空框架与《追书人》成品`](../module-package-review.md)

## 1. 当前结论

《追书人》PDF 共 6 页，已经被整理为 `ModulePackage 1.1.0`。该包不再是等待玩家审核的 Draft，而是规则引擎、AI 主持和游戏编排器共同使用的第一个黄金预设模组。

它已经具备：

- 明确的规则系统、人数和入口场景；
- 文档分段、提取质量、权利状态和内容提示；
- 自建角色要求、推荐技能和默认导入；
- 玩家可见描述与 Keeper 私有说明；
- NPC 知识、目标、行为和数值；
- 物理地点、地图连接、可交互资源和素材展示条件；
- 线索、检定、SAN、时间线、遭遇、Trigger 和 Ending；
- 可以直接创建游戏的 `initial_state`；
- 已解决的原文歧义和自动验证摘要；
- 稳定 ID、对象引用和来源页码。

当前仓库还没有 `ModulePackage Loader`、完整规则引擎和 AI 主持，因此尚不能在现有产品界面中完整开团；这是运行时能力缺失，不是模组包仍需玩家审核。后续组件应以该包为开发和测试输入。

## 2. 解析结果

### 2.1 内容总览

| 内容 | 数量 | 说明 |
|---|---:|---|
| 核心事实 | 5 | Keeper 真相及可见性 |
| 场景 | 12 | 调查、冲突、地穴和最终对话 |
| 地点 | 5 | 城镇、旧宅、墓地、墓碑和地穴入口 |
| 实体 | 6 | NPC 和食尸鬼群体 |
| 预生成角色 | 0 | 原文要求一名自建调查员 |
| 资源 | 4 | 日记、窗户、酒瓶和一品脱酒 |
| 线索 | 13 | 前提、支撑、路线、真相和结局线索 |
| 检定 | 14 | 社交、调查、追踪、幸运、语言和力量 |
| 理智事件 | 4 | 触发条件、损失公式和上限 |
| 时间线 | 1 | 调查昼夜循环和夜间监视窗口 |
| 状态轨道 | 0 | 原文没有感染、异变或怀疑阶段 |
| 遭遇 | 1 | 道格拉斯对峙及其非敌对/暴力结果 |
| 谜题 | 0 | 原文没有机关依赖图 |
| 随机表 | 0 | 原文没有运行时随机表 |
| Trigger | 7 | 移动、状态变化、SAN 和场景切换 |
| Ending | 6 | 和平、失踪、疗养院、逃亡和被捕 |
| 素材 | 2 | 道格拉斯插图和地点地图 |
| 自动归一化决策 | 6 | 已全部解决，不需要玩家审核 |

### 2.2 模组真相和主持约束

玩家受托调查道格拉斯失踪和五本书被盗。真相是：道格拉斯主动进入地下世界并逐渐成为食尸鬼，回来只是为了取回自己的藏书。他通常不主动攻击调查员。

`keeper_brief` 明确约束 AI 主持：

- 不把道格拉斯默认描述成主动猎杀玩家的怪物；
- 不在获得对应线索前透露偷书者和食尸鬼真相；
- 保留从邻居、看守、图书馆、报社、日记、追踪和监视进入主线的多条路径；
- 暴力不是默认胜利方式。

### 2.3 场景

| 场景 | 作用 |
|---|---|
| 托马斯的委托 | 建立失踪和盗书目标 |
| 询问邻居 | 获得道格拉斯与墓地的联系 |
| 墓地看守 | 获得墓碑和夜间人影信息 |
| 地下酒吧 | 获取贿赂用酒，存在被捕风险 |
| 当地图书馆 | 找到旧报纸索引 |
| 报社档案室 | 获得墓地怪物证词 |
| 金博尔宅与书房 | 找到日记和隧道信息 |
| 公共墓地 | 寻找足迹、入口或监视 |
| 夜间监视 | 遭遇前来取书的道格拉斯 |
| 与人影正面对抗 | 处理追赶、呼喊或攻击 |
| 地穴入口 | 处理石板和腐臭危险 |
| 与道格拉斯对话 | 揭示真相并进入最终选择 |

每个 Scene 同时提供：

```text
player_description  可直接告诉玩家
keeper_notes        只提供给 AI 主持
location_ids        当前场景对应的物理地点
entity_ids          当前可交互实体
resource_ids        当前可阅读、持有或操作的资源
clue_ids            当前可获得线索
checkpoint_ids      可能触发的规则检定
encounter_ids       当前可进入的遭遇
trigger_ids         自动事件
next_scene_ids      允许转场目标
source_refs         原文来源
```

### 2.4 规则内容

规则引擎可以从包中读取：

- `module.ruleset_ref`：CoC7 及所需规则能力；
- `locations`：地点层级、连接、隐藏路线和地图绑定；
- `resources`：日记、机关和物品状态；
- NPC `stat_block`：属性、HP、攻击、护甲和 SAN 损失；
- `checkpoints`：技能、难度、前置条件、重复方式、成本和结果；
- `sanity_events`：成功/失败损失和累计上限；
- `timelines`：昼夜推进及定时开放的事件；
- `encounters`：参与者、可选行动、缩放和结束策略；
- `triggers`：事件及 Effect；
- `endings`：条件、优先级和结构化结果；
- `initial_state`：入口场景、初始线索、时间和模组变量。

缺失的检定结果由 `runtime_defaults.missing_checkpoint_outcome=no_effect` 确定性处理；Trigger 默认只执行一次，不能由 AI 主持临场补写规则。

### 2.5 自动归一化结果

此前的 6 项待确认问题已改为确定性决策：

| 原文歧义 | 最终决策 |
|---|---|
| 玩家人数 | 严格按原文使用一名调查员 |
| 攻击食尸鬼群 | 触发被制服并带走的结局，不进入可获胜战斗 |
| 地穴腐臭 | 未提前声明屏住呼吸则自动昏迷到夜晚 |
| SAN 结算顺序 | 先损失 `1D4`，确认威胁结束后回复 `1D6` |
| 五本书归属 | 由玩家选择写入 `books.disposition`，不阻断和平结局 |
| 地图拓扑 | 仅作为不按比例图片，不推断距离和移动时间 |

这些结果保存在 `normalization_decisions` 中，用于审计，不要求玩家逐项确认。

## 3. Parser Agent 应输出什么

Parser Agent 内部可以生成：

```text
SourceManifest
ExtractedDocument
ModuleDraft
ValidationReport
RepairTrace
```

但正式输出只有：

```text
ready ModulePackage
或
failed ImportJob + diagnostics
```

不允许输出“部分可运行、等待玩家审核”的包。完整字段和门禁见 [`Module Parser Agent 产物契约`](../parser-runtime-contract.md)。

## 4. 自动解析和失败策略

```text
上传文件
  -> 文本/OCR/版面提取
  -> 结构识别和来源绑定
  -> 内部 ModuleDraft
  -> 规则、可见性和歧义归一化
  -> Schema 与语义校验
  -> 自动修复并重新校验
  -> ready ModulePackage 或 failed
```

可自动处理的内容写入 `normalization_decisions`。以下情况不得猜测，应直接让导入失败：

- 无法确定规则系统或版本；
- 核心线索无法形成可达路径；
- 关键结局相互冲突且无法排序；
- 玩家描述无法与 Keeper 秘密分离；
- 使用规则引擎不支持的关键 Condition/Effect；
- 关键对象引用缺失或 Trigger 存在无限循环。

玩家只看到导入成功或结构化失败原因，不参与内容审核。

## 5. 入库内容

### 5.1 存储映射

| 内容 | 存储位置 | 方式 |
|---|---|---|
| 原始 PDF | 对象存储 + `module_sources` | 地址、哈希和元数据 |
| 解析任务 | `module_import_jobs` | 阶段、状态和模型版本 |
| Draft、ValidationReport、RepairTrace | `module_import_artifacts` | JSONB 或对象存储 |
| 自动错误和警告 | `module_import_diagnostics` | 每个诊断一行 |
| 模组目录信息 | `scenarios` | 关系字段 |
| 完整 `ModulePackage` | `scenario_revisions.package_json` | 不可变 JSONB |
| 地图、插图和音频 | 对象存储 + `module_assets` | 文件及元数据 |

### 5.2 必需表

#### `module_sources`

```text
id UUID PK
owner_user_id UUID FK
original_filename VARCHAR(255)
mime_type VARCHAR(100)
storage_key VARCHAR(500)
size_bytes BIGINT
checksum_sha256 CHAR(64)
page_count INTEGER NULL
language VARCHAR(20) NULL
rights_declaration JSONB
status VARCHAR(20)
created_at TIMESTAMPTZ
deleted_at TIMESTAMPTZ NULL
```

#### `module_import_jobs`

```text
id UUID PK
source_id UUID FK
requested_ruleset_id UUID FK NULL
status VARCHAR(20)          pending/running/ready/published/failed
stage VARCHAR(30)           extract/structure/normalize/validate/repair/publish
progress INTEGER
parser_version VARCHAR(50)
model_provider VARCHAR(50) NULL
model_name VARCHAR(100) NULL
prompt_version VARCHAR(50) NULL
repair_attempts INTEGER
result_scenario_id UUID FK NULL
result_revision_id UUID FK NULL
error_code VARCHAR(50) NULL
error_detail JSONB NULL
started_at TIMESTAMPTZ NULL
completed_at TIMESTAMPTZ NULL
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

#### `module_import_artifacts`

```text
id UUID PK
job_id UUID FK
artifact_type VARCHAR(40)   source_manifest/extracted_document/module_draft/validation_report/repair_trace
schema_version VARCHAR(30)
content_json JSONB NULL
storage_key VARCHAR(500) NULL
checksum_sha256 CHAR(64)
created_at TIMESTAMPTZ
```

#### `module_import_diagnostics`

```text
id UUID PK
job_id UUID FK
artifact_id UUID FK NULL
code VARCHAR(60)
severity VARCHAR(20)        info/warning/error/blocker
object_type VARCHAR(30) NULL
object_ref VARCHAR(200) NULL
source_ref_json JSONB NULL
message TEXT
details_json JSONB NULL
created_at TIMESTAMPTZ
```

该表用于自动诊断和开发调试，不是玩家审核队列。

#### `scenarios`

```text
id UUID PK
owner_user_id UUID FK NULL
game_system_id UUID FK
world_id UUID FK NULL
title VARCHAR(200)
original_title VARCHAR(200) NULL
slug VARCHAR(200) UNIQUE
synopsis TEXT NULL
authors JSONB
players_min INTEGER
players_max INTEGER
estimated_duration VARCHAR(50) NULL
visibility VARCHAR(20)
status VARCHAR(20)          draft/published/archived
current_revision_id UUID FK NULL
created_at TIMESTAMPTZ
updated_at TIMESTAMPTZ
```

#### `scenario_revisions`

```text
id UUID PK
scenario_id UUID FK
revision_number INTEGER
semantic_version VARCHAR(50)
package_schema_version VARCHAR(30)
ruleset_id UUID FK
ruleset_version VARCHAR(50)
package_json JSONB
validation_summary JSONB
source_job_id UUID FK NULL
checksum_sha256 CHAR(64)
status VARCHAR(20)          ready/published/deprecated
created_at TIMESTAMPTZ
published_at TIMESTAMPTZ NULL
```

建议约束：

```text
UNIQUE(scenario_id, revision_number)
UNIQUE(scenario_id, checksum_sha256)
```

#### `module_assets`

```text
id UUID PK
revision_id UUID FK
asset_key VARCHAR(200)
asset_type VARCHAR(30)
name VARCHAR(200)
storage_key VARCHAR(500)
mime_type VARCHAR(100)
checksum_sha256 CHAR(64)
source_page INTEGER NULL
source_bbox JSONB NULL
metadata_json JSONB
generated_by_ai BOOLEAN
created_at TIMESTAMPTZ
```

## 6. JSONB 与关系表边界

`scenario_revisions.package_json` 是正式模组的唯一事实源。Scene、Location、Entity、Character、Resource、Clue、Checkpoint、SanityEvent、Timeline、Track、Encounter、Puzzle、Table、Trigger 和 Ending 全部保存在其中。

当前不拆分 Condition、Effect、NPC Goal 和 Clue Source 等多态子表。后续如编辑器或搜索需要，可以生成 Scene、Entity、Clue、Trigger 投影表；投影必须由 `package_json` 自动生成，不能手工维护两份内容。

## 7. 后续开发接入

1. 实现 `ModulePackage` Schema 和 Validator；
2. 实现 Loader，从 `module-package.json` 创建初始 GameState；
3. 规则引擎使用 Checkpoint、SanityEvent、Trigger 和 Ending 开发测试；
4. AI 主持使用 `keeper_brief`、Scene、NPC、Fact 和 Clue 开发测试；
5. 编排器实现候选行动校验、规则调用和状态提交；
6. 最后开发 Parser Agent，使任意模组自动生成同结构的 `ModulePackage`。

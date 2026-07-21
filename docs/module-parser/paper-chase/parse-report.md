# 《追书人》模组解析与入库设计报告

工作项：[Issue #98](https://github.com/1024XEngineer/TRPG-master/issues/98)

配套解析草稿：[`module-draft.json`](module-draft.json)

## 1. 报告结论

《追书人》PDF 共 6 页。本次解析已经形成一份可审查的 `ModuleDraft`，但仍需处理人工确认项并通过规则和引用校验，才能发布为 Runtime 可加载的 `ModuleContent`。

解析结果不能只作为一个没有版本信息的 JSON 塞入数据库，也不需要立即把 Scene、NPC、Clue、Condition 和 Effect 全部拆成关系表。推荐采用以下方式：

```text
原始文件、解析任务、人工问题、模组身份、版本和资源：关系表
ModuleDraft、ValidationReport、ModuleContent：版本化 JSONB
PDF、图片和大型中间文件：对象存储
```

本报告只讨论模组解析和发布入库，不包含房间状态、事件日志和复盘等开团运行时数据。

## 2. 本次解析出了什么

### 2.1 内容总览

| JSON 字段 | 数量 | 解析内容 | 主要用途 |
|---|---:|---|---|
| `source` | 1 | 文件名、页数、语言、文档类型、提取方式 | 来源审计 |
| `publication_candidate` | 1 | 标题、规则系统、时代、地点、人数、简介、入口场景 | 创建模组目录 |
| `facts` | 5 | Keeper 才能知道的剧情事实 | 防剧透、约束主持 |
| `scenes` | 12 | 调查节点、冲突、地穴和最终对话 | 场景推进 |
| `entities` | 12 | NPC、群体、物品和地点状态 | NPC 行为和世界状态 |
| `clues` | 13 | 前提、支撑、路线解锁、核心真相和结局线索 | 调查网络 |
| `checkpoints` | 14 | 技能、难度、前置条件、成功/大失败结果 | 规则判定 |
| `sanity_events` | 4 | SAN 触发条件、损失公式和上限 | 理智结算 |
| `triggers` | 7 | 事件触发条件和状态变化 | 剧情自动推进 |
| `endings` | 6 | 条件、优先级、结果和摘要 | 结局判定 |
| `assets` | 2 | 道格拉斯插图和地点地图 | 游戏展示 |
| `review_items` | 6 | 解析歧义和待人工确认问题 | 发布门禁 |

每个关键对象都使用稳定 ID，并保留 `source_refs`，用于追溯 PDF 页码和章节。

### 2.2 模组核心内容

玩家受托调查道格拉斯失踪和五本书被盗。Keeper 真相是：道格拉斯主动进入地下世界并逐渐成为食尸鬼，偷书只是为了取回自己的藏书。他通常不主动攻击调查员，并希望继续自己的生活。

核心体验不是消灭怪物，而是调查真相并决定是否接受、隐瞒或暴力干预道格拉斯的选择。AI Keeper 必须遵守道格拉斯的非敌对行为约束，不能把他默认主持成主动猎杀玩家的怪物。

### 2.3 场景和调查流程

解析出的 12 个场景为：

| 场景 | 作用 |
|---|---|
| 托马斯的委托 | 建立失踪和盗书目标 |
| 询问邻居 | 得知道格拉斯与墓地的联系 |
| 墓地看守 | 获得墓碑和夜间人影信息 |
| 地下酒吧 | 获取贿赂看守所需的酒，存在被捕风险 |
| 图书馆 | 找到旧报纸索引 |
| 报社档案 | 获得类人生物证词 |
| 金博尔宅 | 找到日记和地下隧道信息 |
| 公共墓地 | 寻找足迹、入口或开始监视 |
| 夜间监视 | 直接遭遇前来取书的道格拉斯 |
| 正面对抗 | 处理追赶、攻击或呼喊名字 |
| 地穴入口 | 处理石板和腐臭危险 |
| 与道格拉斯对话 | 揭示真相并进入最终选择 |

这些场景构成调查网络，不是固定的线性流程。邻居、看守、图书馆、报社、日记和监视都可以把玩家引向墓地；即使部分检定失败，重复夜间监视仍可触发遭遇。

### 2.4 NPC、线索和规则

主要 NPC 包括托马斯、道格拉斯、邻居莱拉、墓地看守梅洛迪亚斯、证词提供者希尔达和食尸鬼群。解析内容包含：

- NPC 的公开描述、Keeper 描述、目标、知识边界和初始状态；
- 道格拉斯的数值、默认态度、对话意愿和战斗停止条件；
- 日记、窗户、墓碑、入口石板、酒瓶等可变化对象；
- 13 条线索之间的事实揭示关系和状态效果；
- 14 个技能检定的技能、难度、前置条件和结果；
- 重复检定、职业免检、时间成本、金钱成本和大失败结局；
- 4 个理智事件及 `0/1D6`、`1/1D8`、`1D4` 等公式；
- 7 个触发器及移动实体、改变状态、请求 SAN 检定和切换场景等效果。

当前协议仍需补齐重复检定、职业免检、时间/货币成本、环境声明和理智奖励等表达能力。

### 2.5 结局和资源

解析出的结局包括：和平解决、跟随地下、被食尸鬼群带走、进入疗养院、杀死道格拉斯后逃离以及寻找地下酒吧时被捕。

解析出的资源包括：

- 第 4 页道格拉斯插图，只能在身份揭示后展示；
- 第 6 页地点地图，可作为图片使用，但不能从画面距离推断实际移动时间。

PDF 和图片本体不进入数据库二进制字段，应放入对象存储。

### 2.6 人工确认项

发布前必须处理以下 6 项：

| 问题 | 建议处理方式 |
|---|---|
| 是否严格限制一名调查员 | Demo 保持单人，产品层再决定是否适配多人 |
| 攻击食尸鬼群是否直接失败 | 默认按叙事失败结局处理 |
| 未声明屏息是否自动昏厥 | 保留原文规则，并提前给出感官提示 |
| SAN 损失和回复的结算顺序 | 先损失，再在确认威胁结束后回复 |
| 和平结局中五本书的归属 | 作为结局变量，不擅自补全 |
| 地图是否转换为互动节点 | Demo 使用图片，地图拓扑另行审查 |

## 3. Parser 的标准产物

一个导入任务不应只返回最终 JSON。推荐产出：

| 产物 | 内容 | Runtime 是否加载 |
|---|---|---|
| `SourceManifest` | 文件、页码、哈希、版权声明和提取方式 | 否 |
| `ExtractedDocument` | 文本块、章节、表格、图片位置和 OCR 信息 | 否 |
| `ModuleDraft` | 带来源、置信度和待确认项的解析草稿 | 否 |
| `AssetManifest` | 图片、地图、音频的来源和用途 | 间接使用 |
| `ValidationReport` | Schema、引用、规则、线索可达性和安全检查 | 否 |
| `ModuleContentCandidate` | 清理解析噪声后的待发布内容 | 否 |
| `ModuleContent` | 已验证、不可变、可执行的正式版本 | 是 |

发布路径为：

```text
SourceManifest + ExtractedDocument
                ↓
ModuleDraft + AssetManifest
                ↓
ValidationReport + 人工审查
                ↓
ModuleContentCandidate
                ↓
不可变 ModuleContent revision
```

`ModuleDraft` 不能直接被 Runtime 加载。只有解决 `review_items` 并通过验证后，才能生成正式 `ModuleContent`。

## 4. 哪些内容需要入库

### 4.1 逐项映射

| 解析内容 | 存储位置 | 存储方式 |
|---|---|---|
| 原始 PDF | 对象存储 + `module_sources` | 数据库保存地址、哈希和元数据 |
| 解析任务状态和模型信息 | `module_import_jobs` | 关系字段 |
| `SourceManifest` | `module_import_artifacts` | JSONB |
| `ExtractedDocument` | `module_import_artifacts` 或对象存储 | JSONB/文件 |
| `ModuleDraft` 完整草稿 | `module_import_artifacts` | JSONB |
| `ValidationReport` 和解析报告 | `module_import_artifacts` | JSONB/文件 |
| `review_items` | `module_import_issues` | 每个问题一行 |
| 标题、规则、人数、简介等目录信息 | `scenarios` | 关系字段 |
| 审核后的完整 `ModuleContent` | `scenario_revisions` | 不可变 JSONB |
| 地图、插图和音频 | 对象存储 + `module_assets` | 文件 + 关系字段 |
| `facts/scenes/entities/clues/checkpoints` | `scenario_revisions.content_json` | JSONB 内部对象 |
| `sanity_events/triggers/endings` | `scenario_revisions.content_json` | JSONB 内部对象 |

### 4.2 必需数据库表

#### `module_sources` - 原始上传文件

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 文件 ID |
| `owner_user_id` | UUID FK | 上传者 |
| `original_filename` | VARCHAR(255) | 原文件名 |
| `mime_type` | VARCHAR(100) | PDF、DOCX 等 |
| `storage_key` | VARCHAR(500) | 对象存储地址 |
| `size_bytes` | BIGINT | 文件大小 |
| `checksum_sha256` | CHAR(64) | 完整性和去重 |
| `page_count` | INTEGER NULL | 页数 |
| `language` | VARCHAR(20) NULL | 识别语言 |
| `rights_declaration` | JSONB | 上传权利声明 |
| `status` | VARCHAR(20) | uploaded/scanning/ready/rejected |
| `created_at` | TIMESTAMPTZ | 上传时间 |
| `deleted_at` | TIMESTAMPTZ NULL | 软删除时间 |

#### `module_import_jobs` - 解析任务

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 任务 ID |
| `source_id` | UUID FK | 原始文件 |
| `requested_ruleset_id` | UUID FK NULL | 目标规则系统 |
| `status` | VARCHAR(20) | pending/running/review/published/failed |
| `stage` | VARCHAR(30) | extract/structure/validate/review/publish |
| `progress` | INTEGER | 0-100 |
| `parser_version` | VARCHAR(50) | 解析器版本 |
| `model_provider` | VARCHAR(50) NULL | 模型供应商 |
| `model_name` | VARCHAR(100) NULL | 模型名称 |
| `prompt_version` | VARCHAR(50) NULL | Prompt 版本 |
| `result_scenario_id` | UUID FK NULL | 发布后的模组 |
| `result_revision_id` | UUID FK NULL | 发布后的版本 |
| `error_code` | VARCHAR(50) NULL | 稳定错误码 |
| `error_detail` | JSONB NULL | 错误详情 |
| `started_at/completed_at` | TIMESTAMPTZ NULL | 执行时间 |
| `created_at/updated_at` | TIMESTAMPTZ | 时间戳 |

#### `module_import_artifacts` - 中间产物

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 产物 ID |
| `job_id` | UUID FK | 所属解析任务 |
| `artifact_type` | VARCHAR(40) | source_manifest/extracted_document/module_draft/validation_report/content_candidate |
| `schema_version` | VARCHAR(30) | 产物协议版本 |
| `content_json` | JSONB NULL | 结构化内容 |
| `storage_key` | VARCHAR(500) NULL | 大型产物地址 |
| `checksum_sha256` | CHAR(64) | 内容哈希 |
| `created_at` | TIMESTAMPTZ | 创建时间 |

同一任务可以产生多个 Draft 和验证报告，因此不能把所有结果塞进 `module_import_jobs` 一行。

#### `module_import_issues` - 待人工确认问题

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 问题 ID |
| `job_id` | UUID FK | 所属任务 |
| `artifact_id` | UUID FK NULL | 来源产物 |
| `code` | VARCHAR(60) | 稳定问题码 |
| `severity` | VARCHAR(20) | info/warning/error/blocker |
| `object_type` | VARCHAR(30) | scene/entity/checkpoint/ending 等 |
| `object_ref` | VARCHAR(200) NULL | Draft 内稳定 ID |
| `source_ref_json` | JSONB NULL | 页码和章节 |
| `message` | TEXT | 问题描述 |
| `suggested_resolution` | JSONB NULL | Agent 建议 |
| `resolution_json` | JSONB NULL | 人工处理结果 |
| `status` | VARCHAR(20) | open/resolved/ignored |
| `resolved_by` | UUID FK NULL | 审查人 |
| `created_at/resolved_at` | TIMESTAMPTZ | 时间戳 |

#### `scenarios` - 模组身份和目录信息

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 模组稳定 ID |
| `owner_user_id` | UUID FK NULL | 所有者 |
| `game_system_id` | UUID FK | 默认规则系统 |
| `world_id` | UUID FK NULL | 世界观 |
| `title` | VARCHAR(200) | 标题 |
| `original_title` | VARCHAR(200) NULL | 原标题 |
| `slug` | VARCHAR(200) UNIQUE | 公开标识 |
| `synopsis` | TEXT NULL | 无剧透简介 |
| `authors` | JSONB | 作者列表 |
| `players_min/players_max` | INTEGER | 玩家人数 |
| `estimated_duration` | VARCHAR(50) NULL | 预计时长 |
| `visibility` | VARCHAR(20) | private/unlisted/public |
| `status` | VARCHAR(20) | draft/published/archived |
| `current_revision_id` | UUID FK NULL | 当前发布版本 |
| `created_at/updated_at` | TIMESTAMPTZ | 时间戳 |

#### `scenario_revisions` - 正式模组版本

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 版本 ID |
| `scenario_id` | UUID FK | 所属模组 |
| `revision_number` | INTEGER | 递增版本号 |
| `semantic_version` | VARCHAR(50) | 展示版本 |
| `schema_version` | VARCHAR(30) | ModuleContent 协议版本 |
| `ruleset_id` | UUID FK | 固定规则系统 |
| `ruleset_version` | VARCHAR(50) | 固定规则版本 |
| `content_json` | JSONB | 完整、已验证的 ModuleContent |
| `validation_summary` | JSONB | 发布校验摘要 |
| `source_job_id` | UUID FK NULL | 来源解析任务 |
| `checksum_sha256` | CHAR(64) | 不可变内容哈希 |
| `status` | VARCHAR(20) | review/published/deprecated |
| `created_by` | UUID FK NULL | 发布者 |
| `created_at/published_at` | TIMESTAMPTZ | 时间戳 |

建议约束：

```text
UNIQUE(scenario_id, revision_number)
UNIQUE(scenario_id, checksum_sha256)
```

已发布版本不允许原地修改。内容变化必须创建新 revision，避免已经开局的房间在中途读取到不同模组内容。

#### `module_assets` - 地图、插图和音频

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 资源 ID |
| `revision_id` | UUID FK | 所属模组版本 |
| `asset_key` | VARCHAR(200) | 稳定资源键 |
| `asset_type` | VARCHAR(30) | map/portrait/handout/audio |
| `name` | VARCHAR(200) | 资源名称 |
| `storage_key` | VARCHAR(500) | 对象存储地址 |
| `mime_type` | VARCHAR(100) | MIME 类型 |
| `checksum_sha256` | CHAR(64) | 文件哈希 |
| `source_page` | INTEGER NULL | 来源页码 |
| `source_bbox` | JSONB NULL | 页面裁切坐标 |
| `metadata_json` | JSONB | 尺寸、标签和解锁条件 |
| `generated_by_ai` | BOOLEAN | 是否由 AI 生成 |
| `created_at` | TIMESTAMPTZ | 创建时间 |

## 5. JSONB 和关系表的边界

短期以 `scenario_revisions.content_json` 作为正式模组的唯一事实源，其中保存：

```json
{
  "facts": [],
  "scenes": [],
  "entities": [],
  "clues": [],
  "checkpoints": [],
  "sanity_events": [],
  "triggers": [],
  "endings": [],
  "initial_state": {}
}
```

当前不拆分 Condition、Effect、NPC Goal、Clue Source 等高度多态的子表，避免协议变化导致频繁迁移。

当后台编辑器、搜索或统计出现明确需求时，可以增加 `scenario_scenes`、`module_entities`、`module_clues`、`module_triggers` 等投影表。投影必须由发布流程从 `content_json` 自动生成，不能和 JSON 分别手工维护。

## 6. 发布校验

`ModuleDraft` 只有满足以下条件才能发布：

1. 所有 blocker 和 error 级 `module_import_issues` 已处理；
2. 所有对象 ID 唯一，引用对象存在；
3. 关键对象具有 `source_refs`；
4. 技能、难度、效果和 SAN 公式能被目标规则系统识别；
5. 核心线索至少存在一条可达路径；
6. 结局条件和优先级不存在冲突；
7. 玩家可见内容不包含 Keeper 秘密；
8. `ModuleContent` 通过 Schema 校验并生成校验和；
9. 至少完成一次人工审查和一次模拟跑团。

本次《追书人》已经通过 JSON 合法性、重复 ID、场景引用和 `source_refs` 检查；尚未完成全部人工确认、正式 `ModuleContent` Schema 校验和模拟跑团，因此当前只能作为黄金 Draft，不能直接发布。

## 7. 推荐实施顺序

1. 冻结 `ModuleDraft`、`ValidationReport` 和 `ModuleContent` 首版 Schema；
2. 实现 `module_sources`、`module_import_jobs`、`module_import_artifacts` 和 `module_import_issues`；
3. 实现 `scenarios`、`scenario_revisions` 和 `module_assets`；
4. 使用《追书人》完成 Draft 审查、校验和首次发布；
5. 房间开局时固定使用一个 `scenario_revision`；
6. 再根据编辑器和检索需求增加 Scene、Entity、Clue、Trigger 投影表。

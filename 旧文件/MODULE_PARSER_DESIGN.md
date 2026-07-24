# MODULE_PARSER_DESIGN.md

> 日期：2026-07-14
> 角色：Module Parser Agent 负责人
> 前置：数据模型设计.md / agent设计文档.md / COC_ENGINE_RULE_REQUIREMENTS.md
> 定位：Offline Job。PDF/文档 → Content Layer 数据。不参与游戏循环。

---

## 〇、对齐现有文档

### 0.1 在 Agent 架构中的位置

来自 `agent设计文档.md`：

```
Offline Job — ModuleParser (V3)
  输入: rawText + worldHooks + skillCatalog + schema
  输出: ModulePack + warnings + confidence
  模型: strong + 大上下文 (Claude Opus 200K)
  降级: 人工手动输入 JSON
```

### 0.2 输出目标（Content Layer）

来自 `数据模型设计.md`：

| 模型 | 关键字段 | 存储层 |
|------|---------|--------|
| **World** | `hooks[]`, `variables[]`, `world_rules[]`, `definition` | `worlds` 表 |
| **ModulePack** | `title`, `version`, `world_ref`, `players_min/max`, `difficulty` | `module_packs` 表 |
| **Scene** | `title`, `description`, `exits`, `map_ref` | `module_scenes` 表 |
| **Entity** | `kind`, `name`, `content`, `public_persona`, `secrets`, `stats`, `locked`, `refuse_ops[]`, `state{}`, `rules[]` | `module_entities` 表 |
| **Checkpoint** | `skill`, `difficulty`, `on_success`, `on_fail`, `hidden` | `module_checkpoints` 表 |
| **SanTrigger** | `kind` (六值枚举), `source_tag`, `loss`, `condition` | `module_san_triggers` 表 |
| **WinCondition** | `expr`, `is_ending`, `text` | `module_win_conditions` 表 |
| **Pregen** | `name`, `occupation`, `attributes`, `skills` | `module_pregens` 表 |
| **Asset** | `ref` → `blob_assets.storage_key` | `module_assets` 表 |

---

## 一、字段分类：LLM 提取 vs 人工补充 vs 后处理推导

### 1.1 适合 LLM 自动提取

这些字段是**自然语言描述**，LLM 强项：

| 模型.字段 | 原因 | 置信度 |
|----------|------|--------|
| ModulePack.title | 模组标题，通常在文档第一行或封面 | 🟢 高 |
| Scene.title | 场景名称，通常有章节标题 | 🟢 高 |
| Scene.description | 场景描写——LLM 的核心能力 | 🟢 高 |
| Entity.name | 人物/物品名称 | 🟢 高 |
| Entity.content | 线索内容/物品描述。原文照搬或稍作改写 | 🟢 高 |
| Entity.public_persona | NPC 的表面人设。LLM 擅长概括人物 | 🟢 高 |
| Entity.stats | 属性块——如果原文写了数值，LLM 提取即可 | 🟡 中 |
| Checkpoint.on_success | 成功后发生什么的**描述** | 🟢 高 |
| Checkpoint.on_fail | 失败后发生什么的**描述** | 🟢 高 |
| SanTrigger.condition | 触发条件——自由文本。LLM 可直接提取原文 | 🟢 高 |
| SanTrigger.loss | SAN 损失值——原文通常写"0/1d6" | 🟢 高 |
| WinCondition.text | 结局文本——LLM 强项 | 🟢 高 |
| Pregen 全部 | 预设角色卡——姓名/职业/属性/技能。格式规整 | 🟢 高 |

### 1.2 必须人工补充

这些字段 LLM **会有系统性错误**，必须人工审核或补填：

| 模型.字段 | 为什么 LLM 不行 | 人工需要做什么 |
|----------|----------------|---------------|
| **Entity.secrets** | LLM 会把"秘密"读成"描述"——它区分不了作者写给小熊看的和作者写给 KP 看的 | 逐条核对：NPC 的真实底牌是否正确。模组 PDF 中通常有单独的"守秘人信息"章节 |
| **Entity.rules** | `{"then": {"forbid": true}}` 的生成命中率明显低于 `{"then": {"scale": 0.5}}`。LLM 不想限制玩家（数据模型设计.md §7.6） | 逐条核对：每个 Entity 的 B/C 类 Rule 是否遗漏。对照 19-hook 质询清单 |
| **Entity.refuse_ops** | LLM 会被说服——与 A 类同源的问题。它不觉得"玩家绝对不能拿到这个" | 逐条核对：是否有物品/NPC 应设为"不可转移/不可获取" |
| **SanTrigger.kind** | 六值枚举中 `direct` 和 `check` 极易混淆。LLM 习惯为所有 SAN 损失加检定 | 逐条核对 kind 枚举值 |
| **SanTrigger.source_tag** | 累计封顶的分组键。LLM 不会主动建立"这两处 SAN 来源相同"的关联 | 检查 `capped` 类型的 source_tag 是否正确分组 |
| **WinCondition.expr** | 表达式语法。LLM 会自创不存在的变量名或写错路径 | 逐条核对语法。用符号表校验 |
| **WinCondition.is_ending** | LLM 会把所有条件都当结局——分不清"状态回滚"和"终局" | 逐条核对：《银之锁》没救猫是回滚不是终局 |
| **Checkpoint.difficulty** | 可为空（运行时软判据决定）。LLM 会习惯性填一个值 | 逐条核对哪些 difficulty 应该是 null |
| **Checkpoint.skill** | `@交涉` 这类类别引用——LLM 不理解语法会填成具体技能名 | 逐条核对 SkillRef 格式 |

### 1.3 适合后处理推导

这些字段**不需要 LLM 或人工**——从已有数据自动计算：

| 模型.字段 | 推导逻辑 | 实现 |
|----------|---------|------|
| ModulePack.world_ref | 从上传时用户选择的规则系统确定（当前只支持 `"coc-7e"`） | 代码填充 |
| ModulePack.version | 自动生成 `"1.0.0"`，人工可改 | 代码默认 + 人工编辑 |
| ModulePack.players_min/max | 扫描所有 Checkpoint 和 WinCondition，分析队伍规模引用 | 后处理脚本 |
| Scene.exits | 扫描 Entity 和移动路径描述，推导场景邻接关系 | 后处理脚本（V2） |
| Entity.kind | LLM 给出建议值。后处理校验是否在枚举 {npc, monster, item, clue, animal, object} 内 | 代码校验 + 修正 |
| Entity.state 的引用完整性 | 扫描所有 `Rule.when` 和 `WinCondition.expr`——未被引用的 state key 标记为警告 | 符号表检查脚本 |
| Checkpoint.hidden | 原文有"暗骰"关键词 → true。否则 false | 关键词匹配 |
| Asset.ref → blob_assets | 上传的图片文件自动关联 | 文件管理系统 |

---

## 二、Extraction Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    Extraction Pipeline                           │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ 1. 预处理  │───▶│ 2. LLM   │───▶│ 3. 后处理 │───▶│ 4. 校验   │  │
│  │ 文本提取   │    │ 结构化解析 │    │ 推导+补全 │    │ 符号表+规则│  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│                                                                  │
│  输入: PDF/Markdown/纯文本                                        │
│  输出: ModulePack JSON + Warnings + Confidence                    │
└─────────────────────────────────────────────────────────────────┘
```

### Step 1: 预处理（纯代码）

```
PDF → Markdown 文本提取
  · 工具: PyMuPDF / pdfplumber
  · 输出: 分段 Markdown 文本
  · 保存章节结构（h1/h2/h3 层级）
  · 识别"守秘人信息" vs "玩家信息" 章节边界
```

### Step 2: LLM 结构化解析

```
输入:
  · rawText: 分段后的 Markdown
  · schema: Content Layer 的 JSON Schema 约束
  · worldHooks: 当前规则系统的 hook 清单 (19个，供生成 Rule 时参考)
  · skillCatalog: 合法技能列表 (供生成 Checkpoint.skill 时参考)

Prompt 策略:
  · 分两次调用（降低单次复杂度）:
    Pass 1: 基础信息提取
      → ModulePack.meta + Scene[] + Entity[] (基本信息)
    Pass 2: 机制信息提取
      → Entity.rules[] + Checkpoint[] + SanTrigger[] + WinCondition[]
  · 每次输出严格遵循 JSON Schema

输出:
  · modulePack: 结构化 ModulePack (JSON)
  · unresolved: LLM 无法自信提取的段落列表
  · perFieldConfidence: 每个字段的置信度
```

### Step 3: 后处理推导（纯代码）

```
自动补全:
  · ModulePack.world_ref ← 用户选择的规则系统
  · ModulePack.version  ← 默认 "1.0.0"
  · Entity.kind 校验      ← 枚举白名单检查
  · Checkpoint.hidden     ← 关键词 "暗骰" 匹配

符号表检查:
  · 扫描所有 Rule.when + WinCondition.expr
  · 提取所有被引用的变量名
  · Entity.state 中未被引用的 key → 警告（应改为 publicPersona 自由文本）
  · 引用了未定义变量的 Rule → 错误

引用完整性检查:
  · 所有 SkillRef 是否在 skillCatalog 内
  · 所有 Entity.entity_id 引用是否指向存在的 Entity
  · Scene.exits 是否指向存在的 Scene
```

### Step 4: 校验（见 §三）

---

## 三、Validation Pipeline

### 3.1 四层校验

```
┌──────────────────────────────────────────────────────────────┐
│ Layer 1: Schema Validation（自动 · 无 LLM）                   │
│                                                               │
│  · JSON Schema 结构校验（必填字段、类型、枚举值）               │
│  · 例: SanTrigger.kind ∈ {check, flat, direct,                │
│         max_reduce, gain, capped}                             │
│  · 例: Entity.kind ∈ {npc, monster, item, clue,               │
│         animal, object}                                       │
│  · 失败 → 打回 LLM，重新生成该字段                             │
├──────────────────────────────────────────────────────────────┤
│ Layer 2: Cross-Reference Validation（自动 · 无 LLM）           │
│                                                               │
│  · SkillRef 是否在 skillCatalog 内                            │
│  · entity_id 引用是否存在                                     │
│  · scene_id 引用是否存在                                      │
│  · Rule.hook 是否在 World.hooks 内                            │
│  · Rule.when 语法解析是否合法（Expr 语法）                      │
│  · 失败 → 标记为人工审核项                                    │
├──────────────────────────────────────────────────────────────┤
│ Layer 3: Semantic Validation（自动 + LLM 辅助）               │
│                                                               │
│  · Entity.state 的每个 key 是否被至少一处表达式引用             │
│    未被引用 → 警告（应降级为 publicPersona 自由文本）          │
│  · SanTrigger.source_tag 的同源关联是否正确                    │
│  · WinCondition.is_ending 的语义是否正确                       │
│    触发关键词 "重新" "回到" "返回" → 提示可能应是 is_ending=false│
│  · 失败 → 警告                                                         │
├──────────────────────────────────────────────────────────────┤
│ Layer 4: Human Review（人工 · 必须）                           │
│                                                               │
│  质询清单（按数据模型设计.md §7.6）:                             │
│                                                               │
│  A □ 每个 Entity: 玩家索要/夺取时，是否无论如何都不能得手？       │
│  B □ 每个 Entity: 是否存在某个时刻，无论玩家做什么这件事都发生？  │
│  C □ 每个 Checkpoint: 存在检定成功反而导致更坏结果吗？           │
│  D □ 每个 state key: 它出现在 Rule.when 或 WinCondition.expr 中吗？│
│                                                               │
│  19-hook 空位检查:                                              │
│    对每个 kind ∈ {npc, monster} 的 Entity，                     │
│    逐 hook 检查空位是否需要补 Rule                              │
│                                                               │
│  · B 和 C 的漏报率最高，必须人工逐条审核                         │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 校验结果输出

```json
{
  "modulePack": { ... },
  "validation": {
    "errors": [
      { "layer": 2, "field": "Checkpoint[3].skill", "msg": "skill 'mythos_lore' 不在 COC 7e skillCatalog 中" }
    ],
    "warnings": [
      { "layer": 3, "field": "Entity.cat.state['cat.trusts_player']", "msg": "未被任何 Rule.when 或 WinCondition.expr 引用。建议改为 publicPersona 自由文本" }
    ],
    "humanReviewChecklist": [
      { "item": "B类", "entity": "cat", "hook": "on_scene_enter", "question": "猫是否必须在某个时刻触发牺牲？" },
      { "item": "C类", "checkpoint": "corbitt_int", "question": "INT 检定成功是否导致更坏结果？" }
    ],
    "confidence": 0.82,
    "unresolvedSections": ["地下室隐藏通道的描述未能匹配到任何 Scene"]
  }
}
```

---

## 四、Error Taxonomy

### 4.1 LLM 系统性错误（按频率排序）

| # | 错误类型 | 频率 | 严重度 | 表现 | 原因 |
|---|---------|------|--------|------|------|
| 1 | **B 类遗漏** | 🔴 极高 | 🔴 致命 | 猫必须死的规则没生成。模组结局永不触发 | LLM 的响应式本能——它不会主动想象"玩家什么都没做时会发生什么" |
| 2 | **C 类反转遗漏** | 🔴 极高 | 🔴 致命 | INT 成功=更糟的规则被漏掉。反直觉设计被静默抹除 | LLM 的成败先验相反——它天然觉得 success=好事 |
| 3 | **forbid 类遗漏** | 🟠 高 | 🟡 严重 | 僵尸不会闪避的规则丢失。僵尸只是变强了一点 | LLM 不愿生成限制玩家的规则（数据模型设计.md §7.6） |
| 4 | **secrets 错误** | 🟠 高 | 🔴 致命 | NPC 的真实底牌被当成 publicPersona。信息泄漏 | LLM 区分不了"作者写给 KP 的秘密"和"作者写的人物描述" |
| 5 | **SAN kind 混淆** | 🟠 高 | 🟡 严重 | `direct`（不走检定直接扣）被误标为 `check`（检定式） | LLM 习惯为所有 SAN 损失加检定 |
| 6 | **cap 语义错误** | 🟡 中 | 🟡 严重 | "累加后与 6 比较"被理解成"见过就跳过" | LLM 对"去重"和"累计封顶"的语义混淆 |
| 7 | **state key 膨胀** | 🟡 中 | 🟡 轻微 | 自由文本被误落库——`npc.attitude` 出现在了 entity_states 里 | LLM 想把所有"有状态的描述"都落库 |
| 8 | **WinCondition 全部当终局** | 🟡 中 | 🟡 严重 | 回滚条件（没救猫→重来）被当成 bad ending | LLM 不理解"状态回滚"这个概念 |
| 9 | **difficulty 总是被填值** | 🟢 低 | 🟡 轻微 | 本应运行时决定的 difficulty 被预先填了一个值 | LLM 不喜欢输出 null |
| 10 | **SkillRef 写具体技能而非类别** | 🟢 低 | 🟡 轻微 | `@交涉` 被写成 `persuade` | LLM 不理解类别引用语法 |

### 4.2 按模块分布

```
Entity:
  ██████████ secrets     (40% 的错误在这里)
  ██████     rules       (25%)
  ████       refuse_ops  (15%)
  ██         state keys  (10%)
  ██         stats       (10%)

Checkpoint:
  ██████     skill       (30% — 类别引用 vs 具体技能)
  █████      difficulty  (25% — 不该填的填了)
  ████       on_success  (20%)
  ███        on_fail     (15%)
  ██         hidden      (10%)

SanTrigger:
  █████████  kind        (50% — 六值枚举混淆)
  █████      source_tag  (25%)
  ███        loss        (15%)
  ██         condition   (10%)

WinCondition:
  ████████   expr        (45% — 表达式语法)
  █████      is_ending   (35% — 回滚 vs 终局)
  ███        text        (20%)

Scene / ModulePack / Pregen / Asset:
  ██         错误率低     (<10%)
```

---

## 五、MVP 实现建议

### 5.1 MVP 不做什么

```
✅ MVP 做:
  · Pass 1 基础信息提取（Scene / Entity 基本信息 / Checkpoint 文本 / Pregen）
  · Pass 2 机制信息提取（SanTrigger / WinCondition.text）
  · Layer 1 Schema Validation
  · Layer 2 Cross-Reference Validation
  · 人工审核界面（Web 表单编辑输出的 JSON）

❌ MVP 不做:
  · Entity.rules 自动生成 — MVP 手写 (hook, when, then)
  · Entity.refuse_ops 自动生成 — MVP 人工标记
  · Entity.state 自动提取 — MVP 人工添加 key
  · Layer 3 Semantic Validation — V2
  · 19-hook 质询清单 — V2
  · WinCondition.expr 自动生成 — MVP 人工编写表达式
  · Entity.secrets 自动区分 — MVP 人工填写
```

### 5.2 MVP 流程

```
用户上传 PDF
    │
    ▼
Step 1: 预处理 (PyMuPDF → Markdown)
    │
    ▼
Step 2: LLM Pass 1 — 基础信息
    │  Scene[] + Entity[](name/content/publicPersona/stats)
    │  + Checkpoint[](skill/difficulty/on_success/on_fail)
    │  + Pregen[] + SanTrigger[].condition/.loss
    ▼
Step 3: LLM Pass 2 — 机制信息（可选，MVP 可跳过）
    │  SanTrigger[].kind/.source_tag
    │  + WinCondition[].text/.is_ending
    ▼
Step 4: 后处理推导
    │  填充 world_ref / version / Entity.kind 校验
    ▼
Step 5: Layer 1 + Layer 2 Validation
    │
    ▼
Step 6: 人工审核界面
    │  逐条补填: secrets / rules / refuse_ops / WinCondition.expr
    │  逐条核对: SanTrigger.kind / WinCondition.is_ending
    ▼
Step 7: 输出 ModulePack JSON → 存入数据库
```

### 5.3 MVP 人力估算

| 任务 | 工时 |
|------|------|
| PDF → Markdown 预处理脚本 | 1 天 |
| LLM Pass 1 Prompt + JSON Schema 约束 | 1.5 天 |
| Schema Validation 脚本 | 1 天 |
| Cross-Reference Validation 脚本 | 1 天 |
| 人工审核 Web 界面（简单表单） | 2 天 |
| 端到端联调（导入 1 个模组验证） | 1.5 天 |
| **合计** | **~8 天** |

---

*本文档对齐了数据模型设计.md、agent设计文档.md、COC_ENGINE_RULE_REQUIREMENTS.md 中的所有相关约定。*

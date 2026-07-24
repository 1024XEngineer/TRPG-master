# Agent 模块设计文档

> 日期：2026-07-14
> 定位：定义 AI DM 系统中 Agent 模块的项目目标、架构设计、拆分方案、数据流与协作模式
> 前置阅读：数据模型设计.md / agent-implementation-team-plan.md / COC_ENGINE_RULE_REQUIREMENTS.md

---

## 一、项目目标

### 1.1 要解决的现实问题

跑团（TRPG）爱好者面临一个共同困境：**想玩，但没人愿意当主持人（KP）。**

CoC 跑团对 KP 的要求极高——需熟记数百页规则书、即兴编织恐怖叙事、公正裁决检定、管理多个角色的 SAN 值与私密线索。这导致大量 3-5 人小团体"有玩家、无 KP"，跑团计划一再搁置。

用 AI 替代真人 KP，降低跑团门槛，让"有人就能跑"。

### 1.2 产品形态

一个可运行的 AI DM 系统，支持：

- 玩家自由输入（自然语言描述行动、对话、调查）
- AI 实时响应（旁白叙述、NPC 扮演、规则裁定）
- 确定性规则引擎（检定、战斗、SAN、状态、结局）
- 模组内容导入（PDF/文本 → 结构化数据 → 可运行剧本）

### 1.3 MVP 目标

**跑通一条最小端到端链路**：

```
玩家输入 → 主持 Agent 生成 ActionPlan → 引擎执行 → 返回 ConfirmedOutcome → 主持 Agent 生成回复
```

第一个里程碑：书房调查 Demo——1 个场景、1 个 NPC、2-3 个可交互物体、1 种检定、1 条特殊规则、1 个结局。

### 1.4 核心原则

1. **AI 负责叙事，引擎负责事实。** LLM 擅长语言生成和即兴演绎，但不应直接修改游戏状态。
2. **确定性高于灵活性。** 规则裁定必须是可审计、可重现的。骰子结果不可由 LLM 编造。
3. **信息隔离。** NPC 的秘密、暗骰结果、未发现线索不得进入玩家可见的 LLM 上下文。
4. **先跑通纵向闭环，再横向扩展。** 一个人工 Demo 模组 + 假引擎 → 逐段替换为真实模块。

---

## 二、为什么需要 Agent

### 2.1 单次 LLM 调用无法胜任

直觉上，一个精心提示的 LLM 似乎可以直接当 KP——接收玩家输入，输出叙事和规则裁定。但经过六个真实 COC 模组的逐条验证，**LLM 存在系统性偏向，恰好与"公正裁决"的需求方向相反**：

| 模组 | 规则 | LLM 会怎么做 | 后果 |
|------|------|-------------|------|
| 死者 | 僵尸不会闪避 | 描述僵尸灵活闪避 | 僵尸只是变强一点（可观察） |
| 死者 | 特纳绝不出借小号 | 玩家说服成功，小号到手 | 设定边界被突破（静默失败） |
| 复足 | 手拉手无效 | 三个人手拉手活着走出去 | 结局条件永远不满足（静默失败） |
| 银之锁 | 猫必须死 | 玩家救下了猫 | 模组无法通关（静默失败） |
| 鬼屋 | INT 检定成功 → 更糟 | 成功 = 玩家安全通过 | 反直觉设计被抹除（静默失败） |

**六条全是"限制玩家"的规则。六条漏掉之后玩家都会更开心。这不是巧合。**

### 2.2 LLM 的四种系统性失败模式

这四种模式恰好对应数据模型中的 A/B/C/D 四类引擎介入：

| 类别 | 失败模式 | 为什么 LLM 不行 | 需要什么 |
|------|---------|----------------|---------|
| **A 拒绝** | 它会被说服 | 玩家的理由说得很好，LLM 想让对话舒服地继续 | op 黑名单，引擎强制执行 |
| **B 必然** | 它不会主动想起 | LLM 是被动的，只在玩家说话时被调用。玩家说"我往前走"，LLM 在描述走廊——第 8 轮救下的猫没有任何东西提醒它 | 挂在 hook 上的主动触发器 |
| **C 反转** | 它的成败先验相反 | LLM 天然把 `success` 演绎成好结果。给它一条"成功反而更糟"的规则，它会漏掉或读反 | CheckResolver 强制分支接管 |
| **D 值** | 它是唯一写入者且有动机写错 | 它与"让玩家通关"有利益冲突 | 受保护的变量 + 写入不变式 |

### 2.3 Agent 架构解决的核心问题

单次 LLM 调用 = 一个 prompt in，一个 text out。中间没有：

- **状态隔离**：哪些信息是 KP 私有的，哪些是玩家可见的
- **规则执行**：骰子谁掷、检定谁判、状态谁改
- **审计追溯**：`cat.alive` 是在哪一步变成 `false` 的
- **流程控制**：何时自由叙事，何时暂停等待玩家掷骰，何时触发必然事件

Agent 架构将这些拆分为独立的、可组合的、可审计的模块。

---

## 三、整体架构设计

### 3.1 系统分层

```
┌─────────────────────────────────────────────────────────┐
│                    客户端层                               │
│  玩家输入（自然语言）  ←→  AI 旁白 / NPC 对话 / 检定 UI     │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   Agent 层                               │
│                                                          │
│  ┌────────────────────┐  ┌──────────────────────────┐   │
│  │  主持编排 Agent     │  │   模组导入 Agent（离线）    │   │
│  │  （Runtime）        │  │                          │   │
│  │  · 意图识别         │  │  · Parser Agent           │   │
│  │  · ActionPlan 生成  │  │  · Reviewer Agent         │   │
│  │  · 叙事生成         │  │  · 确定性校验              │   │
│  └────────┬───────────┘  └────────────┬─────────────┘   │
│           │                           │                  │
└───────────┼───────────────────────────┼──────────────────┘
            │                           │
┌───────────▼───────────────────────────▼──────────────────┐
│                  引擎层（确定性，无 LLM）                   │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │CheckResol│ │SAN       │ │Combat    │ │Rule      │   │
│  │ver       │ │Manager   │ │Pipeline  │ │Evaluator │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │GameState │ │EventLog  │ │View      │ │WinCond   │   │
│  │Repo      │ │Writer    │ │Projector │ │Evaluator │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                   数据层                                  │
│                                                          │
│  Reference 层 → Content 层 → GameState 层 → EventLog 层   │
│  (只读规则)    (只读模组)    (可写状态)      (只增事件)     │
└─────────────────────────────────────────────────────────┘
```

### 3.2 为什么 Agent 只负责"上游"和"下游"

**Agent 不参与机械执行，只负责语义理解与自然语言生成。** 中间层由确定性引擎完整接管：

```
上游（Agent 负责）         中游（引擎负责）          下游（Agent 负责）
───────────────────      ──────────────────      ───────────────────
理解玩家意图              检定流水线执行            根据 ConfirmedOutcome
识别动作类型              骰子生成与结果判定         生成旁白叙述
匹配 Checkpoint           Rule 求值                NPC 对话
评估扮演质量              状态变更                  "像什么"的自由演绎
提出 Op 建议              Op 校验与执行
软判据（扮演精彩/合理）     WinCondition 求值         

LLM 可被说服              LLM 无法触及               LLM 不可改写结果
LLM 可能忘记              Hook 主动触发              LLM 不可泄露秘密
LLM 成败先验相反           C 类分支强制接管
```

### 3.3 Agent 与引擎的边界铁律

> **LLM 不得直接写 GameState。它只能提议 Op，由引擎校验后执行。**

```jsonc
// LLM 输出（提议）
{
  "narration": "猫扑到男人脸上，指甲深深陷进他的眼睛。",
  "ops": [
    {"op": "modify", "path": "npc.kidnapper.blind", "set": true},
    {"op": "modify", "path": "cat.alive", "set": false}
  ]
}

// 引擎收到后：
// 1. 校验 path 存在于 entity_states 的键空间
// 2. 校验该 op 符合 allowed_ops 与不变式
// 3. 执行、记账（写 Event）、返回新状态
```

**为什么这条约束不可省**：凡是决定玩家能否通关的状态，不能交给一个想让玩家通关的东西来记。

---

## 四、Agent 拆分方案

### 4.1 总览

系统包含 **两个 Agent 系统**，分别运行在完全不同的生命周期中：

| Agent 系统 | 生命周期 | 触发方式 | 模型需求 | 核心职责 |
|-----------|---------|---------|---------|---------|
| **模组导入 Agent** | 离线（游戏开始前） | 用户上传模组 PDF/文本 | 强模型 + 大上下文 | 将自然语言模组转为结构化 ModuleContent |
| **主持编排 Agent** | 在线（游戏中每回合） | 玩家输入自然语言 | 低延迟 + 稳定输出 | 理解意图 → 生成 ActionPlan → 调用引擎 → 生成回复 |

**为什么是两个而不是一个？**

1. **上下文不同**：导入需要一次读取整个模组（数十页），主持每轮只需要当前场景上下文。
2. **延迟要求不同**：导入可以等几十秒，主持必须在 2-3 秒内响应。
3. **输出结构不同**：导入输出全局数据模型，主持输出单次动作计划。
4. **失败模式不同**：导入错误可人工修正，主持错误玩家立刻体验。

---

### 4.2 模组导入 Agent（Offline）

#### 4.2.1 定位

```
PDF / Markdown / 纯文本  →  ModuleContent JSON  →  存入 Content 层
```

离线作业。不参与游戏循环。一次导入，多次使用。

#### 4.2.2 内部流水线

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 1. 预处理  │───▶│ 2. Parser │───▶│ 3. 后处理 │───▶│ 4. Reviewer│
│ 文本提取   │    │ Agent     │    │ 推导+补全 │    │ Agent +    │
│            │    │ (LLM)     │    │ (代码)    │    │ 人工审核    │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

**Step 1: 预处理（纯代码）**
- PDF → Markdown 文本提取（PyMuPDF / pdfplumber）
- 保存章节结构与段落编号
- 识别"守秘人信息"vs"玩家信息"章节边界
- 生成稳定 `SourceFragment.id`（用于来源追溯）

**Step 2: Parser Agent（LLM，分两次调用）**

Pass 1 — 基础信息提取：
- Scene（场景名称、描述、出口）
- Entity（名称、kind、content、public_persona、stats）
- Checkpoint（技能、难度、成功/失败描述）
- Pregen（预设角色卡）

Pass 2 — 机制信息提取：
- SanTrigger（kind 六值枚举、loss、source_tag）
- WinCondition（text、is_ending）
- Entity.rules（仅标记需要人工补充的候选位置）

**Parser Agent 禁止凭空补造原文没有的机制。** 若原文含糊，应标记 `unresolved_questions`。

**Step 3: 后处理推导（纯代码）**
- 自动填充 `world_ref`、`version`
- Entity.kind 枚举白名单校验
- Checkpoint.hidden 关键词匹配（"暗骰"）
- 符号表检查：扫描所有表达式引用 → 标记未被引用的 state key
- 引用完整性：SkillRef 是否在 skillCatalog 内

**Step 4: Reviewer Agent + 人工审核**

Reviewer Agent 的专项审查：

| 审查项 | 核心问题 | 阻断示例 |
|--------|---------|---------|
| 来源忠实度 | 每个关键事实是否能追溯到原文 | Parser 凭空补出新结局 |
| 机制 A | 是否存在 LLM 会被说服但作者要求绝对拒绝的 Op | "小号绝不转让"却没有 `refuse_ops` |
| 机制 B | 是否存在条件满足后无论如何都必须发生的事件 | 管家进入只写在备注中，没有 Hook |
| 机制 C | 是否存在成功检定反而产生代价或坏结果 | 成功砸柜的文件损毁只写在 prompt 中 |
| 机制 D | Rule/WinCondition 读取的值是否落入受保护状态 | 结局读取但没有初始 state/合法写入口 |
| 秘密隔离 | 未发现秘密是否可能进入 PlayerView | `secrets` 被混入公开内容 |

**A/B/C/D 四类质询清单（必须人工逐条复核）**：

```
A □ 玩家索要/夺取它时，是否无论如何都不能得手？ → refuse_ops
B □ 是否存在某个时刻，无论玩家做什么，这件事都必须发生？ → Rule on on_scene_enter / on_turn_end
C □ 是否存在某个检定，成功反而导致更坏的结果？ → Rule on on_check_resolve
D □ 它是否出现在任何结局条件或规则条件里？ → entity_states
```

**B 与 C 的漏报率最高，必须人工复核——不能只靠 LLM 自检。**

B 需要 LLM 想象"玩家什么都没做时会发生什么"——与它的响应式本能相反。
C 需要它承认"成功是坏事"——与它的成败先验相反。

**19-hook 空位检查**：对每个 `kind ∈ {npc, monster}` 的 Entity，逐 hook 质询：
```
on_dodge_declare → 【空】这个怪物真的能闪避吗？
on_major_wound  → 【空】这个怪物真的会受重伤吗？
```

### 4.2.3 输入与输出

**输入**：
- `rawText`：分段后的 Markdown 文本
- `schema`：Content Layer 的 JSON Schema 约束
- `worldHooks`：当前规则系统的 hook 清单（19 个）
- `skillCatalog`：合法技能列表

**输出**：
- `ModuleContent`：通过 Schema + 引用 + Reviewer + 人工批准的结构化内容
- `ReviewReport`：errors（阻断）/ warnings（可接受）/ coverage（完成度）
- `FixtureCase[]`：用于集成测试的输入-预期输出对
- `EvalCase[]`：用于 Agent 评测的测试用例

#### 4.2.4 字段分工

并非所有字段都由 Agent 提取。三类分工：

| 分工方式 | 字段示例 | 原因 |
|---------|---------|------|
| **LLM 提取** | Scene.description, Entity.name, Entity.content, Checkpoint.on_success, SanTrigger.loss | 自然语言描述，LLM 强项 |
| **人工补充** | Entity.secrets, Entity.rules, Entity.refuse_ops, SanTrigger.kind, WinCondition.expr, WinCondition.is_ending | LLM 存在系统性错误 |
| **后处理推导** | ModuleContent 的元数据字段（world_ref, version）、Entity.kind 校验、Checkpoint.hidden、引用完整性 | 纯逻辑，无需 LLM |

---

### 4.3 主持编排 Agent（Runtime）

#### 4.3.1 定位

```
玩家输入（自然语言）  →  ActionPlan  →  确定性引擎  →  ConfirmedOutcome  →  玩家回复（自然语言）
```

在线。每个玩家回合执行一次。是整个系统的主链路。

#### 4.3.2 核心工作流

```
┌──────────────────────────────────────────────────────┐
│                   主持编排 Agent                        │
│                                                       │
│  玩家输入: "我仔细调查书架"                              │
│     │                                                 │
│     ▼                                                 │
│  ┌──────────────────┐                                 │
│  │ 1. 意图识别       │  ← system prompt + context      │
│  │ 路由: narrative   │     narrative → 直接生成回复     │
│  │    or engine?     │     engine    → 继续步骤 2       │
│  └────────┬─────────┘                                 │
│           │ engine                                     │
│           ▼                                            │
│  ┌──────────────────┐                                 │
│  │ 2. ActionPlan     │  ← 匹配合法动作类型              │
│  │ 生成              │     action_type ∈ {talk,        │
│  │                    │     inspect, check, use_item,   │
│  │                    │     move}                      │
│  │                    │     匹配 Scene.checkpoint_ids   │
│  │                    │     评估软判据（roleplay_tier）   │
│  └────────┬─────────┘                                 │
│           │ ActionPlan (JSON)                          │
│           ▼                                            │
│     ┌──────────────────┐                               │
│     │ 3. 确定性引擎执行  │  ← 不是 Agent！               │
│     │ · 检定流水线       │     LLM 完全无法触及           │
│     │ · Rule 求值        │                              │
│     │ · 状态变更         │                              │
│     │ · EventLog 写入    │                              │
│     │ · 结局判断         │                              │
│     └────────┬─────────┘                               │
│              │ ConfirmedOutcome (JSON)                  │
│              ▼                                         │
│  ┌──────────────────┐                                 │
│  │ 4. 叙事生成       │  ← 根据 ConfirmedOutcome 生成    │
│  │ · 旁白叙述         │    不可改写引擎结果              │
│  │ · NPC 对话         │    不可泄露 secrets             │
│  │ · 感官描写         │    不可泄露暗骰结果              │
│  │ · 公开线索展示      │    不可将失败叙述为成功          │
│  └──────────────────┘                                 │
│                                                       │
│  输出: "你拨开积灰的书册，在书架后方摸到了一把           │
│         冰凉的小钥匙。"                                 │
└──────────────────────────────────────────────────────┘
```

#### 4.3.3 两个路由：narrative vs engine

主持 Agent 必须区分两类玩家输入：

| 路由 | 特征 | 示例 | 处理方式 |
|------|------|------|---------|
| `narrative` | 自由叙事，不需要规则裁定 | "我问管家这里最近有没有怪事" | 直接生成 NPC 对话，不调用引擎 |
| `engine` | 需要检定或状态变更 | "我仔细调查书架" | 生成 ActionPlan → 调用引擎 → 根据结果回复 |

**硬约束：narrative 路由不得修改任何 GameState。** 只有 engine 路由才能提议 Op，且 Op 必须由引擎校验。

#### 4.3.4 行动类型枚举

MVP 最小集合：

```
action_type:
  talk         对话/说服/恐吓（可能触发技能检定）
  inspect      调查/观察（可能触发侦查检定）
  check        明确声明技能检定
  use_item     使用物品/开门/撬锁
  move         移动到另一个场景
```

`CheckRoute` 三种情况：

```
none      不需要检定（纯叙事）
module    命中模组 Checkpoint（加载预定义节点）
default   未命中但需要检定（加载 World.default_checkpoint）
```

#### 4.3.5 叙事约束（硬约束）

1. **不能改写引擎结果。** 引擎判失败 → Agent 不能叙述为成功。
2. **不能泄露秘密。** `Entity.secrets` 永不进入叙事生成的 LLM 上下文。未发现的秘密 → 不可描述。
3. **不能泄露暗骰。** `hidden=true` 的检定，玩家不应知晓"发生了一次检定"，更不应知晓结果。
4. **不能绕过规则。** 引擎 `refuse_ops` 拒绝了操作 → Agent 不能叙述为玩家成功执行。
5. **只能在给定槽位内自由发挥。** 引擎决定了"成功/失败/什么变了"，Agent 只负责"像什么"——感官描写、NPC 语气、氛围渲染。

#### 4.3.6 软判据：roleplay_tier

《蛙蛙村》说服信使的三档难度是 LLM 语义判断的典型场景：

```
玩家："我说服信使"
  roleplay_tier = none        → difficulty = hard
玩家："我告诉信使，村里的人其实在利用他"
  roleplay_tier = reasonable  → difficulty = regular
玩家："我掏出村长的日记，指着那段...（精彩演绎）"
  roleplay_tier = excellent   → difficulty = regular + bonus_die
```

**Agent 评估软判据，输出枚举 → 引擎读枚举，查映射表决定机制。**
判据是软的（LLM 判断）、枚举是硬的（确定性映射）。两者严格分离。

#### 4.3.7 输入与输出

**输入**：
- `player_input`：自然语言字符串
- `runtime_context`：当前场景、角色属性、已发现实体、最近事件
- `module_content`：当前场景的 Entity/Checkpoint/WinCondition
- `game_state`：当前 entity_states、角色状态、pending_check

**输出**：
- `ActionPlan`：{ route, action_type, actor_id, target_id, checkpoint_id?, proposed_skills?, roleplay_tier?, ops? }
- 或直接叙事（narrative 路由）

**引擎返回后**：
- 输入 `ConfirmedOutcome`，输出自然语言回复

---

## 五、核心数据流

### 5.1 端到端回合流程

```
时间轴 →

① 玩家输入
   "我调查书架"
        │
        ▼
② 主持 Agent: 意图识别
   路由判断: 书架在 checkpoints 中 → engine
        │
        ▼
③ 主持 Agent: 生成 ActionPlan
   {
     "route": "engine",
     "action_type": "inspect",
     "actor_id": "pc_1",
     "target_id": "bookshelf",
     "checkpoint_id": "inspect_bookshelf",
     "narrative_intent": "仔细检查书架"
   }
        │
        ▼
④ 引擎: 加载 Checkpoint
   Checkpoint.inspect_bookshelf { skill: "侦查", difficulty: null }
        │
        ▼
⑤ 引擎: 检定流水线
   on_check_declare
   → on_difficulty_calc (roleplay_tier 映射 → difficulty)
   → on_check_roll (auto 模式，静默掷骰)
   → on_check_resolve (判定成功等级 → 执行 C 类 Rule)
        │
        ▼
⑥ 引擎: 状态变更
   entity_states: bookshelf.key_found = false → true
   character.equipment: 追加 "从书架后摸出的小钥匙"
        │
        ▼
⑦ 引擎: 事件写入
   Event { type: "check_resolved", payload: {...} }
   Event { type: "state_modified", payload: {
     path: "bookshelf.key_found", from: false, to: true
   }}
        │
        ▼
⑧ 引擎: 返回 ConfirmedOutcome
   {
     "success": true,
     "facts": ["玩家在书架后发现了钥匙"],
     "state_changes": [{"path": "bookshelf.key_found", "from": false, "to": true}],
     "player_visible_information": ["书架后藏着一把小钥匙"],
     "events": [...]
   }
        │
        ▼
⑨ 主持 Agent: 叙事生成
   输入: ConfirmedOutcome + 场景上下文 + NPC persona
   输出: "你拨开积灰的书册，手指触碰到了冰凉的金属——
          一把小钥匙静静地躺在书架后方的暗格里。"
        │
        ▼
⑩ 返回玩家
   叙事文本 + 可选的 UI 更新（状态面板、物品栏、检定结果）
```

### 5.2 三条核心数据协议

三个协议定义了 Agent 与引擎之间的完整接口：

| 协议 | 生产者 | 消费者 | 解决的问题 |
|------|--------|--------|-----------|
| **ActionPlan** | 主持 Agent | 确定性引擎 | Agent 如何告诉引擎"玩家要做什么" |
| **ConfirmedOutcome** | 确定性引擎 | 主持 Agent | 引擎如何告诉 Agent"最终发生了什么" |
| **ModuleContent** | 模组导入 Agent | 主持 Agent + 引擎 | 场景/实体/规则/检定/结局如何表示 |

这三个协议是三人团队的接口契约。变更需同步更新 Schema、Demo 数据、Mock 和测试。

### 5.3 离线导入流程

```
用户上传 PDF
     │
     ▼
预处理: PDF → Markdown + SourceFragment
     │
     ▼
Parser Agent Pass 1: 基础信息
     │
     ▼
Parser Agent Pass 2: 机制信息（可选）
     │
     ▼
后处理: 推导 + 符号表检查 + 引用完整性检查
     │
     ▼
Schema Validation (Layer 1 + 2)
     │ 失败 → 打回修正
     ▼
Reviewer Agent: 专项审查 (Layer 3)
     │ 阻断 → 打回修正
     ▼
人工审核: A/B/C/D 质询 + 19-hook 空位检查
     │ 阻断 → 人工修订
     ▼
人工批准 → 版本化 ModuleContent → 存入 Content Repository
```

---

## 六、核心 Schema

### 6.1 ModuleContent（模组内容，最小版本）

```jsonc
{
  "world_ref": "coc-7e",
  "scenes": [
    {
      "id": "study",
      "title": "书房",
      "description": "一间积满灰尘的书房。靠墙立着一排书架...",
      "checkpoint_ids": ["inspect_bookshelf", "talk_butler"]
    }
  ],
  "entities": [
    {
      "id": "bookshelf",
      "kind": "object",
      "name": "书架",
      "content": "高大的橡木书架，塞满了发黄的旧书。",
      "secrets": "书架后有一个暗格，里面藏着一把小钥匙。",
      "state": { "key_found": false },
      "rules": []
    },
    {
      "id": "cabinet",
      "kind": "object",
      "name": "上锁的柜子",
      "content": "一只年代久远的木柜。",
      "secrets": "文件藏在柜中。",
      "state": { "opened": false },
      "refuse_ops": ["open"],
      "rules": [
        {
          "hook": "on_interact",
          "when": "bookshelf.key_found == true",
          "then": { "remove_refuse_op": "open" },
          "mode": "append",
          "priority": 10
        }
      ]
    },
    {
      "id": "butler",
      "kind": "npc",
      "name": "管家",
      "public_persona": "一位年迈的管家，穿着整齐的黑色礼服。",
      "secrets": "管家知道柜子的钥匙在书架后面，但不会主动告知，除非玩家态度诚恳。",
      "stats": null
    }
  ],
  "checkpoints": [
    {
      "id": "inspect_bookshelf",
      "match_hint": "调查书架、检查书架、搜索书架",
      "priority": 10,
      "skill": "侦查",
      "difficulty": null,
      "on_success": { "narration_context": "发现了书架后的暗格" },
      "on_fail": { "narration_context": "没有发现异常" },
      "hidden": false,
      "roll_mode": "auto"
    }
  ],
  "win_conditions": [
    {
      "id": "document_found",
      "expr": "cabinet.opened == true",
      "is_ending": true,
      "text": "你打开柜子，找到了那份关键文件。"
    }
  ]
}
```

### 6.2 ActionPlan（动作计划，最小版本）

```jsonc
{
  "route": "engine",                    // "narrative" | "engine"
  "action_type": "inspect",             // talk | inspect | check | use_item | move
  "actor_id": "pc_1",
  "target_id": "bookshelf",
  "checkpoint_id": "inspect_bookshelf", // 可选，引擎会校验归属
  "narrative_intent": "仔细检查书架",
  "proposed_skills": ["侦查"],          // 可选，玩家声明的技能
  "roleplay_tier": "none"               // none | reasonable | excellent，仅 Agent 评估
}
```

### 6.3 ConfirmedOutcome（确认结果，最小版本）

```jsonc
{
  "success": true,
  "facts": [
    "玩家在书架后发现了暗格",
    "暗格中藏有一把小钥匙"
  ],
  "state_changes": [
    {
      "path": "bookshelf.key_found",
      "from": false,
      "to": true
    }
  ],
  "player_visible_information": [
    "书架后藏着一把小钥匙"
  ],
  "roll_result": {
    "skill": "侦查",
    "target_value": 50,
    "roll": 23,
    "tier": "hard_success"
  },
  "events": [
    {
      "type": "check_resolved",
      "checkpoint_id": "inspect_bookshelf",
      "tier": "hard_success"
    },
    {
      "type": "state_modified",
      "path": "bookshelf.key_found",
      "from": false,
      "to": true
    }
  ]
}
```

### 6.4 Rule（规则三元组）

```jsonc
{
  "hook": "on_check_resolve",           // 挂载点（19 个之一）
  "when": "check.tier == 'success'",    // 布尔表达式
  "then": { "apply_condition": "temp_insanity" },  // 算子
  "mode": "override",                   // append | override | forbid
  "priority": 10                        // 执行顺序
}
```

---

## 七、协作模式

### 7.1 Agent ↔ 引擎协作

```
┌──────────────────────┐     ┌──────────────────────┐
│    主持编排 Agent      │     │     确定性引擎         │
│                       │     │                       │
│ · 理解玩家意图         │     │ · 执行检定             │
│ · 路由判断             │     │ · 求值 Rule            │
│ · 软判据评估           │     │ · 执行 Op              │
│ · 生成 ActionPlan      │────▶│ · 更新 GameState       │
│ ·                      │     │ · 写入 EventLog        │
│ · 生成叙事回复          │◀────│ · 判断 WinCondition    │
│ · NPC 扮演             │     │ · 返回 ConfirmedOutcome │
│ · 氛围渲染             │     │                       │
│                       │     │                       │
│  可以做的：             │     │  绝不能交给 Agent 的：   │
│  ✓ 即兴演绎            │     │  ✗ 掷骰                │
│  ✓ 生成 NPC 对话       │     │  ✗ 修改 game state     │
│  ✓ 描写感官细节         │     │  ✗ 执行 Rule           │
│  ✓ 评估扮演质量         │     │  ✗ 判定结局             │
│                       │     │  ✗ 绕过 refuse_ops     │
└──────────────────────┘     └──────────────────────┘
```

**协作协议**：

1. Agent 只能通过 `ActionPlan` 发起引擎调用
2. 引擎只能通过 `ConfirmedOutcome` 返回结果
3. Agent 不可在叙事中改写 ConfirmedOutcome 的任何事实
4. 引擎不可自行决定"玩家想做什么"——那是 Agent 的职责
5. Engine 返回的结果是"发生了什么"（facts），Agent 负责"像什么"（如何描述）

### 7.2 模组导入 Agent ↔ 主持编排 Agent 协作

模组导入 Agent 是生产者，主持编排 Agent 是消费者。两者通过 `ModuleContent` 协议耦合：

```
模组导入 Agent（离线）
     │
     │ ModuleContent（只读，存在 Content 层）
     │
     ▼
主持编排 Agent（在线）
  · 读取 Scene.description → 场景氛围
  · 读取 Entity.content / public_persona → NPC 扮演
  · 读取 Checkpoint → 动作匹配
  · 读取 secrets → 绝不进入叙事上下文
```

**信息隔离由主持 Agent 的上下文组装层保证**：

```python
def build_narration_context(scene, entities, game_state):
    """只有公开信息进入叙事 LLM 上下文。"""
    return {
        "scene_description": scene.description,
        "visible_entities": [
            {
                "name": e.name,
                "content": e.content,
                "public_persona": e.public_persona
                # secrets 不在此处
            }
            for e in entities
            if is_visible(e, game_state)  # 未发现的实体也不在此处
        ],
        "recent_events": get_player_visible_events(game_state.events),
        "party_status": get_public_state(game_state)
    }
```

### 7.3 三人分工与接口契约

按 `agent-implementation-team-plan.md` 的分工方案：

```
成员 A: 主持编排 Agent
  ├── 消费: ModuleContent (来自成员 C)
  ├── 生产: ActionPlan (给成员 B)
  ├── 消费: ConfirmedOutcome (来自成员 B)
  └── 生产: 自然语言回复 (给玩家)

成员 B: 确定性规则引擎
  ├── 消费: ActionPlan (来自成员 A)
  ├── 消费: ModuleContent 中的 Rule/Checkpoint/WinCondition (来自成员 C)
  ├── 生产: ConfirmedOutcome (给成员 A)
  └── 维护: GameState + EventLog

成员 C: 模组数据与解析
  ├── 生产: ModuleContent (给成员 A + B)
  ├── 生产: FixtureCase / EvalCase (给三人共享测试)
  └── 维护: Schema 校验 + Reviewer Agent + 人工审核流程
```

**三人必须共同确定的三个协议**：
1. `ModuleContent` 的结构与字段语义
2. `ActionPlan` 的动作类型枚举与字段
3. `ConfirmedOutcome` 的事实格式与状态变更表示

### 7.4 信息隔离全景图

```
                    ┌──────────────────────┐
                    │   Entity.secrets     │
                    │   Checkpoint.hidden  │
                    │   DM-only 信息        │
                    │                      │
                    │   NEVER enters        │
                    │   narration context   │
                    └──────────────────────┘

┌──────────────────────┐     ┌──────────────────────┐
│  模组导入 Agent       │     │  主持编排 Agent       │
│                       │     │                       │
│  可以读所有内容        │     │  secrets → 永不进入    │
│  包括 secrets         │     │  叙事上下文            │
│  职责：正确分类        │     │  职责：信息隔离         │
│  公开/秘密             │     │                       │
└──────────────────────┘     └──────────────────────┘

┌──────────────────────────────────────────────┐
│              确定性引擎                        │
│                                               │
│  hidden=true 检定:                             │
│    → 不创建 pending_check                     │
│    → 不向任何玩家暴露"发生了一次检定"          │
│    → 骰值仅写入 EventLog（审计用途）            │
│                                               │
│  LLM 提议的 Op:                                │
│    → 校验 secret 信息不通过 Op 泄露             │
│    → 校验不变式                                │
│    → 拒绝时 Agent 收到拒绝原因（不含秘密）       │
└──────────────────────────────────────────────┘
```

---

## 八、MVP 实施路径

### 8.1 开发顺序

```
第 0 步：确定目录结构 + 统一术语 + 三个核心 Schema
第 1 步：人工编写 demo-module.json（书房场景）
第 2 步：实现假引擎（Mock Engine）
第 3 步：跑通主持 Agent 闭环
        玩家输入 → ActionPlan → 假引擎 → ConfirmedOutcome → 回复
第 4 步：逐步替换为真实引擎
        检定 → 状态变更 → EventLog → Rule → WinCondition
第 5 步：实现模组解析 Agent
        PDF → ModuleContent（与人工 Demo 同结构）
第 6 步：增加导入审查 Agent
        Parser 输出 + 原文 → ReviewReport → 人工批准 → 发布
```

### 8.2 当前阶段不做

- 完整 COC 规则（MVP 仅需 P0 的 9 项）
- 多场景大型模组
- 多人同时行动
- 完整 Condition / Ledger / 战斗流水线
- 双 Agent 运行期拆分
- 三套复杂人格 Prompt

### 8.3 避免的错误

1. **不要把 Agent 当自由聊天机器人。** 使用明确编排的工作流：何时调用哪个模块 → 传递什么数据 → 输出什么结构。
2. **不要过早追求完整实现。** 先用人工模组和假引擎跑通纵向闭环，再逐个替换为真实模块。
3. **不要跳过 Schema 设计直接写 Agent。** 三个协议是三人接口——先定 Schema，再各自实现。
4. **不要让 Agent 自主决定修改 GameState。** Op 提议必须经引擎校验。
5. **不要三个人各自独立开发后才集成。** 每天至少跑一次端到端主链路。

---

## 九、总结

```
AI DM 系统 = 模组导入 Agent（离线） + 主持编排 Agent（在线） + 确定性引擎

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  模组导入 Agent   │ ──▶ │    确定性引擎     │ ◀── │  主持编排 Agent   │
│                  │     │                  │     │                  │
│  PDF → JSON      │     │  · 检定          │     │  · 意图识别       │
│  Parser+Reviewer │     │  · Rule(hook,    │     │  · ActionPlan    │
│  +人工审核        │     │    when, then)   │     │  · 叙事生成       │
│                  │     │  · 状态/事件      │     │  · 信息隔离       │
│  ModuleContent   │     │  · 结局判断       │     │                  │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
    Content 层               GameState 层            自然语言回复
    (只读模组)               EventLog 层             (给玩家)
                            (可写状态+只增事件)

核心哲学：
  · LLM 负责上游（理解意图）和下游（生成叙事）
  · 引擎负责中游（执行规则、维护状态）
  · LLM 只能提议 Op，引擎校验后执行
  · 凡是决定玩家能否通关的状态，不能交给想让玩家通关的东西来记
  · A/B/C/D 四类机制是引擎介入的边界——四类之外，纯文本交给 LLM 自由演绎
```

---

*本文档对齐了数据模型设计.md、agent-implementation-team-plan.md、COC_ENGINE_RULE_REQUIREMENTS.md、MODULE_PARSER_DESIGN.md、如何应对动态机制.md、数据库修改建议.md 和 成员C-模组解析与审查Agent流程架构.md 中的所有相关约定。*

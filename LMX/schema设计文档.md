# AI DM 平台 · 设计文档

> 本文档用于说明一个**模组驱动的 AI TRPG 主持平台**如何组织规则、设定、模组、人物卡与运行时状态。
> 文档以 **COC(克苏鲁的呼唤,第七版)** 为主要示例,重点定义内容拆分方式、核心 Schema、规则引擎与大模型的职责边界。
> 目标读者是参与平台设计、开发、内容结构化和模组解析工作的团队成员。
> 说明:整体产品架构仍待进一步讨论,本文档先聚焦规则内容与数据模型。

---

## 文档总览(讲解版)

这份设计文档的核心观点可以压缩成一句话:

> AI DM 平台不是把整本规则书喂给大模型,而是把规则、设定、模组、人物卡和运行状态拆成结构化数据,由引擎负责确定性运算,由 LLM 负责叙事演绎。

讲解时可以按下面这条主线展开:

```
规则书/设定/人物卡/模组
        ↓ 结构化
Script IR + Rule Module + Runtime State
        ↓
玩家行动 → Intent → 引擎校验/掷骰/结算/写 State → Resolution
        ↓
LLM 只读取已裁剪的 narration_context,负责把结果讲成故事
```

| 章节 | 内容 | 讲解重点 |
| --- | --- | --- |
| §0-§1 | 平台定位与核心原则 | 模组驱动;数值和规则走引擎,叙事走 LLM |
| §2 | 整体架构占位 | 架构尚未定稿,这里只记录分层方向 |
| §3 | 规则、设定、模组的关系 | 规则由平台提供;具体设定以模组为准,默认设定库兜底 |
| §4 | COC 规则书 A/B/C/D 拆分 | A 规则机制、B 结构化数据、C 风格基调、D 玩家引导 |
| §5 | 数据模型 Schema | Location 管空间,TriggerBlock 管时序,Ending 管通关,Runtime State 管运行真相 |
| §5.7.1 | 信息作用域 Scope | 多人可见性按 private/location/party/global 确定性过滤 |
| §5.10 | 人物卡 Schema | 调查员包含建卡、属性、资源、技能、背景、装备、经历和成长 |
| §6 | 输入输出格式 | Intent 是唯一引擎入口,Resolution 是引擎出口和信息隔离落点 |
| §7 | COC 技能表 | 固定技能 + 专精技能 + 技能点来源拆分 |
| §8 | LLM 参与边界 | LLM 解析 Intent 和演绎结果,引擎校验/结算/写 State |
| §9 | 第一版范围建议 | 先跑通一个自包含模组,保留多人、DND、完整库等扩展口 |
| 附录 | 待定事项与术语 | 记录架构待定项和核心术语定义 |

下方正文更偏查阅材料:包含分类依据、Schema 示例、字段说明、边界表和后续可转为提示词/开发任务的规则。

---

## 0. 一句话定义

一个**模组驱动的 AI 主持平台**:玩家上传 TRPG 模组,平台解析成结构化数据,AI 担任 DM 主持游戏。核心是把**大模型的创造性叙事**与**确定性的规则/数值运算**解耦。

本文档以 **COC(克苏鲁的呼唤,第七版)** 为唯一示例贯穿说明。

---

## 1. 核心设计原则(准绳)

1. **确定性运算走引擎,创造性叙事走 LLM。** 数值、检定、骰点、资源增减一律由确定性代码执行;只有需要创造力的叙事、演绎、临场裁决才调用大模型。
2. **规则是数据,不是硬编码。** 引擎是"规则解释器",读取规则定义来运算。换规则系统 = 换数据,不改引擎代码。
3. **State 是唯一真相源。** LLM 永远不直接改 state,只能通过工具调用提议变更,由引擎裁决后写入。
4. **事实靠 state,叙事靠 memory,两者分离。**
5. **能结构化的就别用 LLM。** 凡能收敛成结构化输入/运算的都走确定性路径,把 LLM 调用压到最少。
6. **模组 > 设定库 > LLM 即兴。** 内容来源优先级:模组明确写的绝对优先;模组引用标准元素但没详述的查设定库补全;都没有的才由 LLM 按风格发挥。

---

## 2. 整体架构 【待定 · 留空】

> 本节留待架构讨论后填写。目前仅记录已达成的方向性共识,细节未定。

已达成的方向性共识(非最终):

- 分层解耦:输入输出层 / DM Agent(LLM)/ 规则引擎(确定性)/ State Store / 剧本 IR
- 语音作为可插拔层,后期叠加,核心只处理"文字 + 是谁说的"
- 数值运算全程不经过 LLM

**待确定事项:**

- [ ] 各层的具体边界与调用关系
- [ ] Agent 是单体还是多智能体(DM / NPC / 裁判一致性 Agent)
- [ ] Intent / Resolution 接口与各层调用关系
- [ ] 记忆/上下文管理的具体机制
- [ ] 多人并发下的 state 共享与回合调度

---

## 3. 三个核心概念

一局游戏所需的内容可以拆成三部分:规则、设定、模组。三者在系统里走的路径不同,必须分清。

| 概念  | 举例                      | 系统中的形态                 | 谁负责              |
| --- | ----------------------- | ---------------------- | ---------------- |
| 规则  | d100 检定、技能、战斗、SAN、魔法    | A/B/C/D 四类(见 §4)         | 平台构建             |
| 设定  | 神话生物、禁书、1920 年代背景、装备、术语 | 模组设定 + 默认设定库(B/C 类)     | **模组优先**,平台默认库兜底 |
| 模组  | 具体的地点、NPC、线索、结局         | 剧本 IR                  | 用户上传 + 官方        |

这里的"规则 / 设定 / 模组"是内容来源的三分法;§4 的 A/B/C/D 是处理路径的四分法。**D 类玩家引导不是第四种世界内容**,而是把规则、设定、模组 IR 和 Runtime State 投影成玩家能读懂的展示文本。

**关键推论一:规则书需要拆为"规则"和"设定"。** 检定/战斗/SAN 是规则,神话生物、装备表、术语是设定。二者性质不同(见 §4 的 A/B/C/D 拆分)。

**关键推论二:COC 规则 ≠ 克苏鲁设定。** COC 是规则,默认搭配克苏鲁神话,但可以拆开。《半步之遥》用 COC 规则却跑民国佛教业报,与神话无关。所以平台顶层按**规则系统**(COC)分区;具体世界观、怪物形态、年代细节和禁书/组织等设定应**优先服从模组**。平台可以提供一套默认克苏鲁设定库,但它只是兜底补全,不是覆盖模组作者设定的权威。

**关键推论三:一局游戏实际需要的,是"规则 + 该模组 + 少量补全设定",不是整本书。** 模组是自包含的——KP 跑本子靠"脑子里的规则 + 手边这个本子",不重读整本规则书。系统同理:DM 运行时只需"引擎(规则)+ 模组 IR + 按需检索的默认设定",**不需要把整本规则书喂给 LLM**。默认设定库只用于模组没写清楚但引用了标准元素的场景。

---

## 4. COC 规则书内容的 A/B/C/D 四类拆分 【本文档核心】

一本 COC 规则书里的内容**不是一类东西**,而是四种用途完全不同的内容集合。**混在一起处理是最大的认知错误。** 必须先拆成 A/B/C/D 四类,再让每类走自己的技术路径。

### 4.1 为什么必须拆分

同一本规则书同时承担四种职责:

- 给引擎执行的规则:检定、战斗、追逐、SAN、伤害计算。
- 给数据库保存的事实:技能表、职业表、装备表、武器表、怪物属性。
- 给 LLM 激活的风格:宇宙恐怖、1920 年代氛围、守秘人主持方法。
- 给玩家阅读的上手说明:背景介绍、规则摘要、模组导语、当前行动提示。

核心判断:**规则书不是一份要整体喂给 LLM 的文本,而是四种不同用途的内容集合。** A/B/C 是系统内部事实源,D 是面向玩家的展示投影。

### 4.2 四类内容总览

| 类别              | 服务对象     | 本质        | 系统形态                       | 是否喂给 LLM        | 举例                         |
| --------------- | -------- | --------- | -------------------------- | --------------- | -------------------------- |
| **A · 规则机制**    | 引擎       | "怎么运算"    | Rule Module 代码/数据          | **否**           | 检定系统、战斗系统、追逐轮、SAN 机制、伤害计算 |
| **B · 结构化数据**   | 引擎 / 数据库 | "事实清单"    | 结构化数据库 + 硬约束               | 否(部分按需检索)       | 技能表、装备/武器表、神话生物属性、术语表、职业表 |
| **C · 风格基调**    | LLM      | "氛围和品味"   | 提示词 + 少量范例                 | **是**           | 宇宙恐怖、1920 年代语气、第十章 KP 方法  |
| **D · 玩家可读引导** | 人类玩家     | "人话摘要/提示" | 展示文本(投影自 A/B/C + 模组 + 状态) | 否               | 新手规则说明、背景引导、模组导语、技能按钮说明  |

### 4.3 A/B/C/D 的关系:事实源与投影

A/B/C 服务的是系统内部:D 是直接展示给玩家看的内容。D 类**不参与任何运算,不喂给 LLM 做叙事**,它的职责是把 A/B/C 和模组 IR 中的关键信息转成人能快速理解的说明。

```
A 类规则(引擎里的 d100 检定逻辑)
    └──投影/摘要──→ D2 玩家规则引导("掷 d100,骰值 ≤ 你的技能值就成功")
                    ← 同一套规则的"人话版",不是独立维护的另一份规则
```

**关键纪律:D 类是"投影",不是"另写一份"。** A/B/C 是唯一事实源,D 类基于它们编写展示文本;规则或数据变更时,D 类必须同步更新,防止"系统实际规则"和"玩家看到的说明"打架。实践中 D 类通常需要人工润色,因为直接从引擎逻辑自动生成的文本太干,但事实源始终是 A/B/C。

### 4.4 COC 第七版规则书逐章归类(完整,基于官方目录)

> 依据 COC 第七版规则书完整目录整理。归类标注:A=规则机制(引擎)、B=结构化数据(数据库)、C=风格基调(提示词)、D=玩家可读引导(展示文本),参考=仅供团队理解不入系统。规则书章节通常主要贡献 A/B/C;D 多数由 A/B/C 与模组 IR 摘要生成,而不是直接照搬规则书原文。

| 章节                           | 页码  | 归类               | 说明                                                 |
| ---------------------------- | --- | ---------------- | -------------------------------------------------- |
| 第一章 游戏介绍(概述/示例/用具)           | 10  | 参考 + **C**       | 理解性内容,给团队看;不入系统                                    |
| 第二章 洛夫克拉夫特与克苏鲁神话             | 20  | **C**            | 世界观基调来源,提炼进风格提示词                                   |
| 第三章 创建调查员                    | 28  | **A + B**        | 建卡算法(属性生成/技能点分配)是 A;范例职业、速查表是 B                    |
| ├ 半值/五分之一值速查表                | 49  | **A**            | 困难/极难成功阈值算法,引擎运算                                   |
| **第四章 技能(技能列表)**             | 52  | **A + B**        | 技能清单是 B,检定基础值是引擎输入。**刚需,第一版必做(见 §4.6)**            |
| 第五章 游戏系统(检定/奖励惩罚骰/成长)        | 80  | **A**            | 核心检定机制,引擎                                          |
| 第六章 战斗(战斗轮/持械/战技/护甲/射击/伤害治疗) | 100 | **A**            | 全是运算机制,引擎                                          |
| ├ 范例毒剂                       | 129 | **B**            | 毒剂效果数值,数据表                                         |
| 第七章 追逐(建立追逐/追逐轮)             | 130 | **A**            | 追逐机制,引擎                                            |
| 第八章 理智(SAN检定/疯狂/发作/治疗恢复)     | 152 | **A(机制)+ B(清单)** | SAN 机制/疯狂发作是 A;范例躁狂症、恐惧症清单是 B                      |
| 第九章 魔法(使用/学习法术/成为相信者)        | 164 | **A(机制)**        | 施法/学法规则是 A(具体法术见第十二章)                              |
| ├ 神话典籍                       | 164 | **B**            | 典籍清单/效果,数据表                                        |
| **第十章 述行游戏(游戏主持)**           | 182 | **C(核心)**        | KP 主持方法论——**提炼为 DM Agent 核心系统提示词(见下方注1)**          |
| ├ 非玩家角色(NPC)                 | 189 | **C + A/B**      | NPC 扮演指导是 C;NPC 属性结构是 A/B                          |
| ├ 灵感检定                       | 199 | **A**            | 检定机制变体,引擎                                          |
| 第十一章 可怖传说书籍(死灵之书等)           | 222 | **B**            | 神话典籍库,数据表(含 SAN 损失、可学法术)                           |
| 第十二章 神话法术(法术/深层魔法/法术列表)      | 240 | **A(结算)+ B(清单)** | 法术效果结算是 A;法术列表是 B                                  |
| 第十三章 神话造物和异星科技               | 266 | **B**            | 造物/科技物品库,数据表                                       |
| **第十四章 怪物、野兽和外星诸神**          | 276 | **B(属性)+ C(描述)** | 属性块是 B(给引擎);形象/恐怖描述是 C(给 LLM 演绎)。**入库时拆开存(见下方注2)** |
| ├ 神话名词发音                     | 280 | **C**            | 术语,参考                                              |
| 第十五章 附录 I 不朽表                | 346 | **A**            | 规则表,引擎                                             |
| ├ 附录 II 转换到第七版               | 350 | 参考               | 版本迁移说明,不入系统                                        |
| **├ 附录 III 装备列表(20年代/现代)**   | 356 | **B**            | 装备库,数据表(约束超纲 + 补全)                                 |
| **├ 表17 武器列表(20年代/现代)**      | 359 | **B**            | 武器库(伤害/射程/价格),数据表                                  |
| ├ 游戏规则摘要                     | 367 | **A**            | 规则速查,引擎实现的参照                                       |
| **├ 调查员角色卡(20年代/现代)**        | 392 | **B(模板)**        | **人物卡 schema 的官方蓝本,重点参考(见下方注3)**                   |
| 索引                           | 384 | 参考               | —                                                  |

**四类汇总:**

- **A → Rule Module 引擎(不喂 LLM)**：建卡算法、游戏系统、战斗、追逐、SAN 机制、施法规则、法术结算、灵感检定、不朽表、速查表、规则摘要
- **B → 数据库(查表 + 约束)**：技能表(核心刚需)、范例职业、毒剂、恐惧/躁狂症清单、典籍库、法术列表、造物库、怪物属性、装备表、武器表、角色卡模板
- **C → 提示词 + 范例**：洛夫克拉夫特与克苏鲁神话(世界观)、**第十章述行游戏(DM 行为核心来源)**、怪物形象/恐怖描述、神话发音术语
- **D → 玩家展示文本(不喂 LLM)**：背景引导、规则引导、模组导语、运行时情境提示。D 不直接来自整本规则书,而是从 A/B/C、模组 IR 和运行时状态投影/摘要出来

**三条重点注解:**

> **注1 · 第十章"述行游戏"是 C 类的金矿,用途特殊。** 它不是世界观,而是**官方教 KP 怎么主持**的方法论(如何展现神话恐怖、如何处理 NPC、如何创作剧情)。应提炼为 **DM Agent 的核心系统提示词**。它也会影响 D 类玩家提示的语气,但事实源仍然是 C。

> **注2 · 第十四章怪物"一章横跨 B 和 C"。** 每个怪物 = 属性块(B,给引擎算战斗/SAN 损失)+ 形象描述(C,给 LLM 演绎恐怖)。解析入库时**两部分拆开存**:属性进结构化字段,描述进给 LLM 的文本字段。复用 §5.9"剧本 IR 与实体设计"里的属性块型 / 纯机制型实体思路。

> **注3 · 附录 III / 表17 / 角色卡模板 是最该先"照抄"的 B 类数据。** 装备表、武器表是现成结构化清单;**角色卡模板直接是人物卡 schema 的官方蓝本**——建卡和按钮系统对着它设计字段即可,不必自己发明。

### 4.5 四类各自的处理方式

**A 类 · 规则机制 → Rule Module(引擎)**

- 形式化成引擎能执行的数据 + 代码,**不喂 LLM**。
- 理由:让 LLM 记规则、临场算 SAN 会算错、会漂移;引擎执行则精确、瞬时、可控。
- 例:"1/1D6 理智损失"由引擎读规则掷骰扣 SAN,而非让 LLM 模拟这个规则。
- **只需把规则形式化一次(做成 Module),不需每次对话把规则书喂进上下文。**

**B 类 · 结构化数据 → 数据库 + 硬约束**

- 做成结构化数据表,承担两个作用:
  1. **约束**:玩家/LLM 不能凭空造出库外的东西(防超纲)。例:玩家想在 1920 年代掏出 AK47 → 查装备库不存在 → 引擎拒绝。**这种约束必须靠结构化数据,提示词是软约束会漏。**
  2. **补全**:模组没详述的标准元素,从库里查补进 IR。例:模组只写"出现一只深潜者" → 从生物库查其属性和描述。
- 大模型对 B 类事实**不可靠**(生物属性、物品价格会幻觉),所以精确事实一律走数据库,不靠 LLM 记忆。

**C 类 · 风格基调 → 提示词 + 范例**

- 大模型**内置**克苏鲁的"风格知识"(宇宙恐怖基调、洛式语气、1920 年代氛围),可用提示词有效激活:"你是一位克苏鲁 COC 守秘人,营造宇宙恐怖氛围,强调人类渺小与未知恐惧,语言克制阴郁……"
- 但大模型的设定知识**不精确、不受控**,只能用于"风格",涉及具体事实时必须查 B。
- 几乎零成本,第一天就能有。

**D 类 · 玩家可读引导 → 展示层文本**

D 类内部再分四子类,因为来源、展示时机、复用范围不同:

| 子类          | 内容                           | 提炼自       | 展示时机        | 复用范围          |
| ----------- | ---------------------------- | --------- | ----------- | ------------- |
| **D1 背景引导** | 世界观、年代、基调(1920 年代、宇宙恐怖是什么)   | C 类(世界观)  | 进入分区 / 开局前  | **平台级,跨模组复用** |
| **D2 规则引导** | 怎么玩:d100 怎么掷、SAN 是什么、检定成败怎么看 | A 类(规则机制) | 首次游玩 / 随时可查 | **平台级,跨模组复用** |
| **D3 模组导语** | 这个模组讲什么、你扮演谁、开场情境            | 模组 IR     | 开局时         | 每个模组独有        |
| **D4 情境提示** | 当前能做什么、可用技能按钮的说明             | 运行时状态     | 游戏中随时       | 运行时动态生成       |

**为什么必须分开(回答"背景和规则要不要分"):** 因为来源和更新时机不同。

- **D1 背景 + D2 规则**是**平台级、跨模组复用**的——所有 COC 模组共用同一套"什么是 1920 年代""d100 怎么掷"。写一次,所有模组通用。
- **D3 模组导语**每个模组独有,跟着模组 IR 走。
- **D4 情境提示**运行时动态生成(如根据人物卡技能生成按钮说明)。

若不分开、混成一坨,会导致每个模组都要重写背景和规则说明,浪费且不一致。

### 4.6 特别说明:技能表横跨 A 和 B(最易混淆,但最重要)

技能表看似是 B(有哪些技能),但它同时是 A 的必要输入(检定要用基础值),还是输入层按钮系统的数据源:

```
"教育检定" 这一次检定:
  ├── "COC 有'教育'这项技能" ......... B(清单)
  ├── "教育基础值是多少" ............. B(数据)→ 引擎检定要用
  └── "d100 ≤ 教育值 判成败" .......... A(规则)→ 引擎执行
```

**因此技能表是刚需,必须第一版做。** 且模组按惯例**不会写**技能定义(默认平台提供),没有它连优质模组也跑不动——见 §7。技能表本身不属于 D,但 D4 会引用技能表和人物卡,生成"你现在可用哪些技能按钮"的玩家说明。

### 4.7 内容来源优先级(模组 vs 设定库 vs LLM)

当模组、设定库、LLM 三者可能冲突时,裁决顺序:

```
1. 模组明确写了的 → 绝对遵照模组(作者设定最高)
   例:《某模组》说"外域恐怖是黑色水母状",就按这个,不管标准克苏鲁怎么描述
2. 模组没写但引用了标准元素 → 查 B 类设定库补全
   例:模组只写"一只深潜者"没详述 → 从生物库查
3. 模组和设定库都没有 → LLM 按 C 类风格即兴
   例:某路人 NPC 说什么话 → LLM 按 1920 年代 + 克苏鲁氛围自由演

核心:模组 > 设定库 > LLM 即兴。越具体的来源优先级越高。
设定库是"填空默认值",不是"覆盖模组的权威"(模组作者常魔改标准设定)。
```

对 D 类也一样: **D3 模组导语必须服从模组 IR**,不能用平台通用背景或 LLM 即兴内容覆盖模组作者设定。D1/D2 是平台级默认说明,D3 是本模组专属入口,D4 是运行时状态提示。

### 4.8 第一版落地范围

第一版不需要把整本规则书全部结构化,但必须先覆盖能跑起来的最小闭环:

| 类别 | 第一版必做                                | 可后置                              |
| --- | ------------------------------------ | -------------------------------- |
| A   | 基础 d100 检定、技能检定、SAN 基础机制、基础资源增减       | 完整战斗、追逐、法术、疯狂发作细则               |
| B   | 技能表、人物卡字段、基础角色资源、核心检定输入              | 完整装备库、武器库、怪物库、典籍库、法术库           |
| C   | COC 守秘人风格提示词、第十章主持原则摘要、基础克苏鲁氛围       | 更多范例、不同年代/地区的风格包                 |
| D   | D1 背景引导、D2 新手规则引导、D4 技能按钮/当前行动说明      | 更精细的 D3 模组导语模板、个性化新手教程、复杂帮助系统 |

---

## 5. 数据模型(Schema)设计

场景不是只有"地点里有什么",还包括"什么时候发生、是否已经发生过、发生后写入什么状态"。因此 Schema 必须同时建模**空间结构**和**时序结构**:空间结构放在 Location,时序结构放在 TriggerBlock,运行结果写入 Runtime State。

### 5.1 Schema 分层:Core / Module / IR / State

**通用框架放 Core,规则专有部分放 Module,模组解析结果放 Script IR,运行中变化放 Runtime State。** 即使当前只做 COC,也按此分层组织,以便将来加 DND 等时 Core 可复用、不必重构。

```
Core Schema(通用框架)
├── Intent / Resolution 输入输出契约
├── Location        地点/空间容器
├── Narration       叙事文本(表象/真相分离)
├── Interactable    可交互元素
├── TriggerBlock    时序触发块
├── Scope           信息作用域/多人可见性过滤
├── Ending          通关/失败条件定义
├── Check           检定原语
├── Effect          引擎效果
├── Entity / Item   实体与物品
└── Resource        通用可增减数值

COC Rule Module(COC 专有,对应 §4 的 A 类 + B 类核心)
├── 属性系统(百分比)
├── 检定规则(d100 ≤ 技能值,低优;困难/极难;奖励骰/惩罚骰)
├── 技能表(固定核心 + 可扩展槽位,见 §7)
├── SAN 理智系统(含 "X/YdZ" 损失语法与同源去重)
└── 战斗 / 追逐 / 法术等机制

Script IR(模组解析结果)
├── Meta / Location / Entity / Item / Asset
├── TriggerBlock 列表(挂载到地点、实体或全局)
└── Ending / FailCondition 列表

Runtime State(运行时唯一真相源)
├── 玩家资源与人物卡状态
├── 玩家位置 / 队伍 / 并行场景线程
├── 已触发事件 / 已访问地点 / 已揭示线索
├── NPC 状态 / 物品归属 / 场景 flag
└── 规则模块需要的历史记录
```

### 5.2 Core 原语总览

| 原语              | 作用                         | 是否随运行变化 | 主要服务对象        |
| --------------- | -------------------------- | ------- | ------------- |
| `Intent`        | 玩家行动的统一结构化入口              | 否       | 引擎           |
| `Resolution`    | 引擎执行后的统一结构化输出             | 否       | 引擎 + LLM      |
| `Location`      | 承载地点描述、出口、可交互物、触发块引用       | 否       | LLM + 引擎      |
| `Narration`     | 区分玩家可见表象与 DM 真相           | 否       | LLM           |
| `Scope`         | 标记叙事输出的可见范围,用于多人确定性过滤     | 否       | 引擎 + 前端       |
| `Interactable`  | 描述可调查、可拾取、可操作的对象          | 部分变化写 State | LLM + 引擎      |
| `TriggerBlock`  | 描述"什么时候发生、按什么顺序发生、产生什么后果" | 否       | 引擎           |
| `Check`         | 可配置检定原语                    | 否       | 引擎           |
| `Effect`        | 伤害、扣 SAN、给物品、设置 flag 等结果   | 否       | 引擎           |
| `Ending`        | 描述通关地点、结局条件、结局文本和失败条件      | 否       | 引擎 + 展示层      |
| `Entity`        | NPC、怪物、纯机制实体              | 部分变化写 State | LLM + 引擎      |
| `Resource`      | HP、SAN、MP、LUCK 等可增减数值      | 是       | 引擎           |
| `StateHistory`  | 已发生过什么、见过什么、揭示过什么         | 是       | 引擎 + 上下文管理   |

### 5.3 Location:静态场景容器

Location 只负责描述**空间上有什么**:玩家可见表象、DM 真相、可交互元素、出口、以及挂载哪些触发块。它不负责记录"发生过没有";运行历史一律写入 Runtime State。

```json
{
  "id": "hall_north",
  "type": "location",
  "narration": {
    "on_first_enter": "只含玩家可见的表象",
    "on_revisit": "再次进入时的简略描述",
    "style_hint": "生成提示,如'不要暗示这里有异常'"
  },
  "keeper_truth": {
    "summary": "只有 DM/引擎知道的真相,默认不进 LLM 上下文",
    "visibility": "hidden_until_revealed"
  },
  "interactables": [
    {
      "id": "rusty_painting",
      "name": "生锈画框",
      "player_visible": true,
      "truth": "画框后藏着暗格",
      "reveal_condition": { "on": "search", "check": "spot_hidden" }
    }
  ],
  "exits": [
    { "to": "library", "label": "北侧木门" }
  ],
  "trigger_refs": ["trap_ambush_hall", "san_gore_scene_low"]
}
```

**关键边界:** Location 是空间容器,不是历史账本。比如"陷阱是否已经触发""玩家是否见过这类尸体"都不写在 Location 里,而写在 Runtime State。

### 5.4 TriggerBlock:时序场景核心

TriggerBlock 负责描述**时序上怎么发生**。它可以挂载到 Location、Interactable、Entity,也可以是全局触发。所有"先做 A、再做 B、最后写状态"的内容都应该进入 TriggerBlock,不要塞进静态叙事字段。

统一结构:

```json
{
  "id": "trigger_id",
  "type": "suspense_check | san_trigger | random_table | damage_effect | custom",
  "attach_to": "location | interactable | entity | global",
  "trigger": {
    "on": "enter_room | inspect | combat_start | time_passed | manual",
    "once": true,
    "condition": {}
  },
  "sequence": [
    {
      "step": "prompt",
      "visible_to_llm": true,
      "text": "只给玩家/LLM 的阶段性提示"
    },
    {
      "step": "check",
      "check_ref": "coc_standard",
      "target": "actors"
    },
    {
      "step": "reveal",
      "visible_to_llm_after": "check_resolved",
      "text_ref": "reveal_text"
    },
    {
      "step": "effects",
      "effects": []
    }
  ],
  "state_writes": []
}
```

#### 5.4.1 悬念检定:suspense_check

DM 说"全体过敏捷",玩家不知缘由,掷完才揭示"踩中陷阱,过了的闪开了"。特征是**检定在前、叙事揭示在后,检定时故意不告诉玩家原因**。

```json
{
  "id": "trap_ambush_hall",
  "type": "suspense_check",
  "attach_to": "location",
  "trigger": {
    "on": "enter_room",
    "once": true
  },
  "check": {
    "scope": "all_players",
    "attribute": "DEX",
    "difficulty": "regular",
    "prompt_to_player": "你们感到脚下传来异样,快过一个敏捷!"
  },
  "reveal": {
    "after_check": true,
    "on_success": "你敏捷地跃开,寒光擦身而过——一排锈刺从地面弹出。",
    "on_failure": "你慢了半拍,尖刺刺入小腿。"
  },
  "effects": [
    {
      "when": "failure",
      "engine_call": "apply_damage",
      "params": { "damage": "1d6", "target": "failed_actors" }
    }
  ],
  "state_writes": [
    { "op": "add", "path": "history.triggered_events", "value": "trap_ambush_hall" }
  ]
}
```

#### 5.4.2 SAN 触发:san_trigger

同类恐怖只掉一次 SAN 的判断不属于任何单个地点,而是由 TriggerBlock 提供 `source_tag`,由 COC Module 读取规则,由 Runtime State 记录玩家是否已经见过。

```json
{
  "id": "san_gore_scene_low",
  "type": "san_trigger",
  "attach_to": "location",
  "trigger": {
    "on": "reveal_scene",
    "once": false
  },
  "san": {
    "source_tag": "gore_scene_low",
    "loss": "1/1d4",
    "dedup": "by_source_tag"
  },
  "description_ref": "corpse_scene_reveal",
  "state_writes": [
    { "op": "add", "path": "history.encountered_san_sources", "value": "gore_scene_low" }
  ]
}
```

**三方分工:** 模组作者标"什么来源、掉多少";引擎管"见过没、要不要真扣"(查 State 去重);LLM 管"把场面演绎得多恐怖"(纯叙事,不碰 SAN 数值)。

### 5.5 Ending:通关信息与失败条件

模组 IR 应显式定义可达成的结局。结局不是 LLM 即兴判断,而是由引擎在玩家进入关键地点、获得物品、触发事件或资源变化后做确定性检查。满足条件后,引擎输出对应的通关信息,再交给 LLM 做必要的叙事润色。

```json
{
  "endings": [
    {
      "id": "ending_true",
      "at_location": "temple_inner",
      "conditions": [
        { "has_item": "sacred_seal" },
        { "event_triggered": "priest_confessed" },
        { "resource": "SAN", "op": ">", "value": 0 }
      ],
      "text": "通关信息:你封印了业报之源……"
    },
    {
      "id": "ending_escape",
      "at_location": "mountain_gate",
      "conditions": [
        { "resource": "HP", "op": ">", "value": 0 }
      ],
      "text": "你逃出生天,但真相永远埋在山中。"
    }
  ],
  "fail_conditions": [
    { "resource": "HP", "op": "<=", "value": 0, "text": "调查员死亡" },
    { "resource": "SAN", "op": "<=", "value": 0, "text": "永久疯狂" }
  ]
}
```

**判定规则:** `endings` 通常依赖地点和模组状态,如 `at_location + conditions` 全部满足;`fail_conditions` 是全局失败条件,不依赖地点,由 Rule Module 或模组配置提供。通关/失败后也应写入 Runtime State,例如 `history.completed_ending` 或 `history.failed_reason`,避免重复触发。

### 5.6 Runtime State:运行时历史与唯一真相源

State 是运行时唯一真相源。LLM 永远不直接改 State,只能通过工具调用提议变更,由引擎裁决后写入。

```json
{
  "campaign_id": "run_001",
  "players": {
    "pc_001": {
      "resources": {
        "HP": { "current": 11, "max": 11 },
        "SAN": { "current": 48, "max": 99, "start": 55 },
        "MP": { "current": 11, "max": 11 },
        "LUCK": 50
      },
      "location_id": "hall_north",
      "party_id": "party_1"
    }
  },
  "scenes": {
    "hall_north": {
      "active_players": ["pc_001"],
      "narrative_thread": "thread_hall_north"
    }
  },
  "history": {
    "triggered_events": ["trap_ambush_hall"],
    "encountered_san_sources": ["gore_scene_low", "corpse_normal"],
    "visited_locations": ["hall_north"],
    "revealed_clues": ["letter_fragment"],
    "completed_ending": null,
    "failed_reason": null
  },
  "world_flags": {
    "library_door_unlocked": false
  },
  "npc_states": {
    "npc_doctor": { "attitude": "wary", "alive": true }
  },
  "inventory": {
    "pc_001": ["old_key"]
  },
  "private_state": {
    "pc_001": {
      "hidden_clues": ["letter_fragment"],
      "secret_role": null
    }
  }
}
```

运行时判断示例:

```
触发 SAN 检定,source_tag = "gore_scene_low" →
  引擎查 history.encountered_san_sources:
    ├─ 已存在 → 跳过扣 SAN,只给叙事描述
    └─ 不存在 → 正常掷骰扣 SAN → 写入 encountered_san_sources

触发 once 事件,trigger_id = "trap_ambush_hall" →
  引擎查 history.triggered_events:
    ├─ 已存在 → 不再触发
    └─ 不存在 → 正常执行 TriggerBlock → 写入 triggered_events

进入结局地点 temple_inner →
  引擎检查 endings.conditions:
    ├─ 全部满足 → 输出 ending.text → 写入 completed_ending
    └─ 未满足 → 继续游戏
```

### 5.7 LLM 信息隔离:可见性规则

模组原文常把"玩家可见的表象"与"DM 才知道的真相"写在一起。IR 必须在**数据结构上就分开**,否则 LLM 会剧透隐藏信息。信息隔离不只发生在静态 Location,也发生在 TriggerBlock 的不同阶段。

```
阶段1:引擎检测触发 → 只把 check.prompt_to_player 交给 LLM
       → LLM 输出"快过敏捷!"  ← reveal/truth 此时对 LLM 不可见
玩家掷骰 → 引擎判成败 → 结算 effect
阶段2:引擎把"成败结果 + reveal 文本"交给 LLM → LLM 演绎揭示
       ← 此时才把真相给 LLM
```

核心:**LLM 上下文不是完整 IR,而是由引擎按阶段裁剪出的可见切片。** `keeper_truth`、`reveal`、隐藏后果等字段默认不可见,只有满足时序条件后才进入 LLM 上下文。信息隔离优于提示词约束。

#### 5.7.1 信息作用域(Scope):多人可见性过滤

多人游戏中,可见性不按"人"写死,而按**信息的作用域**过滤。每条叙事输出都带 `scope` 标签,引擎根据 Runtime State 中玩家所在位置、队伍和私有可见列表,确定哪些玩家能看到它。这个过滤是确定性逻辑,不经过 LLM。

| scope | 含义 | 判定依据 |
| --- | --- | --- |
| `private` | 只有指定玩家可见 | `P.id` 在 `visible_to` 中 |
| `location` | 同一地点玩家可见 | `P.location_id == info.location_id` |
| `party` | 同队玩家可见 | `P.party_id == info.party_id` |
| `global` | 所有人可见 | 恒为可见 |

叙事输出统一带上作用域:

```json
{
  "narration": "书架深处传来纸张翻动的声响。",
  "scope": "location",
  "location_id": "library",
  "visible_to": ["pc_A", "pc_B"],
  "kind": "scene_event"
}
```

典型用法:

- 房间描述、公开事件、当众动作 → `scope: "location"`
- 私密线索、隐藏身份、自己的 SAN/背包 → `scope: "private"`
- 队伍频道或同队通知 → `scope: "party"`
- DM 全局旁白、时间流逝 → `scope: "global"`

`scenes` 是多人时的关键 Runtime State 结构:每个有玩家停留的地点可视为一条并行叙事线,记录 `active_players` 和独立 `narrative_thread`。DM 在不同 thread 间切换时,只加载对应场景上下文,避免图书馆线和地下室线互相串味。

scope 只解决"谁能看到什么",不解决"多线怎么调度"。多人模式还需要单独决定两件事:①每条 thread 的记忆/摘要如何独立维护;②分头行动时采用并行推进还是聚焦轮转。单人模式下只有一个玩家、一个场景、一条线,`scope` 会自然退化为"全部对该玩家可见",因此第一版也应预留 `scope` / `location_id` / `visible_to` 字段,避免后续多人化时重构叙事输出。

### 5.8 COC Module 如何接入 Core

检定做成"可配置原语",用参数描述,不写死方向。这样不同规则系统用同一 Core,不同 Module 提供参数。

```json
{
  "check_primitive": {
    "id": "coc_standard",
    "dice": "d100",
    "direction": "roll_under",
    "target_source": "skill_or_attribute_value",
    "modifier_mechanism": ["bonus_die", "penalty_die"],
    "success_tiers": ["fumble", "fail", "success", "hard", "extreme", "critical"]
  },
  "san_loss_rules": {
    "loss_syntax": "success/failure",
    "example": "1/1d4",
    "dedup_by_source": true,
    "dedup_granularity": "source_tag"
  }
}
```

**Module 的职责:** 解释 `Check` 怎么算、`Effect` 怎么结算、`Resource` 怎么读写、`TriggerBlock` 里的规则参数是否合法。比如 SAN 去重是 COC Module 的通用规则,模组 IR 只提供 `source_tag` 和 `loss`。

### 5.9 剧本 IR 与实体设计

模组解析产物(IR)至少含七类实体 + 实体间引用关系(构成场景图):

1. **元数据 Meta**:规则系统(COC)、模组标题、简介、人数/时长建议
2. **NPC/怪物 Entity**:剧情型(人格/动机/秘密,给 LLM 扮演)+ 属性型(数值,给引擎),可并存
3. **地点 Location**:描述、可交互元素、触发块引用、遭遇、战利品、连接关系
4. **规则性触发块 TriggerBlock**:检定要求、SAN 触发、随机表、伤害效果、一次性事件、阶段性揭示
5. **结局 Ending / FailCondition**:通关地点、通关条件、结局文本、全局失败条件
6. **物品 Item**:名称、价值、效果、位置、获取条件
7. **美术资源 Asset**:插画/地图,**关联到对应的地点/NPC/怪物实体**(不孤立存储)

实体(NPC/怪物)**不强制有战斗属性块**。有的实体靠机制描述定义(如某些 COC 怪物没有标准 AC/HP,而是"碰触即造成特定后果")。Schema 要同时支持:

- **属性块型**:有生命值、伤害、护甲等结构化战斗数值
- **纯机制型**:无标准属性块,靠"触发条件 → 后果"的 TriggerBlock 定义

### 5.10 人物卡(调查员)Schema

人物卡是按钮系统、检定引擎、成长系统和 LLM 角色演绎的共同输入。本文档的人物卡字段参考了 `LMX/COC7空白卡CY23Final.xlsx` 的"人物卡"、"简化卡 骰娘导入"、"职业列表"、"本职技能"、"技能注释"、"资产及物价参考"、"武器列表 战斗"、"防具表 载具表"、"疯狂表"等工作表,但**不照搬 Excel 布局**。

Excel 同时承担录入、公式计算、展示和规则速查;系统 Schema 必须拆开这些职责:

- **手填事实**:玩家输入或导入的角色设定,如姓名、职业、背景、技能点分配。
- **引擎派生**:半值/五分之一值、HP 上限、MP 上限、MOV、DB、Build、重伤阈值等。
- **运行时 State**:当前 HP/SAN/MP、状态、物品归属、经历增长、已触发疯狂等。
- **展示/速查**:快速规则说明不属于人物卡事实源,应作为 D2 玩家规则引导从 Rule Module 投影。

#### 5.10.1 调查员主结构

```json
{
  "id": "pc_001",
  "identity": {
    "name": "调查员姓名",
    "player": "玩家名",
    "era": "1920s",
    "occupation": {
      "id": "occupation_012",
      "name": "古董商"
    },
    "age": 32,
    "gender": "女",
    "residence": "现居地",
    "birthplace": "故乡",
    "portrait_asset_id": "asset_portrait_001"
  },
  "creation": {
    "age_adjustment": {},
    "occupation_skill_refs": ["appraise", "library_use", "history"],
    "occupation_points_total": 260,
    "occupation_points_spent": 260,
    "interest_points_total": 120,
    "interest_points_spent": 120,
    "custom_packages": []
  },
  "attributes": {
    "STR": 50,
    "CON": 60,
    "SIZ": 55,
    "DEX": 60,
    "APP": 45,
    "INT": 70,
    "POW": 55,
    "EDU": 65,
    "LUCK": 50
  },
  "derived": {
    "HP_max": 11,
    "MP_max": 11,
    "SAN_max": 99,
    "MOV": 8,
    "damage_bonus": "0",
    "build": 0,
    "major_wound_threshold": 6,
    "attribute_thresholds": {
      "STR": { "half": 25, "fifth": 10 },
      "DEX": { "half": 30, "fifth": 12 }
    }
  },
  "resources": {
    "HP": { "current": 11, "max": 11 },
    "SAN": { "current": 55, "max": 99, "start": 55 },
    "MP": { "current": 11, "max": 11 },
    "LUCK": { "current": 50 },
    "temporary_HP": 0,
    "daily_SAN_loss": 0,
    "used_MP": 0
  },
  "skills": [
    {
      "id": "spot_hidden",
      "name": "侦查",
      "category": "调查",
      "base": 25,
      "occupation_points": 20,
      "interest_points": 20,
      "growth_points": 0,
      "total": 65,
      "thresholds": { "regular": 65, "hard": 32, "extreme": 13 },
      "occupation_skill": true,
      "growth_checked": false,
      "check_ref": "coc_standard",
      "source": "standard"
    },
    {
      "id": "science_astronomy",
      "category_type": "科学",
      "specialization": "天文学",
      "category": "知识",
      "base": 1,
      "occupation_points": 0,
      "interest_points": 30,
      "growth_points": 0,
      "total": 31,
      "thresholds": { "regular": 31, "hard": 15, "extreme": 6 },
      "occupation_skill": false,
      "growth_checked": false,
      "check_ref": "coc_standard",
      "source": "specialized"
    }
  ],
  "combat": {
    "armor": {
      "name": "无",
      "value": 0,
      "coverage": [],
      "mov_penalty": 0
    },
    "weapons": [
      {
        "name": "徒手",
        "type": "melee",
        "skill_ref": "fighting_brawl",
        "success_rate": 25,
        "damage": "1d3+DB",
        "range": null,
        "impale": false,
        "attacks_per_round": 1,
        "ammo": null,
        "malfunction": null
      }
    ]
  },
  "assets": {
    "credit_rating": 40,
    "living_standard": "普通",
    "spending_level": 10,
    "cash": { "amount": 50, "currency": "USD" },
    "other_assets": "请在这里详述资产",
    "asset_breakdown": {
      "vehicle": "",
      "residence": "",
      "luxury": "",
      "securities": "",
      "other": ""
    }
  },
  "inventory": [
    {
      "item_id": "old_key",
      "name": "旧钥匙",
      "carried": true,
      "container": "随身"
    }
  ],
  "background": {
    "appearance": "形象描述",
    "ideology_beliefs": "思想与信念",
    "significant_people": [],
    "meaningful_locations": [],
    "treasured_possessions": [],
    "traits": [],
    "injuries_scars": [],
    "phobias_manias": []
  },
  "conditions": [
    {
      "id": "major_wound",
      "type": "physical",
      "name": "重伤",
      "active": false,
      "source": "engine"
    }
  ],
  "experience_log": [
    {
      "module": "毒汤",
      "description": "SAN-6,HP-2,侦查+2",
      "changes": [
        { "target": "resources.SAN.current", "delta": -6 },
        { "target": "skills.spot_hidden.growth_points", "delta": 2 }
      ]
    }
  ],
  "mythos_log": [
    {
      "contact": "米-戈",
      "result": "克苏鲁+3,SAN-6",
      "notes": "第一次神话疯狂,相信者规则激活",
      "cumulative_san_loss": 6
    }
  ],
  "spells": [
    {
      "id": "spell_gray_binding",
      "name": "灰色束缚",
      "cost": "8 MP + 1d6 SAN + 1h",
      "effect": "可以控制死去的人,直到腐烂为止"
    }
  ],
  "relationships": [
    {
      "name": "调查员伙伴",
      "player": "玩家名",
      "note": "一起出生入死",
      "changed_by": "成为挚友",
      "met_in_module": "卡森德拉..."
    }
  ]
}
```

#### 5.10.2 字段分工

| 字段组 | 来源 | 主要用途 | 写入位置 |
| --- | --- | --- | --- |
| `identity` | 玩家手填 / 导入 | 展示、开局介绍、D3 模组导语 | Investigator |
| `creation` | 建卡流程 / 职业表 | 审卡、重算职业技能点、年龄补正 | Investigator |
| `attributes` | 玩家建卡 | 检定目标、派生值计算 | Investigator |
| `derived` | COC Module 计算 | 展示、战斗、检定阈值 | 可缓存,可重算 |
| `resources` | 建卡初值 + 运行时变化 | HP/SAN/MP/LUCK 读写 | Runtime State 为准 |
| `skills` | 技能表 + 玩家分配 | 按钮生成、检定、成长 | Investigator + State |
| `combat` | 武器/防具表 + 玩家装备 | 战斗结算 | Investigator + State |
| `assets` / `inventory` | 玩家手填 / 装备库 | 购买力、携带物、物品约束 | Investigator + State |
| `background` | 玩家手填 | LLM 扮演角色、长期记忆 | Investigator |
| `conditions` | 引擎结算 / 玩家记录 | 疯狂、重伤、疾病、临时状态 | Runtime State |
| `experience_log` / `mythos_log` | 跑团后增长 | 角色成长、长期历史 | Investigator 历史 |
| `spells` | 法术库 + 剧情获得 | 法术展示、施法结算 | Investigator + Module |
| `relationships` | 玩家手填 / 剧情变化 | LLM 关系演绎、伙伴记录 | Investigator 历史 |

#### 5.10.3 设计纪律

- **半值/五分之一值不要作为手填事实源。** 它们由 COC Module 根据 `attributes` 或 `skills.total` 派生,可缓存用于展示。
- **技能点要拆分来源。** Excel 中有初始、成长、职业、兴趣四列;Schema 也应保留 `base`、`growth_points`、`occupation_points`、`interest_points`,否则无法审卡和回溯成长。
- **当前资源以 Runtime State 为准。** 人物卡保存初始和结构,运行中 HP/SAN/MP/LUCK 的当前值由 State Store 记录。
- **背景字段要进入 LLM 可见上下文,但按需裁剪。** 形象、信念、重要之人、宝贵之物、恐惧/躁狂等是角色扮演核心,但不应每轮全量塞入上下文。
- **规则速查不进人物卡。** Excel 里的快速参考规则、理智参考规则、疯狂说明应作为 D2 玩家规则引导,由 Rule Module 投影展示。

---

## 6. 输入输出格式:统一 Intent 与 Resolution

### 6.1 设计核心:Intent 是唯一引擎入口

玩家行动可以来自按钮、地图点击、快捷语或自然语言,但进入引擎前必须收敛成同一种结构化对象:**Intent**。引擎不认识"按钮"或"自然语言",只认识 Intent。

这带来三个好处:引擎只需实现一套处理逻辑;LLM 的输出会被约束成可校验结构;每次行动都可记录、回放、测试。

同理,引擎输出也统一为 **Resolution**。Resolution 记录引擎实际执行了什么,以及 LLM 能看到哪些已裁剪信息。信息隔离由数据结构保证,而不是靠提示词提醒。

```
玩家行动(任意形式) → Intent(JSON) → 校验层 → 引擎 → Resolution(JSON) → LLM 叙事演绎
                                      ↑
                                   唯一入口
```

### 6.2 Intent 的生成路径

Intent 有三种主要生成路径。区别只在于"谁构造 JSON",不影响引擎如何处理。

| 输入路径 | 谁构造 Intent | 是否调用 LLM | 说明 |
| --- | --- | --- | --- |
| 技能按钮 | 前端 | 否 | 过渡期加速器,减少延迟和歧义 |
| 地图移动 | 前端 | 否 | 点击合法出口,直接生成移动 Intent |
| 自然语言 | LLM | 是 | 解析玩家自由表达,转成结构化 Intent |

按钮和地图点击不是引擎的特殊入口,只是省去一次 LLM 意图解析的优化层。未来如果自然语言解析足够快、足够准,按钮可以弱化甚至取消;只要仍然产出 Intent,引擎和 Schema 无需改动。

### 6.3 Intent 数据结构

```json
{
  "intent_id": "intent_00123",
  "actor": "pc_A",
  "source": "button | move | free_text | check_response",
  "raw_input": "我用铁撬撬开这扇门",
  "action": {
    "type": "skill_check | move | interact | use_item | custom"
  },
  "meta": {
    "parsed_by": "engine | llm",
    "confidence": 0.88,
    "timestamp": "2026-07-09T14:23:11Z"
  }
}
```

`raw_input` 用于保留自然语言原文,便于审计和调试。`meta.parsed_by` 标记 Intent 来自前端直构还是 LLM 解析。`meta.confidence` 用于低置信度时要求玩家澄清,避免误执行。

#### action 类型示例

**skill_check**:技能或属性检定。

```json
{
  "type": "skill_check",
  "skill": "spot_hidden",
  "attribute": null,
  "difficulty": "regular",
  "target": null,
  "modifiers": [
    { "source": "item:crowbar", "effect": "bonus_die" }
  ],
  "trigger_ref": null,
  "check_ref": "coc_standard"
}
```

`skill` 与 `attribute` 二选一。`trigger_ref` 用于响应悬念检定等 TriggerBlock。

**move**:地点移动。

```json
{
  "type": "move",
  "from": "library",
  "to": "corridor",
  "via_exit": "oak_door"
}
```

`via_exit` 不应省略,因为两个地点间可能存在多条路径,各自的可见性、前置条件和检定要求不同。

**interact**:与场景可交互物交互。

```json
{
  "type": "interact",
  "target": "rusty_painting",
  "verb": "search",
  "check": {
    "skill": "spot_hidden",
    "difficulty": "hard"
  }
}
```

`check` 可为空。若 LLM 判断该交互无需检定,引擎跳过掷骰,直接生成叙事用 Resolution。

**use_item**:使用背包物品。

```json
{
  "type": "use_item",
  "item": "crowbar",
  "on_target": "locked_door",
  "intended_effect": "force_open",
  "check": { "attribute": "STR", "difficulty": "hard" },
  "modifiers": [
    { "source": "item:crowbar", "effect": "bonus_die" }
  ]
}
```

**custom**:无需检定的纯叙事行动。

```json
{
  "type": "custom",
  "description": "我环顾四周,深吸一口气",
  "requires_check": false
}
```

### 6.4 Intent 校验层

Intent 进入引擎后不能直接执行,必须先经过确定性校验。校验层是防止 LLM 幻觉和玩家越界的硬边界。

| 校验项 | 检查内容 | 拦截的问题 |
| --- | --- | --- |
| 技能合法性 | `skill` 是否在标准技能表内 | LLM 编造不存在的技能 |
| 物品持有 | `item` 是否在玩家背包中 | 凭空使用未持有物品 |
| 目标可达 | `target` 是否属于当前 Location | 跨场景交互 |
| 出口合法 | `to` 是否为当前地点合法出口 | 瞬移 |
| 出口条件 | `visible` / `requires` / `check` 是否满足 | 穿越未发现暗门、无钥匙开锁 |
| 修正来源 | `modifiers.source` 是否来自真实物品或状态 | LLM 白送奖励骰 |
| 置信度 | `meta.confidence` 是否达标 | 解析不确定时误执行 |

LLM 可以把"我用激光枪射击"解析成 Intent,但引擎查背包和时代约束后会拒绝。结构化数据的硬约束在这里生效。

### 6.5 Resolution 数据结构

Resolution 是引擎执行后的结构化结果。它既记录实际发生的运算和 State 写入,也定义交给 LLM 的可见叙事上下文。

```json
{
  "intent_id": "intent_00123",
  "resolved": true,
  "check_result": {
    "skill": "STR",
    "target_value": 60,
    "modified_value": 60,
    "dice": [42],
    "final_roll": 42,
    "tier": "success",
    "modifiers_applied": ["bonus_die:crowbar"]
  },
  "state_changes": [
    { "op": "set", "path": "world_flags.locked_door_open", "value": true },
    { "op": "add", "path": "history.triggered_events", "value": "door_forced" }
  ],
  "narration_context": {
    "scope": "location",
    "location_id": "library",
    "visible_to": ["pc_A", "pc_B"],
    "outcome": "success",
    "visible_facts": ["门被撬开了", "门后是漆黑的走廊"],
    "reveal_text": null,
    "style_hint": "强调铁撬刮擦木门的刺耳声响"
  }
}
```

`check_result` 在无检定行动中可为空。`state_changes` 是引擎实际写入记录,可用于回放、审计和撤销。`narration_context` 是 LLM 能看到的全部内容,已经完成时序和 scope 可见性裁剪。

### 6.6 数据流总览

```
技能按钮 / 地图移动 / 自然语言输入
        │
        ▼
Intent(JSON)                 ← 唯一接口契约
        │
        ▼
Intent 校验层                 ← 防幻觉、防越界
        │
        ▼
引擎确定性运算                 ← 掷骰 / 结算 / 写 State
        │
        ▼
Resolution(JSON)             ← 已裁剪的可见切片
        │
        ▼
LLM 叙事演绎                  ← 只能看到 narration_context
```

**关键结论:** Intent 是接口,输入通道只是实现;校验层是安全边界;Resolution 是信息隔离的执行者。按钮可以弱化,自然语言可以增强,但只要所有输入都收敛到 Intent,引擎就保持稳定。

---

## 7. COC 技能表:固定核心 + 可扩展槽位

**技能框架全 COC 统一(固定核心,约 60+ 项),但部分技能是"类别 + 专精"结构,专精由玩家填。**

- **固定技能**:侦查、聆听、图书馆使用、话术、说服、医学、攀爬、潜行、闪避、克苏鲁神话……(名称 + 基础值固定)
- **可扩展槽位(需专精填空)**:艺术/手艺(___)、科学(___)、格斗/射击(___)、其他语言(___)、驾驶(___)……

### Schema 支持两种技能形态

技能定义(B 类事实源)和人物卡上的技能值(玩家分配结果)要分开:

```json
// 技能定义:平台提供的 B 类数据
{
  "id": "spot_hidden",
  "name": "侦查",
  "category": "调查",
  "base": 25,
  "kind": "fixed",
  "check_ref": "coc_standard"
}
```

```json
// 人物卡技能:建卡/成长后的角色数据
{
  "id": "spot_hidden",
  "name": "侦查",
  "base": 25,
  "occupation_points": 20,
  "interest_points": 20,
  "growth_points": 0,
  "total": 65,
  "thresholds": { "regular": 65, "hard": 32, "extreme": 13 },
  "occupation_skill": true,
  "growth_checked": false,
  "check_ref": "coc_standard"
}
```

```json
// 专精技能:类别固定,专精由玩家填,需校验
{
  "id": "science_astronomy",
  "category_type": "科学",
  "specialization": "天文学",
  "category": "知识",
  "base": 1,
  "occupation_points": 0,
  "interest_points": 30,
  "growth_points": 0,
  "total": 31,
  "thresholds": { "regular": 31, "hard": 15, "extreme": 6 },
  "check_ref": "coc_standard"
}
```

`thresholds` 可由 COC Module 根据 `total` 派生并缓存;真正的事实源是 `base + occupation_points + interest_points + growth_points`。这样才能支持审卡、成长回溯和 D4 技能按钮说明。

### 自填技能"是否符合常理"的校验(分层,大部分不需 LLM)

```
玩家填专精技能 →
  1. 类别是否在标准表内?     (查表,硬校验)   → 否则拒绝或走 3
  2. 专精是否符合年代/世界观? (年代约束,B类)  → 如"科学(核物理)"@1920 → 不合理
  3. 完全自创的新技能?       (软判断)         → 交 DM/规则裁决,LLM 可辅助
```

**大部分是情况 1、2(查表 + 年代约束,结构化、快而准),只有情况 3 才真需 LLM 软判断。** 再次符合"能结构化就别用 LLM"。

**务实提醒:** 校验放在**建卡/传卡环节**(运行时很少临时自创技能),前期可简化为"类别必须在标准表内"一条硬规则。标准技能表(60+ 固定项)是第一版必录的 B 类核心数据。

---

## 8. 大模型参与边界(明确 LLM 做什么、不做什么)

**这是本项目"确定性 + 创造性解耦"的落地。以 COC 的一次检定为例,清晰划出边界。**

### 8.1 LLM 负责什么(软、需智能、有创造性)

1. **叙事演绎(主战场)**:把引擎算出的结果(如"侦查成功")变成生动文字;推进场景、渲染氛围、扮演 NPC。
2. **自由行为的 Intent 解析(枢纽)**:玩家打字"我想爬上房梁偷看"且无结构化输入时,LLM 将其解析为 Intent,再交给引擎校验和执行。
3. **临场裁决"该不该检定、用什么技能、难度多少"**:玩家说服 NPC,LLM 可参与判断需不需要检定、用话术还是说服、难度如何;判断结果必须落到 Intent 字段里,执行仍交引擎。
4. **C 类风格演绎**:以克苏鲁基调组织语言(靠内置知识 + 提示词)。

### 8.2 引擎负责什么(硬、确定性、瞬时)

1. **Intent 校验与执行**:检查技能、物品、目标、出口、修正来源和解析置信度。
2. **掷骰与判定**:d100 ≤ 技能值,判定成败等级(大成功/成功/困难/极难/失败/大失败)。
3. **数值结算**:HP/SAN/MP 增减,伤害计算,SAN 的 "X/YdZ" 损失。
4. **State 读写**:唯一真相源的更新。
5. **B 类事实查询**:技能基础值、装备属性、生物属性等查表。
6. **Resolution 生成**:输出运算结果、State 写入记录和裁剪后的 `narration_context`。

### 8.3 一次检定的边界示例(COC)

**例一:玩家主动点按钮**

```
玩家点【侦查】按钮
  │
  ├─[输入层] 生成 Intent { action:{ type:"skill_check", skill:"spot_hidden" } }
  │
  ├─[引擎] 校验 Intent → 读人物卡 skills.spot_hidden.total=65
  │        → 掷 d100 → 比较 ≤65 → 判定"成功"
  │        → (若涉及)结算 State → 生成 Resolution
  │
  └─[LLM] 收到 Resolution.narration_context → 演绎:
          "你拨开积尘的书页,一行褪色的字迹映入眼帘……"

数值全程不经过 LLM。LLM 可以参与 Intent 解析和结果演绎,但 Intent 校验、运算、State 写入和 Resolution 生成都由引擎完成。
```

**例二:TriggerBlock 触发的悬念检定**

```
玩家进入 hall_north
  │
  ├─[引擎] 发现 TriggerBlock trap_ambush_hall
  │        → 查 Runtime State.history.triggered_events
  │        → 未触发过,执行 suspense_check
  │
  ├─[上下文管理] 只把 check.prompt_to_player 暴露给 LLM
  │        → reveal/truth/effects 此时不可见
  │
  ├─[LLM] 演绎"你们感到脚下传来异样,快过敏捷!"
  │
  ├─[引擎] 玩家掷 DEX → 判定成败 → apply_damage
  │        → 写入 Runtime State.history.triggered_events
  │
  └─[LLM] 收到"成败结果 + reveal 文本" → 演绎陷阱揭示
```

这个例子体现 §5 的关键纪律:TriggerBlock 决定时序,引擎裁剪 LLM 可见内容,State 记录是否发生过。

### 8.4 边界对照总表

| 环节                         | 谁负责          | 类别 / 结构 |
| -------------------------- | ------------ | ------- |
| 自然语言解析为 Intent              | LLM          | 意图解析    |
| 结构化输入直构 Intent               | 前端           | 输入层     |
| Intent 校验                    | 引擎           | Core    |
| TriggerBlock 是否触发、是否 once    | 引擎           | Core    |
| 通关/失败条件检查                  | 引擎           | Core    |
| LLM 可见上下文裁剪                 | 引擎 / 上下文管理   | Core    |
| 叙事输出 scope 可见性过滤             | 引擎 / 前端       | Core    |
| 掷骰、比较、判成败                  | 引擎           | A       |
| HP/SAN/MP/LUCK 等数值结算        | 引擎           | A       |
| Runtime State 读写             | 引擎           | State   |
| 技能值/装备/生物属性查询              | 引擎查表         | B       |
| 防止超纲(库外物品、年代不符技能)         | 引擎(数据约束)     | B       |
| 把结果演绎成叙事、扮演 NPC            | LLM          | C + 演绎  |
| 风格基调(克苏鲁氛围)                | LLM          | C       |
| 玩家规则说明、背景引导、技能按钮说明        | 展示层          | D       |

**一句话:Intent 是入口,Resolution 是出口。** LLM 可以参与自由文本到 Intent 的解析,但引擎只执行通过校验的 Intent;LLM 叙事也只能基于 Resolution 中已裁剪的 `narration_context`。

---

## 9. 第一版范围建议(务实优先级)

以 COC 为第一个规则系统,按"跑通自包含模组"排优先级:

**第一版必做:**

- COC Rule Module 核心(A 类):d100 检定、技能检定、SAN 基础机制、基础资源增减
- 标准技能表(B 类核心):60+ 固定技能 + 可扩展槽位定义 + 基础值
- 人物卡 MVP(§5.10):身份、属性、资源、技能点拆分、基础背景、按钮生成
- Core Schema 最小闭环(§5):Location、TriggerBlock、Check、Effect、Runtime State
- Intent / Resolution 契约(§6):结构化输入、校验层、裁剪后的 `narration_context`
- TriggerBlock 最小能力:普通检定、悬念检定、SAN 触发、once 事件、State 写入
- Ending 最小能力:地点结局、条件组合、全局失败条件、通关信息输出
- LLM 信息隔离与 scope 预留:按阶段裁剪可见上下文,叙事输出带 `scope` / `location_id` / `visible_to`
- 风格提示词(C 类):克苏鲁基调 + 第十章守秘人主持原则摘要
- D 类玩家引导:D1 背景引导、D2 新手规则引导、D4 技能按钮/当前行动说明
- 单个自包含模组的 IR + 跑通完整流程

**可延后:**

- 装备/武器库、神话生物库、术语表(B 类扩展)——很多模组自带所需内容
- 规则书查阅界面 / 新手教程扩展(D2 展示形态)
- 完整的自创技能校验(先做"类别在表内"硬规则)
- 战斗/追逐等复杂 A 类机制(视首个模组是否用到)
- 完整人物卡字段导入(资产细表、伙伴关系、法术、长期经历包可分阶段补)
- D3 模组导语模板精修和个性化帮助系统

**判断依据:模组是自包含的,先跑通一个模组,别被"要不要建完整克苏鲁库"卡住。**

---

## 附录 A:待架构讨论决定的事项

- [ ] §2 整体架构分层的具体边界与调用关系
- [ ] Agent 单体 vs 多智能体
- [ ] Intent / Resolution 接口契约的最终字段
- [ ] 记忆/上下文管理机制
- [ ] 多人并发的 state 共享与回合调度
- [ ] 输入通道到 Intent 的映射规则(按钮/地图/自由文本)
- [ ] TriggerBlock / Runtime State / Rule Module 的调用边界
- [ ] LLM 可见上下文裁剪与信息隔离策略
- [ ] 多人 scope 过滤、并行 thread 记忆隔离与镜头调度策略
- [ ] 剧本解析流水线(LLM 提取 + 校验 + 人工兜底)的具体设计

## 附录 B:核心术语

- **DM/KP/守秘人**:游戏主持人,本项目由 AI 担任
- **调查员**:COC 中玩家角色的称呼
- **模组/Scenario**:自包含的冒险剧本
- **IR**:模组解析后的结构化数据,运行时读它
- **Rule Module**:某规则系统的形式化实现(A + B 核心),引擎加载执行
- **Intent**:玩家行动进入引擎前的统一结构化意图对象,无论来自按钮、地图点击还是自然语言
- **Resolution**:引擎执行 Intent 后的统一结构化结果,包含运算结果、State 写入和裁剪后的叙事上下文
- **TriggerBlock**:时序触发块,描述什么时候发生、按什么顺序发生、产生什么效果、写入哪些 State
- **Scope/信息作用域**:叙事输出的可见范围标签,如 private/location/party/global,由引擎和前端确定性过滤
- **Ending/结局**:模组 IR 中的通关或失败定义,由地点、条件和结局文本组成,引擎确定性检查后输出
- **Effect**:引擎可执行的后果,如伤害、扣 SAN、给物品、设置 flag、写入历史
- **Runtime State**:运行时唯一真相源,记录当前资源、已触发事件、已揭示线索、NPC 状态等
- **Investigator**:COC 调查员人物卡结构,保存角色静态档案、建卡数据、技能结构、背景和成长历史
- **信息隔离**:引擎按阶段裁剪 LLM 可见内容,未揭示的真相、后果、reveal 文本不进入当前上下文
- **检定/Check**:掷骰判定成败,COC 为 d100 ≤ 技能值
- **SAN/理智值**:COC 特有资源,见恐怖之物而损失
- **A/B/C/D 四类**:内容拆分——A 规则机制(引擎)、B 结构化数据(数据库)、C 风格基调(提示词)、D 玩家可读引导(展示给玩家的人话摘要,含 D1 背景/D2 规则/D3 模组导语/D4 情境提示)

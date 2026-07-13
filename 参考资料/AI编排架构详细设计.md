---
tags: [架构设计, AI编排, 意图理解, 检定链路]
date: 2026-07-11
---

# AI 编排架构详细设计 —— 意图/裁决/表达接口级推敲

> **本文定位**：[[架构设计-整体多视图]] §六「AI 编排架构」是决策权威源（流水线骨架/三大不变量/模型适配层/prompt 分层/上下文预算/脱本导回/eval/成本打点）；本文是 §六 的**接口级深化**——把此前"职责描述+关键不变量"的架构层面，落成具体的类型/协议/分支逻辑，与 [[API接口对齐规范]]、[[前端demo数据表设计]] 同等深度，同样按"原地生长"写法，本轮开写、后续轮次继续往里加小节。
> **权威关系**：字段/类型定义以 master §4.5/§5.2 为准，本文不一致处以 master 为准，发现不一致回 master 修正后同步本文。
> **例子贯穿**：沿用内置模组《古宅幽影》。
> 返回首页 → [[00-Index]]　相关 → [[架构设计-整体多视图]]、[[00-架构总览与演进日志]]、[[API接口对齐规范]]

## 一、意图解析与检定链路的边界（2026-07-11，第一轮）

### 1.1 现状缺口

master §4.5 里 `Intent` 已经有 `{kind:'investigate', target: string}` / `{kind:'talk', npcId}` / `{kind:'move', toSceneId}`，但没有定义这些 id 是怎么从玩家自然语言解析出来的，也没定义"解析不出来"时走哪条路。`IntentParser.parseIntent(utterance, view: PlayerView)` 的入参只有 `PlayerView`，而 `PlayerView` 只暴露"已发现的线索"，不包含"当前场景有哪些可互动的东西"（那是 GodView 结构）——按现有签名，`IntentParser` 根本没有材料把"我检查一下铁门"解析成确定的 `entityId`。这正是 [[API接口对齐规范]] 文末待办⑤（没有预设内容时 AI 临场判定的结果怎么走通道）背后的根因：不是协议细节没填，是编排层本身有结构性空白。

### 1.2 SceneActionMenu：给 IntentParser 的安全菜单

`ViewProjector` 新增一个方法，专为 `IntentParser` 准备解析材料——这份材料**不是**给客户端看的，跟 `PlayerView` 是两个不同用途的类型，不能混进 wire 协议：

```typescript
interface SceneActionMenu {
  entities: { id: string; name: string }[];   // 当前 Scene.contents 里 entity_present/clue_access 关联的 Entity，仅 id+name，不含 content/secrets/stats
  exits: { sceneId: string; title: string }[]; // Scene.exits 对应的可去地点
}
interface ViewProjector {
  project(state: GameState, forWhom: string): PlayerView;
  projectActionMenu(state: GameState, forWhom: string): SceneActionMenu;  // 🆕
}
```

**`entities` 不进 `PlayerView`/`view.private`，不做前端可点击热点**：参照 COC 的核心体验——玩家凭描述性语言主动怀疑、主动发现，不是"扫一遍菜单点选项"（那是 point-and-click adventure 的玩法逻辑，跟跑团是两种不同类型体验）。真实模组写作本身已经用"主动弱化次要信息、突出关键线索"（对应 `Entity.isCore`，见 [[前端demo数据表设计]] §5.3）来引导玩家该查什么，这个信号活在 Narrator 的描述文本里；如果再叠一层显式菜单，等于用 UI 机制跟内容层精心设计的"轻重"信号打架。

**`exits` 可以暴露给客户端**：空间导航是"事实"不是"线索"，跟 demo 已有的地图面板（`RoomPage.tsx` `MAP_LOCATIONS`）设计方向一致，不构成剧透。客户端侧的"已发现地点"渐进展示是数据表设计文档已经留的开放项（`rooms.discovered_scene_ids`），不是本文新范围。

### 1.3 Intent 目标引用改成确定性结构

```typescript
type Ref = { matched: true; id: string } | { matched: false; text: string };
type Intent =
  | { kind: 'investigate'; target: Ref }
  | { kind: 'move'; toScene: Ref }
  | { kind: 'talk'; npc: Ref; utterance: string }
  | { kind: 'skillCheck'; skill: string }        // 🆕 见 1.6 路径 B
  | { kind: 'ask'; question: string }
  | { kind: 'unknown'; raw: string };

interface IntentParser {
  parseIntent(utterance: string, view: PlayerView, menu: SceneActionMenu): Promise<Intent>;  // 🆕 加 menu 参数
}
```

`IntentParser` 的任务是"在 `menu` 给的候选里找最匹配的一项，找不到就把原话装进 `text`"——软判据（这段话该配哪个选项）在上游 LLM 求值，落成一个二态的确定性结构；`RulesEngine` 之后只读这个结构，不再自己做任何文本匹配。这跟 `Checkpoint.difficulty`（master §4.3.1）、`SanTrigger.condition`（同上）已经在用的"软判据在上游求值成枚举、规则层只读枚举"是同一个模式——master 里有三处引用"§六.6.4 软判据与硬求值分离"，但翻遍 §六正文其实没有真正写出这一节，是个悬空引用（本轮已把这三处指针改指向本文，见文末说明）。

### 1.4 RulesEngine 五路分支

| Intent 情况 | 行为 | `unknownStreak` |
|---|---|---|
| `kind==='unknown'` | §6.6 脱本导回状态机接管 | +1 |
| `move`，`toScene.matched` 但目标不在当前 `Scene.exits` | 仅叙事拒绝（"你不知道怎么去那"），不改状态 | 不变 |
| `move`，`toScene.matched` 且可达 | 正常迁移 `location` | 不变 |
| `investigate`/`talk`，`target.matched`/`npc.matched` 命中 Entity/Checkpoint | 走既有 check 流程或直接授予效果 | 不变 |
| `investigate`/`talk`/`skillCheck`，未命中任何预设内容 | AI 临场判定（见 1.7），不写状态 | **不变**——关键澄清：Intent 本身是听懂的，跟"没听懂"不是同一种失败，不该占用脱本导回计数 |

### 1.5 CheckOutcome / CheckRollResult 命名去重（发现的既有 bug）

master 里 `CheckOutcome` 这个名字被用了两次、指两个不同的东西：§4.3.1 是"模组作者定义的效果套餐"（`narrationHint`/`grantsEntityIds`/`sanLoss`/`sceneTransition`），§4.5 是"骰子机制结果"（`skill`/`roll`/`target`/`success`/`hidden`）。本轮要表达"Tier 2 临场检定有骰子结果、但没有效果套餐"，两者必须拆开，顺手改掉这处撞名：

```typescript
// §4.3.1 模组内容——命中 Checkpoint 某分支后的"效果套餐"，命名不变
interface CheckOutcome {
  narrationHint: string;
  grantsEntityIds?: string[];
  sanLoss?: SanLossSpec;
  sceneTransition?: string;
}

// §4.5 运行时——CheckResolver.roll() 的返回值，改名避免撞 CheckOutcome
interface CheckRollResult { skill: string; roll: number; target: number; success: boolean; hidden: boolean }
interface CheckResolver { roll(skill: string, target: number, hidden: boolean): CheckRollResult }

interface ActionResult {
  ok: boolean;
  resolutionKind: 'checkpoint' | 'direct' | 'improvised' | 'blocked' | 'unrecognized';  // 🆕
  roll?: CheckRollResult;         // 🔧 原 `check` 改名+改类型；checkpoint 和 improvised(Tier2) 都可能有值
  appliedOutcome?: CheckOutcome;  // 🆕 只有 resolutionKind==='checkpoint' 才有值——命中的 onSuccess/onFail 效果套餐本体
  newlyDiscoveredEntityIds: string[];
  sanLoss?: number;
  sceneChangedTo?: string;
  publicEventSummary: string;
}
```

"临场判定不能执行效果套餐"这条边界现在是类型层面的结构性事实——`appliedOutcome` 在 `improvised` 分支下恒为空，跟项目一贯的"不泄底"那种"编译期不可能"是同一种做法（呼应 ADR-4）。

### 1.6 协议改动：checkId 统一 + check.manual 新事件

现有 `check.request`/`check.roll` 靠 `checkpointId` 关联，但路径 B（`skillCheck`，没有 Checkpoint）时这个字段是空的，关联不上（[[API接口对齐规范]] 待办③）。引入服务端签发的 `checkId`（区别于模组内容的 `checkpointId`），两条路径统一用它对话：

```
C→S check.manual        { skill: string }                                🆕 路径B入口，UI直接选技能发起，不经过 action.submit/IntentParser
S→C check.request       { checkId, skill, target, checkpointId? }        checkId必带；checkpointId仅路径A有
C→S check.roll          { checkId }                                       回传checkId即可，服务端凭此找到待处理的检定上下文
S→C check.result        { checkId, roll, target, success }
```

路径 B 的 `target` 由服务端按角色当前技能值现算（无 `Checkpoint.difficulty` 时默认 `regular`）。骰子结果本身（`check.result`）不区分"预设"还是"临场"——COC 规则里玩家有权知道自己摇出了多少点，这个机制字段不该被藏；真正的分野在于 `RulesEngine` 要不要执行 `appliedOutcome`。

### 1.7 AI 临场判定四层分级

"临场判定一律不改状态"会跟已拍板的 **ADR-11 战斗特例**（MVP 阶段战斗判定"字段建出、规则暂不填充，先交给 LLM 自由文本执行"）冲突，那条先例本身允许 AI 临场改 HP。不能假装它不存在，按风险分层处理：

| 层级 | 触发场景 | 要不要写状态 | 为什么 |
|---|---|---|---|
| **Tier 1 纯氛围** | investigate/talk 没命中任何预设内容（"我看看窗帘"） | 不写 | 没有对应的胜负/复盘语义可挂，写了也没处安放 |
| **Tier 2 有骰子支撑的临场检定** | 路径B `skillCheck` | 骰子结果正常发（`check.result` 照常走），但 `appliedOutcome` 恒空 | 骰子是 `CheckResolver` 算的确定性数值，COC 规则允许玩家对任何技能发起检定；"给不给 flavor 反馈"是软判断交给 Narrator，但不允许这个 flavor 冒充正式线索或触发正式效果 |
| **Tier 3 情理上该扣 SAN 但模组没写 SanTrigger** | 例如目睹尸体，这个模组恰好没建对应触发 | 不属于"临场判定"范畴，走 `World.worldRules` 通用规则（master §4.3.0 本来就举了"常规 SAN 检定"当例子）——触发条件用 LLM 软判据，扣多少用 `SanLossSpec` 硬求值 | SAN 有阈值/不定性疯狂等下游机制，静默临时扣分属于"错了不可逆、系统性偏向"级别风险，不该开临场口子；常规情形理应已被 World 层通用规则兜住 |
| **Tier 4 战斗** | ADR-11 既有特例 | 允许（现状） | 已经是明确标注、范围受限的 MVP 技术债，等战斗规则引擎收尾后被正式规则取代，不纳入本轮"通用临场判定"口子，避免拿特例反推放宽整体边界 |

Tier 2 的 flavor 反馈不需要新的 `EventPayload` 变体，直接复用已有的 `narration.push`（`visibility:'scene'`）落 `events`——它本质上就是一段旁白，只是这次的素材是"骰子好坏+玩家意图"而不是预设的 `narrationHint`。

## 二、SAN 触发与幸运消耗协议（2026-07-11，第二轮）

### 2.1 SanTrigger 是什么

`SanTrigger` 承载的是**模组作者（或解析上传模组的 Agent）预先写死的、跟具体场景/线索绑定的 SAN 机制性事实**——"进了这个房间/看到这具尸体，正式规则要求做一次 SAN 相关处理"，挂在 `Scene.contents` 上。内部天然两层：`condition`（软判据，要不要触发）+ `loss: SanLossSpec`（硬求值，触发后扣多少）——跟 `Checkpoint.difficulty` 同一套模式。这类**内容驱动**的触发不该交给 AI 临场决定：同一模组不同局如果这次触发了、下次没触发（纯粹因为 AI 那天没想起来），玩家会觉得同样的情节理智机制却不一致，是静默、系统性的体验缺陷。

### 2.2 AI 临场触发 SAN——只在没有预设 SanTrigger 命中时，且只能产出"check"语义

跟 `skillCheck` 路径B同一模式的第三次复用：LLM 只在受限枚举里选一档，Rules 查表拿确定性效果，不允许 LLM 直接编数字。

```typescript
interface SanJudge {
  judge(sceneText: string): Promise<{ trigger: false } | { trigger: true; severity: 'mild' | 'moderate' | 'severe' | 'extreme' }>;
}
```

`sceneText` 是 Rules 裁决阶段已经算出的"即将发生的事实"（刚揭示的 `Entity.content`/刚进入的 `Scene.description`），必须在 Narrator 生成最终叙事**之前**跑——`sanLoss` 要进 `ActionResult`，Narrator 是照着 `ActionResult` 生成连贯叙事的，顺序不能反。四档严重度对应的骰子表达式放 `World.sanityMechanic.severityTable`（新字段，见 §4.3.0）。

**边界（重要）**：`SanJudge` 临场触发**只能产出 `SanTrigger.kind='check'` 语义的效果**（走一次"检定"，success/fail 各自的 loss），**不能触发 `flat`/`direct`/`max_reduce`/`gain`/`capped` 这五种更强、往往不可逆的效果**（比如直接清零、永久降低理智上限）——越不可逆的效果越不该交给临场判断，这条跟"AI 临场判定四层分级"里"战斗特例维持 ADR-11、不纳入通用口子"是同一个逻辑，只是这次换了个位置重申。这五种形态本身也**不需要新协议**：没有"检定"这个动作，`RulesEngine` 内部按 `kind` 直接算效果、生效，靠 `narration.push`（叙事）+ 下一次 `view.private`（`visibleSan` 数值更新）体现，不用新增 WS 事件。

### 2.3 幸运消耗——技能检定和理智检定是两套不同协议，不能共用一套字段

**COC7 官方规则调研结论**（Chaosium《守秘人规则书》Luck Spends 可选规则，第 99/125/154 页；Roll20 官方 Compendium 交叉验证；近年无勘误推翻）：

| 检定类型 | 幸运能不能改"成功/失败" | 幸运能改什么 | 换算比例 |
|---|---|---|---|
| 普通技能检定 | **能** | 直接把失败改成功 | 1:1，花费 = 骰出点数 − 目标值；**用幸运救成功的这次不获得技能成长检定资格**（连带规则，记一笔，留到复盘/成长机制那轮细化） |
| 理智检定（`SanTrigger.kind='check'`） | **不能** | 检定失败已定论，只能减少要扣的理智点数 | 花费 = 想减少的点数 × 2（比如原定扣 6，想减到 3，花 6 点幸运） |

这两套语义不同，协议也必须分开设计，不能套用同一个"先给结果、再等玩家决定要不要变成功"的模板：

```
# 普通技能检定（Checkpoint）
S→C check.result.preliminary   { checkId, roll, target, success:false, maxLuckSpend, currentLuck }
C→S luck.spend / luck.skip     { checkId, amount? }   # amount ≤ maxLuckSpend，服务端强制校验
S→C check.result                { checkId, roll, target, success:true, luckSpent, skillGrowthEligible:false }

# 理智检定（SanTrigger kind='check'）
S→C san.check.result.preliminary  { checkId, roll, target, success:false, sanLossIfNoSpend, maxLuckSpend, currentLuck }
C→S luck.spend / luck.skip         { checkId, amount? }   # amount 必须是偶数、≤ maxLuckSpend
S→C san.check.result                { checkId, sanLossFinal, luckSpent }
```

**服务端权威掷骰原则的延伸**：不只是骰子本身，"花多少幸运能换多少效果"这个换算额度也必须服务端算好、通过 `maxLuckSpend` 告知客户端，客户端只能确认/放弃，不能自己报数字。

**不新增 `allowLuckSpend` 标记**：`Checkpoint` 与 `SanTrigger.kind='check'` 天然就是"有检定"的场景，官方规则默认允许幸运介入（COC7 没有例外条款要关掉它，"push 过的检定不能再用幸运"这类边界留到以后设计 push 机制时再处理）；其余五种 `SanTrigger` 形态根本没有"检定"这个动作，自然没有幸运介入的位置——**不是"该关闭的开关"，是"压根不存在的开关"**，不需要为不存在的东西建字段。

## 三、旁白与 NPC 对话的边界（2026-07-11，第三轮）

**流式收尾是机械事实，不是判断题**：`Narrator.narrate()` 返回的 `AsyncIterable<string>` 在底层模型流关闭时自然终止，这个信号是 LLM 流式 API 自带的，不需要 AI 额外判断"该不该收尾"，只需要把这个已有信号搬运到协议层——`narration.push` 补一个终止标记（最后一个分片 `done: true`）。

**`narrate()` 的 `view` 取"发起这次行动的玩家"的 `PlayerView`**；persona system prompt 要求写成"环境可观察的第三人称描述"，不是只有行动者能懂的第二人称口吻——玩家私有的后果（拿到什么线索、SAN 变了多少）本来就走 `clue.granted`/下次 `view.private` 这些私密通道，不进 `narration.push` 文本本身。

**旁白和 NPC 对话的分界线是"能不能被交互"，不是"是不是同一次模型调用"**（讨论中一度想合并成一次调用，被推翻，记录如实标注）：
- **旁白**：单向输出，描述"发生了什么/变了什么"，触发源是任意 `ActionResult`，玩家不能"回复旁白"
- **NPC 对话**：持续多轮的交互循环，触发源是 `Intent.kind==='talk'`，可能挂 Checkpoint（说服/恐吓等技能检定撬信息，复用第一轮已经设计的 check 流程，不需要新协议），NPC 态度变化复用既有 `Entity.state`/`Rule` 机制，不需要新结构
- MVP 阶段两者可以共用同一个底层模型配置（master §十"单旁白人格起步"讲的是**要不要为 NPC 单独调优模型**这个成本问题，不是"NPC 对话要不要设计成独立交互模式"这个架构问题，两者不冲突）
- **NPC"记得"聊过什么，靠既有 EventLog + 近 K 回合窗口 + 滚动摘要覆盖，不需要给每个 NPC 单独开一份对话历史**——只要"这段话是哪个 NPC 说的"被正常记进 `events`（需要给 `EventPayload` 补一个变体，字段细节留后续）

**Prompt 具体怎么拼装（system message 分层组装的 token 级细节）本轮明确暂不深挖**，留后续迭代——这是本轮唯一明确推迟的部分。

## 四、QA 答疑（2026-07-11，第四轮）

QA 是**纯只读、不推进剧情、不消耗回合**的角色，答的是"规则类"（技能是干嘛的/能不能用幸运）和"定位回顾类"（找到了哪些线索/我们在哪）两种问题，本质是复述已知信息，不产生新事实。

**不需要新机制，只需要数据完整+一个诚实的边界**：规则类答案素材是 `World.skillCatalog`/`checkMechanic`/`sanityMechanic`（属于 §6.4 层①，本来就该在，只是数据完整性要跟上）；定位回顾类答案素材就是 `PlayerView`，本来就有。边界写进 persona system prompt：同样只能看 `PlayerView`（不泄底铁律无例外）、不能剧透 `WinCondition`/未发现内容、不知道就老实说不知道不许编——QA 是几个角色里幻觉代价最高的一个，应优先建 §6.7 eval 金标准集。

**协议：专属入口，天然不占回合**——不走 `action.submit`，直接绕开回合门控，不用碰 ADR-1 已经定好的规则：

```
C→S qa.ask       { question: string }                                🆕 独立入口，不经过 IntentParser，不受回合门控
S→C qa.answer    { questionId, text, streaming, seq, done }          私密，仅提问者可见；done 复用第三轮的流式终止信号
```

`Intent.kind==='ask'`（IntentParser 把普通输入解析出这个）继续保留作为兜底，两个入口汇聚到同一个 responder——这是"一个能力、两个入口"模式第三次出现（`skillCheck`/`check.manual` 是第一次）。

```typescript
interface QAResponder { answer(question: string, view: PlayerView): AsyncIterable<string> }
```

不复用 `Narrator.narrate()` 签名——`ActionResult` 对 QA 没意义，硬塞会让人误解"QA 也会产生游戏效果"。QA 问答记进 `EventLog`（补 `EventPayload` 变体，`visibility:'private'`）——复盘时"当时问了什么、怎么答的"是有意义的历史，跟 `check.request`/`error` 这类纯协议提示不同。

## 五、复盘摘要（room_summaries）生成机制（2026-07-11，第五轮）

### 5.1 核心原则：结构化字段查询/计算，只有 summaryText 需要 LLM

`endingType`（`WinCondition` 命中结果，`RulesEngine` 已算出）、`keyFindings`（查 `entityStates` 里 `kind='clue'` 且 `discovered=true`）、`stats.sanChanges`/`characterFates`（`characters` 最终态+确定性规则算出）、`sessions`（`room_sessions` 折进来）——这些全部是查询/计算，不经过 LLM。只有 `summaryText` 这段叙事文字需要生成。

### 5.2 输入是 GameState 全貌（GodView），不是 PlayerView——复盘阶段不受"不泄底"约束

"不泄底"这条不变量管的是**游戏进行中、面向某个具体玩家的实时输出**（Narrator/NPC/QA 类型签名只收 `PlayerView`，是故意的结构性保守设计）。复盘阶段悬念已经不成立，这正是 `GET /rooms/{roomId}/replay`"返回全部事件包括 private"的既有边界（API 对齐规范）——`SummaryGenerator` 只是把同一个边界应用到"生成摘要"这个新场景，不是新发明也不是推翻不变量：

```typescript
interface SummaryGenerator {
  generate(state: GameState, hitWinCondition: WinCondition): Promise<RoomSummary>;
  // 输入是 GameState 全貌(GodView)，不是 PlayerView；persona 复用叙事者(narrator)人格设定保证语气对齐同一个 KP，
  // ModelRole 单独配置('summarizer')，方便独立选型/评测（非流式/大上下文/一次性，跟 Narrator 特性不同）
}
```

素材上复用 §6.5 已有的 `rollingSummary`（大部分历史已被压缩过）+ 结尾几回合原文 + `characters` 最终状态 + `endingType`，不需要重新扫全部原始 `events`。

### 5.3 绝不失败：重试 + 降级模板兜底

跟模组导入的本质区别——**模组导入失败是真的没有素材（无法兜底）；复盘摘要的结构化数据永远存在（游戏结束时 GameState 本来就完整），退化的只是"叙事文字讲得好不好"**。所以能承诺"绝不失败"：

1. 正常重试（次数/时间窗口可配，可以给得比模组导入宽松，玩家不需要在线等）
2. 超过窗口后降级——`summaryText` 退化成纯模板拼接（直接用已有的 `keyFindings`/`stats` 结构化数据拼句子，不需要 LLM），`room_summaries.generation_method`(`'llm'`\|`'fallback_template'`) 标记走的哪条路，对前端透明
3. 终态只有 `succeeded` 一种，**不需要 `failed`**——理论上不会卡死，不是靠运气

## 六、卡关引导策略（2026-07-11，第六轮）

沿用既有判据（[[aidm-datamodel-vs-llm-heuristic]]）——卡关引导算错没有不可逆后果、玩家能自我修正，不建专门数据结构，现有信号（`Entity.isCore`+路径数）够用。这轮落的是**具体 policy 内容**。

**信号**：`turnsSinceLastCoreDiscovery`——距上次任意 `isCore=true` 的 Entity 被发现以来过了多少回合，**现查 `EventLog` 算出来，不持久化**（不违反"不需要新字段"——那条讲的是不建运行时失败计数器，不是禁止现算的临时值）；仅当存在未发现核心线索时才有意义。

**分级 policy（写进 Narrator persona system prompt）**：

| 区间 | 行为 |
|---|---|
| < T1 | 正常叙事，不介入 |
| T1~T2 | 叙事措辞悄悄加权重——更详细描写通向未发现核心线索路径的元素，呼应"作者主动弱化次要信息、突出关键线索"这条既有内容写作习惯，AI 在措辞上做同样的事 |
| > T2 | 借场景内 NPC/环境事件主动递话，仍是叙事，不是系统提示框 |
| 远超阈值 | 语气从"引导"变"半直给"，依然走叙事表达；要不要加"求助"按钮是另一个 UX 决策，不在本轮范围 |

**T1/T2 是 World 级配置参数，不是运行时状态**——跟点数购买法那些具体数字性质一样，可能因模组/难度而变，但不随游戏进行而改变，这跟"不需要新字段"（指运行时持久化追踪）不冲突，只是把该判据用得更精确。

**这是"分级响应"模式第三次出现**（`unknownStreak` 三级 / AI 临场判定四层 / 这次卡关三级），但触发条件完全不同，各自独立维护信号，不能混用同一个计数器。

至此 AI 编排架构详细设计六轮走查全部过完一轮。

## 待办
- [ ] `SceneActionMenu` 里"裸" `checkpoint`/`san_trigger`（无 Entity 锚定）怎么进 menu，留 `Checkpoint` 要不要补 `label` 字段这个小问题给后续
- [ ] "用幸运救成功不获得技能成长检定资格"这条连带规则，落地到 `characters.skills` 成长机制时要记得处理
- [ ] `EventPayload` 补 NPC 对话变体（标记"哪个 NPC 说的话"）、QA 问答变体——字段细节留后续
- [ ] Prompt 组装的 token 级细节（system message 具体怎么拼）——第三轮明确推迟，留后续迭代
- [x] ~~第一轮结论回填 master~~ → 已完成（2026-07-11）：§4.5 接口定义（`SceneActionMenu`/`Intent`/`ActionResult`/`CheckRollResult`）+ §5.2.2 事件目录（`check.manual`+`checkId`）已同步；master 三处"§六.6.4"悬空引用已改指向本文
- [x] ~~第二轮结论回填 master~~ → 已完成（2026-07-11）：§4.3.0（`sanityMechanic.severityTable`）+ §4.5（`SanJudge`）+ §5.2.2（`san.check.*`/`luck.spend`/`luck.skip`）已同步
- [x] ~~第三、四轮结论回填 master~~ → 已完成（2026-07-11）：§5.2.2（`narration.push` 补 `done`、新增 `qa.ask`/`qa.answer`）+ §4.5（`QAResponder`）已同步
- [x] ~~第五轮结论回填 master~~ → 已完成（2026-07-11）：§4.5（`SummaryGenerator`、`ModelRole` 补 `'summarizer'`）已同步；[[前端demo数据表设计]] `room_summaries` 补 `generation_method` 字段
- [x] ~~第六轮结论回填 master~~ → 已完成（2026-07-11）：master 长期待办"卡关引导策略设计"已标记完成，指向本文档 §六
- [x] ~~六轮收官后的审计~~ → 已完成（2026-07-11）：对照 [[架构设计参考 1]] 方法论核对 API/数据表/协议三份文档，[[API接口对齐规范]] §三全量回顾同步、[[前端demo数据表设计]] `check_results` 补 `check_kind`、master §六.2"不泄底"补 `SummaryGenerator` 例外脚注，详见 [[00-架构总览与演进日志]] 演进日志
- [ ] **模组导入 Agent 的内部管线详细设计（第七个议题，明确推迟）**：审计时发现"模组导入"这个第三种 AI 角色（数据表设计文档早提过、跟 Narrator/NPC/QA 同属模型适配层）此前只设计了外壳（异步任务状态机+六步校验），内部怎么解析从没展开过。已讨论出一个方向——分阶段管线（骨架粗提取→逐项精提取→关系装配→既有六步校验），配 `ModuleImportAgent`/`ModulePackDraft` 接口草图，好处是中间产物可持久化、失败重试能精确定位、且能给运行时 AI 保留溯源引用。**决定放到"模块拆分"完成之后再细化**，理由：模组导入是离线异步任务，不进实时回合循环、不背 P0 不变量，耦合度远低于今天六轮涉及的核心游戏循环模块，属于"本身也是一个独立模块"，现在只需要一个粗粒度接口（`ModuleImportAgent.parse()`）就够模块拆分用，内部四阶段管线可以晚点再定，不影响骨架搭建

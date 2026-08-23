# NPC 结构化对话与长期记忆升级方案

## 1. 文档定位

本文档沉淀当前项目关于 NPC 对话、AI 主持人扮演方式和长期记忆升级的最终方案，作为后续实现 PR 的设计基线。

当前结论是：不为每个 NPC 创建独立 Agent，而是在现有 AI Host/Narrator 基础上，增加结构化 NPC 对话消息、NPC 独立认知记忆和按需历史召回。

相关基础工作：

- Issue #363：跨回合上下文压缩与持久化总体设计，已关闭；
- PR #393：长期记忆增量投影、游标、并发安全、来源时间和房间级重建，已合并；
- Issue #402：NPC 共享长期记忆与按需历史召回，已关闭，其权限和召回决策已并入本文；
- Issue #406 / PR #407：本文档的设计评审载体，不要求先合并，也不再新建总 Issue；后续
  实现 PR 直接引用 #407，并按阶段 A/B/C 交付。

---

## 2. 当前项目的 NPC 模型

### 2.1 NPC 不是独立 Agent

当前 NPC 是 ModuleContent/Engine 中的一种世界实体：

```text
玩家角色 Player Actor
    玩家控制，拥有角色卡、属性、技能、背包和状态

NPC Entity
    世界中的人物实体，拥有 id、名称、别名、描述、位置和公开状态

AI Host / Keeper
    不属于游戏世界，负责理解行动、调用规则引擎和生成玩家可见叙事
```

NPC 通常通过以下信息进入当前玩家的 `PlayerView`：

```json
{
  "id": "thomas",
  "kind": "npc",
  "name": "托马斯",
  "aliases": [],
  "description": "玩家当前可见的描述",
  "observable_state": []
}
```

只有 NPC 当前位于场景中、满足可见性条件并且对玩家可见时，玩家和 Host 才能使用它。

### 2.2 当前 AI 主持如何扮演 NPC

当前流程是：

```text
玩家输入
  ↓
Planner / ActionPlan
  判断玩家意图、行动类型和目标
  ↓
Engine
  验证目标、执行规则、提交权威状态
  ↓
Narrator
  根据 PlayerView、提交证据、近期历史和记忆生成叙事
```

NPC 的对白目前主要埋在 Narrator 的自由文本中，例如：

```text
托马斯皱了皱眉。他说门后有一条石阶，而你推开门后发现黑暗正在蔓延。
```

这会造成几个问题：

- 玩家需要从长段叙事中寻找 NPC 的原话；
- 后端无法稳定判断哪一段是 NPC 说的；
- 无法可靠确定 NPC 对谁说话以及谁听到了；
- NPC 长期记忆无法从自由文本中稳定投影；
- 多人回放和权限过滤困难。

---

## 3. 升级目标

升级后仍然只有一个 AI 主持，但输出分为清晰的角色消息：

```text
同一个 AI Host
├── NPC 对话
└── 守秘人叙事
```

目标是：

1. 玩家可以使用 `@NPC` 或 UI 目标选择明确指定交互对象；
2. Host 清楚知道当前是在替哪个 NPC 说话；
3. NPC 只使用自己的认知记忆，不读取其他 NPC 的知识；
4. 玩家不再需要从一大段叙事中寻找 NPC 对白；
5. NPC 对话可以单独落库、检索、摘要和回放；
6. `@NPC` 的整条输入只作为玩家对 NPC 的发言，不拆出技能、旅行或其他 Engine 行动；
7. 一次 NPC 对话允许多个当前可见 NPC 按顺序回复；
8. NPC 的主张不能绕过 Engine 变成世界事实；
9. 长团中可以回忆几十甚至几百回合前的具体对话、地点、行动和线索；
10. 多人房间中不能通过 NPC 绕过玩家权限泄露私密内容。
11. 行动区中未指定接收者的多人消息仍是玩家角色之间的场内角色扮演，不调用 Host，
    也不让 NPC 自动听到；讨论区则继续承载玩家本人之间的游戏外讨论。

---

## 4. 最终架构原则

### 4.1 不创建独立 NPC Agent

不为每个 NPC 创建独立模型实例、独立 Agent Loop 或独立工具调用权限。

推荐架构：

```text
NPC Entity
    ↓
NPC MemoryEntry / NPC Summary
    ↓
当前 AI Host 读取对应 NPC 上下文
    ↓
Host 以 NPC 视角生成结构化回复
    ↓
写入 dialogue.npc 事件
```

NPC 仍由当前 AI 主持人扮演。拆分的是消息协议、上下文作用域和前端展示，不是新增一套 NPC Agent 系统。

### 4.2 不需要复杂的 Mode 状态机

`@NPC` 的主要作用不是启动一个新模式，而是提供结构化的当前交互对象：

```json
{
  "interlocutor_id": "thomas",
  "utterance": "门后有什么？"
}
```

`recipient.kind=npc` 由应用层直接路由到纯对话服务，不调用 Keeper Planner，也不建立
ActionPlan。整条 `utterance` 原样写入 `dialogue.player`，不让模型切分或改写所谓“对白
片段”。NPC 回复仍由当前 Host provider 生成，但使用受限 NPC 上下文和结构化输出契约。

### 4.3 Engine 仍然是唯一事实源

以下内容不能仅因为 NPC 或 Narrator 说过就成为事实：

- 门后有什么；
- 玩家是否拿到物品；
- NPC 是否死亡、受伤或移动；
- 某条线索是否已经发现；
- 某个地点是否存在；
- 某个玩家是否完成行动。

NPC 的对白只表示 NPC 的认知、猜测、主张或记忆。玩家在 `@NPC` 消息中说“我要去地下室并
使用侦查”，只证明 NPC 听见了这项计划，不能证明玩家已经移动或完成检定。需要改变世界
状态时，玩家必须另发 `@守秘人` 输入；单人房间也可以使用无 `@` 的默认守秘人输入。

---

## 5. 结构化消息设计

### 5.1 事件类型

第一版只新增以下两种游戏内权威事件：

```text
dialogue.player   玩家对 NPC 的发言
dialogue.npc      NPC 对玩家或其他参与者的发言
```

守秘人环境描述、行动结果和规则后果继续复用现有 `narration.push`。它已经被 WebSocket、
回放、ConversationSummary、Memory 投影、Host Speech 和前端消费；新增同义的
`narration.keeper` 只会扩大迁移面。NPC 对白拆成 `dialogue.npc` 后，剩余
`narration.push` 在 UI 中自然按守秘人消息展示，无需增加第二种守秘人事件。

现有 `ChatMessage` 继续保持独立，并增加稳定频道语义：

```text
channel=discussion  玩家本人之间的游戏外讨论
channel=roleplay    行动区内、未 @ 接收者的玩家角色间交流
不进入 MemoryEntry
不进入 ConversationSummary
不作为 NPC 知识来源
不调用 Host，不占主持行动槽
```

`roleplay` 消息应同时保存 `actor_id`，由前端显示角色名；`discussion` 继续显示玩家昵称。
两种频道都沿用 `ChatMessage` 的房间内持久化、重连去重和游戏结束清理语义。第一版不把
场内角色扮演纳入永久 Event replay；以后若需要导出完整文字团记录，应单独设计归档，
不能为了归档把无 `@` 消息重新混入 Host Memory。

第一版沿用现有 ChatMessage 的房间受众，不为 `roleplay` 另建场景受众表。因此它是玩家
可见的角色扮演消息，不是权威世界事件：文本中的移动、交付物品、攻击或告知 NPC 都不会
改变 Engine 状态，也不会让在场 NPC 自动获得记忆。需要世界响应或让 NPC 确定性听见时，
玩家必须在行动区结构化选择 `@守秘人` 或 `@NPC`。分场景角色私聊和永久文字团归档都不
属于第一版；确有需求时扩展 ChatMessage 自身，不能把它重新写成 Event。

PR #404 中的两个自由交流入口也必须遵守同一边界。输入是否默认交给 Host，取决于
房间的稳定游戏模式，而不是当前在线人数：

```text
单人游戏
    行动区未 @ 任何对象 → 默认提交给守秘人，调用 Host
    讨论区未 @ 任何对象 → discussion ChatMessage，不调用 Host
    @守秘人       → 提交给守秘人，调用 Host
    @NPC           → 提交结构化 NPC 对话，调用 Host

多人游戏
    行动区未 @ 任何对象 → roleplay ChatMessage，不调用 Host
    讨论区未 @ 任何对象 → discussion ChatMessage，不调用 Host
    @守秘人       → 提交给守秘人，进入主持行动队列
    @NPC           → 提交结构化 NPC 对话，进入主持行动队列
```

`@` 只在行动区输入组件中解析。讨论区即使包含“@主持人”或“@NPC”字样，也仍然是
`channel=discussion` 的普通 ChatMessage，不能触发 Host、NPC 对话或行动队列。
每条行动区输入最多绑定一个结构化 recipient；同时选择守秘人和 NPC、或同时选择多个 NPC
时，客户端要求玩家保留一个主要目标后再提交。其他同场景 NPC 是否插话由服务端冻结的
`allowed_responder_ids` 和 Host 结构化输出决定，不把多个 `@` 文本交给模型猜测。

多人游戏中未指定对象的消息都不占主持行动槽，也不进入 `MemoryEntry`、
`ConversationSummary` 或 NPC 知识来源，但两个频道的产品语义不同：行动区是角色扮演，
讨论区是玩家讨论。`action.chat.send` 必须落成 `channel=roleplay` 的 `ChatMessage`，不能
继续复用会被记忆投影读取的 `action.broadcast`；`chat.send` 则落成
`channel=discussion`。这样既保留前端频道差异，也不会把角色间闲聊、猜测和临时计划误当
成 NPC 已经听到的剧情记忆。

房间模式必须来自创建房间时不会随连接变化的配置。第一版固定使用
`max_players == 1` 判定单人游戏；以后增加独立 `play_mode` 时再迁移，不能根据当前在线
人数或当前在局人数判断，
避免队友断线后同一句无 `@` 输入突然从玩家聊天变成 Host 行动。

### 5.2 玩家对话事件

固定读模型结构：

```json
{
  "type": "dialogue.player",
  "room_id": "room-1",
  "player_id": "player-1",
  "speaker_id": "actor-1",
  "interlocutor_id": "thomas",
  "listener_ids": ["thomas", "gravekeeper"],
  "participant_ids": ["actor-1", "thomas", "gravekeeper"],
  "allowed_responder_ids": ["thomas", "gravekeeper"],
  "utterance": "月影钟响三次，记住这句话。",
  "visibility": "scene_scoped",
  "audience_player_ids": ["player-1", "player-2"],
  "scene_id": "thomas_office",
  "source_action_id": "action-1",
  "source_revision": "42"
}
```

其中 `audience_player_ids`、`listener_ids` 和 `allowed_responder_ids` 都由服务端在主持行动
实际出队、生成 `dialogue.player` 时根据最新权威状态冻结，客户端和模型不能填写或扩大。
排队提交时的场景只用于早期拒绝，不能替代出队时的再次校验。第一版不实现同场景私聊：

- 主要 `interlocutor_id` 必须是发起玩家当前可见、可交互的 NPC；
- 同场景中服务端能够确认在场、可见且可交互的 NPC 都视为听见公开发言，并进入
  `allowed_responder_ids`；
- `dialogue.player.listener_ids` 等于冻结的 `allowed_responder_ids`，保证所有允许插话的 NPC
  都能确定性记住自己听到的公开发言；
- 当时有角色处于同一场景的所有房间玩家都进入 `audience_player_ids`，收到玩家发言和
  后续 NPC 回复；其他场景玩家不接收；
- NPC 只有在对话发起玩家的最新 PlayerView 中可见、可交互时才能成为 responder，因此
  隐藏、离场、死亡或场景外 NPC 不会通过公开广播意外暴露身份。

`events.visibility` 第一版增加 `scene_scoped`，并使用独立 `event_audiences(event_id,
player_id)` 保存冻结受众，主键为 `(event_id, player_id)`。受众从房间持久化成员及其
PlayerView 计算，不能只遍历当前 WebSocket 连接；断线但当时在场的玩家重连后仍有权回放。
JSON 示例中的 `audience_player_ids` 是从该表生成的服务端读模型字段，不接受客户端写入。
回放时不能按玩家当前场景重新计算。这样玩家离开场景后仍能
恢复自己当时听到的对白，也不会让后来进入场景的玩家补看自己未曾听到的历史。

### 5.3 NPC 回复事件

固定读模型结构：

```json
{
  "type": "dialogue.npc",
  "room_id": "room-1",
  "speaker_id": "thomas",
  "listener_ids": ["actor-1", "actor-2", "gravekeeper"],
  "participant_ids": ["thomas", "actor-1", "actor-2", "gravekeeper"],
  "text": "我会记住的。",
  "visibility": "scene_scoped",
  "audience_player_ids": ["player-1", "player-2"],
  "scene_id": "thomas_office",
  "source_dialogue_id": "dialogue-player-1",
  "source_action_id": "action-1",
  "ordinal": 0,
  "source_revision": "42"
}
```

NPC 回复由 Host 生成，但服务端必须验证：

- `speaker_id` 是当前场景可见 NPC；
- `speaker_id` 属于服务端冻结的 `allowed_responder_ids`；
- `listener_ids` 由服务端生成为冻结场景内的玩家角色，以及除当前 speaker 外的其他
  `allowed_responder_ids`；同场景 NPC 因此能够记住彼此公开说过的话；
- `participant_ids` 是 `speaker_id + listener_ids` 的确定性去重结果；
- `audience_player_ids` 与来源 `dialogue.player` 的冻结场景受众一致；
- NPC 没有读取无权限的记忆；
- 回复没有直接写入 Engine 状态；
- 回复长度和消息数量受预算限制。

### 5.4 守秘人叙事事件

环境描述、行动结果和规则后果继续保存为现有事件：

```json
{
  "type": "narration.push",
  "text": "你随后另行决定推开沉重的木门。",
  "claimed_evidence_refs": ["event-42"],
  "visibility": "public"
}
```

前端可以把这些消息合并为一个连续回合，但后端必须把 `dialogue.npc` 和
`narration.push` 分开保存。旧客户端继续正常识别 `narration.push`；新客户端把它显示为
守秘人消息。两者可能来自玩家先后提交的 NPC 对话和守秘人行动，不能因为 UI 连续展示就
合并成同一个 request 或让前一条 `@NPC` 自动推进后一项行动。

### 5.5 NPC 头像、独立声线与语音播报预留

NPC 对话第一版也不实现头像生成，但 `dialogue.npc.speaker_id` 必须足以让前端查询当前
NPC 头像。事件中不保存头像 URL、二进制或 Provider 任务 ID，避免头像更新后历史事件
失效。未来优先复用现有角色头像的 Provider、图片物化、格式校验、任务恢复和内容哈希
能力，仅新增 NPC 作用域存储：

```text
canonical NPC：module_id + module_version + entity_id
runtime NPC：第一版使用通用头像，确有需求时再增加 room_id + entity_id 绑定
```

模组已有静态立绘时优先使用 `ModuleAsset`；只有没有可用素材时才调用头像 Provider。
不在 `EntitySpecV3` 或 dialogue Event 中预留供应商专属头像字段。

NPC 对话第一版不实现声线匹配和语音生成，但结构化事件必须保证未来可以按说话者选择
音色。每一条 `dialogue.npc` 都必须有稳定的 `event_id`、`speaker_id`、`text` 和
`visibility`；多个 NPC 的回复分别落成多个事件，不能合并成一段待解析的自由文本。

未来语音链路复用现有 Host Speech 的 Provider、分句、限流、请求合并和音频缓存：

```text
dialogue.npc 权威事件
  → 校验当前玩家有权读取该事件
  → 根据 speaker_id 查 NPC 声线绑定
  → 使用现有 TTS Provider 合成
  → 按事件和分句返回音频
```

推荐提供与现有主持人语音清单相同形态的只读接口，例如：

```text
GET /rooms/{room_id}/dialogues/{event_id}/speech
GET /rooms/{room_id}/dialogues/{event_id}/speech/sentences/{sentence_index}
```

接口只能读取已落库的权威事件，不能接受前端任意提交的 `text + speaker_id`。这样语音
接口与对话事件使用同一套多人可见性规则，不会通过 TTS 绕过私密对话权限。

Provider 音色 ID 不写入不可变 `ModuleContentV3`，避免更换供应商或音色下架后污染模组
契约。未来用独立绑定保存部署相关配置：

```text
npc_voice_bindings
  module_id
  module_version
  entity_id
  provider
  voice_type
  updated_at

唯一键：(module_id, module_version, entity_id, provider)
```

同一模组版本的 NPC 声线可以被所有房间复用。自动匹配时，可使用 NPC 名称、描述与
模组 `world_profile`，在当前 Provider 的允许音色清单中选择并保存绑定；选择逻辑放在
后端应用层，不进入 Engine，也不能修改 NPC 的权威状态。

当前阶段不为 `EntitySpecV3` 增加 Provider 专属头像或 `voice_type`。只有实际匹配质量证明
名称、描述和模组背景不足时，再增加与供应商无关的 `voice_profile`（例如年龄感、音高、
语速和口音倾向）。缺少绑定、音色下架或 TTS 失败时回退到通用 NPC/主持人音色；文本
对话和 Memory 投影必须继续正常完成。

---

## 6. `@NPC` 和目标验证

### 6.1 `@` 的真实含义

`@守秘人`、`@主持人` 和 `@NPC` 都只是 UI 语法，进入后端时必须转换成结构化接收者，
不能由 WebSocket 层重新解析自然语言。`ActionSubmitPayload` 和持久化主持行动队列都保存
同一份 recipient：

```json
{
  "recipient": {
    "kind": "npc",
    "entity_id": "thomas",
    "explicit": true
  }
}
```

接收者规则固定为：

- 单人游戏未 `@`：`kind=keeper, explicit=false`；
- 明确 `@守秘人` 或 `@主持人`：`kind=keeper, explicit=true`；
- 明确 `@NPC`：`kind=npc, entity_id=<稳定实体 ID>, explicit=true`；
- 多人游戏未 `@`：不创建 Host 请求，直接走玩家聊天协议。

接收者同时决定执行权限：

```text
recipient.kind = npc
  → 整条 utterance 是角色内发言
  → 只创建 dialogue.player / dialogue.npc
  → 不调用 Keeper Planner、ActionPlan、技能检定或 Engine

recipient.kind = keeper
  → 才允许进入现有 Keeper Planner / ActionPlan / Engine
```

因此 `@NPC` 后即使出现“去某地”“使用某技能”“拿走物品”等行动词，也不能被服务端或
模型提升为实际行动。NPC 可以基于自身认知提出建议或回应玩家计划，但不得声称这些行动
已经发生。玩家要执行计划必须再提交一条守秘人输入。

服务端根据房间模式验证该组合，多人游戏不能接受隐式 Keeper 请求。NPC 的
`entity_id` 随后映射为本方案其他部分使用的 `interlocutor_id`。不允许后端从“你”、
“记住”“跟你说”等自然语言关键词猜测听众。

第一版 `@NPC` 与 `@守秘人` 统一复用 PR #404 已有的房间主持行动队列，但出队后按
`recipient.kind` 分流：Keeper 项进入现有 ActionPlan，NPC 项进入专用 `NpcDialogueService`。
这样复用 FIFO、行动占用和限流，同时不会让 NPC 对话经过 Keeper Planner。纯对话可能
短暂等待当前世界行动，这是有意的最小实现取舍；只有实际长局数据证明等待不可接受时，
才增加按 `(room_id, npc_id)` 串行的 NPC 专用队列。

为支持服务重启和 Provider 失败恢复，现有 `host_action_queue` 在实现 NPC 路径时增加最小
任务字段：`lease_owner/lease_expires_at/attempt_count/next_attempt_at/result_event_ids`，状态扩展
为 `queued → processing → completed | retryable_failure`，并保留 `cancelled/discarded` 终态。
这只服务主持队列，不建立通用任务平台。`dialogue.player` 先幂等落库；模型成功后，全部
`dialogue.npc`、Outbox 和队列完成状态在同一事务提交，禁止出现只发布一半 NPC 回复的状态。

### 6.2 服务端验证

服务器收到 `interlocutor_id` 后必须检查：

1. NPC ID 存在；
2. NPC 属于当前房间的 Engine/ModuleContent；
3. NPC 当前存在于 `PlayerView.scene.visible_entities`；
4. NPC 的 `kind` 是 `npc`；
5. NPC 当前没有被隐藏、死亡、离场或禁止交互；
6. 玩家和 NPC 处于允许互动的场景和权限范围。

检查必须执行两次：

```text
入队时：快速拒绝当前已经无效的目标，并冻结 recipient.entity_id
出队时：读取最新 PlayerView 再验证 NPC 和 actor
```

排队期间 NPC 可能离场、死亡、隐藏或变得不可交互。出队验证失败时保存一条玩家可见的
`narration.push` 澄清并结束该队列项，不调用 NPC Narrator，不生成 `dialogue.player`、
`dialogue.npc` 或 NPC Memory。队列 UI 可以展示“待处理原话”，但只有出队验证成功后
落库的 `dialogue.player` 才表示 NPC 确实听见。

如果玩家在托马斯家里发送“我和守墓人交流”，但守墓人不在场，系统不能把玩家传送到墓地，也不能让守墓人隔空回答，应返回澄清：

```text
这里没有看到守墓人。你是要和托马斯交谈，还是先前往墓地？
```

NPC 身份必须来自 ModuleContent/Engine 的稳定实体 ID。名称、别名和自然语言只用于
界面展示或辅助搜索，不能作为权限判断或事件主体。服务端还要明确 NPC 在死亡、隐藏、
离场和不可交互状态下的判定结果；这些状态都必须以当前 `PlayerView` 为准。

当前 PlayerView 中 `kind=npc` 的 runtime entity 也可以成为 interlocutor。canonical NPC ID
随模组版本稳定；runtime NPC ID 只要求在当前房间稳定且不能覆盖 canonical ID。两者的
dialogue、Memory 和 Summary 都以 `(room_id, entity_id)` 隔离，runtime NPC 第一版使用
默认头像和默认声线，不创建模组级媒体绑定。

### 6.3 多 NPC 回复

一次 NPC 对话可以允许多个 NPC 按顺序回复，但每个说话者都必须满足：

- 当前可见；
- 属于本次对话参与者；
- 由结构化上下文允许；
- 不能由模型凭空添加场景外 NPC。

第一版固定每次 NPC 对话最多 3 条 NPC 消息。服务端在对话开始时从同场景可见、可交互
NPC 生成 `allowed_responder_ids`；主要 `interlocutor_id` 必须是第一名回复者，其他 NPC
可以选择不回复，但模型不得跳过主要目标后只让旁人代答。每条回复单独落库并保留 ordinal，
前端按 ordinal 展示。每条消息最多 1000 字符，同一次对话的全部 NPC 消息合计最多 2400 字符。

示例：

```text
玩家：你们怎么看这件事？

托马斯：我认为应该离开这里。
守墓人：不，留下才是安全的。
```

这是一次 Host 调用中生成多个结构化 NPC 消息，不是启动多个 NPC Agent。

### 6.4 已固定的跨模块契约

以下约束属于跨模块契约，实现 PR 不得临时改成另一套语义：

1. **NPC 身份来源**：`interlocutor_id` 使用稳定实体 ID；服务端以当前
   `PlayerView` 验证存在、可见、可交互和状态有效。
2. **事件权限**：`speaker_id/listener_ids` 表示世界中的说话者和听众；
   `audience_player_ids` 表示哪些玩家有权接收和回放，两者不得混用。场景受众在
   `dialogue.player` 实际生成时冻结到 `event_audiences`，回放时不能按当前场景重算。
3. **幂等与顺序**：`dialogue.player` correlation 固定为 `{source_action_id}:player`；每条
   `dialogue.npc` 固定为 `{source_action_id}:npc:{ordinal}`。重复提交不得重复广播、写
   Memory 或重复完成队列项。
4. **Host 输出失败**：目标无效时直接澄清且不调用模型；schema 错误、非法 speaker、
   越权 memory ref 或超预算时携带玩家安全反馈重试一次；Provider 超时或第二次
   仍非法时进入 `retryable_failure`，保留已落库的玩家发言。
5. **摘要信任边界**：`viewer-scoped Summary` 只能由该 viewer 有权读取的
   canonical `MemoryEntry` 重建，不能先生成全知共享自由文本再做字符串裁剪。
6. **纯对话边界**：NPC 队列项直接进入 `NpcDialogueService`，不得创建 ActionPlan、
   ActionAdjudication、技能检定或 Engine effect。
7. **广播闸门**：队列完成只等待 NPC 回复成功落库，不等待 WebSocket 客户端确认。玩家
   断线时仍可完成，重连通过权威 Event 回放恢复。
8. **取消语义**：`dialogue.player` 已经落库后收到取消，不删除或回滚已经发生的发言；只
   阻止尚未生成的 NPC 回复。
9. **第一版隐私范围**：普通 NPC 对话只支持场景公开，不实现同场景私聊或小组私聊；
   clarification 和既有玩家私有事件仍沿用 `player_scoped`。
10. **自由交流边界**：无 `@` 的 `roleplay/discussion` 都落入 ChatMessage，不进入 Event、
    Memory、Summary 或 Host 上下文。
11. **公开听众边界**：`dialogue.player` 的 NPC listener 是全部 allowed responder；每条
    `dialogue.npc` 的 listener 是同场景玩家角色和其他 allowed responder。模型只生成
    `speaker_id + text`，不能自行增删听众。
12. **接收者权限边界**：`@NPC` 整条原文都是对白。行动式措辞只保存在
    `experienced conversation` 中，并明确写成玩家的未确认声称/计划；不得据此生成
    `action/visit` Memory，更不能触发旅行、检定、物品变化或其他权威状态修改。

这些约束应在契约测试和恢复测试中先固定，再接入真实 Host；它们不是模型提示词可以
替代的规则。

---

## 7. 纯 NPC 对话执行方案

### 7.1 路由原则

`recipient.kind` 在进入模型前已经由客户端选择和服务端验证。应用层不得再让模型决定一条
`@NPC` 输入究竟是对话还是行动：

```text
@NPC 我准备去地下室并使用侦查检查门
  → NPC 听见玩家陈述计划
  → 可以给出角色内回应
  → 不移动玩家，不创建检定，不改变门

@守秘人 我去地下室并使用侦查检查门
  → 进入现有 Keeper Planner / ActionPlan
  → Engine 分别裁决旅行、技能和目标
  → narration.push 描述权威结果
```

第一版不支持“一条 `@NPC` 消息先让 NPC 回答，再自动执行同条消息中的玩家行动”。玩家
必须分成两次提交。该限制换来清晰的权限边界、准确的 NPC 原话记忆，以及无需猜测自然
语言片段的确定性实现。

### 7.2 NPC 对话时序

```text
带 recipient.kind=npc 的输入进入 HostActionQueue
  ↓
出队时重新验证 interlocutor_id 和最新 PlayerView
  ↓
冻结 listener、allowed_responder 和 event audience
  ↓
按 {source_action_id}:player 幂等落库整条 dialogue.player 原文
  ↓
NpcDialogueService 读取受限 NPC Context 和安全历史召回
  ↓
Host provider 只生成一至三条 speaker_id + text
  ↓
服务端校验 speaker、长度、权限和消息预算
  ↓
全部 dialogue.npc + Outbox + 队列 completed 在同一事务提交
  ↓
异步投影 NPC Memory 和 Summary
```

NPC Context 不包含 `keeper_capabilities`、隐藏 ModuleContent 或 Engine 写能力。模型即使在
文本中声称“你已经到达地下室”也不能改变 PlayerView；这类无证据结果应由输出审查测试和
提示词约束避免，但权威安全最终由“该路径根本不调用 Engine”保证。

### 7.3 恢复和取消

`NpcDialogueService` 不创建 ActionPlanRun。队列 lease 过期后重新领取时，先按固定
correlation 查询 Event：

- `dialogue.player` 已存在时不重复广播，只继续生成 NPC 回复；
- 任一 `dialogue.npc` 已存在意味着上一批回复事务已经提交，直接恢复
  `result_event_ids` 并完成队列项；
- Provider 失败保留玩家发言并按有限退避重试，不产生虚假的 NPC 回复；
- 玩家发言落库后的取消不能删除这句话，只能阻止尚未开始的回复调用。

---

## 8. NPC 独立长期记忆

### 8.1 记忆主体

NPC 使用现有 `MemoryEntry`，但查询主体从玩家扩展为 NPC：

```text
玩家记忆：room_id + player_id
NPC 记忆：room_id + npc_id
```

同一房间中的同一个 NPC 只有一份 canonical 认知记忆。

为区分“NPC 知道”和“哪些玩家有权在 Host 回复中看到”，MemoryEntry 增加服务端生成的
受众字段：

```text
audience_player_ids: tuple[player_id, ...]
```

`subject_id/listener_ids/participants` 保存世界内认知关系，`audience_player_ids` 保存玩家
权限。场景公开 dialogue 的受众从对应 Event 复制；房间公开 Memory 可以使用空数组表示
所有房间玩家。SQLite/PostgreSQL 查询必须使用 JSON 元素成员判断，不能做
字符串包含，也不能因为 `subject_id == npc_id` 就绕过 viewer 过滤。

### 8.2 记忆类型

NPC 记忆继续使用认知等级：

```text
experienced  NPC 亲自听到或亲自经历
heard        NPC 被明确告知
asserted     角色提出但未被确认的说法
confirmed    Engine 或权威事件确认
presentation 只有叙事表现，不作为事实依据
```

玩家对 NPC 的明确发言：

```text
subject_id = npc_id
kind = conversation
epistemic_status = experienced
listener_ids = [npc_id]
```

这里的 `experienced` 只确认 NPC 亲自听见了这句话，不确认话中描述的行动已经发生。例如
玩家说“我准备去地下室”，记忆内容应是“NPC 听见玩家声称/计划去地下室”，不能投影为
已到访地下室的 `visit` 或 `confirmed` 行动。

没有在场、没有明确听众或没有告知证据时，不生成 NPC `experienced` 记忆。

Narrator 写出“NPC 点头”“NPC 似乎记住了”不能单独生成记忆。

新写入的 NPC `experienced` 对话记忆只从服务端确认的 `dialogue.player` 投影。
`action.broadcast` 不再通过“说、问、告诉、记住”等中文关键词猜 listener，也不再作为新
NPC 对话认知的来源；经过当前 PlayerView 验证的结构化 recipient 和服务端冻结的
`dialogue.player.listener_ids` 才是听众证据。历史已经
带 listener_ids 的旧 action.broadcast 可以保留兼容投影，但不得影响新写入路径。

为清理 PR #404 已经写成 action.broadcast 的无 `@` roleplay，Memory 和玩家摘要重建只把
能够关联到已持久化 ActionPlanRun 或已提交 Adjudication execution 的 action.broadcast
视为 Host 行动；没有权威关联记录的 action.broadcast 按旧自由消息处理并排除。队列中尚未
执行的原话也不提前进入长期 Memory/Summary，等计划真正落库或提交后再由正常链路处理。

### 8.3 NPC 回复也写入记忆

NPC 对玩家说出的结构化回复投影为：

```text
subject_id = speaker_npc_id
kind = conversation
epistemic_status = experienced
content = NPC 曾经向玩家说过的原话
```

同场景其他 NPC 出现在该回复的 `listener_ids` 时，还要为每个 listener NPC 分别投影一条
`experienced` conversation Memory，内容表示它亲自听到 speaker 说过什么。来源事件唯一键
保证重复投影不产生重复记录。玩家角色是否收到消息由 `audience_player_ids` 决定，不能用
NPC Memory 的 subject 反推玩家权限。

如果 NPC 回复只是模型主张而非 Engine 事实，则不能使用 `confirmed`。

### 8.4 NPC 近期对话和摘要

NPC 对话上下文分为：

```text
近期对话：最近若干条 dialogue.player / dialogue.npc
长期 MemoryEntry：可审计的亲历、听闻、主张和事实
NPC Summary：长期剧情和对话概况
原始 Event：精确逐字回忆来源
```

普通回合只加载摘要、近期对话和相关记忆；玩家明确追问原话时，再按权限查询原始事件。

第一版固定预算：

```text
当前 NPC + viewer 近期 dialogue：最多 8 条、3000 字符
相关长期 MemoryEntry：最多 12 条、4000 字符
NPC Summary：最多 6000 字符
```

NPC Summary 不扩展现有 `(room_id, player_id)` 的 `conversation_summaries` 多态语义，而是
新增专用 `npc_conversation_summaries`：

```text
room_id
npc_id
viewer_player_id
summary_json
through_event_created_at / through_event_id
pending_through_event_created_at / pending_through_event_id
source_revision / source_event_ids
status / attempt_count / next_attempt_at / lease_owner / lease_expires_at
updated_at

唯一键：(room_id, npc_id, viewer_player_id)
```

复用现有 ConversationSummary 的结构化模型 client、lease、有限重试和退避处理思路，但
不复用“可见事件数组下标”作为 NPC 游标。NPC 摘要按来源 Event 的 `(created_at, id)` 单调
推进，只扫描该 NPC 与 viewer 有权读取的新 dialogue。满足 10 条新 dialogue、6000 个新
字符或玩家离开当前对话场景之一时异步入队；失败保留旧摘要，不阻塞回合。

摘要遇到 `@NPC` 中的行动式说法时必须保留认知边界，例如写成“玩家声称准备前往地下室”，
不得压缩成“玩家前往了地下室”。只有之后独立的 Keeper/Engine Event 才能确认行动结果。

---

## 9. 多人隐私设计

### 9.1 canonical 记忆和可见摘要分离

同一 NPC 的 canonical MemoryEntry 可以在房间级共享，但每条 Memory 仍保留来源事件的
冻结玩家受众；不能把自由文本摘要直接共享给所有玩家。

固定存储：

```text
MemoryEntry：room_id + npc_id，共享 canonical 认知，带 audience_player_ids
NpcConversationSummary：room_id + npc_id + viewer_player_id，按玩家生成
```

### 9.2 私密知识边界

```text
既有 player_scoped Event 或未来私聊事件
    ↓
NPC canonical Memory 记录认知，同时冻结 audience_player_ids
    ↓
只有受众玩家的 read_npc_context 可以读取
```

第一版不提供同场景 NPC 私聊，也不允许 NPC 主动向未授权 viewer 披露 canonical 私密知识。
以后若增加私聊或知识披露，必须由明确的 Engine/事件链能力扩展受众并生成“NPC 已告知”
事件，不能让自由模型自行决定泄露。

### 9.3 对话可见性

- 普通 NPC 对话：`scene_scoped`，发送给事件发生时同场景的全部冻结玩家受众；
- 第一版不提供同场景私聊；既有 clarification 等玩家私有事件继续使用
  `player_scoped`；
- `ChatMessage` 的 `discussion/roleplay` 消息：沿用房间受众，永远不进入 NPC 记忆和摘要；
- 守秘人回复玩家时，仍按当前玩家的 PlayerView 和可见事件过滤。

### 9.4 守秘人全局认知与玩家安全输出

守秘人系统在逻辑上全知：应用层的 Keeper Planner 可以读取当前房间全部已经提交的
`GameState`、`GameEvent`、权威 `Event`、`ActionExecution`、`MemoryEntry` 和隐藏
`ModuleContent`，包括不同玩家和 NPC 的私密经历。这个权限用于维持世界连续性和正确裁决，
例如知道某名玩家已经触发隐藏机关，即使当前回应的另一名玩家尚未发现原因。

“全知”表示拥有房间级检索权限，不表示每轮把所有历史塞进 Prompt，也不表示所有记录都是
确认事实：`asserted/heard/presentation` 的认知等级仍然保留，Memory 也不能覆盖当前
GameState。`ChatMessage`、尚未执行的队列原话和未提交结果不属于游戏记忆，守秘人同样不读。

守秘人的内部裁决和玩家可见回复必须使用两份独立上下文：

```text
Keeper Planner 内部上下文
  → 当前房间全部权威状态和隐藏模组信息
  → 全房间相关 Event / Memory 的有界检索结果
  → 只用于规划和维持世界连续性

Engine
  → 只接收经过契约校验的命令
  → 不读取 Memory / Summary，继续以 GameState 为唯一事实源

Keeper Narrator 玩家安全上下文
  → 当前玩家的 PlayerView
  → 当前玩家可见的 committed evidence / Event / Memory / Summary
  → 只生成该玩家有权看到的 narration.push
```

两次 Host 调用不得复用跨权限的会话历史、`previous_response_id` 或包含全局上下文的缓存
transcript。Planner 结果进入 Narrator 前必须转换成玩家安全 DTO，只允许当前 PlayerView、
已提交且可见的 evidence 和公开执行结果跨越边界；隐藏事件原文、其他玩家私密记忆和隐藏
ModuleContent 不能进入 Narrator payload。

---

## 10. Host 输入和输出

### 10.1 NPC 对话输入

处理 NPC 对话队列项时，Host 应获得：

```text
当前 PlayerView
当前 interlocutor_id
服务端冻结的 allowed_responder_ids / audience_player_ids
NPC 可见描述和状态
NPC 近期对话
NPC 相关 MemoryEntry
NPC viewer-scoped ConversationSummary
当前玩家原话
```

优先级保持：

```text
PlayerView
> committed evidence
> experienced/heard MemoryEntry
> confirmed MemoryEntry
> NPC Summary
> RecentTurnContext
> asserted/presentation
```

### 10.2 结构化输出

固定输出：

```json
{
  "npc_messages": [
    {
      "speaker_id": "thomas",
      "text": "我会记住的。"
    }
  ]
}
```

`npc_messages` 固定 `min_length=1, max_length=3`。模型只返回服务端允许的 speaker 和文本，
不返回 listener、audience、visibility 或未来 Keeper 叙事；这些字段全部从冻结对话上下文
确定性生成。该队列项在 NPC 回复落库后结束；需要执行行动时，玩家另行提交守秘人输入，
由现有 ActionPlan Narrator 产生普通 `narration.push`。

服务端需要校验：

- `speaker_id` 在允许参与者中；
- 第一条消息的 `speaker_id` 等于主要 `interlocutor_id`；
- 消息引用的 NPC 当前可见；
- 输出没有隐藏协议字段；
- 输出没有未经证据支持的持久化事实；
- 返回数量、字符和建议动作不超过预算。

模型输出非法时不猜测修复，不生成虚假的 NPC 回复；保留已提交的玩家发言，并走可见的
澄清、有限重试或降级路径。

NPC 上下文必须由新的 `read_npc_context(room_id, npc_id, viewer_player_id, actor_id,
revision, ...)` 组装。它先按 `audience_player_ids` 和 Event visibility 过滤，再做 NPC、地点、
关键词和时间排序；禁止通过现有玩家 `read_context(entity_ids=(npc_id,))` 的实体相关性分支
直接取得 NPC 的全部 canonical 私密记忆。

### 10.3 守秘人上下文

新增仅供后端应用层调用的 `read_keeper_context(room_id, revision, ...)`。它复用现有 Event、
GameEvent 和 Memory 存储，不复制一套“守秘人记忆”，也不接受客户端或模型指定
`room_id`、`player_id`、visibility 或 subject 来扩大权限。房间 ID 必须来自当前已认证的
主持队列项，读取结果必须绑定当前 revision。

Keeper Planner 每轮固定获得精简 GameState、当前行动相关隐藏规则和有界全局记忆；检索
优先当前地点、行动目标、输入提及实体、未解决目标和最近权威变化。旧细节仍保存在原始
Event 中，应用层按需查询。第一版复用已有 Memory/Event 查询；现有按玩家隔离的
ConversationSummary 仍然只进入对应玩家的 Narrator 上下文，不能
合并成全知摘要。第一版不新增全房间自由文本摘要表；只有长团测试证明结构化召回不足时，
再设计专用 Keeper Campaign Summary。

Planner 可以依据全局历史理解因果关系并提出计划，但不能凭 Memory 直接修改状态；计划仍须
经过现有契约校验和 Engine 裁决。Engine 不新增 `read_keeper_context` 依赖。

Narrator 不调用 `read_keeper_context`。它继续使用当前玩家作用域的 `read_context()` 和
`ConversationSummary`，并以当前 PlayerView 为最高优先级。因此守秘人系统可以知道所有
事情，但面向玩家时只说出该玩家此刻能够观察或已经获知的部分。

---

## 11. 历史按需召回

长团支持的关键不是无限增加 Prompt，而是固定预算下的按需查询。

新增服务端只读查询，至少支持：

```text
room_id
viewer_player_id
actor_id
subject_id（可选 NPC 或玩家）
entity_ids（可选）
location_id（可选）
kinds（可选）
query_text（可选）
limit
max_chars
```

查询服务必须有两个不可混用的服务端入口：

- `read_keeper_context`：仅 Keeper Planner 内部使用，先强制绑定当前房间，再对全房间已
  提交记录执行有界相关性检索；
- `read_npc_context/read_context`：继续按 `viewer_player_id`、actor、事件受众和 visibility
  过滤，供 NPC 回复和玩家可见 Narrator 使用。

不能通过一个来自客户端的 `include_private=true` 或可伪造 scope 参数切换到守秘人权限。

当前 Host 端口是结构化单次生成，不假设存在 Agent 工具循环，也不依赖 ActionPlan
Planner 提供查询意图。`NpcDialogueService` 在每次模型调用前，将当前玩家原话截断到
最多 200 字符作为 `query_text`，强制绑定当前
`room_id/viewer_player_id/actor_id/interlocutor_id`，先执行有界 Memory 和原始 dialogue Event
查询，再把有限结果放入 NPC Context。客户端和模型都不能提供房间、玩家或其他 NPC 作用域。

查询必须使用数据库条件和固定预算，不能把房间全量 Event 拉到内存扫描。原始 Event 查询
始终先按当前 actor 与 interlocutor 的 dialogue 关系过滤，再做关键词和来源时间排序。玩家
明确给出主题或原话片段时可以返回精确候选；玩家只问“我以前跟你说过什么”而没有范围时，
服务端只返回有限候选元数据，由 NPC 请求玩家补充条件，不能擅自选择一条冒充唯一答案。

没有足够关键词时只使用固定的近期窗口、相关 Memory 和 NPC Summary，不扩大原始 Event
扫描范围。

查询顺序：

```text
权限过滤
→ 当前 NPC
→ 当前地点
→ 玩家明确提及的实体
→ 记忆类型
→ 关键词相关性
→ 认知等级
→ 来源时间
```

第一版只使用现有数据库结构化条件和关键词检索，不引入 Embedding 或向量数据库。

当玩家问：

```text
我当时原话是什么？
```

系统应查询原始 `dialogue.player` Event，而不是让摘要模型伪造引号。

没有匹配原始事件时，NPC 只能说明无法准确回忆或请求玩家补充范围，不能由 Summary
补造逐字引号。`location.entered` 的 Memory 投影还必须把权威 payload 中的
`location_id` 写入 visit Memory；否则守秘人历史查询只能知道发生过移动，无法稳定回答
玩家曾经去过哪里。

---

## 12. 实现步骤

### 阶段 0：契约和现状梳理

工作内容：

- 从包含 PR #404 的最新 `main` 创建实现分支；
- 为现有 ActionPlan、HostActionQueue、Event、ChatMessage、MemoryEntry 和
  ConversationSummary 写迁移前基线测试；
- 固定 schema/codegen 漂移检查，保证 Framework、Backend、SDK 和 Frontend 使用同一事件
  union。

难度：低。

风险：如果直接在 WebSocket 层猜 NPC，容易重新引入之前的监听人误判问题。

### 阶段 1：结构化对话契约

工作内容：

- 增加 `interlocutor_id`；
- 在 ActionSubmitPayload 和 HostActionQueue 冻结结构化 recipient；
- 增加 `dialogue.player` 和 `dialogue.npc` 事件契约；
- 复用 `narration.push`，不新增 `narration.keeper`；
- 增加 `scene_scoped` 和持久化 `event_audiences`；
- 服务端在入队和出队时分别验证 NPC 当前可见且可交互；
- 增加主要目标、多 NPC responder 白名单和最多 3 条消息的约束；
- 为 `ChatMessage` 增加 `discussion/roleplay` channel 和 roleplay actor_id；
- 旧 ChatMessage 的 channel 迁移默认回填 discussion，新 roleplay 必须带 actor_id；
- 停止为新 action.broadcast 推断 listener，并增加 PR #404 历史自由消息的重建兼容规则。

难度：中等。

主要风险：前端、WebSocket、Event replay 和 Host schema 需要保持兼容。

### 阶段 2：纯对话服务和恢复

工作内容：

- 新增最小 `NpcDialogueService`，`recipient.kind=npc` 出队后直接调用；
- 明确绕过 Keeper Planner、ActionPlan、ActionAdjudication 和 Engine；
- 整条玩家原话按固定 correlation 幂等写入 `dialogue.player`；
- 组装受限 NPC Context，并调用 Host provider 生成结构化 NPC 回复；
- NPC 回复、Outbox 和队列完成状态在同一事务提交；
- 扩展主持队列 lease、有限重试、退避和结果事件恢复；
- 对原有 Keeper ActionPlan 保持兼容。

难度：中高。

主要复杂度集中在持久化恢复，而不是 ActionPlan 时序：

- 重连和恢复；
- lease 过期和玩家发言已经落库；
- NPC 回复生成失败；
- Event/Outbox/队列状态的事务一致性；
- 重复提交和重复模型调用；
- 旧客户端只识别 `narration.push` 的兼容。

### 阶段 3：NPC Memory 和 Summary

工作内容：

- 为 MemoryEntry 增加冻结 `audience_player_ids`；
- 增加严格的 `read_npc_context`，不得通过普通实体相关性绕过 viewer 权限；
- 将结构化 dialogue 事件投影为 `experienced/heard`；
- 增加 NPC 近期对话窗口；
- 新增 `npc_conversation_summaries`，不修改现有玩家摘要 owner 语义；
- 按 npc_id + viewer_player_id 生成 NPC 摘要并使用事件复合游标；
- 保留原始 Event 作为精确回忆来源；
- 增加内部 `read_keeper_context`，复用现有房间 Event/Memory 存储，不新建重复记忆表；
- 将 Keeper Planner 全局上下文与 Narrator 玩家安全上下文拆成独立 DTO 和独立模型请求。

难度：中高。

主要风险：NPC 共享认知和玩家隐私之间需要严格的查询过滤，不能把一份未经裁剪的自由文本摘要发给所有玩家。

### 阶段 4：历史按需召回

工作内容：

- 增加服务端只读查询服务；
- `NpcDialogueService` 使用当前原话执行受限查询，并在 Narrator 前预取；
- 支持 NPC、地点、实体、记忆类型和关键词过滤；
- 固定条数和字符预算；
- 玩家明确追问原话时查询原始 Event；
- `location.entered` 确定性写入 visit.location_id；
- 禁止模型扩大查询范围。

难度：中等。

第一版不做向量搜索，先使用结构化 SQL 和关键词查询，降低维护成本。

### 阶段 5：前端展示和回放

工作内容：

- NPC 消息显示明确说话者名称；有静态立绘时显示头像，没有时使用默认头像；
- 守秘人叙事使用独立样式；
- 玩家消息、NPC 消息和守秘人描述按事件顺序混合显示；
- 兼容旧 `narration.push`；
- 刷新、重连、历史回放保持同样顺序。
- 第一版只保证稳定 `speaker_id` 可供未来头像与语音接口查询，不实现 NPC 生图、音色匹配
  或 TTS 接口。

难度：中等。

注意：后端必须结构化保存，但前端不必变成传统多人聊天软件。视觉上仍然可以保持跑团叙事风格。

### 12.6 迁移与兼容顺序

每个阶段只增加自己需要的迁移，并直接接在开发时最新 Alembic head 后：

```text
阶段 A
  host_action_queue.recipient_kind / recipient_entity_id
  chat_messages.channel / actor_id（旧行 channel=discussion）
  events.visibility 支持 scene_scoped
  event_audiences(event_id, player_id)

阶段 B
  host_action_queue lease / retry / result_event_ids
  host_action_queue 状态约束支持 processing / completed / retryable_failure
  旧 started 行缺少可恢复 lease 和结果游标，保守迁移为 completed，保留 cancelled / discarded

阶段 C
  memory_entries.audience_player_ids（旧 public 行为空数组）
  npc_conversation_summaries 及任务索引、事件复合游标索引
```

迁移必须同时覆盖 SQLite 和 PostgreSQL。旧客户端继续读取 `narration.push`；新 dialogue
事件在旧客户端按未知事件安全忽略，不能导致整个回放解码失败。所有新建代码文件开头添加
中文用途说明，关键受众冻结、事务、CAS、游标推进和恢复分支添加中文注释。

---

## 13. 测试计划

### 13.1 契约和权限

- 单人房间未 `@` 的输入默认生成 Keeper Host 请求；
- 多人行动区未 `@` 生成 `channel=roleplay`、带 actor_id 的 ChatMessage；
- 多人讨论区未 `@` 生成 `channel=discussion`、显示玩家昵称的 ChatMessage；
- 两类无 `@` 消息都不调用 Host、不占行动槽、不进入 Event/Memory/Summary；
- 多人房间断线或重连不会改变上述路由；
- `@守秘人` / `@主持人` 生成 Keeper Host 请求，`@NPC` 生成带稳定
  `interlocutor_id` 的 NPC Host 请求；
- `@NPC` 中包含地点、技能、物品或攻击措辞时仍只生成 dialogue Event；
- `@NPC` 不创建 ActionPlan、ActionAdjudication、PendingCheck 或 Engine Event；
- Fake provider 断言 `@NPC` 不调用 Keeper Planner，只调用一次 NPC Narrator；
- `interlocutor_id` 不在当前场景时被拒绝；
- 当前场景没有目标 NPC 时触发澄清；
- 隐藏 NPC 不能生成回复；
- 入队后、出队前离场或死亡的 NPC 触发澄清且不生成 dialogue/Memory；
- NPC 回复 speaker 必须属于 allowed_responder_ids，且第一条来自主要 interlocutor；
- 同场景冻结受众可以收到和回放 dialogue，其他场景玩家不能收到；
- 同场景其他 allowed responder NPC 会听到并记住玩家和 NPC 的公开对白；
- 玩家后来进入该场景时不能补看自己当时不在场的 dialogue；
- `ChatMessage` 不生成 NPC 记忆；
- 跨房间、跨玩家、跨 NPC 记忆被拒绝；
- 私密 NPC 记忆不会出现在其他玩家上下文。

### 13.2 多消息和恢复

- 一次 NPC 对话可以返回两个或三个可见 NPC 的有序回复；
- 不允许场景外 NPC 插入消息；
- NPC 回复落库后队列项直接结束，不执行任何 Engine action；
- NPC 回复失败时保留玩家发言并按有限退避重试；
- 重连后不会重复生成 NPC 回复；
- NPC 回复批次、Outbox 和 completed 状态原子提交，不出现部分 ordinal；
- NPC 回复落库后玩家断线，重连通过 Event 恢复对白；
- `dialogue.player` 落库后的取消不删除对白，只阻止尚未开始的回复调用；
- 同一 `client_action_id` 重试不会重复写入或重复广播。

### 13.3 记忆和摘要

- NPC 亲自听到的话生成 `experienced`；
- NPC 听见行动计划只生成 `experienced conversation`，内容明确标记为玩家声称/计划；
- 上述发言不会额外生成 `action`、`visit` 或 `confirmed` Memory；
- 没有听众证据时保持 `asserted`；
- Narrator 的“点头”“记住了”不会自动升级事实；
- NPC 摘要按 viewer 玩家隔离；
- NPC 摘要将行动式发言保留为“玩家声称/计划”，不会写成已发生事实；
- 摘要失败不阻塞当前回合；
- 10 条 dialogue、6000 字符和离开场景分别触发 NPC 摘要；
- NPC 摘要运行期间追加事件时复合游标只前进、不覆盖新 pending 目标；
- 原始 Event 可以返回精确对话；
- 玩家追问原话但没有匹配 Event 时，NPC 不会用摘要伪造引号；
- `location.entered` 重建后 visit Memory 带正确 location_id；
- 连续 300～500 个回合、至少 3 次摘要压缩后仍能按需找回指定 NPC 的旧对话；
- Keeper Planner 能检索同房间不同玩家和 NPC 的已提交私密 Event/Memory；
- Keeper Planner 仍保留 `asserted/heard/presentation` 等认知等级，不把所有记忆升级为事实；
- `ChatMessage` 和尚未执行的队列原话不会进入 Keeper 全局上下文；
- 玩家询问自己去过哪里、做过什么时，Narrator 能从玩家安全历史返回可审计结果；
- 玩家询问其他玩家的私密经历时，Narrator 不会因 Keeper Planner 全知而泄露内容。

### 13.4 Engine 边界

- NPC 的主张不能直接修改 GameState；
- NPC 说门后有石阶不等于 Engine 确认石阶存在；
- 玩家对 NPC 说“我要去地下室并使用侦查”不会移动、检定或创建 ActionPlan；
- 玩家另行向守秘人提交推门等行动时才进行 Engine 裁决；
- 当前 PlayerView 与旧 NPC 记忆冲突时以当前 PlayerView 为准；
- Keeper 全局 Memory 不能直接修改 GameState，状态变化仍必须来自 Engine 提交。
- Engine 不读取 `read_keeper_context`、Memory 或 Summary，Fake store 可断言没有新增调用。

### 13.5 多人和回放

- 历史 `player_scoped` NPC Memory 不会因为 npc_id 相关性泄露给其他玩家；
- 同一 NPC 可以记住多个玩家的公开对话；
- 场景对话只向冻结 event audience 广播和回放；
- 玩家明确要求同场景 NPC 私聊时返回“不支持私聊”的澄清，不落库、不调用 NPC
  Narrator，也不能静默改成场景公开；
- 旧 `narration.push` 回放不受新事件类型影响；
- 其他玩家的私密 Event 可以进入 Keeper Planner，但绝不进入当前玩家的 Narrator payload；
- Planner 与 Narrator 不复用跨权限模型会话，玩家回复不能泄露 Planner 看到的隐藏原文；
- 隐藏世界变化可以通过当前 PlayerView 中已经可观察的结果呈现，但不能披露隐藏原因。

### 13.6 头像与声线扩展边界

- dialogue Event 不含头像 URL、图片二进制、Provider task ID 或 voice_type；
- 前端只按稳定 speaker_id 查询头像，缺少头像时使用默认样式；
- canonical NPC 优先复用 ModuleAsset 静态立绘，runtime NPC 第一版使用默认头像；
- 未启用任何 NPC 媒体 Provider 时，所有文本对话、Memory、回放和 ActionPlan 测试仍通过。

---

## 14. 开发难度评估

| 子系统 | 难度 | 主要原因 |
|---|---:|---|
| `interlocutor_id` 和可见性验证 | 中 | 需要贯通前端、WebSocket、主持队列和 PlayerView |
| ChatMessage 双频道 | 中 | 需要迁移 channel/actor_id 并改掉 action.broadcast 写入路径 |
| 结构化 dialogue 事件 | 中高 | 需要场景受众、回放、权限和幂等兼容 |
| NPC 多消息回复 | 中高 | 需要限制 speaker、顺序、数量和参与者 |
| 纯对话任务恢复 | 中高 | 需要队列 lease、Event 幂等和批量事务提交 |
| NPC Memory 投影 | 中 | 复用已有 MemoryEntry 和增量投影基础 |
| NPC Summary | 中高 | 需要解决共享认知和 viewer 隔离 |
| Keeper 全局检索隔离 | 中高 | Planner 全知但 Narrator 必须保持玩家安全，需独立 DTO 和模型请求 |
| 历史按需查询 | 中 | 第一版 SQL 关键词检索即可，不需要向量系统 |
| 前端消息展示 | 中 | 新事件类型、旧回放兼容和顺序显示 |
| 头像/声线预留 | 低 | 第一版只保证稳定 speaker_id，不接媒体 Provider |
| 端到端长团测试 | 高 | 需要多场景、多人、重连和真实 Host 试玩 |

总体评估：中高难度，预计明显大于 PR #393，但不需要重写 Engine，也不需要引入独立 Agent 框架。

---

## 15. 风险与缓解

### 风险一：模型把 NPC 说错

缓解：结构化输出、speaker 白名单、Memory 作用域校验、非法输出不猜测修复。

### 风险二：NPC 把秘密泄露给其他玩家

缓解：NPC 认知主体与玩家受众分字段；场景受众在提交时冻结；canonical memory 和
viewer-scoped summary 分离；所有查询先做服务端权限过滤。

### 风险三：NPC 对话被误当成实际行动

缓解：按结构化 recipient 在应用层分流；NPC 路径根本不调用 Keeper Planner、ActionPlan
或 Engine。行动式文字只进入 `experienced conversation`，内容明确保留为未确认声称/计划，
且不投影 `action/visit` Memory。

### 风险四：新增事件导致旧客户端无法显示

缓解：服务端保留旧事件兼容；前端增加未知事件降级展示；回放测试覆盖旧数据。

### 风险五：模型调用增加导致延迟上升

缓解：纯对话只调用一次；摘要异步；不创建常驻 NPC Agent。玩家另行提交守秘人行动时才
产生该行动原本需要的模型调用。

### 风险六：自由文本摘要泄露私密信息

缓解：只从 viewer 有权读取的 Event/Memory 生成 `(npc_id, viewer_player_id)` 独立摘要；
禁止生成全知共享自由文本后再做字符串裁剪。

### 风险七：语音 Provider 配置污染模组或泄露私密对白

缓解：Provider 音色使用独立 `npc_voice_bindings`，不写入 ModuleContent；语音接口只读取
已授权的 `dialogue.npc` 权威事件，TTS 失败只降级为文本。

### 风险八：场景受众在回放时漂移

缓解：事件提交时写入 `event_audiences`，广播、重连和回放都读取冻结受众，不按玩家当前
位置重算。

### 风险九：复用房间行动队列增加纯对话等待

缓解：第一版优先保证顺序、权限和恢复正确，并记录排队等待时间；只有监控证明纯对话
等待影响体验时，再增加 NPC 专用队列，避免提前维护第二套持久化并发状态机。

### 风险十：守秘人全局认知泄露到玩家回复

缓解：Keeper Planner 和 Narrator 使用独立上下文 DTO 与独立模型请求；禁止复用跨权限会话
标识或 transcript。只有玩家可见的 PlayerView、committed evidence 和公开执行结果可以传给
Narrator，并用 Fake provider 直接断言 payload 中不存在其他玩家私密 Event 和隐藏模组原文。

---

## 16. 推荐交付拆分

不扩大已合并的 PR #393，也不要求先合并文档 PR #407 或新建总 Issue。直接从包含 PR #404
的最新 `main` 创建实现分支，各实现 PR 引用 #407。推荐三个可独立验收、可回滚的垂直阶段：

### 阶段 A：NPC 对话契约与事件链路

- 单人/多人房间的接收者路由契约和稳定 `recipient.kind`；
- `interlocutor_id` 及稳定 NPC ID；
- `discussion/roleplay` ChatMessage 路由，彻底停止无 `@` action.broadcast；
- `dialogue.player` / `dialogue.npc` 契约，守秘人继续使用 `narration.push`；
- 当前 `PlayerView` 的可见性与可交互校验；
- `speaker_id`、`listener_ids`、`allowed_responder_ids`、冻结 event audience；
- 固定 correlation、source_action_id、ordinal、source_revision 幂等关系；
- WebSocket、SDK、回放和基础权限测试。

验收：单人无 `@` 能进入 Keeper Host，多人无 `@` 按频道生成角色扮演或玩家讨论消息；
合法场景对话可以落库并只向冻结受众广播和回放；场景外、隐藏或无权 NPC 不能回复；
旧客户端遇到未知事件仍能安全降级。

### 阶段 B：Host 纯对话执行与队列恢复

- Host 的结构化 NPC 输出和 speaker 白名单校验；listener/audience 由服务端生成；
- 一次对话中多个 NPC 的有序回复和消息预算；
- `recipient.kind=npc` 直接进入 NpcDialogueService，禁止调用 ActionPlan 或 Engine；
- “玩家发言幂等落库 → NPC 回复批量落库 → 队列完成”，不执行后续行动；
- 队列 lease、result_event_ids、断线、取消、Provider 失败和重复恢复；
- 目标失效直接澄清；非法模型输出反馈重试一次，仍失败进入 retryable_failure。

验收：`@NPC` 中即使包含旅行、技能或物品动作，也只产生玩家和 NPC 对话，不创建检定或
修改 Engine；回复不乱序、不重复，玩家另行提交 `@守秘人` 后才执行实际行动。

### 阶段 C：NPC 记忆、摘要、历史召回与展示

- NPC canonical `MemoryEntry.audience_player_ids`、近期对话和专用 viewer-scoped Summary；
- 严格 `read_npc_context` 和基于当前原话的受限历史预取；
- 只从 viewer 有权限的 canonical entries 重建摘要；
- 原始 `dialogue.player` Event 的按需精确查询；
- Keeper Planner 使用内部 `read_keeper_context` 有界检索全房间已提交历史，Narrator 继续
  使用当前玩家安全上下文；
- `location.entered → visit.location_id` 投影；
- 前端区分玩家、NPC、守秘人消息，兼容回放和重连；
- 使用稳定 `speaker_id` 查询静态立绘或默认头像，只预留未来声线/生图扩展；
- 长团、多玩家隐私、记忆污染和真实 Host 测试。

验收：NPC 能回忆自己听到的旧对话，但不能读取其他 NPC 或玩家的私密记忆；Keeper Planner
可以使用全房间已提交历史维持连续性，但 Narrator payload 不包含当前玩家无权读取的内容；
`chat.send` / `action.chat.send` 不进入 Host、Event、Memory 或 Summary；300～500 回合后
仍可从原始 Event 召回目标 NPC 的旧对话和玩家地点历史。

每个阶段可以包含多个提交，但不再为每个 DTO、查询或 UI 细节单独开 Issue。只有当某个
阶段实际规模过大、需要独立发布或存在不同负责人时，才再拆出子 Issue。

---

## 17. 最终决策清单

以下方案已经对齐：

- [x] 不创建独立 NPC Agent；
- [x] NPC 仍由同一个 AI Host/Narrator 扮演；
- [x] `@NPC` 转换为结构化 `interlocutor_id`；
- [x] recipient 同时写入提交契约和持久化主持行动队列；
- [x] 服务端在入队和出队时都验证 NPC 当前存在、可见且可交互；
- [x] 目标不存在时触发澄清，不传送玩家或让 NPC 隔空回复；
- [x] 玩家对话和 NPC 回复结构化落库；
- [x] 主要 NPC 必须先回复，同场景 allowed responders 最多产生 3 条有序回复；
- [x] `@NPC` 整条原文只进入纯对话服务，不调用 Keeper Planner、ActionPlan 或 Engine；
- [x] `@NPC` 中的行动式措辞只进入 experienced conversation，并标记为未确认计划；不生成
  action/visit Memory，也不触发地点、技能、物品或状态变化；
- [x] 玩家必须另行提交守秘人输入，才会执行实际行动和技能检定；
- [x] NPC 仍然不能直接改变世界事实；
- [x] 单人未 `@` 默认与守秘人交互；
- [x] 多人行动区未 `@` 是玩家角色间 roleplay，讨论区未 `@` 是玩家本人 discussion；
- [x] 两种无 `@` 消息都使用 ChatMessage，不进入 Host、Event、Memory 或 Summary；
- [x] roleplay 第一版沿用房间 ChatMessage 受众和游戏结束清理，不产生 Engine 行动或 NPC
  听闻；分场景私聊与永久归档后续另做；
- [x] `@守秘人` / `@主持人` 和 `@NPC` 才能在多人游戏中触发 Host；
- [x] 每条行动区输入只有一个结构化 recipient，多 NPC 插话不依赖多个 `@`；
- [x] 第一版 NPC 对话向当时同场景的全部冻结玩家受众广播，不实现同场景私聊；
- [x] allowed responder NPC 会彼此听见公开对白，并分别形成 experienced 记忆；
- [x] `ChatMessage` 不进入 NPC 记忆；
- [x] NPC canonical MemoryEntry 按房间和 NPC 共享，同时保留 audience_player_ids；
- [x] NPC Summary 使用独立表并按 npc_id + viewer_player_id 隔离；
- [x] 原始 Event 保留，用于精确回忆原话；
- [x] 当前 Host 不依赖工具循环，由 NpcDialogueService 使用玩家原话安全预取历史；
- [x] 守秘人系统逻辑上全知，Keeper Planner 可有界检索同房间全部已提交权威历史；
- [x] 全知不等于每轮注入全部历史，也不改变 Memory 的认知等级或 Engine 事实边界；
- [x] Keeper Planner 与玩家可见 Narrator 使用独立上下文 DTO 和独立模型请求；
- [x] Engine 不读取 Keeper Memory 或 Summary，继续以 GameState 和已校验命令为唯一输入；
- [x] Narrator 只读取当前玩家可见的 PlayerView、Event、Memory 和 Summary，不泄露其他
  玩家私密经历或隐藏 ModuleContent；
- [x] 第一版不新增 Keeper 全局摘要表，先复用现有 Event/Memory 的有界检索；
- [x] 守秘人继续使用 `narration.push`，不新增同义 narration.keeper；
- [x] `dialogue.npc` 保留稳定 `event_id` 和 `speaker_id`，支持未来按 NPC 选择声线；
- [x] 第一版不实现 NPC 生图、音色匹配或 TTS，只保留稳定 speaker_id；
- [x] 未来头像/声线绑定独立保存，不写入 dialogue Event 或 Engine 状态；
- [x] 第一版使用结构化 SQL/关键词查询，不引入向量数据库；
- [x] 不实现 NPC 自主行动；
- [x] 不增加 encounter 计数；
- [x] PR #393 不再扩大范围；PR #407 不必先合并，也不再新建总实现 Issue。

---

## 18. 结论

这套方案的本质是：

```text
一个 AI 主持
+ 结构化 NPC 对话
+ 结构化守秘人叙事
+ NPC 独立认知记忆
+ viewer 级别隐私过滤
+ 守秘人全局裁决认知与玩家安全叙事隔离
+ NPC 纯对话与守秘人 ActionPlan 分流
```

它不会把项目变成多个 NPC Agent，也不会让 NPC 脱离 AI 主持自行行动。它解决的是当前 Narrator 把 NPC 对白、守秘人描述和行动结果混在一起的问题，同时为 NPC 长期记忆、多人权限和长团历史召回提供可靠的数据基础。

最终用户体验应当是：

```text
你：@托马斯，门后有什么？

托马斯：门后有一条向下的石阶。

你：@守秘人，我推开木门。

守秘人：你推开木门，看到石阶通向黑暗。
```

玩家不需要从一大段主持人文本中寻找 NPC 的话，而系统也能准确记录谁说了什么、谁听到了什么，以及这些内容是否可以在几十回合后被 NPC 回忆。

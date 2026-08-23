# NPC 结构化对话与长期记忆升级方案

## 1. 文档定位

本文档沉淀当前项目关于 NPC 对话、AI 主持人扮演方式和长期记忆升级的最终方案，作为后续 Issue #402 及其 PR 的实现参考。

当前结论是：不为每个 NPC 创建独立 Agent，而是在现有 AI Host/Narrator 基础上，增加结构化 NPC 对话消息、NPC 独立认知记忆和按需历史召回。

相关基础工作：

- Issue #363：跨回合上下文压缩与持久化总体设计，已关闭；
- PR #393：长期记忆增量投影、游标、并发安全、来源时间和房间级重建，已合并；
- Issue #402：NPC 共享长期记忆与按需历史召回，作为本方案的开发 Issue。

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
6. 玩家说完话后，NPC 回复先落库，再执行玩家后续行动；
7. 一个对话步骤允许多个当前可见 NPC 按顺序回复；
8. NPC 的主张不能绕过 Engine 变成世界事实；
9. 长团中可以回忆几十甚至几百回合前的具体对话、地点、行动和线索；
10. 多人房间中不能通过 NPC 绕过玩家权限泄露私密内容。

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

内部可以把 `step.kind=dialogue` 作为提示字段，但不建立独立的 NPC Agent 或复杂会话状态机。

### 4.3 Engine 仍然是唯一事实源

以下内容不能仅因为 NPC 或 Narrator 说过就成为事实：

- 门后有什么；
- 玩家是否拿到物品；
- NPC 是否死亡、受伤或移动；
- 某条线索是否已经发现；
- 某个地点是否存在；
- 某个玩家是否完成行动。

NPC 的对白只表示 NPC 的认知、猜测、主张或记忆。需要改变世界状态时，必须重新提交玩家行动并由 Engine 裁决。

---

## 5. 结构化消息设计

### 5.1 事件类型

新增或扩展以下游戏内事件类型：

```text
dialogue.player   玩家对 NPC 的发言
dialogue.npc      NPC 对玩家或其他参与者的发言
narration.keeper  守秘人对玩家的环境、结果和过程描述
```

现有玩家讨论区 `ChatMessage` 继续保持独立：

```text
ChatMessage = 玩家之间的讨论区消息
不进入 MemoryEntry
不进入 ConversationSummary
不作为 NPC 知识来源
```

PR #404 中的两个自由交流入口也必须遵守同一边界。输入是否默认交给 Host，取决于
房间的稳定游戏模式，而不是当前在线人数：

```text
单人游戏
    未 @ 任何对象 → 默认提交给守秘人，调用 Host
    @守秘人       → 提交给守秘人，调用 Host
    @NPC           → 提交结构化 NPC 对话，调用 Host

多人游戏
    未 @ 任何对象 → 玩家自由交流，不调用 Host
    @守秘人       → 提交给守秘人，进入主持行动队列
    @NPC           → 提交结构化 NPC 对话，进入主持行动队列
```

多人游戏中未指定对象的消息，无论前端显示在讨论区还是行动区，语义都是玩家自由交流：
不占主持行动槽，不进入 `MemoryEntry`、`ConversationSummary` 或 NPC 知识来源。
`action.chat.send` 不能因为显示在行动频道就复用会被记忆投影读取的
`action.broadcast` 事件类型；如果保留行动频道广播，必须使用独立事件类型，或在
Memory/ConversationSummary 查询中明确排除它。否则玩家的闲聊、猜测和临时计划会在
长团中被误当成剧情记忆。

房间模式必须来自创建房间时不会随连接变化的配置。第一版如果尚无独立 `play_mode`，
可以使用 `max_players == 1` 判定单人游戏；不能根据当前在线人数或当前在局人数判断，
避免队友断线后同一句无 `@` 输入突然从玩家聊天变成 Host 行动。

### 5.2 玩家对话事件

推荐结构：

```json
{
  "type": "dialogue.player",
  "room_id": "room-1",
  "player_id": "player-1",
  "speaker_id": "actor-1",
  "interlocutor_id": "thomas",
  "listener_ids": ["thomas"],
  "participant_ids": ["actor-1", "thomas"],
  "utterance": "月影钟响三次，记住这句话。",
  "visibility": "public",
  "scene_id": "thomas_office",
  "source_action_id": "action-1",
  "source_revision": "42"
}
```

### 5.3 NPC 回复事件

推荐结构：

```json
{
  "type": "dialogue.npc",
  "room_id": "room-1",
  "speaker_id": "thomas",
  "listener_ids": ["actor-1"],
  "participant_ids": ["thomas", "actor-1"],
  "text": "我会记住的。",
  "visibility": "public",
  "scene_id": "thomas_office",
  "source_dialogue_id": "dialogue-player-1",
  "source_revision": "42"
}
```

NPC 回复由 Host 生成，但服务端必须验证：

- `speaker_id` 是当前场景可见 NPC；
- `listener_ids` 属于当前对话参与者；
- NPC 没有读取无权限的记忆；
- 回复没有直接写入 Engine 状态；
- 回复长度和消息数量受预算限制。

### 5.4 守秘人叙事事件

需要保留环境描述、行动结果和规则后果的独立叙事：

```json
{
  "type": "narration.keeper",
  "speaker_type": "keeper",
  "text": "托马斯说完后，你推开了沉重的木门。",
  "claimed_evidence_refs": ["event-42"],
  "visibility": "public"
}
```

前端可以把这些消息合并为一个连续回合，但后端必须分开保存。

### 5.5 NPC 独立声线与语音播报预留

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

当前阶段不为 `EntitySpecV3` 增加 Provider 专属 `voice_type`。只有实际匹配质量证明
名称、描述和模组背景不足时，再增加与供应商无关的 `voice_profile`（例如年龄感、音高、
语速和口音倾向）。缺少绑定、音色下架或 TTS 失败时回退到通用 NPC/主持人音色；文本
对话、Memory 投影和后续 ActionPlan 必须继续正常完成。

---

## 6. `@NPC` 和目标验证

### 6.1 `@` 的真实含义

`@守秘人`、`@主持人` 和 `@NPC` 都只是 UI 语法，进入后端时必须转换成结构化接收者，
不能由 WebSocket 层重新解析自然语言：

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

服务端根据房间模式验证该组合，多人游戏不能接受隐式 Keeper 请求。NPC 的
`entity_id` 随后映射为本方案其他部分使用的 `interlocutor_id`。不允许后端从“你”、
“记住”“跟你说”等自然语言关键词猜测听众。

### 6.2 服务端验证

服务器收到 `interlocutor_id` 后必须检查：

1. NPC ID 存在；
2. NPC 属于当前房间的 Engine/ModuleContent；
3. NPC 当前存在于 `PlayerView.scene.visible_entities`；
4. NPC 的 `kind` 是 `npc`；
5. NPC 当前没有被隐藏、死亡、离场或禁止交互；
6. 玩家和 NPC 处于允许互动的场景和权限范围。

如果玩家在托马斯家里发送“我和守墓人交流”，但守墓人不在场，系统不能把玩家传送到墓地，也不能让守墓人隔空回答，应返回澄清：

```text
这里没有看到守墓人。你是要和托马斯交谈，还是先前往墓地？
```

NPC 身份必须来自 ModuleContent/Engine 的稳定实体 ID。名称、别名和自然语言只用于
界面展示或辅助搜索，不能作为权限判断或事件主体。服务端还要明确 NPC 在死亡、隐藏、
离场和不可交互状态下的判定结果；这些状态都必须以当前 `PlayerView` 为准。

### 6.3 多 NPC 回复

一个对话步骤可以允许多个 NPC 按顺序回复，但每个说话者都必须满足：

- 当前可见；
- 属于本次对话参与者；
- 由结构化上下文允许；
- 不能由模型凭空添加场景外 NPC。

建议第一版限制为每个对话步骤最多 3 条 NPC 消息，避免模型自行展开无限多人对话。

示例：

```text
玩家：你们怎么看这件事？

托马斯：我认为应该离开这里。
守墓人：不，留下才是安全的。
```

这是一次 Host 调用中生成多个结构化 NPC 消息，不是启动多个 NPC Agent。

### 6.4 实现前必须固定的六项契约

以下约束属于跨模块契约，不能留给某个具体 PR 临时决定：

1. **NPC 身份来源**：`interlocutor_id` 使用稳定实体 ID；服务端以当前
   `PlayerView` 验证存在、可见、可交互和状态有效。
2. **事件权限**：事件保留服务端确认的 `speaker_id`、`listener_ids` 和
   `participant_ids`。广播、回放和记忆投影都按这些字段与 `visibility` 过滤，不能只靠
   一段自由文本推断谁听到了。
3. **幂等与顺序**：固定 `dialogue_id`、`source_action_id`、`step_id` 和
   `source_revision` 的关系；重试不得重复广播、写 Memory 或推进 ActionPlan。
4. **Host 输出失败**：场景外 speaker、无效 listener、越权记忆、超出消息预算或非法
   引用必须进入拒绝、澄清或重试路径之一，服务端不能猜测修正后继续。
5. **摘要信任边界**：`viewer-scoped Summary` 只能由该 viewer 有权读取的
   canonical `MemoryEntry` 重建，不能先生成全知共享自由文本再做字符串裁剪。
6. **ActionPlan 恢复**：明确 dialogue step 或等价中间阶段的持久化状态，并覆盖断线、
   lease 过期、取消、部分完成和重复恢复。NPC 回复落库前不得执行依赖它的后续行动。

这些约束应在契约测试和恢复测试中先固定，再接入真实 Host；它们不是模型提示词可以
替代的规则。

---

## 7. ActionPlan 分步执行方案

### 7.1 现状问题

当前 ActionPlan 可以在语义上拆成多个步骤，但通常是所有 Engine 步骤完成后才统一调用 Narrator。

例如：

```text
我问托马斯门后有什么，然后推门。
```

当前容易变成：

```text
执行对话步骤
执行推门步骤
最后一次性生成 Narrator 文本
```

这会让 NPC 回复变成事后旁白，无法真正影响玩家对后续行动的理解。

### 7.2 升级后的时序

采用中间对话结果：

```text
玩家输入
  ↓
Planner 拆出 dialogue step + action step
  ↓
验证 interlocutor_id
  ↓
生成 dialogue.player
  ↓
Host 生成一条或多条 dialogue.npc
  ↓
dialogue.npc 落库并投影 NPC 记忆
  ↓
向前端发送 NPC 消息
  ↓
重新读取最新 PlayerView
  ↓
Engine 裁决后续 action step
  ↓
提交 Engine 结果
  ↓
Host 生成 narration.keeper
  ↓
向前端发送守秘人描述
```

### 7.3 重要边界

NPC 说完后，后续玩家行动必须重新经过 Engine。NPC 说“门后有石阶”不等于门后一定有石阶；玩家推门时仍以当前 Engine 状态为准。

如果只是纯对话，没有后续状态变化，可以只生成 NPC 回复，不再额外生成守秘人叙事。

---

## 8. NPC 独立长期记忆

### 8.1 记忆主体

NPC 使用现有 `MemoryEntry`，但查询主体从玩家扩展为 NPC：

```text
玩家记忆：room_id + player_id
NPC 记忆：room_id + npc_id
```

同一房间中的同一个 NPC 只有一份 canonical 认知记忆。

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

没有在场、没有明确听众或没有告知证据时，不生成 NPC `experienced` 记忆。

Narrator 写出“NPC 点头”“NPC 似乎记住了”不能单独生成记忆。

### 8.3 NPC 回复也写入记忆

NPC 对玩家说出的结构化回复可以投影为：

```text
subject_id = npc_id
kind = conversation
epistemic_status = experienced
content = NPC 曾经向玩家说过的原话
```

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

---

## 9. 多人隐私设计

### 9.1 canonical 记忆和可见摘要分离

同一 NPC 的 canonical MemoryEntry 可以在房间级共享，但不能把包含私密内容的自由文本摘要直接共享给所有玩家。

推荐存储：

```text
MemoryEntry：room_id + npc_id，共享 canonical 记忆
ConversationSummary：room_id + npc_id + viewer_player_id，按玩家生成
```

### 9.2 私密对话示例

```text
玩家 A 私下告诉托马斯一个秘密
    ↓
托马斯的 canonical memory 记录这件事
    ↓
玩家 A 再次询问托马斯：可以使用这条记忆
玩家 B 询问托马斯：不能自动看到这条记忆
```

如果 NPC 后来向玩家 B 明确说出秘密，必须由 Engine/事件链生成“NPC 已向 B 告知”的事件，不能因为 NPC 自己知道就直接泄露给 B。

### 9.3 对话可见性

- 普通场景公开对话：`public`，按房间广播；
- 私聊或玩家私有场景：`player_scoped`，只发送给授权玩家；
- `ChatMessage` 讨论区消息：永远不进入 NPC 记忆和摘要；
- 守秘人回复玩家时，仍按当前玩家的 PlayerView 和可见事件过滤。

---

## 10. Narrator 输入和输出

### 10.1 NPC 对话输入

当当前步骤是 NPC 对话时，Host 应获得：

```text
当前 PlayerView
当前 ActionPlan step
当前 interlocutor_id
NPC 可见描述和状态
NPC 近期对话
NPC 相关 MemoryEntry
NPC viewer-scoped ConversationSummary
当前玩家原话
已提交 evidence
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

推荐输出：

```json
{
  "npc_messages": [
    {
      "speaker_id": "thomas",
      "listener_ids": ["actor-1"],
      "text": "我会记住的。"
    }
  ],
  "keeper_narration": null
}
```

需要执行后续行动时，先只返回 NPC 消息；Engine 行动完成后，再单独生成：

```json
{
  "npc_messages": [],
  "keeper_narration": "你推开了沉重的木门。"
}
```

服务端需要校验：

- `speaker_id` 在允许参与者中；
- `listener_ids` 在当前参与者中；
- 消息引用的 NPC 当前可见；
- 输出没有隐藏协议字段；
- 输出没有未经证据支持的持久化事实；
- 返回数量、字符和建议动作不超过预算。

模型输出非法时不猜测修复，不生成 NPC 记忆；保留已提交的玩家输入和 Engine 结果，并走可见的澄清/降级路径。

---

## 11. 历史按需召回

长团支持的关键不是无限增加 Prompt，而是固定预算下的按需查询。

建议新增服务端只读查询，至少支持：

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

---

## 12. 实现步骤

### 阶段 0：契约和现状梳理

工作内容：

- 确认当前 ActionPlan dialogue step 的输入输出；
- 确认 `PlayerView.visible_entities` 的 NPC 可见性；
- 确认现有 `action.broadcast`、`narration.push` 和 MemoryEntry 投影；
- 确认旧回放和重连协议兼容策略。

难度：低。

风险：如果直接在 WebSocket 层猜 NPC，容易重新引入之前的监听人误判问题。

### 阶段 1：结构化对话契约

工作内容：

- 增加 `interlocutor_id`；
- 增加 `dialogue.player` 和 `dialogue.npc` 事件契约；
- 服务端验证 NPC 当前可见且可交互；
- 增加多 NPC 消息的参与者约束；
- 保留 `ChatMessage` 的讨论区边界。

难度：中等。

主要风险：前端、WebSocket、Event replay 和 Host schema 需要保持兼容。

### 阶段 2：对话中间结果和分步执行

工作内容：

- dialogue step 完成后先生成 NPC 回复；
- NPC 回复落库后再继续后续 ActionPlan step；
- 后续 Engine 行动重新读取 PlayerView；
- Engine 结果完成后再生成守秘人叙事；
- 对原有单步骤行动保持兼容。

难度：高。

这是整个方案最复杂的部分，因为它改变了当前“Plan 完成后统一 Narrator”的时序，需要处理：

- ActionPlan 持久化游标；
- 重连和恢复；
- NPC 回复生成失败；
- 中间事件重复提交；
- 后续步骤等待玩家检定；
- 旧客户端只识别 `narration.push` 的兼容。

### 阶段 3：NPC Memory 和 Summary

工作内容：

- 复用 MemoryEntry 增加 NPC 主体查询；
- 将结构化 dialogue 事件投影为 `experienced/heard`；
- 增加 NPC 近期对话窗口；
- 扩展 ConversationSummary owner；
- 按 viewer_player_id 生成 NPC 摘要；
- 保留原始 Event 作为精确回忆来源。

难度：中高。

主要风险：NPC 共享认知和玩家隐私之间需要严格的查询过滤，不能把一份未经裁剪的自由文本摘要发给所有玩家。

### 阶段 4：历史按需召回

工作内容：

- 增加服务端只读查询服务；
- 支持 NPC、地点、实体、记忆类型和关键词过滤；
- 固定条数和字符预算；
- 玩家明确追问原话时查询原始 Event；
- 禁止模型扩大查询范围。

难度：中等。

第一版不做向量搜索，先使用结构化 SQL 和关键词查询，降低维护成本。

### 阶段 5：前端展示和回放

工作内容：

- NPC 消息显示明确说话者名称或头像；
- 守秘人叙事使用独立样式；
- 玩家消息、NPC 消息和守秘人描述按事件顺序混合显示；
- 兼容旧 `narration.push`；
- 刷新、重连、历史回放保持同样顺序。
- 语音播放入口按 `dialogue.npc.event_id` 请求，不从展示文本猜测 NPC；
- 第一版允许 NPC 语音不可用，不阻塞文本消息和回合执行。

难度：中等。

注意：后端必须结构化保存，但前端不必变成传统多人聊天软件。视觉上仍然可以保持跑团叙事风格。

---

## 13. 测试计划

### 13.1 契约和权限

- 单人房间未 `@` 的输入默认生成 Keeper Host 请求；
- 多人房间未 `@` 的输入只生成玩家聊天，不调用 Host、不占行动槽、不进入 Memory/Summary；
- 多人房间断线或重连不会改变上述路由；
- `@守秘人` / `@主持人` 生成 Keeper Host 请求，`@NPC` 生成带稳定
  `interlocutor_id` 的 NPC Host 请求；
- `interlocutor_id` 不在当前场景时被拒绝；
- 当前场景没有目标 NPC 时触发澄清；
- 隐藏 NPC 不能生成回复；
- NPC 回复 speaker 必须属于允许参与者；
- `ChatMessage` 不生成 NPC 记忆；
- 跨房间、跨玩家、跨 NPC 记忆被拒绝；
- 私密 NPC 记忆不会出现在其他玩家上下文。

### 13.2 多消息和时序

- 一个 dialogue step 可以返回两个或三个可见 NPC 的有序回复；
- 不允许场景外 NPC 插入消息；
- NPC 回复落库后才执行后续 Engine action；
- NPC 回复失败时不执行后续依赖该回复的行动；
- 重连后不会重复生成 NPC 回复；
- 后续行动使用 NPC 回复完成后的最新 PlayerView。

### 13.3 记忆和摘要

- NPC 亲自听到的话生成 `experienced`；
- 没有听众证据时保持 `asserted`；
- Narrator 的“点头”“记住了”不会自动升级事实；
- NPC 摘要按 viewer 玩家隔离；
- 摘要失败不阻塞当前回合；
- 原始 Event 可以返回精确对话；
- 连续 50 个以上回合后仍能找回指定 NPC 的旧对话。

### 13.4 Engine 边界

- NPC 的主张不能直接修改 GameState；
- NPC 说门后有石阶不等于 Engine 确认石阶存在；
- 玩家推门时重新进行 Engine 裁决；
- 当前 PlayerView 与旧 NPC 记忆冲突时以当前 PlayerView 为准。

### 13.5 多人和回放

- 玩家 A 私下告诉 NPC 的内容不会泄露给玩家 B；
- NPC 向 B 明确告知后，B 才能看到对应事件；
- 同一 NPC 可以记住多个玩家的公开对话；
- 公开对话按房间广播；
- 私密对话只发给授权玩家；
- 旧 `narration.push` 回放不受新事件类型影响。

### 13.6 NPC 声线扩展

- 两个 NPC 在同一回合分别回复时，语音服务根据各自 `speaker_id` 使用不同绑定；
- 守秘人叙事继续使用房间主持人音色，不与 NPC 声线混用；
- 私密 `dialogue.npc` 的语音接口拒绝未授权玩家；
- 前端不能提交任意 `text + speaker_id` 绕过权威事件进行合成；
- NPC 没有绑定、绑定音色下架或 Provider 失败时回退且文本回合仍成功；
- 相同 Provider、音色和文本复用现有语音缓存，不重复产生供应商费用。

---

## 14. 开发难度评估

| 子系统 | 难度 | 主要原因 |
|---|---:|---|
| `interlocutor_id` 和可见性验证 | 中 | 需要贯通前端、WebSocket、ActionPlan 和 PlayerView |
| 结构化 dialogue 事件 | 中 | 需要事件、回放、权限和幂等兼容 |
| NPC 多消息回复 | 中高 | 需要限制 speaker、顺序、数量和参与者 |
| 对话后再执行后续行动 | 高 | 改变 ActionPlan/Narrator 时序，涉及恢复和失败处理 |
| NPC Memory 投影 | 中 | 复用已有 MemoryEntry 和增量投影基础 |
| NPC Summary | 中高 | 需要解决共享认知和 viewer 隔离 |
| 历史按需查询 | 中 | 第一版 SQL 关键词检索即可，不需要向量系统 |
| 前端消息展示 | 中 | 新事件类型、旧回放兼容和顺序显示 |
| NPC 独立声线 | 中 | 可复用现有 Host Speech，新增实体绑定和事件级鉴权 |
| 端到端长团测试 | 高 | 需要多场景、多人、重连和真实 Host 试玩 |

总体评估：中高难度，预计明显大于 PR #393，但不需要重写 Engine，也不需要引入独立 Agent 框架。

---

## 15. 风险与缓解

### 风险一：模型把 NPC 说错

缓解：结构化输出、speaker 白名单、Memory 作用域校验、非法输出不猜测修复。

### 风险二：NPC 把秘密泄露给其他玩家

缓解：canonical memory 和 viewer-scoped summary 分离；所有查询先做服务端权限过滤。

### 风险三：对话回复和行动顺序错乱

缓解：NPC 回复落库后才推进后续 ActionPlan；每个后续行动重新投影 PlayerView。

### 风险四：新增事件导致旧客户端无法显示

缓解：服务端保留旧事件兼容；前端增加未知事件降级展示；回放测试覆盖旧数据。

### 风险五：模型调用增加导致延迟上升

缓解：纯对话只调用一次；后续行动完成后才按需调用守秘人叙事；摘要异步；不创建常驻 NPC Agent。

### 风险六：自由文本摘要泄露私密信息

缓解：按 viewer_player_id 生成摘要，或者只对公开记忆生成共享摘要；禁止直接共享未经裁剪的 NPC 摘要。

### 风险七：语音 Provider 配置污染模组或泄露私密对白

缓解：Provider 音色使用独立 `npc_voice_bindings`，不写入 ModuleContent；语音接口只读取
已授权的 `dialogue.npc` 权威事件，TTS 失败只降级为文本。

---

## 16. 推荐交付拆分

不扩大已合并的 PR #393。基于最新 `main` 从 Issue #402 开发，但不把契约、运行时、
记忆和 UI 拆成七个互相等待的 Issue。推荐三个可独立验收、可回滚的垂直阶段：

### 阶段 A：NPC 对话契约与事件链路

- 单人/多人房间的接收者路由契约和稳定 `recipient.kind`；
- `interlocutor_id` 及稳定 NPC ID；
- `dialogue.player` / `dialogue.npc` / `narration.keeper` 契约；
- 当前 `PlayerView` 的可见性与可交互校验；
- `speaker_id`、`listener_ids`、`participant_ids`、`visibility`；
- `dialogue_id`、`source_action_id`、`step_id`、`source_revision` 幂等关系；
- WebSocket、SDK、回放和基础权限测试。

验收：单人无 `@` 能进入 Keeper Host，多人无 `@` 只能玩家聊天；合法公开/私密对话可以
落库、广播和回放；场景外、隐藏或无权 NPC 不能回复；
旧客户端遇到未知事件仍能安全降级。

### 阶段 B：Host 对话执行与 ActionPlan 恢复

- Host 的结构化 NPC 输出和 speaker/listener 白名单校验；
- 一个对话步骤中多个 NPC 的有序回复和消息预算；
- “玩家发言落库 → NPC 回复落库 → 再执行后续 ActionPlan → Engine 裁决 → 守秘人叙事”；
- 对话中间态、断线、取消、lease 过期、模型失败和重复恢复；
- 非法模型输出进入拒绝、澄清或重试，不猜测修复。

验收：`@NPC 提问 → NPC 回复 → 后续行动 → 守秘人叙事` 不乱序、不重复，NPC 文本不
直接修改 Engine 状态。

### 阶段 C：NPC 记忆、摘要、历史召回与展示

- NPC canonical `MemoryEntry`、近期对话和 viewer-scoped Summary；
- 只从 viewer 有权限的 canonical entries 重建摘要；
- 原始 `dialogue.player` Event 的按需精确查询；
- 前端区分玩家、NPC、守秘人消息，兼容回放和重连；
- 基于稳定 `speaker_id` 接入 NPC 声线绑定和现有 Host Speech；
- 长团、多玩家隐私、记忆污染和真实 Host 测试。

验收：NPC 能回忆自己听到的旧对话，但不能读取其他 NPC 或玩家的私密记忆；
`chat.send` / `action.chat.send` 不进入 Host、Memory 或 Summary。

每个阶段可以包含多个提交，但不再为每个 DTO、查询或 UI 细节单独开 Issue。只有当某个
阶段实际规模过大、需要独立发布或存在不同负责人时，才再拆出子 Issue。

---

## 17. 最终决策清单

以下方案已经对齐：

- [x] 不创建独立 NPC Agent；
- [x] NPC 仍由同一个 AI Host/Narrator 扮演；
- [x] `@NPC` 转换为结构化 `interlocutor_id`；
- [x] 服务端验证 NPC 当前存在、可见且可交互；
- [x] 目标不存在时触发澄清，不传送玩家或让 NPC 隔空回复；
- [x] 玩家对话和 NPC 回复结构化落库；
- [x] 一个对话步骤允许多个可见 NPC 有序回复；
- [x] NPC 回复先落库，再执行后续玩家行动；
- [x] 后续行动重新读取 PlayerView 并由 Engine 裁决；
- [x] NPC 仍然不能直接改变世界事实；
- [x] 单人未 `@` 默认与守秘人交互；
- [x] 多人未 `@` 默认是玩家自由交流，不进入 Host、Memory 或 Summary；
- [x] `@守秘人` / `@主持人` 和 `@NPC` 才能在多人游戏中触发 Host；
- [x] 普通公开对话广播，私密对话按 player scope 隔离；
- [x] `ChatMessage` 不进入 NPC 记忆；
- [x] NPC canonical MemoryEntry 按房间和 NPC 共享；
- [x] NPC Summary 按 viewer_player_id 隔离；
- [x] 原始 Event 保留，用于精确回忆原话；
- [x] `dialogue.npc` 保留稳定 `event_id` 和 `speaker_id`，支持未来按 NPC 选择声线；
- [x] NPC Provider 音色绑定独立保存，不写入 ModuleContent 或 Engine 状态；
- [x] NPC 语音复用现有 Host Speech，失败只降级为文本；
- [x] 第一版使用结构化 SQL/关键词查询，不引入向量数据库；
- [x] 不实现 NPC 自主行动；
- [x] 不增加 encounter 计数；
- [x] PR #393 不再扩大范围，后续基于 Issue #402 开发。

---

## 18. 结论

这套方案的本质是：

```text
一个 AI 主持
+ 结构化 NPC 对话
+ 结构化守秘人叙事
+ NPC 独立认知记忆
+ viewer 级别隐私过滤
+ 分步 ActionPlan 执行
```

它不会把项目变成多个 NPC Agent，也不会让 NPC 脱离 AI 主持自行行动。它解决的是当前 Narrator 把 NPC 对白、守秘人描述和行动结果混在一起的问题，同时为 NPC 长期记忆、多人权限和长团历史召回提供可靠的数据基础。

最终用户体验应当是：

```text
你：@托马斯，门后有什么？

托马斯：门后有一条向下的石阶。

守秘人：托马斯说完后，你推开了木门。
```

玩家不需要从一大段主持人文本中寻找 NPC 的话，而系统也能准确记录谁说了什么、谁听到了什么，以及这些内容是否可以在几十回合后被 NPC 回忆。

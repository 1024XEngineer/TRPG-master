---
tags: [架构设计, API, 协议, 前后端对齐]
date: 2026-07-10
---

# API 接口对齐规范 —— 前后端实现时对照用

> **本文定位**：[[架构设计-整体多视图]] §五「协议/集成视图」是**决策权威源**（为什么分 REST/WS、事件信封、状态机、错误码……）；本文是**参考①**（`总览/架构设计参考 1.md`）里「定义功能 API」那一步的具体产出——**前端和后端各自实现时，直接照这份文档对齐字段**，不用互相口头确认「这个接口返回什么格式」「这个字段是不是必填」。
> **权威关系**：字段定义以 master §5.1/§5.2 为准；本文只是把决策落成**可执行的请求/响应示例**，两者不一致时以 master 为准，发现不一致请回 master 修正后再同步本文。
> **例子贯穿**：沿用内置模组《古宅幽影》，方便对上下文。
> 返回首页 → [[00-Index]]　相关 → [[架构设计-整体多视图]]、[[00-架构总览与演进日志]]、[[数据库设计导读]]、[[AI编排架构详细设计]]（检定链路/SAN/幸运消耗/QA 等 AI 编排相关字段的权威出处，本文档 2026-07-11 已回顾同步）

## 一、总览：什么时候用 REST，什么时候用 WS

一句话判断标准（详见 master §5.0）：**非实时、一次请求一次响应、可以用完就走的 → REST；进了房间会话之后双向、服务端会主动推送的 → WS**。

```
建房间 / 查模组目录 / 导入模组 / 车卡 / 拉复盘   →  REST（本文第二节）
一旦进入房间会话：加入/就绪/回合/行动/旁白/私密视角  →  WS 长连接（本文第三节）
```

## 二、REST 接口详情

### 2.0 账号与登录（🆕 2026-07-11 新增，App 强制前置门槛）

> **方向调整，如实记录**：2026-07-10「账号体系设计」那轮曾拍板"不强制访客注册"（`players.user_id`/`rooms.host_user_id` 定为可空外键，账号只用来解决"跨设备找回"，跟"能不能玩"是两件事）。本轮推翻了这条——产品诉求明确为"每个玩家都要能复盘、掉线后能重新进来"，而这必须要求每个真人玩家都有服务端持久身份（`reconnectToken` 只能解决同设备内的会话级重连，解决不了跨设备/跨时间找回），所以改成**登录是玩游戏的硬性前提**，不再是可选增强。`players.user_id`/`rooms.host_user_id` 相应从"可空"改成"非空"（`players.is_ai=true` 的 AI 队友行例外，继续可空），已回填 [[前端demo数据表设计]]。

**App 的实际门槛**：打开 App 可以不登录浏览游戏/规则系统/模组目录（§2.3 `GET /modules` 等公开内容型接口，相当于"看一遍 demo"）；但创建房间、加入房间、车卡这些涉及具体玩家身份的动作，都要求已登录。

**注册与登录是两个独立、完整的步骤，故意不与"加入房间"合并**：账号名和密码必须由玩家本人主动设置，不能由系统在加入房间时顺手代填——一个玩家不知道密码的账号，换设备之后没法登录，等于账号形同虚设，直接违背了做账号体系的初衷。

```json
POST /auth/register
{ "account": "jack_brown", "password": "•••••••", "nickname": "杰克·布朗" }
```
→ `201 { "userId": "user_7f2a", "token": "sess_xxx" }`（账号密码由玩家自己填，注册成功直接可用，省掉紧接着再登录一次的多余往返；`account` 已被占用返回 `409 ACCOUNT_TAKEN`）

```json
POST /auth/login
{ "account": "jack_brown", "password": "•••••••" }
```
→ `200 { "userId": "user_7f2a", "token": "sess_xxx" }`（凭证不对返回 `401 INVALID_CREDENTIALS`）

`POST /auth/logout`（需登录）→ `204`，服务端把这条 `user_sessions` 记录的 `revoked_at` 回填（真实服务端 session，不是无状态 JWT，见 [[前端demo数据表设计]] 问题 A-2）

`GET /auth/me`（需登录）→ `{ "userId": "user_7f2a", "account": "jack_brown", "nickname": "杰克·布朗" }`

**Token 怎么带**：REST 请求走 `Authorization: Bearer <token>` header。WS 连接的鉴权放在**建连握手阶段**（连接时带 token），不塞进 `room.join` 的 payload——鉴权跟"进哪个房间"这件事解耦，见 §三 开头说明。

**跟 `reconnectToken` 的分工没变**：账号（`user_sessions`）解决"换设备/隔一段时间之后，凭身份把这一局历史找回来"；`reconnectToken` 解决"这一局进行中，网络抖动/切后台之后快速重连回来"（不用每次网络波动都重新走一遍登录）——两者继续叠加，现在只是"有账号"从可选变成了每个真人玩家的前提。

### 2.1 大厅浏览与创建房间（2026-07-11 改版）

**浏览类**（不需要登录，相当于逛 demo）：

`GET /games` —— 游戏大类列表
```json
{ "games": [
  { "id": "trpg", "name": "跑团", "icon": "...", "status": "recommended" },
  { "id": "clocktower", "name": "血染钟楼", "status": "coming-soon" }
] }
```

`GET /games/{gameId}/systems` —— 该大类下的规则系统
```json
{ "systems": [
  { "id": "coc7", "gameId": "trpg", "name": "克苏鲁的呼唤 第七版", "status": "ready" },
  { "id": "dnd5e", "gameId": "trpg", "name": "龙与地下城 第五版", "status": "coming-soon" }
] }
```

**创建房间**（🔒 需登录）：
```json
POST /rooms
{ "nickname": "杰克·布朗" }
```
`nickname` 可选，不传则用账号 `nickname`。
```json
{ "roomId": "room_8f3a1c", "roomCode": "AR-1927", "reconnectToken": "rtok_xxx" }
```
房间创建后进入 `Lobby` 阶段（见 §5.2.4 状态机）。**此时 `game_id`/`system_id`/`scenario_id` 全部为空**——master 已有结论"选游戏/选系统是房主单人操作、纯前端导航不落后端"，这里落实为：创建房间不需要传 `gameId`/`systemId`，选游戏/选系统只是前端三级菜单导航的前两级，真正命中后端是选到具体模组的那一刻，见 §2.2。

### 2.2 房间预览与选定模组（2026-07-11 新增/改版）

`GET /rooms/{roomCode}` —— 加入前预览，**不强制登录**（了解性质，跟浏览目录同性质，用来决定要不要点"加入"）
```json
{
  "roomId": "room_8f3a1c",
  "roomCode": "AR-1927",
  "phase": "Lobby",
  "moduleTitle": null,
  "playerCount": 1,
  "maxPlayers": 4
}
```

`POST /rooms/{roomId}/module` —— 房主确定模组（🔒 需登录，仅房主；master §5.1 已定义，本文档此前一直没写，本轮补上）
```json
{
  "moduleId": "builtin:core:shadow-over-arkham:1.0.0",
  "attributeGenMethod": "point_buy"
}
```
→ `200`，服务端做**幂等条件更新**（`UPDATE rooms SET scenario_id=$1, system_id=.., game_id=.., attribute_gen_method=$3 WHERE id=$2 AND scenario_id IS NULL`），`system_id`/`game_id` 从 `moduleId` 反查回填，不需要 §2.1 创建房间时传；已经被设置过时返回 `409 MODULE_ALREADY_SELECTED`（防止两个玩家近乎同时选中不同模组时的竞态，呼应 [[前端demo数据表设计]] `rooms` 小节"写入必须做成幂等操作"的要求）。

`attributeGenMethod` 取值 `'roll'` / `'point_buy'`（对应 `rooms.attribute_gen_method`，缺省 `point_buy`）——**2026-07-11 确认：属性生成方式跟选模组是同一个人（房主）、同一时间段做的"开局配置"，并入这个端点，不单独开一步**。两种方法都要真正实现（不是先做一种、另一种长期占位）——`roll` 用 `worlds.attributes[].rollFormula`（3D6×5 / (2D6+6)×5），`point_buy` 用 `worlds.pointBuyConfig`（总池/每项上下限，具体数字待你核实，见 [[前端demo数据表设计]] 问题 12）；**MVP 允许先实现其中一种上线，接口从一开始就按两个取值预留，不是先做单值枚举以后再扩**。

这个端点也是 §2.4"导入失败后房主改选内置模组救场"复用的同一个入口——解析失败时 `resultModuleId` 从未回填成功，`scenario_id` 依然是 `NULL`，幂等约束不会挡住房主重新选一个别的模组。

### 2.3 `GET /modules` —— 模组目录

**请求**：`?systemId=coc7` 可选，按规则系统筛选（对应 §2.1 三级导航的第三级）；不传则返回全部。

**响应**（字段取自 §4.3.1 `ModuleMeta`）
```json
{
  "builtin": [
    {
      "id": "builtin:core:shadow-over-arkham:1.0.0",
      "title": "古宅幽影",
      "version": "1.0.0",
      "authors": ["AIDM Team"],
      "players": { "min": 2, "max": 4 },
      "difficulty": 3,
      "estimatedDuration": "2-3小时"
    }
  ],
  "imported": []
}
```

### 2.4 `POST /modules/import` —— 导入模组（🔴 2026-07-11 改版：同步 → 异步任务，见下方说明）

> **⚠️ 本节与 master §5.0/§5.1 现有表述不一致，本次以本文为准，待回填 master**：master 目前写的是"客户端一次性上传 JSON 内容包 + 资产，服务端跑六步校验，同步返回结果"。这个假设成立的前提是**用户上传的已经是一份规整的 `ModulePack` JSON**。但真实场景是用户上传的是**原始材料**（本轮确认：PDF 为主，其次 txt/md/docx，地图/插图大多是**嵌在 PDF 内部**，不是单独文件）——在 master 现有六步校验之前，多了一道**耗时不定、可能失败**的「LLM/Agent 解析生成 ModulePack 候选」步骤（对应 [[前端demo数据表设计]] 的 `module_import_jobs` 表），不能再假设同步返回。REST 本身没变（这仍然是一次性提交、非长连接的资源操作，符合 §5.0 分层原则），只是从「一次请求拿到最终结果」改成「提交任务 + 轮询状态」两段式。

**请求**：`multipart/form-data`
- `material`：模组原始材料文件，必填，单文件，接受 `.txt`/`.md`/`.pdf`/`.docx`（暂不做扫描件 OCR）——PDF 内嵌的地图/插图由解析步骤负责识别抽取，不需要作者单独拆分出来
- `assets[]`：材料之外单独提供的地图/图片，可选

**上传前的同步粗检**（不涉及内容语义，只查文件本身）：文件为空 / 超过大小上限 / 扩展名不在支持列表 / 文件本身损坏读不出内容 → 不过直接同步 `4xx` 拒绝，不创建任务。这一步**拦不住**"格式对但内容不像模组"这类语义问题，那属于下面解析步骤的失败范畴。

**响应（粗检通过，202）**
```json
{ "importJobId": "job_8f3a1c", "status": "queued" }
```

**轮询** `GET /modules/import/{importJobId}` —— 仅上传者本人可查
```json
{
  "importJobId": "job_8f3a1c",
  "status": "queued",
  "failStep": null,
  "failReason": null,
  "resultModuleId": null,
  "parsedByModel": null,
  "createdAt": "...",
  "updatedAt": "..."
}
```
- `status` 取值：`queued` / `parsing` / `validating` / `failed` / `succeeded`
- `failStep` 取值（成功前提到的"解析"是新加的第 0 步，其余四步对应 §4.3.3 六步中的前四步——⑤⑥不会失败，不需要枚举）：`parsing` / `schema` / `reference` / `reachability` / `contentSafety`
- `failReason`：**面向用户可读的文案**，不是原始技术报错——这是玩家判断"要不要先切回内置模组救场"的唯一依据（见下方失败兜底说明），措辞必须让没有技术背景的房主能看懂下一步该怎么办
- `resultModuleId`：成功后回填，对应 `module_packs.id`，可直接拿去 `GET /modules/{moduleId}` 查看详情或建房时选用

**前端轮询策略**：目标体验是**1 分钟内出结果，最多几分钟**（真实场景是一群人已经在房间里等着开局，不是"传完关闭 App 几天后再回来查"），建议 2~3 秒轮一次，轮到 `failed`/`succeeded` 停止。

**失败处理的三层设计**（2026-07-11 确认，理由：LLM 解析不规整材料本质是概率过程，技术上无法承诺零失败率，但要把"失败"这件事在产品体验上的代价降到最低）：
1. **自动重试**：六步校验中任一步没过，把具体报错喂回给 LLM 重新生成，再走一遍解析→校验，循环若干次（建议上限 3 次）仍不过才真正落定为 `failed`。这个循环发生在 `parsing`⇄`validating` 两个状态之间，**对客户端透明**——前端只需要一直轮询到终态，不需要感知重试发生过。为了追踪重试了几次（可观测性/排查用），`module_import_jobs` 新增字段 `retry_count`（详见 [[前端demo数据表设计]] 同步更新）。
2. **失败不能卡死房间**：不需要新接口——房主可以直接调用已有的 `POST /rooms/{roomId}/module` 改选别的模组（比如临时切回内置模组救场），`failReason` 的可读性（见上）就是支撑这个决策的关键。
3. **上传前粗检**：见上方"同步粗检"，只能拦住文件层面的明显问题，减少让用户白等一轮解析才发现材料本身有问题（比如传错文件）的情况。

**不再需要的接口**：一次导入通常在几分钟内就有结果，且用户就在等待页面上，不存在"翻旧记录找回一个丢掉的 `importJobId`"的场景（跟 `reconnectToken` 解决的"换设备找回同一局游戏"是不同性质的问题）——**不建单独的"导入任务列表"接口**；已成功导入的模组本来就会出现在 `GET /modules` 的 `imported[]` 数组里，足够覆盖"看我导入过什么"这个需求。

### 2.5 `GET /modules/{moduleId}` —— 模组详情（供选模组屏展示）

返回该模组的 `ModuleMeta` + `scenes` 概要（不含 `npcs.secrets` 等只在 GodView 可见的字段——**即便是给房主预览，也不通过这个公开接口下发底牌**）。

### 2.6 建卡（2026-07-11 定稿：骨架 + 技能校验/装备/掷骰细节）

> **🎲 全局原则：服务端权威掷骰**——不管是本节的建卡属性掷骰，还是 §3.3 正式游玩阶段的技能检定（`check.request`/`check.result`），骰子结果一律由服务端计算，客户端只展示结果、不自己算完再上报。COC 一局游戏里骰子会在很多地方出现（建卡定属性、技能检定、以后的战斗判定），必须是同一套信任模型，不能各管一段。

**拉取建卡所需的规则数据**（`worlds` 上"整份读、几乎不变"的规则参考，数据表设计已定论，前端建卡屏进入时拉一次、本地筛选/搜索即可）：
```
GET /systems/{systemId}/ruleset   [需登录]
→ {
    attributes: AttributeDef[],         // 八维属性定义 + rollFormula
    skillCatalog: SkillDef[],           // 技能目录，含 allocatable 标记、是否槽位模板
    occupationCatalog: OccupationDef[], // 职业目录，含 skillSlots 结构
    ageModifierTable: [...],
    pointBuyConfig: {...},
    resourcePools: ResourcePoolDef[]    // HP/SAN/MP/Luck/DB/MOV 怎么算
  }
```

**两条创建路径**，对应 `characters.based_on_pregen_id` vs `occupation_id` 这两条数据模型上就分开的路（🔒 均需登录，路径修正为 `POST /rooms/{roomId}/characters`，master §5.1 已定义，本文档此前一直写成裸 `/characters`）：

```
① 套用预设角色
POST /rooms/{roomId}/characters   { basedOnPregenId }
→ 201，status 直接是 'complete'（克隆快照，不需要走后续任何一步）

② 从零建卡（断点续建，呼应数据表设计问题 10 已按"确认支持"处理）
POST /rooms/{roomId}/characters   {}
→ 201 { characterId, status: 'draft' }

PATCH /rooms/{roomId}/characters/{characterId}   { ...部分字段 }
→ 200，信息/属性/技能/装备背景每一步各发一次，覆盖式合并保存，status 保持 'draft'
```

**属性怎么填，看房间的 `attribute_gen_method`（§2.2）**：
- `point_buy`：玩家自己决定分配值，直接走上面的 `PATCH { attributes: {...} }`，草稿阶段不强校验总池/单项上下限，留到 `.../complete` 一并校验。
- `roll`：不走 `PATCH` 自己填数字，改调专门的动作端点：
```
POST /rooms/{roomId}/characters/{characterId}/roll-attributes
→ 200 { attributes: { STR: 65, CON: 70, DEX: 55, ... } }
```
用 `worlds.attributes[].rollFormula` 服务端计算并直接写入草稿（呼应上面"服务端权威掷骰"原则）；`attribute_gen_method='point_buy'` 的房间调用这个端点返回 `400`（方法不匹配）。允许草稿阶段重复调用重骰，要不要限制重骰次数是产品细节，不影响接口形状，先不限制。

**装备**：`PATCH` 的 `equipment` 字段就是 `{name, qty?, weaponRef?}[]`——`weaponRef` 目前没有目录可选（`worlds.weaponCatalog` 已拍板跟战斗规则引擎一起后置），这一版是自由文本占位字段，前端不需要做"从目录选武器"的下拉，等 `weaponCatalog` 落地后再补。

**完成建卡**（触发完整校验，草稿阶段的中间 `PATCH` 不做强校验）：
```
POST /rooms/{roomId}/characters/{characterId}/complete
→ 200 完整 characters 行，status → 'complete'
→ 422 校验失败，字段级错误定位，格式类比 §2.4 导入校验失败的可读文案风格：
{
  "success": false,
  "errors": [
    { "field": "skills.格斗:斗殴", "message": "职业点只能分配到该职业允许的技能范围内" },
    { "field": "skills.克苏鲁神话", "message": "此技能建卡阶段不可分配点数" },
    { "field": "skills.信用评级", "message": "取值超出该职业允许范围（30-70）" },
    { "field": "occupationPoints", "message": "职业点数总和超出预算（预算 280，已分配 310）" }
  ]
}
```
校验逻辑（职业点是否落在该职业允许的技能池内、`allocatable` 限制、信用评级区间、点数预算）写在后端建卡服务代码里，不是 DB 约束——呼应数据表设计里"跨字段业务规则，DB 约束语法表达不了"的既有结论。

### 2.7 复盘与历史（2026-07-11 定稿）

**我玩过哪些房间**——既然登录已是硬性前提（§2.0）、复盘要能跨设备找回，得有个入口让玩家看到"我参与过的局"列表，才能点进去复盘：
```
GET /users/me/rooms   [需登录]
→ { rooms: [ { roomId, roomCode, moduleTitle, phase, lastActiveAt, hasSummary } ] }
```
按 `last_active_at` 排序；`hasSummary` 方便前端判断要不要显示"查看复盘"按钮。

**复盘摘要**（对应 `room_summaries`，提炼过的成品，复盘页首先展示的内容）：
```
GET /rooms/{roomId}/summary   [需登录，仅参与过这局的玩家可查]
→ 200 {
    roomId, endingType, summaryText, keyFindings: [...],
    stats: { sanChanges: {...}, characterFates: {...}, durationMinutes },
    sessions: [ { sessionNumber, startedAt, endedAt } ],   // room_sessions 数据折进来，不单独开列表接口
    myCharacterId, myCharacterName,   // 🆕 2026-07-11：按当前登录账号反查 players.user_id=me → characters，方便前端不用自己拐一道查"这局里我演的是哪个角色"
    generatedAt
  }
→ 202 { status: 'pending' }   // 游戏刚结束、摘要还在后台生成，前端稍后重试
```
生成时机：`game.ended` 触发后服务端**异步**在后台生成（LLM 写总结文字），不阻塞 `game.ended` 事件本身下发——游戏一结束应该立刻能看到"结束"画面，不用等 LLM 写完摘要才显示。`room_summaries` 是 1:1、不重新生成，不需要像模组导入那样搞一整套 job 状态机，简单的"还没好就 pending"就够。

**逐条回放**（对应 `events` 原始日志，复盘页"想深挖再翻"的部分）：
```
GET /rooms/{roomId}/replay   [需登录，仅参与过这局的玩家可查]
→ {
  "events": [
    { "id": "evt_001", "type": "narration.push", "ts": 1927031900, "visibility": "scene", "payload": { "sceneId": "scene_hallway", "text": "..." } }
  ]
}
```
`visibility: 'private'` 的事件（别人的暗骰结果、别人当时的私密线索）**2026-07-11 已拍板：复盘返回全部事件，不只 public**——理由：复盘发生在游戏已经结束之后，此时"悬念"这层考量已经不成立，全局可见能让复盘更完整（"原来当时小艾偷偷发现了这个"），跟游玩过程中通信铁律一"不泄底"（正在进行时不能越权看到别人的私密信息）不是同一件事，不冲突。

## 三、WebSocket 事件详情

> **🔒 建连即鉴权（2026-07-11 新增）**：WS 连接建立时必须带账号 token（见 §2.0），服务端校验通过才允许后续发 `room.join`；token 无效直接拒绝建连，不走到事件层面。这跟 `room.join` 成功后另外下发的 `reconnectToken`/`session.bound`（§5.2.2）是两层不同的凭证——前者是"你是谁"（账号），后者是"你在这个房间里的哪个位置"（房间会话）。

所有事件都包一层信封（§5.2.1）：
```json
{ "type": "narration.push", "id": "evt_1234", "ts": 1927031900000, "roomId": "room_8f3a1c", "payload": { "...": "..." } }
```
下面只列 `payload` 的具体示例。

### 3.1 客户端 → 服务端

| 事件 | 示例 payload |
|---|---|
| `room.join` | `{ "roomCode": "AR-1927", "nickname": "小艾" }` |
| `room.rejoin` | 🆕 `{ "roomId": "room_8f3a1c", "playerId": "player_01", "reconnectToken": "rtok_xxx", "lastEventId": "evt_1234" }`（断线重连，见 §5.2.5；`reconnectToken` 校验不过返回 `RECONNECT_TOKEN_EXPIRED`，前端走全量重新 `room.join`） |
| `room.leave` | `{}` |
| `character.select` | `{ "characterId": "char_9c21" }` |
| `player.ready` | `{ "ready": true }` |
| `game.start` | `{}`（仅房主可发，需全员 ready，否则见 master §5.4 错误码） |
| `action.submit` | `{ "utterance": "我检查一下铁门和门锁", "inputMode": "voice" }` |
| `check.roll` | 🔧 2026-07-11 改字段：`{ "checkId": "chk_9f2a" }`——服务端在 `check.request` 里签发的一次性关联令牌，取代原来的 `checkpointId?`（路径B没有 Checkpoint，关联不上），路径A/B统一用它对话 |
| `check.manual` | 🆕 2026-07-11：`{ "skill": "侦查" }`——路径B入口，玩家主动选技能发起检定，不经过 `action.submit`/`IntentParser`；服务端按角色当前技能值现算 `target`（无 Checkpoint 时按 `regular` 难度） |
| `san.check.roll` | 🆕 2026-07-11：`{ "checkId": "chk_a831" }`——理智检定摇骰，跟 `check.roll` 同构 |
| `luck.spend` | 🆕 2026-07-11：`{ "checkId": "chk_9f2a", "amount": 3 }`——花费幸运；技能检定用于把 `roll` 拉回 ≤`target`（`amount`=roll−target），理智检定用于减半损失（`amount`=想减少的点数×2）；`amount` 上限由服务端在对应的 `.preliminary` 事件里给出并强制校验，不信任客户端自报数字（服务端权威掷骰原则的延伸） |
| `luck.skip` | 🆕 2026-07-11：`{ "checkId": "chk_9f2a" }`——放弃花费幸运，直接进入最终结果 |
| `qa.ask` | 🆕 2026-07-11：`{ "question": "侦查这个技能是干嘛的？" }`——QA 答疑独立入口，不经过 `action.submit`/`IntentParser`，天然不受回合门控（不是 `action.submit`） |
| `voice.chunk` | `{ "seq": 1, "audio": "<base64>", "format": "opus", "isFinal": false }` |
| `note.save` | `{ "content": "门锁有新鲜划痕" }` |

> **2026-07-11 补充说明**：`check.roll`/`check.manual`/`san.check.roll`/`luck.spend`/`luck.skip`/`qa.ask` 这几个事件背后的编排逻辑（意图解析边界、AI 临场判定四层分级、旁白与NPC对话边界、卡关引导策略等）不在本文档重复展开，权威出处见 [[AI编排架构详细设计]]——本文档只负责协议字段形状对齐。

### 3.2 服务端 → 客户端（公共广播）

| 事件 | 示例 payload |
|---|---|
| `room.state` | `{ "phase": "InGame", "players": [...], "hostId": "player_01", "moduleId": "builtin:core:shadow-over-arkham:1.0.0" }` |
| `player.joined` | `{ "playerId": "player_02", "nickname": "小艾" }` |
| `turn.begin` | `{ "playerId": "player_01" }` |
| `system.msg` | `{ "text": "案件档案已加载 · AI 守秘人在线" }` |
| `game.ended` | `{ "result": { "type": "success", "description": "..." } }` |

### 3.3 服务端 → 客户端（场景定向，🆕 2026-07-11 新增分类）

> master 2026-07-10 把可见性从两档（public/private）扩成三档，新增"场景"档——分头行动后，同房间玩家可能分散在不同地点，旁白只该发给"当前站在这个场景"的玩家，不该整个房间广播（否则等于泄露"别的队友在干什么"）。`narration.push` 此前误列在 §3.2"公共广播"，本次改正。

| 事件 | 示例 payload |
|---|---|
| `narration.push` | `{ "sceneId": "scene_hallway", "text": "手电筒的光扫过铁门……", "streaming": true, "seq": 3, "done": false }`——🔧 2026-07-11 补 `done`（最后一个分片为 `true`，对应底层模型流关闭的机械事实，客户端据此收起"输入中"指示器）；听众=当前 `characters.location===sceneId` 的玩家集合，现算不是固定订阅 |

### 3.4 服务端 → 客户端（私密定向，逐人不同）

| 事件 | 示例 payload |
|---|---|
| `session.bound` | 🆕 `{ "playerId": "player_01", "reconnectToken": "rtok_xxx" }`（`room.join` 成功后定向下发给刚连接的客户端，本地存起来供 `room.rejoin` 用；不广播） |
| `view.private` | `{ "view": { "forWhom": "player_01", "visibleSceneDescription": "...", "visibleClues": [...], "visibleSan": 65 } }`（🚧 只有 `visibleSan`，缺 HP/MP/幸运，仍待续——这条不在今天六轮 AI 编排详细设计范围内，见文末待办） |
| `check.request` | 🔧 2026-07-11 补 `checkId`：`{ "checkId": "chk_9f2a", "skill": "侦查", "target": 65, "checkpointId": "cp_003" }`——`checkId` 必带（路径A/B统一关联），`checkpointId` 仅路径A（命中 Checkpoint）时有值 |
| `check.result.preliminary` | 🆕 2026-07-11：`{ "checkId": "chk_9f2a", "roll": 68, "target": 65, "success": false, "maxLuckSpend": 3, "currentLuck": 45 }`——仅**技能检定失败**时发，给玩家幸运决策窗口；玩家回应 `luck.spend`/`luck.skip` 后才发最终 `check.result` |
| `check.result` | 🔧 2026-07-11 补 `checkId`/`luckSpent`：`{ "checkId": "chk_9f2a", "roll": 65, "target": 65, "success": true, "luckSpent": 3 }`（`hidden=true` 的检定**连 `check.request` 也不下发**，不只是 `check.result`——避免"展示了掷骰 UI 却永远等不到结果"的怪异体验）。命中 Checkpoint 时 `appliedOutcome` 里的 `grantsEntityIds`/`sanLoss`/`sceneTransition` 依次生效；未命中预设内容时骰子结果照常下发，但不执行任何预设效果，只作为 Narrator 的叙事素材，见 [[AI编排架构详细设计]] §1.7 |
| `san.check.request` | 🆕 2026-07-11：`{ "checkId": "chk_a831", "target": 55, "checkpointId": null }`——理智检定版的 `check.request`，无 `skill` 字段（理智检定是 roll-under 当前 SAN 值，不是技能） |
| `san.check.result.preliminary` | 🆕 2026-07-11：`{ "checkId": "chk_a831", "roll": 78, "target": 55, "success": false, "sanLossIfNoSpend": 6, "maxLuckSpend": 12, "currentLuck": 50 }`——仅允许幸运消耗时发；`success` **不因幸运改变**（理智检定失败已定论），幸运只影响 `sanLossFinal`，这跟技能检定的幸运语义不同，见 [[AI编排架构详细设计]] §2.3（附 COC7 官方规则调研出处） |
| `san.check.result` | 🆕 2026-07-11：`{ "checkId": "chk_a831", "sanLossFinal": 3, "luckSpent": 12 }`——`SanTrigger.kind` 其余五种非 `check` 形态（`flat`/`direct`/`max_reduce`/`gain`/`capped`）不走这套协议，没有摇骰环节，由 `RulesEngine` 内部直接生效，靠 `narration.push`+下次 `view.private` 体现 |
| `clue.granted` | 🔴 `{ "entity": { "id": "entity_042", "kind": "clue", "content": "深灰色羊毛布料碎片" } }`（原 `{ clue }`，随 §4.3.1 `Clue`+`NPC` 合并为 `Entity` 改名，见下方共享类型表说明） |
| `qa.answer` | 🆕 2026-07-11：`{ "questionId": "q_771", "text": "侦查用于……", "streaming": true, "seq": 1, "done": true }`——仅提问者可见；`done` 同 `narration.push` |
| `error` | `{ "code": "NOT_YOUR_TURN", "message": "还没轮到你行动" }`（完整错误码表见 master §5.4，本文档不重复维护，避免两处漂移） |

## 四、共享类型对照（前后端契约，呼应 ADR-9）

后端 Python（Pydantic）定义 → 生成 TS 类型，下面这些是 REST/WS 载荷里用到的核心共享类型，完整字段定义见 §4.3.1：

| 类型 | 用在哪 | 权威定义 |
|---|---|---|
| `ModuleMeta` | `GET /modules` 响应、`room.state` | §4.3.1 |
| `PlayerView` | `view.private` payload | §四 ViewProjector 产物，字段：`forWhom`/`visibleSceneDescription`/`visibleClues`/`visibleSan` |
| `Entity`（裁剪后，🔴 原 `Clue`，2026-07-11 同步改名） | `clue.granted` | §4.3.1——线索/NPC/怪物/物品/动物/杂物统一用 `kind` 区分（合并原因：六个真实 COC 模组验证后发现"核心是线索网络"只对调查型模组成立，其余模组的核心是因果链/携带物开关/说服/战斗，这些"有状态、被规则引用的东西"本质上是同一种数据结构，只是 `kind` 不同，不需要为每种玩法机制各开一套平行 schema）。这里只含已发现字段，不含 `reachableBy` 等模组设计态字段 |
| `Checkpoint` 的公开子集 | `check.request` | 只暴露 `skill`/`target`，绝不下发 `onSuccess`/`onFail` 提示内容 |

## 五、前后端对齐 checklist

改动任何一个接口/事件字段时：
1. 先改 master §5.1/§5.2（权威源）；
2. 同步改本文对应示例；
3. 跑一次 Pydantic → TS 类型生成（ADR-9），确认两端类型没漂移；
4. 通知对接的另一端——本文档就是通知内容，不用口头再讲一遍。

## 待办
- [ ] 补 §5.2.5 断线重连的 `room.rejoin` 请求/响应具体示例（目前 master 只有文字描述）
- [ ] 若 master §五 之后继续深化或字段变动，本文档需要跟着回顾同步
- [x] ~~本轮（§2.0/§2.1/§2.2/§2.6/§2.7/§三）新增端点+账号强制登录+服务端权威掷骰原则回填 master~~ → **已完成（2026-07-11）**：master §4.4.8/§5.1/§5.2.2/ADR-16/ADR-17 已同步，细节仍以本文档为准，master 只保留端点一览+关键原则，不是全量搬运
- [x] ~~理智检定（SAN check）协议设计~~ → **已完成（2026-07-11，AI 编排详细设计第二轮）**：独立的 `san.check.request`/`san.check.roll`/`san.check.result(.preliminary)` 事件族，见 §三
- [x] ~~幸运消耗（luck spend）的协议时序~~ → **已完成（2026-07-11，AI 编排详细设计第二轮）**：`check.result.preliminary`/`san.check.result.preliminary` + `luck.spend`/`luck.skip` 两段式，技能检定与理智检定语义不同（经 COC7 官方规则调研确认），见 §三、[[AI编排架构详细设计]] §2.3
- [x] ~~协议层面的检定/掷骰完整设计~~ → **已完成（2026-07-11）**：`check.roll` 字段形状改用 `checkId`，路径A/路径B（`check.manual`）已定，`resolutionKind`/`appliedOutcome` 从类型层面保证临场判定不执行预设效果，见 [[AI编排架构详细设计]] §一。**`PlayerView` 缺 HP/MP/幸运仍待续**，不在这轮范围
- [x] ~~§三 本次同步的内容要回填 master §5.2.2~~ → 早前一轮已完成；**本次（2026-07-11）新一轮同步**：`checkId`/`check.manual`/`san.check.*`/`luck.spend`/`luck.skip`/`qa.ask`/`qa.answer`/`narration.push.done` 已回填 master §4.5/§5.2.2，双向一致
- [ ] `PlayerView` 补全 HP/MP/幸运（现在只有 `visibleSan`）——唯一还没解决的协议细节，留后续
- [ ] NPC 对话/QA 答疑背后的编排逻辑（旁白与NPC边界、QA定位/复盘摘要生成/卡关引导策略）已在 [[AI编排架构详细设计]] 完成，本文档只对齐协议字段本身，不重复维护编排逻辑的"为什么"

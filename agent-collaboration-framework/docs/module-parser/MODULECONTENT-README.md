# ModuleContent 字段决策：给团队的同步说明

> 最终契约：[module-content-field-decisions.md](module-content-field-decisions.md)
> 本文用追书人（书房 Demo）的例子解释每个字段的作用。

---

## 一、整体结构：当前发布契约的 6 个集合

当前 B/C 发布契约包含 4 个必需集合（`scenes`、`entities`、`checkpoints`、
`win_conditions`）和 2 个默认空集合（`module_rules`、`information_items`）。
规则引擎已能加载这套声明，并在运行前审计实际使用的 Hook、Expression、Operation 与
`world_ref`；当前确定性内核完整覆盖《追书人》纵切，其他发布能力会明确报告为不支持。

```
ModuleContent
├── module_id, version, world_ref    —— 身份和规则系统
├── background                       —— 时代、故事前提与叙事基调
├── initial_scene_id                 —— 显式开局场景
├── scenes[]                         —— 有哪些空间
├── entities[]                       —— 有哪些东西
├── checkpoints[]                    —— 能做哪些动作
├── win_conditions[]                 —— 什么时候结束
├── module_rules[]                   —— 全局规则
└── information_items[]              —— 可独立引用的信息事实
```

---

## 二、逐字段解释

### ModuleContent.background —— “这个故事应当是什么气质”

`background` 是顶层必填的模组级叙述上下文，提炼原文开头的时代、地点、
玩家侧故事前提和叙事基调。规则投影会先把它放入 `PlayerView`，主持编排再从
`PlayerView` 和已提交 evidence 构造 `ActionPlanNarrationContext`；它不能代替已发现信息
成为新的调查事实。
未揭示的幕后真相必须继续放在 `secrets` 或受可见性约束的信息项中，不得写入
`background`。

### SceneSpec —— "在哪里"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"study"` | 唯一标识 |
| `name` / `content` | `"书房"` / `"KP 场景说明..."` | 模组内部名称和完整内容，不直接进入 PlayerView |
| `player_visible_name` | `"书房"` | 玩家安全的场景名称 |
| `player_visible_description` | `"昏黄灯光下，书架、木柜..."` | 玩家当前可感知描述；不得从 `content` 自动兜底 |
| `narrative_details` | `[{"id":"opened-cabinet",...}]` | 通过状态门后持续投影的安全细节 |
| `entity_ids` | `["butler","bookshelf","cabinet"]` | 索引：这个场景里有哪些实体。B 的引擎据此决定 PlayerView 展示什么 |
| `checkpoint_ids` | `["investigate_bookshelf","smash_cabinet"]` | 索引：这个场景里能做什么动作。当前步骤 adjudicator 据此匹配玩家语义 |
| `exits` | `["garden"]` | 可达 Scene 限制；空数组表示可自由前往其他 Scene，非空时只允许列出的 Scene |
| `available_exits` | `[{"id":"north-door",...}]` | 可选的出口展示/可见性覆盖；省略时由 `exits` 和 Scene 安全名称自动派生 |

### EntitySpec —— "有什么东西"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"cabinet"` | 唯一标识，其他字段引用它 |
| `kind` | `"object"` | npc / object / location 三种 |
| `name` / `aliases` | `"密件柜"` / `["目标容器"]` | 内部身份与 KP 语义，不进入 PlayerView |
| `player_visible_name` / `player_visible_aliases` | `"上锁的柜子"` / `["柜子","木柜"]` | 玩家可见身份，也是 Host 的安全语义匹配来源 |
| `content` | `"一只带黄铜锁孔的年代久远的木柜"` | 玩家可见描述 → 进入 PlayerView |
| `narrative_details` | `[{"id":"keyhole",...}]` | 状态成立后才进入 PlayerView 的持续细节 |
| `visibility` | `{"audience":"all",...}` | 实体自身的受众与发现策略 |
| `observable_state` | `[{"key":"opened","label":"柜门是否打开"}]` | 动态状态 allow-list；不复制原始 Entity state |
| `secrets` | `"文件藏在柜中；强行砸开会毁坏文件"` | KP 私密信息 → 不进入 A 的上下文。信息隔离边界 |
| `state` | `{"opened": false}` | 声明合法状态键及初始值；开局时复制到独立的 GameState |
| `refuse_ops` | `["open"]` | 静态拒绝列表：不管什么条件，默认不能 open。需要 Rule 动态解封 |
| `blocked_text` | `"柜门纹丝不动"` | 操作被拒绝时给玩家的提示 |
| `direct_responses` | `{"investigate":"黄铜锁孔很小..."}` | 无检定交互的直接回应——"我看一眼柜子"不需要掷骰 |
| `rules` | `[allow_open_with_key]` | 挂在这个实体上的动态规则 |
| `stat_block` | `{STR:85, CON:75...}` | 可选属性块。道格拉斯有，管家没有。必须可空 |

### RuleSpec —— "什么条件下发生什么"

```
Rule = 什么时候（hook） + 条件是什么（when） + 做什么（then） + 怎么和别的规则相处（mode）
```

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"allow_open_with_key"` | 唯一标识 |
| `hook` | `"on_interact"` | 什么时候检查。发布契约允许 20 个 Hook；内核消费《追书人》所需子集并在运行前审计 |
| `priority` | `100` | 同 hook 上多条规则时排先后 |
| `mode` | `"append"` | 怎么相处。append=追加，override=覆盖系统默认，forbid=整个 hook 跳过 |
| `when` | `{path:"entities.bookshelf.key_found", equals:true}` | 条件判断。支持 path/equals 与受限 AST Expression，不执行任意代码 |
| `then` | `[allow("open"), modify("cabinet.opened", true)]` | 有序操作列表。当前内核支持《追书人》所需的 10 种 Operation |
| `facts` | `["玩家用钥匙打开柜子"]` | 引擎内部确认事实 |
| `player_visible_information` | `["钥匙正好转动了锁芯..."]` | 给玩家看的信息 |

**柜子的规则示例**：

```
Rule(
  hook = "on_interact",                          // 有人要交互时
  when = "entities.bookshelf.key_found == true", // 钥匙找到了
  then = [
    allow("open"),                               // 解除 refuse_ops
    modify("entities.cabinet.opened", true),     // 柜子打开
    modify("entities.document.obtained", true),  // 拿到文件
  ]
)
```

### CheckpointSpec —— "能做什么动作"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"investigate_bookshelf"` | 唯一标识 |
| `scene_id` | `"study"` | 属于哪个场景 |
| `action` | `"investigate"` | 语义提示——不是白名单，只是告诉 A "这是调查类动作" |
| `target_id` | `"bookshelf"` | 针对哪个实体 |
| `skills` | `["spot-hidden"]` | 可用技能 |
| `difficulty`（可空） | `"regular"` | 难度。None 表示运行时决定（蛙蛙村软判据） |
| `outcomes` | `{success: {...}, failure: {...}}` | 成功/失败及可选分级后果（大成功/极难成功/普通成功等） |
| `visibility` | `None` | 谁能看到 + 是否需要先发现。None = 全员可见无需发现。地穴入口需追踪检定后出现 |

### CheckpointOutcomeSpec —— "成功了怎样，失败了怎样"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `facts` | `["玩家在书架后发现钥匙"]` | 引擎确认事实 |
| `discover_information_ids` | `["hidden_document_location"]` | 把长期事实写入玩家/队伍已发现信息 |
| `player_visible_information` | `[{"text":"你拨开积灰的书册..."}]` | 给玩家看的内容；字符串输入也会兼容归一为 `VisibleInformation` |
| `narration_constraints` | `["必须明确玩家已经发现钥匙"]` | 硬约束：A 的 Narrator 不能乱说 |
| `ops` | `[modify("key_found", true)]` | 引擎可执行的操作——**Parser 最难的活**：把"找到钥匙"翻译成 `modify key_found = true` |

### WinConditionSpec —— "什么时候结束"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"ending_document_recovered"` | 唯一标识 |
| `when` | `{path:"entities.document.obtained", equals:true}` | 触发条件 |
| `fact` | `"玩家取得关键文件"` | 引擎确认 |
| `player_visible_information` | `"文件中的记录让真相终于有了证据"` | 结局描述 |
| `is_ending` | `true` | 默认 true。银之锁"被抓回→重来"设为 false——只改状态不结束游戏 |

每次动作执行后，B 遍历所有 `win_conditions`，when 匹配的触发结局。

### VisibilityPolicy + VisibleInformation

| 字段 | 作用 |
|------|------|
| `audience` | 谁能看：all=全体 / actor=执行者 / ho=指定 HO / keeper=仅 KP |
| `requires_discovery` | 是否需要先"发现"：追书人地穴入口、鬼屋暗骰 |
| `discovery_rule` | 怎么发现：自然语言或表达式。空=使用默认机制 |

挂在两个位置：`CheckpointSpec.visibility` 控制"检定点谁能看到"，`VisibleInformation.visibility` 控制"结果信息谁能读"。

---

## 三、一个完整来回

```
① 玩家"我仔细调查书架"
② B 告诉 A：当前在书房，可见 [管家/书架/柜子/文件/窗户]，可用动作 [调查书架, 砸柜子]
③ A 匹配 → Checkpoint("investigate_bookshelf")
④ B 校验：scene_id ✓ target_id ✓ skills ✓
⑤ B 执行 outcomes.success.ops: modify("key_found", true)
⑥ B 检查 WinCondition: document.obtained == true? → false → 不触发
⑦ B 返回 ActionResult: "你拨开积灰的书册，摸到了一把小钥匙"
⑧ A 的 Narrator 生成回复
```

---

## 四、当前落地状态

- **发布契约已落地**：`mode`、`expr`、可空 `difficulty`、`is_ending`、`module_rules`、结构化 `information_items`、内部 `exits`、玩家安全 `available_exits`、`observable_state`、`stat_block`、分级结果、可见性、20 个 Hook 与 Operation 联合类型。
- **《追书人》运行时已落地**：安全 Expression、Hook 优先级与模式、状态级联、COC7 百分骰/SAN/最小战斗、时间、场景、结局、投影和固定随机源测试。
- **扩展策略**：发布契约仍大于当前运行能力；`scale/absorb`、完整 COC7 战斗/追逐等后续能力通过 Runtime 扩展，不修改 B/C 发布字段形状，未支持能力必须 fail closed。

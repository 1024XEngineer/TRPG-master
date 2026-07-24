# ModuleContent 字段决策：给团队的同步说明

> 详细文档：`module-content-field-decisions.md`
> 本文用追书人（书房 Demo）的例子解释每个字段的作用。

---

## 一、整体结构：8 个集合

```
ModuleContent
├── module_id, version, world_ref    —— 身份和规则系统
├── scenes[]                         —— 有哪些空间
├── entities[]                       —— 有哪些东西
├── checkpoints[]                    —— 能做哪些动作
├── win_conditions[]                 —— 什么时候结束
├── module_rules[]                   —— 全局规则（P1）
└── information_items[]              —— 可引用的事实（P1）
```

---

## 二、逐字段解释

### SceneSpec —— "在哪里"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"study"` | 唯一标识 |
| `name` | `"书房"` | 显示名 |
| `content` | `"昏黄灯光下，书架、木柜..."` | 场景描述，给 A 做叙事上下文 |
| `entity_ids` | `["butler","bookshelf","cabinet"]` | 索引：这个场景里有哪些实体。B 的引擎据此决定 PlayerView 展示什么 |
| `checkpoint_ids` | `["investigate_bookshelf","smash_cabinet"]` | 索引：这个场景里能做什么动作。A 的 IntentParser 据此匹配玩家语义 |
| `exits`（P1） | `[]` | 可以去的其他场景。空 = 无空间约束，玩家自由移动。银之锁的房间→走廊则有约束 |

### EntitySpec —— "有什么东西"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"cabinet"` | 唯一标识，其他字段引用它 |
| `kind` | `"object"` | npc / object / location 三种 |
| `name` / `aliases` | `"上锁的柜子"` / `["柜子","木柜"]` | A 做语义匹配——玩家说"打开柜子"能匹配到 |
| `content` | `"一只带黄铜锁孔的年代久远的木柜"` | 玩家可见描述 → 进入 PlayerView |
| `secrets` | `"文件藏在柜中；强行砸开会毁坏文件"` | KP 私密信息 → 不进入 A 的上下文。信息隔离边界 |
| `state` | `{"opened": false}` | 声明合法状态键。**初始值不用于运行时**——B 从 GameState 初始化 |
| `refuse_ops` | `["open"]` | 静态拒绝列表：不管什么条件，默认不能 open。需要 Rule 动态解封 |
| `blocked_text` | `"柜门纹丝不动"` | 操作被拒绝时给玩家的提示 |
| `direct_responses` | `{"investigate":"黄铜锁孔很小..."}` | 无检定交互的直接回应——"我看一眼柜子"不需要掷骰 |
| `rules` | `[allow_open_with_key]` | 挂在这个实体上的动态规则 |
| `stat_block`（P1） | `{STR:85, CON:75...}` | 可选属性块。道格拉斯有，管家没有。必须可空 |

### RuleSpec —— "什么条件下发生什么"

```
Rule = 什么时候（hook） + 条件是什么（when） + 做什么（then） + 怎么和别的规则相处（mode）
```

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"allow_open_with_key"` | 唯一标识 |
| `hook` | `"on_interact"` | 什么时候检查。P2 扩展到 20 个——进入场景/交互/状态变化/时间推进/战斗中每一步 |
| `priority` | `100` | 同 hook 上多条规则时排先后 |
| `mode`（P0） | `"append"` | 怎么相处。append=追加，override=覆盖系统默认，forbid=整个 hook 跳过 |
| `when` | `{path:"entities.bookshelf.key_found", equals:true}` | 条件判断。P2 后支持大于小于、AND/OR、count/max 聚合 |
| `then` | `[allow("open"), modify("cabinet.opened", true)]` | 有序操作列表。P2 从 2 种扩展到 ~11 种 |
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
| `difficulty`（P0 可空） | `"regular"` | 难度。None 表示运行时决定（蛙蛙村软判据） |
| `outcomes` | `{success: {...}, failure: {...}}` | 成功/失败的后果。P2 支持分级（大成功/极难成功/普通成功等各自不同） |
| `visibility`（P2） | `None` | 谁能看到 + 是否需要先发现。None = 全员可见无需发现。地穴入口需追踪检定后出现 |

### CheckpointOutcomeSpec —— "成功了怎样，失败了怎样"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `facts` | `["玩家在书架后发现钥匙"]` | 引擎确认事实 |
| `player_visible_information` | `["你拨开积灰的书册..."]` | 给玩家看的内容。P2 后变为 `VisibleInformation`，可指定 audience |
| `narration_constraints` | `["必须明确玩家已经发现钥匙"]` | 硬约束：A 的 Narrator 不能乱说 |
| `ops` | `[modify("key_found", true)]` | 引擎可执行的操作——**Parser 最难的活**：把"找到钥匙"翻译成 `modify key_found = true` |

### WinConditionSpec —— "什么时候结束"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"ending_document_recovered"` | 唯一标识 |
| `when` | `{path:"entities.document.obtained", equals:true}` | 触发条件 |
| `fact` | `"玩家取得关键文件"` | 引擎确认 |
| `player_visible_information` | `"文件中的记录让真相终于有了证据"` | 结局描述 |
| `is_ending`（P0） | `true` | 默认 true。银之锁"被抓回→重来"设为 false——只改状态不结束游戏 |

每次动作执行后，B 遍历所有 `win_conditions`，when 匹配的触发结局。

### VisibilityPolicy + VisibleInformation（P2）

| 字段 | 作用 |
|------|------|
| `audience` | 谁能看：all=全体 / actor=执行者 / ho=指定 HO / keeper=仅 KP |
| `requires_discovery` | 是否需要先"发现"：追书人地穴入口、鬼屋暗骰 |
| `discovery_rule` | 怎么发现：自然语言或表达式。空=使用默认机制 |

挂在两个位置：`CheckpointSpec.visibility` 控制"检定点谁能看到"，`VisibleInformation.visibility` 控制"结果信息谁能读"。

---

### InformationItem（P1）—— "有什么事实"

| 字段 | 值示例 | 作用 |
|------|--------|------|
| `id` | `"buwen_identity"` | 唯一标识，可被 Rule/Condition 引用 |
| `content` | `"布文杉是隐修堂派来调查学生失踪的卧底"` | 事实正文 |
| `visibility` | `{audience:"keeper"}` | 静态可见性声明。获取后可由 Outcome 的 Effect 切换 |

**作用**：给 `facts` 裸字符串加 ID。调查模组的信息链——"尸体 → 布文杉身份 → 隐修堂 → 地下秘密"——每条事实有稳定 ID 后，Rule 的 Condition 可以写 `when: information_known("buwen_identity")`。

**只负责**：事实本体的静态声明。**不负责**：信息获取过程（InformationAcquisition，Deferred）、玩家知识状态（KnowledgeState，Deferred）。

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

## 四、P0/P1/P2

- **P0**：4 处小改动（mode/expr/difficulty 可空/is_ending），不 break 任何测试
- **P1**：4 个新字段/集合（module_rules/information_items/exits/stat_block），等 B 确认消费者后加。SAN 不设专用对象
- **P2**：扩四张表（Hook 20/Expression 完整/Op ~11/内建变量 ~15），不新增顶层集合。Track/Timeline/Encounter 全部由 Rule 组合表达

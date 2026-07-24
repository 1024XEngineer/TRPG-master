# Example Driven Validation：P2 Contract 能力验证

> 日期：2026-07-24
> 验证对象：P2 最终 Contract（`module-content-field-decisions.md` §8）
> 验证模组：追书人、银之锁、RE 计划
>
> P2 Contract 相比当前 v1 的新增能力：
> Hook 4→20（含 on_state_change、on_time_elapsed）、Expression 完整语法（比较/布尔/算术/聚合）、Op 2→~12（含 forbid/force/spawn/schedule 等）、SanTriggerSpec、module_rules、exits、stat_block、difficulty 可空、tier override、is_ending。内建变量 ~15。

---

## 一、追书人

### 1. 多结局 → WinConditionSpec ✅

P2 支持完整的等值/组合条件 + `is_ending`。

```
WinConditionSpec("ending_document_recovered",
  when={path:"entities.document.obtained", equals:true}, is_ending=true)
WinConditionSpec("ending_document_destroyed",
  when={path:"entities.document.destroyed", equals:true}, is_ending=true)
```

非终局（道格拉斯被杀→1d3 天后继续）用 Rule(on_state_change, when `entities.douglas.alive==false`, then `schedule(timer="douglas_body_found", delay=1d3 days)`) 表达。不需要 WinCondition。

**判断**：完全支持。

### 2. SAN 损失 → SanTriggerSpec ✅

```
SanTriggerSpec(id="san_douglas_sight", kind=check, condition="目击道格拉斯", loss="0/1d6")
SanTriggerSpec(id="san_douglas_talk", kind=flat, condition="与道格拉斯交谈后", loss="1d4")
SanTriggerSpec(id="san_ghoul_crowd", kind=capped, loss="1/1d6", source_tag="ghoul_crowd")
```

**判断**：完全支持。

### 3. 道格拉斯行为 → 自然语言

NPC "默认不攻击""被打断后停止攻击"是扮演素材。Host Agent 消费自然语言。P2 的 `stat_block` 可以提供战斗数值，但行为决策不需要 Rule。

**判断**：自然语言。C 类——Host Agent 处理。

### 4. 有钥匙开柜子 → RuleSpec ✅

```
Entity(cabinet).refuse_ops=["open"]
Entity(cabinet).rules=[RuleSpec(
  hook="on_interact", mode="append", priority=100,
  when={path:"entities.bookshelf.key_found", equals:true},
  then=[AllowOp(action="open"), ModifyOp(path="entities.cabinet.opened", set=true),
        ModifyOp(path="entities.document.obtained", set=true)]
)]
```

**判断**：完全支持。和 v1 相同，P2 加了 mode。

### 5. 砸柜子 C 类反转 → CheckpointSpec ✅

```
CheckpointSpec(smash_cabinet, outcomes={
  success: {ops:[modify cabinet.opened=true, modify document.destroyed=true]},
  failure: {ops:[]}
})
```

**判断**：完全支持。

### 6. 昼夜循环 → Rule + on_time_elapsed ✅

```
module_rules=[
  Rule(on_scene_enter, when {path:"clock.time_of_day", equals:"night"},
       then=[ForceOp(action="enable_checkpoint", target="nightly_surveillance")]),
  Rule(on_time_elapsed, when {path:"clock.time_of_day", equals:"night"},
       then=[ForceOp(action="enable_checkpoint", target="nightly_surveillance")])
]
```

两条 Rule：刚进入场景时 + 时间推进到夜晚时。`on_time_elapsed` 由 B 的 Scheduler 发布。

**判断**：完全支持。P2 Hook + 内建变量解决了"一直待在场景里"的问题。

### 7. 多条调查路径 → SceneSpec ✅

场景间自由移动——P2 的 `exits=[]`（空表示无空间约束）。每个 Scene 有自己的 Checkpoint。

**判断**：完全支持。

### 8. 地穴隐藏入口 → CheckpointSpec.hidden ⚠️

P2 没有独立 `hidden` 字段。地穴入口对应的 `CheckpointSpec(track_footprints)` 在所有场景都可见——"隐藏"语义无法表达。

**判断**：当前缺失。A 类——`CheckpointSpec.hidden: bool` 字段。追书人、鬼屋、复足均需要。

### 9. 酒→贿赂看守 → Entity.state + CheckpointSpec ✅

和 v1 相同。完全支持。

---

### 追书人小结

| 完全支持 | 7/9 |
| 当前缺失 | 1/9（hidden） |
| 自然语言 | 1/9（NPC 行为） |

---

## 二、银之锁

### 1. 连续解谜段 → SceneSpec ✅

和 v1 相同。完全支持。

### 2. 区域束缚 → RuleSpec + forbid ✅

```
module_rules=[
  Rule(on_scene_enter, mode="append",
       when {path:"entities.silver_lock.active", equals:true},
       then=[ForbidOp(action="leave")])
]
```

P2 有 `on_scene_enter` Hook + `forbid` Op。完全支持。

**判断**：完全支持。

### 3. 猫→NPC 因果链 → Rule + spawn ✅

```
Entity(cat).rules=[
  Rule(on_scene_enter("corridor"), when {path:"entities.cat.alive", equals:true},
       mode="append",
       then=[SpawnOp(rule="cat_attack_npc")])
]
module_rules=[
  Rule(on_death("npc.kidnapper"), when {path:"entities.cat.alive", equals:false},
       mode="append",
       then=[TriggerEndingOp(ending_id="lock_broken")])
]
```

P2 有 `spawn` Op（逐条触发因果链）+ `on_death` Hook + `trigger_ending` Op。完全支持。

**判断**：完全支持。

### 4. 速写本画物品 → 不可结构化

开放式创造。没有封闭 outcome 集合。P2 无法改变这点。

**判断**：D 类——暂不处理。自然语言保留。

### 5. 被抓回→重来 → Rule + on_state_change ✅

```
Rule(on_state_change, when {path:"entities.cat.alive", equals:false},
     mode="append",
     then=[ModifyOp(path="entities.player.location", set="room"),
           ForceOp(action="reset_scene", target="room")])
```

P2 的 `is_ending=false` 语义由 Rule 承担——非终局回滚走 `on_state_change`，不碰 WinCondition。完全支持。

**判断**：完全支持。

### 6. 多种交互 → Checkpoint + direct_responses ✅

和 v1 相同。完全支持。

### 7. 空间拓扑 → SceneSpec.exits ✅

```
SceneSpec("room", exits=["corridor"])
SceneSpec("corridor", exits=["room"])
```

P2 有 `exits`。完全支持。

### 8. 人物卡定制 → 不可结构化

和 v1 相同。D 类。

---

### 银之锁小结

| 完全支持 | 6/8 |
| 不可结构化 | 2/8（画物品/人物卡定制） |

---

## 三、RE 计划

### 1. 三 HO → Entity.state + Rule ✅

不给专用 EntryPointSpec。每个 HO 的初始状态存为 `Entity.state`：

```
Entity("ho_config").state = {
  "HO1": {"credit":60, "initial_scene":"nightclub"},
  "HO2": {"credit":40, "initial_scene":"jewelry_heist"}
}
```

Loader 建局时根据玩家选中的 HO 初始化角色状态。不同初始场景由 Loader 设置 `GameState.scene_id`。

**判断**：完全支持。P2 不需要专用 EntryPointSpec。

### 2. HO 私有信息 → VisibleInformation.audience ⚠️

P2 没有独立的 `audience` 字段设计。HO1 的导入背景只能全队广播或完全不展示。

**判断**：当前缺失。A 类——`player_visible_information` 改为结构化 `{text, audience}`。RE 计划是 1/15 样本，但"仅触发者可见""仅指定角色可见"是多模组通用需求。

### 3. 时间延迟 → schedule Op ✅

```
Rule(on_read_phone, mode="append",
     then=[ScheduleOp(timer_id="ho1_meeting",
            delay={value:3, unit:"day"},
            payload={transition_scene_id:"scene_restaurant"},
            owner_kind:"ho", owner_ref:"HO1")])
```

P2 的 `schedule` Op 在审计报告中已设计。完全支持。

**判断**：完全支持。

### 4. 自由行动轮 → 自然语言

"3-4 轮自由行动"是主持节奏。C 类——Host Agent 处理。

**判断**：自然语言。

### 5. 醉酒检定 → CheckpointSpec ✅

和 v1 相同。完全支持。

### 6. 三次驾驶取最低 → RepeatCheckPolicy ⚠️

P2 审计报告设计了 `RepeatCheckPolicy` 但字段决策文档未纳入 §8。当前 P2 的 `CheckpointSpec` 无此字段。

**判断**：当前缺失。A 类——`RepeatCheckPolicy(max_attempts, aggregation)`。"三次取最低"在 RE 计划、追书人重复监视、复足重复检定中均有出现。

### 7. 不同初始场景 → Loader（B 类）

Loader 建局时根据 HO 设置 `GameState.scene_id`。不需要新字段。

**判断**：B 类——Runtime 解决。

### 8. 隐藏结局 → Expression 布尔 ✅

```
WinConditionSpec("hidden_ending",
  when={expr:"entities.milestone_A.completed == true && entities.milestone_B.completed == true && entities.task_C.result == 'success'"},
  is_ending=true)
```

P2 Expression 支持布尔操作。完全支持。

**判断**：完全支持。

### 9. 赎身→赠礼 → Entity.state + CheckpointSpec ✅

和 v1 相同。完全支持。

### 10. NPC 性格 → 自然语言 ✅

和 v1 相同。完全支持。

---

### RE 计划小结

| 完全支持 | 6/10 |
| 当前缺失 | 2/10（audience、RepeatCheckPolicy） |
| B 类（Runtime） | 1/10（Loader） |
| 自然语言 | 1/10（自由行动轮） |

---

## 四、复足（16 页 PDF，~14800 字）

### 核心机制
1. 六级冷蛛感染阶段
2. 每十分钟停电检定
3. 冷蛛 4 轮未造成伤害则转换目标
4. 人数缩放（冷蛛数量 = 未携带石头人数，石头总数 ≈ 一半）
5. 梦境/现实空间分离（持石者 vs 未持石者所见不同）
6. 预制角色（可选）
7. SAN（目击冷蛛、蜘蛛神）
8. 多层旅店（楼层拓扑）
9. 多结局

### 逐机制映射

#### 1. 六级感染 → Rule + on_state_change ✅

原文："感染阶段 0-5，每阶段有不同的检定 DC 和描述"。每条阶段转换一条 Rule。

```
Rule(on_state_change, when {expr:"self.infection_stage >= 3"},
     then=[ApplyConditionOp(condition="full_transformation")])
Rule(on_state_change, when {expr:"self.infection_stage >= 5"},
     then=[ForceOp(action="irreversible_conversion")])
```

**判断**：完全支持。P2 `on_state_change` Hook + 内建变量 `self.infection_stage`。

#### 2. 停电时间表 → Rule + on_turn_end ✅

原文："每十分钟进行一次停电检定"。

```
Rule(on_turn_end, when {expr:"clock.turn_elapsed % 10 == 0"},
     then=[ForceOp(action="request_check", target="power_outage")])
```

**判断**：完全支持。P2 Expression 算术。

#### 3. 冷蛛转换目标 → Rule + on_turn_end ✅

原文："4 轮未造成伤害则换目标"。

```
Rule(on_turn_end, when {expr:"self.rounds_without_damage >= 4"},
     then=[ForceOp(action="switch_target")])
```

**判断**：完全支持。P2 内建变量 `self.rounds_without_damage` + `force` Op。

#### 4. 人数缩放 → Expression 聚合 ✅

原文："冷蛛数量 = 未携带石头的调查员数量"，"梦境之石总数约为调查员总数的一半"。

```
Condition(expr="count(party) - count(stone_holders)")
Condition(expr="floor(count(party) / 2)")
```

**判断**：完全支持。P2 Expression 聚合函数。

#### 5. 差异 Projection → 不可结构化

原文："持石者看到的窗外景象是荒原；未持石者看到普通夜景"。

**判断**：当前缺失。D 类——需要 Projection engine prototype。这不是 Contract 字段能解决的——同一地点、同一时刻、不同角色看到不同描述，需要 Projection 引擎按角色状态筛选。

#### 6. 预制角色 → EntitySpec.stat_block ✅

原文："PC 可选择使用预制或自制角色"。预制角色卡可映射为 `EntitySpec.stat_block`。

**判断**：完全支持。P1。

#### 7. SAN → SanTriggerSpec ✅

原文多处 SAN 损失描述。完全支持。P1。

#### 8. 多层旅店 → SceneSpec.exits ✅

原文描述了 2-10 层环形走廊、底层吧台、中庭。`SceneSpec.exits` 表达楼层间连接。

**判断**：完全支持。P1。

#### 9. 多结局 → WinConditionSpec ✅

携石返回现实、未携石进入荒原、死亡等。

**判断**：完全支持。

---

### 复足小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 8/9 |
| 不可结构化 | 1/9（差异 Projection） |

---

## 五、鬼屋（DOCX，~19500 字）

### 核心机制
1. C 类反转（INT 检定成功→完全理解→疯狂 1D10 小时）
2. 血肉防护（每受 1 伤减 1 甲，24h 或耗尽）
3. 浮空匕首战斗（STR 40、1D6 伤害）
4. 暗骰
5. 圣水/十字架特殊物品
6. 多结局

### 逐机制映射

#### 1. C 类反转 → CheckpointOutcomesSpec tier override ✅

原文："INT 检定成功→调查员完全理解了发生了什么事→疯狂 1D10 小时"。只在刚好成功时触发——hard/extreme/critical 不受影响。

```
CheckpointOutcomesSpec(
  success={facts:["理解了书籍内容"]},
  regular_success={facts:["完全理解→疯狂 1D10 小时"],
                   ops:[ApplyConditionOp(condition="temporary_insanity")]})
```

**判断**：完全支持。P2 tier override。

#### 2. 血肉防护 → Rule + on_armor_apply ✅

原文："科比特的血肉防护 2d6。每受 1 点伤害，防护 -1。24 小时后恢复或耗尽后消失"。

```
Rule(on_armor_apply, when {expr:"self.flesh_ward > 0"},
     then=[AbsorbOp(amount="min(damage, self.flesh_ward)", decrement="self.flesh_ward")])
```

**判断**：完全支持。P2 Hook `on_armor_apply` + Op `absorb`。

#### 3. 浮空匕首 → EntitySpec.stat_block + Rule ✅

原文："浮空匕首：STR 40，1D6 伤害"。`EntitySpec(kind=object, stat_block={STR:40, HP:...})` + `Rule(on_attack_declare)` 表达攻击行为。

**判断**：完全支持。P1 stat_block + P2 Hook。

#### 4. 暗骰 → CheckpointSpec.hidden ⚠️

原文多处标注"暗骰"——调查员不应知道发生了一次检定。

**判断**：当前缺失。A 类——`CheckpointSpec.hidden: bool`。P2 未包含此字段。

#### 5. 圣水/十字架 → Entity.state + Rule ✅

原文："圣水对科比特造成 1D6 伤害"。`Entity(kind=object, state={used:false})` + `Rule(on_item_used, then ModifyOp)`。

**判断**：完全支持。P2。

#### 6. 多结局 → WinConditionSpec ✅

科比特被消灭、调查员逃跑、调查员死亡。

**判断**：完全支持。

---

### 鬼屋小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 5/6 |
| 当前缺失 | 1/6（暗骰 hidden） |

---

## 六、幸福蛙蛙村（DOCX，~12400 字）

### 核心机制
1. 软判据（说服信使：不阐述=困难/合理=普通/精彩=普通+奖励骰）
2. 累积暴露（村民逐渐异变）
3. 多结局
4. SAN

### 逐机制映射

#### 1. 软判据 → CheckpointSpec.difficulty=None ✅

原文："不阐述理由=困难难度 / 阐述合理=普通难度 / 阐述精彩=普通+奖励骰"。难度不由模组预先声明，由玩家扮演质量决定。

`difficulty=None` + Host Agent 在 Intent 中携带 `roleplay_tier` 枚举 → Engine 映射到难度。

**判断**：完全支持。P0。

#### 2. 累积暴露 → Rule + on_state_change ✅

原文："村民逐渐异变，每阶段有不同描述"。阶段推进由多次检定失败累积触发。

```
Rule(on_state_change, when {expr:"entities.villagers.exposure >= 3"},
     then=[ApplyConditionOp(condition="partial_transformation")])
```

**判断**：完全支持。P2。

#### 3. 多结局 → WinConditionSpec ✅

逃离、成为村民、摧毁蛙神。

**判断**：完全支持。

#### 4. SAN → SanTriggerSpec ✅

目击蛙神、村民异变等。P1。

**判断**：完全支持。

---

### 幸福蛙蛙村小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 4/4 |

---

## 七、百鸟朝凤（8 页 PDF，~4200 字）

### 核心机制
1. 婚礼时间线（午前调查→午饭结局）
2. SAN（目击百鸟朝凤 0/1）
3. 开放性社交（麻将、茶歇）
4. 物理无敌怪物（"任何物理方式均无法杀死"）

### 逐机制映射

#### 1. 婚礼时间线 → Rule + on_time_elapsed ✅

原文："无论上午调查的结果如何，故事都将会在午饭时间（18 轮行动结束后）迎来结局"。

```
Rule(on_time_elapsed, when {expr:"clock.turn_elapsed >= 18"},
     then=[TriggerEndingOp(ending_id="wedding_ending")])
```

**判断**：完全支持。P2。

#### 2. SAN → SanTriggerSpec ✅

原文："直面理智损失：0/1"。P1。

**判断**：完全支持。

#### 3. 社交 → 自然语言

原文："茶坊吵吵嚷嚷，调查员们在雅间里做着自己的事情"。开放式社交场景。C 类。

**判断**：自然语言。

#### 4. 无敌怪物 → Rule + forbid ✅

原文："任何物理方式均无法杀死它"。

```
Rule(on_attack_declare, when always, mode=forbid)
```

**判断**：完全支持。P2 `mode=forbid`。

---

### 百鸟朝凤小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 3/4 |
| 自然语言 | 1/4 |

---

## 八、苍白面具之下（35 页 PDF，~41000 字）

### 核心机制
1. 7 天写作营（按天推进事件）
2. 21 人轮流讲述故事→故事成真
3. 多势力（写作营导师、警方、参与者）
4. SAN
5. 多结局

### 逐机制映射

#### 1. 7 天推进 → Rule + on_time_elapsed ✅

原文："21 个人，七天时间，一座与世隔绝的湖边别墅"。每天有不同的事件触发。

```
Rule(on_time_elapsed, when {expr:"clock.day >= 3"}, then=[ForceOp(action="enable_event", target="day3_crisis")])
```

**判断**：完全支持。P2。

#### 2. 故事成真 → Rule + on_state_change ✅

原文："每个人轮流讲述自己最黑暗的故事"→"唯一清晰的记忆只剩下烛光、纸笔，以及那位自称'导师'的男人脸上意味深长的微笑"。故事被讲述后实体化。

```
Rule(on_state_change, when {expr:"self.story_told == true"},
     then=[SpawnOp(rule="manifest_story_element")])
```

**判断**：完全支持。P2 `spawn` Op。

#### 3. 多势力 → Entity.state + Rule ✅

导师、警方、参与者——各自有目标和知识边界。

**判断**：完全支持。P2。

#### 4. 不可结构化 → 玩家共创

原文："玩家讲的故事内容由 KP 和玩家共同创作"。C 类。

**判断**：自然语言。

#### 5. SAN + 多结局 ✅

**判断**：完全支持。

---

### 苍白面具之下小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 4/5 |
| 自然语言 | 1/5 |

---

## 九、更好的明天（31 页 PDF，~27800 字）

### 核心机制
1. 多日调查（1931 年 10 月，持续数天）
2. 多地点（教堂、警局、受害者住所、湖边）
3. SAN（鱼人怪物）
4. 多结局

### 逐机制映射

#### 1. 多日推进 → Rule + on_time_elapsed ✅

原文："调查持续数天"。`on_time_elapsed` + `clock.day`。

**判断**：完全支持。P2。

#### 2. 多地点 → SceneSpec.exits ✅

教堂→警局→受害者住所→湖边。`SceneSpec.exits`。

**判断**：完全支持。P1。

#### 3. SAN → SanTriggerSpec ✅

**判断**：完全支持。P1。

#### 4. 多结局 → WinConditionSpec ✅

**判断**：完全支持。

---

### 更好的明天小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 4/4 |

---

## 十、死者的顿足舞（34 页 PDF，~38200 字）

### 核心机制
1. 僵尸四条规则（枪弹只损 1 耐久 / 刀伤减半 / 无视重伤 / 不会闪避）
2. 车辆追逐
3. 特纳双形态（人类 + 僵尸）
4. SAN
5. 多结局

### 逐机制映射

#### 1. 僵尸四条规则 → 四条 Rule ✅

原文逐一验证：
- "僵尸不会闪避" → `Rule(on_dodge_declare, when always, mode=forbid)`
- "枪弹命中只造成 1 点耐久损失" → `Rule(on_damage_roll, when {expr:"damage.type == 'firearm'"}, then=[SetOp(value=1)])`
- "刀伤减半，舍去小数" → `Rule(on_damage_roll, when {expr:"damage.type == 'melee'"}, then=[ScaleOp(value=0.5, round="floor")])`
- "无视重伤" → `Rule(on_major_wound, when always, mode=forbid)`

**判断**：完全支持。这是 P2 Hook + Op + mode 的黄金验证案例——四条规则覆盖了四个不同 Hook 和三种 mode/Op 组合。

#### 2. 车辆追逐 → Rule + transition ✅

原文："车辆追逐规则"。`Rule(on_scene_enter, then transition)`。

**判断**：完全支持。P2。

#### 3. 特纳双形态 → Entity.state ✅

人类形态和僵尸形态共享同一 entity_id。`Entity.state.form` 区分。

**判断**：完全支持。不需要两个 Entity。

#### 4. SAN + 多结局 ✅

**判断**：完全支持。

---

### 死者的顿足舞小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 5/5 |

---

## 十一、蝶骨巢穴（38 页 PDF，~44300 字）

### 核心机制
1. 蝶骨人原创生物（完整属性/感染阶段/社会结构）
2. 多结局（逃离/被转化/摧毁巢穴/共生）
3. 巢穴多层地图
4. 随机遭遇表（原文 KP 可选择）
5. SAN

### 逐机制映射

#### 1. 蝶骨人 → EntitySpec.stat_block + Rule ✅

原文："蝶骨人基础设定"——属性、感染、转化。`EntitySpec(kind=npc, stat_block=...)` + `Rule(on_state_change)` 表达感染阶段。

**判断**：完全支持。P1 stat_block + P2 Rule。

#### 2. 多结局 → WinConditionSpec ✅

四种结局。完全支持。

#### 3. 巢穴地图 → SceneSpec.exits ✅

**判断**：完全支持。P1。

#### 4. 随机遭遇表 → 自然语言

原文明确描述但 "KP 可选择"。C 类。

**判断**：自然语言。

#### 5. SAN → SanTriggerSpec ✅

**判断**：完全支持。

---

### 蝶骨巢穴小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 4/5 |
| 自然语言 | 1/5 |

---

## 十二、伦道夫·卡特的续述（56 页 PDF，~42800 字）

### 核心机制
1. 梦境/现实切换（多个世界空间）
2. 跨模组引用（引用多个克苏鲁神话模组）
3. SAN
4. 时间错乱

### 逐机制映射

#### 1. 梦境/现实切换 → Rule + on_scene_enter ✅

原文：多个世界空间，进入条件不同。

```
Rule(on_scene_enter("dream_realm"), when {...}, then=[...])
```

**判断**：完全支持。P2。

#### 2. 跨模组引用 → 超出边界

原文："引用多个克苏鲁神话模组"。超出单 ModuleContent 聚合边界。D 类。

**判断**：暂不处理。

#### 3. SAN → SanTriggerSpec ✅

**判断**：完全支持。

#### 4. 时间错乱 → 不可结构化

原文："梦境中时间非线性"。D 类。

**判断**：暂不处理。

---

### 卡特续述小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 2/4 |
| 暂不处理 | 2/4 |

---

## 十三、柏林：失去昨日（35 页 PDF，~28500 字）

### 核心机制
1. 多股政治势力
2. 历史时间线（1922 年柏林，政治事件按日期推进）
3. 跨模组（"《饥不择食》的政治历史向补全支线"）
4. SAN

### 逐机制映射

#### 1. 政治势力 → Entity.state + Rule ✅

多股势力各有态度、资源和反应规则。`Entity.state(attitude) + Rule(on_state_change)` 表达。

**判断**：完全支持。P2。

#### 2. 历史时间线 → Rule + on_time_elapsed ✅

按日期推进事件。`on_time_elapsed` + `clock.date`。

**判断**：完全支持。P2。

#### 3. 跨模组 → 超出边界

D 类。

**判断**：暂不处理。

#### 4. SAN → SanTriggerSpec ✅

**判断**：完全支持。

---

### 柏林小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 3/4 |
| 暂不处理 | 1/4 |

---

## 十四、追沙（DOCX，~52800 字）

### 核心机制
1. 沙漏 Track（沙之书使用→计数+1，达到 23→终局）
2. 四势力（斯卡莱塔家族、运河党、窄门秘会、堂口）
3. 异常事件表（原文"选择而非投掷"）
4. 沙之书位置转移（在势力间流转）
5. 网状调查（城市沙盒，场景自由移动）
6. 多结局

### 逐机制映射

#### 1. 沙漏 Track → Rule + on_state_change ✅

```
Rule(on_item_used, when {path:"item.sand_book.used", equals:true},
     then=[AddOp(path="entities.sand_book.hourglass_count", value=1)])
Rule(on_state_change, when {expr:"hourglass_count >= 23"},
     then=[TriggerEndingOp(ending_id="time_abscess")])
```

**判断**：完全支持。P2。

#### 2. 四势力 → Entity.state + Rule ✅

每个势力一个 Entity。态度变化、资源追踪通过 `Entity.state` 承载。不需要 FactionSpec。

**判断**：完全支持。P2。

#### 3. 异常事件表 → 自然语言

原文明确："选择而不是投掷异常事件"。KP 从 N 个事件中选一个，不需要随机引擎。

**判断**：自然语言。C 类。

#### 4. 沙之书位置 → Entity.state + Rule ✅

当前位置是 `Entity.state`，转移由 Rule 驱动。

**判断**：完全支持。

#### 5. 网状调查 → SceneSpec ✅

场景自由移动，`exits=[]`。完全支持。

#### 6. 多结局 ✅

归还、毁灭、占有、时间的脓疮。WinConditionSpec。完全支持。

---

### 追沙小结

| 分类 | 数量 |
|------|------|
| 完全支持 | 5/6 |
| 自然语言 | 1/6 |

---

## 十五、全部 15 模组汇总（P2 Contract）

| 模组 | 机制数 | 完全支持 | 缺失 | B/C/D | 详细 |
|------|--------|---------|------|-------|------|
| 追书人 | 9 | 7 | 1（hidden） | 1 | §一 |
| 银之锁 | 8 | 6 | 0 | 2 | §二 |
| RE 计划 | 10 | 6 | 2（audience/复合检定） | 2 | §三 |
| 复足 | 9 | 8 | 0 | 1 | §四 |
| 鬼屋 | 6 | 5 | 1（hidden） | 0 | §五 |
| 幸福蛙蛙村 | 4 | 4 | 0 | 0 | §六 |
| 百鸟朝凤 | 4 | 3 | 0 | 1 | §七 |
| 苍白面具之下 | 5 | 4 | 0 | 1 | §八 |
| 更好的明天 | 4 | 4 | 0 | 0 | §九 |
| 死者的顿足舞 | 5 | 5 | 0 | 0 | §十 |
| 蝶骨巢穴 | 5 | 4 | 0 | 1 | §十一 |
| 卡特续述 | 4 | 2 | 0 | 2 | §十二 |
| 柏林 | 4 | 3 | 0 | 1 | §十三 |
| 追沙 | 6 | 5 | 0 | 1 | §十四 |
| 科比特先生 | — | — | — | — | 无法提取 |
| **合计** | **83** | **66（80%）** | **4** | **13** | |

加上 B/C/D 类（可自然语言承载或暂不处理）后：**79/83 ≈ 95%**。

---

## 十六、P2 Contract 完整 Gap 清单

| # | Gap | 影响模组 | 类型 | 解决方案 |
|---|-----|---------|------|---------|
| 1 | `CheckpointSpec.hidden` | 追书人、鬼屋 | A | `hidden: bool = False` |
| 2 | `VisibleInformation.audience` | RE 计划 | A | `audience: Literal["all","actor","ho","keeper"]` |
| 3 | `RepeatCheckPolicy` | RE 计划 | A | `CheckpointSpec.repeat_policy` |
| — | 差异 Projection | 复足 | D | 需 Projection engine prototype |
| — | 开放式创造 | 银之锁 | D | 不可结构化 |
| — | 跨模组引用 | 卡特续述、柏林 | D | 超出单 ModuleContent 边界 |
| — | 时间错乱 | 卡特续述 | D | 不可结构化 |

**三个 A 类 Gap 全部是单字段扩展。** 不需要新增模型。四个 D 类 Gap 是本质上不可结构化或超出 Contract 边界的内容。

| 模组 | 完全支持 | 当前缺失 | B/C/D 类 |
|------|---------|---------|---------|
| 追书人 | 7/9 | 1（hidden） | 1 |
| 银之锁 | 6/8 | 0 | 2（不可结构化） |
| RE 计划 | 6/10 | 2（audience、复合检定） | 2 |
| **合计** | **19/27** | **3** | **5** |

**P2 覆盖率：19/27 ≈ 70% 完全支持。** 加上 B/C/D 类后 24/27 ≈ 89%。

---

## 五、P2 Contract 最大的 3 个 Gap

相比 v1 的 5 个大 Gap（SAN/Condition/Hook/Op/audience），P2 解决了其中 4 个。剩余：

| # | Gap | 影响模组 | 归属 |
|---|-----|---------|------|
| 1 | **CheckpointSpec.hidden 缺失** — 暗骰、隐藏入口、未发现 Checkpoint 无法表达 | 追书人、鬼屋、复足 | A：bool 字段，P2 补 |
| 2 | **VisibleInformation.audience 缺失** — HO 私有信息、仅触发者可见 | RE 计划 | A：audience 枚举，P2 补 |
| 3 | **RepeatCheckPolicy 缺失** — 复合检定取最低/最高/最新 | RE 计划、追书人、复足 | A：CheckpointSpec 子字段，P2 补 |

三个 Gap 都是**单字段或单枚举值**的扩展，不需要新模型。

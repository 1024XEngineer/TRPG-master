# P2 Contract 测试：五个新模组验证

> 日期：2026-07-24
> 验证对象：P2 最终 Contract（`module-content-field-decisions.md` §8）
> 测试模组：`示例模组/test/` 下全部五个模组
> 
> 本轮目的：验证 P2 Contract 对之前未分析过的五个模组能否正确表达。**不是**修改 Contract，**不是**重新设计，**不是**比较谁更好——只是拿五个新模组跑一遍 P2 Contract，记录哪些能表达、哪些不能。

---

## 一、异父——教父主题 CoC 模组（~58000 字）

### 模组特征

1945 年纽约，黑手党家族底层打手。柯里昂家族 vs 塔塔利亚家族 vs 巴齐尼家族的势力斗争。线性推进为主，任务驱动。包含：势力关系、暗骰、SAN、战斗、多结局。

### 机制映射

| 机制 | P2 表达 | 判断 |
|------|--------|------|
| 三大家族势力 | `Entity.state(attitude) + Rule(on_state_change)` — P2 | ✅ |
| 势力地盘（哪里有我们的眼线、哪里不能去） | `SceneSpec.content` 自然语言描述 | ✅ |
| 暗骰（多处标注） | `CheckpointSpec.visibility(audience="keeper")` | ✅ |
| SAN（目击神话存在） | `Rule + ModifyOp` 修改角色属性 — P2 | ✅ |
| 绝对禁止的生意（毒品=铁律） | `Entity.refuse_ops=["sell_drugs", "use_drugs"]` — 当前已有 | ✅ |
| 沉默法则（Ometà） | 自然语言，Host Agent 处理 | C 类 |
| 多结局 | `WinConditionSpec` | ✅ |
| 克莱门扎、桑尼、汤姆等 NPC 网络 | `EntitySpec` 多实体 + `Entity.state` 关系追踪 | ✅ |

**小结**：6/7 完全支持。沉默法则是 RP 约束，不需要结构化。

---

## 二、极限绷住——荒诞恐怖喜剧（~25500 字）

### 模组特征

1925 年纽约州金曦庄园。奶龙病毒（熵增频率，看到并笑出来的人感染）。**贯穿全程的特殊机制**：狂笑时刻——三个难度的意志判定。非线性场景式结构，多条信息获取路径导向不同结局。存在特殊物品：《了不起的盖茨比》手稿复印本（阅读可抑制感染症状）。画作《贪婪》被烧毁→所有狂笑症状终止。

### 机制映射

| 机制 | P2 表达 | 判断 |
|------|--------|------|
| 狂笑时刻（三级难度意志判定） | `CheckpointSpec` 三个独立 Checkpoint（普通/困难/极限），各自 declaration | ✅ |
| 奶龙病毒感染（看到→笑→感染→笑欲加重→窒息而死） | `Rule(on_state_change, when self.infection_stage>=N)` — P2 Track via Rule | ✅ |
| 《了不起的盖茨比》抑制感染 | `Entity(kind=object, state={read:false})` + `Rule(on_read, then ModifyOp(self.infection_stage, -1))` | ✅ |
| 画作烧毁→症状终止 | `Rule(on_state_change, when entities.painting.destroyed==true, then ApplyConditionOp("symptoms_terminated"))` | ✅ |
| 非线性场景（调查员可能跳过某些线索） | `SceneSpec.exits=[]`（自由移动）+ 多条 Checkpoint 路径 | ✅ |
| 格赫罗斯（外神背景） | `EntitySpec.secrets` 自然语言 | ✅ |
| 日全食激活力量（特定时间触发） | `Rule(on_time_elapsed, when clock.date=="1925-01-24")` — P2 | ✅ |
| SAN 损失（目击奶龙、目睹狂笑致死） | `Rule + ModifyOp` — P2 | ✅ |

**小结**：8/8 完全支持。极限绷住的三个特殊机制（狂笑三级判定、病毒感染阶段、物品抑制效果）全部分别由 P2 的 CheckpointSpec（三级难度声明）、Rule + on_state_change（Track）、Rule + on_read（物品效果）覆盖。

---

## 三、校园黑色怪谈——高中校园调查（~34000 字）

### 模组特征

现代中国古城中学，奈亚拉托提普教团渗透。非线性调查，多结局。包含：校园七大怪谈、暗骰、SAN、战斗、教师蛊惑状态、隐修堂调查员被杀、地下密室、传教士历史、附录多个结局。

### 机制映射

| 机制 | P2 表达 | 判断 |
|------|--------|------|
| 七大怪谈（十三阶梯/人体模型/音乐教室回音等） | `SceneSpec` 七个场景 + 各自 `CheckpointSpec` | ✅ |
| 教师被蛊惑状态（"大多数教师都或多或少接受了奈亚拉托提普的诱惑"） | `Entity.state(corrupted: bool)` + `Rule(on_state_change)` | ✅ |
| 地下密室 | `SceneSpec` + `CheckpointSpec.visibility(requires_discovery=true)` — P2 | ✅ |
| 隐修堂调查员被杀（尸体埋在花坛） | `InformationItem` + `InformationAcquisition`（调查花坛→发现尸体→获得真相）— 当前用自然语言 | ⚠️ 信息链可表达但事实/线索分离需 P2 InformationItem |
| 多结局（附录 i） | `WinConditionSpec` | ✅ |
| SAN（目击奈亚拉托提普相关存在） | `Rule + ModifyOp` — P2 | ✅ |
| 非线性调查（"并非要求玩家做到十全十美，不同选择造就不同结局"） | `SceneSpec.exits=[]` + 多条 Checkpoint 路径 | ✅ |
| 传教士历史（"半个多世纪前的诡异事件"） | `ModuleFrame.keeper_background` 或 `SceneSpec.content` 自然语言 | ✅ |
| 暗骰 | `CheckpointSpec.visibility(audience="keeper")` | ✅ |

**小结**：8/9 完全支持。隐修堂调查员→尸体→真相的信息链在当前 Contract 中用自然语言可承载，但 Fact/Clue 的结构化分离需 P2 InformationItem。

---

## 四、芒卡的巧克力工厂——查理与巧克力工厂 CoC 改编（~7700 字）

### 模组特征

1926 年阿卡姆郊外。单次会话短模组，2-6 名玩家。**巧克力维度**（类似幻梦境）。**"纯粹的想象"技能**——调查员可以用想象力创造物品。董事长=界外幽鬼，宗帕-隆帕=食肉原住民，被奴役的儿童。大量理智损失。**需要修改理智规则允许完全疯狂的角色继续游戏**。

### 机制映射

| 机制 | P2 表达 | 判断 |
|------|--------|------|
| "纯粹的想象"技能（创造物品） | 不可结构化——开放式创造，无封闭 Outcome 集合 | D 类 |
| 巧克力维度（异维度空间） | `SceneSpec` 多个场景 + `Rule(on_scene_enter, when location=="chocolate_dimension")` | ✅ |
| 董事长=界外幽鬼 | `EntitySpec(secrets=...)` 自然语言 | ✅ |
| 道罗斯化身（图书馆） | `EntitySpec` + `SceneSpec("library")` | ✅ |
| 紫外线视力（戴护目镜/吃紫罗兰巧克力后可见董事长） | `Entity.state(uv_vision: bool)` + `Rule(on_item_used)` — P2 | ✅ |
| 合同签署（"骗人签协议"） | `CheckpointSpec`（社交对抗） + `Entity.state(contract_signed: bool)` | ✅ |
| 理智损失（大量） | `Rule + ModifyOp` — P2 | ✅ |
| 挖掉眼珠保持理智 | `CheckpointSpec` + `Rule(on_action, then ModifyOp)` | ✅ |
| 疯狂角色继续游戏（HOUSE RULE） | **超出 P2 Contract 范围**——这是 Ruleset 的修改，不是模组声明 | B 类 |

**小结**：6/8 完全支持。"纯粹的想象"技能和"疯狂继续游戏"超出 Contract 范围（D 类 + B 类）。

---

## 五、停滞之水——1924 年广州历史 CoC 模组（~28000 字）

### 模组特征

1924 年 7 月广州，黄埔军校时期。深潜者教团 + 克苏鲁降临仪式。高和罗夫（苏联顾问）被擒，调查员需在各方势力中寻找他。包含：广州七区详细设定（各区的商品/武器/服务可用性）、多势力（黄埔军校/旧军队/深潜者教团/沙面殖民者/广州商团）、仪式倒计时、深潜者变形（变成高和罗夫的样子）、历史背景。

### 机制映射

| 机制 | P2 表达 | 判断 |
|------|--------|------|
| 广州七区（各区的商品/武器/服务差异） | `SceneSpec` 七个场景 + `SceneSpec.content` 描述各区的可用资源 | ✅ |
| 多势力（黄埔军/旧军/深潜者/殖民者/商团） | `Entity.state(attitude) + Rule(on_state_change)` — P2 | ✅ |
| 仪式倒计时（"仅在高和罗夫失联 24 小时后"） | `Rule(on_timer_expired + schedule)` — P2 audit | ✅ |
| 深潜者变形（变成高和罗夫样子扰乱视听） | `Entity.state(form: "human"|"deep_one")` + `Rule(on_state_change)` | ✅ |
| 克苏鲁精神力量侵染（缓慢腐烂） | `Rule(on_time_elapsed)` — 长期被动效果 | ✅ |
| 卡斯伯特=不朽深潜者（千年身份） | `EntitySpec(secrets=...)` 自然语言 | ✅ |
| 高和罗夫转化（作为仪式祭品） | `Entity.state(transformation_stage)` + `Rule(on_state_change)` — Track via Rule | ✅ |
| 各势力组织搜索队伍（24 小时倒计时） | `Rule(schedule, timer_id="search_teams", delay=24h)` | ✅ |
| 气候机制（"广州 7 月气候极其湿热"） | `SceneSpec.content` 自然语言——环境描述 | ✅ |
| 各区枪械购买限制 | `Entity.refuse_ops` + `Rule(on_interact, Condition)` — 条件化访问 | ✅ |

**小结**：10/10 完全支持。停滞之水是五个模组中 P2 表达力最强的——七个区的地理限制、多势力关系、仪式倒计时、深潜者变形全部由 P2 的现有能力覆盖。

---

## 六、汇总

| 模组 | 机制数 | 完全支持 | 缺失/暂不处理 |
|------|--------|---------|-------------|
| 异父 | 7 | 6 | 1（沉默法则 C 类） |
| 极限绷住 | 8 | 8 | 0 |
| 校园黑色怪谈 | 9 | 8 | 1（信息链需 P2 InformationItem） |
| 芒卡的巧克力工厂 | 8 | 6 | 2（纯粹想象 D 类 + 疯狂继续 B 类） |
| 停滞之水 | 10 | 10 | 0 |
| **合计** | **42** | **38（90%）** | **4** |

---

## 七、P2 Contract 暴露的新问题

五个模组中，**没有发现需要新增领域对象的 Gap**。所有可表达机制均由 P2 现有 Contract 覆盖。

三个暴露了 P2 现有已知 Gap（非新问题）：

| Gap | 触发模组 | P2 状态 |
|-----|---------|--------|
| InformationItem/InformationAcquisition 结构化 | 校园黑色怪谈（隐修堂→尸体→真相链） | P2 Defer，等 KnowledgeState consumer |
| 开放式创造（"纯粹想象"技能） | 芒卡的巧克力工厂 | D 类，不可结构化 |
| House Rule 修改（"疯狂继续游戏"） | 芒卡的巧克力工厂 | B 类，属于 Ruleset 修改 |

**P2 Contract 通过了五个新模组的盲测。** 没有暴露需要新增顶层集合、新增 Hook、新增 Op 的需求。

# Agent 系统实施与三人协作计划

> **文档定位**：在已有 Agent 总体架构的基础上，明确 MVP 的开工顺序、三人分工、协作接口、第一阶段交付物与验收标准。
>
> **适用阶段**：项目启动、MVP 第一阶段开发与日常集成。
>
> **核心结论**：不要一开始让三个人各自独立完成一个 Agent。
> 三人应先共同确定一个 Demo 模组、三个核心数据协议和一条端到端工作流；
> 随后以人工模组和假引擎跑通纵向闭环，再按“运行时主持 Agent、
> 确定性引擎、模组数据与解析审查”三个长期方向并行开发，
> 并逐步用真实模块替换假模块。

---

## 1. 当前阶段最重要的目标

团队当前最大的风险不是“某个 Agent 写不出来”，而是三个部分分别完成后无法对接：

```text
模组解析结果
→ 主持 Agent 不知道如何读取
→ 主持 Agent 输出的动作
→ 引擎不知道如何执行
→ 引擎返回的结果
→ 主持 Agent 无法可靠叙述
```

因此，第一阶段不以“完成三个 Agent”为目标，而以跑通一条最小端到端链路为目标。

```text
玩家输入
→ 主持 Agent 生成 Intent
→ 引擎执行动作并更新状态
→ 引擎返回 ActionResult
→ 主持 Agent 生成忠于结果的回复
```

只要这条链路能够稳定运行，现有架构就得到了第一次有效验证。后续的模组解析、复杂规则、多场景和多 Agent 拆分，都可以在这条链路上逐步扩展。

---

## 2. MVP 最小范围

第一个版本不要尝试实现完整的 COC 主持系统。建议只支持一个固定的小场景，并限制内容和规则范围。

### 2.1 内容范围

- 1 个固定场景；
- 1～2 个 NPC；
- 2～3 个可交互物体；
- 普通对话与调查；
- 1 种属性或技能检定；
- 1 条特殊规则；
- 1 个关键状态；
- 1 个简单结局。

### 2.2 推荐 Demo：书房调查

```text
玩家进入书房
→ 可以和管家对话
→ 可以调查书架
→ 调查成功后发现钥匙
→ 使用钥匙打开柜子
→ 获得关键文件
→ 触发结局
```

建议包含以下元素：

| 类型 | 内容 |
| --- | --- |
| 场景 | 书房 |
| NPC | 管家 |
| 可交互实体 | 书架、钥匙、柜子、关键文件 |
| Checkpoint | 调查书架 |
| 关键状态 | `has_key`、`has_document` |
| 特殊规则 | 没有钥匙时不能正常打开柜子 |
| 结局条件 | 玩家获得关键文件 |

### 2.3 最小闭环必须覆盖

- 自由对话；
- Checkpoint 检定；
- 状态变更；
- Rule 触发；
- 结局判断；
- 最终叙事；
- EventLog 记录。

### 2.4 第一里程碑演示

```text
玩家：我仔细调查书架。

主持 Agent：
生成 `investigate` Intent。

确定性引擎：
执行调查检定，更新 has_key，写入 EventLog，返回 ActionResult。

主持 Agent：
你拨开积灰的书册，在书架后方摸到了一把冰凉的小钥匙。
```

这个演示能够成功且结果一致，就是第一阶段最有价值的里程碑。

---

## 3. 推荐实施策略

### 3.1 不要先接真正的模组解析

长期架构包含：

```text
模组解析 Agent
→ 导入审查 Agent
→ 主持编排 Agent
```

但实现顺序不建议从模组解析 Agent 开始。解析结果最终必须被运行时消费；如果运行时还没有成形，就无法判断解析 Agent 输出的数据是否真正有用。

更稳妥的顺序是：

1. 人工编写一份标准模组 JSON；
2. 让运行时 Agent 和引擎读取这份 JSON；
3. 跑通完整游戏流程；
4. 再让解析 Agent 自动生成同结构的 JSON；
5. 最后增加导入审查 Agent。

这相当于：

> 先手写“标准答案”，验证系统是否会使用；再让 AI 自动生成这份标准答案。

### 3.2 始终保持系统可运行

第一阶段允许部分模块是 Mock，但主链路必须持续可运行：

```text
人工 Demo 模组
→ 主持 Agent
→ 假引擎
→ 主持 Agent 回复
```

之后逐步替换：

```text
假引擎
→ 真骰子
→ Checkpoint
→ 状态变更
→ EventLog
→ Hook / Rule
→ WinCondition
```

不要等三个人分别做完全部模块后再进行第一次集成。

---

## 4. 三人分工

建议每个人有清晰的长期主责，但共同参与接口设计和每日集成。

| 成员   | 主责方向               | 核心产出                        |
| ---- | ------------------ | --------------------------- |
| 成员 A | 主持编排 Agent 与运行时工作流 | 玩家输入到最终回复的主链路               |
| 成员 B | 确定性规则引擎与状态系统       | 检定、规则、状态、日志与结局              |
| 成员 C | 模组数据、解析审查与质量评测     | 标准模组、解析 Agent、审查 Agent 与评测集 |

### 4.1 成员 A：主持编排 Agent 与运行时工作流

#### 成员 A 的主要职责

```text
玩家输入
→ 读取当前场景和角色状态
→ 判断自由叙事还是规则行为
→ 生成 Intent
→ 组装 EngineRequest 并调用引擎
→ 读取 ActionResult
→ 生成玩家回复
```

具体负责：

- 主持 Agent 的 system prompt；
- 运行时上下文组装；
- 玩家意图识别；
- 动作类型 Schema；
- Checkpoint 匹配；
- 工具调用；
- 引擎前后两个阶段的调用流程；
- 最终旁白与 NPC 对话生成；
- 防止 Agent 擅自改写引擎结果；
- 自由叙事与规则行为的路由判断。

建议主要维护：

```text
collaboration_framework/agents/runtime_host.py
collaboration_framework/workflow.py
prompts/
schemas/intent.schema.json
schemas/narration-output.schema.json
```

#### 成员 A 的第一阶段交付物

- 玩家输入能够转换为最小 `Intent`；
- 能根据 `Intent` 进入澄清、直接叙事或引擎分支；
- 能调用假引擎；
- 能根据模拟 `ActionResult` 生成回复；
- 引擎判定失败时，叙事不会擅自写成成功。

### 4.2 成员 B：确定性规则引擎与状态系统

#### 成员 B 的主要职责

```text
EngineRequest
→ 流水线执行
→ Rule 求值
→ 状态校验
→ GameState 更新
→ EventLog 写入
→ 生成 ActionResult
```

具体负责：

- 检定流水线；
- 骰子系统；
- Hook 机制；
- `when` 表达式求值；
- `then` / `op` 执行；
- Rule priority；
- GameState；
- EventLog；
- WinCondition；
- 房间隔离；
- 状态修改白名单；
- `refuse_ops`；
- invariant 校验。

建议主要维护：

```text
collaboration_framework/engine/atomic.py
collaboration_framework/engine/pipelines/  # 后续拆分
collaboration_framework/engine/rules/      # 后续拆分
collaboration_framework/engine/state/      # 后续拆分
collaboration_framework/engine/events/     # 后续拆分
schemas/action-result.schema.json
```

#### 成员 B 的第一阶段交付物

- 提供可被成员 A 调用的假引擎接口；
- 实现最简单的检定；
- 实现 GameState 状态修改；
- 写入 EventLog；
- 返回最小 `ActionResult`。

> 成员 B 当前不直接开发 Agent，但确定性引擎是整个 Agent 系统的规则地基。

### 4.3 成员 C：模组数据、解析审查与质量评测

#### 前期职责

运行时链路尚未稳定时，先不急于开发完整解析 Agent，优先人工整理标准 Demo 数据。

具体负责：

- World / ModulePack / Scene 数据结构；
- Entity / Checkpoint / WinCondition；
- 测试模组的人工标注；
- `demo-module.json`；
- Demo 输入与预期结果；
- JSON Schema 校验；
- Agent 测试样例；
- 评测集与错误分类。

#### 后期职责

运行时能够稳定消费 `demo-module.json` 后，再实现：

```text
模组原文
→ 模组解析 Agent
→ ModuleContent JSON
→ 导入审查 Agent
```

建议主要维护：

```text
content/
collaboration_framework/modules/validation.py
collaboration_framework/agents/module_parser.py   # 后续 Agent
collaboration_framework/agents/module_reviewer.py # 后续 Agent
fixtures/
evals/
```

#### 成员 C 的第一阶段交付物

- 人工编写 `demo-module.json`；
- 准备 10～20 条测试输入及预期输出；
- 实现 JSON Schema 校验；
- 开始最小 Entity / Checkpoint 提取实验。

---

## 5. 三人必须共同确定的内容

三个人可以分别承担模块主责，但以下内容必须共同讨论并定稿。

### 5.1 三个核心数据协议

第一天共同确定：

```text
ModuleContent
Intent / EngineRequest
ActionResult
```

它们分别对应三个人之间的接口：

| 协议 | 解决的问题 | 主要生产方 | 主要消费方 |
| --- | --- | --- | --- |
| ModuleContent | 场景、实体、规则、检定和结局如何表示 | 成员 C | 成员 A、B |
| Intent / EngineRequest | 主持 Agent 如何提议动作，编排层如何注入可信执行上下文 | 成员 A / 编排层 | 成员 B |
| ActionResult | 引擎如何告诉主持 Agent 最终发生了什么 | 成员 B | 成员 A |

如果这三个协议没有提前确定，三个人很容易分别实现三套互不兼容的数据结构。

### 5.2 一个统一的测试场景

三个人共同维护：

```text
fixtures/demo-module.json
fixtures/demo-cases.json
```

所有模块都以同一份 Demo 数据测试，以便持续检查：

- 模组数据能否被运行时读取；
- Intent 能否被组装为 EngineRequest 并由引擎执行；
- 引擎结果能否被 Agent 正确叙述；
- 状态变化和 EventLog 是否一致；
- 结局条件是否按预期触发。

### 5.3 一份统一术语表

建议创建 `docs/glossary.md`，至少明确以下术语：

```text
Action
Checkpoint
Pipeline
Hook
Rule
Op
GameState
Event
Outcome
Narration
```

尤其需要避免“事件”一词被不同成员分别用来表示玩家动作、EventLog 或剧情节点。

---

## 6. 三个核心 Schema 的最小版本

第一版只定义闭环所需的最小字段，不要一次实现完整架构文档中的所有能力。

### 6.1 最小 ModuleContent

```json
{
  "module_id": "study-demo",
  "version": "0.1.0",
  "world_ref": "coc-7e",
  "scenes": [],
  "entities": [],
  "checkpoints": [],
  "win_conditions": []
}
```

这段示例必须与 Pydantic `ModuleContent` 及其自动生成的
`schemas/module-content.schema.json` 同步。当前契约没有顶层 `rules`；模组实体规则
放在 `Entity.rules`。Pydantic Model 是输入事实源，生成的 Schema 是 JSON 校验产物，
两者都不由文档示例反向定义。

### 6.2 最小 Intent / EngineRequest

```json
{
  "execution": "engine",
  "kind": "interact",
  "action": "investigate",
  "target": {"matched": true, "id": "bookshelf"},
  "check": {
    "route": "module",
    "checkpoint_id": "investigate_bookshelf",
    "proposed_skills": ["spot_hidden"]
  },
  "narrative_intent": "仔细检查书架",
  "clarification_question": null
}
```

`execution=narrative|engine` 决定是否调用引擎；`check.route=none|module|default`
只表达检定来源。无检定的合法世界动作使用 `execution=engine + check.route=none`。

编排层不让模型生成可信身份，而是组装如下信封：

```text
EngineRequest
  player_input: PlayerInput
  intent: Intent
```

### 6.3 最小 ActionResult

```json
{
  "success": true,
  "resolution": "checkpoint",
  "confirmed_facts": [
    "玩家发现了一把钥匙"
  ],
  "state_changes": [
    {
      "path": "pc_1.has_key",
      "from": false,
      "to": true,
      "cause": "checkpoint:investigate_bookshelf"
    }
  ],
  "player_visible_information": [
    "书架后藏着一把小钥匙"
  ],
  "narration_constraints": ["必须明确玩家已经发现钥匙"],
  "next_required_action": null,
  "events": [],
  "state_version": 1
}
```

第一阶段先验证三个 JSON 能完整流转，再逐步增加：

- `subactions`；
- `proposed_ops`；
- `roll_results`；
- `events`；
- `hidden_information`；
- `narration_constraints`；
- `next_required_action`。

---

## 7. 推荐仓库结构

```text
project/
├── collaboration_framework/
│   ├── agents/
│   │   ├── runtime_host.py
│   │   ├── module_parser.py       # 后续 Agent
│   │   └── module_reviewer.py     # 后续 Agent
│   ├── engine/
│   │   ├── atomic.py
│   │   ├── pipelines/             # 后续拆分
│   │   ├── rules/                 # 后续拆分
│   │   ├── state/                 # 后续拆分
│   │   └── events/                # 后续拆分
│   ├── modules/
│   │   └── validation.py
│   ├── contracts.py
│   ├── ports.py
│   └── workflow.py
│
├── docs/
│   ├── agent-architecture-design.md
│   ├── agent-implementation-team-plan.md
│   ├── data-model.md
│   └── glossary.md
│
├── schemas/
│   ├── module-content.schema.json
│   ├── intent.schema.json
│   ├── engine-request.schema.json
│   ├── action-result.schema.json
│   └── narration.schema.json
│
├── fixtures/
│   ├── demo-module.json
│   └── demo-cases.json
│
├── prompts/
├── evals/
└── tests/
```

第一天不需要实现所有目录中的内容，但目录归属、模块边界和接口位置应先明确。

---

## 8. 推荐开发步骤

### 第 0 步：整理仓库和统一术语

三人共同完成：

- 确定目录结构；
- 确定统一命名；
- 建立 `glossary.md`；
- 明确模块维护人；
- 确认主分支合并和代码评审规则。

### 第 1 步：定义输入输出 Schema

共同定义最小版本：

- `ModuleContent`；
- `Intent / EngineRequest`；
- `ActionResult`。

完成标准：

- 三个 Schema 可以独立校验；
- Demo 示例能够通过校验；
- A、B、C 对每个字段的含义理解一致；
- 暂不使用的字段不提前加入。

### 第 2 步：人工构建 Demo 模组

成员 C 人工编写 `fixtures/demo-module.json`，至少包含：

- 书房场景；
- 管家；
- 书架；
- 钥匙；
- 柜子；
- 关键文件；
- 调查 Checkpoint；
- `has_key`；
- `has_document`；
- 结局条件。

同时编写 10～20 条测试输入及预期结果，例如：

```text
我和管家聊聊。
我观察书架。
我仔细调查书架。
我直接砸开柜子。
我用钥匙打开柜子。
我看看窗外。
```

测试数据既要包含正常路径，也要包含：

- 不需要引擎的自由叙事；
- 需要引擎的规则行为；
- 缺少必要物品的非法操作；
- 检定成功；
- 检定失败；
- 重复调查；
- 结局触发。

### 第 3 步：实现假引擎

成员 B 先提供稳定接口，不必立即实现完整 Rule 系统：

```python
def execute_action(
    request: EngineRequest,
) -> ActionResult:
    ...
```

第一版可以返回固定结果：

```text
inspect_bookshelf
→ success
→ has_key = true
```

这样成员 A 不需要等待完整规则引擎，即可开始接通主持 Agent。

### 第 4 步：跑通主持 Agent 闭环

成员 A 完成：

```text
玩家输入
→ Intent
→ EngineRequest
→ 假引擎
→ ActionResult
→ 玩家回复
```

重点测试两类输入：

#### 自由叙事

```text
我问管家这里最近有没有怪事。
```

预期：不调用规则引擎，直接生成 NPC 对话。

#### 规则行为

```text
我仔细调查书架。
```

预期：生成 Intent，组装 EngineRequest 并调用引擎，再根据 ActionResult 回复。

这个阶段优先保证事实忠实度，而不是追求文采。必须避免：

```text
引擎判定失败
→ Agent 却叙述为成功
```

### 第 5 步：逐步替换为真实引擎

成员 B 按以下顺序加入真实能力：

1. 普通检定；
2. 状态变更；
3. EventLog；
4. WinCondition；
5. 单个 Hook；
6. 单条 Rule；
7. Rule priority；
8. Condition / Ledger 等复杂能力后置。

第一版不要一次实现完整 Condition、Ledger 或所有 Hook。

### 第 6 步：实现模组解析 Agent

运行期能够稳定读取 `demo-module.json` 后，成员 C 再实现：

```text
模组文本
→ 模组解析 Agent
→ 生成与 demo-module.json 同结构的数据
```

第一版只解析 Demo 所需字段：

- Scene；
- Entity；
- Checkpoint；
- Rule；
- WinCondition。

解析结果需要与人工编写的标准答案进行比较，而不是只检查 JSON 是否能够生成。

### 第 7 步：增加导入审查 Agent

导入审查 Agent 的输入：

```text
原始模组文本
+
模组解析 Agent 输出
```

输出应包含：

- 缺失项；
- 错误项；
- 风险项；
- 修改建议。

第一版重点检查：

- A 类：绝对不能做的事情是否遗漏；
- B 类：必然事件是否遗漏；
- C 类：反转后果是否遗漏；
- D 类：关键状态是否落库；
- Rule 是否引用不存在的变量；
- WinCondition 是否引用不存在的 state。

---

## 9. 协作与集成方式

### 9.1 接口驱动开发

成员之间只依赖公开接口，不依赖其他模块的内部实现。

规则引擎接口：

```python
def execute_action(
    request: EngineRequest,
) -> ActionResult:
    ...
```

模组解析接口：

```python
def parse_module(source_text: str) -> ModuleContent:
    ...
```

主持编排接口可以抽象为：

```python
def interpret_action(
    request: InterpretRequest,
) -> Intent:
    ...

def compose_narration(
    request: NarrationRequest,
) -> NarrationOutput:
    ...
```

这些接口先稳定下来，内部可以从 Mock 逐步替换为真实实现。

`run_turn()` 的 `TurnOutput` 是宿主内部聚合结果，不是玩家协议。玩家侧只投影
`NarrationOutput` 和明确允许公开的视图。`SummaryOperation` 作为图外
`SummaryOutbox` 命令消费，只能写非权威摘要存储，不能修改 `GameState` 或追加 Event。

### 9.2 每天至少集成一次主链路

建议每天至少运行一次：

```text
玩家输入
→ Agent
→ Engine
→ Agent 回复
```

即使部分模块仍是 Mock，也要保证主链路始终可演示、可测试。

### 9.3 变更协议时同步更新

任何核心字段变更，必须同时更新：

- JSON Schema；
- Demo 数据；
- Mock；
- 单元测试；
- 接口文档；
- 使用该字段的上下游模块。

核心协议不应由某一位成员单方面修改。

### 9.4 每个人都要为自己的模块写测试

#### 成员 A 的测试

输入玩家话语，检查 Intent：

```text
我调查书架
→ action_type = inspect
→ target_id = bookshelf
```

同时检查最终叙事是否遵守 `ActionResult`。

#### 成员 B 的测试

输入 EngineRequest，检查：

- 骰子结果；
- Rule 执行；
- 状态修改；
- EventLog；
- 结局判断；
- 非法状态修改是否被拒绝。

#### 成员 C 的测试

输入模组片段，检查：

- Entity 是否正确提取；
- Checkpoint 是否完整；
- Rule 是否遗漏；
- state 是否完整；
- 输出是否通过 Schema 校验；
- 解析结果与人工标准答案的差异。

---

## 10. 第一周建议安排

以下节奏可根据团队实际时间压缩或扩展。

### 第 1 天：共同设计

三人共同完成：

- 确认书房 Demo 场景；
- 确认三个核心 Schema；
- 建立仓库目录；
- 编写术语表；
- 确定接口维护人和评审规则。

### 第 2 天：准备标准输入输出

- 成员 A：准备玩家输入到 Intent 的示例；
- 成员 B：准备 EngineRequest 到 ActionResult 的 Mock；
- 成员 C：完成第一版 `demo-module.json` 和 `demo-cases.json`。

当天结束前，三人共同检查三份数据能否对接。

### 第 3 天：接通假引擎闭环

- 成员 A：实现回合路由和 Intent 输出；
- 成员 B：提供可调用的假引擎；
- 成员 C：补充测试输入、非法操作和失败路径。

当天目标：首次跑通“玩家输入 → Agent → 假引擎 → Agent 回复”。

### 第 4 天：加入真实状态与日志

- 成员 A：增加叙事忠实度检查；
- 成员 B：加入最小 GameState、状态变更和 EventLog；
- 成员 C：加入 Schema 自动校验和预期状态断言。

### 第 5 天：加入检定和结局

- 成员 A：处理检定成功、失败两种叙事；
- 成员 B：加入普通检定和 WinCondition；
- 成员 C：补齐成功、失败、重复操作、结局触发测试。

当天结束时进行第一阶段演示和复盘。

---

## 11. 第一阶段验收标准

### 11.1 主链路

- [ ] 玩家可以进入书房场景；
- [ ] 玩家可以与管家自由对话；
- [ ] 玩家可以调查书架；
- [ ] 调查行为会生成合法 Intent；
- [ ] 引擎能够执行检定；
- [ ] 成功时正确更新 `has_key`；
- [ ] 状态变化被写入 EventLog；
- [ ] 使用钥匙后可以打开柜子；
- [ ] 获得文件后能够触发结局；
- [ ] 主持 Agent 的叙事与引擎结果一致。

### 11.2 协议和数据

- [ ] `ModuleContent` Schema 已确定；
- [ ] `Intent / EngineRequest` Schema 已确定；
- [ ] `ActionResult` Schema 已确定；
- [ ] `demo-module.json` 能通过 Schema 校验；
- [ ] 上下游对同一字段的语义理解一致；
- [ ] 协议变更有对应测试。

### 11.3 测试和质量

- [ ] 至少有 10～20 条 Demo 测试输入；
- [ ] 覆盖自由叙事与规则行为；
- [ ] 覆盖成功和失败；
- [ ] 覆盖非法操作；
- [ ] 覆盖重复操作；
- [ ] 覆盖结局触发；
- [ ] 引擎失败时，Agent 不会叙述为成功；
- [ ] 每位成员负责的模块都有自动测试或可重复验证方式。

---

## 12. 当前阶段明确不做的内容

为了控制第一阶段范围，以下内容暂不作为 MVP 前置条件：

- 完整 COC 规则；
- 多场景大型模组；
- 多人同时行动；
- 完整 Condition / Ledger；
- 所有 Hook；
- 多条复杂 Rule priority 冲突；
- 运行期双 Agent 拆分；
- 独立剧情导演 Agent；
- 完整总结复盘 Agent；
- 三套复杂人格 Prompt；
- 解析任意格式和任意复杂度的模组。

这些能力应在最小闭环稳定后，根据真实问题和评测结果逐步加入。

---

## 13. 需要避免的开发方式

### 13.1 不要把三个 Agent 当作自由聊天的机器人

系统不应依赖：

```text
Agent A 和 Agent B 自由聊天
→ Agent B 再与 Agent C 自由聊天
```

而应使用明确编排的工作流：

```text
何时调用哪个模块
→ 传递哪些数据
→ 必须输出什么结构
→ 下一步由谁处理
```

当前真正需要优先建设的是：

- Schema；
- 工作流；
- 工具接口；
- 状态机；
- 测试样例。

### 13.2 不要过早追求完整实现

- 不要先实现完整模组解析，再考虑运行时如何使用；
- 不要第一版就实现全部规则、Hook 和 Condition；
- 不要在事实一致性尚未解决时优先优化叙事文采；
- 不要让三个人长时间在独立分支开发后才首次集成；
- 不要在没有评测数据时提前拆分更多运行期 Agent。

---

## 14. 最终分工结论

```text
成员 A：运行时主持 Agent
负责理解玩家、生成 Intent、组装 EngineRequest、调用引擎并生成最终回复。

成员 B：确定性规则引擎
负责检定、规则、状态、事件、约束和结局。

成员 C：模组数据与解析审查
负责标准模组、解析 Agent、审查 Agent、Schema 校验和评测。
```

但三个人开始各自开发之前，必须先共同完成：

```text
一个 Demo 模组
+
三个核心 Schema
+
一条端到端工作流
```

最终开工原则：

> 先用人工模组和假引擎跑通纵向闭环，再把假模块逐个替换为真实模块；通过稳定的数据协议并行开发，并始终保持系统可运行。

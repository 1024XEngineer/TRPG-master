# ModuleContent Capability Matrix

> 状态：Phase 1 事实基线  
> 日期：2026-07-21  
> 目的：区分 Contract 表达能力、Validation 覆盖、Runtime 消费能力和测试证据；本文不定义 Phase 2 Schema。

## 1. 权威范围

本矩阵只依据当前可执行代码和测试：

- [`contracts/module.py`](../agent-collaboration-framework/collaboration_framework/contracts/module.py)：Phase 1 唯一共享 Schema 权威；
- [`module/validation.py`](../agent-collaboration-framework/collaboration_framework/module/validation.py)：Draft → ModuleContent 的确定性语义校验；
- [`engine/atomic.py`](../agent-collaboration-framework/collaboration_framework/engine/atomic.py)：当前 Fake Runtime 的实际消费语义；
- [`fixtures/demo-module.json`](../agent-collaboration-framework/fixtures/demo-module.json)：Phase 1 正向样本；
- `tests/test_module_*.py` 与 `tests/test_workflow.py`：当前自动化证据。

RFC 和目标设计只用于后续候选分析，不作为“已经支持”的证据。

## 2. 状态定义

| 标记 | 含义 |
|------|------|
| ✓ 已证明 | Contract、Validation、Runtime 和测试证据足以证明当前声明的能力；或测试明确证明该职责属于其他边界 |
| △ 部分证明 | 只有部分层实现、实现未被针对性测试，或当前行为是 MVP 占位语义 |
| ✗ 未覆盖 | 当前 Contract 无法表达、Runtime 不消费，或没有证据证明 |

缺口类型：

| 类型 | 含义 |
|------|------|
| Contract gap | 当前 ModuleContent 无法表达该机制 |
| Validation gap | Contract 能表达，但确定性校验没有覆盖必要约束 |
| Runtime gap | Contract 能表达，但 Runtime 没有执行对应语义 |
| Test gap | 代码看起来存在，但没有自动化测试直接证明 |
| External boundary | 能力应属于 GameState、Ruleset、发布元数据或其他模块，不应直接加入 ModuleContent |

## 3. Phase 1 能力总表

| # | 模组机制 | Contract 表达 | Validation | Runtime 实际消费 | 自动化证据 | 状态与缺口 |
|---|----------|---------------|------------|------------------|------------|------------|
| 1 | 模组 ID、版本、规则集引用 | `module_id/version/world_ref` | 必填、非空、额外字段拒绝 | Runtime 保存 ModuleContent；当前不使用 version/world_ref 裁定 | Contract、Publish、Runtime Load tests | △ `module_id` 可加载；version/world_ref 尚未连接版本策略和 Ruleset，属于 Runtime/External boundary |
| 2 | Scene 定义与当前场景选择 | `SceneSpec(id/name/content)` | Scene ID 唯一；Checkpoint/Entity 引用检查 | 根据 `GameState.scene_id` 查找 Scene | Workflow 与 Runtime Integration tests 固定证明 `study` | ✓ 已证明 |
| 3 | Scene 包含的 Entity | `SceneSpec.entity_ids` | Entity 必须存在 | 只投影当前 Scene 的 Entity | 缺失引用负向 fixture；PlayerView/Runtime tests | ✓ 已证明 |
| 4 | Scene 暴露的 Checkpoint | `SceneSpec.checkpoint_ids` | Checkpoint 必须存在且反向归属 Scene | 只投影当前 Scene 登记的 Checkpoint | 引用负向 fixtures；Checkpoint workflow tests | ✓ 已证明 |
| 5 | Entity 基本描述 | `id/kind/name/aliases/content` | 类型、枚举、必填字段 | 构造 ProjectionEntity，供 Host 匹配和展示 | alias intent cases、PlayerView workflow | ✓ 当前三种 kind 范围内已证明 |
| 6 | Entity 类型扩展 | `kind = npc/object/location` | 非法枚举拒绝 | Runtime 透传 kind，不做分类规则 | Contract enum test | △ 当前三类已证明；更多类型属于 Contract 候选，尚无真实需求证据 |
| 7 | Entity 秘密隔离 | `EntitySpec.secrets` | 结构检查 | ProjectionSnapshot 不复制 secrets | 代码边界存在；没有针对 secrets 的独立泄漏测试 | △ Test gap |
| 8 | Entity 状态键声明 | `EntitySpec.state` | Condition/Modify 只能引用声明过的顶层状态路径 | Runtime 从独立 GameState 读取和修改对应路径 | state path 负向 fixtures；顺序 Runtime Integration | ✓ 顶层 state key 已证明 |
| 9 | Entity.state 自动初始化 | `EntitySpec.state` 看似含默认值，但没有初始化契约 | 不负责构造 GameState | Runtime 只接收已初始化 GameState | Runtime Integration 显式加载 `demo-state.json` | ✓ 已证明属于 External boundary；当前明确不自动初始化 |
| 10 | 嵌套 Entity state 路径 | `state` 值允许 JSON 对象，但 known_paths 只生成 `entities.<id>.<top_key>` | 嵌套叶子路径不会被声明为 known path | Runtime 路径读取器可逐段读取，但正式 ModuleContent 会先被 Validation 阻断 | 无正向 fixture/test | ✗ Validation/Contract 语义缺口，暂不支持 |
| 11 | 直接响应 | `direct_responses[action]` | 仅结构检查 | 无 Checkpoint/Rule 时按 verb 返回直接文本 | dialogue/direct workflow 证明 direct resolution；未逐字断言 direct_responses 内容 | △ Test gap |
| 12 | 默认拒绝动作 | `refuse_ops + blocked_text` | 仅结构检查 | verb 在 refuse_ops 且无 allowing rule 时返回 blocked | Demo 声明了 cabinet.open；没有独立 Runtime 断言 | △ Test gap |
| 13 | 有条件解除拒绝 | `Rule.when + then[allow]` | Rule path、Operation、重复 ID 校验 | `_allowing_rule` 按 priority 查条件与 AllowOperation | `rule-allow-after-state-change.json` 完整验证先获得钥匙再开柜 | ✓ 当前 on_action 用例已证明；不代表其他 hook 已支持 |
| 14 | Rule priority | `RuleSpec.priority` | int 结构检查 | allowing rules 按 priority 降序 | 无冲突 Rule fixture/test | △ Test gap |
| 15 | `on_action` Hook | `RuleSpec.hook` 枚举支持 | 非法 hook 拒绝 | `_allowing_rule` 没有检查 `rule.hook`，所有含 allow 的 Rule 都可能参与 action | `test_action_does_not_execute_on_scene_enter_rule` 以 expected failure 记录正确隔离语义未满足 | △ Runtime gap 已由审计测试确认；on_action 正向流程能运行，但 hook 过滤不正确 |
| 16 | `on_scene_enter` Hook | Schema 支持 | 枚举检查 | 无 scene-enter dispatcher；该 Rule 反而会被 action lookup 纳入候选 | `rule-hook-on-scene-enter.json` + expected-failure audit | ✗ Runtime gap 已确认；尚未实现正确的 scene-enter 派发 |
| 17 | `on_turn_end` Hook | Schema 支持 | 枚举检查 | 无 turn-end dispatcher | 无测试 | ✗ Runtime gap |
| 18 | `on_check_resolve` Hook | Schema 支持 | 枚举检查 | Checkpoint 后没有按该 hook 派发 Rule | 无测试 | ✗ Runtime gap |
| 19 | 单一 equals 条件 | `ConditionSpec(path, equals)` | path 必须引用已声明 state | `_condition_matches` 读取路径并执行相等比较 | Rule/WinCondition path tests；结局集成测试 | ✓ 已证明 |
| 20 | AND/OR/NOT、比较、算术条件 | 无 Expr；只有一个 path + equals | 无法校验 | 无法执行 | 无测试 | ✗ Contract gap |
| 21 | Checkpoint Scene/Target 归属 | `scene_id/target_id` | Scene、Target 必须存在；Target 必须在 Scene | 执行前再次复核 scene/target | 多个负向 fixtures；trusted checkpoint tests | ✓ 已证明 |
| 22 | Checkpoint 技能候选 | `skills: tuple[str, ...]` 且非空 | 非空；传入 catalog 时校验合法 ID | proposed_skills 必须为 Checkpoint.skills 子集 | empty/unknown skill tests；workflow trusted candidate test | △ Skill Catalog 仍为可选注入，缺统一所有者 |
| 23 | Checkpoint difficulty | `regular/hard/extreme` | 枚举检查 | Fake Runtime 不使用 difficulty 计算结果 | Contract enum 覆盖；无 Dice test | △ MVP 占位，Runtime/Ruleset gap |
| 24 | Checkpoint 成功分支 | `outcomes.success` | Modify path 检查 | `mvp_check_result=success` 时执行 success.ops、facts、visible、constraints | investigate/smash Runtime Integration | ✓ MVP 成功分支已证明 |
| 25 | Checkpoint 失败分支 | `outcomes.failure` | Modify path 检查 | `mvp_check_result=failure` 时只消费 failure 的 ops、facts、visible、constraints | `checkpoint-failure.json` 验证状态、Event、内部事实、玩家信息、叙事约束及成功分支不泄漏 | ✓ MVP failure 分支已证明 |
| 26 | Critical/Fumble/Pushed Roll 等结果 | 只有 success/failure | 无法校验其他分支 | 无法执行其他分支 | 无测试 | ✗ Contract gap；等待生产 Check Resolver 需求 |
| 27 | `ModifyOperation(set)` | `op=modify, path, set` | path 必须已声明 | 原子修改 GameState 并生成 Event/StateChange | path 负向 tests；顺序 Runtime Integration | ✓ 已证明 |
| 28 | `AllowOperation` | `op=allow, action` | discriminator/字段结构检查 | 在 Rule allowing 逻辑中解除 refuse，并执行同一 Rule 的 Modify | capability case 验证 direct/success、状态修改及 Rule cause Event | ✓ 当前 allow + modify 链路已证明 |
| 29 | 数值增减、集合增删、移动、生成等 Operation | 无对应 Operation | 无法校验 | `_apply_operation` 只接受 ModifyOperation | 无测试 | ✗ Contract gap |
| 30 | Checkpoint 事实、玩家信息、叙事约束 | outcome 中有 `facts/player_visible_information/narration_constraints` | 结构检查 | facts 写入内部 execution，visible 写入 ActionResult/Narration，constraints 写入 ActionResult | failure capability case 逐字段断言；既有 success Runtime Integration 覆盖成功路径 | ✓ 当前二分 outcome 消费已证明 |
| 31 | 状态修改 Event | ModuleContent 只声明 Operation；Event 属于 Engine | 校验 Operation path | 每次真实修改生成 StateModifiedEvent | Event replay、顺序 Runtime Integration | ✓ 已证明属于 Runtime boundary |
| 32 | WinCondition 终局求值 | `id/when/fact/player_visible_information` | ID、state path 检查 | 每次正常动作后遍历，命中后写 ending_id/phase 并生成 Events | sequential Runtime Integration | ✓ 已证明 |
| 33 | 多个 WinCondition 同时命中 | tuple 顺序可表达排列，但没有显式 priority | 不检查冲突或可达性 | Runtime 命中第一个后 return | 无冲突 fixture/test | △ 隐式顺序语义，缺团队决策和测试 |
| 34 | 非终局剧情分支/回滚 | 无专用 WinCondition 行为；可尝试普通 Rule/Operation | 无专门检查 | WinCondition 只结束游戏 | 无测试 | ✗ 不属于 WinCondition；需要 Rule/Operation 能力审计 |
| 35 | Scene 转换 | Scene 可定义多个，但无 transition Operation | 只校验 Scene 引用 | Runtime 读取 GameState.scene_id，但 ModuleContent 无法通过 Operation 修改它 | 无测试 | ✗ Contract gap |
| 36 | SAN/HP/资源变化 | 可用通用 state + modify 模拟简单 set；没有 Dice/增减/资源语义 | 只能检查预声明路径 | Runtime 只会 set，不实现规则集计算 | 无 fixture/test | △ 简单赋值理论可表达但未证明；完整机制为 Contract/Ruleset gap |
| 37 | SanTrigger | Phase 1 无模型 | 无 | 无 | 无 | ✗ Phase 2 候选，不得视为当前缺陷结论 |
| 38 | Pregen/Asset | Phase 1 无模型 | 无 | 无 | 无 | ✗ Phase 2 候选；可能属于发布或角色边界 |
| 39 | ModuleDraft → ModuleContent 边界 | 私有 ModuleDraft 与共享 ModuleContent 同形 | 聚合语义错误后才构造正式 Contract | Runtime 只接收 ModuleContent | architecture、validation、publish tests | ✓ 已证明 |
| 40 | 规范化发布与重新加载 | ModuleContent frozen/extra forbid/tuple | 发布前必须 pass | Runtime 从发布 JSON 重建 ModuleContent | Publish 与 Runtime Integration tests | ✓ 已证明 |

## 4. 当前结论

### 4.1 Phase 1 已形成的最小可执行语言

当前已被测试证明的核心闭环是：

```text
Scene
→ Entity / Checkpoint 投影
→ Checkpoint success
→ Modify Entity state
→ StateModifiedEvent
→ WinCondition equals
→ ending_id + phase=ended
```

这足以支持当前 `demo-module.json`，但不能据此证明足以表达一般 CoC 模组。

### 4.2 最高优先级不是“立即加字段”

当前最先需要澄清的是已有字段的消费语义：

1. `RuleSpec.hook` 已声明四种值，但 Runtime 没有完整 Hook dispatcher；
2. `EntitySpec.state` 是状态键声明还是初始化模板，目前依靠约定区分；
3. `world_ref` 和 `Checkpoint.skills` 尚未连接统一 Skill Catalog/Ruleset；
4. 多个 WinCondition 同时命中时只有隐式数组顺序；
5. Checkpoint failure 分支和 Rule allow 流程均已由独立 capability case 证明。

这些问题中，只有确认真实机制无法表达后，才能判定为 Contract gap。

## 5. 下一批 Capability Cases

建议按以下顺序新增小型 fixture。每个 fixture 只证明一个机制，避免把所有行为继续堆入 demo：

| 优先级 | 建议文件 | 要证明的问题 | 当前预期 |
|--------|----------|--------------|----------|
| 已完成 | `rule-allow-after-state-change.json` | 先修改状态，再由 Rule allow 动作 | 已证明 Checkpoint → state → Rule allow → Modify → Event |
| 已完成 | `checkpoint-failure.json` | failure.ops、facts、visible、constraints 是否完整消费 | 已证明四类字段进入各自边界，且 success 内容不泄漏 |
| 待补正向 | `rule-hook-on-action.json` | Runtime 是否严格过滤 hook | 当前 action 流可执行，但仍需与正式 dispatcher 语义一起设计 |
| 已完成审计 | `rule-hook-on-scene-enter.json` | action 流程是否错误执行其他 hook | expected failure 已确认 Runtime 未按 hook 隔离；未修改 Runtime |
| P1 | `win-condition-conflict.json` | 多结局同时满足时的确定性策略 | 需要团队确认顺序/priority |
| P1 | `nested-state-path.json` | 嵌套 state 的声明和执行边界 | 预计暴露 Validation/Contract 语义缺口 |
| P1 | `scene-transition.json` | 模组是否需要声明场景迁移 | 当前无法表达 |
| P1 | `resource-change.json` | SAN/HP 简单赋值与规则集计算的边界 | 需要真实机制样本 |

建议目录在首个 case 确定后创建：

```text
agent-collaboration-framework/fixtures/capability-cases/
```

不要先创建空目录，也不要把这些测试样本当作正式发布物。

## 6. Schema 变更门槛

只有同时满足以下条件，才建议修改 `contracts/module.py`：

1. 至少一个真实模组机制无法用当前 Contract 无损表达；
2. 已排除该能力属于 GameState、Ruleset、发布元数据或 UI；
3. 已确认不是 Validation 或 Runtime 漏实现已有语义；
4. 有最小正向 fixture 和负向 fixture；
5. B/C 对字段语义和 Runtime 消费方式达成一致；
6. Schema、Validation、Runtime 和集成测试能够在同一变更中闭环。

## 7. 本轮未执行的工作

- 未修改 `contracts/module.py`；
- 未修改 Validation；
- 未修改 Runtime；
- 未新增 capability fixture；
- 未实现 Phase 2 字段；
- 未把 RFC 目标能力填写成当前已支持。

## 8. 已记录的预期失败

| 测试 | 正确期望 | 当前结论 | 处理 |
|------|----------|----------|------|
| `test_action_does_not_execute_on_scene_enter_rule` | action 流程不得执行 `hook=on_scene_enter` 的 Rule；柜子应保持 blocked，状态和 Event 不变 | 当前 Runtime 的 `_allowing_rule` 不过滤 hook，正确语义未满足 | 使用 `unittest.expectedFailure` 保留可执行证据；本轮不修改 Runtime |

预期失败不是已支持能力，也不能作为长期行为契约。团队确认 Hook dispatcher 语义并修复 Runtime 后，应移除 `expectedFailure`，让同一测试按正确期望正常通过。

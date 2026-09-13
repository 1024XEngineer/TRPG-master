# #484–#487：四个串行 PR 的实施与验证计划

编写日期：2026-09-12。核查基线：`98a9aba5357fba507047ad9dd1f478d7f27cfc52`，分支 `feat/issue-484-487-capability-completion`，与本次获取的 `upstream/main` 一致。

本文按单人开发安排四个串行 PR。每个 PR 交付一个能独立演示和验证的场景，所需契约、执行器、持久化、投影与测试随场景一起交付。PR 内可以分多次提交，但不能把使主案例成立的必要部分推到下一个 PR。

**状态：计划，尚未实施。** 下文的预期值、测试名、步骤和验收项均不是已通过的测试报告。标注“拟新增”的文件、接口名称可在实施时调整；已有文件链接是当前代码的落点。规则书尚待核对的数值不作为默认常量或测试真值。

## 1. 交付顺序与范围

| PR | 建议标题 | 主案例 | Issue 归属 | 开工前提 |
|---|---|---|---|---|
| PR1 | `fix(sanity): 让规则拥有的 SAN 检定完整结算损失` | SAN=60，检定失败，损失骰=4，接受后变为56，恢复后仍为56 | 完整覆盖 #484、#486；复用 #485，补结果后果入口 | 当前基线即可开始 |
| PR2 | `feat(sanity): 按稳定来源执行理智损失累计上限` | 上限6，同来源请求损失4、4、3，实际损失4、2、0 | #487 的来源、账本、习惯化 | PR1 已合并；来源范围及重置规则已核对 |
| PR3 | `feat(sanity): 打通临时疯狂及小时期限生命周期` | 单次损失满足规则，经必要检定后进入临时疯狂，发作与状态按各自期限处理 | #487 的单次阈值、临时疯狂、发作；补 #485 期限消费 | PR2 已合并；单次阈值、检定、时长已核对 |
| PR4 | `feat(sanity): 打通累计疯狂与跨日恢复规则` | 单次均不足以触发，但同窗口累计达到阈值，形成不定性疯狂，跨日和恢复保持正确 | #487 的累计窗口、不定性疯狂、日期/月尺度 | PR3 已合并；累计基准、优先级和恢复规则已核对 |

按轮期限另留后续 PR，依赖 #401 的 E6b。四个 PR 完成后也不能宣称完整回合系统或 #487 全部完成。

单人推进方式：完成当前 PR 的全部验收、收敛评审并合并，再从包含该 PR 的最新上游基线开下一个。尚未合并时可以写后续案例说明，不同时维护多个互相依赖的功能分支。

### 1.1 来源与现有实现

- [#401 能力缺口总纲](https://github.com/1024XEngineer/TRPG-master/issues/401)规定 Engine、CoC7 适配层和模组的职责。
- [#484 数值资源](https://github.com/1024XEngineer/TRPG-master/issues/484)与[#486 SAN 基础结算](https://github.com/1024XEngineer/TRPG-master/issues/486)在 PR1 联合交付，保留各自完整验收范围。
- [#485 适配层与条件](https://github.com/1024XEngineer/TRPG-master/issues/485)的 [PR #492](https://github.com/1024XEngineer/TRPG-master/pull/492)已合并；当前代码已有适配器、条件记录及应用/解除接口。Issue 仍为 Open，不能只依据状态重新实现一遍。
- [#487 累计、习惯化与疯狂](https://github.com/1024XEngineer/TRPG-master/issues/487)拆成 PR2–4 的三个完整场景；其按轮要求继续跟踪。
- #483 的规则来源及权限已落地；[#415 时间域](https://github.com/1024XEngineer/TRPG-master/issues/415)已有 WorldTime、TimeTask 和恢复能力。

### 1.2 本轮核查到的代码事实

| 事实 | 实施含义 | 当前落点 |
|---|---|---|
| Actor 已有 HP、SAN、MP、Luck、Mythos；没有通用数值 Effect | PR1 增加真正的消费者，不能只增加 Schema | [models.py](../agent-collaboration-framework/collaboration_framework/engine/models.py)、[Effect 契约](../agent-collaboration-framework/collaboration_framework/contracts/adjudication.py)、[effects.py](../agent-collaboration-framework/collaboration_framework/registry/effects.py) |
| SAN 的 `success_loss`、`failure_loss`、`habit_cap` 仍只有识别，没有结算 | PR1 只消费基础损失；PR2 才启用上限 | [check_profiles.py](../agent-collaboration-framework/collaboration_framework/registry/check_profiles.py) |
| Adapter 的 Outcome Handler 表为空，类型尚为 `Any` | PR1 在实际调用处收窄契约并接入 SAN；保留不产生后果的其他 Profile 行为 | [rulesets.py](../agent-collaboration-framework/collaboration_framework/registry/rulesets.py) |
| 主动、被动均有来源，但只有部分检定需要恢复 Agenda | 共享结算后仍按 `origin.resumes_agenda` 分流，不能按“有来源”一概恢复 Agenda | [adjudication.py](../agent-collaboration-framework/collaboration_framework/engine/adjudication.py)、`RuleCheckOrigin` |
| Condition 有结构化 expiry 和解除接口，但未找到自动消费期限的生产路径 | PR3 必须同时打通应用、调度、到期消费、投影和恢复 | [conditions.py](../agent-collaboration-framework/collaboration_framework/engine/conditions.py)、`ConditionExpiry` |
| 后端已有真实 Store 恢复及提交前失败注入能力 | 复用这些接缝验证事务，不另造假持久化链 | [SQLAlchemy Store](../trpg-backend/app/adapters/sqlalchemy_engine_store.py)、[被动检定测试](../trpg-backend/tests/test_issue398_passive_check.py) |
| 当前内置模组为四个，原 Issue 重点只列追书人、银之锁 | 回归覆盖全部内置模组，额外补常暗之厢的两处 SAN | [内置模组清单](../trpg-backend/app/service/builtin_module_loader.py) |
| `e2e/` 验证 SDK→后端，不运行浏览器；前端 CI 当前只执行 lint/build | SDK E2E 与页面组件测试分别验收，不能互相代替 | [E2E 说明](../e2e/README.md)、[前端 CI](../.github/workflows/trpg-frontend-ci.yml) |

## 2. 所有 PR 共用的执行与证据规则

### 2.1 实现环境

1. 功能实现建议使用部署目录之外的独立 worktree、独立虚拟环境及测试依赖。当前目录保持已验收版本；不要把测试库指向热更新服务使用的数据库。
2. PR1 基于实施时包含本次基线的上游；后续 PR 必须包含前一 PR 的合并结果。记录基线 SHA，开始前重新查看工作区改动。
3. 后端测试复用 `tests/conftest.py` 的临时文件 SQLite 和 `engine_store_factory`。SQLite 通过不等于 PostgreSQL 事务/迁移通过。
4. SDK E2E 使用现有 runner 新建的 `e2e.db`，默认端口8099；占用时换测试端口，不连接8000上的开发服务。页面验收也使用独立前后端实例。
5. 模型使用确定性实现，骰子由测试端构造时注入。测试控制不能成为玩家可调用的修改骰面或资源接口。

以上是后续实施方式。本次只新增计划文档，不执行 worktree 创建、依赖安装、数据库操作或功能修改。

### 2.2 每个 PR 的固定工作顺序

| 顺序 | 必做工作 | 留下的证据 |
|---|---|---|
| A | 固定主案例、输入、骰子、规则版本和预期状态 | 可复现的案例编号，修复前基线 SHA |
| B | 先加从既有公开引擎/服务入口出发的行为测试 | 失败在目标断言，例如 SAN 仍为60；不能只是新类型无法导入 |
| C | 逐步实现完整调用链，每步运行对应聚焦测试 | 改动与测试的对应关系 |
| D | 验证重复请求、断线、重启、事务失败 | 重新读取数据库后的状态、事件数量、持久化游标和抽样事实 |
| E | 验证 SDK、PlayerView 和组件显示 | 同一修订下的协议值与可见值一致 |
| F | 跑受影响回归、契约生成和必要 CI 检查 | 命令、退出码、用例数、跳过项及原因 |
| G | 对核心防线做一次定向破坏验证 | 临时去掉关键逻辑后对应案例失败；恢复代码后通过 |
| H | 按验收清单准备 PR，完成后再进入下一 PR | 主案例前后对比、范围、限制、兼容与回退说明 |

PR2 的“修复前”是 PR1 合并版，PR3 的“修复前”是 PR2 合并版，依此类推。不能都拿最初“不扣 SAN”的基线证明新功能有效。

### 2.3 验证层次

| 层 | 验证什么 | 使用方式 |
|---|---|---|
| 引擎行为 | 规则输入、最终检定、状态变化、事件顺序、边界 | 真实契约、RuleAgenda、Effect 和有限骰序列；仅替换随机源与 Store |
| 后端持久化 | 事务、幂等、恢复、旧快照、房间隔离 | SQLAlchemy 测试库；换 Store/Session 后重新读库，必要时增加子进程恢复用例 |
| SDK→后端 E2E | 公开流程、WebSocket 更新、重连读回、多玩家可见性 | 使用现有 E2E runner；至少覆盖每个 PR 的一个核心可达场景 |
| 前端组件 | 角色卡资源、疯狂状态、更新和解除 | 用真实投影形状驱动组件；从旧值更新到新值，不只检查首次渲染 |
| 人工演示 | 实际页面、操作顺序、叙事与状态是否一致 | 独立测试房间；截图只证明显示，不能代替持久化断言 |

所有案例至少断言：数值/条件、事件或消费次数、可恢复状态。HTTP 200、`status=resolved`、日志出现“成功”、叙事写“你损失了理智”都不足以证明功能完成。

## 3. 动工前需要固定的共用约定

### 3.1 规则书核对记录

[#487](https://github.com/1024XEngineer/TRPG-master/issues/487)明确要求编码前记录规则版次、机械结论和人工 Review。下面是待填的核对表，不阻塞 PR1 按已发布参数执行基础损失。

| 编号 | 必须核对的结论 | 最迟完成时间 |
|---|---|---|
| R1 | `habit_cap` 的来源身份、共享范围、累计周期和重置条件；封顶后是否仍需要检定/掷损失骰 | PR2 开始前 |
| R2 | 单次损失阈值，比较哪个损失值，是否需要额外检定及其触发结果 | PR3 开始前 |
| R3 | 临时疯狂状态与疯狂发作的区别、各自时长、发作表版本、再次刺激的处理 | PR3 开始前 |
| R4 | 不定性疯狂的累计窗口、基准 SAN、阈值计算和取整规则、SAN 恢复对窗口的影响 | PR4 开始前 |
| R5 | 单次/累计同时满足时的优先级或共存规则，以及已有疯狂时的行为 | PR3 先明确已支持范围，PR4 完整核对 |
| R6 | 小时/日期/月的期限、恢复条件及月份换算策略，幸运/推动对上述检定的权限 | 相应消费者开始前 |

每条记录：规则书名称、版次、页码/章节、采用的机械结论、是否可选规则、核对人和对应测试编号。人工核对可以由唯一开发者本人完成，不额外引入等待另一位开发者的排期。只摘录实现所需的结论，不复制完整规则表。

后文以 `T_single`、`T_period`、`D_bout`、`D_condition` 表示核对后确定的阈值和时长。**这些占位符必须在对应 PR 的测试中替换为有出处的具体输入与期望值，带占位符的案例不能作为通过证据。**

### 3.2 事件、幂等与提交边界

1. 通用数值事件保存 actor/resource、结构化数量、骰子事实、before、请求 delta、实际 delta、after、可见性和 Rule/Check/Action 来源。事件名在 PR1 中固定并进入测试。
2. 同一个 SAN 后果需要跨请求稳定的身份。不能只用客户端 `request_id` 防重；换 request、重放 Check、恢复 Agenda 都不能再产生同一后果。
3. PR1 输出的 SAN 后果事实是 PR2–4 的唯一损失输入。如果同时发通用资源事件和 SAN 语义事件，必须关联到同一个后果，账本只选一个规范输入记账。
4. PR2 对上限的约束发生在数值提交前：读取账本→计算剩余额度→限制实际扣减→提交最终 SAN 事实及记账。不能先全扣、发事件，再退款；否则后续疯狂消费者会看见错误损失。
5. 已提交损失保持不可变。后续消费者挂起时保存消费进度，恢复只继续后果处理，不再次扣 SAN 或掷损失骰。
6. 抽样恢复要区分两个故障点：已提交但响应丢失，以及抽样后、事务提交前失败。后者不能靠“命令完成日志”解决。PR1 必须选定可恢复抽样方案，例如命令/Check 级持久随机依据及稳定抽样键；若增加准备阶段，它不得改变资源或发布最终后果。最终骰子事实、数值、事件与恢复状态仍在同一可恢复提交中落地。
7. 预检、能力投影和效果顺序模拟不消耗正式随机源，不发布事件。受约束数值通过既有 `DiceRoller` 执行，不能新建通用表达式求值入口。
8. `zero loss` 也有一次可审计的结算事实；它与“该检定尚未处理”不同。其是否进入某种累计由已核对规则决定，不能因没有资源变化就再次结算。

## 4. PR1：SAN 基础结算完整可用

### 4.1 主案例与现有内容

主案例选《追书人》`first_sight_of_douglas`。布置合法前置状态，调查员 SAN=60，经正式行动使 `true_form_seen` 成立，规则发起被动 SAN 检定。固定 D100=81、损失 `1d6`=4，玩家接受失败结果。

- 当前预期缺口：检定和规则链能结束，但权威 SAN 仍为60；实施时先用行为测试证实。
- PR1 完成：最终 SAN=56；一份损失事实；PlayerView 与角色卡为56；父规则/父动作继续时读取56；恢复后仍为56。
- 未确认最终结果前：SAN=60，不提前消费损失骰。

基础损失回归表来自当前模组内容，不能在引擎中按这些 Rule ID 编码。

| 模组/规则 | 成功损失 | 失败损失 | 用途 |
|---|---|---|---|
| 追书人 `first_sight_of_douglas` | 0 | 1d6 | 主案例 |
| 追书人 `ghoul_crowd_sanity` | 0 | 1d6 | 基础损失；`habit_cap=6` 的完整消费在 PR2 |
| 银之锁 `rat_thing_sanity` | 0 | 1d6 | 第二个正式模组回归 |
| 银之锁 `door_ghost_sanity` | 1 | 1d3 | 成功也扣值、不同骰式 |
| 常暗之厢两处 SAN | 1 | 分别为1d4、1d6 | 当前新增内置内容的兼容性 |

### 4.2 实现步骤

| 步骤 | 实现工作与产物 | 本步验证 |
|---|---|---|
| P1-01 | 在正式追书人内容上构造主案例。复用 `_arm_first_sight`、正式 `submit/decide/decide_post_roll` 调用和临时数据库；固定 SAN 与骰子输入 | 先得到“期待56、实际60”的失败；记录基线，不以新类缺失作为红测 |
| P1-02 | 定义封闭资源 ID、增减方向、`fixed/dice` 数量及当前 actor 数值 Effect。接入契约、registry、读写声明、参数校验和固定值执行 | 未知资源、任意字段路径、布尔冒充整数、负数量/越界骰子均拒绝；HP/SAN/MP/Luck/Mythos 的合法固定增减有规则执行案例 |
| P1-03 | 固定资源边界：SAN至少以0为下界；MP/Luck/Mythos服从当前非负模型；HP不借此引入未经设计的生死阈值。缺失的可空资源显式拒绝，不能当0 | SAN=2请求扣4实际扣2；不虚构 max 值；错误输入无状态/事件副作用 |
| P1-04 | 接入骰式执行、稳定后果键、可恢复抽样及审计字段，明确0损失。通过既有事务接口落地，InMemory 与 SQLAlchemy 语义一致 | 预检不掷骰；相同后果只有一份正式抽样事实；覆盖提交前失败及提交后响应丢失 |
| P1-05 | 收窄 Outcome Handler 输入/输出：最终 Check 结果、固定 ModuleVersion 的 RuleCheckSpec、actor及来源。CoC7 层把封闭损失字符串转成结构化数量，再交通用 Effect 执行 | 六种 degree 按 #486 映射；未知/非法参数显式失败；通用数值执行器不识别 `coc7.sanity` 或模组 ID |
| P1-06 | 在 `_settle_check` 周边建立共享后果阶段，再按 `resumes_agenda` 进入 `_resume_rule_check` 或 `_finalize_action`。确认新 state/events 没有被旧 runtime 覆盖 | 主动与被动都扣值；结果分支、事件屏障、父 continuation 读取新状态；幸运/推动如被允许，只按最终结果扣一次 |
| P1-07 | 连接权威资源投影、`committed_results_from_events`/叙事输入和 WS 修订。前端复用已有 live resources，修复实际缺失的显示消费者 | 同一修订中数据库、PlayerView、角色卡一致；SAN=0不退回建卡数值；Narrator收到真实已提交后果 |
| P1-08 | 扩展持久化、命令重放、旧 Check/快照读取和并发测试。用 `before_commit`、新 Store、新 Session 验证故障边界 | 失败不留半份资源/事件；换 request 不能重复结算；两个同版本并发请求最多一个生效；旧快照可读取 |
| P1-09 | 增加 SDK SAN 场景和组件更新用例。现有 E2E 固定骰恒为1，需在测试构造根增加有限且区分用途的骰输入，使 D100=81 与 d6=4 可同时成立 | 不把81作为d6结果；序列耗尽/越界明确失败；生产环境不启用测试控制；SDK重连后仍读取56 |
| P1-10 | 更新实际受影响的 framework Schema、后端 DTO 导出和 SDK 类型，补所有内置模组回归；整理证据和未交付范围 | 聚焦测试、全量回归、构建、契约再生成一致；确认没有顺带改变 #475 NPC离场或 #319 剧情 |

### 4.3 验收矩阵

| 编号 | 输入/操作 | 必须成立的结果 | 层次 |
|---|---|---|---|
| S01 | 主案例：60，D100=81，d6=4，接受 | 56；只产生一次损失；规则链继续 | 引擎、持久化、SDK、组件 |
| S02 | 已掷D100，但尚未最终确认 | SAN保持60；无损失抽样/最终损失事实 | 引擎、持久化 |
| S03 | 成功损失0 | SAN不变；有一次0损失结算记录；不掷损失骰 | 引擎、持久化 |
| S04 | 银之锁成功损失1，SAN=60 | SAN=59；固定值执行 | 引擎、组件 |
| S05 | 覆盖四种成功 degree、failure、fumble | 选择对应成功/失败参数；不另加未经确认的大失败公式 | 引擎 |
| S06 | SAN=2，请求损失4 | after=0；requested=4，actual=2；界面显示0 | 引擎、持久化、组件 |
| S07 | 合法 `agent_match` SAN 规则夹具 | 与被动案例相同的后果；恢复正确父路径，不寻找不存在的 Agenda | 引擎、持久化 |
| S08 | 同一最终决定原样重试 | 同一事件/后果；资源不再变化；不再次抽样 | 持久化、SDK |
| S09 | 新 request_id 重复处理同一已结束 Check | 明确已结算/版本错误；无新增损失 | 持久化 |
| S10 | 抽样后提交前失败；或提交后丢响应再恢复 | 前者无半截业务提交且恢复同一抽样依据；后者读回既有事实；最终只扣一次 | 持久化、故障注入 |
| S11 | 损失参数非法、未知资源、缺失SAN、过期来源版本 | 明确拒绝；不回落到Agent自报值，不部分执行 | 引擎、持久化 |
| S12 | 其他资源的固定/骰式增加及减少 | 真实规则执行后按注册边界写入对应资源；证明 #484 全范围 | 引擎、持久化 |
| S13 | 损失后紧跟测试观察点/结果分支，再接父动作 | 后续看到56；不先恢复父动作再扣损失 | 引擎、叙事上下文 |
| S14 | 已允许的幸运改判、推动后最终确认 | 按最终 degree 结算；此前不扣；相关权限依然生效 | 引擎、持久化 |
| S15 | 两个actor，只有A触发；A重连 | 只改A；B可见内容遵守既有可见性；恢复不串房间 | 持久化、SDK |
| S16 | 六处已发布 SAN，加四个内置模组加载回归 | 成功、失败、恢复正确；版本内容不被无故改写 | 内容、引擎、后端 |

核心变异检查：去掉资源写入应使 S01 失败；把结算移到最终确认前应使 S02 失败；去掉防重应使 S08/S09 失败。破坏只在隔离 worktree 临时进行，恢复后再提交。

### 4.4 文件与测试落点

- 既有：`contracts/adjudication.py`、`contracts/module_v3.py`、`registry/effects.py`、`registry/rulesets.py`、`engine/adjudication.py`、`engine/models.py`、`engine/persistent_results.py`、`engine/projection_v3.py`。
- 既有：两种 Store、后端 `app/core/engine.py`、`app/controller/ws.py`、前端 `CharacterBasicInfo.tsx` / `RoomPage.tsx`；只改场景需要的部分。
- 拟新增：framework `tests/test_actor_resources.py`、`tests/test_sanity_settlement.py`；backend `tests/test_sanity_settlement_persistence.py`；E2E `tests/sanity-settlement.e2e.ts`。
- 复用并扩展：`test_registry_effects.py`、`test_registry_rulesets.py`、`test_issue398_passive_check.py`、`test_adjudication_persistence.py`、`test_rule_match_adjudication.py`、`test_narration_results.py`、`CharacterBasicInfo.test.tsx`、`RoomPage.test.tsx`。

### 4.5 完成标准

- [ ] S01–S16通过，至少一条 SDK 场景及组件动态更新通过。
- [ ] #484、#486 验收逐条映射到具体测试，满足后才在 PR 使用 `Closes #484` / `Closes #486`。
- [ ] 玩家看到SAN变化，固定值、骰式和0损失都可审计；恢复不重复处理。
- [ ] 明确记载 `habit_cap`、疯狂、SAN最大值及战斗尚未交付；保留 #487。
- [ ] #485仅按实际补缺引用，不能因为结果入口接通就关闭其所有剩余验收。

## 5. PR2：同来源 SAN 损失封顶

### 5.1 主案例

以《追书人》食尸鬼群的 `habit_cap=6` 为参数依据，构造通过发布校验的可重复刺激测试模组。当前正式规则有 `crowd_sight_resolved` 一次性标记，不能通过去掉它来伪造真实剧情反复触发。

同一actor、同一经核对来源、同一有效累计周期，初始 SAN=60，依次请求损失4、4、3：

- PR1 后：SAN依次56、52、49。
- PR2 后：SAN依次56、54、54；实际损失4、2、0，累计6。
- 换独立来源请求损失2：该来源有独立额度，SAN可再减2。

此案例证明“上限6的机械执行”；什么对象共享来源、何时重置，须完成 R1 核对后另用具体数据验证。

### 5.2 实现步骤

| 步骤 | 实现工作与产物 | 本步验证 |
|---|---|---|
| P2-01 | 完成R1，构造同来源重复刺激及不同来源对照；先在PR1基线上执行 | 主断言显示期待54、实际49；不能以始终无法再次触发的正式剧情充当重复来源测试 |
| P2-02 | 明确注册来源键与身份作用域。区分“规则出处”和“恐怖来源”；重命名、Check、Event和request变化不应制造新来源 | 同来源跨规则/事件是否共享按R1测试；不同来源、actor、房间互不误合并 |
| P2-03 | 给现有内容补足可执行来源声明/映射。若新增参数，在适配器注册、发布校验和运行时一起消费；需要改内置内容时发布新版本 | 不在通用Engine硬编码追书人ID；缺少可证明的来源时明确能力不足；不覆盖已发布ModuleVersion |
| P2-04 | 建立actor级损失账本，从PR1规范SAN事件取得事件ID、来源、请求/实际损失、before/after、WorldTime与版本；增加消费幂等键 | 同一后果重放不重复记账；通用资源事件和SAN事件不会算两次；0损失也能确认已消费 |
| P2-05 | 在SAN扣减前读账本限制额度，把最终实际损失与账本变化放入一致事务；保留原始请求损失 | 4、4、3→4、2、0；观察者始终看见最终实际损失；不出现先扣后退款的中间事件 |
| P2-06 | 处理并发、恢复和旧快照。对PR1已存在事件做有证据的迁移/补账，标明覆盖边界 | 两次竞争不能突破额度；断线不清零；迁移重复执行不重复计数；不能从当前SAN反推历史损失 |
| P2-07 | 更新SDK/组件中的可见结算反馈，完成正式模组兼容及错误场景；不向玩家泄露隐藏来源身份 | 封顶后的0损失可解释；玩家看到实际扣减；重连一致；缺源不是“静默忽略上限” |
| P2-08 | 回归PR1，做上限/防重变异验证，整理PR2前后快照与未交付范围 | PR1基本扣减仍正确；去掉上限后主案例失败；保留疯狂部分未完成 |

旧房间的历史兼容是本 PR 的交付项：按固定 ModuleVersion 与可验证来源映射补账；没有历史证据时记录缺口并采用经确认的显式兼容方案，不能把缺失历史当作“累计为0”。来源迁移与内容版本策略必须写进 PR 描述。

### 5.3 验收矩阵

| 编号 | 输入/操作 | 必须成立的结果 |
|---|---|---|
| H01 | 同来源上限6，请求4、4、3 | 实扣4、2、0；SAN=54；来源累计6 |
| H02 | 达到来源A上限后，来源B请求2 | B独立计算，SAN再减2 |
| H03 | 同来源更换显示名、request、Check或触发Event | 不重置额度；身份规则遵从R1 |
| H04 | 两个actor/两个房间遇到同一来源 | 不串账；累计范围与核对规则一致 |
| H05 | 重放同一损失事件，或同时提供它的通用/SAN事件表示 | 只记账一次，不重复触发下游 |
| H06 | 剩余额度2，两个并发请求各要扣2 | 最多实际扣2；冲突路径重读最新账本 |
| H07 | SAN只剩1，来源还可扣2，请求4 | 记录请求4、来源约束及实际扣1；相关累计采用核对后的数值语义 |
| H08 | 封顶结算前后换Store/进程恢复 | 同一额度与同一后果；不重掷、重复记账或清零 |
| H09 | 缺来源、非法cap、无法证明的来源合并 | 显式拒绝/能力报告；没有静默忽略或半份数值提交 |
| H10 | 使用PR1历史事件迁移旧快照并重复迁移 | 可证明的历史仅累计一次；缺口可见，不从SAN猜历史 |
| H11 | 跨越R1定义的重置边界，及未跨越边界的对照 | 只按规则重置；不因重连、改文案或任意跨日自动清零 |
| H12 | 封顶后的WS更新与重连投影 | 角色卡保留54；反馈为实际损失0；隐藏来源不外泄 |

### 5.4 文件与完成标准

拟新增：framework `tests/test_sanity_habituation.py`；backend `tests/test_sanity_habituation_persistence.py`；E2E `tests/sanity-habituation.e2e.ts`。实现沿PR1的CoC7后果处理、状态/Store和投影扩展；账本模块可单独组织，但不另开“只有账本”的PR。

- [ ] H01–H12通过，R1有已核对记录。
- [ ] 真实已发布规则的首次触发、合法重复夹具和旧房间来源兼容分别有证据。
- [ ] SAN事实、实际扣减和账本一致，没有补偿式退款或重复消费。
- [ ] PR1回归通过，#487仍保持未完成。

## 6. PR3：临时疯狂、发作与小时期限

### 6.1 主案例与边界

选择规则已确认允许使用小时尺度的场景。一次真实SAN结算达到 `T_single`，完成规则要求的后续检定并得到触发结果，产生临时疯狂与受控发作记录；推进游戏时间，分别处理发作期限和疯狂状态期限。

当前《追书人》有 `temporary_insanity_leads_to_asylum`，监听 `actor.temporary_insanity`。满足食尸鬼群已出现等前置时，它会设置 `sent_to_asylum` 并应用 `unconscious`。PR3应验证从SAN损失真实到达这条既有规则，不能直接伪造疯狂事件来证明主链成立。

这只验证该规则已有的标志和昏迷效果；位置迁移、精神病院完整剧情及 #319 其他内容仍按其自己的验收处理。疯狂发作结束不自动等于恢复理智，也不自动解除模组另加的昏迷。

### 6.2 实现步骤

| 步骤 | 实现工作与产物 | 本步验证 |
|---|---|---|
| P3-01 | 完成R2/R3及已支持范围的R5/R6。把 `T_single`、后续检定触发方向、`D_bout/D_condition` 替换为具体案例 | 阈值、失败/成功语义和小时场景均有出处；主测试在PR2上只扣SAN，没有疯狂后果 |
| P3-02 | 从PR2账本/规范SAN事件判定单次阈值；定义消费进度、已有条件及再次刺激策略 | 不读叙事、不重新掷损失骰；按实际/请求损失的核对语义判断；重复事件不重复判定 |
| P3-03 | 如规则要求INT等后续检定，同PR补齐所需的受约束Profile/属性读取与现有检定UI、持久化游标 | 当前被动Profile仅SAN，不能只登记一个字符串；新检定能挂起、展示、接受并跨Store恢复 |
| P3-04 | 注册类型化临时疯狂与发作类型、来源和原因；使用明确的重复/共存策略；产生模组可消费的稳定事件 | 条件权威记录与玩家安全投影一致；发作类型及其骰子只产生规定次数；已有模组事件能接上 |
| P3-05 | 为已确认小时期限创建真实TimeTask/绝对occurrence，条件引用可恢复期限。注册时间事件消费者，应用/到期操作随事务提交 | 到期前有效、到期后按规则结束；明确day_index；同名“夜晚”不能使条件提前或重复结束 |
| P3-06 | 在追加检定、事件连锁、模组后果和父continuation之间接入恢复屏障 | SAN不重扣；后续检定未完成时父动作不越过屏障；模组规则只执行一次 |
| P3-07 | 区分发作结束、临时疯狂状态恢复、模组额外条件解除；处理到期时已移除/已消费的情况 | 已结束记录不重新进入玩家条件列表；结束一个条件不删除无关条件 |
| P3-08 | 增加玩家安全状态/期限展示与Narrator上下文，同步必要的Schema/SDK；Engine只记录发作类型和机械状态 | 显示可见期限/阶段；不泄露Keeper精确时间或隐藏来源；Narrator不会决定权威类型/期限 |
| P3-09 | 覆盖重启、旧Condition快照、时间终点及无回合能力场景；运行PR1/PR2回归 | 不依赖现实时间；缺少时间能力显式挂起/拒绝，不发布“半截Condition”或伪造按轮支持 |

期限优先引用带绝对occurrence的TimeTask。旧 `time_point` 引用要有明确兼容解释，不能只按每天重复的point ID判断新条件期限。内部到期消费者复用通用时间事件，不要求每个模组自己补一条恢复规则。

### 6.3 验收矩阵

| 编号 | 输入/操作 | 必须成立的结果 |
|---|---|---|
| T01 | 单次损失位于 `T_single-1` | 正常扣SAN，没有临时疯狂及多余后续检定 |
| T02 | 单次恰好满足阈值，后续检定得到触发结果 | 一份疯狂状态和规则要求的发作记录；来源可追溯 |
| T03 | 相同阈值输入，后续检定得到不触发结果 | 保留SAN损失；不产生应被该结果排除的疯狂状态 |
| T04 | 追加检定出现后断线，换Store/进程继续 | 恢复同一决定和同一来源；不重扣SAN，不重建新检定 |
| T05 | 满足追书人已有分支前置，从真实SAN路径触发 | `actor.temporary_insanity`进入既有规则，标志/昏迷效果各提交一次；不硬编码Rule ID |
| T06 | 时间位于 `D_bout` 前/到期点 | 仅按核对规则结束发作；不顺带清除仍有效的疯狂状态 |
| T07 | 时间位于 `D_condition` 前/到期或其他合法恢复条件 | 独立判断疯狂状态恢复；模组附加条件不被误删 |
| T08 | 含期限的快照保存后重启 | 类型、绝对期限和任务一致；不重掷发作/时长，不从当前时间重新起算 |
| T09 | 到期事件重放；或到期前条件已被合法移除 | 幂等，无重复解除事件；已结束条件不复活 |
| T10 | 再次刺激/已有疯狂/同类不同来源 | 按已确认的替换、延长、共存或忽略策略执行，保留来源；不能依赖当前“同ID即忽略”默认行为 |
| T11 | 时间任务越过模组终点或当前无对应时间能力 | 明确失败/挂起及可恢复消费状态；不留下无期限但声称已完整应用的条件 |
| T12 | 选择需要按轮期限的场景 | 明确不可执行，不把普通行动或WorldTime点当轮；已提交SAN事实保持唯一 |
| T13 | 条件JSON往返、旧字符串快照、WS重连、页面解除 | 旧数据可读；投影只含活动条件；状态更新后界面同步 |
| T14 | 对照Narrator收到的发作事实与最终状态 | 类型、期限和SAN来自权威事实；Engine不强制执行“逃跑/暴力”等叙事行为 |

### 6.4 文件与完成标准

复用 `engine/conditions.py`、`ActorCondition`、`registry/rulesets.py`、`registry/predicates.py`、TimeTask/Agenda执行、PlayerView、检定组件和叙事后果投影。需要的额外检定和时间事件消费者随本场景交付。

拟新增：framework `tests/test_temporary_insanity.py`；backend `tests/test_temporary_insanity_persistence.py`；E2E `tests/temporary-insanity.e2e.ts`。扩展 `test_actor_conditions.py`、`test_time_tasks.py`、`test_time_acceptance.py` 和页面状态测试。

- [ ] T01–T14通过，R2/R3及相关R5/R6均已具体化。
- [ ] 真实SAN→必要检定→条件/发作→模组后果→时间恢复全链有证据。
- [ ] 发作、疯狂、模组附加条件拥有分别验证的生命周期。
- [ ] PR1/PR2回归通过；按轮场景和不定性疯狂继续标记未交付。
- [ ] #485期限补缺逐条核验；是否关闭该Issue取决于其全部验收，不与本PR自动绑定。

## 7. PR4：累计疯狂、跨日与长期恢复

### 7.1 主案例

采用已核对的累计窗口与基准。一个actor多次受到来自可区分来源的SAN损失，每次均不足以触发临时疯狂，累计达到 `T_period`：

- PR3 后：每次扣值正确，但没有不定性疯狂。
- PR4 后：在规定边界形成不定性疯狂，条件、发作、事件和玩家显示一致。
- 对照：累计 `T_period-1` 不触发；同样损失分布到不同规则窗口分别计算。

使用多个来源避免主案例先撞上PR2习惯化上限。单次/累计同时触发另设交互案例，不能用主案例混测两种成因。

### 7.2 实现步骤

| 步骤 | 实现工作与产物 | 本步验证 |
|---|---|---|
| P4-01 | 完成R4/R5/R6：窗口、基准SAN、阈值/取整、恢复影响、月份换算与条件恢复 | `T_period`替换为具体数值；多次小损失主案例在PR3基线上失败 |
| P4-02 | 复用PR2账本，持久化窗口身份、基准及累计。明确基准取样时机，禁止每次用扣减后的当前SAN重算分母 | 同一损失分成不同次数时按规则得到一致结果；基准不会随损失漂移 |
| P4-03 | 消费权威WorldTime边界，处理跨日、多点推进、时间跳跃和消费延迟；损失归属以其权威事件时刻为准 | 不读玩家time_label或墙钟；延迟消费的前一日事件不计入后一日；不漏算/重复重置 |
| P4-04 | 实现不定性疯狂条件、发作及既有条件交互，按R5决定优先级、升级或共存 | 同一SAN事件不产生互相冲突的状态或超出规则次数的发作；不会误清除临时疯狂/其他条件 |
| P4-05 | 实现已核对的日期/月尺度与恢复条件，复用PR3期限消费者；记录换算策略及规则版本 | 游戏时间到期或满足恢复条件才转变；跨日清零累计不自动治愈；没有月历依据时不擅自固定“一个月=30天” |
| P4-06 | 处理PR2账本到新窗口状态的兼容、旧房间基准缺失、乱序/重复事件与恢复 | 有证据才回填；不能从当前SAN猜窗口起始值；不回溯修改已提交损失或重复触发过去的疯狂 |
| P4-07 | 同步玩家状态/期限投影、叙事上下文和SDK恢复；增加独立来源的跨窗口E2E | 玩家看到累计后果及当前活动状态；重连、改时间文案不改变机制 |
| P4-08 | 完成四PR联合回归、日界线/恢复变异验证及Issue覆盖审计 | 基础损失、习惯化、临时/不定性疯狂相互兼容；列出按轮剩余项，不能提前关闭 #487 |

### 7.3 验收矩阵

| 编号 | 输入/操作 | 必须成立的结果 |
|---|---|---|
| C01 | 同窗口多次小损失累计 `T_period-1` | 不形成不定性疯狂，SAN和账本正确 |
| C02 | 再损失1，累计恰好达到 `T_period` | 规定的疯狂后果只产生一次，玩家显示同步 |
| C03 | 相同损失分到两个规则窗口 | 按各窗口独立阈值判断，不无条件跨窗口相加 |
| C04 | 期间SAN增加/减少，次数不同但已确认累计相同 | 基准与累计遵循R4，不随当前SAN漂移；不实现本计划之外的SAN恢复规则 |
| C05 | 游戏跨日，但现实时间不变；或现实跨日但游戏未推进 | 只跟随权威游戏时间 |
| C06 | 旧窗口事件延迟到新窗口消费，或事件重复/乱序重放 | 使用事件所属窗口；不污染新窗口，不重复累计 |
| C07 | 同次损失同时满足单次与累计阈值 | 按R5给出已核对的共存/升级/优先关系及规定的发作次数 |
| C08 | 不定性疯狂已生效后跨日 | 累计窗口按规则更新，既有疯狂不因清零自动解除 |
| C09 | 日期/月期限或其他恢复条件满足与未满足 | 正确恢复对应状态；明确区分发作结束、恢复检查到期和实际恢复 |
| C10 | 月份换算、跨日/多日跳转、模组终点 | 使用记录的换算策略和绝对边界；不可达期限显式处理 |
| C11 | 阈值触发前后/恢复前后重启，两个actor同时累计 | 事件和状态幂等，窗口基准不重置，actor之间隔离 |
| C12 | PR2旧账本或旧房间缺起始基准 | 兼容策略可审计；有证据才迁移，没有猜测补齐或事后重复惩罚 |
| C13 | 习惯化限制后的损失再进入累计判断 | 累计使用规则确认的最终损失语义，不把原始请求损失重复计入 |
| C14 | SDK重连、组件状态更新、叙事上下文 | 活动状态与期限一致；历史解除状态不复活；隐藏来源和Keeper时间不外泄 |

### 7.4 文件与完成标准

拟新增：framework `tests/test_indefinite_insanity.py`；backend `tests/test_indefinite_insanity_persistence.py`；E2E `tests/indefinite-insanity.e2e.ts`。实现复用前两个疯狂相关PR的账本、条件、时间消费者及投影，不再建立第二份日累计或期限源。

- [ ] C01–C14通过，规则数值/月份策略均已核对。
- [ ] PR1–PR3核心案例仍通过；新旧房间、跨窗口、重启均有真实持久化证据。
- [ ] 规则窗口、发作期限、疯狂状态期限、恢复条件分别验证。
- [ ] 给出四PR覆盖清单与剩余限制；按轮期限未完成时 #487 保持未完成。

## 8. 验证命令与执行时机

以下命令供实施时使用，**本次没有执行**。均在独立 worktree 中运行。拟新增测试文件需先创建；其中规则占位符也须先完成核对。按顺序先聚焦、后必要全量，已通过且代码未变时不重复跑同一套检查。

### 8.1 环境准备

在worktree根目录：

```bash
uv sync --project trpg-backend --locked
npm --prefix trpg-sdk ci
npm --prefix trpg-sdk run build
npm --prefix trpg-frontend ci
npm --prefix e2e ci
```

不复制正在部署的虚拟环境或共享其可写依赖目录。后端项目以editable方式引用相邻framework，必须确认实际导入路径属于当前worktree。

后端测试命令在 `trpg-backend/` 执行。使用临时测试库及确定性provider；如环境有真实语音配置，应在测试进程显式使用 `HOST_SPEECH_PROVIDER=disabled`，不修改部署 `.env`。

### 8.2 每个 PR 的聚焦命令

PR1，工作目录 `trpg-backend/`：

```bash
HOST_SPEECH_PROVIDER=disabled uv run pytest -c pyproject.toml -q \
  ../agent-collaboration-framework/tests/test_actor_resources.py \
  ../agent-collaboration-framework/tests/test_sanity_settlement.py \
  tests/test_sanity_settlement_persistence.py \
  tests/test_issue398_passive_check.py \
  tests/test_adjudication_persistence.py \
  tests/test_rule_match_adjudication.py
```

PR2，同一工作目录：

```bash
HOST_SPEECH_PROVIDER=disabled uv run pytest -c pyproject.toml -q \
  ../agent-collaboration-framework/tests/test_sanity_habituation.py \
  tests/test_sanity_habituation_persistence.py \
  ../agent-collaboration-framework/tests/test_sanity_settlement.py \
  tests/test_sanity_settlement_persistence.py
```

PR3，同一工作目录：

```bash
HOST_SPEECH_PROVIDER=disabled uv run pytest -c pyproject.toml -q \
  ../agent-collaboration-framework/tests/test_temporary_insanity.py \
  ../agent-collaboration-framework/tests/test_actor_conditions.py \
  ../agent-collaboration-framework/tests/test_time_tasks.py \
  ../agent-collaboration-framework/tests/test_time_acceptance.py \
  tests/test_temporary_insanity_persistence.py \
  tests/test_issue398_passive_check.py
```

PR4，同一工作目录：

```bash
HOST_SPEECH_PROVIDER=disabled uv run pytest -c pyproject.toml -q \
  ../agent-collaboration-framework/tests/test_indefinite_insanity.py \
  tests/test_indefinite_insanity_persistence.py \
  ../agent-collaboration-framework/tests/test_sanity_habituation.py \
  ../agent-collaboration-framework/tests/test_temporary_insanity.py \
  tests/test_time_advance.py
```

### 8.3 契约、构建与回归

在 `trpg-backend/` 执行framework Schema和后端DTO导出：

```bash
uv run python -m collaboration_framework.schema_export
HOST_SPEECH_PROVIDER=disabled uv run python scripts/export_schema.py
```

再在worktree根目录执行：

```bash
npm --prefix trpg-sdk run codegen
npm --prefix trpg-sdk run typecheck
npm --prefix trpg-sdk test
npm --prefix trpg-sdk run build
npm --prefix trpg-frontend test -- src/features/character/CharacterBasicInfo.test.tsx src/routes/games/trpg/RoomPage.test.tsx
npm --prefix trpg-frontend run lint
npm --prefix trpg-frontend run build
git diff --check
```

首次生成允许产生预期契约差异，审查并纳入对应PR；在已保存这些变更的工作树上再次生成，`agent-collaboration-framework/schemas/` 与 `trpg-sdk/src/generated/` 应无新增漂移。不能在首次新增契约时要求生成结果相对旧基线没有差异。

每个PR准备合并时，在 `trpg-backend/` 运行受影响两层的完整Python测试与backend CI检查：

```bash
HOST_SPEECH_PROVIDER=disabled uv run pytest -c pyproject.toml -q ../agent-collaboration-framework/tests
HOST_SPEECH_PROVIDER=disabled uv run pytest -c pyproject.toml -q
uv run ruff check .
uv run ruff format --check .
uv run ty check
```

framework新改文件按该项目的规则做lint/格式检查，不借功能PR批量重排无关历史文件。涉及新SQL表、索引、约束或迁移时，除 `test_migrations.py` 外，在专用PostgreSQL测试库验证迁移及并发案例；不要对开发库执行迁移或回退实验。

当前Backend CI的paths未覆盖所有framework改动，Frontend CI也未自动运行Vitest。实施PR应确认本计划要求的检查真正被执行；需要时随受影响PR补最小CI触发/测试步骤，不能把“没有触发的检查”记作通过。

### 8.4 SDK E2E

先完成各PR的拟新增文件及P1-09测试骰输入。在 `e2e/` 目录分别执行：

```bash
E2E_REAL_MODEL=0 HOST_SPEECH_PROVIDER=disabled E2E_ONLY=tests/sanity-settlement.e2e.ts npm run test:e2e
E2E_REAL_MODEL=0 HOST_SPEECH_PROVIDER=disabled E2E_ONLY=tests/sanity-habituation.e2e.ts npm run test:e2e
E2E_REAL_MODEL=0 HOST_SPEECH_PROVIDER=disabled E2E_ONLY=tests/temporary-insanity.e2e.ts npm run test:e2e
E2E_REAL_MODEL=0 HOST_SPEECH_PROVIDER=disabled E2E_ONLY=tests/indefinite-insanity.e2e.ts npm run test:e2e
```

每个PR执行已经实现的相关场景；PR4再做联合E2E回归。脚本会重建其worktree内的 `e2e.db` 并启动自己的后端。测试证明公开调用链，准备夹具时可发布合法测试内容，但不能在发起行动后直接改最终SAN/Condition来制造通过结果。

## 9. 人工演示与每个 PR 的证据包

每个PR保留一个简短演示流程，使用与自动化相同的规则及确定性数据：

| PR | 演示步骤 | 应看到的变化 |
|---|---|---|
| PR1 | 打开SAN=60角色卡→触发初见规则→固定失败/损失4→接受→刷新/重连 | 确认前60，确认后56，重连仍56；后续叙事与状态一致 |
| PR2 | 在测试模组连续触发同来源4、4、3→切换来源→重连 | 56→54→54；新来源独立扣值，旧额度不因重连清零 |
| PR3 | 触发已核对的单次疯狂案例→处理后续检定→推进对应期限→重连 | 临时疯狂/发作出现；各自按规则结束；无关条件保留 |
| PR4 | 同窗口多次小损失跨阈值→跨日→达恢复条件→重连 | 不定性疯狂出现；跨日累计更新但状态不被误清除；恢复正确 |

证据记录模板：

```text
PR / 案例编号：
修复前 SHA / 修复后 SHA：
模组 ID、版本、Rule/Check 来源：
规则书依据（需要时）：
初始 SAN / 条件 / 游戏时间 / 来源累计：
固定输入和骰子（区分D100、损失、后续检定、发作与时长）：
修复前失败断言及实际值：
修复后数据库状态 / 规范事件 / PlayerView / 页面结果：
重复提交与恢复结果：
执行命令、退出码、通过数、跳过项：
变异内容、应失败测试、恢复后的结果：
剩余范围、兼容策略及部署注意事项：
```

证据用新建测试数据，避免把真实房间聊天、密钥或完整本地配置写入PR。截图不能替代事件计数、状态及数据库恢复证据。

## 10. 合并、部署与完成判定

| PR | 合并时应成立 | 仍未交付 |
|---|---|---|
| PR1 | #484所有资源能力与 #486基础SAN结算均有消费者和恢复证据 | 来源上限、疯狂、最大SAN、战斗 |
| PR2 | 同来源上限真实生效，来源/历史兼容有明确方案 | 临时与不定性疯狂 |
| PR3 | 已核对的临时疯狂、发作、小时期限与模组事件链完整 | 累计疯狂与按轮期限 |
| PR4 | 累计窗口、不定性疯狂、日期/月尺度及恢复规则完整 | E6b与按轮期限，以及本计划范围外的C0/战斗等能力 |

部署每个PR前核对“当前运行版本→待部署版本”的实际差异，检查迁移、持久化形状、模块版本、SDK产物和在途Check。新增状态若旧程序无法读回，不能仅凭 `git switch` 声称可回滚；需要已验证的读取兼容或数据恢复方案。数据库恢复只对测试副本演练。

单次部署后的冒烟分别检查：服务就绪、正式模组读取、目标案例的新房间、升级前在途Check恢复、WS重连、角色卡/条件显示。服务启动正常只证明启动，不代表规则正确。

按轮后续PR的最小案例仍保留：固定持续3轮，前2轮未到期，第3轮规定边界结束，断线/重启不重置计数；只有真实E6b回合结构可驱动它。四个串行PR不以普通行动次数或WorldTime点替代这个能力。

最终关闭条件：#484/#486按PR1全范围验收；#485按自身剩余清单复核；#487在四PR及按轮剩余项全部满足后再关闭。本文不创建PR、不更新Issue、不宣称任何未执行测试已通过。

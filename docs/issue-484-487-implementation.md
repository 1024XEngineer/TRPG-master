# #484–#487 实现与验证记录

基线 `98a9aba5357fba507047ad9dd1f478d7f27cfc52`。按用户 2026-09-13 的最新要求，四阶段均进入同一条本地分支 `feat/issue-484-487-capability-completion`，不创建远程 PR。实现及数据库测试在独立工作区进行，部署目录在验收前保持原版本。

## PR1：资源与 SAN 结算

- 主红测：`test_failed_sanity_check_commits_loss_before_resuming_parent` 在基线上失败于 `60 != 56`；通过正式《追书人》规则和 SQL Store 复现。
- `fixed/dice` 封闭数量；当前 actor 的 HP/SAN/MP/Luck/Mythos 增减；非负资源下界为 0，HP 保持既有无下界策略，不引入最大值。
- 最终确认后先应用通用资源效果，再发隐藏的规范 `actor.sanity_loss`；四种成功采用 success_loss，两种失败采用 failure_loss，符合 #486 约定。
- 资源事件含骰面、请求/实际 delta、前后值及原因；规范 SAN 事件关联 Check、规则和固定模组版本。公开投影不携带隐藏规则来源。
- 新表 `engine_randomness` 只持久化私有随机依据，按房间和稳定命令/Check 版本取一次。检定业务事务失败后，新 Store、新 request 仍按同一 Check/版本恢复骰子；普通规则动作按同一 request ID 恢复。正式随机源使用版本化 HMAC counter 和拒绝抽样。测试骰源支持有限序列与按骰型有限队列。
- 新增迁移 `l5m6n7o8p9q0`。部署执行与恢复点见末尾。回退只删新表，不改历史资源、事件或角色数据；回退旧功能不会撤销已扣 SAN。
- 首轮 framework 全量发现既有 prompt 版本断言落后于 v10，及旧 schema 文案漂移；同步断言与生成产物。普通 AdjudicatedCheckStep 保持原行为；原 #475 失败案例补足新增损失骰输入，NPC 行为断言不变。

已执行的验证（后续追加最终结果）：

| 验证 | 结果 |
|---|---|
| 初始资源/SAN/注册表聚焦 | 64 passed |
| SAN SQL + SQLite 迁移 | 15 passed |
| framework 全量（最终） | 667 passed |
| 后端全量 | 764 passed，23 skipped，3 warnings |
| 静态检查 | ruff / ty 均通过 |
| 资源写入变异 | 删除写入后 SAN 主案例失败，恢复后全量通过 |
| SDK 类型、测试、构建 | 39 passed，构建成功 |
| 角色卡/RoomPage | 90 passed；lint/build 成功 |
| SDK→WS→真实后端→重连 | SAN 60→56；1 passed |
| PostgreSQL 16 新迁移往返 | upgrade、downgrade 到上一版、upgrade 成功 |
| PostgreSQL SAN 故障与并发 | 3 passed |

后端测试复用的 `_create_building_room` 曾在一个 flush 中无关系地插入 Room、Player、Character，SQLite 未启用外键时掩盖了问题；现按外键父级顺序 flush。默认测试库仍是独立临时 SQLite，专用 PostgreSQL 用 `TRPG_TEST_DATABASE_URL` 指定。

SDK E2E 命令：

```bash
E2E_REAL_MODEL=0 HOST_SPEECH_PROVIDER=disabled \
E2E_ONLY=tests/sanity-settlement.e2e.ts \
E2E_DICE_BY_SIDES='{"100":[81],"6":[4]}' npm --prefix e2e run test:e2e
```

后端全量的警告包括既有 Starlette TestClient 弃用提示及两个 WebSocket 测试结束时的 aiosqlite 工作线程关闭提示；本次没有测试失败。未把跳过项算作通过。

## PR2：稳定来源和习惯化

第一步检查点：`a0a9b6b`。主红测在第一步版本得到 SAN=49（期望54），修复后三次请求4/4/3实际扣4/2/0，账本累计6。

来源注册随内置新版本发布：追书人3.0.13、银之锁3.0.5、常暗之厢3.0.2；旧数据库 ModuleVersion 保持不可变。追书人的单只/群体食尸鬼共享 coc7.ghoul；没有根据显示名合并来源。旧3.0.12等已知规则使用固定版本映射。

账本只消费 actor.sanity_loss，通用资源事件不重复计入；保存请求/实际、before/after、来源、Check身份、版本及世界小时。上限在通用资源写入之前约束，零损失也追加唯一事实。发展阶段按稳定 phase_id 衰减累计1，重复不再衰减，不退款。

历史兼容：缺账本时 Store 提供原始历史供适配器补账，只重建能证明的规范事实；旧事实没有世界小时则保持未知。没有规范事实的旧历史标记 legacy_gap，遇到有上限来源拒绝继续，须通过规则拥有的 coc7.acknowledge_sanity_history 明确基线及原因。没有从当前SAN猜历史，也没有自动把未知历史当0。人工确认不是本次测试已完成的事项。

已验证：8项引擎来源行为、14项SQL/发布回归、5项独立PostgreSQL事务测试，SDK三次检定及重连1项；移除额度约束后主案例失败，恢复后通过。最终 framework 675 passed。ruff与ty通过；没有新增数据库表，私有快照字段缺省兼容。

## PR3：临时疯狂、发作与小时生命周期

第二步检查点：`90b1771`。主红测在第二步版本中单次扣5后直接resolved，没有INT；现在扣值后保存追加INT决定及原始父结果，父Agenda等待同一决定。INT成功进入临时疯狂，失败保留损失但不疯狂；追加INT不允许幸运/推动。

临时状态与概括发作分别抽取并保存期限，使用隐藏TimeTask及绝对occurrence。实际时间推进先消费到期条件，再继续规则。新的每日time_point引用只绑定一次绝对日期；旧引用保留“下次匹配点”兼容语义。安全休息和发作中断由规则拥有的动作完成，提前解除同步取消任务。结束疯狂不清除模组另加的昏迷。

真实追书人：SAN损失5→INT成功→actor.temporary_insanity→sent_to_asylum及unconscious，SDK重连仍有对应状态；没有硬编码该Rule ID。概括发作采用受控类型，仅记录机械状态，不自动执行暴力、逃离或物品损失。发作期间实际SAN损失为0；潜伏期间的新损失直接产生新发作。

按轮模式明确报INSANITY_ROUNDS_UNSUPPORTED，已提交SAN保持唯一；模组终点之后的期限拒绝整个条件提交。恢复使用原抽样依据，事务失败不会留下半份Condition或任务。

PlayerView仅投影活动条件、安全类型名称与相对剩余小时，绝对时钟、来源及任务引用保留私有。角色卡随WS更新及解除。SDK原有手写AgentSelfActor同步引用生成的条件DTO。SDK场景发现叙事验证器无法将结构化结果放入集合：已改为规范JSON比较，并使声明契约支持对应JSON值；相同对象键顺序不影响比较，伪造时长拒绝。

验证：framework 690 passed（含新增13项临时机制案例），SQL/发布16 passed；SDK完整追书人链1 passed；SDK单元39 passed；角色卡/RoomPage 91 passed；前端lint/build、SDK类型及构建通过。移除到期消费者后小时主案例失败，恢复后通过。PostgreSQL 7 passed。无新增表，旧快照缺省可读；含新待决后果的快照应由本版本继续处理，不能只回退代码并宣称可无损读写新状态。


## PR4：累计窗口、不定性疯狂和月度恢复

第三步检查点：`0212bd3`。红测在第三步版本连续损失4、4、3、1后 SAN=48，却没有不定性疯狂。现在窗口起始60、实际累计12时直接产生一次不定性疯狂及概括发作，无多余INT；移除累计判断的变异会使该主案例失败。

新房间初始化起始基准，SAN增加不移动该基准；规范损失在来源封顶/下界约束后才累计。明确支持Keeper安全休息窗口和作者声明的世界日窗口。旧窗迟到/重复事实不污染当前窗，两个actor分别累计。跨日和安全休息不会解除不定性疯狂；同次单次与累计阈值优先不定性；已有临时状态升级时取消其小时任务。

月度治疗由 `coc7.start_treatment` 和 `coc7.review_treatment` 执行。显式公历锚点、真实TimeTask/occurrence及持久化疗程共同决定复查时间；到期仍保留疯狂，只开放检查。私护/机构、成功后SAN恢复检查、无进展、恶化停月、外来创伤中断、新疗程和发展阶段明确恢复均有消费者。资源增减复用通用Effect，治疗SAN收益上限由CoC7计算后交给通用执行器，保留原骰面及请求/实际值。

玩家仅看到活动状态、相对小时及“治疗中/可复查/治疗中断”；没有把复查日期冒充疯狂结束日期，也没有公开历史来源、日历锚点或任务ID。SDK重连恢复SAN48与不定性疯狂，临时状态不会凭空出现。

已执行：本步28个框架案例，另补1个明确历史确认案例；完整framework 719 passed；本步SQLite恢复2 passed；四阶段PostgreSQL 9 passed；SDK39 passed；角色卡/RoomPage92 passed；SDK和前端构建、前端lint及后端ruff/format/ty通过。四条SDK E2E分别通过（每条1 passed）。后端最终全量结果在末尾记录。

| 计划验收范围 | 核心证据文件 |
|---|---|
| PR1 S01–S16 资源和最终SAN | framework `test_actor_resources.py`、`test_sanity_settlement.py`；SQL `test_sanity_settlement_persistence.py`；SDK `sanity-settlement.e2e.ts` |
| PR2 H01–H12 来源及历史 | framework `test_sanity_habituation.py`；SQL `test_sanity_habituation_persistence.py`；SDK `sanity-habituation.e2e.ts` |
| PR3 T01–T14 临时疯狂和期限 | framework `test_temporary_insanity.py`、既有conditions/time任务测试；SQL `test_temporary_insanity_persistence.py`；SDK `temporary-insanity.e2e.ts` |
| PR4 C01–C14 累计及恢复 | framework `test_indefinite_insanity.py`、`test_sanity_treatment.py`；SQL `test_indefinite_insanity_persistence.py`；SDK `indefinite-insanity.e2e.ts` |
| 玩家展示/叙事声明 | `CharacterBasicInfo.test.tsx`、`RoomPage.test.tsx`；backend `test_action_plan_narrator.py` |

后端CI现在覆盖framework变更，执行框架全量并在PostgreSQL运行四个SQL穿行测试文件；前端CI增加Vitest执行。生成契约及SDK保持一致。测试使用隔离环境、独立数据库与仅test环境可注入的有限骰列，未修改开发环境的随机或语音配置。

## 作者接入和旧房间边界

新规则的SAN检查通过 `success_loss`、`failure_loss`、可选 `sanity_source` 引用作者注册的稳定来源。规则拥有的动作在 `InvokeRulesetActionStep` 中调用，不能由玩家随意提交效果。示例参数：

```json
{"action_id":"coc7.start_treatment","actor_binding":"actor","parameters":{"treatment_id":"care-1924-1","kind":"private","safe":true}}
{"action_id":"coc7.review_treatment","actor_binding":"actor","parameters":{"treatment_id":"care-1924-1","review_month":1,"safe":true}}
{"action_id":"coc7.safe_rest","actor_binding":"actor","parameters":{"rest_id":"safe-night-1","safe":true,"uninterrupted":true}}
{"action_id":"coc7.investigator_development","actor_binding":"actor","parameters":{"phase_id":"chapter-1","recover_indefinite":true}}
```

这些为Step字段示意，正式模组仍需合法id、next_step_id及触发前提；治疗还需 `sanity_policy.calendar_anchor`。默认内置短篇不会被伪造为已写好数月治疗剧情；新增能力通过合法测试模组和已发布规则变体穿行。

旧房间没有规范SAN历史时保持缺口，带上限的检查明确拒绝（SAN未扣）。规则拥有的 `coc7.acknowledge_sanity_history` 接受 `cutover_id`、`reason` 和逐来源 `habituation` 数值，并防止覆盖已确证账本。实际历史数值必须由Keeper提供；本次没有替16个本地旧房间猜数值或确认历史。固定旧ModuleVersion仍保留原内容；后续若要增加确认/治疗剧情，需合法的新版本与显式迁移方案。新房间直接使用完整新账本。

实现范围仍不包含E6b按轮期限、永久疯狂/退场、完整战斗或发作叙事动作；缺少真实回合能力时明确报错。没有关闭任何Issue、发布PR或推送远端，也没有把自动化测试称为人工规则复核。

## 最终部署与验证记录

最终全量：framework **719 passed**；backend **770 passed、23 skipped、2 warnings**（611.45秒）。后端警告为Starlette/httpx弃用和既有WebSocket测试结束时的SQLAlchemy连接回收提示，无失败。SDK **39 passed**；页面 **92 passed**；专用PostgreSQL **9 passed**；四条SDK E2E各 **1 passed**。ruff、格式、ty、前端lint、两端构建均通过；重新导出Schema与SDK无漂移。

部署预检：原开发库处于 `i2j3k4l5m6n7`，需补既有 `j3k4l5m6n7o8`、`k4l5m6n7o8p9` 和本次 `l5m6n7o8p9q0`，三者均为新增字段/表。私有原始备份 `/tmp/trpg-capability-deployment/before-capability.db` 与迁移演练副本分开保存，未把含真实房间数据的备份加入Git。迁移副本完整性正常；新SQL Store可读16个旧房间、4个历史已决Pending及4个历史Check，16个旧actor均有INT。没有活动Agenda；缺少SAN账本/窗口的16个旧actor保留上述明确兼容边界。

原计划文件保留为规划基线，本文是实施记录。实际同步完成：本地分支 `feat/issue-484-487-capability-completion` 包含四个顺序检查点，前三个为 `a0a9b6b`、`90b1771`、`0212bd3`，第四个为本节所属提交。未创建第二个实现分支，隔离工作区使用detached HEAD；未push或创建远程PR。

同步前的最新开发库恢复点为 `/tmp/trpg-capability-deployment/before-switch.db`。开发库已升级至 `l5m6n7o8p9q0`，quick_check=ok；16个原GameSession保留，内置ModuleVersion从12份增加至15份，旧版本保持原样。后端reloader自动启动新worker，前端Vite进程保持运行；8000/openapi.json、9877/及模组列表接口均200。Vite实际输出包含新恢复状态；本地后端虚拟环境导入的是部署目录内framework。WebSocket PlayerView不属于HTTP OpenAPI，四条SDK重连结果来自同代码的独立E2E服务。

本地SDK已重新构建。`.env`、原计划、`.vscode`内原文件及原PPT均通过同步前后SHA-256一致性检查。原计划内容不变，现纳入本地提交。原有两个未跟踪项（`.vscode/`和PPT）保留，无其他未提交实现改动。

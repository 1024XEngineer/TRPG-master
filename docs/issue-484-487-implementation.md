# #484–#487 实现与验证记录

基线 `98a9aba5357fba507047ad9dd1f478d7f27cfc52`。按用户 2026-09-13 的最新要求，四阶段均进入同一条本地分支 `feat/issue-484-487-capability-completion`，不创建远程 PR。实现及数据库测试在独立工作区进行，部署目录在验收前保持原版本。

## PR1：资源与 SAN 结算

- 主红测：`test_failed_sanity_check_commits_loss_before_resuming_parent` 在基线上失败于 `60 != 56`；通过正式《追书人》规则和 SQL Store 复现。
- `fixed/dice` 封闭数量；当前 actor 的 HP/SAN/MP/Luck/Mythos 增减；非负资源下界为 0，HP 保持既有无下界策略，不引入最大值。
- 最终确认后先应用通用资源效果，再发隐藏的规范 `actor.sanity_loss`；四种成功采用 success_loss，两种失败采用 failure_loss，符合 #486 约定。
- 资源事件含骰面、请求/实际 delta、前后值及原因；规范 SAN 事件关联 Check、规则和固定模组版本。公开投影不携带隐藏规则来源。
- 新表 `engine_randomness` 只持久化私有随机依据，按房间和稳定命令/Check 版本取一次。业务事务失败后，新 Store、新 request 仍恢复同一骰子序列；正式随机源使用版本化 HMAC counter 和拒绝抽样。测试骰源支持有限序列与按骰型有限队列。
- 新增迁移 `l5m6n7o8p9q0`。当前部署尚未执行此迁移。回退只删新表，不改历史资源、事件或角色数据；回退旧功能不会撤销已扣 SAN。
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

## 后续阶段

PR2：来源注册、规范账本、习惯化额度与发展阶段衰减。

PR3：额外 INT 检定、临时疯狂、独立发作记录、小时任务及到期消费。

PR4：稳定累计窗口、不定性疯狂、跨日与按明确月历的治疗恢复。

每阶段后继续补充测试、差异、提交及剩余限制。当前记录不宣称后续阶段已实现，也不宣称已完成人工页面演示或规则人工复核。

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

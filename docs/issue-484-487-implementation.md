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

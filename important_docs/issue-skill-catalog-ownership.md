> 状态：proposal
> 作者：黄女珊
> 日期：2026-07-21

# [Architecture] 明确 Check Candidate Catalog 所有权与注入边界

## 一、动机 / 背景

Module Parser Phase 1 已实现确定性 Validation，并支持通过调用方注入的字符串集合校验 `Checkpoint.skills`：

```python
validate_module_json(payload, skill_catalog=skill_catalog)
```

但当前字段名和接口名不足以准确表达实际需求。根据 `COC7空白卡CY23Final.xlsx`：

1. 角色卡将属性与技能分开保存；
2. 力量 STR、敏捷 DEX 等属于属性，不属于技能表；
3. 侦查、聆听、图书馆使用等属于普通技能；
4. 技艺、格斗、射击、科学、外语、生存等允许专攻或自定义名称；
5. 技能检定和属性检定使用相似的成功等级，但取值来源不同。

当前 Demo 同时存在：

```json
{"skills": ["spot_hidden"]}
```

以及：

```json
{"skills": ["strength"]}
```

`spot_hidden` 是技能检定，`strength` 实际是力量属性检定。因此，当前 `Checkpoint.skills` 已经承担了“所有合法检定候选”的含义，而不是严格意义上的 Skill ID 列表。

如果继续只设计 Skill Catalog，会出现两种错误选择：

- 严格按技能表校验时，当前 `strength` 会被拒绝；
- 把 `strength` 当作 Skill 加入目录时，会混淆 Runtime 应从属性还是技能中取值。

本 Issue 将原“Skill Catalog”问题修正为更准确的 **Check Candidate Catalog** 问题。

## 二、核心概念

### 2.1 Check Candidate Catalog

按 `world_ref` 提供当前 Ruleset 全部合法检定候选的只读目录：

```text
Check Candidate Catalog (coc-7e)
├── Attributes
│   ├── str
│   ├── con
│   ├── siz
│   ├── dex
│   ├── app
│   ├── int
│   ├── pow
│   ├── edu
│   └── luck
│
├── Skills
│   ├── spot_hidden
│   ├── listen
│   ├── library_use
│   ├── locksmith
│   └── psychology
│
└── Specialized Skills
    ├── fighting:brawl
    ├── firearms:handgun
    ├── science:biology
    ├── art_craft:photography
    └── language_other:japanese
```

它回答：

> 某个 ID 是否是当前 Ruleset 中合法的检定候选？它属于属性、普通技能还是专攻技能？

### 2.2 Checkpoint 候选

当前 Phase 1 字段仍然是：

```python
CheckpointSpec.skills: tuple[str, ...]
```

但建议将其 Phase 1 语义明确为：

> 当前 Checkpoint 允许使用的标准检定候选 ID；由于历史字段名仍叫 `skills`，候选暂时可以是 Skill ID 或 Attribute ID。

### 2.3 Character 能力值

角色的实际能力属于 Character/Runtime，不属于 ModuleContent：

```text
Character.attributes[str] = 60
Character.skills[spot_hidden] = 65
```

Module Parser 不检查具体角色是否拥有技能，也不计算技能值。

## 三、本期范围与明确不做

### 本期范围

确认：

1. Check Candidate Catalog 的所有者；
2. Catalog 是否按 `world_ref` 隔离；
3. Phase 1 `Checkpoint.skills` 的兼容语义；
4. Attribute ID、Skill ID 和专攻 ID 的规范格式；
5. Validation 如何只读验证候选 ID；
6. Runtime 如何根据候选类型选择 Character 取值来源；
7. Catalog 缺失时正式导入是否 blocked；
8. Phase 2 是否使用可判别的 Check Candidate 结构。

### 明确不做

| 不做 | 原因 |
|------|------|
| 立即修改 `contracts/module.py` | Phase 1 Contract 已冻结 |
| 立即将 `Checkpoint.skills` 重命名 | 属于 Phase 2 破坏性 Contract 变更候选 |
| 在 Module Parser 内硬编码 CoC 7e 目录 | Ruleset 数据不归 C 所有 |
| Validation 直接访问数据库 | 确定性校验不应绑定基础设施 |
| 检查玩家是否拥有技能 | 属于 Character/Check Resolver |
| 计算普通/困难/极难结果 | 属于 Runtime Dice/Ruleset |
| 自动修正别名或拼写 | Parser 可以提议规范化，Validation 不静默改值 |
| 完整录入 Excel 的全部技能数据 | 本 Issue 先做架构决策 |
| 修改 Runtime 行为 | 本 Issue 只记录 B/C 边界 |

## 四、关键决策与建议

### 决策 1：Catalog 归 Ruleset / Reference Data 所有

| 选项 | 描述 | 结论 |
|------|------|------|
| Module Parser 维护目录 | C 可直接校验，但会复制规则数据 | ❌ 不采用 |
| Runtime Engine 私有硬编码 | C 无法在不反向依赖 Engine 的情况下校验 | ❌ 不采用 |
| Ruleset / Reference Data 提供只读 Catalog | B/C 使用同一权威来源 | ✅ 建议采用 |

Module Parser 只消费目录；Runtime 通过同一 Ruleset 元数据决定取值和检定方式。

### 决策 2：Catalog 必须按 `world_ref` 隔离

建议能力接口：

```python
class CheckCandidateCatalog(Protocol):
    def candidates_for(self, world_ref: str) -> Collection[str]: ...
```

Phase 1 也可以使用不可变快照：

```python
Mapping[str, frozenset[str]]
```

当前 `skill_catalog: Collection[str] | None` 可作为过渡接口，但文档中应注明它实际接收的是合法检定候选 ID 集合。

### 决策 3：Phase 1 保留字段名，扩正语义

Phase 1 不修改：

```python
CheckpointSpec.skills
```

暂时采用：

```text
Checkpoint.skills = Check Candidate IDs
```

示例：

```json
{"skills": ["spot_hidden", "library_use"]}
```

表示技能候选。

```json
{"skills": ["str"]}
```

表示属性候选。

这是兼容语义，不代表长期 Schema 仍应混合两种类型。

### 决策 4：Catalog 需要保留候选类型

Validation Phase 1 只需要 ID 集合，但生产 Ruleset 不能只有字符串，应能表达：

```python
CheckCandidateDefinition(
    id="str",
    kind="attribute",
)

CheckCandidateDefinition(
    id="spot_hidden",
    kind="skill",
)
```

该定义属于 Ruleset/Reference Data，不进入当前 `contracts/module.py`。

Runtime 解析逻辑应由 B 侧决定：

```text
kind=attribute
→ Character.attributes[id]

kind=skill
→ Character.skills[id] 或 Ruleset 基础值
```

### 决策 5：专攻技能使用“族 + 专攻”规范 ID

角色卡允许技艺、格斗、射击、科学、外语、生存等自定义专攻，因此 Catalog 不能只接受有限字符串枚举。

建议 ID 形式：

```text
art_craft:photography
fighting:brawl
firearms:handgun
science:biology
language_other:japanese
survival:desert
drive:automobile
lore:dreamlands
```

Validation 分两层：

1. 固定候选必须存在于 Ruleset Catalog；
2. 专攻候选的 family 必须是 Ruleset 允许的专攻族，具体 specialization 必须经过注册或明确的规范化策略。

不能简单允许所有未知字符串，否则 Catalog 无法发现 Parser 拼写错误或幻觉。

### 决策 6：标准 Attribute ID 需要 B/C 确认

当前 Demo 使用：

```text
strength
```

角色卡使用规则缩写：

```text
STR
```

候选方案：

| 方案 | 示例 | 优点 | 缺点 |
|------|------|------|------|
| 完整英文名 | `strength` | 易读 | 与规则书缩写、未来 Character 属性键可能不一致 |
| 小写规则缩写 | `str` | 短、稳定、接近 CoC 术语 | 需要统一现有 demo 和数据层 |

**建议**：采用小写规则缩写 `str/con/siz/dex/app/int/pow/edu/luck`，但在 B 侧确认 Character 属性键之前，不修改 `demo-module.json`。

### 决策 7：Validation 只验证候选合法性

Module Validation 负责：

```text
Checkpoint.skills 中每个 ID
∈ world_ref 对应 Check Candidate Catalog
```

不负责：

- 查询具体玩家；
- 判断角色是否拥有技能；
- 读取技能值或属性值；
- 计算基础值；
- 执行 Dice；
- 决定最终采用哪个候选。

当前稳定错误码 `checkpoint.ref.skill_not_found` 可在 Phase 1 保持兼容；Phase 2 再评估是否改为更准确的 `checkpoint.ref.check_candidate_not_found`。

### 决策 8：Catalog Validation 作为非阻塞延期项

当前世界规则、技能、属性和职业数据尚未完成数据库建设，因此现阶段不把 Catalog Validation 作为 Phase 1 后续开发的前置条件。

临时策略：

```text
Phase 1 开发、Demo 和单元测试：
Catalog 已提供 → 执行检定候选合法性校验
Catalog 未提供 → 记录 warning 或使用最小测试快照，继续结构与内部引用校验
                 → 允许 Validation、Publish 和 Runtime 集成继续推进

正式生产发布：
必须取得与 world_ref 对应的权威 Catalog
Catalog 缺失 → blocked，不发布
```

该延期不影响以下开发：Parser、ModuleDraft、确定性内部引用 Validation、Publish、CLI 编排和 Runtime Integration。

数据库或 Ruleset Reference Data 就绪后，恢复本项工作的触发条件为：

- 能按 `world_ref` 查询属性、普通技能和专攻技能；
- 数据项具有稳定标准 ID，并至少能区分 `attribute | skill`；
- B/C 已确认 `str/strength` 和专攻技能 ID 规范；
- Validation 可以通过只读接口或不可变快照取得 Catalog，而不直接绑定数据库实现。

满足条件后，将正式导入策略从“缺失时 warning”切换为“缺失时 blocked”，并补齐合法、非法、专攻和跨 `world_ref` 测试。

### 决策 9：Runtime Phase 1 不重复做静态合法性校验

Phase 1 职责链：

```text
Validation：候选是否属于 Ruleset Catalog
Host：proposed_skills 是否来自可信 Checkpoint 候选
Runtime：proposed_skills 是否属于 Checkpoint.skills
Check Resolver：根据候选类型读取 Character 值并裁定
```

正式 ModuleContent 已通过 Validation，Runtime 不需要在每个动作中重复检查静态 Catalog。

## 五、Phase 2 目标结构候选

Phase 2 可考虑用可判别结构替代混合字符串：

```python
class SkillCheckRef:
    kind: Literal["skill"]
    id: str

class AttributeCheckRef:
    kind: Literal["attribute"]
    id: str
```

Checkpoint 示例：

```json
{
  "check_candidates": [
    {"kind": "skill", "id": "spot_hidden"},
    {"kind": "skill", "id": "library_use"}
  ]
}
```

力量检定：

```json
{
  "check_candidates": [
    {"kind": "attribute", "id": "str"}
  ]
}
```

该结构只是 Phase 2 候选，必须经过 B/C 评审后才能修改共享 Contract。

## 六、当前实现事实

```text
CheckpointSpec.skills: tuple[str, ...]，至少一项
Validation: 可选接收 Collection[str]
Host: proposed_skills 必须属于 PlayerView 中可信 Checkpoint 候选
Runtime: proposed_skills 必须属于 Checkpoint.skills
Runtime: 尚未根据候选类型读取 Character.attributes / Character.skills
```

当前不存在：

- 集中式 Check Candidate Catalog；
- Check Candidate Catalog Protocol；
- 按 `world_ref` 隔离的不可变快照；
- 属性与技能的显式类型信息；
- 专攻 ID 注册/规范化接口；
- Character 能力值与 Check Resolver 的正式接线。

以上 Catalog 相关缺口当前标记为 **非阻塞**；在正式生产发布启用前必须解决。

## 七、验收标准

### 架构决策

- [ ] 确认 Catalog 归 Ruleset / Reference Data 所有
- [ ] 确认 Catalog 按 `world_ref` 隔离
- [ ] 确认 Phase 1 `Checkpoint.skills` 表示检定候选 ID，而不仅是技能
- [ ] 确认候选至少区分 attribute 与 skill
- [ ] 确认 Attribute 标准 ID 使用 `str` 还是 `strength`
- [ ] 确认专攻技能的标准 ID 形式
- [x] Phase 1/Demo 缺少 Catalog 时不阻塞后续开发
- [ ] 确认生产发布缺少 Catalog 时 blocked
- [ ] 确认 Validation 不直接依赖 Engine 或数据库
- [ ] 确认 Runtime/Check Resolver 的 Character 取值职责

### 后续实现验收

- [ ] 数据库或 Ruleset Reference Data 就绪后恢复 Catalog Validation 开发
- [ ] 提供 `world_ref="coc-7e"` 的最小不可变 Check Candidate 快照
- [ ] `spot_hidden` 能被识别为 skill
- [ ] `str` 或团队确认后的等价 ID 能被识别为 attribute
- [ ] 未知固定候选返回稳定错误
- [ ] 合法专攻 ID 能通过，非法 family 被拒绝
- [ ] 相同 Catalog 和 ModuleDraft 始终生成相同 ValidationReport
- [ ] Import Workflow 只注入/查询 Catalog，不复制 Ruleset 数据
- [ ] Runtime 和共享 contracts 不依赖 Module Parser 私有模型
- [ ] Phase 1 不修改 `contracts/module.py`
- [ ] 所有现有测试继续通过

## 八、建议实施拆分

决策通过后拆为：

1. **Phase 1 Check Candidate Snapshot**
   - 定义 Ruleset 私有的只读候选元数据；
   - 提供覆盖 demo 的最小 CoC 7e 快照；
   - 兼容当前 `skill_catalog` 注入参数；
   - 确认并统一 `strength/str`。

2. **Formal Import Catalog Requirement**
   - 等待数据库或 Ruleset Reference Data 达到本 Issue 的恢复条件；
   - 正式导入必须取得 `world_ref` 对应快照；
   - 缺失时 blocked；
   - Phase 1/Demo 在此之前允许 warning 或测试快照继续推进。

3. **Phase 2 Check Candidate Contract**
   - B/C 评审可判别 `skill | attribute` 结构；
   - Parser 将名称和别名规范化为标准 ID；
   - Runtime Check Resolver 按 kind 选择 Character 数据来源。

CLI、数据库 Repository、角色成长计算、Dice 和 Review Pass 不并入本 Issue。

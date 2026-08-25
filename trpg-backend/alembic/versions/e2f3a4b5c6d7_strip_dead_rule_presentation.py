"""剥离 RulePresentationSpec 删除后残留在模组快照里的死字段 (#398)

Revision ID: e2f3a4b5c6d7
Revises: b8c9d0e1f2a3

`2c1162e refactor(contracts): 删除零消费者的 RulePresentationSpec` 把规则级的
`presentation` 从契约里摘掉了。字段本身确实零消费者，摘掉没有行为影响——但
`ModuleVersion.content_json` 存的是**发布期序列化出来的快照**，重构之前每次
`model_dump_json()` 都会把这个没人填过的可选字段当成 `"presentation": null`
一并写进去。

于是"新代码 + 旧库"的组合下有两个症状：

1. `ContractModel` 设了 `extra="forbid"`，旧快照里的死字段现在直接让
   `ModuleContentV3` 解析失败。GameSession 绑着的每一个历史版本都会在运行时
   炸掉，存档等于废了。
2. 内置模组加载器把重新归一化的内容与库里的旧行比对，判定"同一
   (module_id, version) 已存在不同内容"，拒绝静默覆盖，后端 lifespan 启动失败。

注意这不是模组内容变了——fixture 源文件里从来没写过规则级 presentation（两个
内置模组的 JSON 里 `presentation` 各只出现一次，都是顶层的 ModulePresentation），
那些 null 纯粹是序列化产物。所以正确的修法是把快照重新编码成新的序列化形式，而
不是推一个假的模组版本号：升版本只能让加载器走 insert 分支从而绕开症状 2，症状 1
里那些历史版本照样解析不了，存档照样是废的。

为什么 CI 没拦住：pytest 在 `tempfile.mkdtemp()` 的临时空库上 `create_all`
建表（根本不走 alembic），migration job 在全新 postgres 容器的空库上跑，两者都
只覆盖"全新建库"路径，而这个 bug 只存在于"旧数据 + 新代码"的升级路径上。同理，
这条迁移在空库上是 no-op，CI 也不会验证它——要守住得单独加一个"灌旧格式快照 →
跑迁移 → 断言可解析"的回归测试。

实现上刻意不 import `ModuleContentV3`：迁移一旦引用应用层契约，契约的下一次演进
就会把这条历史迁移一起搞挂。这里只用裸 SQL + json，与 b7e4c2d1a6f9 的做法一致。
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 用轻量 table 构造而不是 sa.text()：content_json 在 SQLite 上是 TEXT、在
# PostgreSQL 上是 JSON，声明列类型让 SQLAlchemy 自己处理两边的序列化差异，
# 迁移就不必按方言分支写 CAST。
_module_versions = sa.table(
    "module_versions",
    sa.column("module_id", sa.String),
    sa.column("version", sa.String),
    sa.column("content_json", sa.JSON),
)

_FIELD = "presentation"


def _rules_of(payload: object) -> list:
    if not isinstance(payload, dict):
        return []
    rules = payload.get("rules")
    return rules if isinstance(rules, list) else []


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            _module_versions.c.module_id,
            _module_versions.c.version,
            _module_versions.c.content_json,
        )
    ).all()

    pending: list[tuple[str, str, dict]] = []
    populated: list[str] = []

    for module_id, version, content in rows:
        document = json.loads(content) if isinstance(content, str) else content
        stripped = 0
        for rule in _rules_of(document):
            if not isinstance(rule, dict) or _FIELD not in rule:
                continue
            if rule[_FIELD] is not None:
                # 本次数据里这一支不该发生（全是 null）。真出现了说明有人给规则
                # 填过实际展示内容，那就不是"死字段"了，不能当噪音删掉。
                populated.append(f"{module_id} {version}")
                continue
            del rule[_FIELD]
            stripped += 1
        if stripped:
            pending.append((module_id, version, document))

    if populated:
        raise RuntimeError(
            "迁移已中止：以下快照的 rules[*].presentation 存在非 null 值，"
            f"删除会丢失真实数据，请人工确认后再处理：{sorted(set(populated))}"
        )

    for module_id, version, document in pending:
        connection.execute(
            _module_versions.update()
            .where(
                sa.and_(
                    _module_versions.c.module_id == module_id,
                    _module_versions.c.version == version,
                )
            )
            .values(content_json=document)
        )


def downgrade() -> None:
    """把 `presentation: null` 加回每条规则，还原重构前的序列化形状。"""

    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            _module_versions.c.module_id,
            _module_versions.c.version,
            _module_versions.c.content_json,
        )
    ).all()

    for module_id, version, content in rows:
        document = json.loads(content) if isinstance(content, str) else content
        restored = 0
        for rule in _rules_of(document):
            if isinstance(rule, dict) and _FIELD not in rule:
                rule[_FIELD] = None
                restored += 1
        if not restored:
            continue
        connection.execute(
            _module_versions.update()
            .where(
                sa.and_(
                    _module_versions.c.module_id == module_id,
                    _module_versions.c.version == version,
                )
            )
            .values(content_json=document)
        )

"""把时段/终点字段补进存量模组快照的序列化形状 (#415)

Revision ID: a2c5e8b1d3f4
Revises: f7b9c2d4e6a8

#415 给 `TimePointSpec` 加了 `time_segment` / `label` 两个可选字段，给
`ModuleTimePolicySpec` 加了 `terminal_point`。三个都是可选、都有默认值，所以
**旧快照在新代码下解析正常**——存档没事。

出问题的是内置模组加载器：它把重新归一化的内容与库里的旧行整体比对，判定
「同一 (module_id, version) 已存在不同内容」就拒绝静默覆盖。而
`model_dump_json()` 会把这三个没人填过的可选字段一并写成 null，于是同一份模组
内容在新代码下序列化出来多了若干个 key，比对必然不等，后端 lifespan 起不来。

这与 #398 的 e2f3a4b5c6d7 是同一类问题，方向相反：那次是契约**删**字段、旧快照
里多出死字段撞 `extra="forbid"`；这次是契约**加**字段、新序列化多出 null，撞
加载器的相等性检查。修法同样是把快照重新编码成新的序列化形状，而不是推一个假
的模组版本号——升版本只会让加载器走 insert 分支绕开症状，库里那些历史版本的
快照形状照样是旧的，下次再有人做同样的比对还会踩。

（追书人本轮确实升到了 3.0.8，但那是因为规则内容真的变了；银之锁 3.0.1 内容
没有任何改动，不该为了绕开加载器而升版本。）

为什么 CI 拦不住：pytest 在 `tempfile.mkdtemp()` 的临时空库上 `create_all`
建表（根本不走 alembic），migration job 在全新 postgres 容器的空库上跑，两者都
只覆盖「全新建库」路径，而这个 bug 只存在于「旧数据 + 新代码」的升级路径上。
配套回归测试用「灌旧格式快照 → 跑迁移 → 断言加载器判定 unchanged」守住。

实现上刻意不 import `ModuleContentV3`：迁移一旦引用应用层契约，契约的下一次
演进就会把这条历史迁移一起搞挂。这里只用裸 SQL + json，与 e2f3a4b5c6d7 一致。
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a2c5e8b1d3f4"
down_revision: str | Sequence[str] | None = "f7b9c2d4e6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 与 e2f3a4b5c6d7 同样用轻量 table 构造：content_json 在 SQLite 上是 TEXT、
# 在 PostgreSQL 上是 JSON，声明列类型让 SQLAlchemy 处理两边的序列化差异。
_module_versions = sa.table(
    "module_versions",
    sa.column("module_id", sa.String),
    sa.column("version", sa.String),
    sa.column("content_json", sa.JSON),
)

# 新增字段与它们在「没人填过」时的序列化值。
_POINT_FIELDS = ("time_segment", "label")
_POLICY_FIELD = "terminal_point"


def _time_policy_of(payload: object) -> dict | None:
    if not isinstance(payload, dict):
        return None
    policy = payload.get("time_policy")
    return policy if isinstance(policy, dict) else None


def _rewrite(document: object, *, add: bool) -> int:
    """按新形状补齐或按旧形状剥离，返回改动的字段数。"""

    policy = _time_policy_of(document)
    if policy is None:
        # 模组完全没声明 time_policy 时，快照里连这个键都没有——那是
        # `ModuleContentV3` 的默认值在序列化时展开的结果，旧库里一定有。
        # 真遇到没有的，说明这行不是 v3 快照，跳过比猜安全。
        return 0

    changed = 0
    points = policy.get("default_points")
    if isinstance(points, list):
        for point in points:
            if not isinstance(point, dict):
                continue
            for field in _POINT_FIELDS:
                if add and field not in point:
                    point[field] = None
                    changed += 1
                elif not add and point.get(field) is None and field in point:
                    del point[field]
                    changed += 1

    if add and _POLICY_FIELD not in policy:
        policy[_POLICY_FIELD] = None
        changed += 1
    elif not add and policy.get(_POLICY_FIELD) is None and _POLICY_FIELD in policy:
        del policy[_POLICY_FIELD]
        changed += 1
    return changed


def _rewrite_all(*, add: bool) -> None:
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
        if not _rewrite(document, add=add):
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


def upgrade() -> None:
    _rewrite_all(add=True)


def downgrade() -> None:
    """剥掉这三个字段，还原扩展前的序列化形状。

    只剥 null：模组真的声明过 label 或 terminal_point 时，那是作者数据，
    降级不能顺手删掉。
    """

    _rewrite_all(add=False)

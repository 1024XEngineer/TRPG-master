# 显式导入所有 ORM 模型，确保它们注册到 Base.metadata，供建表流程发现。
from app.models.room import Room, RoomPlayer

__all__ = ["Room", "RoomPlayer"]

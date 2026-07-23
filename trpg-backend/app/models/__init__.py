# 显式导入所有 ORM 模型，确保它们注册到 Base.metadata，供建表/Alembic
# autogenerate 发现。导入顺序不影响 SQLAlchemy 建表（外键靠字符串表名解析，
# 不要求被引用的表已经导入），这里按内容库 → 账号 → 房间运行时 → 事件日志 →
# 复盘与导入分组，只是为了可读性。
from app.models.chat import ChatMessage
from app.models.content import (
    Entity,
    Game,
    GameSystem,
    ModuleAsset,
    ModuleCheckpoint,
    ModulePregen,
    ModuleSanTrigger,
    ModuleWinCondition,
    Scenario,
    ScenarioScene,
    World,
)
from app.models.event import CheckResult, Event
from app.models.replay import ModuleImportJob, RoomSession, RoomSummary
from app.models.room import Character, Note, Player, Room
from app.models.user import User, UserCharacterTemplate, UserSession

__all__ = [
    "ChatMessage",
    "CheckResult",
    "Character",
    "Entity",
    "Event",
    "Game",
    "GameSystem",
    "ModuleAsset",
    "ModuleCheckpoint",
    "ModuleImportJob",
    "ModulePregen",
    "ModuleSanTrigger",
    "ModuleWinCondition",
    "Note",
    "Player",
    "Room",
    "RoomSession",
    "RoomSummary",
    "Scenario",
    "ScenarioScene",
    "User",
    "UserCharacterTemplate",
    "UserSession",
    "World",
]

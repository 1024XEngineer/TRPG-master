"""运行时状态访问层（对应 master §4.4.2/§4.4.3）——跨房间隔离唯一入口 + 事件溯源。

🆕 模块拆分设计.md 二次修订：从初版 core/rules 拆出，因为 GameStateRepo/EventLog
是数据访问层，跟 RulesEngine 的"规则怎么算"职责不同，且两者共享同一组表
（rooms/players/characters/notes/events/entity_states）。
"""

from core.state.event_log import EventLog
from core.state.models import Event, EventPayload, GameState, PlayerState
from core.state.repo import GameStateRepo

__all__ = [
    "Event",
    "EventPayload",
    "GameState",
    "PlayerState",
    "EventLog",
    "GameStateRepo",
]

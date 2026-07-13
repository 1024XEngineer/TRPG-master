"""权限唯一出口（通信铁律一）——对应 master §4.5 ViewProjector。"""

from core.view.models import PlayerView, SceneActionMenu
from core.view.projector import ViewProjector

__all__ = ["PlayerView", "SceneActionMenu", "ViewProjector"]

"""Controller 层：`/api/v1/games` + `/api/v1/systems` 路由（issue #77 新增）。

游戏大类 / 规则系统 / 建卡规则目录，三个只读接口都由内容库真实数据支撑
（`Game`/`GameSystem` 表，见 app/core/seed.py 的种子数据），不是固定假数据。
两个前缀分开成两个 APIRouter，是因为 `ruleset` 挂在 `/systems/{systemId}`
下而不是 `/games/{gameId}/systems/{systemId}`——跟 issue §2 的端点表一致。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.dto.game import GameRead, GameSystemRead, RulesetRead
from app.service import room as room_service

games_router = APIRouter(prefix="/games", tags=["games"])
systems_router = APIRouter(prefix="/systems", tags=["games"])


@games_router.get("", response_model=ApiResponse[list[GameRead]])
async def list_games(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[GameRead]]:
    """GET /api/v1/games —— 游戏大类列表。"""
    games = await room_service.list_games(db)
    return ApiResponse.ok(games)


@games_router.get("/{game_id}/systems", response_model=ApiResponse[list[GameSystemRead]])
async def list_game_systems(
    game_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[GameSystemRead]]:
    """GET /api/v1/games/{gameId}/systems —— 大类下的规则系统列表。"""
    try:
        systems = await room_service.list_game_systems(db, game_id)
    except room_service.ModuleNotFoundError as exc:
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    return ApiResponse.ok(systems)


@systems_router.get("/{system_id}/ruleset", response_model=ApiResponse[RulesetRead])
async def get_ruleset(
    system_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[RulesetRead]:
    """GET /api/v1/systems/{systemId}/ruleset —— 建卡所需规则数据。"""
    try:
        ruleset = await room_service.get_ruleset(db, system_id)
    except room_service.ModuleNotFoundError as exc:
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    return ApiResponse.ok(ruleset)

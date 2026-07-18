"""Controller 层：`/api/v1/games` + `/api/v1/systems` 路由（issue #77 新增，
issue #84 S2 补充建卡计算预览接口）。

游戏大类 / 规则系统 / 建卡规则目录，三个只读接口都由内容库真实数据支撑
（`Game`/`GameSystem` 表，见 app/core/seed.py 的种子数据），不是固定假数据。
两个前缀分开成两个 APIRouter，是因为 `ruleset` 挂在 `/systems/{systemId}`
下而不是 `/games/{gameId}/systems/{systemId}`——跟 issue §2 的端点表一致。
"""

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller.dependencies import extract_bearer_token
from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.character import CharacterComputeResult, CharacterPreviewRequest
from app.dto.common import ApiResponse
from app.dto.game import GameRead, GameSystemRead, RulesetRead
from app.service import auth as auth_service
from app.service import character as character_service
from app.service import room as room_service

games_router = APIRouter(prefix="/games", tags=["games"])
systems_router = APIRouter(prefix="/systems", tags=["games"])


async def _require_user_id(authorization: str | None, db: AsyncSession) -> str:
    try:
        me = await auth_service.get_me(db, extract_bearer_token(authorization))
    except auth_service.AuthenticationError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    return me.user_id


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


@systems_router.post(
    "/{system_id}/character/preview", response_model=ApiResponse[CharacterComputeResult]
)
async def preview_character(
    system_id: str,
    payload: CharacterPreviewRequest,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CharacterComputeResult]:
    """POST /api/v1/systems/{systemId}/character/preview —— 建卡过程中的权威
    计算预览（issue #84 S2，路线乙的接缝）：前端把当前草稿（属性/职业/技能
    分配）发上来，后端用 `coc7_rules` 权威算出衍生值 + 技能点预算 + 校验报告，
    前端只负责渲染，不再本地重算 COC7 规则数值。

    鉴权要求登录（跟 `GET /me/character-templates` 一致），但不要求是房间
    成员——建卡向导在正式进房前也可能需要预览（且系统内规则数据本身跟房间
    无关），systemId 只用来确认这个规则系统真实存在（复用 `get_ruleset`
    已有的存在性校验），当前只有内置 COC7 一套规则实现，不按 systemId 分流。
    """
    await _require_user_id(authorization, db)
    try:
        await room_service.get_ruleset(db, system_id)
    except room_service.ModuleNotFoundError as exc:
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    result = character_service.compute_character_preview(payload)
    return ApiResponse.ok(result)

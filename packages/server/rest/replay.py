"""复盘与历史 —— 对应 API 对齐规范 §2.7 + §4.4.6 资产访问控制。"""

from __future__ import annotations

from fastapi import APIRouter, Response

router = APIRouter(tags=["replay"])


@router.get("/users/me/rooms")
async def my_rooms() -> dict:
    """🔒 需登录。复盘的入口——"我参与过的局"列表，按 last_active_at 排序。"""
    raise NotImplementedError("GET /users/me/rooms 待实现")


@router.get("/rooms/{room_id}/summary")
async def room_summary(room_id: str, response: Response) -> dict:
    """🔒 需登录，仅参与过这局的玩家可查。game.ended 后异步生成，未生成完
    返回 202 pending（room_summaries 是 1:1，不需要整套 job 状态机）。"""
    raise NotImplementedError("GET /rooms/{roomId}/summary 待实现（core.ai.SummaryGenerator）")


@router.get("/rooms/{room_id}/replay")
async def room_replay(room_id: str) -> dict:
    """复盘返回全部事件，包括 visibility='private'——复盘阶段悬念不成立，
    跟游玩中"不泄底"铁律不冲突。"""
    raise NotImplementedError("GET /rooms/{roomId}/replay 待实现（core.state.EventLog）")


@router.get("/rooms/{room_id}/assets/{asset_id}")
async def get_asset(room_id: str, asset_id: str) -> dict:
    """校验 assetId 归属 roomId 后返回短期签名 URL；不区分"不存在"和"无权限"，
    统一 404，避免给猜测者透露信息。"""
    raise NotImplementedError("GET /rooms/{roomId}/assets/{assetId} 待实现")

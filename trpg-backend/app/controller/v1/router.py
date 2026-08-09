"""
把 v1 版本下的所有子路由（health/auth/rooms/modules/me/games）汇总成一个
api_router，统一挂 "/api/v1" 前缀。main.py 只需要 `app.include_router(api_router)`
一次，以后新增业务模块时在这里加一行 include_router 就行，不用去改 main.py。
"""

from fastapi import APIRouter

from app.controller.v1 import (
    auth,
    endings,
    games,
    health,
    host_speech,
    inventory,
    me,
    modules,
    portraits,
    rooms,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(rooms.router)
api_router.include_router(portraits.router)
api_router.include_router(host_speech.router)
api_router.include_router(inventory.router)
api_router.include_router(endings.router)
api_router.include_router(modules.router)
api_router.include_router(me.router)
api_router.include_router(games.games_router)
api_router.include_router(games.systems_router)

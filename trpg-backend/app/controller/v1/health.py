"""健康检查接口，给部署平台/监控探活用，不需要鉴权、不碰数据库。"""

from fastapi import APIRouter

from app.dto.common import ApiResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ApiResponse[dict[str, str]])
async def health() -> ApiResponse[dict[str, str]]:
    return ApiResponse.ok({"status": "ok"})

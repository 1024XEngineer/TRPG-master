"""测试共用的账号 / 房间辅助。

issue #106 起创建和加入房间都要求登录，于是几乎每个房间相关的用例开头都要先
「注册一个账号 → 带着 token 建房」。三个测试模块（rooms / characters / ws）
原来各自维护一份 `create_room`，那样要改三遍，所以抽到这里。

⚠️ 不要从 `conftest.py` 里 import 这些（见 conftest 的说明）——那会把 conftest
当成另一个模块再导入一次、连带新建一个引擎，表建在旧引擎上，结果是 no such table。
"""

from httpx import AsyncClient

AUTH_BASE = "/api/v1/auth"
ROOMS_BASE = "/api/v1/rooms"


_account_seq = 0


async def register(
    client: AsyncClient, account: str | None = None, nickname: str = "测试员"
) -> str:
    """注册一个账号，返回登录 token。

    不传 `account` 就自动取一个唯一的（`user1`、`user2`…）。默认唯一而不是默认
    固定，是因为账号重复注册会 409——一个用例里建两个房间、或者一主一客，用固定
    默认值就会莫名其妙地失败在注册那一步，而不是失败在它真正想测的东西上。

    **需要"同一个人"时要显式传同一个 `account`**：房间成员的幂等键是账号，同一个
    账号第二次 join 会被当成重连、原样返回既有身份，而不是加入一个新玩家。
    """
    global _account_seq
    if account is None:
        _account_seq += 1
        account = f"user{_account_seq}"
    response = await client.post(
        f"{AUTH_BASE}/register",
        json={"account": account, "password": "secret1", "nickname": nickname},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["token"]


def bearer(token: str) -> dict[str, str]:
    """账号身份：`Authorization: Bearer <token>`。"""
    return {"Authorization": f"Bearer {token}"}


def reconnect(token: str) -> dict[str, str]:
    """房间身份：`X-Reconnect-Token: <token>`。"""
    return {"X-Reconnect-Token": token}


async def create_room(
    client: AsyncClient,
    token: str | None = None,
    max_players: int = 4,
    room_name: str = "测试房间",
    nickname: str = "房主",
) -> dict:
    """建一个房间。`token` 不传就现注册一个账号。"""
    if token is None:
        token = await register(client)
    response = await client.post(
        ROOMS_BASE,
        json={"roomName": room_name, "nickname": nickname, "maxPlayers": max_players},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


async def join_room(
    client: AsyncClient, room_code: str, token: str, nickname: str = "玩家"
) -> dict:
    """用房间码加入房间，返回房间身份信息。"""
    response = await client.post(
        f"{ROOMS_BASE}/{room_code}/join",
        json={"nickname": nickname},
        headers=bearer(token),
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]

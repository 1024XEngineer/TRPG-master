# 房间管理接口草案

本文档梳理 issue #39 中 MS1 房间管理所需的后端接口。范围覆盖创建房间、通过房间 key 加入房间、等待大厅准备状态、房主开始游戏，以及后续房间内互动内容的隔离边界。

## 设计约定

- API 前缀沿用现有后端骨架：`/api`。
- 所有房间接口均需要已登录玩家身份。当前认证方案未落地时，可在开发阶段用 `X-Player-Id` 作为临时玩家标识；正式实现应替换为会话或 token。
- `room_id` 是服务端内部主键，不用于邀请分享。
- `room_key` 是玩家可分发的加入凭证，只在创建房间和查询本人房间详情时返回给房主。
- MS1 只支持 CoC 和预设模组，接口保留 `world_id` 与 `module_id`，由服务端校验其合法性。
- 同一玩家在同一时间最多处于一个未结束房间，避免上下文串房。

## 核心状态

### RoomStatus

| 值 | 含义 |
| --- | --- |
| `waiting` | 等待大厅中，可加入、可准备 |
| `in_game` | 游戏已开始，MS1 不允许中途加入 |
| `closed` | 房间关闭或游戏结束 |

### RoomMemberRole

| 值 | 含义 |
| --- | --- |
| `host` | 房主，可开始游戏 |
| `player` | 普通玩家 |

### RoomMemberStatus

| 值 | 含义 |
| --- | --- |
| `not_ready` | 未准备 |
| `ready` | 已准备 |

## 数据模型

### RoomSummary

```json
{
  "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
  "name": "雾中小镇",
  "world_id": "coc-7th",
  "module_id": "module_blackwater_creek",
  "status": "waiting",
  "host_player_id": "player_001",
  "max_players": 4,
  "member_count": 2,
  "created_at": "2026-07-14T07:30:00Z"
}
```

### RoomDetail

```json
{
  "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
  "room_key": "7KQ4-P9M2",
  "name": "雾中小镇",
  "world_id": "coc-7th",
  "module_id": "module_blackwater_creek",
  "status": "waiting",
  "host_player_id": "player_001",
  "max_players": 4,
  "members": [
    {
      "player_id": "player_001",
      "display_name": "阿鸣",
      "role": "host",
      "status": "ready",
      "joined_at": "2026-07-14T07:30:00Z"
    },
    {
      "player_id": "player_002",
      "display_name": "林",
      "role": "player",
      "status": "not_ready",
      "joined_at": "2026-07-14T07:32:00Z"
    }
  ],
  "created_at": "2026-07-14T07:30:00Z"
}
```

非房主查询 `RoomDetail` 时，服务端应隐藏或置空 `room_key`，避免加入凭证被无限扩散。

## HTTP 接口

### 创建房间

`POST /api/rooms`

创建者自动成为房主，并加入等待大厅。服务端生成 `room_key`。

请求：

```json
{
  "name": "雾中小镇",
  "world_id": "coc-7th",
  "module_id": "module_blackwater_creek",
  "max_players": 4
}
```

校验规则：

- `name`：1-40 个字符。
- `world_id`：MS1 仅允许 CoC 世界，例如 `coc-7th`。
- `module_id`：必须属于所选世界，且是预设模组。
- `max_players`：2-6，且不小于当前成员数。

响应 `201 Created`：

```json
{
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": "7KQ4-P9M2",
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "waiting",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "not_ready",
        "joined_at": "2026-07-14T07:30:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  }
}
```

常见错误：

- `400 INVALID_ROOM_CONFIG`：世界、模组或人数上限非法。
- `409 PLAYER_ALREADY_IN_ACTIVE_ROOM`：玩家已在另一个等待中或进行中的房间。

### 通过房间 key 加入房间

`POST /api/rooms/join`

请求：

```json
{
  "room_key": "7KQ4-P9M2"
}
```

响应 `200 OK`：

```json
{
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": null,
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "waiting",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "ready",
        "joined_at": "2026-07-14T07:30:00Z"
      },
      {
        "player_id": "player_002",
        "display_name": "林",
        "role": "player",
        "status": "not_ready",
        "joined_at": "2026-07-14T07:32:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  }
}
```

常见错误：

- `404 ROOM_KEY_NOT_FOUND`：房间 key 不存在。
- `409 ROOM_NOT_JOINABLE`：房间不在 `waiting` 状态。
- `409 ROOM_FULL`：房间人数已满。
- `409 PLAYER_ALREADY_IN_ROOM`：玩家已在该房间。
- `409 PLAYER_ALREADY_IN_ACTIVE_ROOM`：玩家已在另一个等待中或进行中的房间。

### 获取我的当前房间

`GET /api/rooms/me`

用于刷新页面后恢复等待大厅或游戏房间入口。

响应 `200 OK`：

```json
{
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": "7KQ4-P9M2",
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "waiting",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "ready",
        "joined_at": "2026-07-14T07:30:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  }
}
```

若玩家不在任何未结束房间中，响应 `200 OK`：

```json
{
  "room": null
}
```

### 获取房间详情

`GET /api/rooms/{room_id}`

仅房间成员可访问。等待大厅和游戏页面都可用该接口做兜底刷新。

响应 `200 OK`：

```json
{
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": null,
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "waiting",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "ready",
        "joined_at": "2026-07-14T07:30:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  }
}
```

常见错误：

- `403 ROOM_MEMBER_REQUIRED`：当前玩家不是该房间成员。
- `404 ROOM_NOT_FOUND`：房间不存在。

### 更新准备状态

`PATCH /api/rooms/{room_id}/members/me`

进入等待大厅后，玩家通过该接口表达准备状态。房主也需要准备；只有全部成员为 `ready` 后，房主才能开始游戏。

请求：

```json
{
  "status": "ready"
}
```

响应 `200 OK`：

```json
{
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": null,
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "waiting",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "ready",
        "joined_at": "2026-07-14T07:30:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  }
}
```

常见错误：

- `400 INVALID_MEMBER_STATUS`：状态不是 `ready` 或 `not_ready`。
- `403 ROOM_MEMBER_REQUIRED`：当前玩家不是该房间成员。
- `409 ROOM_NOT_WAITING`：房间已开始或关闭，不能修改准备状态。

### 房主开始游戏

`POST /api/rooms/{room_id}/start`

仅房主可调用。服务端在同一事务中校验成员准备状态并创建游戏会话。

请求：

```json
{}
```

响应 `200 OK`：

```json
{
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": "7KQ4-P9M2",
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "in_game",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "ready",
        "joined_at": "2026-07-14T07:30:00Z"
      },
      {
        "player_id": "player_002",
        "display_name": "林",
        "role": "player",
        "status": "ready",
        "joined_at": "2026-07-14T07:32:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  },
  "game": {
    "game_id": "game_01JZ7W05Q8XTCH4P4ZD1PXEM2C",
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "status": "running",
    "started_at": "2026-07-14T07:40:00Z"
  }
}
```

常见错误：

- `403 ROOM_HOST_REQUIRED`：当前玩家不是房主。
- `409 ROOM_NOT_WAITING`：房间已开始或关闭。
- `409 ROOM_MEMBERS_NOT_READY`：存在未准备成员。
- `409 ROOM_MEMBER_COUNT_TOO_LOW`：成员数不足 2 人。

## 实时同步接口

### 等待大厅事件流

`WebSocket /api/rooms/{room_id}/lobby`

仅房间成员可连接。用于同步成员加入、离开、准备状态变化、房主开始游戏等大厅事件。HTTP 接口仍是状态变更的来源，WebSocket 只广播结果。

服务端事件：

```json
{
  "type": "room.updated",
  "room": {
    "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
    "room_key": null,
    "name": "雾中小镇",
    "world_id": "coc-7th",
    "module_id": "module_blackwater_creek",
    "status": "waiting",
    "host_player_id": "player_001",
    "max_players": 4,
    "members": [
      {
        "player_id": "player_001",
        "display_name": "阿鸣",
        "role": "host",
        "status": "ready",
        "joined_at": "2026-07-14T07:30:00Z"
      }
    ],
    "created_at": "2026-07-14T07:30:00Z"
  }
}
```

```json
{
  "type": "game.started",
  "room_id": "room_01JZ7VX8J6QY9Q9S6K8H4N2S5X",
  "game_id": "game_01JZ7W05Q8XTCH4P4ZD1PXEM2C"
}
```

连接关闭错误：

- `4403 ROOM_MEMBER_REQUIRED`：当前玩家不是该房间成员。
- `4404 ROOM_NOT_FOUND`：房间不存在。

## 房间内互动隔离

后续叙事、行动、检定、私密信息等游戏中接口必须携带 `room_id` 或通过 `game_id` 反查 `room_id`，并统一执行房间成员校验：

- 非房间成员不能读取房间消息、角色状态、AI 叙事上下文或等待大厅成员列表。
- AI 上下文按 `room_id` 或 `game_id` 分区存储，不能使用全局玩家会话拼接多房间内容。
- WebSocket 广播必须按房间 channel 分发，例如 `room:{room_id}:lobby` 与 `room:{room_id}:game`。
- `private_info.targetPlayer` 只能发送给同一房间中的目标玩家；目标玩家不在该房间时应拒绝生成或丢弃该事件。

## 统一错误响应

建议所有房间接口使用一致的错误结构：

```json
{
  "error": {
    "code": "ROOM_FULL",
    "message": "房间人数已满"
  }
}
```

## 待后续确认

- 正式认证接口与玩家资料接口。
- 世界和预设模组的查询接口，例如 `GET /api/worlds`、`GET /api/worlds/{world_id}/modules`。
- 房主离开房间时是否转移房主。
- 房间关闭、成员退出、踢人等 MS1 之外的管理能力。

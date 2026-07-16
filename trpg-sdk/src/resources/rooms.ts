import type { ApiClient } from '../client';
import type {
  CreateRoomInput,
  CreateRoomResult,
  ModuleSummary,
  SelectModuleInput,
  JoinRoomInput,
  RoomPreview,
  MyRoomSummary,
  RoomSummary,
  ReplayEvent,
} from '../types';

/**
 * `/api/v1/rooms` 和 `/api/v1/modules` 的类型化封装。
 */
export class RoomsResource {
  constructor(private readonly client: ApiClient) {}

  private authenticated(reconnectToken: string): RequestInit {
    return { headers: { 'X-Reconnect-Token': reconnectToken } };
  }

  /** POST /api/v1/rooms — 创建房间，返回 roomId/roomCode/reconnectToken/playerId */
  create(payload: CreateRoomInput): Promise<CreateRoomResult> {
    return this.client.post<CreateRoomResult>('/rooms', payload);
  }

  /** GET /api/v1/modules — 获取可用模组列表 */
  listModules(): Promise<ModuleSummary[]> {
    return this.client.get<ModuleSummary[]>('/modules');
  }

  /** POST /api/v1/rooms/{roomId}/module — 房主选定模组 */
  selectModule(
    roomId: string,
    payload: SelectModuleInput,
    reconnectToken: string
  ): Promise<null> {
    return this.client.post<null>(
      `/rooms/${roomId}/module`,
      payload,
      this.authenticated(reconnectToken)
    );
  }

  /** POST /api/v1/rooms/{roomCode}/join — 用房间码加入房间 */
  join(roomCode: string, payload: JoinRoomInput): Promise<CreateRoomResult> {
    return this.client.post<CreateRoomResult>(`/rooms/${roomCode}/join`, payload);
  }

  /** GET /api/v1/rooms/{roomCode} — 获取房间信息 + 玩家列表 */
  getInfo(roomCode: string): Promise<RoomPreview> {
    return this.client.get<RoomPreview>(`/rooms/${roomCode}`);
  }

  /** POST /api/v1/rooms/{roomId}/start-story — 房主开始游戏 */
  startStory(roomId: string, reconnectToken: string): Promise<null> {
    return this.client.post<null>(
      `/rooms/${roomId}/start-story`,
      null,
      this.authenticated(reconnectToken)
    );
  }

  /** GET /api/v1/me/rooms — 获取我的房间列表 */
  listMyRooms(reconnectToken: string): Promise<MyRoomSummary[]> {
    return this.client.get<MyRoomSummary[]>(
      '/me/rooms',
      this.authenticated(reconnectToken)
    );
  }

  /** POST /api/v1/rooms/{roomId}/end — 房主结束游戏 */
  endGame(roomId: string, reconnectToken: string): Promise<null> {
    return this.client.post<null>(
      `/rooms/${roomId}/end`,
      null,
      this.authenticated(reconnectToken)
    );
  }

  /** GET /api/v1/rooms/{roomId}/summary — 复盘摘要（issue #77 新增，本期未实现） */
  getSummary(roomId: string, reconnectToken: string): Promise<RoomSummary> {
    return this.client.get<RoomSummary>(
      `/rooms/${roomId}/summary`,
      this.authenticated(reconnectToken)
    );
  }

  /** GET /api/v1/rooms/{roomId}/replay — 逐条事件回放（issue #77 新增） */
  getReplay(roomId: string, reconnectToken: string): Promise<ReplayEvent[]> {
    return this.client.get<ReplayEvent[]>(
      `/rooms/${roomId}/replay`,
      this.authenticated(reconnectToken)
    );
  }
}

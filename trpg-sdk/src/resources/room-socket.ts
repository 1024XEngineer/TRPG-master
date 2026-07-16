import type {
  ActionSubmitPayload,
  PlayerReadyPayload,
  RoomJoinPayload,
  ServerToClientEvent,
} from '../types';

export type RoomSocketHandler = (event: ServerToClientEvent) => void;

/** `ServerToClientEvent` 联合类型里所有已知的 `type` 判别值，用于运行时校验
 * 服务端推来的消息（见 isValidServerEvent）。跟 types.ts 里手写的
 * ServerToClientEvent 字面量保持一致——新增 WS 事件时两边都要加。 */
const KNOWN_EVENT_TYPES: ReadonlySet<ServerToClientEvent['type']> = new Set([
  'session.bound',
  'narration.push',
]);

/**
 * 运行时校验服务端推来的消息是不是一个合法的 `ServerToClientEvent`
 * （issue #75 决策 5）：只校验信封形状（有 `type`/`payload`）和 `type` 是
 * 已知判别值，不校验 payload 内部字段——payload 内部字段级的一致性由
 * codegen 的 CI 漂移检查保证，不需要在每条消息的运行时再校验一次。
 * 这不是一个真正的类型守卫（没有对 payload 做逐字段检查），但作为运行时
 * 防线，拦住"未知事件类型"和"结构完全不对"这两类真实会发生的失败模式已经够。
 *
 * 导出（而不是模块私有）是为了能在 room-socket.test.ts 里直接单元测试，
 * 不用为了测这段校验逻辑真的起一个 WebSocket 连接。
 */
export function isValidServerEvent(value: unknown): value is ServerToClientEvent {
  if (typeof value !== 'object' || value === null) return false;
  const { type, payload } = value as { type?: unknown; payload?: unknown };
  return (
    typeof type === 'string' &&
    KNOWN_EVENT_TYPES.has(type as ServerToClientEvent['type']) &&
    typeof payload === 'object' &&
    payload !== null
  );
}

/**
 * `/ws/{roomId}` 的类型化封装（issue #60）。这条通道是独立于 REST API
 * 版本号的实时通道，不走 ApiClient 的 HTTP/`{success,data,error}` 信封，
 * 地址和事件形状跟 trpg-app 原型 services/api-client.ts 的约定一致：
 * 客户端发送 `{type, playerId, payload}`，服务端推送 `{type, payload}`。
 *
 * 单例连接：同一个 roomId 重复调用 connect() 会复用已有（或正在建立中的）
 * 连接，页面切换时不需要关心是否已经连过——跟原型里"房间级单例连接"的
 * 设计保持一致。
 */
export class RoomSocket {
  private ws: WebSocket | null = null;
  private roomId: string | null = null;
  private readonly handlers = new Set<RoomSocketHandler>();

  constructor(private readonly wsBaseUrl: string) {}

  /** 建立（或复用）到 roomId 的连接。token 是账号登录会话（issue #58），
   * 不是房间的 X-Reconnect-Token——两者是独立的身份体系。 */
  connect(roomId: string, token: string): WebSocket {
    if (
      this.ws &&
      this.roomId === roomId &&
      (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)
    ) {
      return this.ws;
    }
    this.ws?.close();

    this.roomId = roomId;
    const url = `${this.wsBaseUrl}/ws/${roomId}?token=${encodeURIComponent(token)}`;
    const socket = new WebSocket(url);
    socket.onmessage = (event) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        console.warn('[RoomSocket] received malformed JSON, dropped', event.data);
        return;
      }
      // 校验不过就丢弃 + warn，不 throw、不断开连接——一条格式不对的消息
      // 不应该让整局游戏的连接挂掉（issue #75 决策 5）。之前这里直接把
      // JSON.parse 的结果断言成 ServerToClientEvent，服务端推来的形状对不上
      // 时会悄无声息地把错误数据当合法事件发给所有订阅者。
      if (!isValidServerEvent(parsed)) {
        console.warn('[RoomSocket] received event with unknown type or invalid shape, dropped', parsed);
        return;
      }
      this.handlers.forEach((handler) => handler(parsed));
    };
    this.ws = socket;
    return socket;
  }

  /** 等到连接真正 OPEN 再发第一条 room.join——避免在 CONNECTING 状态下调用 send() 报错。 */
  waitForOpen(socket: WebSocket): Promise<void> {
    if (socket.readyState === WebSocket.OPEN) return Promise.resolve();
    return new Promise((resolve, reject) => {
      socket.addEventListener('open', () => resolve(), { once: true });
      // 原来这里直接用 WebSocket 的 Event 对象 reject——不是 Error，下游写
      // `.catch(e => e.message)` 只会拿到 undefined。改成传一个真正的
      // Error，原始 Event 保留在 cause 里给需要排查细节的调用方用。
      socket.addEventListener(
        'error',
        (event) => reject(new Error('WebSocket connection failed', { cause: event })),
        { once: true }
      );
    });
  }

  /** 订阅服务端推送事件，返回取消订阅函数。多个页面/组件可以各自订阅、
   * 各自 unsubscribe，不影响底层连接本身（连接跨页面保持，见 connect）。 */
  onMessage(handler: RoomSocketHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  joinRoom(playerId: string, payload: RoomJoinPayload): void {
    this.send('room.join', playerId, payload);
  }

  setReady(playerId: string, payload: PlayerReadyPayload): void {
    this.send('player.ready', playerId, payload);
  }

  startGame(playerId: string): void {
    this.send('game.start', playerId, {});
  }

  submitAction(playerId: string, payload: ActionSubmitPayload): void {
    this.send('action.submit', playerId, payload);
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
    this.roomId = null;
  }

  private send(type: string, playerId: string, payload: unknown): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn(`[RoomSocket] not connected, dropped: ${type}`, payload);
      return;
    }
    this.ws.send(JSON.stringify({ type, playerId, payload }));
  }
}

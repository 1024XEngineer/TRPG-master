import type {
  ActionSubmitPayload,
  CheckRollPayload,
  PlayerReadyPayload,
  RoomJoinPayload,
  RoomRejoinPayload,
  SanCheckRollPayload,
  ServerToClientEvent,
} from '../types';

export type RoomSocketHandler = (event: ServerToClientEvent) => void;

/**
 * 每个 S→C 事件各自的 payload 校验器。
 *
 * 写成以 `ServerToClientEvent['type']` 为键的映射类型（而不是一个事件名数组
 * 加一段公共校验），是为了让 TypeScript 强制约束这张表的完整性：往
 * ServerToClientEvent 联合里加一个新事件却忘了在这里加校验器，编译期就会报错。
 * 这张表同时也是"已知事件类型"的唯一来源，不需要另外维护一份事件名清单。
 *
 * 注意这里刻意只做逐字段的类型检查，不做取值范围/格式校验——目的是让下面的
 * 类型守卫名副其实，而不是复刻一套完整的 schema 校验。SDK 是零运行时依赖的，
 * 不会为此引入 ajv 之类的校验库（issue #75 决策 5）。事件数量涨上去之后
 * （骨架那期要加 13 个 S→C 事件），这张表更适合改成从 JSON Schema 生成。
 */
const PAYLOAD_VALIDATORS: {
  [K in ServerToClientEvent['type']]: (payload: Record<string, unknown>) => boolean;
} = {
  'session.bound': (p) => typeof p.roomId === 'string' && typeof p.playerId === 'string',
  'narration.push': (p) => typeof p.text === 'string',
  // issue #77 新增的 11 个 S→C 事件。只校验必填字段的类型（可空字段不校验）；
  // 嵌套对象（players/player）只做「是不是对象/数组」的浅检查，不深入逐字段。
  'room.state': (p) =>
    typeof p.roomId === 'string' && typeof p.phase === 'string' && Array.isArray(p.players),
  'player.joined': (p) => typeof p.player === 'object' && p.player !== null,
  'turn.begin': (p) => typeof p.playerId === 'string',
  'game.ended': () => true, // reason 可空，没有必填字段
  'view.private': (p) => typeof p.playerId === 'string' && typeof p.text === 'string',
  'check.request': (p) => typeof p.playerId === 'string' && typeof p.skill === 'string',
  'check.result': (p) =>
    typeof p.playerId === 'string' &&
    typeof p.skill === 'string' &&
    typeof p.rollValue === 'number' &&
    typeof p.result === 'string',
  'san.check.request': (p) => typeof p.playerId === 'string',
  'san.check.result': (p) =>
    typeof p.playerId === 'string' &&
    typeof p.rollValue === 'number' &&
    typeof p.sanLoss === 'number' &&
    typeof p.result === 'string',
  'clue.granted': (p) => typeof p.playerId === 'string' && typeof p.clueName === 'string',
  error: (p) => typeof p.code === 'string' && typeof p.message === 'string',
};

/**
 * 运行时校验服务端推来的消息是不是一个合法的 `ServerToClientEvent`。
 *
 * 校验三层：信封形状（是对象、有 `type`/`payload`）→ `type` 是已知判别值 →
 * 该判别值对应的 payload 字段类型正确。第三层是必须的：这个函数向 TypeScript
 * 断言了 `value is ServerToClientEvent`，如果只校验信封就返回 true，
 * `{ type: 'narration.push', payload: {} }` 会被当成合法事件下发，下游
 * 读到的 `payload.text` 是 `undefined`，而类型系统还以为它是 string——
 * 等于用类型守卫的形式对编译器撒谎（PR #76 review 指出）。
 *
 * 导出（而不是模块私有）是为了能在 room-socket.test.ts 里直接单元测试，
 * 不用为了测这段校验逻辑真的起一个 WebSocket 连接。
 */
export function isValidServerEvent(value: unknown): value is ServerToClientEvent {
  if (typeof value !== 'object' || value === null) return false;
  const { type, payload } = value as { type?: unknown; payload?: unknown };
  if (typeof type !== 'string' || !(type in PAYLOAD_VALIDATORS)) return false;
  if (typeof payload !== 'object' || payload === null) return false;
  const validate = PAYLOAD_VALIDATORS[type as ServerToClientEvent['type']];
  return validate(payload as Record<string, unknown>);
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

  /** check.roll —— 玩家请求做一次技能检定（issue #77 新增，后端本期回
   * NOT_IMPLEMENTED 的 error 事件，真实服务端权威掷骰待规则引擎落地）。 */
  rollCheck(playerId: string, payload: CheckRollPayload): void {
    this.send('check.roll', playerId, payload);
  }

  /** san.check.roll —— 理智检定摇骰（issue #77 新增，后端本期回 NOT_IMPLEMENTED）。 */
  rollSanCheck(playerId: string, payload: SanCheckRollPayload): void {
    this.send('san.check.roll', playerId, payload);
  }

  /** room.rejoin —— 断线重连（issue #77 仅铺协议，后端本期回 NOT_IMPLEMENTED）。 */
  rejoin(playerId: string, payload: RoomRejoinPayload): void {
    this.send('room.rejoin', playerId, payload);
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

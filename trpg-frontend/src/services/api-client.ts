// SDK 客户端单例 + 账号会话 token 管理 + 错误信息友好化（issue #66：前端
// 原型接入 trpg-frontend）。原型这里原本手写了一整套 apiRequest/WS 封装
// （外加 mock 模式），现在统一改成调用已经和后端联调过的 trpg-sdk，
// 其余页面组件对这个模块的调用方式（函数名/参数）保持不变。

import { ApiError, createTrpgSdk, type ServerToClientEvent } from 'trpg-sdk';

export { ApiError };

export const sdk = createTrpgSdk({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1'
});

const TOKEN_STORAGE_KEY = 'aidm_token';

let authToken: string | null = localStorage.getItem(TOKEN_STORAGE_KEY);

export function setAuthToken(token: string | null) {
  authToken = token;
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

// 把 ApiError/网络错误翻译成用户能看懂的提示——不要把原始异常直接甩给用户。
// trpg-sdk 的 ApiError.message 已经是后端 DTO/业务校验给出的具体原因
// （比如"账号或密码不正确"），直接用就行，不需要再解析响应体。
export function friendlyErrorMessage(err: unknown, fallback = '操作失败，请稍后重试'): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof TypeError) return '网络连接失败，请检查网络后重试';
  return fallback;
}

// ── WebSocket：房间级单例连接，跨 Lobby→Room 页面导航保持不断 ──
// 底层是 sdk.roomSocket（issue #60），这里只是保留原型页面组件已经在用
// 的函数签名，避免改动调用方。

export function connectWebSocket(roomId: string): WebSocket {
  return sdk.roomSocket.connect(roomId, authToken ?? '');
}

export function waitForWsOpen(socket: WebSocket): Promise<void> {
  return sdk.roomSocket.waitForOpen(socket);
}

export function onWsMessage(handler: (envelope: ServerToClientEvent) => void): () => void {
  return sdk.roomSocket.onMessage(handler);
}

export function sendWsMessage(type: string, playerId: string, payload: unknown) {
  switch (type) {
    case 'room.join':
      sdk.roomSocket.joinRoom(
        playerId,
        payload as { reconnectToken: string; roomCode?: string; nickname?: string }
      );
      return;
    case 'player.ready':
      sdk.roomSocket.setReady(playerId, payload as { ready: boolean });
      return;
    case 'game.start':
      sdk.roomSocket.startGame(playerId);
      return;
    case 'action.submit':
      sdk.roomSocket.submitAction(playerId, payload as { utterance: string });
      return;
    default:
      console.warn(`[WS] unknown event type: ${type}`, payload);
  }
}

export function disconnectWebSocket() {
  sdk.roomSocket.disconnect();
}

// HTTP / WebSocket 客户端封装 —— 真实对接后端（2026-07-13 起不再是 mock）。

const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000'

interface RequestOptions {
  method?: string
  body?: unknown
  headers?: Record<string, string>
}

let authToken: string | null = localStorage.getItem('aidm_token')

export function setAuthToken(token: string | null) {
  authToken = token
  if (token) {
    localStorage.setItem('aidm_token', token)
  } else {
    localStorage.removeItem('aidm_token')
  }
}

export function getAuthToken(): string | null {
  return authToken
}

export class ApiError extends Error {
  status: number
  body: unknown
  constructor(status: number, body: unknown) {
    super(`API Error ${status}: ${JSON.stringify(body)}`)
    this.status = status
    this.body = body
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { method = 'GET', body, headers = {} } = options

  const requestHeaders: Record<string, string> = {
    'Content-Type': 'application/json',
    ...headers,
  }

  if (authToken) {
    requestHeaders['Authorization'] = `Bearer ${authToken}`
  }

  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: requestHeaders,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let errBody: unknown = null
    try {
      errBody = await response.json()
    } catch {
      // ignore
    }
    throw new ApiError(response.status, errBody)
  }

  if (response.status === 204) {
    return undefined as T
  }
  return await response.json()
}

// ── WebSocket ──────────────────────────────────────────
// 全局单例连接：跨 LobbyPage → RoomPage 导航要保持同一条连接不断开，
// connectWebSocket 做成幂等的（同一个 roomId 重复调用直接复用），既解决了
// "换页面要不要重连" 的问题，也顺带解决了 React StrictMode 开发环境下
// effect 会 mount→cleanup→remount 一次导致的重复连接/服务端 accept 冲突。
let ws: WebSocket | null = null
let wsRoomId: string | null = null
type WsHandler = (envelope: { type: string; payload: unknown }) => void
const wsHandlers = new Set<WsHandler>()

export function onWsMessage(handler: WsHandler): () => void {
  wsHandlers.add(handler)
  return () => wsHandlers.delete(handler)
}

export function connectWebSocket(roomId: string): WebSocket {
  if (ws && wsRoomId === roomId && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return ws
  }
  if (ws) {
    ws.close()
  }

  wsRoomId = roomId
  const url = `${WS_BASE_URL}/ws/${roomId}?token=${encodeURIComponent(authToken || '')}`
  ws = new WebSocket(url)
  ws.onmessage = (event) => {
    try {
      const envelope = JSON.parse(event.data)
      wsHandlers.forEach((h) => h(envelope))
    } catch (err) {
      console.error('[WS] failed to parse message', err, event.data)
    }
  }
  ws.onerror = (err) => console.error('[WS] error', err)
  return ws
}

export function waitForWsOpen(socket: WebSocket): Promise<void> {
  if (socket.readyState === WebSocket.OPEN) return Promise.resolve()
  return new Promise((resolve, reject) => {
    socket.addEventListener('open', () => resolve(), { once: true })
    socket.addEventListener('error', (e) => reject(e), { once: true })
  })
}

export function disconnectWebSocket() {
  if (ws) {
    ws.close()
    ws = null
    wsRoomId = null
  }
}

export function sendWsMessage(type: string, playerId: string, payload: unknown) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, playerId, payload }))
  } else {
    console.warn(`[WS] not connected, dropped: ${type}`, payload)
  }
}

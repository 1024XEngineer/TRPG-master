// HTTP 客户端封装 — 后续对接真实后端
// 当前为 mock 模式，所有接口返回占位数据

const BASE_URL = import.meta.env.VITE_API_URL || '/api'

interface RequestOptions {
  method?: string
  body?: unknown
  headers?: Record<string, string>
}

let authToken: string | null = null

export function setAuthToken(token: string | null) {
  authToken = token
}

export function getAuthToken(): string | null {
  return authToken
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

  // Mock mode — return empty data
  if (import.meta.env.VITE_MOCK_API === 'true') {
    console.log(`[API Mock] ${method} ${path}`, body)
    return {} as T
  }

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: requestHeaders,
      body: body ? JSON.stringify(body) : undefined,
    })

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`)
    }

    return await response.json()
  } catch (error) {
    console.error(`[API Error] ${method} ${path}:`, error)
    throw error
  }
}

// WebSocket 连接管理 — 占位
let ws: WebSocket | null = null

export function connectWebSocket(roomCode: string): WebSocket {
  const url = import.meta.env.VITE_WS_URL || `ws://localhost:3001/ws/${roomCode}`

  if (ws) {
    ws.close()
  }

  // 开发阶段不实际连接
  console.log(`[WS] Would connect to: ${url}`)
  ws = null

  // 生产环境：
  // ws = new WebSocket(url)
  // ws.onmessage = (event) => { ... }
  // ws.onclose = () => { ... }

  return null as unknown as WebSocket
}

export function disconnectWebSocket() {
  if (ws) {
    ws.close()
    ws = null
  }
}

export function sendWsMessage(type: string, payload: unknown) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, payload }))
  } else {
    console.log(`[WS] Would send: ${type}`, payload)
  }
}

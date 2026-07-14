import { useNavigate } from 'react-router-dom'
import { useEffect, useState, useRef } from 'react'
import { UserPlus, ArrowLeft } from 'lucide-react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { connectWebSocket, sendWsMessage, onWsMessage, waitForWsOpen, disconnectWebSocket } from '@/services/api-client'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'

// 第一个等待界面：等所有玩家进入房间、都标记"已就绪"，才能一起往下走到
// 背景介绍 + 建卡（见需求：不论房主还是访客，全员到齐才能开始）。
export default function LobbyPage() {
  const navigate = useNavigate()

  // ★ 不要用 useRoomStore(s => ({...})) 这种每次渲染都新建对象的写法——
  // Zustand 的 useSyncExternalStore 会因为引用不相等而判定"变了"，触发无限重渲染。
  const roomId = useRoomStore((s) => s.roomId)
  const isHost = useRoomStore((s) => s.isHost)
  const roomCode = useRoomStore((s) => s.roomCode)
  const playerId = useRoomStore((s) => s.playerId)
  const nickname = useAuthStore((s) => s.nickname)
  const [ready, setReady] = useState(false)
  const [joined, setJoined] = useState(false)
  const [error, setError] = useState('')
  const info = useRoomPlayers(roomCode)
  const advancedRef = useRef(false)

  useEffect(() => {
    if (!roomId || !playerId) return
    let cancelled = false

    const off = onWsMessage((envelope) => {
      if (envelope.type === 'session.bound' && !cancelled) {
        setJoined(true)
      }
    })

    const ws = connectWebSocket(roomId)
    waitForWsOpen(ws)
      .then(() => {
        if (cancelled) return
        sendWsMessage('room.join', playerId, { roomCode, nickname: nickname || '玩家' })
      })
      .catch(() => setError('WebSocket 连接失败'))

    return () => {
      cancelled = true
      off()
      // ★ 这里故意不 disconnectWebSocket()——连接要跨 LobbyPage→RoomPage 导航
      // 保持不断。connectWebSocket 本身是幂等的（同一 roomId 直接复用）。
    }
  }, [roomId, playerId, roomCode, nickname])

  const players = info?.players ?? []
  const allReady = players.length > 0 && players.every((p) => p.ready)

  // ★ 全员就绪后，每个客户端各自轮询到这个状态就自动往下走——没有 WS 广播
  // 可用，只能靠"大家都在轮询同一份真实数据、条件一满足就各自出发"来实现
  // "全员到齐才能开始"，而不是由房主单点触发、广播给其他人。
  useEffect(() => {
    if (allReady && !advancedRef.current) {
      advancedRef.current = true
      navigate('/story')
    }
  }, [allReady, navigate])

  const toggleReady = () => {
    if (!playerId) return
    const next = !ready
    setReady(next)
    sendWsMessage('player.ready', playerId, { ready: next })
  }

  const handleLeave = () => {
    // ★ 不能让"没有 playerId 就直接 return"卡死用户——刷新页面等场景下
    // room-store 可能还没恢复完，但用户始终要有办法离开这个页面（见
    // 2026-07-13 测试报告 P0：返回按钮失效导致的死锁）。
    if (playerId) {
      const msg = isHost ? '确定要解散房间吗？所有成员将被移出。' : '确定要离开房间吗？'
      if (!window.confirm(msg)) return
      disconnectWebSocket()
    }
    navigate('/home')
  }

  return (
    <div className="animate-screen-in px-5 pt-6">
      <button
        onClick={handleLeave}
        className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150 mb-3"
      >
        <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
      </button>
      <div className="flex items-center justify-center gap-2 mb-1">
        <span className="font-mono text-2xl font-bold text-text-primary tracking-[0.15em] bg-card border border-dashed border-border-mid px-4 py-1.5 rounded-sm">
          {roomCode || '------'}
        </span>
      </div>
      <p className="text-center text-xs text-text-muted mb-5">
        {joined ? '等待大厅 · 已连接' : '等待大厅 · 连接中…'}
        {info && ` · ${players.length}/${info.maxPlayers} 人已加入`}
      </p>
      {error && <p className="text-center text-xs text-[#c04040] mb-3">{error}</p>}

      <div className="flex flex-col gap-2">
        {players.length === 0 && (
          <div className="text-center py-6 text-xs text-text-dim">正在获取房间成员…</div>
        )}
        {players.map((p) => {
          const isSelf = p.playerId === playerId
          return (
            <div key={p.playerId} className="flex items-center gap-3 px-3.5 py-3 bg-card border border-border-light rounded-md">
              <div className={`w-10 h-10 rounded-full bg-panel border border-border-mid flex items-center justify-center text-lg flex-shrink-0 ${p.ready ? 'border-brass' : ''}`}>
                {p.ready ? '🔍' : '○'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-text-primary">{p.nickname}{isSelf && ' (你)'}</div>
                <div className="text-xs text-text-muted">{p.isHost ? '房主' : '玩家'}</div>
              </div>
              <span
                className={`text-[11px] font-semibold px-2.5 py-[3px] rounded-[99px] ${
                  p.ready ? 'bg-[rgba(74,138,74,0.12)] text-mold' : 'bg-panel text-text-muted'
                }`}
              >
                {p.ready ? '已就绪' : '未就绪'}
              </span>
            </div>
          )
        })}
      </div>

      <button
        onClick={toggleReady}
        className="w-full mt-3 px-6 py-3 rounded-sm border border-border-mid bg-card text-text-body text-sm font-semibold active:bg-panel transition-all flex items-center justify-center gap-2"
      >
        <UserPlus className="w-4 h-4" />
        {ready ? '取消就绪' : '标记为已就绪'}
      </button>

      <p className="text-center text-xs text-text-muted mt-4">
        {allReady ? '全员已就绪，即将开始…' : '等待所有玩家标记为已就绪'}
      </p>
    </div>
  )
}

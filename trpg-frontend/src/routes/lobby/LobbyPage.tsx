import { useNavigate } from 'react-router-dom'
import { useEffect, useState, useRef } from 'react'
import { UserPlus, ArrowLeft } from 'lucide-react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { connectWebSocket, sendWsMessage, onWsMessage, waitForWsOpen, disconnectWebSocket } from '@/services/api-client'
import { startStory } from '@/services/room'
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
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const nickname = useAuthStore((s) => s.nickname)
  const [ready, setReady] = useState(false)
  const [joined, setJoined] = useState(false)
  const [error, setError] = useState('')
  const [confirmLeave, setConfirmLeave] = useState(false)
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
        sendWsMessage('room.join', playerId, {
          reconnectToken: reconnectToken || '',
          roomCode,
          nickname: nickname || '玩家',
        })
      })
      .catch(() => setError('WebSocket 连接失败'))

    return () => {
      cancelled = true
      off()
      // ★ 这里故意不 disconnectWebSocket()——连接要跨 LobbyPage→RoomPage 导航
      // 保持不断。connectWebSocket 本身是幂等的（同一 roomId 直接复用）。
    }
  }, [roomId, playerId, roomCode, nickname, reconnectToken])

  const players = info?.players ?? []
  // 房主在这个页面上没有"标记已就绪"按钮（只有"开始游戏"），他们用点击
  // 开始游戏本身表达意愿——所以判断"全员就绪"时要把房主排除在外，只看
  // 访客，否则房主自己的 ready 永远是 false，"开始游戏"按钮永远点不了。
  const nonHostPlayers = players.filter((p) => !p.isHost)
  const allReady = players.length > 0 && nonHostPlayers.every((p) => p.ready)
  const [starting, setStarting] = useState(false)

  // ★ 全员就绪只是"可以开始"的前提，不代表自动开始——房主必须主动点"开始
  // 游戏"才真正推进（见反馈：不应该默认自动跳转）。访客端没有这个按钮，
  // 靠轮询 storyStarted 标记跟进，这个标记只有房主点击后才会被置位。
  useEffect(() => {
    if (isHost) return
    if (info?.storyStarted && !advancedRef.current) {
      advancedRef.current = true
      navigate('/room/story')
    }
  }, [info?.storyStarted, isHost, navigate])

  const handleStartStory = async () => {
    if (!roomId || !allReady) return
    setStarting(true)
    await startStory(roomId)
    advancedRef.current = true
    navigate('/room/story')
  }

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
    if (playerId && !confirmLeave) {
      setConfirmLeave(true)
      return
    }
    if (playerId) disconnectWebSocket()
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

      {confirmLeave && (
        <div className="bg-card border border-[#c04040]/30 rounded-md p-3.5 mb-3.5">
          <p className="text-xs text-text-body text-center mb-2.5">
            {isHost ? '确定要解散房间吗？所有成员将被移出。' : '确定要离开房间吗？'}
          </p>
          <div className="flex gap-2">
            <button onClick={() => setConfirmLeave(false)}
              className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium active:bg-border-light">
              取消
            </button>
            <button onClick={handleLeave}
              className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium active:bg-[#a03030]">
              {isHost ? '确认解散' : '确认离开'}
            </button>
          </div>
        </div>
      )}
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
        {info && Array.from({ length: Math.max(0, info.maxPlayers - players.length) }).map((_, i) => (
          <div key={`empty-${i}`} className="flex items-center gap-3 px-3.5 py-3 bg-transparent border border-dashed border-border-mid rounded-md">
            <div className="w-10 h-10 rounded-full border border-dashed border-border-mid flex items-center justify-center text-lg flex-shrink-0 text-text-dim">
              ?
            </div>
            <div className="flex-1 min-w-0 text-xs text-text-dim">等待玩家加入…</div>
          </div>
        ))}
      </div>

      {isHost ? (
        <button
          onClick={handleStartStory}
          disabled={!allReady || starting}
          className={`w-full mt-3 px-6 py-3 rounded-sm text-sm font-semibold transition-all flex items-center justify-center gap-2 ${
            allReady && !starting
              ? 'bg-brass text-white active:bg-brass-dark active:scale-[0.97]'
              : 'bg-border-light text-text-dim cursor-not-allowed'
          }`}
        >
          {starting ? '开始中…' : '开始游戏'}
        </button>
      ) : (
        <button
          onClick={toggleReady}
          className="w-full mt-3 px-6 py-3 rounded-sm border border-border-mid bg-card text-text-body text-sm font-semibold active:bg-panel transition-all flex items-center justify-center gap-2"
        >
          <UserPlus className="w-4 h-4" />
          {ready ? '取消就绪' : '标记为已就绪'}
        </button>
      )}

      <p className="text-center text-xs text-text-muted mt-4">
        {isHost
          ? (allReady ? '全员已就绪，点击开始游戏' : '等待所有玩家标记为已就绪')
          : (info?.storyStarted ? '房主已开始，即将进入…' : '等待房主开始游戏')}
      </p>
    </div>
  )
}

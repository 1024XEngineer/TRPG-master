import { useNavigate } from 'react-router-dom'
import { useEffect, useState, useRef } from 'react'
import { User } from 'lucide-react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { connectWebSocket, sdk, onWsMessage, waitForWsOpen, disconnectWebSocket, friendlyErrorMessage } from '@/services/api-client'
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
  const cancelLeaveRef = useRef<HTMLButtonElement>(null)

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
        sdk.roomSocket.joinRoom(playerId, {
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
  const emptySeatCount = info ? Math.max(0, info.maxPlayers - players.length) : 0
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')

  // 服务端房间预览才是就绪状态的权威源。刷新或重连后用它恢复本人的按钮文案，
  // 同时保留点击后的即时反馈，不必等待下一轮 3 秒轮询。
  const selfReady = players.find((player) => player.playerId === playerId)?.ready
  useEffect(() => {
    if (selfReady !== undefined) setReady(selfReady)
  }, [selfReady])

  useEffect(() => {
    if (!confirmLeave) return
    cancelLeaveRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setConfirmLeave(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [confirmLeave])

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
    // 失败必须复位 starting、并且把原因显示出来。原来这里既没有 catch 也没有
    // finally——后端一旦拒绝（比如房间已经过了大厅阶段会返回 409），按钮就永久
    // 卡在「开始中…」，用户既走不下去也看不到任何原因，只能刷新页面。
    try {
      setStartError('')
      await startStory(roomId)
      advancedRef.current = true
      navigate('/room/story')
    } catch (err) {
      setStartError(friendlyErrorMessage(err, '开始游戏失败'))
    } finally {
      setStarting(false)
    }
  }

  const toggleReady = () => {
    if (!playerId) return
    const next = !ready
    setReady(next)
    sdk.roomSocket.setReady(playerId, { ready: next })
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

  const helperMessage = isHost
    ? allReady
      ? '全员已就绪，点击开始游戏'
      : '等待所有玩家标记为已就绪'
    : info?.storyStarted
      ? '房主已开始，即将进入…'
      : ready
        ? '你已就绪，等待房主开始游戏'
        : '标记就绪后，等待房主开始游戏'

  return (
    <div className="lobby-scene animate-screen-in">
      <img
        className="lobby-scene__background"
        src="/assets/rooms/lobby/background.webp"
        alt=""
        aria-hidden="true"
      />

      <img className="lobby-scene__map" src="/assets/rooms/lobby/map.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__note" src="/assets/rooms/lobby/gather-note.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__poster" src="/assets/rooms/lobby/camp-poster.webp" alt="" aria-hidden="true" />

      <header className="lobby-scene__header">
        <button type="button" className="lobby-scene__back" onClick={handleLeave} aria-label="离开房间">
          <img src="/assets/rooms/create/back-button.webp" alt="" aria-hidden="true" />
        </button>
      </header>

      <main className="lobby-scene__dossier" aria-labelledby="lobby-room-code">
        <img
          className="lobby-scene__dossier-art"
          src="/assets/rooms/lobby/dossier.webp"
          alt=""
          aria-hidden="true"
        />

        <section className="lobby-scene__masthead" aria-label="房间信息">
          <h1 id="lobby-room-code" className="lobby-scene__room-code" aria-label={`房间码 ${roomCode || '未获取'}`}>
            {Array.from(roomCode || '------').map((character, index) => (
              <span
                className={/\d/.test(character) ? 'lobby-scene__room-code-digit' : undefined}
                key={`${character}-${index}`}
              >
                {character}
              </span>
            ))}
          </h1>
          <p className="lobby-scene__connection" aria-live="polite">
            <span className={`lobby-scene__connection-dot ${joined ? 'is-connected' : ''}`} aria-hidden="true" />
            等待大厅 · {joined ? '已连接' : '连接中…'}
            {info && <span> · {players.length}/{info.maxPlayers} 人已加入</span>}
          </p>
          {error && <p className="lobby-scene__connection-error" role="alert">{error}</p>}
        </section>

        <section className="lobby-scene__roster" aria-labelledby="lobby-roster-title">
          <h2 id="lobby-roster-title" className="sr-only">冒险队成员</h2>
          <div
            className="lobby-scene__player-list"
            data-onboarding-target="lobby-players"
            aria-busy={!info}
          >
            {!info && (
              <div className="lobby-player lobby-player--loading" role="status">
                <img className="lobby-player__paper" src="/assets/rooms/lobby/seat.webp" alt="" aria-hidden="true" />
                正在整理冒险队档案…
              </div>
            )}

            {players.map((player) => {
              const isSelf = player.playerId === playerId
              const status = player.isHost ? '房主' : player.ready ? '已就绪' : '未就绪'
              return (
                <article
                  key={player.playerId}
                  className={`lobby-player ${player.ready ? 'is-ready' : ''} ${player.isHost ? 'is-host' : ''}`}
                >
                  <img className="lobby-player__paper" src="/assets/rooms/lobby/seat.webp" alt="" aria-hidden="true" />
                  <span className="lobby-player__avatar" aria-hidden="true">
                    <User />
                  </span>
                  <span className="lobby-player__identity">
                    <strong title={player.nickname}>{player.nickname}{isSelf && '（你）'}</strong>
                    <small>{player.isHost ? '冒险发起人' : '冒险队成员'}</small>
                  </span>
                  <span className={`lobby-player__status ${player.ready ? 'is-ready' : ''} ${player.isHost ? 'is-host' : ''}`}>
                    <img src="/assets/rooms/lobby/status-badge.webp" alt="" aria-hidden="true" />
                    <span>{status}</span>
                  </span>
                </article>
              )
            })}

            {Array.from({ length: emptySeatCount }).map((_, index) => (
              <div className="lobby-player lobby-player--empty" key={`empty-${index}`} data-testid="lobby-empty-seat">
                <img className="lobby-player__paper" src="/assets/rooms/lobby/seat.webp" alt="" aria-hidden="true" />
                <span>等待玩家加入…</span>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="lobby-scene__footer">
        {startError && <p className="lobby-scene__start-error" role="alert">{startError}</p>}

        {isHost ? (
          <button
            type="button"
            onClick={handleStartStory}
            disabled={!allReady || starting}
            data-onboarding-target="lobby-start-story"
            className="lobby-scene__start-action"
            aria-describedby="lobby-action-hint"
          >
            <img src="/assets/rooms/lobby/start-game.webp" alt="" aria-hidden="true" />
            <span className={starting ? 'lobby-scene__start-progress' : 'sr-only'}>
              {starting ? '开始中…' : '开始游戏'}
            </span>
          </button>
        ) : (
          <button
            type="button"
            onClick={toggleReady}
            data-onboarding-target="lobby-ready"
            className={`lobby-scene__ready-action ${ready ? 'is-ready' : ''}`}
            aria-pressed={ready}
            aria-describedby="lobby-action-hint"
          >
            <span aria-hidden="true">◆</span>
            {ready ? '取消就绪' : '标记为已就绪'}
            <span aria-hidden="true">◆</span>
          </button>
        )}

        <p id="lobby-action-hint" className="lobby-scene__action-hint" aria-live="polite">
          <span aria-hidden="true">✥</span>
          {helperMessage}
          <span aria-hidden="true">✥</span>
        </p>
      </footer>

      {confirmLeave && (
        <div className="lobby-leave-dialog" onMouseDown={() => setConfirmLeave(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="lobby-leave-title"
            className="lobby-leave-dialog__paper"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <img
              className="lobby-leave-dialog__art"
              src="/assets/rooms/lobby/leave-dialog.webp"
              alt=""
              aria-hidden="true"
            />
            <span className="lobby-leave-dialog__eyebrow">冒险队档案</span>
            <h2 id="lobby-leave-title">{isHost ? '解散冒险队？' : '离开冒险队？'}</h2>
            <div className="lobby-leave-dialog__divider" aria-hidden="true"><span>◆</span></div>
            <p>{isHost ? '所有成员将被移出当前房间。' : '你将离开当前房间，可使用房间码重新加入。'}</p>
            <div className="lobby-leave-dialog__actions">
              <button ref={cancelLeaveRef} type="button" onClick={() => setConfirmLeave(false)}>继续等待</button>
              <button type="button" className="is-danger" onClick={handleLeave}>
                {isHost ? '确认解散' : '确认离开'}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

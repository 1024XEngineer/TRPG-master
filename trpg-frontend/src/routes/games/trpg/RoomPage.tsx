import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  BookOpen,
  Brain,
  Dice6,
  Heart,
  Map,
  ScrollText,
  SendHorizontal,
  Users,
  X,
} from 'lucide-react'
import type { GameViewPayload } from 'trpg-sdk'
import {
  connectWebSocket,
  disconnectWebSocket,
  onWsMessage,
  sdk,
  waitForWsOpen,
} from '@/services/api-client'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'

interface Message {
  id: string
  kind: 'system' | 'narration' | 'player' | 'check' | 'clue'
  text: string
}

function BottomPanel({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  if (!open) return null
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed bottom-0 left-0 right-0 z-50 max-w-[430px] mx-auto max-h-[72vh] overflow-y-auto bg-card rounded-t-2xl shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 sticky top-0 bg-card border-b border-border-light">
          <h3 className="text-base font-bold text-text-primary">{title}</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center">
            <X className="w-4 h-4 text-text-muted" />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </>
  )
}

function nowId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`
}

export default function RoomPage() {
  const navigate = useNavigate()
  const roomId = useRoomStore((s) => s.roomId)
  const roomCode = useRoomStore((s) => s.roomCode)
  const playerId = useRoomStore((s) => s.playerId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const nickname = useAuthStore((s) => s.nickname)
  const roomInfo = useRoomPlayers(roomCode)
  const [view, setView] = useState<GameViewPayload | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [waiting, setWaiting] = useState(false)
  const [error, setError] = useState('')
  const [panel, setPanel] = useState<'clues' | 'map' | 'actor' | 'members' | null>(null)
  const [confirmExit, setConfirmExit] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastSequenceRef = useRef(0)
  const seenEventsRef = useRef(new Set<string>())

  const appendOnce = (eventId: string | null | undefined, message: Message) => {
    const id = eventId || message.id
    if (seenEventsRef.current.has(id)) return
    seenEventsRef.current.add(id)
    setMessages((current) => [...current, message])
  }

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages])

  useEffect(() => {
    if (!roomId || !playerId) return
    let cancelled = false
    const off = onWsMessage((envelope) => {
      if (envelope.sequence != null) {
        lastSequenceRef.current = Math.max(lastSequenceRef.current, envelope.sequence)
      }
      if (envelope.type === 'session.bound') {
        sdk.roomSocket.rejoin(playerId, {
          reconnectToken: reconnectToken || '',
          lastEventSequence: lastSequenceRef.current,
        })
      } else if (envelope.type === 'game.view') {
        setView(envelope.payload)
        setWaiting(false)
        lastSequenceRef.current = Math.max(
          lastSequenceRef.current,
          envelope.payload.eventSequence
        )
      } else if (envelope.type === 'narration.push') {
        setWaiting(false)
        appendOnce(envelope.eventId, {
          id: nowId('narration'),
          kind: 'narration',
          text: envelope.payload.text,
        })
      } else if (envelope.type === 'player.message') {
        appendOnce(envelope.payload.requestId || envelope.eventId, {
          id: nowId('player'),
          kind: 'player',
          text: envelope.payload.text,
        })
      } else if (envelope.type === 'check.request') {
        appendOnce(envelope.eventId, {
          id: nowId('check-request'),
          kind: 'system',
          text: `需要进行 ${envelope.payload.skill} 检定：${envelope.payload.reason}`,
        })
      } else if (envelope.type === 'san.check.request') {
        appendOnce(envelope.eventId, {
          id: nowId('san-request'),
          kind: 'system',
          text: `需要进行理智检定：${envelope.payload.reason}`,
        })
      } else if (envelope.type === 'check.result') {
        appendOnce(envelope.eventId, {
          id: nowId('check-result'),
          kind: 'check',
          text: `${envelope.payload.skill}：掷出 ${envelope.payload.rollValue}，结果为 ${envelope.payload.result}`,
        })
      } else if (envelope.type === 'san.check.result') {
        appendOnce(envelope.eventId, {
          id: nowId('san-result'),
          kind: 'check',
          text: `理智检定掷出 ${envelope.payload.rollValue}，损失 ${envelope.payload.sanLoss} 点 SAN`,
        })
      } else if (envelope.type === 'clue.granted') {
        appendOnce(envelope.eventId, {
          id: nowId('clue'),
          kind: 'clue',
          text: `获得线索：${envelope.payload.clueName}${envelope.payload.description ? `。${envelope.payload.description}` : ''}`,
        })
      } else if (envelope.type === 'game.ended') {
        appendOnce(envelope.eventId, {
          id: nowId('ending'),
          kind: 'system',
          text: envelope.payload.summary || '本局游戏已经结束。',
        })
        setWaiting(false)
      } else if (envelope.type === 'error') {
        setWaiting(false)
        setError(envelope.payload.message)
      }
    })

    const socket = connectWebSocket(roomId)
    waitForWsOpen(socket)
      .then(() => {
        if (cancelled) return
        sdk.roomSocket.joinRoom(playerId, {
          reconnectToken: reconnectToken || '',
          roomCode,
          nickname: nickname || '玩家',
        })
      })
      .catch(() => setError('实时连接失败，请稍后重试'))

    return () => {
      cancelled = true
      off()
    }
  }, [roomId, playerId, reconnectToken, roomCode, nickname])

  const sendAction = (event?: FormEvent) => {
    event?.preventDefault()
    const utterance = input.trim()
    if (!utterance || !playerId || !view || view.pendingCheck || view.activeEndingId) return
    const clientActionId = crypto.randomUUID()
    appendOnce(null, {
      id: clientActionId,
      kind: 'player',
      text: utterance,
    })
    sdk.roomSocket.submitAction(playerId, {
      clientActionId,
      utterance,
      sourceRevision: view.stateRevision,
    })
    setInput('')
    setWaiting(true)
    setError('')
  }

  const confirmRoll = () => {
    if (!playerId || !view?.pendingCheck) return
    const payload = {
      clientActionId: crypto.randomUUID(),
      checkRequestId: view.pendingCheck.checkRequestId,
      sourceRevision: view.stateRevision,
    }
    if (view.pendingCheck.kind === 'san') {
      sdk.roomSocket.rollSanCheck(playerId, payload)
    } else {
      sdk.roomSocket.rollCheck(playerId, payload)
    }
    setWaiting(true)
    setError('')
  }

  const handleExit = () => {
    disconnectWebSocket()
    navigate('/home')
  }

  if (!roomId || !playerId) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-text-muted">
        房间身份已失效，请重新进入房间。
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-card relative max-w-[430px] mx-auto">
      <header className="flex items-center gap-2.5 px-4 py-2.5 border-b border-border-light bg-page flex-shrink-0">
        <button onClick={() => setConfirmExit(true)} className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center">
          <ArrowLeft className="w-4 h-4 text-text-muted" />
        </button>
        <div className="w-8 h-8 rounded-full bg-[#f3eef8] flex items-center justify-center">📜</div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-text-primary truncate">
            {roomInfo?.moduleTitle || view?.scene.name || '正在载入模组'}
          </div>
          <div className="text-[11px] text-text-muted truncate">
            {view ? view.scene.name : '同步游戏状态中…'}
          </div>
        </div>
        <button onClick={() => setPanel('members')} className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center">
          <Users className="w-4 h-4 text-text-muted" />
        </button>
      </header>

      {confirmExit && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center px-8" onClick={() => setConfirmExit(false)}>
          <div className="bg-card border border-border-light rounded-md p-5 w-full max-w-[300px]" onClick={(event) => event.stopPropagation()}>
            <p className="text-sm text-text-body text-center mb-4">确定退出吗？房间会保留，可稍后继续。</p>
            <div className="flex gap-2">
              <button onClick={() => setConfirmExit(false)} className="flex-1 py-2 rounded-sm bg-panel text-text-muted text-xs">取消</button>
              <button onClick={handleExit} className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs">退出</button>
            </div>
          </div>
        </div>
      )}

      <div className="px-4 py-3 bg-page border-b border-border-light">
        <div className="text-sm font-semibold text-text-primary">{view?.scene.name || '等待 GameView'}</div>
        {view?.scene.playerDescription && (
          <p className="text-xs text-text-muted leading-[1.7] mt-1">{view.scene.playerDescription}</p>
        )}
      </div>

      <main className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
        {messages.length === 0 && view && (
          <div className="text-center py-2">
            <span className="text-[11px] text-text-dim bg-panel px-3.5 py-1 rounded-full">
              游戏状态已恢复 · 版本 {view.stateRevision}
            </span>
          </div>
        )}
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.kind === 'player' ? 'justify-end' : 'justify-start'}`}
          >
            <div className={`max-w-[85%] px-3.5 py-2.5 rounded-md text-sm leading-[1.65] ${
              message.kind === 'player'
                ? 'bg-[#eef6ee] text-text-body'
                : message.kind === 'narration'
                  ? 'bg-[#fdfaf4] border-l-[3px] border-brass text-[#4a4030]'
                  : message.kind === 'check'
                    ? 'bg-[#f3eef8] text-[#604080] font-mono'
                    : message.kind === 'clue'
                      ? 'bg-[#eef3f8] text-[#3f6280]'
                      : 'bg-panel text-text-muted'
            }`}>
              {message.text}
            </div>
          </div>
        ))}
        {waiting && (
          <div className="flex gap-1 items-center px-4 py-3 bg-panel rounded-md self-start">
            {[0, 1, 2].map((index) => (
              <span key={index} className="w-1.5 h-1.5 bg-brass rounded-full animate-bounce" style={{ animationDelay: `${index * 0.2}s` }} />
            ))}
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      {error && <div className="px-4 py-2 text-xs text-[#c04040] bg-[#fff4f4]">{error}</div>}

      {view?.activeEndingId && !view.pendingCheck && (
        <div className="px-4 py-3 border-t border-border-light bg-[#eef6ee]">
          <div className="text-xs font-semibold text-mold">本局已经结束</div>
          <button
            onClick={() => navigate(`/home/my-rooms/review/${roomCode}`)}
            className="w-full mt-2 py-2.5 rounded-sm bg-mold text-white text-xs font-semibold"
          >
            查看复盘
          </button>
        </div>
      )}

      {view?.pendingCheck && (
        <div className="px-4 py-3 border-t border-border-light bg-[#fdfaf4]">
          <div className="flex items-center gap-2">
            <Dice6 className="w-5 h-5 text-brass-dark" />
            <div className="flex-1">
              <div className="text-xs font-semibold text-text-primary">
                {view.pendingCheck.kind === 'san'
                  ? '理智检定'
                  : `${view.pendingCheck.skillId || '技能'}检定`}
              </div>
              <div className="text-[11px] text-text-muted mt-0.5">
                {view.pendingCheck.reason} · 目标 {view.pendingCheck.targetValue}
              </div>
            </div>
            <button onClick={confirmRoll} disabled={waiting} className="px-4 py-2 rounded-sm bg-brass text-white text-xs font-semibold disabled:opacity-50">
              确认掷骰
            </button>
          </div>
          <p className="text-[10px] text-text-dim mt-2">骰值由服务端生成，客户端仅展示结算结果。</p>
        </div>
      )}

      {view && (
        <div className="flex items-center gap-4 px-4 py-2 border-t border-border-light bg-page">
          <div className="flex items-center gap-1.5 flex-1">
            <Heart className="w-3.5 h-3.5 text-mold" />
            <span className="text-[10px] text-text-muted">HP</span>
            <span className="text-xs font-bold font-mono text-mold">{view.actor.currentHp}</span>
          </div>
          <div className="flex items-center gap-1.5 flex-1">
            <Brain className="w-3.5 h-3.5 text-[#7050a0]" />
            <span className="text-[10px] text-text-muted">SAN</span>
            <span className="text-xs font-bold font-mono text-[#7050a0]">{view.actor.currentSan}</span>
          </div>
          <div className="text-[10px] text-text-dim">状态 v{view.stateRevision}</div>
        </div>
      )}

      <div className="flex border-t border-border-light bg-card">
        <button onClick={() => setPanel('actor')} className="flex-1 py-2 text-[10px] text-text-muted flex flex-col items-center gap-1">
          <ScrollText className="w-4 h-4" />人物
        </button>
        <button onClick={() => setPanel('clues')} className="flex-1 py-2 text-[10px] text-text-muted flex flex-col items-center gap-1">
          <BookOpen className="w-4 h-4" />线索
        </button>
        <button onClick={() => setPanel('map')} className="flex-1 py-2 text-[10px] text-text-muted flex flex-col items-center gap-1">
          <Map className="w-4 h-4" />地点
        </button>
      </div>

      <form onSubmit={sendAction} className="border-t border-border-light px-3 py-3 bg-page flex gap-2">
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          disabled={!view || Boolean(view.pendingCheck) || Boolean(view.activeEndingId)}
          placeholder={view?.pendingCheck ? '请先确认检定' : view?.activeEndingId ? '本局已结束' : '输入行动…'}
          className="flex-1 bg-input border border-border-mid rounded-[20px] px-4 py-2.5 text-sm outline-none disabled:opacity-60"
        />
        <button type="submit" disabled={!input.trim() || !view || waiting || Boolean(view.pendingCheck)} className="w-10 h-10 rounded-full bg-brass text-white flex items-center justify-center disabled:opacity-40">
          <SendHorizontal className="w-[18px] h-[18px]" />
        </button>
      </form>

      <BottomPanel open={panel === 'actor'} title={`调查员 · ${view?.actor.name || ''}`} onClose={() => setPanel(null)}>
        {view && (
          <div className="space-y-4">
            <p className="text-sm text-text-muted">{view.actor.occupation || '未设置职业'}</p>
            <div className="grid grid-cols-3 gap-2">
              {Object.entries(view.actor.attributes ?? {}).map(([key, value]) => (
                <div key={key} className="bg-panel rounded p-2 text-center">
                  <div className="text-[10px] text-text-muted">{key}</div>
                  <div className="font-mono font-bold text-text-primary">{value}</div>
                </div>
              ))}
            </div>
            <div className="space-y-1.5">
              {Object.entries(view.actor.skills ?? {})
                .sort(([, left], [, right]) => right - left)
                .map(([skill, value]) => (
                  <div key={skill} className="flex justify-between text-xs py-1 border-b border-border-light">
                    <span className="text-text-muted">{skill}</span>
                    <span className="font-mono font-bold text-text-primary">{value}%</span>
                  </div>
                ))}
            </div>
          </div>
        )}
      </BottomPanel>

      <BottomPanel open={panel === 'clues'} title="已获线索" onClose={() => setPanel(null)}>
        {view?.clues?.length ? (
          <div className="space-y-3">
            {view.clues.map((clue) => (
              <div key={clue.clueId} className="bg-panel rounded-md p-3">
                <div className="text-sm font-semibold text-text-primary">{clue.name}</div>
                <p className="text-xs text-text-muted leading-[1.7] mt-1">{clue.text}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-text-dim text-center py-6">尚未获得线索</p>
        )}
      </BottomPanel>

      <BottomPanel open={panel === 'map'} title="当前场景" onClose={() => setPanel(null)}>
        <div className="bg-panel rounded-md p-4">
          <div className="text-sm font-semibold text-text-primary">{view?.scene.name}</div>
          <p className="text-xs text-text-muted leading-[1.7] mt-1">{view?.scene.playerDescription}</p>
        </div>
        {view?.visibleEntities?.length ? (
          <div className="mt-4 space-y-2">
            <h4 className="text-xs font-semibold text-brass-dark">可见对象</h4>
            {view.visibleEntities.map((entity) => (
              <div key={entity.entityId} className="px-3 py-2 border border-border-light rounded">
                <div className="text-sm text-text-primary">{entity.name}</div>
                {entity.publicDescription && <p className="text-xs text-text-muted mt-1">{entity.publicDescription}</p>}
              </div>
            ))}
          </div>
        ) : null}
      </BottomPanel>

      <BottomPanel open={panel === 'members'} title="房间成员" onClose={() => setPanel(null)}>
        <div className="space-y-2">
          {(roomInfo?.players ?? []).map((player) => (
            <div key={player.playerId} className="flex items-center gap-3 px-3 py-2 bg-panel rounded-md">
              <div className="w-8 h-8 rounded-full bg-card flex items-center justify-center">🔍</div>
              <div className="flex-1">
                <div className="text-sm text-text-primary">{player.nickname}</div>
                <div className="text-[11px] text-text-dim">{player.isHost ? '房主' : '玩家'}</div>
              </div>
            </div>
          ))}
        </div>
      </BottomPanel>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ScrollText } from 'lucide-react'
import type { ReplayEvent, RoomPreview, RoomSummary } from 'trpg-sdk'
import { friendlyErrorMessage } from '@/services/api-client'
import {
  getRoomInfo,
  getRoomReplay,
  getRoomSummary,
  joinRoomByCode,
} from '@/services/room'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'

export default function ReviewPage() {
  const navigate = useNavigate()
  const { roomCode } = useParams<{ roomCode: string }>()
  const nickname = useAuthStore((s) => s.nickname)
  const setRoomIdentity = useRoomStore((s) => s.setRoomIdentity)
  const [room, setRoom] = useState<RoomPreview | null>(null)
  const [summary, setSummary] = useState<RoomSummary | null>(null)
  const [replay, setReplay] = useState<ReplayEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!roomCode) return
    let cancelled = false
    const load = async () => {
      const identity = await joinRoomByCode(roomCode, nickname || undefined)
      setRoomIdentity(identity)
      const [roomInfo, roomSummary, events] = await Promise.all([
        getRoomInfo(roomCode),
        getRoomSummary(identity.roomId),
        getRoomReplay(identity.roomId),
      ])
      if (cancelled) return
      setRoom(roomInfo)
      setSummary(roomSummary)
      setReplay(events)
    }
    load()
      .catch((err) => {
        if (!cancelled) setError(friendlyErrorMessage(err, '加载复盘失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [roomCode, nickname, setRoomIdentity])

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-10">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => navigate('/home/my-rooms')} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel">
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" />
        </button>
        <h2 className="text-lg font-bold text-text-primary">复盘</h2>
      </div>

      <div className="px-5 space-y-4">
        {loading && <p className="text-sm text-text-dim text-center py-10">正在读取本局记录…</p>}
        {error && <p className="text-[11px] text-[#c04040] text-center">{error}</p>}

        {room && summary && (
          <>
            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <div className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-1">{room.roomName}</div>
              <div className="text-sm text-text-muted">{room.moduleTitle || '未知模组'} · 已完成</div>
              {summary.outcome && <div className="text-xs text-mold mt-2">结局：{summary.outcome}</div>}
            </div>

            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3 flex items-center gap-1.5">
                <ScrollText className="w-[14px] h-[14px]" /> 案件回顾
              </h4>
              {summary.summaryText ? (
                <p className="text-sm text-text-body leading-[1.8]">{summary.summaryText}</p>
              ) : (
                <p className="text-sm text-text-dim py-4 text-center">尚未生成复盘摘要</p>
              )}
              {summary.highlights?.length ? (
                <ul className="mt-4 space-y-2">
                  {summary.highlights.map((highlight) => (
                    <li key={highlight} className="text-xs text-text-muted bg-panel rounded px-3 py-2">{highlight}</li>
                  ))}
                </ul>
              ) : null}
            </div>

            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">事件记录</h4>
              {replay.length ? (
                <div className="space-y-2">
                  {replay.map((event) => (
                    <div key={event.id} className="border-l-2 border-border-mid pl-3 py-1">
                      <div className="text-[10px] font-mono text-text-dim">
                        #{event.sequence ?? '—'} · {event.eventType}
                      </div>
                      {typeof event.payload.text === 'string' && (
                        <p className="text-xs text-text-body leading-[1.6] mt-1">{event.payload.text}</p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-text-dim text-center py-4">暂无可见事件</p>
              )}
            </div>

            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">参与调查员</h4>
              <div className="space-y-1.5">
                {room.players.map((player) => (
                  <div key={player.playerId} className="flex items-center gap-3 px-3 py-2 bg-panel rounded-md">
                    <div className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center text-sm">🔍</div>
                    <div className="flex-1">
                      <div className="text-sm font-medium text-text-primary">{player.nickname}</div>
                      <div className="text-[11px] text-text-dim">{player.isHost ? '房主' : '玩家'}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

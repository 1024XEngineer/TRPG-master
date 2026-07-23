import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, ScrollText } from 'lucide-react'
import { getRoomInfo, type RoomPreview } from '@/services/room'
import { friendlyErrorMessage } from '@/services/api-client'

// 复盘摘要目前后端还没有真的生成——这里先展示一段占位文案，模拟设计稿里
// 「复盘摘要异步生成，先 pending 再补上」的体验（见 API 接口对齐规范 §复盘）。
const PLACEHOLDER_RECAP =
  '调查员们循着匿名信的线索来到惠特利旧宅，从铁门上的划痕开始，一路深入宅邸内部。过程中的每一次调查、对话与检定都将被记录进这里——目前后端的复盘摘要生成还在开发中，这段文字只是占位效果。'

export default function ReviewPage() {
  const navigate = useNavigate()
  const { roomCode } = useParams<{ roomCode: string }>()
  const [room, setRoom] = useState<RoomPreview | null>(null)
  const [error, setError] = useState('')
  const [generating, setGenerating] = useState(true)

  useEffect(() => {
    if (!roomCode) return
    getRoomInfo(roomCode)
      .then(setRoom)
      .catch((err) => setError(friendlyErrorMessage(err, '加载复盘失败')))
  }, [roomCode])

  useEffect(() => {
    const timer = setTimeout(() => setGenerating(false), 900)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-10">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => navigate('/home/my-rooms')} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all">
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
        </button>
        <h2 className="text-lg font-bold text-text-primary">复盘</h2>
      </div>

      <div className="px-5 space-y-4">
        {error && <p className="text-[11px] text-[#c04040] text-center">{error}</p>}

        {room && (
          <>
            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <div className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-1">{room.roomName}</div>
              <div className="text-sm text-text-muted">{room.moduleTitle || '未知模组'} · 已完成</div>
            </div>

            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3 flex items-center gap-1.5">
                <ScrollText className="w-[14px] h-[14px]" /> 案件回顾
              </h4>
              {generating ? (
                <p className="text-sm text-text-dim py-4 text-center animate-pulse">复盘摘要生成中…</p>
              ) : (
                <p className="text-sm text-text-body leading-[1.8]">{PLACEHOLDER_RECAP}</p>
              )}
            </div>

            <div className="bg-card border border-border-light rounded-md p-[18px]">
              <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-3">参与调查员</h4>
              <div className="space-y-1.5">
                {room.players.map((p) => (
                  <div key={p.playerId} className="flex items-center gap-3 px-3 py-2 bg-panel rounded-md">
                    <div className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center text-sm flex-shrink-0">🔍</div>
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-text-primary">{p.nickname}</div>
                      <div className="text-[11px] text-text-dim">{p.isHost ? '房主' : '玩家'}</div>
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

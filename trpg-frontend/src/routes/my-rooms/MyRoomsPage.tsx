import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Play, ScrollText, Hash, Plus } from 'lucide-react'
import { listMyRooms, joinRoomByCode, getRoomInfo, type MyRoomSummary } from '@/services/room'
import { friendlyErrorMessage } from '@/services/api-client'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'

const PHASE_LABEL: Record<string, string> = {
  Lobby: '大厅等待中',
  InGame: '游戏进行中',
  Completed: '已完成',
}

// 后端 MyRoomSummary.updatedAt 是 ISO-8601 字符串（pydantic 的 datetime 序列化
// 结果），不是数字时间戳。这里必须先 Date.parse 成毫秒再参与算术——直接拿字符串
// 去减会得到 NaN，最终一路落到 new Date(NaN) 显示成 "Invalid Date"（issue #75
// 引入 codegen 时发现的真实 bug：此前 SDK 手写类型误标成 number，与这里的错误
// 用法互相掩盖，TS 一直没能报出来）。
function formatTime(ts: string): string {
  const parsed = Date.parse(ts)
  if (Number.isNaN(parsed)) return '未知时间'
  const diffMin = Math.round((Date.now() - parsed) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.round(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  return new Date(parsed).toLocaleDateString('zh-CN')
}

// 房间阶段 → 重新进入时该落到哪个页面。
//
// 不含 `Completed`：已完成的房间在下面是单独一个列表、走「查看复盘」按钮
// （`/home/my-rooms/review/:roomCode`），根本不会调到 `handleResume`。放一条
// 到不了的映射进来只会误导人——而且一旦写错路由，谁也发现不了。
const RESUME_ROUTE: Record<string, string> = {
  Lobby: '/room/lobby',
  Building: '/room/ready',
  InGame: '/room/play',
}

export default function MyRoomsPage() {
  const navigate = useNavigate()
  const nickname = useAuthStore((s) => s.nickname)
  const setRoomIdentity = useRoomStore((s) => s.setRoomIdentity)
  const setHost = useRoomStore((s) => s.setHost)
  const [rooms, setRooms] = useState<MyRoomSummary[] | null>(null)
  const [error, setError] = useState('')
  const [resumingCode, setResumingCode] = useState<string | null>(null)

  useEffect(() => {
    listMyRooms()
      .then(setRooms)
      .catch((err) => setError(friendlyErrorMessage(err, '加载房间列表失败')))
  }, [])

  const inProgress = rooms?.filter((r) => r.phase !== 'Completed') ?? []
  const completed = rooms?.filter((r) => r.phase === 'Completed') ?? []

  const handleResume = async (room: MyRoomSummary) => {
    setResumingCode(room.roomCode)
    setError('')
    try {
      const identity = await joinRoomByCode(room.roomCode, nickname || undefined)
      const info = await getRoomInfo(room.roomCode)
      const me = info.players.find((p) => p.playerId === identity.playerId)
      setRoomIdentity(identity)
      setHost(me?.isHost ?? false)
      // 按房间阶段回到对应的页面。原来只区分 InGame / 其它，Building 阶段
      // （已经过了大厅、正在建卡）会被送回大厅——而大厅的"开始游戏"在这个阶段
      // 必然被后端 409 拒绝，用户就卡在那儿了。房间状态机是
      // Lobby → Building → InGame → Completed，这里要一一对上。
      navigate(RESUME_ROUTE[room.phase] ?? '/room/lobby')
    } catch (err) {
      setError(friendlyErrorMessage(err, '继续游戏失败'))
    } finally {
      setResumingCode(null)
    }
  }

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-10">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => navigate('/home')} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all">
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
        </button>
        <h2 className="text-lg font-bold text-text-primary">我的游戏</h2>
      </div>

      <div className="px-5 space-y-5">
        {error && <p className="text-[11px] text-[#c04040] text-center">{error}</p>}

        {rooms === null && !error && (
          <p className="text-center text-sm text-text-dim py-10">加载中…</p>
        )}

        {rooms !== null && rooms.length === 0 && (
          <div className="text-center py-16 space-y-4">
            <p className="text-sm text-text-dim">还没有加入过任何房间</p>
            <div className="flex flex-col gap-2.5 px-6">
              <button onClick={() => navigate('/home/create')}
                className="flex items-center justify-center gap-2 px-6 py-3 w-full rounded-sm text-sm font-semibold bg-brass text-white active:bg-brass-dark active:scale-[0.97] transition-all">
                <Plus className="w-[16px] h-[16px]" /> 创建房间
              </button>
              <button onClick={() => navigate('/home/join')}
                className="flex items-center justify-center gap-2 px-6 py-3 w-full rounded-sm text-sm font-semibold bg-card text-text-body border border-border-mid active:bg-panel active:scale-[0.97] transition-all">
                <Hash className="w-[16px] h-[16px]" /> 加入房间
              </button>
            </div>
          </div>
        )}

        {inProgress.length > 0 && (
          <div>
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">进行中</h4>
            <div className="space-y-2.5">
              {inProgress.map((room) => (
                <div key={room.roomCode} className="bg-card border border-border-light rounded-md p-[14px] flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text-primary truncate">{room.roomName}</div>
                    <div className="text-[11px] text-text-muted mt-0.5">
                      {room.moduleTitle || '尚未选择模组'} · {PHASE_LABEL[room.phase] || room.phase} · {formatTime(room.updatedAt)}
                    </div>
                  </div>
                  <button
                    onClick={() => handleResume(room)}
                    disabled={resumingCode === room.roomCode}
                    className="flex items-center gap-1 px-3.5 py-2 rounded-sm text-xs font-semibold bg-brass text-white active:bg-brass-dark active:scale-[0.96] transition-all disabled:opacity-60"
                  >
                    <Play className="w-[14px] h-[14px]" />
                    {resumingCode === room.roomCode ? '进入中…' : '继续'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {completed.length > 0 && (
          <div>
            <h4 className="text-[12px] font-semibold text-brass-dark uppercase tracking-[0.08em] mb-2.5">已完成</h4>
            <div className="space-y-2.5">
              {completed.map((room) => (
                <div key={room.roomCode} className="bg-card border border-border-light rounded-md p-[14px] flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-text-primary truncate">{room.roomName}</div>
                    <div className="text-[11px] text-text-muted mt-0.5">
                      {room.moduleTitle || '未知模组'} · {formatTime(room.updatedAt)}
                    </div>
                  </div>
                  <button
                    onClick={() => navigate(`/home/my-rooms/review/${room.roomCode}`)}
                    className="flex items-center gap-1 px-3.5 py-2 rounded-sm text-xs font-semibold bg-transparent text-brass-dark border border-brass active:bg-panel active:scale-[0.96] transition-all"
                  >
                    <ScrollText className="w-[14px] h-[14px]" />
                    查看复盘
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

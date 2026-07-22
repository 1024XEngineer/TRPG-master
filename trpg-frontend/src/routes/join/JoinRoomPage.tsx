import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { ArrowLeft, DoorOpen, Hash } from 'lucide-react'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { joinRoomByCode } from '@/services/room'
import { friendlyErrorMessage } from '@/services/api-client'

export default function JoinRoomPage() {
  const navigate = useNavigate()
  const nickname = useAuthStore((s) => s.nickname)
  const setRoomIdentity = useRoomStore((s) => s.setRoomIdentity)
  const setHost = useRoomStore((s) => s.setHost)
  const [roomCode, setRoomCode] = useState('')
  const [error, setError] = useState('')
  const [joining, setJoining] = useState(false)

  const handleJoin = async () => {
    const code = roomCode.trim().toUpperCase()
    if (code.length < 4) {
      setError('请输入房间号')
      return
    }
    setError('')
    setJoining(true)
    try {
      const room = await joinRoomByCode(code, nickname || undefined)
      setRoomIdentity(room)
      setHost(false)
      // ★ 访客也要先进大厅——所有玩家到齐、都准备好之后才能一起进入建卡
      // 阶段，不能像以前那样直接跳过大厅、单独去建卡（见需求：全员到齐才能
      // 开始游戏）。
      navigate('/room/lobby')
    } catch (err) {
      setError(friendlyErrorMessage(err, '加入房间失败，请检查房间号'))
    } finally {
      setJoining(false)
    }
  }

  return (
    <div className="animate-screen-in min-h-screen flex flex-col bg-page">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => navigate('/home')} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all">
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
        </button>
        <h2 className="text-lg font-bold text-text-primary">加入房间</h2>
      </div>

      <div className="flex-1 flex flex-col items-center px-5 pt-12">
        <DoorOpen className="w-12 h-12 text-brass mb-4" />
        <p className="text-sm text-text-muted mb-6">输入房主分享的房间号</p>

        <div className="relative w-full max-w-[280px] mb-6">
          <Hash className="w-4 h-4 absolute left-4 top-1/2 -translate-y-1/2 text-text-dim" />
          <input
            value={roomCode}
            onChange={e => {
              const v = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6)
              setRoomCode(v)
              setError('')
            }}
            placeholder="输入 6 位房间号"
            autoFocus
            maxLength={6}
            className="w-full pl-11 pr-4 py-3.5 rounded-[8px] bg-input border border-border-light text-text-primary text-[18px] font-mono font-bold tracking-[0.12em] outline-none focus:border-brass focus:shadow-[0_0_0_3px_rgba(184,151,106,0.1)] placeholder:text-text-dim placeholder:font-normal placeholder:tracking-normal"
          />
        </div>

        {error && <p className="text-[12px] text-[#c04040] mb-4">{error}</p>}

        <button
          onClick={handleJoin}
          disabled={roomCode.length < 4 || joining}
          className={`w-full max-w-[280px] py-3.5 rounded-sm text-sm font-semibold transition-all ${
            roomCode.length >= 4 && !joining
              ? 'bg-brass text-white active:bg-brass-dark active:scale-[0.97]'
              : 'bg-border-light text-text-dim cursor-not-allowed'
          }`}>
          {joining ? '加入中…' : '加入房间'}
        </button>
      </div>
    </div>
  )
}

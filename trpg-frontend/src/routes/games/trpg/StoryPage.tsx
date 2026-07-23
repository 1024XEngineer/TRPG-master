import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen, UserRound } from 'lucide-react'
import type { ModuleDetail } from 'trpg-sdk'
import { disconnectWebSocket, friendlyErrorMessage } from '@/services/api-client'
import { createCharacterFromPregen } from '@/services/character/character-api'
import { getModuleDetail, getRoomInfo } from '@/services/room'
import { useGameStore } from '@/stores/game-store'
import { useRoomStore } from '@/stores/room-store'

export default function StoryPage() {
  const navigate = useNavigate()
  const selectedModuleId = useGameStore((s) => s.moduleId)
  const setSelectedModule = useGameStore((s) => s.setModule)
  const roomId = useRoomStore((s) => s.roomId)
  const roomCode = useRoomStore((s) => s.roomCode)
  const roomModuleId = useRoomStore((s) => s.moduleId)
  const setRoomModuleId = useRoomStore((s) => s.setModuleId)
  const characterId = useRoomStore((s) => s.characterId)
  const setCharacterId = useRoomStore((s) => s.setCharacterId)
  const [module, setModule] = useState<ModuleDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [choosingPregen, setChoosingPregen] = useState<string | null>(null)
  const [confirmExit, setConfirmExit] = useState(false)

  useEffect(() => {
    let cancelled = false
    const resolveModuleId = async () => {
      if (roomModuleId || selectedModuleId) return roomModuleId || selectedModuleId
      if (!roomCode) return null
      const room = await getRoomInfo(roomCode)
      return room.moduleId ?? null
    }

    resolveModuleId()
      .then(async (moduleId) => {
        if (!moduleId) throw new Error('房间尚未选择模组')
        const detail = await getModuleDetail(moduleId)
        if (cancelled) return
        setModule(detail)
        setRoomModuleId(moduleId)
        setSelectedModule(moduleId)
      })
      .catch((err) => {
        if (!cancelled) setError(friendlyErrorMessage(err, '模组详情加载失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [
    roomCode,
    roomModuleId,
    selectedModuleId,
    setRoomModuleId,
    setSelectedModule,
  ])

  const handleExit = () => {
    disconnectWebSocket()
    navigate('/home')
  }

  const choosePregen = async (pregenId: string) => {
    if (!roomId || choosingPregen) return
    setChoosingPregen(pregenId)
    setError('')
    try {
      const id = await createCharacterFromPregen(roomId, pregenId)
      setCharacterId(id)
      navigate('/room/ready')
    } catch (err) {
      setError(friendlyErrorMessage(err, '预制人物选择失败'))
      setChoosingPregen(null)
    }
  }

  const exitConfirm = confirmExit && (
    <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center px-8" onClick={() => setConfirmExit(false)}>
      <div className="bg-[#1a1620] border border-[rgba(255,255,255,0.12)] rounded-md p-5 w-full max-w-[300px]" onClick={(e) => e.stopPropagation()}>
        <p className="text-sm text-[#d4cfc8] text-center mb-4">确定要退出游戏吗？房间会保留，之后可以从「我的游戏」继续。</p>
        <div className="flex gap-2">
          <button onClick={() => setConfirmExit(false)} className="flex-1 py-2 rounded-sm bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] text-[#a09888] text-xs font-medium">
            取消
          </button>
          <button onClick={handleExit} className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium">
            确认退出
          </button>
        </div>
      </div>
    </div>
  )

  if (loading || !module) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#1a1620] to-[#0d0b10] flex flex-col items-center justify-center px-7 text-center">
        {exitConfirm}
        <button onClick={() => setConfirmExit(true)} className="absolute top-4 left-4 w-[34px] h-[34px] rounded-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] flex items-center justify-center text-[#a09888]">
          <ArrowLeft className="w-[18px] h-[18px]" />
        </button>
        <BookOpen className="w-12 h-12 mb-4 text-[#706090]" />
        <p className="text-sm text-[#9088a0]">{loading ? '正在读取模组…' : error}</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#1a1620] to-[#0d0b10] px-7 py-16 relative">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_20%,rgba(112,80,160,0.1),transparent_60%)] pointer-events-none" />
      {exitConfirm}
      <button onClick={() => setConfirmExit(true)} className="absolute top-4 left-4 w-[34px] h-[34px] rounded-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] flex items-center justify-center text-[#a09888] z-10">
        <ArrowLeft className="w-[18px] h-[18px]" />
      </button>

      <div className="relative">
        <div className="font-mono text-[11px] tracking-[0.15em] text-[#706090] mb-4">
          {module.developmentOnly ? '开发样例 · 不可公开发布' : `VERSION ${module.version}`}
        </div>
        <h1 className="text-[28px] font-bold text-[#eeead8] leading-[1.25] mb-2">{module.title}</h1>
        {module.originalTitle && (
          <p className="font-mono text-xs text-[#9088a0] mb-6 tracking-[0.05em]">{module.originalTitle}</p>
        )}
        <div className="w-10 h-px bg-[#504860] mb-6" />
        <p className="text-sm leading-[1.9] text-[#c8c0b8] mb-5">{module.premise}</p>
        <div className="bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] rounded-md p-4 mb-8">
          <div className="text-xs font-semibold text-[#b0a0d0] mb-2">{module.entryScene.name}</div>
          <p className="text-sm leading-[1.8] text-[#c8c0b8]">{module.entryScene.playerDescription}</p>
        </div>

        {characterId ? (
          <button onClick={() => navigate('/room/ready')} className="w-full py-3.5 rounded-sm bg-brass text-white text-sm font-semibold">
            查看已选人物 →
          </button>
        ) : (
          <>
            <h2 className="text-base font-bold text-[#eeead8] mb-2">选择预制调查员</h2>
            <p className="text-xs text-[#9088a0] mb-4">选择后会复制一份人物快照并直接完成建卡。</p>
            <div className="space-y-3">
              {(module.pregens ?? []).map((pregen) => (
                <button
                  key={pregen.id}
                  onClick={() => choosePregen(pregen.id)}
                  disabled={choosingPregen !== null}
                  className="w-full text-left bg-[rgba(255,255,255,0.05)] border border-[rgba(255,255,255,0.1)] rounded-md p-4 active:scale-[0.98] transition-all disabled:opacity-60"
                >
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-full bg-[rgba(112,80,160,0.2)] flex items-center justify-center">
                      <UserRound className="w-5 h-5 text-[#b0a0d0]" />
                    </div>
                    <div className="flex-1">
                      <div className="text-sm font-semibold text-[#eeead8]">{pregen.name}</div>
                      {pregen.occupation && <div className="text-[11px] text-[#9088a0] mt-0.5">{pregen.occupation}</div>}
                    </div>
                    <span className="text-xs text-[#b0a0d0]">
                      {choosingPregen === pregen.id ? '选择中…' : '选择'}
                    </span>
                  </div>
                  {pregen.summary && <p className="text-xs leading-[1.7] text-[#a8a0a8] mt-3">{pregen.summary}</p>}
                </button>
              ))}
            </div>
            <button onClick={() => navigate('/room/character')} className="w-full mt-4 py-3 text-xs text-[#9088a0] border border-[rgba(255,255,255,0.1)] rounded-sm">
              使用自定义建卡（完善中）
            </button>
          </>
        )}
        {error && <p className="text-xs text-[#d06060] text-center mt-4">{error}</p>}
      </div>
    </div>
  )
}

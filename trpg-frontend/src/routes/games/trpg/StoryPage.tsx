import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, BookOpen } from 'lucide-react'
import type { ModuleDetail } from 'trpg-sdk'
import { useGameStore } from '@/stores/game-store'
import { useRoomStore } from '@/stores/room-store'
import { disconnectWebSocket, friendlyErrorMessage } from '@/services/api-client'
import { getModuleDetail } from '@/services/room'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'

export default function StoryPage() {
  const navigate = useNavigate()
  const sceneId = useGameStore((s) => s.sceneId)
  const roomCode = useRoomStore((s) => s.roomCode)
  const storedModuleId = useRoomStore((s) => s.moduleId)
  const setModuleId = useRoomStore((s) => s.setModuleId)
  const roomInfo = useRoomPlayers(roomCode)
  const moduleId = storedModuleId || roomInfo?.moduleId || sceneId
  const [module, setModule] = useState<ModuleDetail | null>(null)
  const [loadError, setLoadError] = useState('')
  const [confirmExit, setConfirmExit] = useState(false)

  useEffect(() => {
    if (roomInfo?.moduleId && roomInfo.moduleId !== storedModuleId) {
      setModuleId(roomInfo.moduleId)
    }
  }, [roomInfo?.moduleId, setModuleId, storedModuleId])

  useEffect(() => {
    if (!moduleId) return
    let cancelled = false
    setLoadError('')
    getModuleDetail(moduleId)
      .then((detail) => {
        if (!cancelled) setModule(detail)
      })
      .catch((error) => {
        if (!cancelled) setLoadError(friendlyErrorMessage(error, '加载模组故事失败'))
      })
    return () => {
      cancelled = true
    }
  }, [moduleId])

  const handleExit = () => {
    disconnectWebSocket()
    navigate('/home')
  }

  const exitConfirm = confirmExit && (
    <div className="fixed inset-0 z-40 bg-black/60 flex items-center justify-center px-8" onClick={() => setConfirmExit(false)}>
      <div className="bg-[#1a1620] border border-[rgba(255,255,255,0.12)] rounded-md p-5 w-full max-w-[300px]" onClick={(e) => e.stopPropagation()}>
        <p className="text-sm text-[#d4cfc8] text-center mb-4">确定要退出游戏吗？房间会保留，之后可以从「我的游戏」继续。</p>
        <div className="flex gap-2">
          <button onClick={() => setConfirmExit(false)}
            className="flex-1 py-2 rounded-sm bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] text-[#a09888] text-xs font-medium">
            取消
          </button>
          <button onClick={handleExit}
            className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium active:bg-[#a03030]">
            确认退出
          </button>
        </div>
      </div>
    </div>
  )

  if (!module) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-[#1a1620] to-[#0d0b10] flex flex-col justify-center px-7 py-10 relative">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_30%,rgba(112,80,160,0.08),transparent_70%)] pointer-events-none" />
        {exitConfirm}
        <button
          onClick={() => setConfirmExit(true)}
          className="absolute top-4 left-4 w-[34px] h-[34px] rounded-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] flex items-center justify-center text-[#a09888] z-10"
        >
          <ArrowLeft className="w-[18px] h-[18px]" />
        </button>
        <div className="text-center text-[#9088a0]">
          <BookOpen className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p className="text-sm">{loadError || (moduleId ? '正在加载模组…' : '房间尚未选择模组')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-b from-[#1a1620] to-[#0d0b10] flex flex-col justify-center px-7 py-10 relative">
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_50%_30%,rgba(112,80,160,0.08),transparent_70%)] pointer-events-none" />
      {exitConfirm}
      <button
        onClick={() => setConfirmExit(true)}
        className="absolute top-4 left-4 w-[34px] h-[34px] rounded-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] flex items-center justify-center text-[#a09888] z-10"
      >
        <ArrowLeft className="w-[18px] h-[18px]" />
      </button>

      <div className="font-mono text-[11px] tracking-[0.15em] text-[#706090] mb-5">
        {module.storyLabel || `MODULE ${module.version}`}
      </div>
      <h1 className="text-[28px] font-bold text-[#eeead8] leading-[1.25] mb-2">
        {module.title}
      </h1>
      <p className="font-mono text-xs text-[#9088a0] mb-8 tracking-[0.05em]">
        {module.nameEn || module.subtitle || ''}
      </p>
      <div className="w-10 h-px bg-[#504860] mb-7" />
      <div className="text-sm leading-[1.9] text-[#c8c0b8]">
        {module.storyPages.map((page, idx) => (
          <section key={`${page.title}-${idx}`} className={idx < module.storyPages.length - 1 ? 'mb-5' : ''}>
            {page.title && <h2 className="font-semibold text-[#ded8cc] mb-1">{page.title}</h2>}
            <p>{page.content}</p>
          </section>
        ))}
      </div>
      <button
        onClick={() => navigate('/room/character')}
        className="mt-10 self-start px-6 py-3.5 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all"
      >
        继续 →
      </button>
    </div>
  )
}

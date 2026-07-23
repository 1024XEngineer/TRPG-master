import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { BookOpen, ChevronRight, Clock, Users } from 'lucide-react'
import type { ModuleSummary } from 'trpg-sdk'
import { getGameById, SYSTEM_COLORS } from '@/config/games'
import { friendlyErrorMessage } from '@/services/api-client'
import { listModules } from '@/services/room'
import Badge from '@/shared/components/Badge'
import { useGameStore } from '@/stores/game-store'

const COC7_SYSTEM_ID = '00000000-0000-0000-0000-000000000002'

export default function ScenarioSelectionPage() {
  const navigate = useNavigate()
  const { gameId, systemId } = useParams<{ gameId: string; systemId: string }>()
  const game = getGameById(gameId || '')
  const setModule = useGameStore((s) => s.setModule)
  const setGame = useGameStore((s) => s.setGame)
  const setReturnFromGameSelect = useGameStore((s) => s.setReturnFromGameSelect)
  const returnFromGameSelect = useGameStore((s) => s.returnFromGameSelect)
  const [modules, setModules] = useState<ModuleSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const colors = SYSTEM_COLORS[systemId || ''] ?? SYSTEM_COLORS.coc
  const systemName = colors?.name || '未知系统'

  useEffect(() => {
    let cancelled = false
    listModules()
      .then((items) => {
        if (cancelled) return
        const expectedSystemId = systemId === 'coc' ? COC7_SYSTEM_ID : systemId
        setModules(items.filter((item) => item.gameSystemId === expectedSystemId))
      })
      .catch((err) => {
        if (!cancelled) setError(friendlyErrorMessage(err, '模组列表加载失败'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [systemId])

  const handleSelect = (module: ModuleSummary) => {
    setModule(module.id)
    setGame(gameId || '', systemId || '')
    if (returnFromGameSelect) {
      setReturnFromGameSelect(false)
      navigate('/home/create')
    } else {
      navigate('/room/story')
    }
  }

  return (
    <div className="animate-screen-in">
      <div className="flex items-center gap-2.5 px-5 pb-3 pt-1">
        <button
          onClick={() => navigate(`/home/create/games/${gameId}`)}
          className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150"
        >
          <svg className="w-[18px] h-[18px] text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
        </button>
        <h2 className="text-lg font-bold text-text-primary">选择模组</h2>
      </div>
      <p className="text-xs text-text-muted px-5 pb-4">
        {game?.name || '跑团'} · {systemName}
      </p>

      <div className="px-5 flex flex-col gap-3.5">
        {loading && (
          <div className="text-center py-10 text-text-muted text-sm">正在读取可用模组…</div>
        )}
        {!loading && error && (
          <div className="text-center py-10 text-[#c04040] text-sm">{error}</div>
        )}
        {!loading && !error && modules.length === 0 && (
          <div className="text-center py-10 text-text-muted text-sm">暂无可用模组</div>
        )}

        {modules.map((module) => (
          <div
            key={module.id}
            onClick={() => handleSelect(module)}
            className="bg-card border border-border-light rounded-md p-5 cursor-pointer active:scale-[0.98] transition-all duration-200"
          >
            <div className="flex items-start gap-3 mb-3">
              <div className={`w-12 h-12 rounded-[12px] flex-shrink-0 flex items-center justify-center ${colors.iconBg}`}>
                <BookOpen className={`w-6 h-6 ${colors.iconColor}`} />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-[17px] font-bold text-text-primary">{module.title}</h3>
                {module.originalTitle && (
                  <p className="text-xs text-text-muted mt-0.5 font-mono tracking-[0.03em]">
                    {module.originalTitle}
                  </p>
                )}
              </div>
              <ChevronRight className="w-[18px] h-[18px] text-text-dim mt-1" />
            </div>
            <div className="flex flex-wrap items-center gap-3 text-[11px] text-text-dim">
              <span className="flex items-center gap-1">
                <Users className="w-3.5 h-3.5" />
                {module.playersMin === module.playersMax
                  ? `${module.playersMin} 人`
                  : `${module.playersMin}-${module.playersMax} 人`}
              </span>
              {module.estimatedDuration && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {module.estimatedDuration}
                </span>
              )}
              <Badge variant={module.runtimeStatus === 'ready' ? 'success' : 'default'}>
                {module.developmentOnly ? '开发样例' : '已就绪'}
              </Badge>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

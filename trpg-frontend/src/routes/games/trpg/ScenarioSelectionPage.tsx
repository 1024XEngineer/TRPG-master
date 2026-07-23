import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { BookOpen, Clock, Users, ChevronRight, Upload } from 'lucide-react'
import type { ModuleSummary } from 'trpg-sdk'
import { getGameById, getSystemVisualKey, SYSTEM_COLORS } from '@/config/games'
import { useGameStore } from '@/stores/game-store'
import { friendlyErrorMessage } from '@/services/api-client'
import { listModules } from '@/services/room'
import Badge from '@/shared/components/Badge'

const difficultyLabel: Record<number, string> = {
  1: '入门',
  2: '进阶',
  3: '挑战',
}

const difficultyStyles: Record<string, string> = {
  '入门': 'bg-[rgba(74,138,74,0.12)] text-[#4a8a4a]',
  '进阶': 'bg-[rgba(184,151,106,0.12)] text-[#b8976a]',
  '挑战': 'bg-[rgba(192,64,64,0.12)] text-[#c04040]',
}

export default function ScenarioSelectionPage() {
  const navigate = useNavigate()
  const { gameId, systemId } = useParams<{ gameId: string; systemId: string }>()
  const game = getGameById(gameId || '')
  const [modules, setModules] = useState<ModuleSummary[] | null>(null)
  const [loadError, setLoadError] = useState('')

  const setScene = useGameStore((s) => s.setScene)
  const setGame = useGameStore((s) => s.setGame)
  const setReturnFromGameSelect = useGameStore((s) => s.setReturnFromGameSelect)
  const returnFromGameSelect = useGameStore((s) => s.returnFromGameSelect)
  const systemName = modules?.[0]?.gameSystemName || '当前规则系统'
  const colors = SYSTEM_COLORS[getSystemVisualKey(systemName)]

  useEffect(() => {
    let cancelled = false
    listModules()
      .then((items) => {
        if (!cancelled) {
          setModules(items.filter((item) => item.gameSystemId === systemId))
        }
      })
      .catch((error) => {
        if (!cancelled) setLoadError(friendlyErrorMessage(error, '加载模组目录失败'))
      })
    return () => {
      cancelled = true
    }
  }, [systemId])

  const handleSelect = (module: ModuleSummary) => {
    if (module.status !== 'ready') return
    setScene(module.id)
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
        {modules === null && !loadError && (
          <div className="text-center py-10 text-text-muted text-sm">正在加载模组…</div>
        )}
        {loadError && (
          <div className="text-center py-10 text-[#c04040] text-sm">{loadError}</div>
        )}
        {modules?.length === 0 && (
          <div className="text-center py-10 text-text-muted text-sm">
            暂无预置模组，您可以自行导入
          </div>
        )}

        {modules?.map((module) => {
          const difficulty = difficultyLabel[module.difficulty] ?? `等级 ${module.difficulty}`
          const diffStyle = difficultyStyles[difficulty] || difficultyStyles['进阶']
          const isReady = module.status === 'ready'

          return (
            <button
              type="button"
              key={module.id}
              onClick={() => handleSelect(module)}
              disabled={!isReady}
              className={`text-left bg-card border border-border-light rounded-md p-5 transition-all duration-200 ${
                isReady ? 'cursor-pointer active:scale-[0.98]' : 'cursor-not-allowed opacity-65'
              }`}
            >
              <div className="flex items-start gap-3 mb-3">
                <div className={`w-12 h-12 rounded-[12px] flex-shrink-0 flex items-center justify-center ${colors?.iconBg ?? 'bg-panel'}`}>
                  <BookOpen className={`w-6 h-6 ${colors?.iconColor ?? 'text-text-muted'}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[17px] font-bold text-text-primary">{module.title}</h3>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${diffStyle}`}>
                      {difficulty}
                    </span>
                  </div>
                  <p className="text-xs text-text-muted mt-0.5 font-mono tracking-[0.03em]">
                    {module.nameEn || `v${module.version}`}
                  </p>
                </div>
                {isReady && (
                  <div className="text-text-dim flex-shrink-0 mt-1">
                    <ChevronRight className="w-[18px] h-[18px]" />
                  </div>
                )}
              </div>
              <p className="text-xs text-text-muted leading-[1.7] line-clamp-2 mb-3">
                {module.synopsis || '暂无故事简介'}
              </p>
              <div className="flex items-center gap-4 text-[11px] text-text-dim">
                <span className="flex items-center gap-1">
                  <Users className="w-3.5 h-3.5" />
                  {module.playersMin}-{module.playersMax} 人
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {module.estimatedDuration || '时长待定'}
                </span>
                <Badge variant={isReady ? 'success' : 'default'}>
                  {isReady ? '已就绪' : '开发中'}
                </Badge>
              </div>
            </button>
          )
        })}
      </div>

      <div className="px-5 mt-5">
        <button
          type="button"
          className="w-full flex items-center justify-center gap-2 py-3.5 rounded-sm border border-dashed border-border-mid bg-transparent text-text-muted text-sm active:bg-panel transition-all duration-150"
        >
          <Upload className="w-[18px] h-[18px]" />
          自行导入模组
        </button>
        <p className="text-[11px] text-text-dim text-center mt-2 mb-6">
          支持 JSON / YAML 格式的模组文件
        </p>
      </div>
    </div>
  )
}

import { useNavigate, useParams } from 'react-router-dom'
import { BookOpen, Clock, Users, ChevronRight, Upload } from 'lucide-react'
import { getGameById, getScenariosBySystem, SYSTEM_COLORS } from '@/config/games'
import { useGameStore } from '@/stores/game-store'
import Badge from '@/shared/components/Badge'
import type { Scenario } from '@/types/game'

const difficultyStyles: Record<string, string> = {
  '入门': 'bg-[rgba(74,138,74,0.12)] text-[#4a8a4a]',
  '进阶': 'bg-[rgba(184,151,106,0.12)] text-[#b8976a]',
  '挑战': 'bg-[rgba(192,64,64,0.12)] text-[#c04040]',
}

export default function ScenarioSelectionPage() {
  const navigate = useNavigate()
  const { gameId, systemId } = useParams<{ gameId: string; systemId: string }>()
  const game = getGameById(gameId || '')
  const scenarios = getScenariosBySystem(systemId || '')

  const setScene = useGameStore((s) => s.setScene)
  const setGame = useGameStore((s) => s.setGame)
  const setReturnFromGameSelect = useGameStore((s) => s.setReturnFromGameSelect)
  const returnFromGameSelect = useGameStore((s) => s.returnFromGameSelect)
  const colors = SYSTEM_COLORS[systemId || '']
  const systemName = colors?.name || '未知系统'

  const handleSelect = (scenario: Scenario) => {
    setScene(scenario.id)
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
        {scenarios.length === 0 && (
          <div className="text-center py-10 text-text-muted text-sm">
            暂无预置模组，您可以自行导入
          </div>
        )}

        {scenarios.map((scenario) => {
          const diffStyle = difficultyStyles[scenario.difficulty] || difficultyStyles['入门']

          return (
            <div
              key={scenario.id}
              onClick={() => handleSelect(scenario)}
              className="bg-card border border-border-light rounded-md p-5 cursor-pointer active:scale-[0.98] transition-all duration-200"
            >
              <div className="flex items-start gap-3 mb-3">
                <div className={`w-12 h-12 rounded-[12px] flex-shrink-0 flex items-center justify-center ${colors.iconBg}`}>
                  <BookOpen className={`w-6 h-6 ${colors.iconColor}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-[17px] font-bold text-text-primary">{scenario.name}</h3>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${diffStyle}`}>
                      {scenario.difficulty}
                    </span>
                  </div>
                  <p className="text-xs text-text-muted mt-0.5 font-mono tracking-[0.03em]">
                    {scenario.nameEn}
                  </p>
                </div>
                <div className="text-text-dim flex-shrink-0 mt-1">
                  <ChevronRight className="w-[18px] h-[18px]" />
                </div>
              </div>
              <p className="text-xs text-text-muted leading-[1.7] line-clamp-2 mb-3">
                {scenario.description}
              </p>
              <div className="flex items-center gap-4 text-[11px] text-text-dim">
                <span className="flex items-center gap-1">
                  <Users className="w-3.5 h-3.5" />
                  {scenario.playerCount}
                </span>
                <span className="flex items-center gap-1">
                  <Clock className="w-3.5 h-3.5" />
                  {scenario.estimatedTime}
                </span>
                <Badge variant={scenario.status === 'ready' ? 'success' : 'default'}>
                  {scenario.status === 'ready' ? '已就绪' : '开发中'}
                </Badge>
              </div>
            </div>
          )
        })}
      </div>

      {/* 自行导入模组 */}
      <div className="px-5 mt-5">
        <button
          onClick={() => {
            /* TODO: 导入模组的弹窗或页面 */
          }}
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

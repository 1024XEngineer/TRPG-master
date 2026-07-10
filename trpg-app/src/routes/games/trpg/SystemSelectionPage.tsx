import { useNavigate, useParams } from 'react-router-dom'
import { Shield, Swords, ChevronRight } from 'lucide-react'
import { getGameById, SYSTEM_COLORS } from '@/config/games'
import Badge from '@/shared/components/Badge'

export default function SystemSelectionPage() {
  const navigate = useNavigate()
  const { gameId } = useParams<{ gameId: string }>()
  const game = getGameById(gameId || '')

  if (!game || !game.systems) {
    return (
      <div className="animate-screen-in px-5 pt-10 text-center text-text-muted text-sm">
        未找到该游戏
      </div>
    )
  }

  const systems = [
    {
      id: 'coc',
      name: '克苏鲁的呼唤',
      nameEn: 'Call of Cthulhu 7th',
      description: '1920 年代调查员\n对抗宇宙恐怖的经典规则',
      status: 'ready' as const,
    },
    {
      id: 'dnd',
      name: '龙与地下城',
      nameEn: 'Dungeons & Dragons 5e',
      description: '剑与魔法的奇幻冒险\n史诗级英雄传说',
      status: 'wip' as const,
    },
  ]

  return (
    <div className="animate-screen-in">
      <div className="flex items-center gap-2.5 px-5 pb-3 pt-1">
        <button
          onClick={() => navigate('/games')}
          className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150"
        >
          <svg className="w-[18px] h-[18px] text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
        </button>
        <h2 className="text-lg font-bold text-text-primary">选择世界</h2>
      </div>
      <p className="text-xs text-text-muted px-5 pb-4">{game.name} · 选择规则系统</p>

      <div className="px-5 flex flex-col gap-3.5">
        {systems.map((sys) => {
          const colors = SYSTEM_COLORS[sys.id]
          const isReady = sys.status === 'ready'
          const IconComp = sys.id === 'coc' ? Shield : Swords

          return (
            <div
              key={sys.id}
              onClick={() => {
                if (isReady) navigate(`/games/${gameId}/scenarios/${sys.id}`)
              }}
              className={`
                bg-card border border-border-light rounded-md p-5
                cursor-pointer flex items-center gap-4
                active:scale-[0.98] transition-all duration-200
                ${isReady ? '' : 'opacity-60'}
                ${colors.border.replace('border-', 'border-l-4 border-l-')}
              `}
            >
              <div className={`w-14 h-14 rounded-[14px] flex-shrink-0 flex items-center justify-center ${colors.iconBg}`}>
                <IconComp className={`w-7 h-7 ${colors.iconColor}`} />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-[17px] font-bold text-text-primary">{sys.name}</h3>
                <p className="text-xs text-text-muted mt-0.5 leading-[1.5]">{sys.nameEn}</p>
                <p className="text-[11px] text-text-muted mt-1 leading-[1.5] whitespace-pre-line">{sys.description}</p>
                {isReady && (
                  <Badge variant="success">推荐新手 · 已就绪</Badge>
                )}
                {!isReady && (
                  <Badge variant="default">开发中</Badge>
                )}
              </div>
              {isReady && (
                <div className="text-text-dim">
                  <ChevronRight className="w-[18px] h-[18px]" />
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

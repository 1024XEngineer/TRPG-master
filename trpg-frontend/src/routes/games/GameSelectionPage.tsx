import { useNavigate } from 'react-router-dom'
import { ScrollText, Clock, Ghost, Theater } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { GAME_REGISTRY } from '@/config/games'
import Badge from '@/shared/components/Badge'

const iconMap: Record<string, LucideIcon> = {
  'scroll-text': ScrollText,
  'clock': Clock,
  'wolf': Ghost,
  'theater': Theater,
}

function getStatusBadge(status: string) {
  switch (status) {
    case 'recommended':
      return <Badge variant="success">推荐</Badge>
    case 'coming-soon':
      return <Badge variant="default">开发中</Badge>
    case 'wip':
      return <Badge variant="default">开发中</Badge>
    default:
      return null
  }
}

export default function GameSelectionPage() {
  const navigate = useNavigate()

  return (
    <div className="animate-screen-in">
      <div className="flex items-center gap-2.5 px-5 pb-3 pt-1">
        <button
          onClick={() => navigate('/home')}
          className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150"
        >
          <svg className="w-[18px] h-[18px] text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
        </button>
        <h2 className="text-lg font-bold text-text-primary">选择游戏</h2>
      </div>

      <div className="px-5 grid grid-cols-2 gap-3">
        {GAME_REGISTRY.map((game) => {
          const IconComp = iconMap[game.icon] || ScrollText
          return (
            <div
              key={game.id}
              onClick={() => {
                if (game.status === 'recommended') {
                  navigate(`/home/create/games/${game.id}`)
                }
              }}
              className={`
                bg-card border border-border-light rounded-md p-[22px] text-center
                cursor-pointer transition-all duration-200 relative
                active:scale-[0.96]
                ${game.status === 'recommended' ? `border-b-[3px] ${game.borderColor}` : `border-b-[3px] ${game.borderColor}`}
              `}
            >
              <div className={`w-[52px] h-[52px] rounded-[14px] mx-auto mb-2.5 flex items-center justify-center ${game.iconBg}`}>
                <IconComp className={`w-[26px] h-[26px] ${game.iconColor}`} />
              </div>
              <div className="text-sm font-semibold text-text-primary mb-0.5">{game.name}</div>
              <div className="text-[11px] text-text-muted leading-[1.4] whitespace-pre-line">{game.description}</div>
              <div className="mt-2">{getStatusBadge(game.status)}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

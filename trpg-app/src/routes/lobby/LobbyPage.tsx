import { useNavigate } from 'react-router-dom'
import { UserPlus } from 'lucide-react'

export default function LobbyPage() {
  const navigate = useNavigate()

  return (
    <div className="animate-screen-in px-5 pt-6">
      <div className="flex items-center justify-center gap-2 mb-1">
        <span className="font-mono text-2xl font-bold text-text-primary tracking-[0.15em] bg-card border border-dashed border-border-mid px-4 py-1.5 rounded-sm">
          AR-1927
        </span>
        <span className="text-xs text-brass-dark cursor-pointer">📋</span>
      </div>
      <p className="text-center text-xs text-text-muted mb-5">等待大厅 · 1/4 人已就绪</p>

      <div className="flex flex-col gap-2">
        {[
          { name: '杰克·布朗', character: '私家侦探 · 调查员', status: 'ready' as const },
          { name: '等待中…', character: '空缺', status: 'waiting' as const },
          { name: '等待中…', character: '空缺', status: 'waiting' as const },
          { name: 'AI 调查员', character: '自动补位', status: 'ai' as const },
        ].map((p, i) => (
          <div key={i} className="flex items-center gap-3 px-3.5 py-3 bg-card border border-border-light rounded-md">
            <div className={`
              w-10 h-10 rounded-full bg-panel border border-border-mid flex items-center justify-center text-lg flex-shrink-0
              ${p.status === 'ready' ? 'border-brass' : ''}
              ${p.status === 'ai' ? 'border-ink-blue' : ''}
            `}>
              {p.status === 'ready' ? '🔍' : p.status === 'ai' ? '🤖' : '○'}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold text-text-primary">{p.name}</div>
              <div className="text-xs text-text-muted">{p.character}</div>
            </div>
            {p.status === 'waiting' ? (
              <button className="flex items-center gap-1 text-[11px] font-semibold px-2.5 py-[5px] rounded-[99px] bg-brass text-white cursor-pointer active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap">
                <UserPlus className="w-3 h-3" />
                加入
              </button>
            ) : (
              <span className={`
                text-[11px] font-semibold px-2.5 py-[3px] rounded-[99px]
                ${p.status === 'ready' ? 'bg-[rgba(74,138,74,0.12)] text-mold' : ''}
                ${p.status === 'ai' ? 'bg-[rgba(74,112,152,0.12)] text-ink-blue' : ''}
              `}>
                {p.status === 'ready' ? '已就绪' : 'AI 队友'}
              </span>
            )}
          </div>
        ))}
      </div>

      <button
        onClick={() => navigate('/room')}
        className="w-full mt-5 px-6 py-3.5 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all"
      >
        开始游戏 (1/3 人已就绪)
      </button>
    </div>
  )
}

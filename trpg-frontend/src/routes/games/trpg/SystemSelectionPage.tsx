import { useNavigate, useParams } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Shield, Swords, ChevronRight } from 'lucide-react'
import type { GameSystem } from 'trpg-sdk'
import { getGameById, getSystemVisualKey, SYSTEM_COLORS } from '@/config/games'
import Badge from '@/shared/components/Badge'
import { useGameStore } from '@/stores/game-store'
import { friendlyErrorMessage, sdk } from '@/services/api-client'

export default function SystemSelectionPage() {
  const navigate = useNavigate()
  const { gameId } = useParams<{ gameId: string }>()
  const game = getGameById(gameId || '')
  const [systems, setSystems] = useState<GameSystem[] | null>(null)
  const [loadError, setLoadError] = useState('')
  // ★ 只有从"创建房间→选择游戏"这条子流程进来（returnFromGameSelect）才允许
  // 继续往下选模组/建卡；从登录页"浏览已有游戏"直接进来的，最多只能看到这一页
  // ——建卡必须绑定一个真实房间，纯浏览模式走不到那一步（见需求：浏览入口不
  // 应该能进入游戏流程）。
  const canProceed = useGameStore((s) => s.returnFromGameSelect)

  useEffect(() => {
    let cancelled = false
    sdk.games
      .list()
      .then(async (games) => {
        const catalogs = await Promise.all(games.map((item) => sdk.games.listSystems(item.id)))
        if (!cancelled) setSystems(catalogs.flat())
      })
      .catch((error) => {
        if (!cancelled) setLoadError(friendlyErrorMessage(error, '加载规则系统失败'))
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (!game) {
    return (
      <div className="animate-screen-in px-5 pt-10 text-center text-text-muted text-sm">
        未找到该游戏
      </div>
    )
  }

  return (
    <div className="animate-screen-in">
      <div className="flex items-center gap-2.5 px-5 pb-3 pt-1">
        <button
          onClick={() => navigate('/home/create/games')}
          className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150"
        >
          <svg className="w-[18px] h-[18px] text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5M12 19l-7-7 7-7" />
          </svg>
        </button>
        <h2 className="text-lg font-bold text-text-primary">选择世界</h2>
      </div>
      <p className="text-xs text-text-muted px-5 pb-4">{game.name} · 选择规则系统</p>

      {!canProceed && (
        <div className="mx-5 mb-4 px-3.5 py-2.5 bg-[#fdf3e0] border border-[#e0c088] rounded-[6px] text-[12px] text-[#8a6a2a]">
          浏览模式：创建或加入房间后才能继续选择模组、创建角色
        </div>
      )}

      <div className="px-5 flex flex-col gap-3.5">
        {systems === null && !loadError && (
          <p className="text-center text-sm text-text-muted py-8">正在加载规则系统…</p>
        )}
        {loadError && <p className="text-center text-sm text-[#c04040] py-8">{loadError}</p>}
        {systems?.map((sys) => {
          const visualKey = getSystemVisualKey(sys.name)
          const colors = SYSTEM_COLORS[visualKey]
          const isReady = canProceed
          const IconComp = visualKey === 'coc' ? Shield : Swords

          return (
            <div
              key={sys.id}
              onClick={() => {
                if (isReady) navigate(`/home/create/games/${gameId}/scenarios/${sys.id}`)
              }}
              className={`
                bg-card border border-border-light rounded-md p-5
                flex items-center gap-4
                active:scale-[0.98] transition-all duration-200
                ${isReady ? 'cursor-pointer' : 'opacity-60'}
                ${colors.border.replace('border-', 'border-l-4 border-l-')}
              `}
            >
              <div className={`w-14 h-14 rounded-[14px] flex-shrink-0 flex items-center justify-center ${colors.iconBg}`}>
                <IconComp className={`w-7 h-7 ${colors.iconColor}`} />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-[17px] font-bold text-text-primary">{sys.name}</h3>
                <p className="text-xs text-text-muted mt-0.5 leading-[1.5]">
                  {sys.version || '当前版本'}
                </p>
                <Badge variant="success">已就绪</Badge>
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

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Hash, Plus, BookOpen } from 'lucide-react'
import { useAuthStore } from '@/stores/auth-store'

// 登录后的首页——单独一个页面/路由，不再和登录/注册表单共用同一个
// LoginPage 组件（之前是同一个组件里用 isLoggedIn 切换两套内容）。
export default function HomePage() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const nickname = useAuthStore((s) => s.nickname)
  const logout = useAuthStore((s) => s.logout)

  useEffect(() => {
    if (!isLoggedIn) navigate('/login', { replace: true })
  }, [isLoggedIn, navigate])

  if (!isLoggedIn) return null

  return (
    <div className="animate-screen-in">
      <div className="flex flex-col items-center pt-[72px] px-5 pb-10">
        <img
          src="/logo.png"
          alt="AI桌游主持人"
          className="w-20 h-20 mb-4 object-contain"
        />
        <h1 className="text-[26px] font-bold text-text-primary tracking-[0.08em] px-2 text-center">
          AI桌游主持人
        </h1>
        <p className="text-xs text-text-muted tracking-[0.06em] mt-0.5">
          AI 智能主持 · 多游戏聚会平台
        </p>
      </div>

      <div className="px-5 flex flex-col gap-2.5">
        <p className="text-center text-xs text-text-muted mb-1">
          已登录：{nickname} · <button onClick={logout} className="underline">退出登录</button>
        </p>
        <button
          className="flex items-center justify-center gap-2 px-6 py-3.5 w-full rounded-sm text-sm font-semibold cursor-pointer transition-all duration-150 border-none font-sans active:scale-[0.97] bg-brass text-white active:bg-brass-dark"
          onClick={() => navigate('/join')}
        >
          <Hash className="w-[18px] h-[18px]" />
          加入房间
        </button>
        <button
          className="flex items-center justify-center gap-2 px-6 py-3.5 w-full rounded-sm text-sm font-semibold cursor-pointer transition-all duration-150 border font-sans active:scale-[0.97] bg-card text-text-body border-border-mid active:bg-panel"
          onClick={() => navigate('/create')}
        >
          <Plus className="w-[18px] h-[18px]" />
          创建房间
        </button>
        <button
          className="flex items-center justify-center gap-2 px-6 py-3.5 w-full rounded-sm text-sm font-semibold cursor-pointer transition-all duration-150 border font-sans active:scale-[0.97] bg-transparent text-brass-dark border-brass"
          onClick={() => navigate('/games')}
        >
          <BookOpen className="w-[18px] h-[18px]" />
          浏览已有游戏
        </button>
      </div>

      <p className="text-center pt-6 text-text-dim text-[11px]">
        AI桌游主持人 © 2026
      </p>
    </div>
  )
}

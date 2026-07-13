import { useNavigate } from 'react-router-dom'
import { Hash, Plus, BookOpen } from 'lucide-react'

export default function LoginPage() {
  const navigate = useNavigate()

  return (
    <div className="animate-screen-in">
      {/* Brand */}
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
        <div className="mt-7 text-center max-w-[280px]">
          <span className="inline-block font-mono text-[11px] text-brass-dark bg-[rgba(184,151,106,0.1)] px-3 py-[2px] rounded-[99px] mb-2">
            狼人杀 · 跑团 · 血染钟楼 等
          </span>
          <span className="block text-xs text-text-muted leading-[1.7]">
            扫码即玩，AI 担任主持人
            <br />
            与朋友们畅玩各类桌游与聚会游戏
          </span>
        </div>
      </div>

      {/* Actions */}
      <div className="px-5 flex flex-col gap-2.5">
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

import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { ArrowLeft, BookOpen } from 'lucide-react'
import { useGameStore } from '@/stores/game-store'
import { getScenarioById } from '@/config/games'
import { useMemo } from 'react'
import { disconnectWebSocket } from '@/services/api-client'

// 访客走 /join 加入房间，从来不会经过"选择游戏/世界/模组"那几步，本地
// game-store 里的 sceneId 天然是空的。后端目前也确实只有这一款真实落库的
// 模组（惠特利旧宅，见 server/rest/lobby.py 的注释），不管房主当初在 UI 上
// 选的是哪张模组卡，实际跑的都是它——所以访客没有 sceneId 时，直接兜底成
// 这一款，跟后端的真实行为保持一致，而不是让访客看到"未选择模组"的空页面。
const FALLBACK_SCENE_ID = 'whateley'

export default function StoryPage() {
  const navigate = useNavigate()
  const sceneId = useGameStore((s) => s.sceneId)
  const scenario = useMemo(() => getScenarioById(sceneId || FALLBACK_SCENE_ID), [sceneId])
  // ★ 这里已经在"游戏进行中"的流程里了（大厅已经全员就绪、房主已经点了开始），
  // 左上角不能再是无提示的 navigate(-1)——那样会悄悄把人退回一个其实已经走完
  // 的大厅步骤，其他人可能都已经往下走了，状态会对不上。改成和 RoomPage 一致
  // 的"退出确认"：退出只是这个人自己先走，房间保留，之后能从「我的游戏」继续。
  const [confirmExit, setConfirmExit] = useState(false)

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

  if (!scenario) {
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
          <p className="text-sm">未选择模组</p>
          <button
            onClick={() => navigate('/home/create/games')}
            className="mt-6 px-5 py-2.5 rounded-sm bg-brass text-white text-xs font-semibold"
          >
            返回选择游戏
          </button>
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
        {scenario.storyLabel}
      </div>
      <h1 className="text-[28px] font-bold text-[#eeead8] leading-[1.25] mb-2">
        {scenario.name}
      </h1>
      <p className="font-mono text-xs text-[#9088a0] mb-8 tracking-[0.05em]">
        {scenario.nameEn}
      </p>
      <div className="w-10 h-px bg-[#504860] mb-7" />
      <div className="text-sm leading-[1.9] text-[#c8c0b8]">
        {scenario.storyPages.map((page, idx) => (
          <p key={idx} className={idx < scenario.storyPages.length - 1 ? 'mb-4' : ''}
            dangerouslySetInnerHTML={{ __html: page }}
          />
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

// /login 和 /login/register 共用的品牌区块——拆成两个独立路由后，这部分
// 视觉是唯一还有必要共享的，不用两边各写一遍。
export default function AuthHeader() {
  return (
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
  )
}

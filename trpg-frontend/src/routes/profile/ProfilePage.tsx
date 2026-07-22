import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, LogOut } from 'lucide-react'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { useCharacterStore } from '@/stores/character-store'
import { updateProfile, fetchMe, logout as logoutFromServer } from '@/services/auth'
import { friendlyErrorMessage } from '@/services/api-client'

export default function ProfilePage() {
  const navigate = useNavigate()
  const [account, setAccount] = useState('')
  const nickname = useAuthStore((s) => s.nickname)
  const setNickname = useAuthStore((s) => s.setNickname)
  const clearAuthStore = useAuthStore((s) => s.logout)
  const resetRoomStore = useRoomStore((s) => s.reset)
  const clearCharacterStore = useCharacterStore((s) => s.clear)
  const [draft, setDraft] = useState(nickname || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    fetchMe().then((me) => { if (me) setAccount(me.account) })
  }, [])

  const handleSave = async () => {
    if (!draft.trim() || draft === nickname) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const res = await updateProfile(draft.trim())
      setNickname(res.nickname)
      setSaved(true)
    } catch (err) {
      setError(friendlyErrorMessage(err, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const handleLogout = async () => {
    // 之前只清了 auth-store 的内存状态，没调用 services/auth.ts 里真正撤销
    // 后端会话 + 清掉 localStorage token 的 logout()——退出后刷新页面，
    // App 的 fetchMe() 会拿着还没失效的 token 把用户自动重新登进去。
    await logoutFromServer().catch(() => {
      // 后端调用失败也无所谓，本地状态照样清掉，让用户回到登录页。
    })
    clearAuthStore()
    resetRoomStore()
    clearCharacterStore()
    navigate('/auth/login')
  }

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-10">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button onClick={() => navigate('/home')} className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all">
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
        </button>
        <h2 className="text-lg font-bold text-text-primary">个人信息</h2>
      </div>

      <div className="px-5 flex flex-col items-center pt-6 pb-8">
        <div className="w-16 h-16 rounded-full bg-brass/15 text-brass-dark text-2xl font-bold flex items-center justify-center">
          {(draft || nickname)?.charAt(0) || '?'}
        </div>
      </div>

      <div className="px-5 space-y-3.5">
        <div className="bg-card border border-border-light rounded-md p-[18px]">
          <label className="text-[11px] font-medium text-text-muted mb-1 block">昵称</label>
          <input
            value={draft}
            onChange={(e) => { setDraft(e.target.value); setSaved(false) }}
            placeholder="输入昵称"
            className="w-full px-3.5 py-2.5 rounded-[6px] bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass"
          />
        </div>

        <div className="bg-card border border-border-light rounded-md p-[18px]">
          <label className="text-[11px] font-medium text-text-muted mb-1 block">账号</label>
          <p className="text-[15px] text-text-dim">{account}</p>
        </div>

        {error && <p className="text-[11px] text-[#c04040] text-center">{error}</p>}
        {saved && <p className="text-[11px] text-brass-dark text-center">已保存</p>}

        <button
          onClick={handleSave}
          disabled={saving || !draft.trim() || draft === nickname}
          className="w-full py-3.5 rounded-sm text-sm font-semibold transition-all bg-brass text-white active:bg-brass-dark active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? '保存中…' : '保存'}
        </button>

        <button
          onClick={handleLogout}
          className="w-full py-3.5 rounded-sm text-sm font-semibold border border-[#c04040]/40 text-[#c04040] flex items-center justify-center gap-2 active:bg-[#c04040]/5 transition-all"
        >
          <LogOut className="w-[16px] h-[16px]" /> 退出登录
        </button>
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { register, login, fetchMe } from '@/services/auth'
import { useAuthStore } from '@/stores/auth-store'
import { friendlyErrorMessage } from '@/services/api-client'

// 纯登录/注册页——不再兼职首页。登录成功后跳到 /home，那里才是"创建房间/
// 加入房间/浏览已有游戏"这些入口所在的页面。
export default function LoginPage() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const authLogin = useAuthStore((s) => s.login)

  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (isLoggedIn) navigate('/home', { replace: true })
  }, [isLoggedIn, navigate])

  const submit = async () => {
    setError('')
    if (!account.trim() || !password.trim()) {
      setError('请填写账号和密码')
      return
    }
    if (mode === 'register' && !nickname.trim()) {
      setError('请填写昵称')
      return
    }
    setLoading(true)
    try {
      if (mode === 'register') {
        const res = await register(account.trim(), password, nickname.trim())
        authLogin(res.token, res.userId, nickname.trim())
      } else {
        const res = await login(account.trim(), password)
        // 登录接口不返回昵称，得单独查一次 /auth/me 才能拿到真实昵称，
        // 否则会一直显示成账号字符串（见 2026-07-13 测试报告）。
        const me = await fetchMe()
        authLogin(res.token, res.userId, me?.nickname || account.trim())
      }
      navigate('/home')
    } catch (err) {
      setError(friendlyErrorMessage(err, '登录/注册失败'))
    } finally {
      setLoading(false)
    }
  }

  if (isLoggedIn) return null

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

      <div className="px-5 flex flex-col gap-2.5">
        <div className="flex gap-2 mb-1">
          <button
            onClick={() => setMode('login')}
            className={`flex-1 py-2 text-sm font-semibold rounded-sm transition-all ${
              mode === 'login' ? 'bg-brass text-white' : 'bg-card border border-border-mid text-text-muted'
            }`}
          >
            登录
          </button>
          <button
            onClick={() => setMode('register')}
            className={`flex-1 py-2 text-sm font-semibold rounded-sm transition-all ${
              mode === 'register' ? 'bg-brass text-white' : 'bg-card border border-border-mid text-text-muted'
            }`}
          >
            注册
          </button>
        </div>

        <input
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          placeholder="账号"
          className="w-full px-3.5 py-2.5 rounded-sm bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password"
          placeholder="密码"
          className="w-full px-3.5 py-2.5 rounded-sm bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass"
        />
        {mode === 'register' && (
          <input
            value={nickname}
            onChange={(e) => setNickname(e.target.value)}
            placeholder="昵称"
            className="w-full px-3.5 py-2.5 rounded-sm bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass"
          />
        )}

        {error && <p className="text-xs text-[#c04040] px-1">{error}</p>}

        <button
          onClick={submit}
          disabled={loading}
          className="flex items-center justify-center gap-2 px-6 py-3.5 w-full rounded-sm text-sm font-semibold cursor-pointer transition-all duration-150 border-none font-sans active:scale-[0.97] bg-brass text-white active:bg-brass-dark disabled:opacity-60"
        >
          {loading ? '处理中…' : mode === 'register' ? '注册并进入' : '登录'}
        </button>
      </div>

      <p className="text-center pt-6 text-text-dim text-[11px]">
        AI桌游主持人 © 2026
      </p>
    </div>
  )
}

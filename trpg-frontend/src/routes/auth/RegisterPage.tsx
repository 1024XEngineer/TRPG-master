import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { register } from '@/services/auth'
import { useAuthStore } from '@/stores/auth-store'
import { friendlyErrorMessage } from '@/services/api-client'
import AuthHeader from './AuthHeader'

// 纯注册页——从 /login 拆出来，独立路由 /login/register。
export default function RegisterPage() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const authLogin = useAuthStore((s) => s.login)

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
    if (!nickname.trim()) {
      setError('请填写昵称')
      return
    }
    setLoading(true)
    try {
      const res = await register(account.trim(), password, nickname.trim())
      authLogin(res.token, res.userId, nickname.trim())
      navigate('/home')
    } catch (err) {
      setError(friendlyErrorMessage(err, '注册失败'))
    } finally {
      setLoading(false)
    }
  }

  if (isLoggedIn) return null

  return (
    <div className="animate-screen-in">
      <AuthHeader />

      <div className="px-5 flex flex-col gap-2.5">
        <div className="flex gap-2 mb-1">
          <button
            onClick={() => navigate('/auth/login')}
            className="flex-1 py-2 text-sm font-semibold rounded-sm transition-all bg-card border border-border-mid text-text-muted"
          >
            登录
          </button>
          <button className="flex-1 py-2 text-sm font-semibold rounded-sm transition-all bg-brass text-white">
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
        <input
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          placeholder="昵称"
          className="w-full px-3.5 py-2.5 rounded-sm bg-input border border-border-light text-text-primary text-[15px] outline-none focus:border-brass"
        />

        {error && <p className="text-xs text-[#c04040] px-1">{error}</p>}

        <button
          onClick={submit}
          disabled={loading}
          className="flex items-center justify-center gap-2 px-6 py-3.5 w-full rounded-sm text-sm font-semibold cursor-pointer transition-all duration-150 border-none font-sans active:scale-[0.97] bg-brass text-white active:bg-brass-dark disabled:opacity-60"
        >
          {loading ? '处理中…' : '注册并进入'}
        </button>
      </div>

      <p className="text-center pt-6 text-text-dim text-[11px]">
        AI桌游主持人 © 2026
      </p>
    </div>
  )
}

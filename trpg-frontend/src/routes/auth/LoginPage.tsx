import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react'
import { login, fetchMe } from '@/services/auth'
import { useAuthStore } from '@/stores/auth-store'
import { friendlyErrorMessage } from '@/services/api-client'
import AuthPageLayout from './AuthPageLayout'

// 纯登录页——注册是另一个路由（/auth/register），不再用本地 state 切 tab。
// 登录成功后跳到 /home，那里才是"创建房间/加入房间/浏览已有游戏"这些入口
// 所在的页面。
export default function LoginPage() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const authLogin = useAuthStore((s) => s.login)

  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
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
    setLoading(true)
    try {
      const res = await login(account.trim(), password)
      // 登录接口不返回昵称，得单独查一次 /auth/me 才能拿到真实昵称，
      // 否则会一直显示成账号字符串（见 2026-07-13 测试报告）。
      const me = await fetchMe()
      authLogin(res.token, res.userId, me?.nickname || account.trim())
      navigate('/home')
    } catch (err) {
      setError(friendlyErrorMessage(err, '登录失败'))
    } finally {
      setLoading(false)
    }
  }

  if (isLoggedIn) return null

  return (
    <AuthPageLayout mode="login" loading={loading} error={error} onSubmit={submit}>
      <label className="auth-field auth-field--account">
        <UserRound className="auth-field__icon" aria-hidden="true" />
        <span className="sr-only">账号</span>
        <input
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          placeholder="账号"
          autoComplete="username"
          inputMode="text"
          disabled={loading}
          aria-describedby={error ? 'auth-form-error' : undefined}
        />
      </label>

      <label className="auth-field auth-field--password">
        <LockKeyhole className="auth-field__icon" aria-hidden="true" />
        <span className="sr-only">密码</span>
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type={showPassword ? 'text' : 'password'}
          placeholder="密码"
          autoComplete="current-password"
          disabled={loading}
          aria-describedby={error ? 'auth-form-error' : undefined}
        />
        <button
          type="button"
          className="auth-field__password-toggle"
          onClick={() => setShowPassword((visible) => !visible)}
          disabled={loading}
          aria-label={showPassword ? '隐藏密码' : '显示密码'}
          aria-pressed={showPassword}
        >
          {showPassword ? <EyeOff aria-hidden="true" /> : <Eye aria-hidden="true" />}
        </button>
      </label>
    </AuthPageLayout>
  )
}

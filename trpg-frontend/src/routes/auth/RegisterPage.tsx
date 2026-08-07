import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Eye, EyeOff, LockKeyhole, UserRound } from 'lucide-react'
import { register } from '@/services/auth'
import { useAuthStore } from '@/stores/auth-store'
import { friendlyErrorMessage } from '@/services/api-client'
import AuthPageLayout from './AuthPageLayout'

// 纯注册页——与登录页平级，使用独立路由 /auth/register。
export default function RegisterPage() {
  const navigate = useNavigate()
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn)
  const authLogin = useAuthStore((s) => s.login)

  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
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
    <AuthPageLayout mode="register" loading={loading} error={error} onSubmit={submit}>
      <label className="auth-field auth-field--account">
        <UserRound className="auth-field__icon" aria-hidden="true" />
        <span className="sr-only">账号</span>
        <input
          value={account}
          onChange={(e) => setAccount(e.target.value)}
          placeholder="账号"
          autoComplete="username"
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
          autoComplete="new-password"
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

      <label className="auth-field auth-field--nickname">
        <UserRound className="auth-field__icon" aria-hidden="true" />
        <span className="sr-only">昵称</span>
        <input
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
          placeholder="昵称"
          autoComplete="nickname"
          disabled={loading}
          aria-describedby={error ? 'auth-form-error' : undefined}
        />
      </label>
    </AuthPageLayout>
  )
}

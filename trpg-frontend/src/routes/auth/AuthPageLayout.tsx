import type { FormEvent, ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import './auth.css'

type AuthMode = 'login' | 'register'

interface AuthPageLayoutProps {
  mode: AuthMode
  loading: boolean
  error: string
  onSubmit: () => void | Promise<void>
  children: ReactNode
}

const modeCopy: Record<AuthMode, { title: string; loading: string }> = {
  login: { title: '登录', loading: '登录中…' },
  register: { title: '注册', loading: '注册中…' },
}

/**
 * 登录与注册共用同一张 849 × 1852 的设计画布。面板、装饰和表单控件都在
 * 画布或面板自己的百分比坐标系里定位，缩放时会作为一个整体变化，避免图片
 * 边框和可交互控件在不同屏幕宽度下逐渐错位。
 */
export default function AuthPageLayout({
  mode,
  loading,
  error,
  onSubmit,
  children,
}: AuthPageLayoutProps) {
  const navigate = useNavigate()
  const copy = modeCopy[mode]

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!loading) void onSubmit()
  }

  return (
    <div className={`auth-scene auth-scene--${mode}`}>
      <div className="auth-scene__artboard">
        <img
          className="auth-scene__poster"
          src="/assets/auth/detective-poster.webp"
          alt=""
          aria-hidden="true"
        />
        <img
          className="auth-scene__badge"
          src="/assets/auth/dm-badge.webp"
          alt=""
          aria-hidden="true"
        />

        <header className="sr-only">
          <h1>AI跑团主持人</h1>
          <p>AI智能主持，随时畅玩</p>
        </header>

        <section className="auth-panel" aria-labelledby="auth-page-title">
          <img
            className="auth-panel__art"
            src={`/assets/auth/${mode}-panel.webp`}
            alt=""
            aria-hidden="true"
          />

          <form className="auth-panel__form" onSubmit={submit} noValidate>
            <h2 id="auth-page-title" className="sr-only">
              {copy.title}
            </h2>

            <button
              type="button"
              className="auth-tab auth-tab--login"
              aria-current={mode === 'login' ? 'page' : undefined}
              onClick={() => mode !== 'login' && navigate('/auth/login')}
            >
              <span className="sr-only">登录</span>
            </button>
            <button
              type="button"
              className="auth-tab auth-tab--register"
              aria-current={mode === 'register' ? 'page' : undefined}
              onClick={() => mode !== 'register' && navigate('/auth/register')}
            >
              <span className="sr-only">注册</span>
            </button>

            {children}

            <p
              id="auth-form-error"
              className="auth-panel__error"
              role={error ? 'alert' : undefined}
              aria-live="polite"
            >
              {error || '\u00a0'}
            </p>

            <button type="submit" className="auth-submit" disabled={loading}>
              <span>{loading ? copy.loading : copy.title}</span>
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}

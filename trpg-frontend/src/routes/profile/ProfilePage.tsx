import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, LogOut } from 'lucide-react'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { useCharacterStore } from '@/stores/character-store'
import { updateProfile, fetchMe, logout as logoutFromServer } from '@/services/auth'
import { friendlyErrorMessage } from '@/services/api-client'
import { archiveNumber } from '@/utils/archive-number'

export default function ProfilePage() {
  const navigate = useNavigate()
  const userId = useAuthStore((state) => state.userId)
  const nickname = useAuthStore((state) => state.nickname)
  const setNickname = useAuthStore((state) => state.setNickname)
  const clearAuthStore = useAuthStore((state) => state.logout)
  const resetRoomStore = useRoomStore((state) => state.reset)
  const clearCharacterStore = useCharacterStore((state) => state.clear)
  const [account, setAccount] = useState('')
  const [draft, setDraft] = useState(nickname || '')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    let active = true

    fetchMe()
      .then((me) => {
        if (!active) return
        if (!me) {
          setError('档案读取失败，请稍后重试')
          return
        }
        setAccount(me.account)
        setDraft(me.nickname)
        setNickname(me.nickname)
      })
      .catch(() => {
        if (active) setError('档案读取失败，请稍后重试')
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [setNickname])

  const trimmedDraft = draft.trim()
  const canSave = !loading && !saving && Boolean(trimmedDraft) && trimmedDraft !== nickname

  const handleSave = async () => {
    if (!canSave) return
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const result = await updateProfile(trimmedDraft)
      setDraft(result.nickname)
      setNickname(result.nickname)
      setSaved(true)
    } catch (caughtError) {
      setError(friendlyErrorMessage(caughtError, '保存失败，请稍后重试'))
    } finally {
      setSaving(false)
    }
  }

  const handleLogout = async () => {
    if (loggingOut) return
    setLoggingOut(true)
    await logoutFromServer().catch(() => undefined)
    clearAuthStore()
    resetRoomStore()
    clearCharacterStore()
    navigate('/auth/login')
  }

  return (
    <section className="profile-scene" aria-labelledby="profile-page-title">
      <div className="profile-scene__artboard">
        <img
          className="profile-scene__background"
          src="/assets/profile/background.webp"
          alt=""
          aria-hidden="true"
          width={864}
          height={1821}
        />
        <button
          type="button"
          className="profile-scene__back"
          onClick={() => navigate('/home')}
          aria-label="返回首页"
        >
          <ArrowLeft aria-hidden="true" />
        </button>

        <img
          className="profile-scene__title"
          src="/assets/profile/title-plaque.webp"
          alt=""
          aria-hidden="true"
          width={471}
          height={129}
        />
        <h1 id="profile-page-title" className="sr-only">个人档案</h1>

        <img
          className="profile-scene__dossier"
          src="/assets/profile/dossier.webp"
          alt=""
          aria-hidden="true"
          width={865}
          height={1455}
        />

        <div className="profile-scene__identity" aria-label="档案身份">
          <strong title={nickname || '未设置昵称'}>{nickname || '未设置昵称'}</strong>
          <span>
            DM 档案库编号： <b className="profile-scene__archive-number">{archiveNumber(userId)}</b>
          </span>
        </div>

        <form
          className="profile-scene__form"
          onSubmit={(event) => {
            event.preventDefault()
            void handleSave()
          }}
        >
          <div className="profile-scene__field">
            <label htmlFor="profile-nickname">昵称</label>
            <div className="profile-scene__control">
              <input
                id="profile-nickname"
                value={draft}
                onChange={(event) => {
                  setDraft(event.target.value)
                  setSaved(false)
                  setError('')
                }}
                disabled={loading || saving}
                maxLength={50}
                autoComplete="nickname"
                placeholder={loading ? '正在读取档案…' : '输入昵称'}
              />
            </div>
          </div>

          <div className="profile-scene__field">
            <label htmlFor="profile-account">账号</label>
            <div className="profile-scene__control is-readonly">
              <input
                id="profile-account"
                value={loading ? '' : account}
                placeholder={loading ? '正在读取档案…' : '暂无账号信息'}
                readOnly
                aria-readonly="true"
              />
              <span className="profile-scene__readonly">只读</span>
            </div>
          </div>

          <div className="profile-scene__status" role="status" aria-live="polite">
            {error && <span className="is-error">{error}</span>}
            {!error && saved && <span>修改已保存</span>}
          </div>

          <button
            type="submit"
            className="profile-scene__save"
            disabled={!canSave}
            aria-label={saving ? '正在保存修改' : '保存修改'}
          >
            <img
              src="/assets/profile/save-button.webp"
              alt=""
              aria-hidden="true"
              width={480}
              height={128}
            />
            {saving && <span>保存中…</span>}
          </button>
        </form>

        <button
          type="button"
          className="profile-scene__logout"
          onClick={() => void handleLogout()}
          disabled={loggingOut}
        >
          <LogOut aria-hidden="true" />
          <span>{loggingOut ? '正在退出…' : '退出登录'}</span>
        </button>
      </div>
    </section>
  )
}

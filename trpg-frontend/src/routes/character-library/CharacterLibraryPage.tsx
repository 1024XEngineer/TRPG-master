import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, LoaderCircle, PawPrint, Plus, RefreshCw, UserRound } from 'lucide-react'
import { friendlyErrorMessage } from '@/services/api-client'
import { useTemplatePortraits } from '@/hooks/useTemplatePortraits'
import {
  createCharacterTemplate,
  deleteCharacterTemplate,
  listCharacterTemplates,
  type CharacterTemplate,
} from '@/services/character/template-api'

function formatTime(ts: string): string {
  const parsed = Date.parse(ts)
  if (Number.isNaN(parsed)) return '未知时间'
  const diffMin = Math.round((Date.now() - parsed) / 60000)
  if (diffMin < 1) return '刚刚更新'
  if (diffMin < 60) return `${diffMin} 分钟前更新`
  const diffHour = Math.round(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前更新`
  return `${new Date(parsed).toLocaleDateString('zh-CN')} 更新`
}

function summarize(template: CharacterTemplate): string {
  const data = (template.data ?? {}) as Record<string, unknown>
  const occupation = typeof data.occupation === 'string' ? data.occupation : ''
  const attributes = data.attributes
  const started =
    attributes !== null && typeof attributes === 'object' && Object.keys(attributes).length > 0
  if (!started) return '尚未开始建卡'
  return occupation || '未选择职业'
}

function CharacterCard({
  template,
  portraitUrl,
  pendingDelete,
  deleting,
  onOpen,
  onAskDelete,
  onDelete,
  onCancelDelete,
}: {
  template: CharacterTemplate
  portraitUrl?: string
  pendingDelete: boolean
  deleting: boolean
  onOpen: () => void
  onAskDelete: () => void
  onDelete: () => void
  onCancelDelete: () => void
}) {
  return (
    <article className="character-library__card" data-testid={`character-card-${template.templateId}`}>
      <button
        type="button"
        className="character-library__card-open"
        onClick={onOpen}
        aria-label={`打开 ${template.name} 的角色卡`}
      >
        <img
          className="character-library__card-frame"
          src="/assets/characters/library/card-frame.webp"
          alt=""
          aria-hidden="true"
          width={314}
          height={553}
        />
        <img
          className="character-library__paperclip"
          src="/assets/characters/library/paperclip.webp"
          alt=""
          aria-hidden="true"
          width={87}
          height={104}
        />
        <span className="character-library__portrait">
          {portraitUrl ? (
            <img src={portraitUrl} alt={`${template.name}的人物图片`} />
          ) : (
            <UserRound aria-hidden="true" />
          )}
        </span>
        <span className="character-library__name">{template.name}</span>
        <span className="character-library__occupation">{summarize(template)}</span>
        <span className="character-library__updated">{formatTime(template.updatedAt)}</span>
      </button>

      <div className="character-library__delete-wrap">
        {pendingDelete ? (
          <div className="character-library__confirm" role="group" aria-label={`确认删除 ${template.name}`}>
            <span>删除这张卡？</span>
            <div>
              <button type="button" onClick={onDelete} disabled={deleting}>
                {deleting ? '删除中…' : '确认'}
              </button>
              <button type="button" onClick={onCancelDelete} disabled={deleting}>
                取消
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="character-library__delete" onClick={onAskDelete} aria-label={`删除 ${template.name}`}>
            <img src="/assets/characters/library/delete-button.webp" alt="" aria-hidden="true" width={102} height={105} />
          </button>
        )}
      </div>
    </article>
  )
}

export default function CharacterLibraryPage() {
  const navigate = useNavigate()
  const [templates, setTemplates] = useState<CharacterTemplate[] | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const portraitUrls = useTemplatePortraits(templates)

  const loadTemplates = useCallback(() => {
    setError('')
    setTemplates(null)
    void listCharacterTemplates()
      .then(setTemplates)
      .catch((err) => setError(friendlyErrorMessage(err, '加载角色卡库失败')))
  }, [])

  useEffect(() => {
    loadTemplates()
  }, [loadTemplates])

  const handleCreate = async () => {
    if (creating) return
    setCreating(true)
    setError('')
    try {
      const used = new Set((templates ?? []).map((item) => item.name))
      let name = '未命名调查员'
      for (let n = 2; used.has(name); n += 1) name = `未命名调查员 ${n}`
      const created = await createCharacterTemplate(name)
      navigate(`/home/characters/${created.templateId}`)
    } catch (err) {
      setError(friendlyErrorMessage(err, '新建角色卡失败'))
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (templateId: string) => {
    if (deletingId) return
    setDeletingId(templateId)
    setError('')
    try {
      await deleteCharacterTemplate(templateId)
      setTemplates((current) => (current ?? []).filter((item) => item.templateId !== templateId))
      setPendingDelete(null)
    } catch (err) {
      setError(friendlyErrorMessage(err, '删除角色卡失败'))
    } finally {
      setDeletingId(null)
    }
  }

  const isLoading = templates === null && !error

  return (
    <section className="character-library-scene" aria-labelledby="character-library-page-title">
      <div className="character-library-scene__artboard">
        <img
          className="character-library-scene__background"
          src="/assets/characters/library/background.webp"
          alt=""
          aria-hidden="true"
          width={853}
          height={1844}
        />
        <button type="button" className="character-library__back" onClick={() => navigate('/home')} aria-label="返回首页">
          <ArrowLeft aria-hidden="true" />
        </button>
        <header className="character-library__header">
          <PawPrint aria-hidden="true" />
          <div>
            <h1 id="character-library-page-title">我的角色卡</h1>
            <p>管理你的角色卡片</p>
          </div>
          <PawPrint aria-hidden="true" />
        </header>

        <section className="character-library__content" aria-labelledby="character-library-title">
          <h2 id="character-library-title" className="sr-only">我的角色卡列表</h2>
          {error && (
            <div className="character-library__error" role="alert">
              <span>{error}</span>
              <button type="button" onClick={loadTemplates} aria-label="重试加载角色卡">
                <RefreshCw aria-hidden="true" /> 重试
              </button>
            </div>
          )}
          {isLoading && (
            <div className="character-library__status" role="status" aria-label="正在加载角色卡">
              <LoaderCircle aria-hidden="true" />
              <span>正在整理档案…</span>
            </div>
          )}
          {templates !== null && (
            <div
              className="character-library__grid"
              tabIndex={0}
              aria-label="角色卡列表，可纵向滚动"
            >
              {templates.map((template) => (
                <CharacterCard
                  key={template.templateId}
                  template={template}
                  portraitUrl={portraitUrls[template.templateId]}
                  pendingDelete={pendingDelete === template.templateId}
                  deleting={deletingId === template.templateId}
                  onOpen={() => navigate(`/home/characters/${template.templateId}`)}
                  onAskDelete={() => setPendingDelete(template.templateId)}
                  onDelete={() => void handleDelete(template.templateId)}
                  onCancelDelete={() => setPendingDelete(null)}
                />
              ))}
              <button
                type="button"
                className="character-library__new-card"
                onClick={() => void handleCreate()}
                disabled={creating}
                aria-label="从空白卡新建角色卡"
              >
                {creating ? <LoaderCircle aria-hidden="true" /> : <Plus aria-hidden="true" />}
                <span>{creating ? '正在创建…' : '新建角色卡'}</span>
              </button>
            </div>
          )}
        </section>
      </div>
    </section>
  )
}

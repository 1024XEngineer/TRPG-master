import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Plus, Trash2, User } from 'lucide-react'
import { friendlyErrorMessage } from '@/services/api-client'
import { useTemplatePortraits } from '@/hooks/useTemplatePortraits'
import {
  createCharacterTemplate,
  deleteCharacterTemplate,
  listCharacterTemplates,
  type CharacterTemplate,
} from '@/services/character/template-api'

// 后端返回的是 ISO-8601 字符串（pydantic 的 datetime 序列化结果），不是毫秒
// 时间戳——直接参与算术会得到 NaN，一路落到 "Invalid Date"。这个坑在
// MyRoomsPage 上真踩过（issue #75），这里沿用同一份处理。
function formatTime(ts: string): string {
  const parsed = Date.parse(ts)
  if (Number.isNaN(parsed)) return '未知时间'
  const diffMin = Math.round((Date.now() - parsed) / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin} 分钟前`
  const diffHour = Math.round(diffMin / 60)
  if (diffHour < 24) return `${diffHour} 小时前`
  return new Date(parsed).toLocaleDateString('zh-CN')
}

function summarize(template: CharacterTemplate): string {
  const data = (template.data ?? {}) as Record<string, unknown>
  const occupation = typeof data.occupation === 'string' ? data.occupation : ''
  // 属性为空说明这张卡刚建、还没捏——如实说，不要显示成一张完整的卡。
  const attributes = data.attributes
  const started =
    attributes !== null && typeof attributes === 'object' && Object.keys(attributes).length > 0
  if (!started) return '尚未开始建卡'
  return occupation || '未选择职业'
}

export default function CharacterLibraryPage() {
  const navigate = useNavigate()
  const [templates, setTemplates] = useState<CharacterTemplate[] | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const portraitUrls = useTemplatePortraits(templates)

  useEffect(() => {
    listCharacterTemplates()
      .then(setTemplates)
      .catch((err) => setError(friendlyErrorMessage(err, '加载角色卡库失败')))
  }, [])

  const handleCreate = async () => {
    setCreating(true)
    setError('')
    try {
      // 空白卡之间也会撞去重约束（#337：两张都是空的就是"一模一样"）。所以新建
      // 时先挑一个当前列表里没用过的名字，而不是让玩家点第二次"新建"就吃 409。
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
    setDeletingId(templateId)
    setError('')
    try {
      await deleteCharacterTemplate(templateId)
      setTemplates((current) =>
        (current ?? []).filter((item) => item.templateId !== templateId)
      )
      setPendingDelete(null)
    } catch (err) {
      setError(friendlyErrorMessage(err, '删除角色卡失败'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div className="animate-screen-in min-h-screen bg-page pb-10">
      <div className="flex items-center gap-2.5 px-5 pt-3 pb-2">
        <button
          onClick={() => navigate('/home')}
          aria-label="返回"
          className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel active:scale-[0.94] transition-all"
        >
          <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
        </button>
        <h2 className="text-lg font-bold text-text-primary">我的角色卡</h2>
      </div>

      <div className="px-5 space-y-5">
        {error && <p className="text-[11px] text-[#c04040] text-center">{error}</p>}

        {templates === null && !error && (
          <p className="text-center text-sm text-text-dim py-10">加载中…</p>
        )}

        {templates !== null && templates.length === 0 && (
          <div className="text-center py-16 space-y-4">
            <p className="text-sm text-text-dim">卡库里还没有角色卡</p>
            <p className="text-[11px] text-text-muted px-8">
              建好的调查员存在这里，下次开局可以直接选，不用从头再捏一遍。
            </p>
          </div>
        )}

        {templates !== null && templates.length > 0 && (
          <div className="space-y-2.5">
            {templates.map((template) => (
              <div
                key={template.templateId}
                className="bg-card border border-border-light rounded-md p-[14px] flex items-center gap-3"
              >
                <button
                  type="button"
                  onClick={() => navigate(`/home/characters/${template.templateId}`)}
                  className="flex flex-1 min-w-0 items-center gap-3 text-left"
                >
                  <div className="h-14 w-14 flex-shrink-0 overflow-hidden rounded-sm border border-border-light bg-input flex items-center justify-center">
                    {portraitUrls[template.templateId] ? (
                      <img
                        src={portraitUrls[template.templateId]}
                        alt={`${template.name}的人物图片`}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <User className="h-6 w-6 text-text-dim" aria-hidden="true" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-text-primary truncate">
                      {template.name}
                    </div>
                    <div className="text-[11px] text-text-muted mt-0.5">
                      {summarize(template)} · {formatTime(template.updatedAt)}
                    </div>
                  </div>
                </button>
                {pendingDelete === template.templateId ? (
                  <div className="flex items-center gap-1.5">
                    <button
                      onClick={() => handleDelete(template.templateId)}
                      disabled={deletingId === template.templateId}
                      className="px-3 py-2 rounded-sm text-xs font-semibold bg-[#c04040] text-white active:scale-[0.96] transition-all disabled:opacity-60"
                    >
                      {deletingId === template.templateId ? '删除中…' : '确认删除'}
                    </button>
                    <button
                      onClick={() => setPendingDelete(null)}
                      className="px-3 py-2 rounded-sm text-xs font-semibold bg-card text-text-body border border-border-mid active:bg-panel active:scale-[0.96] transition-all"
                    >
                      取消
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setPendingDelete(template.templateId)}
                    aria-label={`删除 ${template.name}`}
                    className="w-[34px] h-[34px] rounded-sm border border-border-mid flex items-center justify-center text-text-muted active:bg-panel active:scale-[0.96] transition-all"
                  >
                    <Trash2 className="w-[16px] h-[16px]" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {templates !== null && (
          <button
            onClick={handleCreate}
            disabled={creating}
            className="flex items-center justify-center gap-2 px-6 py-3 w-full rounded-sm text-sm font-semibold bg-brass text-white active:bg-brass-dark active:scale-[0.97] transition-all disabled:opacity-60"
          >
            {creating ? (
              <>
                <User className="w-[16px] h-[16px]" /> 新建中…
              </>
            ) : (
              <>
                <Plus className="w-[16px] h-[16px]" /> 新建角色卡
              </>
            )}
          </button>
        )}
      </div>
    </div>
  )
}

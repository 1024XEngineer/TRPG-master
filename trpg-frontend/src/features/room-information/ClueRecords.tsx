import { Plus, Save } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { InformationSection, UnreadDot } from './InformationDisclosure'

interface ManualRecord {
  id: string
  title: string
  content: string
}

interface ClueRecordsProps {
  roomId: string | null
  information: readonly { id: string; title: string; summary: string }[]
  isUnread: (id: string) => boolean
}

function isManualRecord(value: unknown): value is ManualRecord {
  if (!value || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return typeof record.id === 'string' && record.id.length > 0
    && typeof record.title === 'string' && typeof record.content === 'string'
}

function loadRecords(roomId: string | null): { records: ManualRecord[]; error: string | null } {
  if (!roomId) return { records: [], error: null }
  try {
    const raw = localStorage.getItem(`aidm-records-${roomId}`)
    if (raw !== null) {
      const saved = JSON.parse(raw)
      if (saved?.version !== 1 || !Array.isArray(saved.records)
        || !saved.records.every(isManualRecord)
        || new Set(saved.records.map((record: ManualRecord) => record.id)).size !== saved.records.length) {
        throw new Error('Invalid saved records')
      }
      return { records: saved.records, error: null }
    }
    // Keep the old text untouched; import it into the shared list on the first save.
    const legacy = localStorage.getItem(`aidm-notes-${roomId}`)
    return { records: legacy?.trim() ? [{ id: 'legacy-notes', title: '手写笔记', content: legacy }] : [], error: null }
  } catch {
    return { records: [], error: '无法读取已保存的记录，请刷新后重试。' }
  }
}

export function ClueRecords(props: ClueRecordsProps) {
  return <RoomClueRecords key={props.roomId} {...props} />
}

function RoomClueRecords({ roomId, information, isUnread }: ClueRecordsProps) {
  const [loaded] = useState(() => loadRecords(roomId))
  const [records, setRecords] = useState(loaded.records)
  const [editor, setEditor] = useState<{ id: string | null; title: string; content: string } | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [savedId, setSavedId] = useState<string | null>(null)
  const savedRecordRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (savedId) savedRecordRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [savedId])

  function saveRecord(event: FormEvent) {
    event.preventDefault()
    if (!roomId || !editor?.content.trim() || loaded.error) return
    const record: ManualRecord = {
      id: editor.id ?? globalThis.crypto?.randomUUID?.() ?? `record-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      title: editor.title.trim() || '记录',
      content: editor.content,
    }
    const next = editor.id ? records.map((existing) => existing.id === editor.id ? record : existing) : [...records, record]
    try {
      localStorage.setItem(`aidm-records-${roomId}`, JSON.stringify({ version: 1, records: next }))
    } catch {
      setSaveError('保存失败，内容仍保留在编辑框中，请重试。')
      return
    }
    setRecords(next)
    setEditor(null)
    setSaveError(null)
    setSavedId(record.id)
  }

  function deleteRecord() {
    if (!roomId || !pendingDelete || editor || loaded.error) return
    const next = records.filter((record) => record.id !== pendingDelete)
    try {
      // Persist even an empty list so the old note is not imported again after deletion.
      localStorage.setItem(`aidm-records-${roomId}`, JSON.stringify({ version: 1, records: next }))
    } catch {
      setDeleteError('删除失败，记录仍保留，请重试。')
      return
    }
    setRecords(next)
    setPendingDelete(null)
    setDeleteError(null)
    setSavedId(null)
  }

  function editRecord(record: ManualRecord) {
    setSavedId(null)
    setSaveError(null)
    setEditor(record)
  }

  const recordEditor = editor && (
    <form className="room-play__information-entry room-play__information-entry--manual room-play__record-editor"
      aria-label={editor.id ? '编辑记录' : '新增记录'} onSubmit={saveRecord}>
      <input aria-label="记录标题" placeholder="记录标题（可选）" value={editor.title}
        onChange={(event) => setEditor({ ...editor, title: event.target.value })} />
      <textarea aria-label="记录内容" placeholder="写下你的发现或推测…" rows={4} autoFocus value={editor.content}
        onChange={(event) => setEditor({ ...editor, content: event.target.value })} />
      {saveError && <p role="alert" className="room-play__record-error">{saveError}</p>}
      <div className="room-play__record-editor-actions">
        <button type="button" className="room-play__record-action" onClick={() => { setEditor(null); setSaveError(null) }}>取消</button>
        <button type="submit" className="room-play__record-action is-primary" disabled={!editor.content.trim() || Boolean(loaded.error)}>
          <Save aria-hidden="true" /> 保存
        </button>
      </div>
    </form>
  )

  return (
    <InformationSection title="已知线索"
      unread={information.some((entry) => isUnread(`information:${entry.id}`))}
      actions={(
        <button type="button" className="room-play__record-action" disabled={!roomId || editor !== null || pendingDelete !== null}
          onClick={() => {
            setSavedId(null)
            setSaveError(null)
            setEditor({ id: null, title: '', content: '' })
          }}>
          <Plus aria-hidden="true" /> 新增记录
        </button>
      )}>
      {loaded.error && <p role="alert" className="room-play__record-error">{loaded.error}</p>}
      <div className="room-play__information-list">
        {editor?.id === null && recordEditor}
        {information.map((entry) => (
          <section key={`information:${entry.id}`} className="room-play__information-entry">
            <h5 className="room-play__information-title" aria-label={entry.title}>
              <span className="room-play__information-name">
                <span className="room-play__information-text">{entry.title}</span>
                {isUnread(`information:${entry.id}`) && <UnreadDot />}
              </span>
            </h5>
            <div className="room-play__information-content">{entry.summary}</div>
          </section>
        ))}
        {records.map((record) => editor?.id === record.id ? (
          <div key={`record:${record.id}`}>{recordEditor}</div>
        ) : (
          <section key={`record:${record.id}`} ref={savedId === record.id ? savedRecordRef : undefined}
            className="room-play__information-entry room-play__information-entry--manual">
            <div className="room-play__record-header">
              <h5 className="room-play__information-title">{record.title}</h5>
              <button type="button" className="room-play__record-action" aria-label={`编辑记录：${record.title}`}
                disabled={editor !== null || pendingDelete !== null} onClick={() => editRecord(record)}>编辑</button>
              <button type="button" className="room-play__record-action is-danger" aria-label={`删除记录：${record.title}`}
                disabled={editor !== null || pendingDelete !== null}
                onClick={() => { setPendingDelete(record.id); setDeleteError(null) }}>删除</button>
            </div>
            {pendingDelete === record.id && (
              <div className="room-play__record-delete-confirm" role="group" aria-label={`确认删除记录：${record.title}`}>
                <span>删除这条记录？</span>
                <button type="button" className="room-play__record-action" autoFocus
                  onClick={() => { setPendingDelete(null); setDeleteError(null) }}>取消</button>
                <button type="button" className="room-play__record-action is-danger" onClick={deleteRecord}>确认删除</button>
                {deleteError && <p role="alert" className="room-play__record-error">{deleteError}</p>}
              </div>
            )}
            <div className="room-play__information-content">{record.content}</div>
          </section>
        ))}
        {!information.length && !records.length && !editor && !loaded.error && (
          <p className="text-xs text-text-muted py-2">暂无线索或记录</p>
        )}
      </div>
    </InformationSection>
  )
}

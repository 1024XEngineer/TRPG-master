import { useEffect, useRef, useState } from 'react'
import { Clock, FileText, RotateCcw, Trash2, Users, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import type { ModuleDetail, ModuleSummary } from 'trpg-sdk'
import { FIXED_TRPG } from '@/config/games'
import { ROUTES } from '@/config/routes'
import { ModuleCover, MODULE_ASSET_ROOT } from '@/components/ModuleCover'
import { friendlyErrorMessage } from '@/services/api-client'
import { getModuleDetail, listModules } from '@/services/room'
import { useGameStore } from '@/stores/game-store'

const ASSET_ROOT = MODULE_ASSET_ROOT
const MAX_IMPORT_SIZE = 20 * 1024 * 1024
const ACCEPTED_FILE_TYPES = '.pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document'
const CARD_BACKGROUNDS = [
  `${ASSET_ROOT}/module-card-1.webp`,
  `${ASSET_ROOT}/module-card-2.webp`,
  `${ASSET_ROOT}/module-card-3.webp`,
]
const MODULE_PREPARATION_PAGE_INDEXES: Record<string, readonly number[]> = {
  'paper-chase-zh-coc7': [1],
}

const difficultyLabel: Record<number, string> = {
  1: '入门',
  2: '进阶',
  3: '挑战',
}

interface PendingImport {
  id: string
  file: File
  title: string
  extension: 'PDF' | 'DOCX'
}

function playerRange(module: ModuleSummary) {
  return module.playersMin === module.playersMax
    ? `${module.playersMin} 人`
    : `${module.playersMin}-${module.playersMax} 人`
}

function readableFileSize(size: number) {
  return `${(size / 1024 / 1024).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`
}

function contentSentences(content: string) {
  return content.match(/[^。！？]+[。！？]?/g)?.map((sentence) => sentence.trim()).filter(Boolean) ?? [content]
}

export default function ScenarioSelectionPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const detailDialogRef = useRef<HTMLElement>(null)
  const detailCloseRef = useRef<HTMLButtonElement>(null)
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null)
  const detailRequestRef = useRef(0)
  const [loadAttempt, setLoadAttempt] = useState(0)
  const [modules, setModules] = useState<ModuleSummary[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [pendingImport, setPendingImport] = useState<PendingImport | null>(null)
  const [importError, setImportError] = useState('')
  const [detailModuleId, setDetailModuleId] = useState<string | null>(null)
  const [detailCache, setDetailCache] = useState<Record<string, ModuleDetail>>({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')

  const selectedModuleId = useGameStore((state) => state.sceneId)
  const setScene = useGameStore((state) => state.setScene)
  const detailSummary = modules?.find((module) => module.id === detailModuleId) ?? null
  const detail = detailModuleId ? detailCache[detailModuleId] : undefined
  const preparationPageIndexes = detailModuleId
    ? MODULE_PREPARATION_PAGE_INDEXES[detailModuleId] ?? []
    : []
  const preparationPages = detail?.storyPages.filter((_, index) => preparationPageIndexes.includes(index)) ?? []
  const openingPages = detail?.storyPages.filter((_, index) => !preparationPageIndexes.includes(index)) ?? []

  useEffect(() => {
    let cancelled = false
    setModules(null)
    setLoadError('')
    listModules()
      .then((items) => {
        if (!cancelled) {
          setModules(items.filter((item) => item.gameSystemId === FIXED_TRPG.systemId))
        }
      })
      .catch((error) => {
        if (!cancelled) setLoadError(friendlyErrorMessage(error, '加载模组目录失败'))
      })
    return () => {
      cancelled = true
    }
  }, [loadAttempt])

  useEffect(() => {
    if (!detailModuleId) return

    const dialog = detailDialogRef.current
    if (!dialog) return

    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    detailCloseRef.current?.focus()

    const focusableSelector = [
      'a[href]',
      'button:not([disabled])',
      'input:not([disabled])',
      'select:not([disabled])',
      'textarea:not([disabled])',
      '[tabindex]:not([tabindex="-1"])',
    ].join(',')

    const focusableElements = () => Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector))
      .filter((element) => !element.hidden && element.getAttribute('aria-hidden') !== 'true')

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDetails()
        return
      }
      if (event.key !== 'Tab') return

      const elements = focusableElements()
      if (elements.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }

      const firstElement = elements[0]
      const lastElement = elements[elements.length - 1]
      const activeElement = document.activeElement
      if (event.shiftKey && (activeElement === firstElement || !dialog.contains(activeElement))) {
        event.preventDefault()
        lastElement.focus()
      } else if (!event.shiftKey && activeElement === lastElement) {
        event.preventDefault()
        firstElement.focus()
      }
    }

    const handleFocusIn = (event: FocusEvent) => {
      if (!dialog.contains(event.target as Node)) detailCloseRef.current?.focus()
    }

    window.addEventListener('keydown', handleKeyDown)
    document.addEventListener('focusin', handleFocusIn)
    return () => {
      document.body.style.overflow = previousBodyOverflow
      window.removeEventListener('keydown', handleKeyDown)
      document.removeEventListener('focusin', handleFocusIn)
    }
  }, [detailModuleId])

  const closeDetails = () => {
    detailRequestRef.current += 1
    setDetailModuleId(null)
    setDetailLoading(false)
    setDetailError('')
    window.setTimeout(() => detailTriggerRef.current?.focus(), 0)
  }

  const loadDetail = (module: ModuleSummary) => {
    const requestId = detailRequestRef.current + 1
    detailRequestRef.current = requestId
    setDetailLoading(true)
    setDetailError('')
    getModuleDetail(module.id)
      .then((result) => {
        if (detailRequestRef.current !== requestId) return
        setDetailCache((current) => ({ ...current, [module.id]: result }))
        setDetailLoading(false)
      })
      .catch((error) => {
        if (detailRequestRef.current !== requestId) return
        setDetailError(friendlyErrorMessage(error, '加载模组详情失败'))
        setDetailLoading(false)
      })
  }

  const openDetails = (module: ModuleSummary, trigger: HTMLButtonElement) => {
    if (module.status !== 'ready') return
    detailTriggerRef.current = trigger
    setDetailModuleId(module.id)
    setDetailError('')
    if (!detailCache[module.id]) loadDetail(module)
  }

  const handleSelect = () => {
    if (!detailSummary || detailSummary.status !== 'ready') return
    setScene(detailSummary.id)
    navigate(ROUTES.CREATE)
  }

  const handleImport = (file: File | undefined) => {
    if (!file) return
    setImportError('')

    const extension = file.name.split('.').pop()?.toLowerCase()
    if (extension !== 'pdf' && extension !== 'docx') {
      setImportError('仅支持 PDF 或 DOCX 文件')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }
    if (file.size > MAX_IMPORT_SIZE) {
      setImportError('文件不能超过 20 MB')
      if (fileInputRef.current) fileInputRef.current.value = ''
      return
    }

    setPendingImport({
      id: `${file.name}-${file.size}-${file.lastModified}`,
      file,
      title: file.name.replace(/\.(pdf|docx)$/i, ''),
      extension: extension.toUpperCase() as 'PDF' | 'DOCX',
    })
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const removePendingImport = () => {
    setPendingImport(null)
    setImportError('')
  }

  return (
    <div className="scenario-selection-scene">
      <img
        className="scenario-selection-scene__background"
        src={`${ASSET_ROOT}/background.webp`}
        alt=""
        aria-hidden="true"
      />

      <header className="scenario-selection-scene__header" inert={detailModuleId ? true : undefined}>
        <button
          type="button"
          aria-label="返回创建房间"
          onClick={() => navigate(ROUTES.CREATE)}
          className="scenario-selection-scene__back"
        >
          <img src={`${ASSET_ROOT}/back-button.webp`} alt="" aria-hidden="true" />
        </button>
        <h1 className="scenario-selection-scene__title">
          <img src={`${ASSET_ROOT}/title.webp`} alt="选择模组" />
        </h1>
      </header>

      <main
        className="scenario-selection-scene__catalog"
        aria-label="COC7 模组目录"
        inert={detailModuleId ? true : undefined}
      >
        {pendingImport && (
          <article className="scenario-module-card scenario-module-card--pending">
            <img
              className="scenario-module-card__paper"
              src={CARD_BACKGROUNDS[0]}
              alt=""
              aria-hidden="true"
            />
            <div className="scenario-module-card__content">
              <ModuleCover
                moduleId={pendingImport.id}
                title={pendingImport.title}
                className="scenario-module-card__cover"
                imageClassName="scenario-module-card__cover-image"
                frameClassName="scenario-module-card__cover-frame"
              />
              <div className="scenario-module-card__information">
                <div className="scenario-module-card__heading">
                  <h2>{pendingImport.title}</h2>
                  <span>{pendingImport.extension}</span>
                </div>
                <p className="scenario-module-card__subtitle">待解析的本地模组</p>
                <p className="scenario-module-card__synopsis">
                  文件已加入队列，解析服务尚未接入。
                </p>
              </div>
              <div className="scenario-module-card__metadata">
                <span><FileText aria-hidden="true" />{readableFileSize(pendingImport.file.size)}</span>
                <span className="scenario-module-card__status scenario-module-card__status--parsing">
                  解析中
                </span>
              </div>
            </div>
            <button
              type="button"
              className="scenario-module-card__remove"
              aria-label={`删除正在解析的模组 ${pendingImport.title}`}
              onClick={removePendingImport}
            >
              <Trash2 aria-hidden="true" />
            </button>
          </article>
        )}

        {modules === null && !loadError && (
          <section className="scenario-selection-state" aria-live="polite">
            <span className="scenario-selection-state__spinner" aria-hidden="true" />
            <h2>正在翻阅模组档案</h2>
            <p>请稍候，调查资料正在整理中……</p>
          </section>
        )}

        {loadError && (
          <section className="scenario-selection-state scenario-selection-state--error" role="alert">
            <h2>模组档案读取失败</h2>
            <p>{loadError}</p>
            <button type="button" onClick={() => setLoadAttempt((value) => value + 1)}>
              <RotateCcw aria-hidden="true" />重新加载
            </button>
          </section>
        )}

        {modules?.length === 0 && (
          <section className="scenario-selection-state">
            <FileText aria-hidden="true" />
            <h2>暂无可用模组</h2>
            <p>当前没有已发布的 COC7 模组，可以先导入本地文件。</p>
          </section>
        )}

        {modules?.map((module, index) => {
          const isReady = module.status === 'ready'
          const isSelected = selectedModuleId === module.id
          const difficulty = difficultyLabel[module.difficulty] ?? `等级 ${module.difficulty}`

          return (
            <article
              className={`scenario-module-card${isReady ? '' : ' scenario-module-card--disabled'}`}
              key={module.id}
            >
              <img
                className="scenario-module-card__paper"
                src={CARD_BACKGROUNDS[index % CARD_BACKGROUNDS.length]}
                alt=""
                aria-hidden="true"
              />
              <div className="scenario-module-card__content">
                <ModuleCover
                  moduleId={module.id}
                  title={module.title}
                  className="scenario-module-card__cover"
                  imageClassName="scenario-module-card__cover-image"
                  frameClassName="scenario-module-card__cover-frame"
                />
                <div className="scenario-module-card__information">
                  <div className="scenario-module-card__heading">
                    <h2>{module.title}</h2>
                    <span>{FIXED_TRPG.systemCatalogName} · {difficulty}</span>
                  </div>
                  <p className="scenario-module-card__subtitle">{module.nameEn || `v${module.version}`}</p>
                  <p className="scenario-module-card__synopsis">
                    {module.synopsis || '这份模组暂时没有公开故事简介。'}
                  </p>
                </div>
                <div className="scenario-module-card__metadata">
                  <span><Users aria-hidden="true" />{playerRange(module)}</span>
                  <span><Clock aria-hidden="true" />{module.estimatedDuration || '时长待定'}</span>
                  <span className={`scenario-module-card__status${isSelected ? ' scenario-module-card__status--selected' : ''}`}>
                    {isReady ? (isSelected ? '已选择' : '未选择') : '开发中'}
                  </span>
                </div>
              </div>
              <button
                type="button"
                className="scenario-module-card__hit-area"
                aria-label={`查看模组 ${module.title} 详情`}
                disabled={!isReady}
                onClick={(event) => openDetails(module, event.currentTarget)}
              />
            </article>
          )
        })}
      </main>

      <footer className="scenario-selection-scene__footer" inert={detailModuleId ? true : undefined}>
        <input
          ref={fileInputRef}
          className="sr-only"
          type="file"
          aria-label="选择 PDF 或 DOCX 模组文件"
          accept={ACCEPTED_FILE_TYPES}
          onChange={(event) => handleImport(event.target.files?.[0])}
        />
        <button
          type="button"
          className="scenario-selection-scene__import"
          aria-label={pendingImport ? '已有模组正在解析，请先删除后再导入' : '导入 PDF 或 DOCX 模组'}
          disabled={Boolean(pendingImport)}
          onClick={() => fileInputRef.current?.click()}
        >
          <img src={`${ASSET_ROOT}/import-button.webp`} alt="" aria-hidden="true" />
        </button>
        <p>支持 PDF、DOCX，单个文件不超过 20 MB</p>
        {importError && <p className="scenario-selection-scene__import-error" role="alert">{importError}</p>}
      </footer>

      {detailModuleId && detailSummary && (
        <div className="scenario-module-detail" role="presentation" onMouseDown={(event) => {
          if (event.target === event.currentTarget) closeDetails()
        }}>
          <section
            ref={detailDialogRef}
            className="scenario-module-detail__dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="scenario-module-detail-title"
            tabIndex={-1}
          >
            <button
              ref={detailCloseRef}
              type="button"
              className="scenario-module-detail__close"
              aria-label="关闭模组详情"
              onClick={closeDetails}
            >
              <X aria-hidden="true" />
            </button>

            <div className="scenario-module-detail__header">
              <ModuleCover
                moduleId={detailSummary.id}
                title={detailSummary.title}
                className="scenario-module-card__cover"
                imageClassName="scenario-module-card__cover-image"
                frameClassName="scenario-module-card__cover-frame"
              />
              <div className="scenario-module-detail__identity">
                <span>{detail?.storyLabel || FIXED_TRPG.systemCatalogName}</span>
                <h2 id="scenario-module-detail-title">{detailSummary.title}</h2>
                <p>{detail?.subtitle || detailSummary.nameEn || `v${detailSummary.version}`}</p>
                <div className="scenario-module-detail__metadata">
                  <span><Users aria-hidden="true" />{playerRange(detailSummary)}</span>
                  <span><Clock aria-hidden="true" />{detailSummary.estimatedDuration || '时长待定'}</span>
                  <span><FileText aria-hidden="true" />CoC 7e</span>
                </div>
              </div>
            </div>

            <div className="scenario-module-detail__body">
              {detailLoading && (
                <div className="scenario-module-detail__state" aria-live="polite">
                  <span className="scenario-selection-state__spinner" aria-hidden="true" />
                  正在展开故事档案……
                </div>
              )}

              {detailError && (
                <div className="scenario-module-detail__state scenario-module-detail__state--error" role="alert">
                  <p>{detailError}</p>
                  <button type="button" onClick={() => loadDetail(detailSummary)}>
                    <RotateCcw aria-hidden="true" />重新加载
                  </button>
                </div>
              )}

              {detail && !detailLoading && (
                <>
                  <section>
                    <h3>故事简介</h3>
                    <p>{detail.synopsis || '这份模组暂时没有公开故事简介。'}</p>
                  </section>
                  <section>
                    <h3>开局提示</h3>
                    {openingPages.length > 0 ? openingPages.map((page, index) => (
                      <div className="scenario-module-detail__story-page" key={`${page.title}-${index}`}>
                        {page.title && <h4>{page.title}</h4>}
                        <p>{page.content}</p>
                      </div>
                    )) : <p>这份模组暂时没有额外的开局提示。</p>}
                  </section>
                  {preparationPages.map((page, index) => (
                    <section className="scenario-module-detail__preparation" key={`${page.title}-${index}`}>
                      <h3>{page.title || '调查员准备'}</h3>
                      <ul>
                        {contentSentences(page.content).map((sentence, sentenceIndex) => (
                          <li key={`${sentence}-${sentenceIndex}`}>{sentence}</li>
                        ))}
                      </ul>
                    </section>
                  ))}
                </>
              )}
            </div>

            <div className="scenario-module-detail__actions">
              <button
                type="button"
                className="scenario-module-detail__select"
                disabled={!detail || detailLoading}
                onClick={handleSelect}
              >
                <span aria-hidden="true">◆</span>
                {selectedModuleId === detailSummary.id ? '确认继续使用' : '选择此模组'}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

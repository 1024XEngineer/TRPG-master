import { useEffect, useRef, useState } from 'react'
import type { CharacterTemplate } from '@/services/character/template-api'
import { getCharacterTemplatePortrait } from '@/services/character/template-api'

interface CachedPortrait {
  version: string
  url: string
}

function mapsEqual(current: Record<string, string>, next: Record<string, string>): boolean {
  const currentIds = Object.keys(current)
  const nextIds = Object.keys(next)
  return currentIds.length === nextIds.length
    && nextIds.every((templateId) => current[templateId] === next[templateId])
}

/** 加载账号级角色卡头像，并集中管理请求取消和 Object URL 生命周期。 */
export function useTemplatePortraits(
  templates: readonly CharacterTemplate[] | null,
): Record<string, string> {
  const cacheRef = useRef(new Map<string, CachedPortrait>())
  const requestsRef = useRef(new Map<string, AbortController>())
  const [urls, setUrls] = useState<Record<string, string>>({})

  useEffect(() => {
    const syncUrls = () => {
      const next = Object.fromEntries(
        [...cacheRef.current].map(([templateId, item]) => [templateId, item.url]),
      )
      setUrls((current) => mapsEqual(current, next) ? current : next)
    }

    const activeIds = new Set((templates ?? []).map((template) => template.templateId))
    for (const [templateId, cached] of cacheRef.current) {
      const template = templates?.find((item) => item.templateId === templateId)
      if (
        !activeIds.has(templateId)
        || !template?.hasPortrait
        || !template.portraitVersion
        || cached.version !== template.portraitVersion
      ) {
        URL.revokeObjectURL(cached.url)
        cacheRef.current.delete(templateId)
        requestsRef.current.get(templateId)?.abort()
        requestsRef.current.delete(templateId)
      }
    }

    for (const template of templates ?? []) {
      const version = template.portraitVersion
      if (!template.hasPortrait || !version) continue
      if (cacheRef.current.get(template.templateId)?.version === version) continue

      requestsRef.current.get(template.templateId)?.abort()
      const controller = new AbortController()
      requestsRef.current.set(template.templateId, controller)
      void getCharacterTemplatePortrait(template.templateId, version, controller.signal)
        .then((blob) => {
          if (
            controller.signal.aborted
            || requestsRef.current.get(template.templateId) !== controller
          ) return
          const url = URL.createObjectURL(blob)
          const previous = cacheRef.current.get(template.templateId)
          cacheRef.current.set(template.templateId, { version, url })
          requestsRef.current.delete(template.templateId)
          if (previous) URL.revokeObjectURL(previous.url)
          syncUrls()
        })
        .catch(() => {
          // 头像加载失败只回退到占位图，不阻断角色卡列表和选卡流程。
          if (requestsRef.current.get(template.templateId) === controller) {
            requestsRef.current.delete(template.templateId)
          }
        })
    }

    syncUrls()
  }, [templates])

  useEffect(() => () => {
    for (const controller of requestsRef.current.values()) controller.abort()
    for (const cached of cacheRef.current.values()) URL.revokeObjectURL(cached.url)
    requestsRef.current.clear()
    cacheRef.current.clear()
  }, [])

  return urls
}

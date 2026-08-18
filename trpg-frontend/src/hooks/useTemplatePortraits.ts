import { useEffect, useRef, useState } from 'react'
import type { CharacterTemplate } from '@/services/character/template-api'
import { getCharacterTemplatePortrait } from '@/services/character/template-api'

interface CachedPortrait {
  version: string
  url: string
}

interface PendingPortrait {
  version: string
  controller: AbortController
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
  const requestsRef = useRef(new Map<string, PendingPortrait>())
  const [urls, setUrls] = useState<Record<string, string>>({})

  useEffect(() => {
    const syncUrls = () => {
      const next = Object.fromEntries(
        [...cacheRef.current].map(([templateId, item]) => [templateId, item.url]),
      )
      setUrls((current) => mapsEqual(current, next) ? current : next)
    }

    const activePortraitVersions = new Map(
      (templates ?? [])
        .filter((template) => template.hasPortrait && template.portraitVersion)
        .map((template) => [template.templateId, template.portraitVersion as string]),
    )

    // 请求可能尚未进入 cacheRef。模板被删除、切换为无头像或版本变化时，也必须
    // 立即使旧请求失效，避免它随后把过期 Blob URL 写回页面。
    for (const [templateId, pending] of requestsRef.current) {
      if (activePortraitVersions.get(templateId) !== pending.version) {
        pending.controller.abort()
        requestsRef.current.delete(templateId)
      }
    }

    for (const [templateId, cached] of cacheRef.current) {
      if (activePortraitVersions.get(templateId) !== cached.version) {
        URL.revokeObjectURL(cached.url)
        cacheRef.current.delete(templateId)
      }
    }

    for (const template of templates ?? []) {
      const version = template.portraitVersion
      if (!template.hasPortrait || !version) continue
      if (cacheRef.current.get(template.templateId)?.version === version) continue

      const pending = requestsRef.current.get(template.templateId)
      if (pending?.version === version) continue
      pending?.controller.abort()
      const controller = new AbortController()
      requestsRef.current.set(template.templateId, { version, controller })
      void getCharacterTemplatePortrait(template.templateId, version, controller.signal)
        .then((blob) => {
          const currentRequest = requestsRef.current.get(template.templateId)
          if (
            controller.signal.aborted
            || currentRequest?.controller !== controller
            || currentRequest.version !== version
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
          if (requestsRef.current.get(template.templateId)?.controller === controller) {
            requestsRef.current.delete(template.templateId)
          }
        })
    }

    syncUrls()
  }, [templates])

  useEffect(() => () => {
    for (const pending of requestsRef.current.values()) pending.controller.abort()
    for (const cached of cacheRef.current.values()) URL.revokeObjectURL(cached.url)
    requestsRef.current.clear()
    cacheRef.current.clear()
  }, [])

  return urls
}

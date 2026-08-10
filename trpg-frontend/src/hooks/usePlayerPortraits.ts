/**
 * 按房间成员的头像版本加载鉴权 Blob，并统一管理 Object URL 的复用与释放。
 */
import { useEffect, useRef, useState } from 'react'
import type { RoomPlayerSummary } from 'trpg-sdk'
import { sdk } from '@/services/api-client'

interface CachedPortrait {
  roomId: string
  version: string
  url: string
}

export function usePlayerPortraits(
  roomId: string | null,
  reconnectToken: string | null,
  players: readonly RoomPlayerSummary[],
): Record<string, string> {
  const cacheRef = useRef(new Map<string, CachedPortrait>())
  const requestsRef = useRef(new Map<string, AbortController>())
  const [urls, setUrls] = useState<Record<string, string>>({})

  useEffect(() => {
    const activePlayerIds = new Set(players.map((player) => player.playerId))

    // 房间成员离开、切换房间或头像被清除时，立即释放不再可见的 Blob URL。
    for (const [cachedPlayerId, cached] of cacheRef.current) {
      const player = players.find((item) => item.playerId === cachedPlayerId)
      if (
        !activePlayerIds.has(cachedPlayerId)
        || !player?.hasPortrait
        || !player.portraitVersion
        || cached.roomId !== roomId
      ) {
        URL.revokeObjectURL(cached.url)
        cacheRef.current.delete(cachedPlayerId)
        requestsRef.current.get(cachedPlayerId)?.abort()
        requestsRef.current.delete(cachedPlayerId)
      }
    }

    if (!roomId || !reconnectToken) {
      setUrls({})
      return
    }

    for (const player of players) {
      const version = player.portraitVersion
      if (!player.hasPortrait || !version) continue
      const cached = cacheRef.current.get(player.playerId)
      if (cached?.roomId === roomId && cached.version === version) continue

      requestsRef.current.get(player.playerId)?.abort()
      const controller = new AbortController()
      requestsRef.current.set(player.playerId, controller)
      void sdk.characters
        .getPlayerPortrait(roomId, player.playerId, version, reconnectToken, controller.signal)
        .then((blob) => {
          if (controller.signal.aborted || requestsRef.current.get(player.playerId) !== controller) {
            return
          }
          const url = URL.createObjectURL(blob)
          const previous = cacheRef.current.get(player.playerId)
          cacheRef.current.set(player.playerId, { roomId, version, url })
          requestsRef.current.delete(player.playerId)
          if (previous) URL.revokeObjectURL(previous.url)
          setUrls(Object.fromEntries(
            [...cacheRef.current].map(([id, item]) => [id, item.url]),
          ))
        })
        .catch(() => {
          // 头像是增强展示；鉴权过期或网络失败时保留旧图/默认图标，不阻断游戏。
          if (requestsRef.current.get(player.playerId) === controller) {
            requestsRef.current.delete(player.playerId)
          }
        })
    }

    setUrls(Object.fromEntries(
      [...cacheRef.current].map(([id, item]) => [id, item.url]),
    ))
  }, [players, reconnectToken, roomId])

  useEffect(() => () => {
    for (const controller of requestsRef.current.values()) controller.abort()
    for (const cached of cacheRef.current.values()) URL.revokeObjectURL(cached.url)
    requestsRef.current.clear()
    cacheRef.current.clear()
  }, [])

  return urls
}

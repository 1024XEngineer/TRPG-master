import { useEffect, useState } from 'react'

export interface RoomPanelEntry {
  id: string
  panel: 'map' | 'notes'
  content: string
}

interface PanelMemory {
  version: 1
  initialized: boolean
  seen: Record<string, string>
  unread: Record<string, string>
  collapsed: Record<string, boolean>
}

interface PanelState extends PanelMemory {
  storageKey: string | null
  entries: readonly RoomPanelEntry[] | null
  openPanel: string | null
}

function isRecordOf(value: unknown, type: 'string' | 'boolean'): boolean {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && Object.values(value).every((entry) => typeof entry === type)
}

function restore(storageKey: string | null): PanelState {
  const initial: PanelState = {
    version: 1, initialized: false, seen: {}, unread: {}, collapsed: {},
    storageKey, entries: null, openPanel: null,
  }
  if (!storageKey) return initial
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) ?? 'null')
    if (saved?.version === 1 && typeof saved.initialized === 'boolean'
      && isRecordOf(saved.seen, 'string') && isRecordOf(saved.unread, 'string')
      && isRecordOf(saved.collapsed, 'boolean')) {
      return { ...initial, initialized: saved.initialized, seen: saved.seen,
        unread: saved.unread, collapsed: saved.collapsed }
    }
  } catch { /* Storage may be unavailable; keep the current visit usable. */ }
  return initial
}

function observe(state: PanelState, entries: readonly RoomPanelEntry[] | null): PanelState {
  if (!entries) return { ...state, entries }
  const seen = { ...state.seen }
  const unread = { ...state.unread }
  for (const entry of entries) {
    if (state.initialized && seen[entry.id] !== entry.content) {
      unread[entry.id] = entry.content
    }
    seen[entry.id] = entry.content
  }
  // Retain absent entries: returning to a scene must not rediscover its old items.
  return { ...state, entries, initialized: true, seen, unread }
}

/** #530: local reading state only; visible content still comes from PlayerView. */
export function useRoomPanelState(
  roomId: string | null,
  playerId: string | null,
  entries: readonly RoomPanelEntry[] | null,
) {
  const storageKey = roomId && playerId
    ? `aidm-room-panels:${JSON.stringify([roomId, playerId])}` : null
  const [state, setState] = useState(() => observe(restore(storageKey), entries))

  // Reconcile before rendering children so closing a panel acknowledges exactly
  // the displayed snapshot, without an effect clearing a later incoming update.
  if (state.storageKey !== storageKey) {
    setState(observe(restore(storageKey), entries))
  } else if (state.entries !== entries) {
    setState(observe(state, entries))
  }

  const serialized = JSON.stringify({
    version: state.version, initialized: state.initialized, seen: state.seen,
    unread: state.unread, collapsed: state.collapsed,
  } satisfies PanelMemory)
  useEffect(() => {
    if (!storageKey) return
    try { localStorage.setItem(storageKey, serialized) }
    catch { /* Reading and folding still work without browser persistence. */ }
  }, [storageKey, serialized])

  const unreadIds = new Set(entries?.filter((entry) =>
    state.unread[entry.id] === entry.content).map((entry) => entry.id))
  const isUnread = (id: string) => unreadIds.has(id)

  return {
    openPanel: state.openPanel,
    setOpenPanel: (next: string | null) => {
      setState((current) => {
        if (current.storageKey !== storageKey || next === current.openPanel) return current
        const unread = { ...current.unread }
        for (const entry of entries ?? []) {
          if (entry.panel === current.openPanel && unread[entry.id] === entry.content) {
            delete unread[entry.id]
          }
        }
        return { ...current, openPanel: next, unread }
      })
    },
    isUnread,
    hasUnread: (panel: RoomPanelEntry['panel']) => entries?.some((entry) =>
      entry.panel === panel && isUnread(entry.id)) ?? false,
    isExpanded: (id: string) => !state.collapsed[id],
    toggleExpanded: (id: string) => setState((current) => current.storageKey !== storageKey
      ? current
      : { ...current, collapsed: { ...current.collapsed, [id]: !current.collapsed[id] } }),
  }
}

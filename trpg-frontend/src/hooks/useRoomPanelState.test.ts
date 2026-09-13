import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRoomPanelState, type RoomPanelEntry } from './useRoomPanelState'

const location: RoomPanelEntry = { id: 'location:hall', panel: 'map', content: '门厅' }
const item: RoomPanelEntry = { id: 'item:key', panel: 'map', content: '铜钥匙 ×1' }
const clue: RoomPanelEntry = { id: 'information:letter', panel: 'notes', content: '一封信' }
const baseline = [location]

function setup(entries: RoomPanelEntry[] | null = baseline) {
  return renderHook(({ roomId, playerId, entries }) => useRoomPanelState(roomId, playerId, entries), {
    initialProps: { roomId: 'room-1', playerId: 'player-1', entries },
  })
}

describe('room panel reading state', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('waits for a real baseline and ignores reordering and repeated snapshots', () => {
    const { result, rerender } = setup(null)
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, item, clue] })
    expect(result.current.hasUnread('map')).toBe(false)
    expect(result.current.hasUnread('notes')).toBe(false)
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [clue, { ...item }, { ...location }] })
    expect(result.current.hasUnread('map')).toBe(false)
    expect(result.current.hasUnread('notes')).toBe(false)
  })

  it('keeps updates unread while open and folded, and acknowledges only the closed panel', () => {
    const { result, rerender } = setup()
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, item, clue] })
    act(() => result.current.setOpenPanel('map'))
    act(() => result.current.toggleExpanded('items'))
    expect(result.current.isUnread(item.id)).toBe(true)
    expect(result.current.hasUnread('notes')).toBe(true)
    act(() => result.current.setOpenPanel('skills'))
    expect(result.current.hasUnread('map')).toBe(false)
    expect(result.current.hasUnread('notes')).toBe(true)
    act(() => result.current.setOpenPanel('map'))
    expect(result.current.isExpanded('items')).toBe(false)
    expect(result.current.isUnread(item.id)).toBe(false)
  })

  it('does not acknowledge an update arriving after the close in the same batch', () => {
    const { result, rerender } = setup([location, clue])
    act(() => result.current.setOpenPanel('notes'))
    const updated = { ...clue, content: '信里新出现了一个地址' }
    act(() => {
      result.current.setOpenPanel(null)
      rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, updated] })
    })
    expect(result.current.openPanel).toBeNull()
    expect(result.current.isUnread(clue.id)).toBe(true)
    act(() => result.current.setOpenPanel('notes'))
    act(() => result.current.setOpenPanel(null))
    expect(result.current.isUnread(clue.id)).toBe(false)
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, { ...updated, content: '地址又多了门牌号' }] })
    expect(result.current.isUnread(clue.id)).toBe(true)
  })

  it('remembers absent items on revisiting a scene and retains their unread status', () => {
    const { result, rerender } = setup()
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, item] })
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location] })
    expect(result.current.hasUnread('map')).toBe(false)
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, item] })
    expect(result.current.isUnread(item.id)).toBe(true)
    act(() => result.current.setOpenPanel('map'))
    act(() => result.current.setOpenPanel(null))
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [] })
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, item] })
    expect(result.current.hasUnread('map')).toBe(false)
  })

  it('restores reading and folding after remount without crossing room or player identities', () => {
    const first = setup()
    first.rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, clue] })
    act(() => first.result.current.toggleExpanded('information'))
    first.unmount()
    const { result, rerender } = setup([location, clue])
    expect(result.current.hasUnread('notes')).toBe(true)
    expect(result.current.isExpanded('information')).toBe(false)
    rerender({ roomId: 'room-1', playerId: 'player-2', entries: [location, clue] })
    expect(result.current.hasUnread('notes')).toBe(false)
    expect(result.current.isExpanded('information')).toBe(true)
    rerender({ roomId: 'room-2', playerId: 'player-1', entries: [location, clue] })
    expect(result.current.hasUnread('notes')).toBe(false)
    expect(result.current.isExpanded('information')).toBe(true)
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, clue] })
    expect(result.current.hasUnread('notes')).toBe(true)
    expect(result.current.isExpanded('information')).toBe(false)
  })

  it('keeps controls usable when browser storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    const { result, rerender } = setup()
    rerender({ roomId: 'room-1', playerId: 'player-1', entries: [location, item] })
    act(() => result.current.setOpenPanel('map'))
    act(() => result.current.toggleExpanded('items'))
    act(() => result.current.setOpenPanel(null))
    expect(result.current.hasUnread('map')).toBe(false)
    expect(result.current.isExpanded('items')).toBe(false)
  })
})

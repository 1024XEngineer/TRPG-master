import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RoomConversationEvent, ServerToClientEvent } from 'trpg-sdk'
import RoomPage from './RoomPage'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { useCharacterStore } from '@/stores/character-store'

const { apiMocks, hookMocks } = vi.hoisted(() => {
  let wsHandler: ((event: ServerToClientEvent) => void) | null = null
  const apiMocks = {
    sdk: {
      rooms: {
        listConversation: vi.fn(),
      },
      roomSocket: {
        getPlayerView: vi.fn(() => null),
        joinRoom: vi.fn(),
        submitAction: vi.fn(),
        rollCheck: vi.fn(),
        sendChat: vi.fn(),
      },
    },
    connectWebSocket: vi.fn(() => ({}) as WebSocket),
    waitForWsOpen: vi.fn(() => Promise.resolve()),
    onWsMessage: vi.fn((handler: (event: ServerToClientEvent) => void) => {
      wsHandler = handler
      return () => {
        wsHandler = null
      }
    }),
    disconnectWebSocket: vi.fn(),
    friendlyErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
    emitWs: (event: ServerToClientEvent) => wsHandler?.(event),
  }
  const hookMocks = {
    useRoomPlayers: vi.fn(() => ({
      phase: 'InGame',
      players: [{ playerId: 'player-1', isHost: true }],
    })),
    useRuleset: vi.fn(() => ({ ruleset: null, loading: false, error: '' })),
    endGame: vi.fn(),
  }
  return { apiMocks, hookMocks }
})

vi.mock('@/services/api-client', () => apiMocks)
vi.mock('@/hooks/useRoomPlayers', () => ({ useRoomPlayers: hookMocks.useRoomPlayers }))
vi.mock('@/hooks/useRuleset', () => ({ useRuleset: hookMocks.useRuleset }))
vi.mock('@/services/room', () => ({ endGame: hookMocks.endGame }))

const history: RoomConversationEvent[] = [
  {
    id: 'event-narr-1',
    type: 'narration.push',
    channel: 'action',
    payload: { text: '主持历史回复' },
    createdAt: '2026-07-28T10:00:00Z',
  },
  {
    id: 'event-action-1',
    type: 'action.broadcast',
    channel: 'action',
    payload: {
      playerId: 'player-1',
      clientActionId: 'act-1',
      nickname: '调查员',
      utterance: '行动历史原话',
    },
    createdAt: '2026-07-28T10:01:00Z',
  },
  {
    id: 'event-check-1',
    type: 'check.result',
    channel: 'action',
    payload: {
      playerId: 'player-1',
      clientActionId: 'act-1',
      skill: 'stealth',
      skillName: '潜行',
      rollValue: 12,
      targetValue: 55,
      difficulty: 'regular',
      successLevel: 'regular',
      passed: true,
      result: 'regular',
    },
    createdAt: '2026-07-28T10:02:00Z',
  },
  {
    id: 'chat-1',
    type: 'chat.message',
    channel: 'discussion',
    payload: {
      messageId: 'chat-1',
      playerId: 'player-2',
      nickname: '队友',
      text: '讨论区历史',
      sentAt: '2026-07-28T10:03:00Z',
      clientMessageId: 'chat-client-1',
    },
    createdAt: '2026-07-28T10:03:00Z',
  },
]

describe('RoomPage conversation history', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Element.prototype.scrollIntoView = vi.fn()
    useRoomStore.getState().reset()
    useCharacterStore.getState().clear()
    useAuthStore.getState().logout()
    useAuthStore.getState().login('auth-token', 'user-1', '调查员')
    useRoomStore.setState({
      roomId: 'room-1',
      roomCode: 'ROOM1',
      playerId: 'player-1',
      reconnectToken: 'reconnect-1',
      moduleId: 'module-1',
      characterId: 'character-1',
      isHost: true,
    })
    apiMocks.sdk.rooms.listConversation.mockResolvedValue(history)
  })

  afterEach(() => {
    cleanup()
  })

  function renderPage() {
    return render(
      <MemoryRouter initialEntries={['/room/play']}>
        <Routes>
          <Route path="/room/play" element={<RoomPage />} />
        </Routes>
      </MemoryRouter>
    )
  }

  it('restores action and discussion messages into their channels', async () => {
    renderPage()

    await waitFor(() => {
      expect(screen.getByText('行动历史原话')).toBeInTheDocument()
    })
    expect(screen.getByText('主持历史回复')).toBeInTheDocument()
    expect(screen.getByText(/潜行 55% · D100 12 · 成功/)).toBeInTheDocument()
    expect(screen.queryByText('讨论区历史')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '讨论区' }))
    expect(screen.getByText('讨论区历史')).toBeInTheDocument()
    expect(screen.queryByText('行动历史原话')).not.toBeInTheDocument()
  })

  it('deduplicates realtime action echoes already restored from history', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('行动历史原话')).toBeInTheDocument()
    })

    act(() => {
      apiMocks.emitWs({
        type: 'action.broadcast',
        payload: {
          playerId: 'player-1',
          clientActionId: 'act-1',
          nickname: '调查员',
          utterance: '行动历史原话',
        },
      })
    })

    expect(screen.getAllByText('行动历史原话')).toHaveLength(1)
  })
})

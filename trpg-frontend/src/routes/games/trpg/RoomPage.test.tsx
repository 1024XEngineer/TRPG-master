import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { RoomConversationEvent, ServerToClientEvent } from 'trpg-sdk'
import RoomPage from './RoomPage'
import { useAuthStore } from '@/stores/auth-store'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'

const {
  emitWsMessage,
  mockGetPlayerView,
  mockJoinRoom,
  mockListConversation,
  mockOnWsMessage,
  mockWaitForWsOpen,
  wsHandlers,
} = vi.hoisted(() => {
  const handlers = new Set<(event: ServerToClientEvent) => void>()
  return {
    wsHandlers: handlers,
    emitWsMessage: (event: ServerToClientEvent) => {
      for (const handler of handlers) handler(event)
    },
    mockGetPlayerView: vi.fn(),
    mockJoinRoom: vi.fn(),
    mockListConversation: vi.fn(),
    mockOnWsMessage: vi.fn((handler: (event: ServerToClientEvent) => void) => {
      handlers.add(handler)
      return () => handlers.delete(handler)
    }),
    mockWaitForWsOpen: vi.fn(() => Promise.resolve()),
  }
})

vi.mock('@/services/api-client', () => ({
  connectWebSocket: vi.fn(() => ({}) as WebSocket),
  disconnectWebSocket: vi.fn(),
  friendlyErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
  onWsMessage: mockOnWsMessage,
  waitForWsOpen: mockWaitForWsOpen,
  sdk: {
    rooms: {
      listConversation: mockListConversation,
    },
    roomSocket: {
      getPlayerView: mockGetPlayerView,
      joinRoom: mockJoinRoom,
      rollCheck: vi.fn(),
      sendChat: vi.fn(),
      submitAction: vi.fn(),
    },
  },
}))

vi.mock('@/services/room', () => ({
  endGame: vi.fn(),
}))

vi.mock('@/hooks/useRoomPlayers', () => ({
  useRoomPlayers: () => ({
    phase: 'InGame',
    moduleTitle: '追书人',
    players: [
      {
        playerId: 'player-1',
        nickname: '陈探员',
        isHost: true,
        ready: true,
        hasCharacter: true,
      },
    ],
  }),
}))

vi.mock('@/hooks/useRuleset', () => ({
  useRuleset: () => ({
    ruleset: { attributes: [], skills: [], occupations: [] },
    loading: false,
    error: '',
  }),
}))

function renderRoomPage() {
  return render(
    <MemoryRouter>
      <RoomPage />
    </MemoryRouter>,
  )
}

function conversationHistory(): RoomConversationEvent[] {
  return [
    {
      id: 'chat-1',
      type: 'chat.message',
      channel: 'discussion',
      payload: {
        messageId: 'chat-1',
        playerId: 'player-1',
        nickname: '陈探员',
        text: '先在讨论区确认路线',
        sentAt: '2026-07-28T10:00:00Z',
        clientMessageId: 'client-chat-1',
      },
      createdAt: '2026-07-28T10:00:00Z',
    },
    {
      id: 'act-1',
      type: 'action.broadcast',
      channel: 'action',
      payload: {
        playerId: 'player-1',
        clientActionId: 'act-1',
        nickname: '陈探员',
        utterance: '我查看书架',
      },
      createdAt: '2026-07-28T10:01:00Z',
    },
    {
      id: 'act-1',
      type: 'check.result',
      channel: 'action',
      payload: {
        playerId: 'player-1',
        clientActionId: 'act-1',
        skillName: '图书馆使用',
        targetValue: 50,
        rollValue: 23,
        difficulty: 'regular',
        successLevel: 'regular',
        passed: true,
        result: 'regular',
      },
      createdAt: '2026-07-28T10:02:00Z',
    },
    {
      id: 'act-1',
      type: 'narration.push',
      channel: 'action',
      payload: {
        text: '你发现书架后有一个暗格。',
      },
      createdAt: '2026-07-28T10:03:00Z',
    },
  ]
}

describe('RoomPage conversation history', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    wsHandlers.clear()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
    localStorage.clear()
    sessionStorage.clear()
    useRoomStore.getState().reset()
    useAuthStore.getState().logout()
    useCharacterStore.getState().clear()
    useRoomStore.getState().setRoomIdentity({
      roomId: 'room-1',
      roomCode: 'ABC123',
      playerId: 'player-1',
      reconnectToken: 'reconnect-1',
    })
    useAuthStore.getState().login('token-1', 'user-1', '陈探员')
    mockGetPlayerView.mockReturnValue(null)
    mockListConversation.mockResolvedValue([])
  })

  afterEach(() => {
    cleanup()
  })

  it('restores action history by default and discussion history after switching channel', async () => {
    mockListConversation.mockResolvedValue(conversationHistory())

    renderRoomPage()

    expect(await screen.findByText('我查看书架')).toBeInTheDocument()
    expect(screen.getByText('你发现书架后有一个暗格。')).toBeInTheDocument()
    expect(screen.getByText('图书馆使用 50% · D100 23 · 成功')).toBeInTheDocument()
    expect(mockListConversation).toHaveBeenCalledWith('room-1', 'reconnect-1')

    fireEvent.click(screen.getByRole('button', { name: '讨论区' }))

    expect(await screen.findByText('先在讨论区确认路线')).toBeInTheDocument()
  })

  it('does not duplicate realtime action broadcast already restored from history', async () => {
    mockListConversation.mockResolvedValue([
      conversationHistory().find((event) => event.type === 'action.broadcast')!,
    ])

    renderRoomPage()

    expect(await screen.findByText('我查看书架')).toBeInTheDocument()

    emitWsMessage({
      type: 'action.broadcast',
      payload: {
        playerId: 'player-1',
        clientActionId: 'act-1',
        nickname: '陈探员',
        utterance: '我查看书架',
      },
    })

    await waitFor(() => {
      expect(screen.getAllByText('我查看书架')).toHaveLength(1)
    })
  })
})

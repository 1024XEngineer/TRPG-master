import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  mockRollCheck,
  mockSubmitAction,
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
    mockRollCheck: vi.fn(),
    mockOnWsMessage: vi.fn((handler: (event: ServerToClientEvent) => void) => {
      handlers.add(handler)
      return () => handlers.delete(handler)
    }),
    mockSubmitAction: vi.fn(),
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
      rollCheck: mockRollCheck,
      sendChat: vi.fn(),
      submitAction: mockSubmitAction,
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
        characterName: '杜调查员',
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
        characterName: '杜调查员',
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
    mockSubmitAction.mockReturnValue(new Promise(() => undefined))
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
    expect(screen.getByText('杜调查员 · 掷骰')).toBeInTheDocument()
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
        characterName: '杜调查员',
        utterance: '我查看书架',
      },
    })

    await waitFor(() => {
      expect(screen.getAllByText('我查看书架')).toHaveLength(1)
    })
  })

  it('falls back for legacy payloads when characterName is missing', async () => {
    useCharacterStore.getState().setCharacter(
      {
        info: {
          name: '杜调查员',
          playerName: '陈探员',
          age: '32',
          gender: '男',
          residence: '阿卡姆',
          birthplace: '波士顿',
          occupationId: null,
        },
        attr: {},
        skillAlloc: {},
        skillFinalValues: {},
        equipment: '',
        background: '',
        notes: '',
        derived: { hp: 10, san: 60, db: '0', move: 8 },
      } as never,
      'room-1',
    )
    mockListConversation.mockResolvedValue([])

    renderRoomPage()

    emitWsMessage({
      type: 'action.broadcast',
      payload: {
        playerId: 'player-1',
        clientActionId: 'legacy-act-1',
        nickname: '房主',
        utterance: '我查看书架',
      },
    })
    expect(await screen.findByText('房主')).toBeInTheDocument()

    emitWsMessage({
      type: 'check.result',
      payload: {
        playerId: 'player-1',
        clientActionId: 'legacy-act-2',
        skill: 'library-use',
        skillName: '图书馆使用',
        targetValue: 50,
        rollValue: 23,
        difficulty: 'regular',
        successLevel: 'regular',
        passed: true,
        result: 'regular',
      },
    })

    expect(await screen.findByText('杜调查员 · 掷骰')).toBeInTheDocument()
  })

  it('keeps the first check result when reopening the modal before confirming', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-1',
          summary: '调查书架',
          difficulty: 'regular',
          skills: [
            { id: 'skill-library', name: '图书馆使用', targetValue: 50 },
            { id: 'skill-search', name: '侦查', targetValue: 40 },
          ],
        },
      })
    })

    expect(await screen.findByText('图书馆使用')).toBeInTheDocument()

    vi.useFakeTimers()
    const randomSpy = vi.spyOn(Math, 'random')
      .mockReturnValueOnce(0.2)
      .mockReturnValueOnce(0.3)

    fireEvent.mouseDown(screen.getByTestId('dice-table'))
    fireEvent.mouseUp(screen.getByTestId('dice-table'))

    await act(async () => {
      vi.advanceTimersByTime(600)
    })

    expect(screen.getByText('23')).toBeInTheDocument()
    expect(mockRollCheck).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole('button', { name: '关闭面板' }).at(-1)!)
    fireEvent.click(screen.getByRole('button', { name: '骰子' }))
    expect(screen.getByText('23')).toBeInTheDocument()

    const confirmButton = screen.getByRole('button', { name: '确认并发送' })
    fireEvent.click(confirmButton)
    fireEvent.click(confirmButton)

    expect(mockRollCheck).toHaveBeenCalledTimes(1)
    expect(mockRollCheck).toHaveBeenCalledWith('player-1', {
      clientActionId: 'check-1',
      skill: 'skill-library',
      rollValue: 23,
    })

    randomSpy.mockRestore()
    vi.useRealTimers()
  })

  it('clears the pending check result when a new request arrives', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-1',
          summary: '调查书架',
          difficulty: 'regular',
          skills: [{ id: 'skill-library', name: '图书馆使用', targetValue: 50 }],
        },
      })
    })

    expect(await screen.findByText('图书馆使用')).toBeInTheDocument()

    vi.useFakeTimers()
    const randomSpy = vi.spyOn(Math, 'random')
      .mockReturnValueOnce(0.2)
      .mockReturnValueOnce(0.3)
      .mockReturnValueOnce(0.4)
      .mockReturnValueOnce(0.1)

    fireEvent.mouseDown(screen.getByTestId('dice-table'))
    fireEvent.mouseUp(screen.getByTestId('dice-table'))

    await act(async () => {
      vi.advanceTimersByTime(600)
    })

    fireEvent.click(screen.getByRole('button', { name: '确认并发送' }))
    expect(mockRollCheck).toHaveBeenCalledTimes(1)

    await act(async () => {
      emitWsMessage({
        type: 'check.result',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-1',
          skill: 'skill-library',
          skillName: '图书馆使用',
          targetValue: 50,
          rollValue: 23,
          difficulty: 'regular',
          successLevel: 'regular',
          passed: true,
          result: 'regular',
        },
      })
    })

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-2',
          summary: '再次调查',
          difficulty: 'regular',
          skills: [{ id: 'skill-search', name: '侦查', targetValue: 40 }],
        },
      })
    })

    expect(screen.getByText('侦查')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getByTestId('dice-table'))
    fireEvent.mouseUp(screen.getByTestId('dice-table'))

    await act(async () => {
      vi.advanceTimersByTime(600)
    })

    expect(screen.getByText('41')).toBeInTheDocument()

    randomSpy.mockRestore()
    vi.useRealTimers()
  })

  it('shows copyable diagnostics and only offers retry for retryable failures', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    })
    renderRoomPage()

    const input = screen.getByPlaceholderText('输入行动…')
    fireEvent.change(input, { target: { value: '我调查书架' } })
    fireEvent.submit(input.closest('form')!)
    await waitFor(() => expect(mockSubmitAction).toHaveBeenCalledTimes(1))

    act(() => emitWsMessage({
      type: 'turn.failed',
      payload: {
        correlationId: 'timeout-correlation',
        code: 'HOST_AGENT_TIMEOUT',
        publicMessage: '主持 Agent 响应超时，请重试',
        retryable: true,
      },
    }))

    expect(screen.getByText('主持 Agent 响应超时，请重试')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '使用原请求重试' })).toBeInTheDocument()
    const copyButton = screen.getByRole('button', { name: '复制错误详情' })
    expect(copyButton).toHaveTextContent(
      '错误码 HOST_AGENT_TIMEOUT · 定位号 timeout-',
    )
    fireEvent.click(copyButton)
    expect(writeText).toHaveBeenCalledWith(
      'HOST_AGENT_TIMEOUT · timeout-correlation',
    )

    act(() => emitWsMessage({
      type: 'turn.failed',
      payload: {
        correlationId: 'contract-correlation',
        code: 'TURN_CONTRACT_INVALID',
        publicMessage: '本次动作未通过主持编排契约校验',
        retryable: false,
      },
    }))

    expect(screen.getByText('本次动作未通过主持编排契约校验')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '使用原请求重试' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '复制错误详情' })).toHaveTextContent(
      'TURN_CONTRACT_INVALID',
    )
  })

  it('renders invalid Agent output as keeper guidance', () => {
    renderRoomPage()

    act(() => emitWsMessage({
      type: 'turn.failed',
      payload: {
        correlationId: 'invalid-output-correlation',
        code: 'HOST_AGENT_INVALID_OUTPUT',
        publicMessage: '请结合眼前的人物或物品，换一种说法。',
        retryable: false,
      },
    }))

    expect(
      screen.getByText('守秘人提示：请结合眼前的人物或物品，换一种说法。'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '使用原请求重试' })).not.toBeInTheDocument()
  })
})

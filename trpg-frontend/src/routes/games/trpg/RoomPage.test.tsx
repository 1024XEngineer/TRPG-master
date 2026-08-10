/**
 * RoomPage regressions for authoritative history/live message ownership and
 * opening-progress cleanup. Network and WebSocket boundaries are mocked here.
 */
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AgentPlayerView,
  RoomConversationEvent,
  ServerToClientEvent,
} from 'trpg-sdk'
import RoomPage from './RoomPage'
import { useAuthStore } from '@/stores/auth-store'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'

function installRoomSpeechApi() {
  class RoomAudio extends EventTarget {
    src = ''
    playbackRate = 1
    volume = 1
    preservesPitch = false
    play = vi.fn(async () => {})
    pause = vi.fn()
    load = vi.fn()
    removeAttribute = vi.fn()
  }
  const audio = new RoomAudio()
  vi.stubGlobal('Audio', class { constructor() { return audio } })
  vi.stubGlobal('URL', { ...URL, createObjectURL: vi.fn(() => 'blob:room-speech'), revokeObjectURL: vi.fn() })
  mockGetHostSpeechSettings.mockResolvedValue({
    available: true,
    provider: 'fake',
    voiceType: 'voice-a',
    voices: [{ voiceType: 'voice-a', label: '测试音色' }],
    autoEmotion: true,
  })
  mockGetHostSpeechManifest.mockImplementation(async (_roomId: string, messageId: string) => ({
    messageId,
    sentences: [{
      index: 0,
      text: ({
        'action-206': '渐进片段一号。渐进片段二号。',
        'narration-1': '新的主持人叙事',
        'history-narration': '历史主持人叙事',
        'narration-controls-1': '控制面板测试',
      } as Record<string, string>)[messageId] ?? '测试分句',
    }],
  }))
  mockGetHostSpeechSentence.mockResolvedValue(new Blob(['mp3'], { type: 'audio/mpeg' }))
  return { audio }
}

class RoomSpeechRecognition {
  static instances: RoomSpeechRecognition[] = []
  lang = ''
  continuous = true
  interimResults = true
  onstart: (() => void) | null = null
  onresult: ((event: {
    resultIndex?: number
    results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }>
  }) => void) | null = null
  onend: (() => void) | null = null
  onerror: ((event: { error: string }) => void) | null = null
  start = vi.fn()
  stop = vi.fn()
  abort = vi.fn()

  constructor() {
    RoomSpeechRecognition.instances.push(this)
  }

  emitFinal(transcript: string) {
    this.onresult?.({
      resultIndex: 0,
      results: [Object.assign([{ transcript }], { isFinal: true })],
    })
  }
}

function installRoomSpeechRecognition() {
  RoomSpeechRecognition.instances = []
  Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
  Object.defineProperty(window, 'SpeechRecognition', {
    configurable: true,
    value: RoomSpeechRecognition,
  })
}

const {
  emitWsMessage,
  mockGetOpeningMessageId,
  mockGetPlayerView,
  mockJoinRoom,
  mockListConversation,
  mockGetHostSpeechSettings,
  mockGetHostSpeechManifest,
  mockGetHostSpeechSentence,
  mockUpdateHostSpeechSettings,
  mockOnWsMessage,
  mockRollCheck,
  mockSendChat,
  mockSubmitAction,
  mockSubmitPlannedAction,
  mockWaitForWsOpen,
  wsHandlers,
  dice3dSupported,
  dice3dBehavior,
  dice3dRolls,
} = vi.hoisted(() => {
  const handlers = new Set<(event: ServerToClientEvent) => void>()
  return {
    wsHandlers: handlers,
    dice3dSupported: { value: false },
    dice3dBehavior: { value: 'unsupported' as 'unsupported' | 'manual' },
    dice3dRolls: [] as Array<{ token: string; settle: (value: number) => void }>,
    emitWsMessage: (event: ServerToClientEvent) => {
      for (const handler of handlers) handler(event)
    },
    mockGetOpeningMessageId: vi.fn(),
    mockGetPlayerView: vi.fn(),
    mockJoinRoom: vi.fn(),
    mockListConversation: vi.fn(),
    mockGetHostSpeechSettings: vi.fn(),
    mockGetHostSpeechManifest: vi.fn(),
    mockGetHostSpeechSentence: vi.fn(),
    mockUpdateHostSpeechSettings: vi.fn(),
    mockRollCheck: vi.fn(),
    mockSendChat: vi.fn(),
    mockOnWsMessage: vi.fn((handler: (event: ServerToClientEvent) => void) => {
      handlers.add(handler)
      return () => handlers.delete(handler)
    }),
    mockSubmitAction: vi.fn(),
    mockSubmitPlannedAction: vi.fn(),
    mockWaitForWsOpen: vi.fn(() => Promise.resolve()),
  }
})

vi.mock('@/services/api-client', () => ({
  connectWebSocket: vi.fn(() => ({}) as WebSocket),
  disconnectWebSocket: vi.fn(),
  friendlyErrorMessage: vi.fn((_err: unknown, fallback: string) => fallback),
  getAuthToken: vi.fn(() => 'token-1'),
  onWsMessage: mockOnWsMessage,
  waitForWsOpen: mockWaitForWsOpen,
  sdk: {
    rooms: {
      listConversation: mockListConversation,
      getHostSpeechSettings: mockGetHostSpeechSettings,
      getHostSpeechManifest: mockGetHostSpeechManifest,
      getHostSpeechSentence: mockGetHostSpeechSentence,
      updateHostSpeechSettings: mockUpdateHostSpeechSettings,
    },
    roomSocket: {
      getOpeningMessageId: mockGetOpeningMessageId,
      getPlayerView: mockGetPlayerView,
      joinRoom: mockJoinRoom,
      rollCheck: mockRollCheck,
      sendChat: mockSendChat,
      submitAction: mockSubmitAction,
      submitPlannedAction: mockSubmitPlannedAction,
    },
  },
}))

vi.mock('@/services/room', () => ({
  endGame: vi.fn(),
}))

/**
 * 3D 骰子在 jsdom 里跑不了（没有 WebGL），默认按"不支持"处理，与真实 jsdom
 * 行为一致，不影响其余用例。
 *
 * `dice3dSupported` 置 true 时启用可控假舞台：默认模拟引擎加载失败；切到 manual
 * 后由测试决定每一轮何时定格，用来覆盖跨请求迟到回调。
 */
vi.mock('@/features/dice3d', async () => {
  const { forwardRef, useImperativeHandle } = await import('react')
  return {
    supports3DDice: () => dice3dSupported.value,
    Dice3DStage: forwardRef(
      (
        {
          onSettled,
          onUnsupported,
        }: {
          onSettled: (value: number, token: string) => void
          onUnsupported?: (token: string | null) => void
        },
        ref: React.Ref<{ roll: (token: string) => boolean }>,
      ) => {
        useImperativeHandle(
          ref,
          () => ({
            roll: (token: string) => {
              if (dice3dBehavior.value === 'unsupported') {
                onUnsupported?.(token)
                return true
              }
              dice3dRolls.push({ token, settle: (value) => onSettled(value, token) })
              return true
            },
          }),
          [onSettled, onUnsupported],
        )
        return <div data-testid="dice-3d-stage" />
      },
    ),
  }
})

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

vi.mock('@/hooks/usePlayerPortraits', () => ({
  usePlayerPortraits: () => ({ 'player-1': 'blob:player-1-portrait' }),
}))

vi.mock('@/hooks/useRuleset', () => ({
  useRuleset: () => ({
    ruleset: {
      attributes: [],
      skills: [
        { id: 'accounting', name: '会计', nameEn: 'accounting', base: 5, category: 'occupation' },
        { id: 'charm', name: '取悦', nameEn: 'charm', base: 15, category: 'social' },
        { id: 'stealth', name: '潜行', nameEn: 'stealth', base: 20, category: 'interest' },
      ],
      occupations: [{
        id: 1,
        name: '记者',
        creditMin: 0,
        creditMax: 70,
        skillPointsFormula: 'EDU*4',
        skillIds: ['accounting'],
        choiceSlots: [{ count: 1, candidateSkillIds: null, label: '任意一项技能' }],
        description: '',
      }],
    },
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

function playerViewFixture(): AgentPlayerView {
  return {
    room_id: 'room-1',
    player_id: 'player-1',
    actor_id: 'actor-1',
    scene_id: 'scene-1',
    phase: 'playing',
    revision: 'revision-1',
    self_actor: {
      id: 'actor-1',
      name: '杜调查员',
      occupation: '记者',
      attributes: [],
      skills: [],
      resources: [],
      conditions: [],
      equipment: [],
      background_summary: '仅本人可见',
      public_status_summary: '神色警觉',
    },
    scene: {
      id: 'scene-1',
      name: '旧宅门厅',
      description: '仅用于确认视图不会生成开场的场景描述',
      time: '深夜',
      visible_entities: [],
      visible_actors: [],
      available_exits: [],
    },
    world: {
      elapsed_minutes: 0,
      time_of_day: 'night',
      core_resolved: false,
      ending_available: false,
      ending_id: null,
    },
    known_information: [],
    checkpoint_options: [],
  }
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
    dice3dSupported.value = false
    dice3dBehavior.value = 'unsupported'
    dice3dRolls.length = 0
    Object.defineProperty(window, 'speechSynthesis', { configurable: true, value: undefined })
    Object.defineProperty(window, 'SpeechSynthesisUtterance', { configurable: true, value: undefined })
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: true })
    Reflect.deleteProperty(window, 'SpeechRecognition')
    Reflect.deleteProperty(window, 'webkitSpeechRecognition')
    RoomSpeechRecognition.instances = []
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
    mockGetOpeningMessageId.mockReturnValue(null)
    mockListConversation.mockResolvedValue([])
    mockGetHostSpeechSettings.mockResolvedValue({
      available: false,
      provider: 'disabled',
      voiceType: null,
      voices: [],
      autoEmotion: true,
    })
    mockSubmitAction.mockReturnValue(new Promise(() => undefined))
    mockSubmitPlannedAction.mockReturnValue(new Promise(() => undefined))
  })

  afterEach(() => {
    cleanup()
    Reflect.deleteProperty(window, 'SpeechRecognition')
    Reflect.deleteProperty(window, 'webkitSpeechRecognition')
    Reflect.deleteProperty(window, 'isSecureContext')
  })

  it('restores action history by default and discussion history after switching channel', async () => {
    mockListConversation.mockResolvedValue(conversationHistory())

    renderRoomPage()

    expect(await screen.findByText('我查看书架')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '杜调查员的头像' })).toHaveAttribute(
      'src',
      'blob:player-1-portrait',
    )
    expect(screen.getByText('你发现书架后有一个暗格。')).toBeInTheDocument()
    expect(screen.getByText('图书馆使用 50% · D100 23 · 成功')).toBeInTheDocument()
    expect(screen.getByText('杜调查员 · 掷骰')).toBeInTheDocument()
    expect(mockListConversation).toHaveBeenCalledWith('room-1', 'reconnect-1')

    fireEvent.click(screen.getByRole('button', { name: '讨论区' }))

    expect(await screen.findByText('先在讨论区确认路线')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: '陈探员的头像' })).toHaveAttribute(
      'src',
      'blob:player-1-portrait',
    )
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

  it('does not create an opening from view.updated alone', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    emitWsMessage({
      type: 'view.updated',
      payload: {
        playerId: 'player-1',
        playerView: playerViewFixture(),
      },
    })

    await waitFor(() => {
      expect(
        screen.queryByText('仅用于确认视图不会生成开场的场景描述'),
      ).not.toBeInTheDocument()
    })
  })

  it('deduplicates game-opening when history arrives before realtime', async () => {
    mockListConversation.mockResolvedValue([
      {
        id: 'game-opening',
        type: 'narration.push',
        channel: 'action',
        payload: {
          messageId: 'game-opening',
          text: '唯一的权威开场',
        },
        createdAt: '2026-07-28T10:03:00Z',
      },
    ])
    renderRoomPage()
    expect(await screen.findByText('唯一的权威开场')).toBeInTheDocument()

    emitWsMessage({
      type: 'narration.push',
      payload: {
        messageId: 'game-opening',
        text: '唯一的权威开场',
      },
    })

    await waitFor(() => {
      expect(screen.getAllByText('唯一的权威开场')).toHaveLength(1)
    })
  })

  it('deduplicates game-opening when realtime arrives before history', async () => {
    let resolveHistory!: (events: RoomConversationEvent[]) => void
    mockListConversation.mockReturnValue(
      new Promise<RoomConversationEvent[]>((resolve) => {
        resolveHistory = resolve
      }),
    )
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    emitWsMessage({
      type: 'narration.push',
      payload: {
        messageId: 'game-opening',
        text: '实时先到的权威开场',
      },
    })
    expect(await screen.findByText('实时先到的权威开场')).toBeInTheDocument()

    await act(async () => {
      resolveHistory([
        {
          id: 'game-opening',
          type: 'narration.push',
          channel: 'action',
          payload: {
            messageId: 'game-opening',
            text: '实时先到的权威开场',
          },
          createdAt: '2026-07-28T10:03:00Z',
        },
      ])
    })

    await waitFor(() => {
      expect(screen.getAllByText('实时先到的权威开场')).toHaveLength(1)
    })
  })

  it('shows opening progress and clears it when the opening arrives', async () => {
    mockGetOpeningMessageId.mockReturnValue('game-opening')
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    expect(
      await screen.findByText('守秘人正在生成开场叙事'),
    ).toBeInTheDocument()

    emitWsMessage({
      type: 'narration.push',
      payload: {
        messageId: 'game-opening',
        text: '生成完成的开场',
      },
    })
    await waitFor(() => {
      expect(
        screen.queryByText('守秘人正在生成开场叙事'),
      ).not.toBeInTheDocument()
    })
  })

  it('preserves real newlines in historical and realtime narration', async () => {
    mockListConversation.mockResolvedValue([
      {
        id: 'narration-history-1',
        type: 'narration.push',
        channel: 'action',
        payload: { text: '历史第一段\n历史第二段' },
        createdAt: '2026-07-28T10:03:00Z',
      },
    ])

    renderRoomPage()

    const historical = await screen.findByText(
      (_content, element) =>
        element?.classList.contains('whitespace-pre-wrap') === true &&
        element.textContent === '历史第一段\n历史第二段',
    )
    expect(historical).toHaveClass('whitespace-pre-wrap')

    emitWsMessage({
      type: 'narration.push',
      payload: { text: '实时第一段\n实时第二段' },
    })

    const realtime = await screen.findByText(
      (_content, element) =>
        element?.classList.contains('whitespace-pre-wrap') === true &&
        element.textContent === '实时第一段\n实时第二段',
    )
    expect(realtime).toHaveClass('whitespace-pre-wrap')
  })

  it('reveals narration chunks gradually instead of dumping the whole text', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    const full = '雨点敲打着窗框。屋里只剩壁炉燃烧的细响。'
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-203', sequence: 0, text: '雨点敲打着窗框。' },
    })
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-203', sequence: 1, text: '屋里只剩壁炉燃烧的细响。' },
    })

    // 这是本用例的核心：片段同时到达，但不能立刻整段显示。
    await waitFor(
      () => {
        const shown =
          screen
            .getByText('生成中…')
            .parentElement?.querySelector('.whitespace-pre-wrap')?.textContent ?? ''
        expect(shown.length).toBeGreaterThan(0)
        expect(full.startsWith(shown)).toBe(true)
        expect(shown).not.toBe(full)
      },
      { timeout: 2000 },
    )
  })

  it('holds the authoritative push until the reveal finishes, then hands over once', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    const full = '雨点敲打着窗框。屋里只剩壁炉燃烧的细响。'
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-203', sequence: 0, text: '雨点敲打着窗框。' },
    })
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-203', sequence: 1, text: '屋里只剩壁炉燃烧的细响。' },
    })
    // 权威消息紧跟着片段到达（真实间隔约 0.5ms），但不能当场接管。
    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'action-203', text: full },
    })

    // 两段式等待：先确认揭示真的开始了，再等它交接完成。只断言"全文出现一次"
    // 是不够的——揭示到全文、权威消息还没接管的那一帧同样满足，命中的是临时
    // 气泡而不是权威消息。
    await screen.findByText('生成中…')
    await waitFor(
      () => expect(screen.queryByText('生成中…')).not.toBeInTheDocument(),
      { timeout: 4000 },
    )
    // 交接完成后全文在，且只有一份——临时气泡没有和权威消息并存。
    expect(screen.getAllByText(full)).toHaveLength(1)
  })

  // 回归：待提交槽位原本是单个，揭示 A 的过程中到达的 B 会把 A 顶掉，A 既不
  // 进消息列表也不朗读，只能靠刷新走历史恢复（PR #213 review 指出）。
  it('keeps an earlier narration when another push lands mid-reveal', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    const first = '第一条叙事的前半句。第一条叙事的后半句。'
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-A', sequence: 0, text: '第一条叙事的前半句。' },
    })
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-A', sequence: 1, text: '第一条叙事的后半句。' },
    })
    emitWsMessage({ type: 'narration.push', payload: { messageId: 'action-A', text: first } })
    // A 还在揭示时，另一条没有片段的叙事直接到达。
    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'action-B', text: '第二条叙事直接落地。' },
    })

    // 两条都要落地，且顺序不能颠倒——队列按到达顺序提交。
    await waitFor(
      () => {
        expect(screen.getByText(first)).toBeInTheDocument()
        expect(screen.getByText('第二条叙事直接落地。')).toBeInTheDocument()
      },
      { timeout: 4000 },
    )
    const rendered = screen.getAllByText(/第[一二]条叙事/).map((node) => node.textContent)
    expect(rendered).toEqual([first, '第二条叙事直接落地。'])
  })

  it('deduplicates repeated chunks and tolerates out-of-order arrival', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    const full = '第一段落在这里。第二段落在这里。'
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-204', sequence: 1, text: '第二段落在这里。' },
    })
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-204', sequence: 0, text: '第一段落在这里。' },
    })
    // 重连重放同一个片段不得让文字出现两次。
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-204', sequence: 1, text: '第二段落在这里。' },
    })
    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'action-204', text: full },
    })

    await screen.findByText('生成中…')
    await waitFor(
      () => expect(screen.queryByText('生成中…')).not.toBeInTheDocument(),
      { timeout: 4000 },
    )
    expect(screen.getAllByText(full)).toHaveLength(1)
  })

  it('drops streamed chunks when the turn fails', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-205', sequence: 0, text: '半截叙事片段。' },
    })
    expect(await screen.findByText('生成中…')).toBeInTheDocument()

    emitWsMessage({
      type: 'turn.failed',
      payload: {
        correlationId: 'action-205',
        code: 'HOST_AGENT_TIMEOUT',
        publicMessage: '守秘人没能完成这次回合，请重试。',
        retryable: true,
      },
    })
    await waitFor(() => expect(screen.queryByText('生成中…')).not.toBeInTheDocument())
    expect(screen.queryByText('半截叙事片段。')).not.toBeInTheDocument()
  })

  it('speaks the narration only once the authoritative push has landed', async () => {
    installRoomSpeechApi()
    localStorage.setItem(
      'aidm-host-speech-settings',
      JSON.stringify({ enabled: true, voiceURI: null }),
    )
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    const full = '渐进片段一号。渐进片段二号。'
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-206', sequence: 0, text: '渐进片段一号。' },
    })
    emitWsMessage({
      type: 'narration.chunk',
      payload: { messageId: 'action-206', sequence: 1, text: '渐进片段二号。' },
    })
    expect(await screen.findByText('生成中…')).toBeInTheDocument()
    // 揭示途中不能出声：片段不是权威消息。
    expect(mockGetHostSpeechManifest).not.toHaveBeenCalled()

    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'action-206', text: full },
    })
    await waitFor(() => expect(mockGetHostSpeechManifest).toHaveBeenCalledTimes(1), { timeout: 4000 })
    expect(mockGetHostSpeechManifest.mock.calls[0]?.[1]).toBe('action-206')
  })

  it('commits immediately when a narration arrives without any chunks', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'action-207', text: '单片段叙事直接落地。' },
    })

    expect(await screen.findByText('单片段叙事直接落地。')).toBeInTheDocument()
    expect(screen.queryByText('生成中…')).not.toBeInTheDocument()
  })

  it('automatically speaks new final narration once by message id', async () => {
    installRoomSpeechApi()
    localStorage.setItem('aidm-host-speech-settings', JSON.stringify({ enabled: true, voiceURI: null }))
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'narration-1', text: '新的主持人叙事' },
    })
    expect(await screen.findByText('新的主持人叙事')).toBeInTheDocument()
    await waitFor(() => expect(mockGetHostSpeechManifest).toHaveBeenCalledTimes(1))
    expect(mockGetHostSpeechManifest.mock.calls[0]?.[1]).toBe('narration-1')

    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'narration-1', text: '新的主持人叙事' },
    })
    await waitFor(() => expect(mockGetHostSpeechManifest).toHaveBeenCalledTimes(1))
  })

  it('does not auto-speak restored history but supports manual replay', async () => {
    installRoomSpeechApi()
    localStorage.setItem('aidm-host-speech-settings', JSON.stringify({ enabled: true, voiceURI: null }))
    mockListConversation.mockResolvedValue([
      {
        id: 'history-narration',
        type: 'narration.push',
        channel: 'action',
        payload: { messageId: 'history-narration', text: '历史主持人叙事' },
        createdAt: '2026-07-28T10:03:00Z',
      },
    ])

    renderRoomPage()
    expect(await screen.findByText('历史主持人叙事')).toBeInTheDocument()
    expect(mockGetHostSpeechManifest).not.toHaveBeenCalled()

    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'history-narration', text: '历史主持人叙事' },
    })
    await waitFor(() => {
      expect(screen.getAllByText('历史主持人叙事')).toHaveLength(1)
      expect(mockGetHostSpeechManifest).not.toHaveBeenCalled()
    })

    fireEvent.click(screen.getByRole('button', { name: '重新朗读' }))
    await waitFor(() => expect(mockGetHostSpeechManifest).toHaveBeenCalledTimes(1))
    expect(mockGetHostSpeechManifest.mock.calls[0]?.[1]).toBe('history-narration')
  })

  it('exposes speech controls and stops the queue when disabled', async () => {
    const { audio } = installRoomSpeechApi()
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    fireEvent.click(screen.getByRole('button', { name: '主持人语音' }))
    const toggle = screen.getByRole('switch', { name: '主持人语音朗读' })
    fireEvent.click(toggle)
    expect(toggle).toBeChecked()

    emitWsMessage({
      type: 'narration.push',
      payload: { messageId: 'narration-controls-1', text: '控制面板测试' },
    })
    expect(await screen.findByText('控制面板测试')).toBeInTheDocument()
    await waitFor(() => expect(audio.play).toHaveBeenCalledTimes(1))

    fireEvent.click(screen.getByRole('button', { name: '暂停朗读' }))
    expect(audio.pause).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: '继续朗读' }))
    expect(audio.play).toHaveBeenCalledTimes(2)
    fireEvent.click(toggle)
    expect(toggle).not.toBeChecked()
    expect(audio.pause).toHaveBeenCalledTimes(2)
  })

  it('keeps text readable and disables replay when speech is unsupported', async () => {
    mockListConversation.mockResolvedValue([
      {
        id: 'unsupported-narration',
        type: 'narration.push',
        channel: 'action',
        payload: { messageId: 'unsupported-narration', text: '纯文本主持人叙事' },
        createdAt: '2026-07-28T10:03:00Z',
      },
    ])
    renderRoomPage()
    expect(await screen.findByText('纯文本主持人叙事')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重新朗读' })).toBeDisabled()
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

  it('preserves categorized background line breaks in the character sheet', async () => {
    const background = '形象描述：穿着旧风衣\n重要之人：导师亨利'
    useCharacterStore.getState().setCharacter(
      {
        info: {
          name: '杜调查员',
          playerName: '陈探员',
          age: '32',
          gender: '男',
          residence: '阿卡姆',
          birthplace: '波士顿',
          occupationId: 1,
        },
        attr: {},
        skillAlloc: {},
        skillFinalValues: { accounting: 40, charm: 50, stealth: 30 },
        occupationChoiceSkillIds: ['charm'],
        equipment: '',
        background,
        notes: '',
        derived: { hp: 10, san: 60, mp: 10, db: '0', build: '0', move: 8 },
      },
      'room-1',
    )
    mockListConversation.mockResolvedValue([])

    renderRoomPage()
    fireEvent.click(screen.getByRole('button', { name: '角色卡' }))
    for (const label of ['生命值', '理智值', '魔法值', '伤害加值', '体格', '移动力']) {
      expect(screen.getByText(new RegExp(label))).toBeInTheDocument()
    }
    fireEvent.click(screen.getByRole('button', { name: '背景装备' }))

    const renderedBackground = screen.getByText((_, element) => element?.textContent === background)
    expect(renderedBackground).toHaveClass('whitespace-pre-wrap')
  })

  // jsdom 没有 WebGL，supports3DDice() 为 false —— 正好覆盖降级路径：
  // 渲染能力缺失时不能把检定卡住（issue #217）。
  it('falls back to the 2D dice display when WebGL is unavailable', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-fallback',
          summary: '检查旧报纸',
          difficulty: 'regular',
          skills: [{ id: 'library', name: '图书馆使用', targetValue: 60 }],
        },
      })
    })

    expect(await screen.findByText('图书馆使用')).toBeInTheDocument()
    expect(screen.queryByTestId('dice-3d-stage')).not.toBeInTheDocument()
    expect(screen.getByText('十位')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '掷骰' })).toBeInTheDocument()
  })

  // 回归：3D 引擎在玩家点了「掷骰」之后才加载失败时，只翻 use3D 会让 rolling
  // 永远不清 —— 检定卡在「骰子还在滚」，既没有结果也没有重掷入口，恰好是这套
  // 降级本该防住的情况（PR #219 review 指出）。
  it('completes the roll when the 3D engine fails to load after the tap', async () => {
    dice3dSupported.value = true
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-3d-fail',
          summary: '检查旧报纸',
          difficulty: 'regular',
          skills: [{ id: 'library', name: '图书馆使用', targetValue: 60 }],
        },
      })
    })
    expect(await screen.findByText('图书馆使用')).toBeInTheDocument()
    expect(screen.getByTestId('dice-3d-stage')).toBeInTheDocument()

    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValueOnce(0.2).mockReturnValueOnce(0.3)

    // 点击掷骰 → 假舞台立刻触发 onUnsupported，模拟 chunk 加载失败。
    fireEvent.click(screen.getByRole('button', { name: '掷骰' }))
    await act(async () => {
      vi.advanceTimersByTime(800)
    })
    vi.useRealTimers()

    // 这一次掷骰必须被补完：结果出来、能确认发送，而不是永远停在"骰子还在滚"。
    expect(screen.getByText('23')).toBeInTheDocument()
    expect(screen.queryByText('🎲 骰子还在滚……')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '确认并发送' })).toBeInTheDocument()
    // 已经退回 2D 展示。
    expect(screen.queryByTestId('dice-3d-stage')).not.toBeInTheDocument()
  })

  it('ignores a stale 3D result and lets the replacement check roll normally', async () => {
    dice3dSupported.value = true
    dice3dBehavior.value = 'manual'
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-a',
          summary: '调查书架',
          difficulty: 'regular',
          skills: [{ id: 'skill-library', name: '图书馆使用', targetValue: 50 }],
        },
      })
    })

    fireEvent.click(await screen.findByRole('button', { name: '掷骰' }))
    expect(dice3dRolls).toHaveLength(1)

    await act(async () => {
      emitWsMessage({
        type: 'check.request',
        payload: {
          playerId: 'player-1',
          clientActionId: 'check-b',
          summary: '检查门锁',
          difficulty: 'regular',
          skills: [{ id: 'skill-locksmith', name: '锁匠', targetValue: 40 }],
        },
      })
    })

    expect(screen.getByText('锁匠')).toBeInTheDocument()
    act(() => dice3dRolls[0].settle(23))

    expect(screen.queryByText('23')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '确认并发送' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '掷骰' }))
    expect(dice3dRolls).toHaveLength(2)

    act(() => dice3dRolls[1].settle(41))
    expect(screen.getByText('41')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '确认并发送' }))

    expect(mockRollCheck).toHaveBeenCalledTimes(1)
    expect(mockRollCheck).toHaveBeenCalledWith('player-1', {
      clientActionId: 'check-b',
      skill: 'skill-locksmith',
      rollValue: 41,
    })
  })

  it('shows explicit occupation choice skills in the occupation tab', () => {
    useCharacterStore.getState().setCharacter(
      {
        info: {
          name: '杜调查员', playerName: '陈探员', age: '32', gender: '男',
          residence: '阿卡姆', birthplace: '波士顿', occupationId: 1,
        },
        attr: {},
        skillAlloc: {},
        skillFinalValues: { accounting: 40, charm: 50, stealth: 30 },
        occupationChoiceSkillIds: ['charm'],
        equipment: '',
        background: '',
        notes: '',
        derived: { hp: 10, san: 60, mp: 10, db: '0', build: '0', move: 8 },
      },
      'room-1',
    )
    mockListConversation.mockResolvedValue([])

    renderRoomPage()
    fireEvent.click(screen.getByRole('button', { name: '技能' }))
    expect(screen.getByText('会计')).toBeInTheDocument()
    expect(screen.getByText('取悦')).toBeInTheDocument()
    expect(screen.queryByText('潜行')).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '兴趣技能' }))
    expect(screen.getByText('潜行')).toBeInTheDocument()
    expect(screen.queryByText('取悦')).not.toBeInTheDocument()
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

    fireEvent.click(screen.getByRole('button', { name: '掷骰' }))

    await act(async () => {
      vi.advanceTimersByTime(800)
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

    fireEvent.click(screen.getByRole('button', { name: '掷骰' }))

    await act(async () => {
      vi.advanceTimersByTime(800)
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
    fireEvent.click(screen.getByRole('button', { name: '掷骰' }))

    await act(async () => {
      vi.advanceTimersByTime(800)
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
    await waitFor(() => expect(mockSubmitPlannedAction).toHaveBeenCalledTimes(1))
    expect(mockSubmitAction).not.toHaveBeenCalled()

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

  it('shows a disabled microphone with a clear message when speech input is unavailable', () => {
    renderRoomPage()

    expect(screen.getByRole('button', { name: '语音输入不可用' })).toBeDisabled()
    expect(screen.getByText('当前浏览器不支持语音输入，请继续使用键盘输入')).toBeInTheDocument()
  })

  it('appends speech without auto-submitting and keeps it available in both channels', () => {
    installRoomSpeechRecognition()
    renderRoomPage()

    const input = screen.getByPlaceholderText('输入行动…')
    fireEvent.change(input, { target: { value: '我先观察' } })
    fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }))
    const actionRecognition = RoomSpeechRecognition.instances[0]
    act(() => actionRecognition.onstart?.())
    expect(screen.getByRole('button', { name: '停止语音输入并采用文字' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '取消语音输入' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '发送消息' })).not.toBeInTheDocument()
    act(() => {
      actionRecognition.emitFinal('检查门锁')
      actionRecognition.onend?.()
    })

    expect(input).toHaveValue('我先观察 检查门锁')
    expect(mockSubmitAction).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '发送消息' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '讨论区' }))
    expect(screen.getByRole('button', { name: '开始语音输入' })).toBeEnabled()
    fireEvent.change(input, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }))
    const discussionRecognition = RoomSpeechRecognition.instances[1]
    act(() => {
      discussionRecognition.onstart?.()
      discussionRecognition.emitFinal('我们先商量路线')
      discussionRecognition.onend?.()
    })
    expect(input).toHaveValue('我们先商量路线')
    expect(mockSendChat).not.toHaveBeenCalled()
    fireEvent.submit(input.closest('form')!)
    expect(mockSendChat).toHaveBeenCalledWith('player-1', expect.objectContaining({
      text: '我们先商量路线',
    }))
  })

  it('cancels active speech on channel changes and ignores late browser results', () => {
    installRoomSpeechRecognition()
    renderRoomPage()

    fireEvent.click(screen.getByRole('button', { name: '开始语音输入' }))
    const recognition = RoomSpeechRecognition.instances[0]
    const lateResult = recognition.onresult!
    act(() => recognition.onstart?.())
    fireEvent.click(screen.getByRole('button', { name: '讨论区' }))
    expect(recognition.abort).toHaveBeenCalledOnce()

    act(() => lateResult({
      resultIndex: 0,
      results: [Object.assign([{ transcript: '不应进入讨论区' }], { isFinal: true })],
    }))
    expect(screen.getByPlaceholderText('输入行动…')).toHaveValue('')
  })

  it('reports an insecure HTTP page instead of attempting recognition', () => {
    installRoomSpeechRecognition()
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false })
    renderRoomPage()

    expect(screen.getByRole('button', { name: '语音输入不可用' })).toBeDisabled()
    expect(screen.getByText('当前页面不是安全连接，请使用 HTTPS 或 localhost 访问')).toBeInTheDocument()
    expect(RoomSpeechRecognition.instances).toHaveLength(0)
  })

  it('hides a settled single-action check panel once the turn produces narration', async () => {
    // A standalone single action emits no plan.* events, so the panel used to
    // survive the turn. Its buttons stayed clickable and a second click resent
    // the same stale sourceRevision, which the server can only reject.
    mockSubmitPlannedAction.mockImplementation(
      () =>
        new Promise(() => {
          /* the authoritative narration is what settles this turn */
        }),
    )
    renderRoomPage()

    const input = screen.getByPlaceholderText('输入行动…')
    fireEvent.change(input, { target: { value: '我要撬开抽屉' } })
    fireEvent.submit(input.closest('form')!)
    await waitFor(() => expect(mockSubmitPlannedAction).toHaveBeenCalled())
    const { clientActionId } = mockSubmitPlannedAction.mock.calls[0][1]

    act(() =>
      emitWsMessage({
        type: 'adjudication.pending',
        payload: {
          correlationId: clientActionId,
          planId: null,
          sourceRevision: 'revision-1',
          status: 'awaiting_post_roll_decision',
          pendingDecision: null,
          checkRun: {
            check_id: 'check-1',
            action_request_id: clientActionId,
            selected_candidate_id: 'library',
            status: 'awaiting_post_roll_decision',
            version: 1,
            roll_count: 1,
            roll: { value: 80, degree: 'failure', passed: false },
            post_roll_options: [{ option_id: 'accept-current', kind: 'accept_result' }],
            final_result: null,
          },
        },
      }),
    )
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()

    act(() =>
      emitWsMessage({
        type: 'narration.push',
        payload: { messageId: clientActionId, text: '抽屉纹丝不动，木头发出干涩的响声。' },
      }),
    )

    await waitFor(() =>
      expect(screen.queryByRole('region', { name: '待处理检定' })).not.toBeInTheDocument(),
    )
  })

  it('keeps another action\'s pending check while an unrelated turn settles', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    act(() =>
      emitWsMessage({
        type: 'adjudication.pending',
        payload: {
          correlationId: 'still-waiting',
          planId: null,
          sourceRevision: 'revision-1',
          status: 'awaiting_skill_choice',
          pendingDecision: {
            decision_id: 'decision-9',
            action_request_id: 'still-waiting',
            source_revision: 'revision-1',
            decision_version: 1,
            actor_id: 'actor-1',
            summary: '仍在等待玩家选择',
            options: [
              {
                candidate_id: 'library',
                skill_id: 'library-use',
                display_name: '图书馆使用',
                target_value: 50,
                difficulty: 'regular' as const,
                method_summary: '检查书架上的旧书',
                player_safe_reason: '这是当前场景中可见的调查方式',
              },
            ],
            allow_cancel: true,
          },
        },
      }),
    )
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()

    act(() =>
      emitWsMessage({
        type: 'narration.push',
        payload: { messageId: 'a-different-action', text: '别的动作结算完了。' },
      }),
    )

    expect(screen.getByRole('region', { name: '待处理检定' })).toBeInTheDocument()
  })

  it('submits the room input through ActionPlan and clears stale decisions', async () => {
    renderRoomPage()

    const input = screen.getByPlaceholderText('输入行动…')
    fireEvent.change(input, { target: { value: '去书房找线索' } })
    fireEvent.submit(input.closest('form')!)
    await waitFor(() =>
      expect(mockSubmitPlannedAction).toHaveBeenCalledWith(
        'player-1',
        expect.objectContaining({ utterance: '去书房找线索' }),
      ),
    )
    expect(mockSubmitAction).not.toHaveBeenCalled()

    const pending: Extract<ServerToClientEvent, { type: 'adjudication.pending' }> = {
      type: 'adjudication.pending',
      payload: {
        correlationId: 'plan-input-1',
        planId: 'plan-input-1',
        sourceRevision: 'revision-1',
        status: 'awaiting_skill_choice',
        pendingDecision: {
          decision_id: 'decision-1',
          action_request_id: 'step-request-1',
          source_revision: 'revision-1',
          decision_version: 1,
          actor_id: 'actor-1',
          summary: '调查书房',
          options: [
            {
              candidate_id: 'library',
              skill_id: 'library-use',
              display_name: '图书馆使用',
              target_value: 50,
              difficulty: 'regular' as const,
              method_summary: '检查书架上的旧书',
              player_safe_reason: '这是当前场景中可见的调查方式',
            },
          ],
          allow_cancel: true,
        },
      },
    }
    act(() => emitWsMessage(pending))
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()

    act(() => emitWsMessage({
      type: 'plan.step_changed',
      payload: {
        correlationId: 'plan-input-1',
        currentStep: 2,
        completedSteps: 1,
        totalSteps: 2,
        phase: 'executing',
      },
    }))
    expect(screen.queryByRole('region', { name: '待处理检定' })).not.toBeInTheDocument()

    act(() => emitWsMessage(pending))
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()
    act(() => emitWsMessage({
      type: 'plan.stopped',
      payload: {
        correlationId: 'plan-input-1',
        currentStep: 2,
        completedSteps: 1,
        totalSteps: 2,
        phase: 'stopped',
      },
    }))
    expect(screen.queryByRole('region', { name: '待处理检定' })).not.toBeInTheDocument()

    act(() => emitWsMessage(pending))
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()
    act(() => emitWsMessage({
      type: 'plan.completed',
      payload: {
        correlationId: 'plan-input-1',
        currentStep: 2,
        completedSteps: 2,
        totalSteps: 2,
        phase: 'completed',
      },
    }))
    expect(screen.queryByRole('region', { name: '待处理检定' })).not.toBeInTheDocument()

    act(() => emitWsMessage(pending))
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()
    act(() => emitWsMessage({
      type: 'error',
      payload: {
        code: 'ACTION_IN_PROGRESS',
        message: '当前行动仍在处理中',
      },
    }))
    expect(screen.queryByRole('region', { name: '待处理检定' })).not.toBeInTheDocument()

    act(() => emitWsMessage(pending))
    expect(await screen.findByRole('region', { name: '待处理检定' })).toBeInTheDocument()
    act(() => emitWsMessage({
      type: 'turn.failed',
      payload: {
        correlationId: 'plan-input-1',
        code: 'HOST_AGENT_TIMEOUT',
        publicMessage: '主持 Agent 响应超时，请重试。',
        retryable: true,
      },
    }))
    expect(screen.queryByRole('region', { name: '待处理检定' })).not.toBeInTheDocument()
  })

  it('shows the authoritative world clock and ending state from the PlayerView', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    act(() =>
      emitWsMessage({
        type: 'view.updated',
        payload: {
          playerId: 'player-1',
          playerView: {
            ...playerViewFixture(),
            world: {
              elapsed_minutes: 13 * 60 + 25,
              time_of_day: 'night',
              core_resolved: true,
              ending_available: true,
              ending_id: null,
            },
          },
        },
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: '地图' }))

    expect(screen.getByText('夜晚 · 已过去 13 小时 25 分钟')).toBeInTheDocument()
    expect(
      screen.getByText('主线已经收束，可以选择如何收尾'),
    ).toBeInTheDocument()
  })

  it('hides the mainline banner until an ending effect is committed', async () => {
    renderRoomPage()
    await waitFor(() => expect(mockOnWsMessage).toHaveBeenCalled())

    act(() =>
      emitWsMessage({
        type: 'view.updated',
        payload: { playerId: 'player-1', playerView: playerViewFixture() },
      }),
    )
    fireEvent.click(screen.getByRole('button', { name: '地图' }))

    expect(screen.getByText('夜晚 · 刚刚开始')).toBeInTheDocument()
    expect(screen.queryByLabelText('主线进度')).not.toBeInTheDocument()
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

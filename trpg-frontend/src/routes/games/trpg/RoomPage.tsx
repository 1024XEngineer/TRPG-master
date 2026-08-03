import { useNavigate } from 'react-router-dom'
import { RoomSocketServerError, TurnFailedError, type AgentPlayerView, type AgentTurnPhase, type CheckRequestPayload, type NarrationPushPayload, type RoomConversationEvent } from 'trpg-sdk'
import { ArrowLeft, Users, Map, BookOpen, ScrollText, Star, X, SendHorizontal, Dice6, Plus, Save, FlagOff, Heart, Volume2, Pause, Play, Square, RotateCcw } from 'lucide-react'
import { useCallback, useState, useRef, useEffect, type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { useCharacterStore } from '@/stores/character-store'
import { connectWebSocket, waitForWsOpen, sdk, onWsMessage, disconnectWebSocket, friendlyErrorMessage } from '@/services/api-client'
import { endGame } from '@/services/room'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'
import { useRuleset } from '@/hooks/useRuleset'
import { useHostSpeech } from '@/hooks/useHostSpeech'

// `crypto.randomUUID()` 要求安全上下文（HTTPS 或 localhost）——CI Preview
// 部署在纯 HTTP 的 IP:端口上（issue #200，域名/HTTPS 明确列在本期不做），
// `isSecureContext` 为 false 时 `crypto.randomUUID` 整个是 `undefined`，
// 调用直接抛 TypeError。这行抛出发生在 sendMessage 的参数求值阶段——
// 比 submitPlayerAction 函数体还早，异常不会被任何 .catch() 接住，界面上
// 不会有任何提示，行为是"点发送后什么都没发生"。`crypto.getRandomValues`
// 不受这条限制（只有 `subtle`/`randomUUID` 这类更高层的 API 被安全上下文
// 网关挡住），用它手搓一个符合 RFC4122 v4 格式的 UUID 作为兜底。
function randomActionId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// ─── Types ───────────────────────────────────────────
interface Message {
  type: 'system' | 'narr' | 'player' | 'dice'
  channel?: 'action' | 'discussion'
  messageId?: string
  sender?: string
  content: string
  time: string
  isSelf?: boolean
}

interface MapLocation {
  id: string
  icon: string
  name: string
  desc: string
  isCurrent?: boolean
}

function mapLocationsFromPlayerView(playerView: AgentPlayerView | null): MapLocation[] {
  if (!playerView) {
    return [{
      id: 'waiting-for-view',
      icon: '📍',
      name: '等待场景同步',
      desc: '进入游戏后由规则引擎提供当前位置',
      isCurrent: true,
    }]
  }
  const current: MapLocation = {
    id: playerView.scene.id,
    icon: '📍',
    name: playerView.scene.name,
    desc: playerView.scene.description || '当前所在场景',
    isCurrent: true,
  }
  const seen = new Set([current.id])
  const exits = playerView.scene.available_exits.flatMap((exit): MapLocation[] => {
    const id = exit.destination?.scene_id ?? `exit:${exit.id}`
    if (seen.has(id)) return []
    seen.add(id)
    return [{
      id,
      icon: exit.destination ? '🧭' : '🚪',
      name: exit.destination?.name ?? exit.name,
      desc: exit.description || `可经「${exit.name}」到达`,
    }]
  })
  return [current, ...exits]
}

const PHASE_LABELS: Record<AgentTurnPhase, string> = {
  reading_player_view: '守秘人正在查看当前场景',
  understanding_action: '守秘人正在理解你的行动',
  waiting_for_check: '等待你选择技能并掷骰',
  executing_action: '规则引擎正在结算行动',
  refreshing_player_view: '正在更新场景与已知信息',
  generating_narration: '守秘人正在组织叙事',
}

function resourceValue(playerView: AgentPlayerView | null, id: string): number | null {
  const normalized = id.toLocaleLowerCase()
  const resource = playerView?.self_actor.resources.find((item) =>
    item.id.toLocaleLowerCase() === normalized ||
    item.name.toLocaleLowerCase() === normalized
  )
  return resource?.value ?? null
}

function formatRoomTime(value: string | Date): string {
  return new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function conversationMessageId(type: RoomConversationEvent['type'], id: string): string {
  return `history:${type}:${id}`
}

/**
 * 一条主持叙事正在渐进到达时的临时拼装状态（issue #203）。
 *
 * 它**不是**权威历史：片段不落库，最终以服务端持久化的 `narration.push` 为准。
 * 收到同一 `messageId` 的 push 后这份状态立即丢弃，由权威消息接管；刷新或重新
 * 进房只会拿到 push，不会重放片段。
 */
interface StreamingNarration {
  messageId: string
  chunks: Record<number, string>
  /** 已揭示的字符数。片段几乎同时到达，靠它把文字按节奏放出来。 */
  revealed: number
}

/**
 * 按 `sequence` 收片段。同一序号重复到达（重连/重试）不会重复拼接，换了
 * `messageId` 说明是新的一条叙事，连揭示进度一起从头开始。
 */
export function accumulateNarrationChunk(
  current: StreamingNarration | null,
  chunk: { messageId: string; sequence: number; text: string },
): StreamingNarration {
  const base =
    current?.messageId === chunk.messageId
      ? current
      : { messageId: chunk.messageId, chunks: {}, revealed: 0 }
  if (chunk.sequence in base.chunks) return base
  return {
    ...base,
    chunks: { ...base.chunks, [chunk.sequence]: chunk.text },
  }
}

/** 按序号升序拼接已到达的片段；乱序到达也能得到正确文本。 */
export function streamingNarrationText(state: StreamingNarration): string {
  return Object.keys(state.chunks)
    .map(Number)
    .sort((a, b) => a - b)
    .map((sequence) => state.chunks[sequence])
    .join('')
}

/**
 * 逐字揭示的节奏参数（issue #203）。
 *
 * 服务端是在完整叙事生成并校验之后才切片的，所有片段会在毫秒级内一起到达
 * （实测三帧间隔 0.5–0.7ms）。所以「渐进」必须由前端控制节奏，否则玩家看到的
 * 仍然是整段瞬间弹出。这是展示层的节奏，不是真的增量生成——真增量要等可独立
 * 校验的 ValidatedNarrationChunk 协议。
 *
 * 长文本按比例加快，保证总时长不超过 REVEAL_MAX_MS；短文本自然更快结束。
 */
const REVEAL_TICK_MS = 30
const REVEAL_MAX_MS = 2400

function mergeHistoricalMessages(current: Message[], history: Message[]): Message[] {
  const ids = new Set(current.flatMap((item) => (item.messageId ? [item.messageId] : [])))
  return [...history.filter((item) => !item.messageId || !ids.has(item.messageId)), ...current]
}

function appendLiveMessage(current: Message[], message: Message): Message[] {
  if (message.messageId && current.some((item) => item.messageId === message.messageId)) {
    return current
  }
  return [...current, message]
}

function displayName(...candidates: Array<string | null | undefined>): string {
  for (const candidate of candidates) {
    const trimmed = candidate?.trim()
    if (trimmed) return trimmed
  }
  return '玩家'
}

function conversationEventToMessage(
  event: RoomConversationEvent,
  selfPlayerId: string | null,
  senderName: string,
): Message | null {
  if (event.type === 'chat.message') {
    const payload = event.payload as {
      messageId: string
      playerId: string
      nickname: string
      text: string
      sentAt: string
      clientMessageId: string
    }
    return {
      type: 'player',
      channel: 'discussion',
      messageId: conversationMessageId(event.type, event.id),
      sender: payload.nickname,
      content: payload.text,
      time: formatRoomTime(payload.sentAt),
      isSelf: payload.playerId === selfPlayerId,
    }
  }
  if (event.type === 'action.broadcast') {
    const payload = event.payload as {
      playerId: string
      clientActionId: string
      nickname: string
      characterName?: string | null
      utterance: string
    }
    return {
      type: 'player',
      channel: 'action',
      messageId: conversationMessageId(event.type, event.id),
      sender: displayName(payload.characterName, payload.nickname),
      content: payload.utterance,
      time: formatRoomTime(event.createdAt),
      isSelf: payload.playerId === selfPlayerId,
    }
  }
  if (event.type === 'narration.push') {
    const payload = event.payload as { messageId?: string | null; text: string }
    return {
      type: 'narr',
      channel: 'action',
      messageId: conversationMessageId(event.type, payload.messageId || event.id),
      sender: '守秘人',
      content: payload.text,
      time: formatRoomTime(event.createdAt),
    }
  }
  if (event.type === 'check.result') {
    const payload = event.payload as {
      playerId: string
      clientActionId: string
      skillName: string
      characterName?: string | null
      targetValue: number
      rollValue: number
      difficulty: string
      successLevel: string
      passed: boolean
      result: string
    }
    const levelLabels: Record<string, string> = {
      critical: '大成功',
      extreme: '极难成功',
      hard: '困难成功',
      regular: '成功',
      failure: '失败',
      fumble: '大失败',
    }
    const difficultyLabels: Record<string, string> = {
      regular: '常规',
      hard: '困难',
      extreme: '极难',
    }
    const levelLabel = levelLabels[payload.successLevel] ?? payload.result
    const outcomeLabel = payload.passed
      ? levelLabel
      : `${levelLabel}（未通过${difficultyLabels[payload.difficulty] ?? ''}检定）`
    return {
      type: 'dice',
      channel: 'action',
      messageId: conversationMessageId(event.type, event.id),
      sender: displayName(
        payload.characterName,
        payload.playerId === selfPlayerId ? senderName : null,
      ),
      content: `${payload.skillName} ${payload.targetValue}% · D100 ${payload.rollValue} · ${outcomeLabel}`,
      time: formatRoomTime(event.createdAt),
      isSelf: payload.playerId === selfPlayerId,
    }
  }
  return null
}

const DICE_OPTIONS = [
  { id: 'd100', label: 'D100' },
  { id: 'd20', label: 'D20' },
  { id: 'd6', label: 'D6' },
] as const

type DiceType = typeof DICE_OPTIONS[number]['id']

type PendingCheckDiceState = {
  clientActionId: string
  selectedSkillId: string | null
  shakeLevel: number
  result: number | null
  rolling: boolean
  showResult: boolean
  tens: number
  ones: number
  submitted: boolean
}

function createPendingCheckDiceState(checkRequest: CheckRequestPayload): PendingCheckDiceState {
  return {
    clientActionId: checkRequest.clientActionId,
    selectedSkillId: checkRequest.skills[0]?.id ?? null,
    shakeLevel: 0,
    result: null,
    rolling: false,
    showResult: false,
    tens: 0,
    ones: 0,
    submitted: false,
  }
}

const DIFFICULTY_COLORS: Record<string, string> = {
  crit: '#5aaa5a',
  success: '#4a8a4a',
  fail: '#d45050',
  fumble: '#d45050',
}

// ─── Panel Component ─────────────────────────────────
// heightVh：不传就是原来的"按内容自适应、最多 72vh"；传了就固定成这个高度
// （不再随内容多少变化），配合内部 overflow-y-auto 滚动——用于内容量本身
// 会因为切页签/切分类而差很多、又不想让面板跟着一起忽高忽低的场景。
function BottomPanel({ open, onClose, title, children, heightVh }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; heightVh?: number }) {
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  const maxH = heightVh ?? 72

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />}
      <div
        className={`fixed bottom-0 left-0 right-0 z-50 bg-card rounded-t-2xl shadow-xl transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] max-w-[430px] mx-auto ${open ? 'translate-y-0' : 'translate-y-full'}`}
        style={heightVh ? { height: `${maxH}vh` } : { maxHeight: `${maxH}vh` }}
      >
        <div className="flex flex-col items-center pt-2.5 pb-0 cursor-pointer" onClick={onClose}>
          <div className="w-9 h-1 rounded-full bg-border-mid" />
        </div>
        <div className="flex items-center justify-between px-5 pt-2 pb-3">
          <h3 className="text-base font-bold text-text-primary">{title}</h3>
          <button aria-label="关闭面板" onClick={onClose} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center active:scale-90 transition-transform">
            <X className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
          </button>
        </div>
        <div className="overflow-y-auto px-5 pb-6" style={{ maxHeight: `calc(${maxH}vh - 60px)` }}>
          {children}
        </div>
      </div>
    </>
  )
}

// ─── Dice System ─────────────────────────────────────
// 跟角色卡/技能那几个面板一样用 BottomPanel（底部弹层，不盖满整个屏幕），
// 不再是独立的全屏深色页面。面板现在跟其他面板一样常驻挂载、靠 open 控制
// 滑入滑出，所以每次重新打开都要把上一次投骰的结果清空，不然会看到上一轮
// 的结果还留着。
function DiceModal({
  open,
  onClose,
  onResult,
  checkRequest,
  checkDiceState,
  setCheckDiceState,
}: {
  open: boolean
  onClose: () => void
  onResult: (result: number, diceType: DiceType, skillId?: string) => void
  checkRequest: CheckRequestPayload | null
  checkDiceState: PendingCheckDiceState | null
  setCheckDiceState: Dispatch<SetStateAction<PendingCheckDiceState | null>>
}) {
  const [freeDiceType, setFreeDiceType] = useState<DiceType>('d100')
  const [freeShakeLevel, setFreeShakeLevel] = useState(0)
  const [freeResult, setFreeResult] = useState<number | null>(null)
  const [freeRolling, setFreeRolling] = useState(false)
  const [freeShowResult, setFreeShowResult] = useState(false)
  const [freeTens, setFreeTens] = useState(0)
  const [freeOnes, setFreeOnes] = useState(0)
  const tableRef = useRef<HTMLDivElement>(null)
  const isGrabbed = useRef(false)
  const directionChanges = useRef(0)
  const lastDirX = useRef(0)
  const lastDirY = useRef(0)
  const submitLockRef = useRef(false)

  useEffect(() => {
    if (!checkRequest) {
      submitLockRef.current = false
      return
    }
    if (!checkDiceState || checkDiceState.clientActionId !== checkRequest.clientActionId) {
      setCheckDiceState(createPendingCheckDiceState(checkRequest))
      submitLockRef.current = false
      return
    }
    submitLockRef.current = checkDiceState.submitted
  }, [checkRequest, checkDiceState, setCheckDiceState])

  useEffect(() => {
    if (open && !checkRequest) {
      setFreeDiceType('d100')
      setFreeShakeLevel(0)
      setFreeResult(null)
      setFreeRolling(false)
      setFreeShowResult(false)
      setFreeTens(0)
      setFreeOnes(0)
      submitLockRef.current = false
    }
  }, [open, checkRequest])

  const isCheckMode = Boolean(checkRequest)
  const activeCheckDice = checkRequest ? checkDiceState : null
  const activeDiceType: DiceType = isCheckMode ? 'd100' : freeDiceType
  const activeShakeLevel = isCheckMode ? activeCheckDice?.shakeLevel ?? 0 : freeShakeLevel
  const activeResult = isCheckMode ? activeCheckDice?.result ?? null : freeResult
  const activeRolling = isCheckMode ? activeCheckDice?.rolling ?? false : freeRolling
  const activeShowResult = isCheckMode ? activeCheckDice?.showResult ?? false : freeShowResult
  const activeTens = isCheckMode ? activeCheckDice?.tens ?? 0 : freeTens
  const activeOnes = isCheckMode ? activeCheckDice?.ones ?? 0 : freeOnes
  const activeSelectedSkillId = isCheckMode
    ? activeCheckDice?.selectedSkillId ?? checkRequest?.skills[0]?.id ?? null
    : null
  const selectedSkill =
    checkRequest?.skills.find((skill) => skill.id === activeSelectedSkillId) ?? null
  const targetValue = selectedSkill?.targetValue ?? 65
  const canEditCheck = isCheckMode && !activeRolling && !activeShowResult && activeResult === null && !activeCheckDice?.submitted

  const updateCheckDiceState = (updater: (current: PendingCheckDiceState) => PendingCheckDiceState) => {
    if (!checkRequest) return
    setCheckDiceState((current) => {
      if (!current || current.clientActionId !== checkRequest.clientActionId) return current
      return updater(current)
    })
  }

  const roll = (power: number) => {
    if (isCheckMode) {
      if (!checkRequest || !activeCheckDice || activeCheckDice.result !== null || activeCheckDice.submitted || activeCheckDice.rolling) return
      const requestId = checkRequest.clientActionId
      updateCheckDiceState((current) => ({
        ...current,
        rolling: true,
        showResult: false,
      }))

      const tens = Math.floor(Math.random() * 10)
      const ones = Math.floor(Math.random() * 10)
      let finalResult = tens * 10 + ones
      if (finalResult === 0) finalResult = 100

      const dur = 500 + power * 100
      setTimeout(() => {
        setCheckDiceState((current) => {
          if (!current || current.clientActionId !== requestId) return current
          return {
            ...current,
            result: finalResult,
            showResult: true,
            rolling: false,
            tens,
            ones,
          }
        })
      }, dur)
      return
    }

    setFreeRolling(true)
    setFreeShowResult(false)

    let finalResult: number
    let tens = 0
    let ones = 0

    if (freeDiceType === 'd100') {
      tens = Math.floor(Math.random() * 10)
      ones = Math.floor(Math.random() * 10)
      finalResult = tens * 10 + ones
      if (finalResult === 0) finalResult = 100
      setFreeTens(tens)
      setFreeOnes(ones)
    } else if (freeDiceType === 'd20') {
      finalResult = Math.floor(Math.random() * 20) + 1
    } else {
      finalResult = Math.floor(Math.random() * 6) + 1
    }

    const dur = 500 + power * 100
    setTimeout(() => {
      setFreeResult(finalResult)
      setFreeShowResult(true)
      setFreeRolling(false)
    }, dur)
  }

  const handleMouseDown = () => {
    if (activeRolling || activeShowResult || (isCheckMode && activeResult !== null)) return
    isGrabbed.current = true
    directionChanges.current = 0
    lastDirX.current = 0
    lastDirY.current = 0
    if (isCheckMode) {
      updateCheckDiceState((current) => ({
        ...current,
        shakeLevel: 0,
      }))
    } else {
      setFreeShakeLevel(0)
    }
  }

  const handleMouseMove = (e: React.MouseEvent | React.TouchEvent) => {
    if (!isGrabbed.current) return
    const clientX = 'touches' in e ? e.touches[0].clientX : e.clientX
    const clientY = 'touches' in e ? e.touches[0].clientY : e.clientY

    if (tableRef.current) {
      const rect = tableRef.current.getBoundingClientRect()
      const dx = clientX - (rect.left + rect.width / 2)
      const dy = clientY - (rect.top + rect.height / 2)
      const dirX = Math.sign(dx)
      const dirY = Math.sign(dy)

      if (lastDirX.current !== 0 && dirX !== lastDirX.current) directionChanges.current++
      if (lastDirY.current !== 0 && dirY !== lastDirY.current) directionChanges.current++
      lastDirX.current = dirX
      lastDirY.current = dirY

      const level = Math.min(5, Math.floor(directionChanges.current / 2.5))
      if (isCheckMode) {
        updateCheckDiceState((current) => ({
          ...current,
          shakeLevel: level,
        }))
      } else {
        setFreeShakeLevel(level)
      }
    }
  }

  const handleMouseUp = () => {
    if (!isGrabbed.current) return
    isGrabbed.current = false
    if (activeShakeLevel >= 1) {
      roll(activeShakeLevel)
    } else {
      roll(1)
    }
  }

  const confirmResult = () => {
    if (isCheckMode) {
      if (!checkRequest || !activeCheckDice || activeResult === null || !activeSelectedSkillId) return
      if (submitLockRef.current || activeCheckDice.submitted) return
      submitLockRef.current = true
      setCheckDiceState((current) => {
        if (!current || current.clientActionId !== checkRequest.clientActionId) return current
        return { ...current, submitted: true }
      })
      onResult(activeResult, 'd100', activeSelectedSkillId)
      onClose()
      return
    }

    if (activeResult === null) return
    onResult(activeResult, activeDiceType, undefined)
    onClose()
  }

  const renderDiceDisplay = () => {
    const glow = activeRolling ? 'opacity-40' : ''
    return (
      <div ref={tableRef} className={`relative w-full h-48 flex items-center justify-center select-none ${isGrabbed.current ? 'cursor-grabbing' : 'cursor-grab'} ${glow}`}>
        {activeDiceType === 'd100' ? (
          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className={`text-[42px] font-bold font-mono tracking-wider ${activeTens === 0 ? 'text-[#c8c0b8]' : 'text-[#eeead8]'} transition-colors`}>
                {String(activeTens * 10).padStart(2, '0')}
              </div>
              <div className="text-[10px] text-[#9088a0] mt-1 font-mono">十位</div>
            </div>
            <div className="text-[28px] text-[#9088a0] font-mono">+</div>
            <div className="text-center">
              <div className={`text-[42px] font-bold font-mono ${activeOnes === 0 ? 'text-[#c8c0b8]' : 'text-[#eeead8]'} transition-colors`}>
                {activeOnes}
              </div>
              <div className="text-[10px] text-[#9088a0] mt-1 font-mono">个位</div>
            </div>
          </div>
        ) : (
          <div
            className={`text-[64px] font-bold font-mono text-[#eeead8] ${isGrabbed.current ? 'scale-105' : ''} transition-transform duration-150`}
            style={{
              clipPath: activeDiceType === 'd20' ? 'polygon(50% 0%, 95% 25%, 95% 75%, 50% 100%, 5% 75%, 5% 25%)' : undefined,
              background: 'linear-gradient(145deg, #2a2630, #1a1620)',
              width: activeDiceType === 'd20' ? '90px' : '80px',
              height: activeDiceType === 'd20' ? '96px' : '80px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: activeDiceType === 'd6' ? '12px' : undefined,
              border: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            {activeRolling ? (activeDiceType === 'd20' ? Math.floor(Math.random() * 20) + 1 : Math.floor(Math.random() * 6) + 1) : activeResult || '-'}
          </div>
        )}
      </div>
    )
  }

  const getVerdict = (): { label: string; color: string } | null => {
    if (activeResult === null || activeDiceType !== 'd100') return null
    if (activeResult === 1) return { label: '大成功', color: DIFFICULTY_COLORS.crit }
    if (activeResult <= Math.floor(targetValue / 5)) return { label: '极难成功', color: DIFFICULTY_COLORS.success }
    if (activeResult <= Math.floor(targetValue / 2)) return { label: '困难成功', color: DIFFICULTY_COLORS.success }
    if (activeResult <= targetValue) return { label: '成功', color: DIFFICULTY_COLORS.success }
    return { label: '失败', color: DIFFICULTY_COLORS.fail }
  }

  const verdict = getVerdict()

  return (
    <BottomPanel open={open} onClose={onClose} title="骰子检定">
      {!isCheckMode && (
        <div className="flex gap-1.5 mb-3.5">
          {DICE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              onClick={() => {
                if (!freeRolling) {
                  setFreeDiceType(opt.id)
                  setFreeResult(null)
                  setFreeShowResult(false)
                  setFreeShakeLevel(0)
                  setFreeTens(0)
                  setFreeOnes(0)
                }
              }}
              className={`flex-1 text-center text-[12px] font-semibold py-1.5 rounded-[99px] border transition-all ${
                freeDiceType === opt.id ? 'bg-brass text-white border-brass' : 'bg-panel text-text-muted border-border-light'
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      {isCheckMode && checkRequest && checkRequest.skills.length > 1 && (
        <div className="flex flex-wrap gap-2 mb-3.5">
          {checkRequest.skills.map((skill) => (
            <button
              key={skill.id}
              disabled={!canEditCheck}
              onClick={() => {
                if (!canEditCheck) return
                setCheckDiceState((current) => {
                  if (!current || current.clientActionId !== checkRequest.clientActionId) return current
                  return {
                    ...current,
                    selectedSkillId: skill.id,
                    result: null,
                    showResult: false,
                    shakeLevel: 0,
                    tens: 0,
                    ones: 0,
                    submitted: false,
                    rolling: false,
                  }
                })
                submitLockRef.current = false
              }}
              className={`px-3 py-1.5 rounded-full border text-xs font-semibold transition-all ${
                activeSelectedSkillId === skill.id
                  ? 'bg-brass text-white border-brass'
                  : 'bg-panel text-text-muted border-border-light'
              }`}
            >
              {skill.name} {skill.targetValue}
            </button>
          ))}
        </div>
      )}

      <div className="text-center mb-3">
        <span className="text-xs text-brass-dark font-semibold bg-brass/10 px-4 py-1 rounded-full inline-block">
          {selectedSkill?.name ?? '自由掷骰'}
        </span>
        <div className="font-mono text-xs text-text-muted mt-1">
          {activeDiceType === 'd100'
            ? `目标: ${targetValue} · D% = 十位 + 个位`
            : '自由检定'}
        </div>
      </div>

      <div
        data-testid="dice-table"
        className="rounded-md bg-[#1a1620] px-4 pt-5 pb-4 flex flex-col items-center relative overflow-hidden"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onTouchStart={handleMouseDown}
        onTouchMove={handleMouseMove}
        onTouchEnd={handleMouseUp}
      >
        {activeShakeLevel >= 2 && !activeRolling && !activeShowResult && (
          <div
            className="absolute w-52 h-52 rounded-full pointer-events-none transition-all duration-200"
            style={{
              background: `radial-gradient(circle, rgba(184,151,106,${0.04 + activeShakeLevel * 0.04}) 0%, transparent 70%)`,
              transform: `scale(${1 + activeShakeLevel * 0.05})`,
            }}
          />
        )}

        {renderDiceDisplay()}

        {!activeRolling && !activeShowResult && (
          <div className="text-center mt-2">
            <span className="text-xs text-[#9088a0]">
              {activeShakeLevel === 0 ? '👆 按住这里来回拖动 · 摇动后松手' :
               activeShakeLevel <= 2 ? '⚡ 再用力一点……' :
               activeShakeLevel <= 4 ? '🔥 快了！' :
               '💥 松手投出！'}
            </span>
          </div>
        )}

        {!activeRolling && !activeShowResult && (
          <div className="flex gap-1 mt-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className={`w-6 h-1 rounded-full transition-all duration-200 ${
                i < activeShakeLevel ? (i >= 3 ? 'bg-brass' : 'bg-[rgba(184,151,106,0.5)]') : 'bg-[rgba(255,255,255,0.08)]'
              }`} />
            ))}
          </div>
        )}

        {activeRolling && (
          <div className="text-center mt-2 text-xs text-[#9088a0] animate-pulse">
            🎲 骰子飞出去了……
          </div>
        )}
      </div>

      {activeShowResult && activeResult !== null && (
        <div className="flex flex-col items-center pt-4 gap-3 animate-[fadeIn_0.3s_ease]">
          <div className="text-center">
            {activeDiceType === 'd100' ? (
              <>
                <div className="flex items-center justify-center gap-2 text-text-dim font-mono text-sm">
                  <span>{String(activeTens * 10).padStart(2, '0')}</span>
                  <span>+</span>
                  <span>{activeOnes}</span>
                  <span>=</span>
                </div>
                <div className={`text-[44px] font-bold font-mono ${activeResult === 1 ? 'text-[#5aaa5a]' : activeResult > targetValue ? 'text-[#d45050]' : 'text-[#4a8a4a]'}`}>
                  {String(activeResult).padStart(2, '0')}
                </div>
              </>
            ) : (
              <div className="text-[44px] font-bold font-mono text-text-primary">{activeResult}</div>
            )}
            {verdict && (
              <div className="text-base font-bold mt-1" style={{ color: verdict.color }}>{verdict.label}</div>
            )}
            <div className="text-xs text-text-dim mt-1 font-mono">
              {activeDiceType === 'd100'
                ? `${selectedSkill?.name ?? '自由检定'} ${targetValue}% · 需求 ≤${targetValue}`
                : `${activeDiceType.toUpperCase()} · 自由检定`}
            </div>
          </div>

          <button
            onClick={confirmResult}
            disabled={isCheckMode && !!activeCheckDice?.submitted}
            className="w-full py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark active:scale-[0.97] transition-all disabled:opacity-60"
          >
            确认并发送
          </button>
        </div>
      )}
    </BottomPanel>
  )
}

// ─── Main RoomPage ───────────────────────────────────
export default function RoomPage() {
  const navigate = useNavigate()
  const roomId = useRoomStore((s) => s.roomId)
  const roomCode = useRoomStore((s) => s.roomCode)
  const playerId = useRoomStore((s) => s.playerId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const nickname = useAuthStore((s) => s.nickname)
  // 按房间取角色卡，而不是直接读 s.character——本地缓存不按房间区分的话，
  // 换房间会把上一个房间的角色数据错误地展示出来（见 PR #67 review）。
  const character = useCharacterStore((s) => (roomId ? s.getForRoom(roomId) : null))
  const senderName = character?.info.name || nickname || '你'
  const { ruleset } = useRuleset()
  const roomInfo = useRoomPlayers(roomCode)
  const hostSpeech = useHostSpeech()
  const enqueueHostSpeech = hostSpeech.enqueue
  const markHostSpeechSeen = hostSpeech.markSeen
  const isHost = roomInfo?.players.find((p) => p.playerId === playerId)?.isHost ?? false
  const [roomPhase, setRoomPhase] = useState<string | null>(null)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [ending, setEnding] = useState(false)
  const [endError, setEndError] = useState('')
  const [confirmExit, setConfirmExit] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [channel, setChannel] = useState<'action' | 'discussion'>('action')
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [pendingAction, setPendingAction] = useState<{ clientActionId: string; utterance: string } | null>(null)
  const [pendingCheck, setPendingCheck] = useState<CheckRequestPayload | null>(null)
  const [pendingCheckDice, setPendingCheckDice] = useState<PendingCheckDiceState | null>(null)
  const [playerView, setPlayerView] = useState<AgentPlayerView | null>(() => {
    const cached = sdk.roomSocket.getPlayerView()
    return cached?.room_id === roomId ? cached : null
  })
  const [progressLabel, setProgressLabel] = useState<string | null>(null)
  const [streamingNarration, setStreamingNarration] = useState<StreamingNarration | null>(null)
  // 队列而不是单槽：揭示窗口最长 REVEAL_MAX_MS，这期间完全可能再来一条叙事
  // （无片段的叙事后端会跳过切片，直接发 push）。用单槽的话后到的会把前一条
  // 顶掉，被顶掉的那条既不进 messages 也不朗读，只能靠刷新走历史恢复。
  const [pendingNarrations, setPendingNarrations] = useState<NarrationPushPayload[]>([])
  const [actionError, setActionError] = useState('')
  const [actionErrorRetryable, setActionErrorRetryable] = useState(false)
  const [actionErrorIsGuidance, setActionErrorIsGuidance] = useState(false)
  const [actionErrorCode, setActionErrorCode] = useState<string | null>(null)
  const [actionErrorCorrelationId, setActionErrorCorrelationId] = useState<string | null>(null)
  const [openPanel, setOpenPanel] = useState<string | null>(null)
  const [sheetPage, setSheetPage] = useState<'info' | 'background'>('info')
  const [skillsTab, setSkillsTab] = useState<'occupation' | 'interest'>('occupation')
  const [showDice, setShowDice] = useState(false)
  const notesKey = roomId ? `aidm-notes-${roomId}` : null
  // ★ 之前"📋 案件笔记"标题是直接塞进 textarea 初始内容里的普通文本，用户
  // 一编辑/全选删除就会把标题本身也删掉。改成占位符（placeholder），真正
  // 的内容默认是空白，标题不会被误删，也不占用户还没写的正文空间。
  const [notes, setNotes] = useState(
    () => (notesKey && localStorage.getItem(notesKey)) || ''
  )
  const [lastSaved, setLastSaved] = useState<string | null>(() => (notesKey ? localStorage.getItem(notesKey) : null) ? new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const pendingNarrationActionIdRef = useRef<string | null>(null)
  const suspended = (roomPhase || roomInfo?.phase) === 'Suspended'
  const mapLocations = mapLocationsFromPlayerView(playerView)
  const currentHp = resourceValue(playerView, 'hp') ?? character?.derived.hp ?? null
  const currentSan = resourceValue(playerView, 'san') ?? character?.derived.san ?? null

  useEffect(() => {
    if (roomInfo?.phase) setRoomPhase(roomInfo.phase)
  }, [roomInfo?.phase])

  useEffect(() => {
    if (!roomId || !reconnectToken) return
    let cancelled = false
    void sdk.rooms.listConversation(roomId, reconnectToken).then((history) => {
      if (cancelled) return
      const restored = history
        .map((event) => conversationEventToMessage(event, playerId, senderName))
        .filter((item): item is Message => item !== null)
      markHostSpeechSeen(
        restored.flatMap((item) =>
          item.type === 'narr' && item.messageId ? [item.messageId] : [],
        ),
      )
      setMessages((current) => mergeHistoricalMessages(current, restored))
      if (
        restored.some(
          (item) =>
            item.messageId === conversationMessageId('narration.push', 'game-opening'),
        )
      ) {
        setTyping(false)
        setProgressLabel(null)
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [markHostSpeechSeen, roomId, reconnectToken, playerId, senderName])

  useEffect(() => {
    // ★ block: 'nearest' 很关键——默认的 scrollIntoView 会尝试把目标"居中"，
    // 这会一路把祖先链上所有能滚动的容器都滚一遍，包括 #root（虽然它设了
    // overflow:hidden，但那只是不让用户手动滚，程序仍然能改它的 scrollTop，
    // 一旦被带偏就会把整个 RoomPage 顶飞，见「继续游戏」跳转后的空白页 bug）。
    // 'nearest' 只调整真正需要滚的那个容器（消息列表自己），不会殃及无关祖先。
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [messages])

  // ★ 访客走的是 /join → /character → /character-ready → /room，全程不经过
  // /lobby——而 connectWebSocket 之前只在 LobbyPage 里调用过，导致访客的浏览器
  // 从头到尾没建立过 WS 连接，发消息全部被静默丢弃（见 2026-07-13 多人测试报告
  // P0）。这里补一次同样的连接+room.join，对已经连过的房主是幂等空操作。
  useEffect(() => {
    if (!roomId || !playerId) return
    const cached = sdk.roomSocket.getPlayerView()
    setPlayerView(cached?.room_id === roomId ? cached : null)
    let cancelled = false
    const ws = connectWebSocket(roomId)
    waitForWsOpen(ws)
      .then(() => {
        if (cancelled) return
        sdk.roomSocket.joinRoom(playerId, { reconnectToken: reconnectToken || '', roomCode, nickname: nickname || '玩家' })
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [roomId, playerId, roomCode, nickname, reconnectToken])

  /** 把权威叙事落成正式消息，并交给语音朗读。只有它产出权威历史。 */
  const commitNarration = useCallback((payload: NarrationPushPayload) => {
    const authoritativeId = payload.messageId?.trim()
    const messageId = authoritativeId
      ? conversationMessageId('narration.push', authoritativeId)
      : pendingNarrationActionIdRef.current
        ? conversationMessageId('narration.push', pendingNarrationActionIdRef.current)
        : undefined
    enqueueHostSpeech(messageId, payload.text)
    setMessages((prev) => {
      if (messageId && prev.some((item) => item.messageId === messageId)) {
        pendingNarrationActionIdRef.current = null
        return prev
      }
      if (!messageId && prev.at(-1)?.content === payload.text) return prev
      pendingNarrationActionIdRef.current = null
      return appendLiveMessage(prev, {
        type: 'narr',
        channel: 'action',
        messageId,
        sender: '守秘人',
        content: payload.text,
        time: formatRoomTime(new Date()),
      })
    })
  }, [enqueueHostSpeech])

  // 逐字揭示：片段几乎同时到达，节奏由这里控制。长文本按比例加快，总时长
  // 不超过 REVEAL_MAX_MS。
  useEffect(() => {
    if (!streamingNarration) return
    const full = streamingNarrationText(streamingNarration)
    if (streamingNarration.revealed >= full.length) return
    const step = Math.max(1, Math.ceil(full.length / (REVEAL_MAX_MS / REVEAL_TICK_MS)))
    const timer = setTimeout(() => {
      setStreamingNarration((current) =>
        current === null
          ? current
          : {
              ...current,
              revealed: Math.min(
                streamingNarrationText(current).length,
                current.revealed + step,
              ),
            },
      )
    }, REVEAL_TICK_MS)
    return () => clearTimeout(timer)
  }, [streamingNarration])

  // 权威消息何时接管：按到达顺序逐条提交，队首那条还没揭示完就等着。
  //
  // 严格按队首处理（而不是跳过它先提交后面的）是为了保持叙事顺序：后到的
  // 叙事最多被队首多等一个揭示周期，但不会插到前一条之前，也不会把它挤掉。
  useEffect(() => {
    const next = pendingNarrations[0]
    if (!next) return
    const belongsToStream =
      streamingNarration !== null &&
      next.messageId != null &&
      streamingNarration.messageId ===
        conversationMessageId('narration.push', next.messageId)
    if (
      belongsToStream &&
      streamingNarration.revealed < streamingNarrationText(streamingNarration).length
    ) {
      return
    }
    commitNarration(next)
    setPendingNarrations((current) => current.slice(1))
    // 只清掉刚提交的这条对应的片段状态。别的叙事还在揭示时不能顺手清空，
    // 否则它的文字会凭空消失。
    if (belongsToStream) setStreamingNarration(null)
  }, [commitNarration, pendingNarrations, streamingNarration])

  // 服务端主持人回复：只订阅 narration.push，不从 turn.completed 或本地逻辑
  // 生成主持叙述。
  useEffect(() => {
    const off = onWsMessage((envelope) => {
      if (envelope.type === 'narration.chunk') {
        // 已经有文字在往外走，就不要再同时显示"正在思考"的点点了。
        setTyping(false)
        setProgressLabel(null)
        setStreamingNarration((current) =>
          accumulateNarrationChunk(current, {
            messageId: conversationMessageId('narration.push', envelope.payload.messageId),
            sequence: envelope.payload.sequence,
            text: envelope.payload.text,
          }),
        )
      } else if (envelope.type === 'narration.push') {
        setTyping(false)
        setProgressLabel(null)
        // 不在这里直接落地：权威消息比最后一个片段只晚到半毫秒，立刻接管会让
        // 刚开始的渐进展示当场被整段覆盖。入队，交给上面的 effect 按序裁决。
        setPendingNarrations((current) => [...current, envelope.payload])
      } else if (envelope.type === 'opening.started') {
        setTyping(true)
        setProgressLabel('守秘人正在生成开场叙事')
      } else if (envelope.type === 'room.state') {
        setRoomPhase(envelope.payload.phase)
      } else if (envelope.type === 'chat.message') {
        setMessages((prev) => {
          const messageId = conversationMessageId('chat.message', envelope.payload.messageId)
          if (prev.some((item) => item.messageId === messageId)) return prev
          return appendLiveMessage(prev, {
            type: 'player',
            channel: 'discussion',
            messageId,
            sender: envelope.payload.nickname,
            content: envelope.payload.text,
            time: formatRoomTime(envelope.payload.sentAt),
            isSelf: envelope.payload.playerId === playerId,
          })
        })
      } else if (envelope.type === 'action.broadcast') {
        setMessages((prev) => appendLiveMessage(prev, {
          type: 'player',
          channel: 'action',
          messageId: conversationMessageId('action.broadcast', envelope.payload.clientActionId),
          sender: displayName(envelope.payload.characterName, envelope.payload.nickname),
          content: envelope.payload.utterance,
          time: formatRoomTime(new Date()),
          isSelf: envelope.payload.playerId === playerId,
        }))
      } else if (envelope.type === 'check.request') {
        setTyping(false)
        setProgressLabel(null)
        setPendingCheck(envelope.payload)
        setPendingCheckDice((current) =>
          current?.clientActionId === envelope.payload.clientActionId
            ? current
            : createPendingCheckDiceState(envelope.payload)
        )
        setShowDice(true)
      } else if (envelope.type === 'check.result') {
        const levelLabels: Record<string, string> = {
          critical: '大成功',
          extreme: '极难成功',
          hard: '困难成功',
          regular: '成功',
          failure: '失败',
          fumble: '大失败',
        }
        const difficultyLabels: Record<string, string> = {
          regular: '常规',
          hard: '困难',
          extreme: '极难',
        }
        const levelLabel =
          levelLabels[envelope.payload.successLevel] ?? envelope.payload.result
        const outcomeLabel = envelope.payload.passed
          ? levelLabel
          : `${levelLabel}（未通过${difficultyLabels[envelope.payload.difficulty] ?? ''}检定）`
        setMessages(prev => appendLiveMessage(prev, {
          type: 'dice',
          channel: 'action',
          messageId: conversationMessageId('check.result', envelope.payload.clientActionId),
          sender: displayName(
            envelope.payload.characterName,
            envelope.payload.playerId === playerId ? senderName : null,
          ),
          content: `${envelope.payload.skillName} ${envelope.payload.targetValue}% · D100 ${envelope.payload.rollValue} · ${outcomeLabel}`,
          time: formatRoomTime(new Date()),
          isSelf: envelope.payload.playerId === playerId,
        }))
        setPendingCheck(current =>
          current?.clientActionId === envelope.payload.clientActionId ? null : current
        )
        setPendingCheckDice(current =>
          current?.clientActionId === envelope.payload.clientActionId ? null : current
        )
        if (envelope.payload.playerId === playerId) setShowDice(false)
      } else if (envelope.type === 'turn.started') {
        setTyping(true)
        setProgressLabel('守秘人正在查看当前场景')
      } else if (envelope.type === 'turn.phase_changed') {
        setTyping(envelope.payload.phase !== 'waiting_for_check')
        setProgressLabel(PHASE_LABELS[envelope.payload.phase])
      } else if (envelope.type === 'tool.started') {
        setTyping(true)
        setProgressLabel(envelope.payload.publicProgressLabel)
      } else if (envelope.type === 'turn.failed') {
        setTyping(false)
        setProgressLabel(null)
        // 片段只在叙事落库成功后才会下发，回合失败时不存在对应的权威消息——
        // 留着半截文字会让玩家以为那是这回合的结果。
        //
        // 只中止揭示，不清待提交队列：队列里的都是已经落库的权威消息（push 紧跟
        // 片段到达），清掉等于丢服务端认定已发生的叙事。中止后它们会立即落地。
        setStreamingNarration(null)
        setActionError(envelope.payload.publicMessage)
        setActionErrorRetryable(envelope.payload.retryable)
        setActionErrorIsGuidance(envelope.payload.code === 'HOST_AGENT_INVALID_OUTPUT')
        setActionErrorCode(envelope.payload.code)
        setActionErrorCorrelationId(envelope.payload.correlationId)
        pendingNarrationActionIdRef.current = null
      } else if (envelope.type === 'view.updated') {
        if (envelope.payload.playerId === playerId) {
          setPlayerView(envelope.payload.playerView)
        }
      } else if (envelope.type === 'error') {
        setTyping(false)
        setProgressLabel(null)
        setStreamingNarration(null)
        setActionError(envelope.payload.message)
        setActionErrorRetryable(false)
        setActionErrorIsGuidance(false)
        setActionErrorCode(envelope.payload.code)
        setActionErrorCorrelationId(envelope.payload.correlationId ?? null)
        pendingNarrationActionIdRef.current = null
      }
    })
    if (sdk.roomSocket.getOpeningMessageId() === 'game-opening') {
      setTyping(true)
      setProgressLabel('守秘人正在生成开场叙事')
    }
    return off
  }, [enqueueHostSpeech, playerId, senderName])

  const submitPlayerAction = (action: { clientActionId: string; utterance: string }) => {
    if (!playerId || suspended) return
    pendingNarrationActionIdRef.current = action.clientActionId
    setPendingAction(action)
    setActionError('')
    setActionErrorRetryable(false)
    setActionErrorIsGuidance(false)
    setActionErrorCode(null)
    setActionErrorCorrelationId(null)
    setTyping(true)
    void sdk.roomSocket
      .submitAction(playerId, action)
      .then((result) => {
        setPlayerView(result.player_view)
        setPendingAction((current) =>
          current?.clientActionId === action.clientActionId ? null : current
        )
      })
      .catch((error: unknown) => {
        setTyping(false)
        setProgressLabel(null)
        setActionError(
          error instanceof TurnFailedError || error instanceof RoomSocketServerError
            ? error.message
            : friendlyErrorMessage(error, '行动提交失败，请重试')
        )
        setActionErrorRetryable(
          error instanceof TurnFailedError ? error.retryable : true
        )
        setActionErrorIsGuidance(
          error instanceof TurnFailedError && error.code === 'HOST_AGENT_INVALID_OUTPUT'
        )
        setActionErrorCode(
          error instanceof TurnFailedError || error instanceof RoomSocketServerError
            ? error.code
            : 'CLIENT_TRANSPORT_ERROR'
        )
        setActionErrorCorrelationId(
          error instanceof TurnFailedError || error instanceof RoomSocketServerError
            ? error.correlationId
            : action.clientActionId
        )
        pendingNarrationActionIdRef.current = null
      })
  }

  const sendMessage = (e?: FormEvent) => {
    e?.preventDefault()
    const text = input.trim()
    if (!text || !playerId || suspended) return
    setInput('')
    if (channel === 'discussion') {
      sdk.roomSocket.sendChat(playerId, { text, clientMessageId: randomActionId() })
    } else {
      submitPlayerAction({ clientActionId: randomActionId(), utterance: text })
    }
  }

  const handleDiceResult = (result: number, diceType: DiceType, skillId?: string) => {
    if (pendingCheck) {
      if (!playerId || diceType !== 'd100' || !skillId || pendingCheckDice?.submitted) return
      setTyping(true)
      sdk.roomSocket.rollCheck(playerId, {
        clientActionId: pendingCheck.clientActionId,
        skill: skillId,
        rollValue: result,
      })
      return
    }
    const typeLabel = diceType.toUpperCase()
    const resultLabel = diceType === 'd100' ? (result <= 5 ? '极限成功' : result <= 65 ? '成功' : '失败') : `掷出 ${result}`
    setMessages(prev => [...prev, {
      type: 'dice', channel: 'action', sender: senderName, content: `${typeLabel} · ${result} · ${resultLabel}`, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), isSelf: true,
    }])
  }

  // 结束游戏——仅房主可操作。房间转「已完成」后只能在「我的游戏」里查看复盘，不能再回到聊天室。
  const handleEndGame = async () => {
    if (!roomId) return
    setEnding(true)
    setEndError('')
    try {
      await endGame(roomId)
      hostSpeech.stop()
      disconnectWebSocket()
      navigate('/home')
    } catch (err) {
      setEndError(friendlyErrorMessage(err, '结束游戏失败'))
      setEnding(false)
    }
  }

  // 退出（不是结束游戏）——只是自己离开，房间对其他人继续存在、phase 不变，
  // 之后可以从「我的游戏」用同一个身份重新进来（见 MyRoomsPage 的继续逻辑）。
  const handleExit = () => {
    hostSpeech.stop()
    disconnectWebSocket()
    navigate('/home')
  }

  return (
    <div className="h-full flex flex-col bg-card relative max-w-[430px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-border-light bg-page flex-shrink-0">
        <button onClick={() => setConfirmExit(true)} className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel">
          <ArrowLeft className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
        </button>
        <div className="w-8 h-8 rounded-full bg-[#f3eef8] flex items-center justify-center text-base flex-shrink-0">
          🏚️
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-text-primary">{roomInfo?.moduleTitle || '当前模组'}</div>
          <div className="text-[11px] text-text-muted">
            {playerView?.scene.name || (roomInfo ? `${roomInfo.players.length} 位调查员` : '克苏鲁的呼唤')}
          </div>
        </div>
        <button
          onClick={() => setOpenPanel(openPanel === 'speech' ? null : 'speech')}
          aria-label="主持人语音"
          title="主持人语音"
          className={`w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel ${hostSpeech.status === 'speaking' ? 'text-brass-dark' : 'text-text-muted'}`}
        >
          <Volume2 className="w-4 h-4" strokeWidth={2.5} />
        </button>
        <button
          onClick={() => setOpenPanel(openPanel === 'members' ? null : 'members')}
          aria-label="房间成员"
          title="房间成员"
          className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel"
        >
          <Users className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
        </button>
      </div>

      {/* 退出确认——不是结束游戏，房间对其他人继续存在 */}
      {confirmExit && (
        <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center px-8" onClick={() => setConfirmExit(false)}>
          <div className="bg-card border border-border-light rounded-md p-5 w-full max-w-[300px]" onClick={(e) => e.stopPropagation()}>
            <p className="text-sm text-text-body text-center mb-4">确定要退出游戏吗？房间会保留，之后可以从「我的游戏」继续。</p>
            <div className="flex gap-2">
              <button onClick={() => setConfirmExit(false)}
                className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium active:bg-border-light">
                取消
              </button>
              <button onClick={handleExit}
                className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium active:bg-[#a03030]">
                确认退出
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex items-center gap-1 px-3 py-2 border-b border-border-light bg-page">
        {([{ id: 'action', label: '行动' }, { id: 'discussion', label: '讨论区' }] as const).map((item) => (
          <button key={item.id} type="button" onClick={() => setChannel(item.id)} className={`flex-1 py-1.5 text-xs font-semibold rounded-md ${channel === item.id ? 'bg-brass text-white' : 'text-text-muted bg-panel'}`}>
            {item.label}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3" id="chatScroll">
        {messages.filter((msg) => (msg.channel ?? 'action') === channel).map((msg, i) => {
          if (msg.type === 'system') {
            return (
              <div key={i} className="text-center py-1.5 animate-[fadeIn_0.3s_ease]">
                <span className="text-[11px] text-text-dim bg-panel px-3.5 py-1 rounded-[99px] font-mono">{msg.content}</span>
              </div>
            )
          }

          if (msg.type === 'dice') {
            return (
              <div key={i} className="flex flex-row-reverse gap-2.5 animate-[msgIn_0.3s_ease]">
                <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm bg-[#eef6ee] border border-border-light">
                  🎲
                </div>
                <div className="flex-1 min-w-0 text-right">
                  <div className="text-[11px] font-semibold text-mold mb-0.5">{msg.sender} · 掷骰</div>
                  <div className="text-sm leading-[1.65] text-text-body inline-block max-w-full px-3.5 py-2.5 bg-[#eef6ee] rounded-md font-mono">
                    {msg.content}
                  </div>
                  <div className="text-[10px] text-text-dim mt-0.5">{msg.time}</div>
                </div>
              </div>
            )
          }

          const isPlayer = msg.type === 'player' && msg.isSelf
          const isNarr = msg.type === 'narr'

          return (
            <div key={i} className={`flex gap-2.5 ${isPlayer ? 'flex-row-reverse' : ''} animate-[msgIn_0.3s_ease]`}>
              <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm border border-border-light ${isNarr ? 'bg-[#faf5eb] border-brass' : isPlayer ? 'bg-[#eef6ee]' : 'bg-panel'}`}>
                {isNarr ? '📜' : isPlayer ? '🔍' : '🤖'}
              </div>
              <div className={`flex-1 min-w-0 ${isPlayer ? 'text-right' : ''}`}>
                <div className={`text-[11px] font-semibold text-text-muted mb-0.5 ${isPlayer ? 'text-mold' : ''} ${isNarr ? 'text-brass-dark' : ''}`}>
                  {msg.sender}
                </div>
                <div className={`
                  text-sm leading-[1.65] text-text-body inline-block max-w-full px-3.5 py-2.5
                  ${isPlayer ? 'bg-[#eef6ee] rounded-md' : ''}
                  ${isNarr ? 'bg-[#fdfaf4] border-l-[3px] border-brass rounded-r-sm rounded-l-none italic text-[#4a4030] text-left whitespace-pre-wrap' : ''}
                  ${!isPlayer && !isNarr ? 'bg-panel rounded-md' : ''}
                `}>
                  {msg.content}
                </div>
                <div className="text-[10px] text-text-dim mt-0.5">{msg.time}</div>
                {isNarr && (
                  <button
                    type="button"
                    aria-label="重新朗读"
                    title="重新朗读"
                    disabled={!hostSpeech.supported}
                    onClick={() => hostSpeech.replay(msg.content)}
                    className="mt-1 inline-flex items-center gap-1 text-[10px] text-text-muted disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <RotateCcw className="w-3 h-3" strokeWidth={2} />
                    重播
                  </button>
                )}
              </div>
            </div>
          )
        })}

        {/* 渐进到达的主持叙事（issue #203）。没有"重播"按钮：它还不是权威
            消息，语音朗读只认最终 narration.push。*/}
        {streamingNarration && streamingNarration.revealed > 0 && (
          <div className="flex gap-2.5 animate-[msgIn_0.3s_ease]">
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm bg-[#faf5eb] border border-brass">
              📜
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] font-semibold text-brass-dark mb-0.5">守秘人</div>
              <div className="text-sm leading-[1.65] inline-block max-w-full px-3.5 py-2.5 bg-[#fdfaf4] border-l-[3px] border-brass rounded-r-sm rounded-l-none italic text-[#4a4030] text-left whitespace-pre-wrap">
                {streamingNarrationText(streamingNarration).slice(0, streamingNarration.revealed)}
              </div>
              <div className="text-[10px] text-text-dim mt-0.5">生成中…</div>
            </div>
          </div>
        )}

        {/* Typing indicator。第一个片段到达后还没揭示出字的那一瞬间也留着它，
            避免出现一个空气泡。*/}
        {(typing || (streamingNarration !== null && streamingNarration.revealed === 0)) && (
          <div className="flex gap-2.5 animate-[msgIn_0.3s_ease]">
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm bg-[#faf5eb] border border-brass">
              📜
            </div>
            <div className="bg-panel inline-flex gap-2 items-center px-4 py-3 rounded-md">
              <div className="inline-flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="w-1.5 h-1.5 bg-brass rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.2}s`, animationDuration: '1.4s' }} />
                ))}
              </div>
              {progressLabel && (
                <span className="text-[11px] text-text-muted">{progressLabel}</span>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Action Bar */}
      <div className="flex bg-card border-t border-border-light flex-shrink-0">
        {[
          { icon: ScrollText, label: '角色卡', key: 'sheet' },
          { icon: Star, label: '技能', key: 'skills' },
          { icon: Map, label: '地图', key: 'map' },
          { icon: BookOpen, label: '速记', key: 'notes' },
        ].map((item) => (
          <button
            key={item.key}
            onClick={() => setOpenPanel(openPanel === item.key ? null : item.key)}
            className={`flex-1 py-1.5 px-1 bg-none border-none text-[10px] font-medium cursor-pointer flex flex-col items-center gap-[3px] font-sans transition-colors ${
              openPanel === item.key ? 'text-brass-dark bg-panel' : 'text-text-muted'
            }`}
          >
            <item.icon className="w-5 h-5" strokeWidth={1.5} />
            {item.label}
          </button>
        ))}
      </div>

      {/* HP/SAN 实时状态条——放在角色卡/技能等快捷面板和输入框之间，聊天时想随时
          瞄一眼当前状态不用点开面板。HP 目前没有"当前值/上限值"两套数字（还没
          做受伤扣血的机制，见已知局限），先按"当前即满值"画满条，以后接了扣血
          机制这里会自然跟着变化。 */}
      {currentHp !== null && currentSan !== null && (
        <div className="flex items-center gap-4 px-4 py-2 border-t border-border-light bg-page flex-shrink-0">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <Heart className="w-3 h-3 text-mold flex-shrink-0" strokeWidth={2.5} />
            <span className="text-[10px] font-semibold text-text-muted flex-shrink-0">HP</span>
            <div className="flex-1 h-1.5 rounded-full bg-border-light overflow-hidden">
              <div className="h-full rounded-full bg-mold" style={{ width: '100%' }} />
            </div>
            <span className="text-[11px] font-bold font-mono text-mold flex-shrink-0">{currentHp}</span>
          </div>
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <span className="text-[10px] font-semibold text-text-muted flex-shrink-0">SAN</span>
            <div className="flex-1 h-1.5 rounded-full bg-border-light overflow-hidden">
              <div className="h-full rounded-full bg-[#7050a0]" style={{ width: `${Math.min(100, currentSan)}%` }} />
            </div>
            <span className="text-[11px] font-bold font-mono text-[#7050a0] flex-shrink-0">{currentSan}</span>
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-border-light px-3 pb-3 pt-1.5 bg-page flex-shrink-0">
        {suspended && (
          <p className="text-[11px] text-[#9a6a30] text-center pb-1.5">
            游戏已挂起，恢复后才能继续提交行动
          </p>
        )}
        {actionError && !suspended && (
          <div className="pb-1.5 px-1">
            <div className="flex items-center justify-between gap-2">
              <p className={`text-[11px] ${actionErrorIsGuidance ? 'text-[#8a642d]' : 'text-[#c04040]'}`}>
                {actionErrorIsGuidance ? `守秘人提示：${actionError}` : actionError}
              </p>
              {pendingAction && actionErrorRetryable && (
                <button
                  type="button"
                  onClick={() => submitPlayerAction(pendingAction)}
                  className="text-[11px] text-brass-dark underline flex-shrink-0"
                >
                  使用原请求重试
                </button>
              )}
            </div>
            {actionErrorCode && actionErrorCorrelationId && (
              <button
                type="button"
                aria-label="复制错误详情"
                title="复制完整错误码和定位号"
                onClick={() => void navigator.clipboard?.writeText(
                  `${actionErrorCode} · ${actionErrorCorrelationId}`
                )}
                className="mt-1 text-[10px] font-mono text-text-dim underline decoration-dotted"
              >
                错误码 {actionErrorCode} · 定位号 {actionErrorCorrelationId.slice(0, 8)}
              </button>
            )}
          </div>
        )}
        <form onSubmit={sendMessage} className="flex gap-2 items-end">
          <button
            type="button"
            aria-label="骰子"
            onClick={() => setShowDice(true)}
            disabled={suspended}
            className="w-10 h-10 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center flex-shrink-0 active:scale-[0.92] active:border-brass active:text-brass-dark transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <Dice6 className="w-[18px] h-[18px]" strokeWidth={2} />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={suspended}
            placeholder={suspended ? '游戏已挂起' : '输入行动…'}
            className="flex-1 bg-input border border-border-mid rounded-[20px] px-4 py-2.5 text-sm text-text-primary font-sans outline-none min-h-[40px] placeholder:text-text-dim focus:border-brass transition-colors disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={suspended || !input.trim()}
            className="w-10 h-10 rounded-full bg-brass border-none text-white flex items-center justify-center flex-shrink-0 active:scale-[0.92] transition-all hover:bg-brass-dark disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <SendHorizontal className="w-[18px] h-[18px]" strokeWidth={2.5} />
          </button>
        </form>
      </div>

      {/* ── Panels ── */}

      {/* Panel: 角色卡（真实建卡数据，不再是写死的示例角色）。分两页——技能已经有
          单独的底部按钮，这里不重复放。 */}
      <BottomPanel open={openPanel === 'sheet'} onClose={() => setOpenPanel(null)} title={`调查员 · ${character?.info.name || '未建卡'}`}>
        {character ? (
          <>
            <div className="flex gap-1.5 mb-3.5">
              {[{ key: 'info', label: '基本信息' }, { key: 'background', label: '背景装备' }].map((p) => (
                <button key={p.key} onClick={() => setSheetPage(p.key as typeof sheetPage)}
                  className={`flex-1 text-center text-[12px] font-semibold py-1.5 rounded-[99px] border transition-all ${
                    sheetPage === p.key ? 'bg-brass text-white border-brass' : 'bg-panel text-text-muted border-border-light'
                  }`}>
                  {p.label}
                </button>
              ))}
            </div>

            {sheetPage === 'info' && (
              <>
                <div className="flex items-center gap-3 mb-3.5">
                  <div className="w-12 h-14 rounded-sm flex items-center justify-center text-2xl"
                    style={{ background: 'linear-gradient(135deg,#e8e0d0,#d8cfb8)', border: '2px solid #b8976a' }}>
                    🕵️
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-text-primary">{character.info.name}</div>
                    <div className="text-[11px] text-text-muted">
                      {character.info.age}岁 · {character.info.gender} · {character.info.occupationId ? ruleset?.occupations.find(o => o.id === character.info.occupationId)?.name : '未选择职业'}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-1.5 mb-4">
                  <div className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                    <span className="text-[11px] text-text-muted">居住地</span>
                    <span className="text-sm font-medium text-text-primary">{character.info.residence || '—'}</span>
                  </div>
                  <div className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                    <span className="text-[11px] text-text-muted">出生地</span>
                    <span className="text-sm font-medium text-text-primary">{character.info.birthplace || '—'}</span>
                  </div>
                </div>

                <div className="flex gap-2 mb-4">
                  {[
                    { label: 'HP', value: `${character.derived.hp}`, color: 'text-mold' },
                    { label: 'SAN', value: `${character.derived.san}`, color: 'text-[#7050a0]' },
                    { label: 'MP', value: `${character.derived.mp}`, color: 'text-[#4a7098]' },
                    { label: 'DB', value: character.derived.db, color: 'text-text-muted' },
                    { label: 'MOV', value: `${character.derived.move}`, color: 'text-text-muted' },
                  ].map((pill) => (
                    <div key={pill.label} className="flex-1 bg-panel rounded-md px-2.5 py-2 text-center">
                      <div className="text-[10px] text-text-muted font-medium">{pill.label}</div>
                      <div className={`text-base font-bold font-mono ${pill.color}`}>{pill.value}</div>
                    </div>
                  ))}
                </div>

                <div className="h-px bg-border-light mb-3.5" />

                <h4 className="text-xs font-semibold text-brass-dark mb-2.5">基础属性</h4>
                <div className="grid grid-cols-2 gap-1.5">
                  {/* 属性清单由后端 ruleset 驱动，前端不再自己维护一份名单——
                      此前三处各硬编码一份，加幸运时漏改一处就导致角色卡看不到
                      幸运值（issue #96）。 */}
                  {(ruleset?.attributes ?? []).map(attribute => (
                    <div key={attribute.key} className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                      <span className="font-mono text-[11px] font-bold text-text-muted">{attribute.key}</span>
                      <span className="font-mono text-sm font-bold text-text-primary">{character.attr[attribute.key]}</span>
                    </div>
                  ))}
                </div>
              </>
            )}

            {sheetPage === 'background' && (
              <>
                <h4 className="text-xs font-semibold text-brass-dark mb-2.5">装备</h4>
                <p className="text-sm text-text-body leading-[1.7] mb-4">{character.equipment || '未填写装备'}</p>
                <h4 className="text-xs font-semibold text-brass-dark mb-2.5">背景故事</h4>
                <p className="text-sm text-text-body leading-[1.7] mb-4">{character.background || '未填写背景故事'}</p>
                <h4 className="text-xs font-semibold text-brass-dark mb-2.5">备注</h4>
                <p className="text-sm text-text-body leading-[1.7]">{character.notes || '未填写备注'}</p>
              </>
            )}
          </>
        ) : (
          <p className="text-sm text-text-dim py-6 text-center">还没有创建角色</p>
        )}
      </BottomPanel>

      {/* Panel: 技能——按职业技能/兴趣技能分两页，各自按数值从高到低排列。
          固定半屏高度，两个页签内容多少不一样也不会让面板忽高忽低。 */}
      <BottomPanel open={openPanel === 'skills'} onClose={() => setOpenPanel(null)} title="技能" heightVh={50}>
        {character ? (
          <>
            <div className="flex gap-1.5 mb-3.5">
              {[{ key: 'occupation', label: '职业技能' }, { key: 'interest', label: '兴趣技能' }].map((t) => (
                <button key={t.key} onClick={() => setSkillsTab(t.key as typeof skillsTab)}
                  className={`flex-1 text-center text-[12px] font-semibold py-1.5 rounded-[99px] border transition-all ${
                    skillsTab === t.key ? 'bg-brass text-white border-brass' : 'bg-panel text-text-muted border-border-light'
                  }`}>
                  {t.label}
                </button>
              ))}
            </div>
            <div className="space-y-2">
              {(() => {
                const occSkillIds = character.info.occupationId
                  ? ruleset?.occupations.find(o => o.id === character.info.occupationId)?.skillIds ?? []
                  : []
                const list = (ruleset?.skills ?? [])
                  .filter((skill) => skillsTab === 'occupation' ? occSkillIds.includes(skill.id) : !occSkillIds.includes(skill.id))
                  .map((skill) => ({
                    skill,
                    value: character.skillFinalValues?.[skill.id] ?? 0,
                  }))
                  .sort((a, b) => b.value - a.value)
                return list.map(({ skill, value }) => (
                  <div key={skill.id} className="flex items-center gap-3 py-1.5">
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-text-primary">{skill.name}</div>
                      <div className="text-[10px] text-text-dim font-mono">{skill.nameEn}</div>
                    </div>
                    <div className="flex-1 h-2 rounded-full bg-border-light overflow-hidden">
                      <div className="h-full rounded-full bg-brass transition-all" style={{ width: `${value}%` }} />
                    </div>
                    <span className="text-xs font-bold font-mono text-text-muted min-w-[36px] text-right">{value}%</span>
                  </div>
                ))
              })()}
            </div>
          </>
        ) : (
          <p className="text-sm text-text-dim py-6 text-center">暂未建卡</p>
        )}
      </BottomPanel>

      {/* Panel: 地图 */}
      <BottomPanel open={openPanel === 'map'} onClose={() => setOpenPanel(null)} title="地图">
        <div className="bg-[#f2efe8] rounded-md flex flex-col items-center justify-center py-10 mb-4 border border-border-light">
          <Map className="w-10 h-10 text-text-dim mb-2" />
          <span className="text-xs text-text-dim">
            {playerView?.scene.name || '等待规则引擎同步当前场景'}
          </span>
          {playerView?.scene.time && (
            <span className="text-[10px] text-text-dim mt-1">{playerView.scene.time}</span>
          )}
        </div>
        <div className="h-px bg-border-light mb-3.5" />
        <h4 className="text-xs font-semibold text-brass-dark mb-2.5">当前位置与可达地点</h4>
        <div className="space-y-1.5">
          {mapLocations.map((loc) => (
            <div key={loc.id} className={`flex items-center gap-3 px-3 py-2 rounded ${
              loc.isCurrent ? 'bg-[rgba(74,138,74,0.06)] border border-[rgba(74,138,74,0.15)]' : 'hover:bg-panel'
            }`}>
              <span className="text-lg">{loc.icon}</span>
              <div className="flex-1">
                <div className="text-sm font-medium text-text-primary">{loc.name}</div>
                <div className="text-[11px] text-text-muted">{loc.desc}</div>
              </div>
              {loc.isCurrent && <span className="text-[10px] font-semibold text-mold flex-shrink-0">▶ 当前位置</span>}
            </div>
          ))}
        </div>
        {playerView && playerView.known_information.length > 0 && (
          <>
            <div className="h-px bg-border-light my-3.5" />
            <h4 className="text-xs font-semibold text-brass-dark mb-2.5">已知信息</h4>
            <div className="space-y-2">
              {playerView.known_information.map((information) => (
                <div key={information.id} className="rounded-md bg-panel px-3 py-2">
                  <div className="text-sm font-medium text-text-primary">
                    {information.title}
                  </div>
                  <div className="text-[11px] leading-relaxed text-text-muted mt-0.5">
                    {information.summary}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </BottomPanel>

      {/* Panel: 速记 */}
      <BottomPanel open={openPanel === 'notes'} onClose={() => setOpenPanel(null)} title="速记本">
        <div className="flex gap-2 mb-3">
          <button onClick={() => setNotes(prev => prev + `\n\n[🔍 新线索 ${new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})}]\n`)}
            className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium flex items-center justify-center gap-1 active:bg-border-light">
            <Plus className="w-3.5 h-3.5" /> 添加线索标签
          </button>
          <button onClick={() => {
              if (!notesKey) return
              localStorage.setItem(notesKey, notes)
              setLastSaved(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }))
            }}
            className="px-4 py-2 rounded-sm bg-brass text-white text-xs font-medium flex items-center justify-center gap-1 active:bg-brass-dark">
            <Save className="w-3.5 h-3.5" /> 保存
          </button>
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="📋 案件笔记"
          className="w-full min-h-[180px] text-sm leading-[1.7] text-text-body bg-input border border-border-light rounded-md px-3.5 py-3 resize-none outline-none focus:border-brass transition-colors font-mono placeholder:text-text-dim"
        />
        <div className="text-[10px] text-text-dim mt-2 text-right">{lastSaved ? `最后保存: ${lastSaved}` : '尚未保存'}</div>
      </BottomPanel>

      {/* Panel: 主持人语音 */}
      <BottomPanel open={openPanel === 'speech'} onClose={() => setOpenPanel(null)} title="主持人语音">
        {!hostSpeech.supported ? (
          <p className="text-sm text-text-dim py-6 text-center">
            当前浏览器不支持语音朗读，文本消息仍可正常使用
          </p>
        ) : (
          <div className="space-y-4">
            <label className="flex items-center justify-between gap-3">
              <span>
                <span className="block text-sm font-semibold text-text-primary">主持人语音朗读</span>
                <span className="block text-[11px] text-text-muted mt-0.5">新产生的最终主持人消息自动播放</span>
              </span>
              <input
                type="checkbox"
                role="switch"
                aria-label="主持人语音朗读"
                checked={hostSpeech.enabled}
                onChange={(event) => hostSpeech.setEnabled(event.target.checked)}
                className="h-5 w-9 accent-brass"
              />
            </label>

            <label className="block">
              <span className="block text-xs font-semibold text-text-muted mb-1.5">音色</span>
              <select
                aria-label="主持人音色"
                value={hostSpeech.selectedVoiceURI ?? ''}
                onChange={(event) => hostSpeech.setSelectedVoiceURI(event.target.value)}
                disabled={hostSpeech.voices.length === 0}
                className="w-full bg-input border border-border-light rounded-md px-3 py-2 text-sm text-text-primary disabled:opacity-50"
              >
                {hostSpeech.voices.length === 0 ? (
                  <option value="">正在加载音色…</option>
                ) : (
                  hostSpeech.voices.map((voice) => (
                    <option key={voice.voiceURI} value={voice.voiceURI}>
                      {voice.name} · {voice.lang}
                    </option>
                  ))
                )}
              </select>
            </label>

            <div className="flex items-center justify-between text-[11px] text-text-muted">
              <span>
                {hostSpeech.status === 'speaking' ? '正在朗读' : hostSpeech.status === 'paused' ? '已暂停' : '空闲'}
              </span>
              <span>待播放 {hostSpeech.queueLength} 条</span>
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                aria-label="暂停朗读"
                title="暂停朗读"
                onClick={hostSpeech.pause}
                disabled={hostSpeech.status !== 'speaking'}
                className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium flex items-center justify-center gap-1 disabled:opacity-40"
              >
                <Pause className="w-3.5 h-3.5" />
                暂停
              </button>
              <button
                type="button"
                aria-label="继续朗读"
                title="继续朗读"
                onClick={hostSpeech.resume}
                disabled={hostSpeech.status !== 'paused'}
                className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium flex items-center justify-center gap-1 disabled:opacity-40"
              >
                <Play className="w-3.5 h-3.5" />
                继续
              </button>
              <button
                type="button"
                aria-label="停止朗读"
                title="停止朗读"
                onClick={hostSpeech.stop}
                disabled={hostSpeech.status === 'idle' && hostSpeech.queueLength === 0}
                className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium flex items-center justify-center gap-1 disabled:opacity-40"
              >
                <Square className="w-3.5 h-3.5" />
                停止
              </button>
            </div>
          </div>
        )}
      </BottomPanel>

      {/* Panel: 房间成员 */}
      <BottomPanel open={openPanel === 'members'} onClose={() => setOpenPanel(null)} title="房间成员">
        {roomInfo ? (
          <div className="space-y-1.5">
            <p className="text-xs text-text-muted mb-2">{roomInfo.players.length}/{roomInfo.maxPlayers} 人</p>
            {roomInfo.players.map((p) => (
              <div key={p.playerId} className="flex items-center gap-3 px-3 py-2 bg-panel rounded-md">
                <div className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center text-sm flex-shrink-0">🔍</div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-text-primary">{p.nickname}</div>
                  <div className="text-[11px] text-text-dim">{p.isHost ? '房主' : '玩家'}{p.playerId === playerId ? ' · 你' : ''}</div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-text-dim py-6 text-center">正在获取房间成员…</p>
        )}

        {isHost && (
          <div className="mt-4 pt-4 border-t border-border-light">
            {endError && <p className="text-[11px] text-[#c04040] text-center mb-2">{endError}</p>}
            {confirmEnd ? (
              <div className="space-y-2">
                <p className="text-xs text-text-muted text-center">确定要结束本局游戏吗？结束后将无法再回到聊天室，只能在「我的游戏」里查看复盘。</p>
                <div className="flex gap-2">
                  <button onClick={() => setConfirmEnd(false)} disabled={ending}
                    className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium active:bg-border-light disabled:opacity-60">
                    取消
                  </button>
                  <button onClick={handleEndGame} disabled={ending}
                    className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium active:bg-[#a03030] disabled:opacity-60">
                    {ending ? '结束中…' : '确认结束'}
                  </button>
                </div>
              </div>
            ) : (
              <button onClick={() => setConfirmEnd(true)}
                className="w-full py-2 rounded-sm bg-transparent text-[#c04040] border border-[#c04040]/40 text-xs font-medium flex items-center justify-center gap-1.5 active:bg-[#c04040]/5">
                <FlagOff className="w-3.5 h-3.5" /> 结束游戏
              </button>
            )}
          </div>
        )}
      </BottomPanel>

      {/* ── Dice Modal ── */}
      <DiceModal
        open={showDice}
        onClose={() => setShowDice(false)}
        onResult={handleDiceResult}
        checkRequest={pendingCheck}
        checkDiceState={pendingCheckDice}
        setCheckDiceState={setPendingCheckDice}
      />
    </div>
  )
}

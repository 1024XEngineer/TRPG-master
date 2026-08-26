import { useNavigate } from 'react-router-dom'
import { RoomSocketServerError, TurnFailedError, type AdjudicationPendingPayload, type AgentPlayerView, type AgentTurnPhase, type CheckRequestPayload, type CheckResultPayload, type EndingDraft, type NarrationPushPayload, type RoomActionStatePayload, type RoomConversationEvent, type RoomPlayerSummary, type SceneTransitionPendingPayload, type TimeAdvancePendingPayload } from 'trpg-sdk'
import { ArrowLeft, Users, Map, MapPin, BookOpen, ScrollText, Star, X, SendHorizontal, Plus, Save, FlagOff, Heart, Brain, Volume2, Pause, Play, Square, RotateCcw, Mic, LoaderCircle, Clock3, Check } from 'lucide-react'
import { useCallback, useState, useRef, useEffect, useMemo, type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomCharacter } from '@/hooks/useRoomCharacter'
import { connectWebSocket, waitForWsOpen, sdk, onWsMessage, disconnectWebSocket, friendlyErrorMessage, getAuthToken } from '@/services/api-client'
import { confirmEndingDraft, createEndingDraft, endGame } from '@/services/room'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'
import { usePlayerPortraits } from '@/hooks/usePlayerPortraits'
import { useRuleset } from '@/hooks/useRuleset'
import { useHostSpeech } from '@/hooks/useHostSpeech'
import { useSpeechInput } from '@/hooks/useSpeechInput'
import { Dice3DStage, supports3DDice, type Dice3DHandle, type DiceRollToken } from '@/features/dice3d'
import { OnboardingTrigger } from '@/features/onboarding'
import { CheckWorkflowPanel } from '@/features/adjudication'
import { CharacterBasicInfo } from '@/features/character/CharacterBasicInfo'
import { PortraitGenerationModal } from '@/routes/character-ready/PortraitGenerationModal'
import { usePortraitGenerationStore } from '@/stores/portrait-generation-store'
import type {
  CheckRunView as UiCheckRunView,
  PendingCheckDecisionView as UiPendingCheckDecisionView,
} from '@/features/adjudication'
import './RoomPage.css'

function IsometricDiceIcon() {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
      <path d="M16 3 28 9.5 16 16 4 9.5 16 3Z" fill="#fff0c8" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M4 9.5 16 16v13L4 22.5v-13Z" fill="#d8a65c" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M28 9.5 16 16v13l12-6.5v-13Z" fill="#b87935" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx="16" cy="9.4" r="1.45" fill="currentColor" />
      <circle cx="8.3" cy="14" r="1.25" fill="currentColor" />
      <circle cx="11.7" cy="22.7" r="1.25" fill="currentColor" />
      <circle cx="23.7" cy="14" r="1.25" fill="#fff0c8" />
      <circle cx="20.3" cy="22.7" r="1.25" fill="#fff0c8" />
    </svg>
  )
}

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

function skillPillColors(value: number) {
  const ratio = Math.min(100, Math.max(0, value)) / 100
  return {
    backgroundColor: `hsl(36 52% ${92 - ratio * 22}%)`,
    borderColor: `hsl(31 45% ${72 - ratio * 22}%)`,
  }
}

function pendingDecisionForUi(
  pending: AdjudicationPendingPayload | null,
): UiPendingCheckDecisionView | null {
  const decision = pending?.pendingDecision
  if (!decision) return null
  return {
    ...decision,
    status: decision.status ?? 'awaiting_skill_choice',
    allow_cancel: decision.allow_cancel ?? true,
  }
}

function checkRunForUi(
  pending: AdjudicationPendingPayload | null,
): UiCheckRunView | null {
  const checkRun = pending?.checkRun
  if (!checkRun) return null
  return {
    ...checkRun,
    final_result: checkRun.final_result ?? null,
    post_roll_options: (checkRun.post_roll_options ?? []).map((option) => {
      if ('resource_id' in option) {
        return {
          ...option,
          kind: 'spend_resource' as const,
          resource_id: 'luck' as const,
        }
      }
      if ('requires_revised_method' in option) {
        return {
          ...option,
          kind: 'push' as const,
          requires_revised_method: true as const,
        }
      }
      return { ...option, kind: 'accept_result' as const }
    }),
  }
}

const checkResultLevelLabels: Record<string, string> = {
  critical: '大成功',
  extreme: '极难成功',
  hard: '困难成功',
  regular: '成功',
  failure: '失败',
  fumble: '大失败',
}

const checkDifficultyLabels: Record<string, string> = {
  regular: '常规',
  hard: '困难',
  extreme: '极难',
}

function checkResultContent(payload: CheckResultPayload): string {
  const levelLabel = checkResultLevelLabels[payload.successLevel] ?? payload.result
  const outcomeLabel = payload.passed
    ? levelLabel
    : `${levelLabel}（未通过${checkDifficultyLabels[payload.difficulty] ?? ''}检定）`
  const resolutionLabel =
    payload.resolutionKind === 'spend_luck' && payload.luckSpent
      ? ` · 消耗 ${payload.luckSpent} 点幸运 → ${outcomeLabel}`
      : ` · ${outcomeLabel}`
  return `${payload.skillName} ${payload.targetValue}% · D100 ${payload.rollValue}${resolutionLabel}`
}

function hostUtteranceFromActionInput(text: string): string | null {
  if (!text.includes('@主持人')) return null
  const rest = text.split('@主持人').join(' ').replace(/\s+/g, ' ').trim()
  return rest.length > 0 ? rest : null
}

const HOST_MENTION_LONG_PRESS_MS = 450

function KeeperAvatar({ onLongPress }: { onLongPress: () => void }) {
  const timerRef = useRef<number | null>(null)

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  useEffect(() => clearTimer, [])

  return (
    <button
      type="button"
      aria-label="长按 @主持人"
      className="room-play__avatar room-play__avatar--keeper"
      onPointerDown={() => {
        clearTimer()
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null
          onLongPress()
        }, HOST_MENTION_LONG_PRESS_MS)
      }}
      onPointerUp={clearTimer}
      onPointerCancel={clearTimer}
      onPointerLeave={clearTimer}
      onContextMenu={(event) => event.preventDefault()}
    >
      <img src="/assets/rooms/play/keeper-cat.webp" alt="" aria-hidden="true" draggable={false} />
    </button>
  )
}

// ─── Types ───────────────────────────────────────────
interface Message {
  type: 'system' | 'narr' | 'player' | 'dice'
  channel?: 'action' | 'discussion'
  messageId?: string
  narrationId?: string
  sender?: string
  content: string
  time: string
  isSelf?: boolean
  playerId?: string
}

const EMPTY_ROOM_PLAYERS: RoomPlayerSummary[] = []

interface MapLocation {
  id: string
  icon: string
  name: string
  desc: string
  depth: number
  access?: 'unknown' | 'reachable' | 'blocked'
  visited?: boolean
  isCurrent?: boolean
}

const LOCATION_IMAGE_BY_ID: Record<string, string> = {
  arnoldsburg_streets: '/assets/rooms/play/location-arnoldsburg-streets.webp',
  thomas_office: '/assets/rooms/play/location-thomas-office.webp',
  neighborhood: '/assets/rooms/play/location-neighborhood.webp',
  cemetery: '/assets/rooms/play/location-cemetery.webp',
  library: '/assets/rooms/play/location-library.webp',
  newspaper_office: '/assets/rooms/play/location-newspaper-office.webp',
  surveillance_point: '/assets/rooms/play/location-surveillance-point.webp',
  kimball_study: '/assets/rooms/play/location-kimball-study.webp',
}

function mapLocationsFromPlayerView(playerView: AgentPlayerView | null): MapLocation[] {
  if (!playerView) {
    return [{
      id: 'waiting-for-view',
      icon: '📍',
      name: '等待场景同步',
      desc: '进入游戏后由规则引擎提供当前位置',
      depth: 0,
      isCurrent: true,
    }]
  }
  if (playerView.known_locations && playerView.known_locations.length > 0) {
    const locations = playerView.known_locations
    const knownIds = new Set(locations.map((location) => location.id))
    const children = new globalThis.Map<string | null, typeof locations>()
    for (const location of locations) {
      const parentId = location.parent_location_id && knownIds.has(location.parent_location_id)
        ? location.parent_location_id
        : null
      children.set(parentId, [...(children.get(parentId) ?? []), location])
    }
    const ordered: MapLocation[] = []
    const visited = new Set<string>()
    const walk = (parentId: string | null, depth: number) => {
      for (const location of children.get(parentId) ?? []) {
        if (visited.has(location.id)) continue
        visited.add(location.id)
        const isCurrent = location.id === playerView.scene.id
        const status = location.access === 'blocked'
          ? '路线受阻'
          : location.localization !== 'located'
            ? '位置尚未确认'
            : location.visited
              ? '已到访'
              : '已知地点'
        ordered.push({
          id: location.id,
          icon: isCurrent
            ? '📍'
            : location.kind === 'region'
              ? '🗺️'
              : location.kind === 'connector'
                ? '🛣️'
                : location.kind === 'room'
                  ? '🚪'
                  : '🏛️',
          name: location.name,
          desc: isCurrent
            ? playerView.scene.description || '当前所在场景'
            : location.description || status,
          depth,
          access: location.access,
          visited: location.visited,
          isCurrent,
        })
        walk(location.id, depth + 1)
      }
    }
    walk(null, 0)
    // Malformed/cyclic hierarchy must not make a known location disappear.
    for (const location of locations) {
      if (!visited.has(location.id)) {
        children.set(null, [location])
        walk(null, 0)
      }
    }
    return ordered
  }
  const current: MapLocation = {
    id: playerView.scene.id,
    icon: '📍',
    name: playerView.scene.name,
    desc: playerView.scene.description || '当前所在场景',
    depth: 0,
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
      depth: 0,
    }]
  })
  return [current, ...exits]
}

const PHASE_LABELS: Record<AgentTurnPhase, string> = {
  reading_player_view: '守秘人理解玩家意图中',
  understanding_action: '守秘人理解玩家意图中',
  waiting_for_check: '守秘人等待玩家掷骰子',
  executing_action: '守秘人组织语言中',
  refreshing_player_view: '守秘人组织语言中',
  generating_narration: '守秘人组织语言中',
}

const ORGANIZING_PHASE_MIN_MS = 600

const TIME_OF_DAY_LABELS = { day: '白天', night: '夜晚' } as const

/**
 * 3D 掷骰从受理到定格的上限。超过就退回 2D 把这次掷骰补完。
 *
 * 必须明显高于动画自身的封顶：引擎是 MAX_TUMBLE_SECONDS 4.5s + SETTLE 0.55s
 * ≈ 5.05s，再加上第一次掷骰要现拉懒加载 chunk。上一版取 6s，正好卡在这个和
 * 之间，于是正常的掷骰被当成卡死，动画被误杀成 2D。这里留足余量——它是防
 * 死锁的兜底，不是性能预算，宁可晚一点也不能误伤。
 */
const DICE_3D_SETTLE_TIMEOUT_MS = 15000

/** Render the Engine's authoritative discrete world-time point. */
function formatWorldTime(dayIndex: number, hourOfDay: number): string {
  return `第 ${dayIndex + 1} 天 ${String(hourOfDay).padStart(2, '0')}:00`
}

/**
 * PlayerView 的当前资源，按小写 id 索引，供角色卡面板显示活的 HP/SAN/MP/幸运。
 *
 * 顶部状态栏一直读 PlayerView，角色卡面板读的却是建卡快照，同一页的同名数值
 * 于是对不上（issue #286）。两处现在共用这同一份投影。
 */
function liveResourcesOf(playerView: AgentPlayerView | null): Record<string, number> {
  const resources: Record<string, number> = {}
  for (const item of playerView?.self_actor.resources ?? []) {
    if (typeof item.value !== 'number' || !Number.isFinite(item.value)) continue
    // id 与 name 都建索引，和 `resourceValue` 的匹配口径保持一致：否则顶部
    // 状态栏能按 name 命中的资源，面板会按 id 找不到，又变回两个数。
    resources[item.id.toLocaleLowerCase()] = item.value
    resources[item.name.toLocaleLowerCase()] = item.value
  }
  return resources
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

/** 保留玩家已有输入；只有两段之间没有空白或句末标点时才补一个空格。 */
export function appendSpeechTranscript(current: string, transcript: string): string {
  const normalized = transcript.trim()
  if (!normalized) return current
  if (!current) return normalized
  const needsSeparator = !/[\s，。！？；：、,.!?;:]$/u.test(current)
  return `${current}${needsSeparator ? ' ' : ''}${normalized}`
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
      playerId: payload.playerId,
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
      playerId: payload.playerId,
    }
  }
  if (event.type === 'narration.push') {
    const payload = event.payload as { messageId?: string | null; text: string }
    const narrationId = payload.messageId || event.id
    return {
      type: 'narr',
      channel: 'action',
      messageId: conversationMessageId(event.type, narrationId),
      narrationId,
      sender: '守秘人',
      content: payload.text,
      time: formatRoomTime(event.createdAt),
    }
  }
  if (event.type === 'check.result') {
    const payload = event.payload as unknown as CheckResultPayload
    return {
      type: 'dice',
      channel: 'action',
      messageId: conversationMessageId(event.type, event.id),
      sender: displayName(
        payload.characterName,
        payload.playerId === selfPlayerId ? senderName : null,
      ),
      content: checkResultContent(payload),
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
  result: number | null
  rolling: boolean
  showResult: boolean
  tens: number
  ones: number
  submitted: boolean
}

type AuthoritativeDiceRoll = {
  correlationId: string
  checkId: string
  rollCount: number
  value: number
  degree: UiCheckRunView['roll']['degree']
}

function createPendingCheckDiceState(checkRequest: CheckRequestPayload): PendingCheckDiceState {
  return {
    clientActionId: checkRequest.clientActionId,
    selectedSkillId: checkRequest.skills[0]?.id ?? null,
    result: null,
    rolling: false,
    showResult: false,
    tens: 0,
    ones: 0,
    submitted: false,
  }
}

/** D100 结果拆成十位/个位用于展示。100 由「00 + 0」得来，两位都是 0。 */
function splitD100(value: number): { tens: number; ones: number } {
  if (value === 100) return { tens: 0, ones: 0 }
  return { tens: Math.floor(value / 10), ones: value % 10 }
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
function BottomPanel({ open, onClose, title, children, heightVh, className = '' }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; heightVh?: number; className?: string }) {
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
        className={`room-play__bottom-panel ${className} fixed bottom-0 left-0 right-0 z-50 bg-card rounded-t-2xl shadow-xl transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] max-w-[430px] mx-auto ${open ? 'translate-y-0' : 'translate-y-full'}`}
        style={heightVh ? { height: `${maxH}vh` } : { maxHeight: `${maxH}vh` }}
      >
        <div className="flex flex-col items-center pt-2.5 pb-0 cursor-pointer" onClick={onClose}>
          <div className="w-9 h-1 rounded-full bg-border-mid" />
        </div>
        <div className="room-play__bottom-panel-header px-5 pt-2 pb-3">
          <h3 className="room-play__bottom-panel-title text-base font-bold text-text-primary">{title}</h3>
          <button aria-label="关闭面板" onClick={onClose} className="room-play__bottom-panel-close w-7 h-7 rounded-full bg-panel flex items-center justify-center active:scale-90 transition-transform">
            <X className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
          </button>
        </div>
        <div className="room-play__bottom-panel-content overflow-y-auto px-5 pb-6" style={{ maxHeight: `calc(${maxH}vh - 60px)` }}>
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
export function DiceModal({
  open,
  onClose,
  onResult,
  checkRequest,
  checkDiceState,
  setCheckDiceState,
  presetResult = null,
  presetDegree = null,
  autoRollKey,
  postRollOptions = [],
  luckValue = null,
  onPostRollOption,
  sequentialTargets,
  onSequentialRoll,
}: {
  open: boolean
  onClose: () => void
  onResult: (result: number, diceType: DiceType, skillId?: string) => void
  checkRequest: CheckRequestPayload | null
  checkDiceState: PendingCheckDiceState | null
  setCheckDiceState: Dispatch<SetStateAction<PendingCheckDiceState | null>>
  presetResult?: number | null
  presetDegree?: UiCheckRunView['roll']['degree'] | null
  autoRollKey?: string
  postRollOptions?: UiCheckRunView['post_roll_options']
  luckValue?: number | null
  onPostRollOption?: (optionId: string, revisedMethod?: string) => void
  /** 连续骰模式：复用同一骰盘逐颗展示服务端已经确定的目标点数。 */
  sequentialTargets?: number[]
  onSequentialRoll?: (value: number, index: number) => void
}) {
  const [freeDiceType, setFreeDiceType] = useState<DiceType>('d100')
  const [freeResult, setFreeResult] = useState<number | null>(null)
  const [freeRolling, setFreeRolling] = useState(false)
  const [freeShowResult, setFreeShowResult] = useState(false)
  const [freeTens, setFreeTens] = useState(0)
  const [freeOnes, setFreeOnes] = useState(0)
  const [revisedMethod, setRevisedMethod] = useState('')
  const [sequentialIndex, setSequentialIndex] = useState(0)
  const submitLockRef = useRef(false)
  const dice3dRef = useRef<Dice3DHandle>(null)
  const rollGenerationRef = useRef(0)
  // 3D 不可用（无 WebGL / 用户要求减少动效 / 引擎加载失败）时退回原来的 2D 展示。
  // 检定是主流程的一环，不能因为渲染能力缺失就卡住。
  const [use3D, setUse3D] = useState(() => supports3DDice())

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
      setFreeResult(null)
      setFreeRolling(false)
      setFreeShowResult(false)
      setFreeTens(0)
      setFreeOnes(0)
      setSequentialIndex(0)
      submitLockRef.current = false
    }
  }, [open, checkRequest])

  const isCheckMode = Boolean(checkRequest)
  const isSequentialMode = Boolean(sequentialTargets?.length)
  const sequentialTarget = isSequentialMode ? sequentialTargets?.[sequentialIndex] ?? null : null
  const activePresetResult = isSequentialMode ? sequentialTarget : presetResult
  const activeCheckDice = checkRequest ? checkDiceState : null
  const activeDiceType: DiceType = isCheckMode ? 'd100' : isSequentialMode ? 'd6' : freeDiceType
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

  /**
   * 已经交给 3D、但还没定格的那次掷骰。
   *
   * 用 ref 而不是读 state：3D 失败回调可能与 `roll()` 在同一个同步流程里发生，
   * 那时 `rolling` 的 setState 还没生效，读 state 会拿到旧值、判断成"没有掷骰
   * 在进行"，等于没修。
   */
  const inFlight3DRollRef = useRef<{
    requestId: string | null
    token: DiceRollToken
  } | null>(null)

  /**
   * 3D 接了这次掷骰、但迟迟不定格时的兜底闹钟。
   *
   * `roll()` 返回 true 只代表舞台受理了，不代表它一定会回调：懒加载 chunk 可能
   * 卡住、WebGL 上下文可能丢失、标签页切到后台会让 rAF 整个暂停。这些情况下
   * `onSettled` 永远不来，rolling 永远不清，检定就死在"骰子还在滚"。
   */
  const watchdog3DRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const clear3DWatchdog = useCallback(() => {
    if (watchdog3DRef.current === null) return
    clearTimeout(watchdog3DRef.current)
    watchdog3DRef.current = null
  }, [])

  /** 结果落地：3D 由动画定格回调进来，2D 由本地随机 + 定时器进来，两条路共用。 */
  const settle = (value: number, requestId: string | null) => {
    clear3DWatchdog()
    inFlight3DRollRef.current = null
    const settledValue = activePresetResult ?? value
    const { tens, ones } = activeDiceType === 'd100' ? splitD100(settledValue) : { tens: 0, ones: 0 }
    if (requestId !== null) {
      setCheckDiceState((current) => {
        if (!current || current.clientActionId !== requestId) return current
        return { ...current, result: settledValue, showResult: true, rolling: false, tens, ones }
      })
      return
    }
    setFreeTens(tens)
    setFreeOnes(ones)
    setFreeResult(settledValue)
    setFreeShowResult(true)
    setFreeRolling(false)
  }

  const currentRequestId = () => (isCheckMode ? checkRequest?.clientActionId ?? null : null)

  const resetRolling = useCallback((requestId: string | null) => {
    if (requestId === null) {
      setFreeRolling(false)
      return
    }
    setCheckDiceState((current) => {
      if (!current || current.clientActionId !== requestId) return current
      return { ...current, rolling: false }
    })
  }, [setCheckDiceState])

  /** 2D 回退掷骰：本地随机 + 固定时长的假动画，与改造前一致。 */
  const roll2D = (requestId: string | null) => {
    let finalResult: number
    if (activePresetResult !== null) {
      finalResult = activePresetResult
    } else if (activeDiceType === 'd100') {
      const tens = Math.floor(Math.random() * 10)
      const ones = Math.floor(Math.random() * 10)
      finalResult = tens * 10 + ones
      if (finalResult === 0) finalResult = 100
    } else if (activeDiceType === 'd20') {
      finalResult = Math.floor(Math.random() * 20) + 1
    } else {
      finalResult = Math.floor(Math.random() * 6) + 1
    }
    setTimeout(() => settle(finalResult, requestId), 700)
  }

  /**
   * 给一次已被 3D 受理的掷骰装上兜底：超时未定格就退回 2D 把它补完。
   *
   * 走 `handle3DUnsupported` 而不是直接 `roll2D`，是为了和真正的 3D 失败共用
   * 同一条降级路径——它会一并翻掉 use3D，避免后续每一次检定都再等一轮超时。
   */
  /**
   * 这一次 3D 掷骰不会定格了，用 2D 把它补完 —— 但**保留** 3D 能力。
   *
   * 和 handle3DUnsupported 的区别就在最后半句：超时、舞台被卸载都只是这一次
   * 的意外（chunk 慢、玩家中途关了弹窗），不等于这台设备用不了 3D。之前两条
   * 路都走 setUse3D(false)，于是任何一次误判都会把之后每一次检定永久降级成
   * 只有数字的版本。
   */
  const finish3DRollWithout3D = (token: DiceRollToken) => {
    const pending = inFlight3DRollRef.current
    if (pending?.token !== token) return
    clear3DWatchdog()
    inFlight3DRollRef.current = null
    roll2D(pending.requestId)
  }

  const arm3DWatchdog = (token: DiceRollToken) => {
    clear3DWatchdog()
    watchdog3DRef.current = setTimeout(() => {
      watchdog3DRef.current = null
      finish3DRollWithout3D(token)
    }, DICE_3D_SETTLE_TIMEOUT_MS)
  }

  const roll = () => {
    const requestId = currentRequestId()
    if (isCheckMode) {
      if (!checkRequest || !activeCheckDice || activeCheckDice.result !== null || activeCheckDice.submitted || activeCheckDice.rolling) return
      updateCheckDiceState((current) => ({ ...current, rolling: true, showResult: false }))
    } else {
      if (freeRolling) return
      setFreeRolling(true)
      setFreeShowResult(false)
    }

    // 自由掷骰读取物理定格后的朝上面；检定使用服务端已持久化的权威结果，
    // 只让 3D 引擎把对应面平滑定格，客户端不会生成第二个检定结果。
    if (use3D) {
      const stage = dice3dRef.current
      const token = `${requestId ?? 'free'}:${++rollGenerationRef.current}`
      inFlight3DRollRef.current = { requestId, token }
      if (stage === null) {
        // 舞台根本没挂载，这次掷骰不可能有动画，用 2D 补完它而不是留个死胡同。
        inFlight3DRollRef.current = null
        roll2D(requestId)
        return
      }
      if (!stage.roll(token, activePresetResult ?? undefined)) {
        // 舞台在，只是还占着上一次掷骰。掷骰现在一律由玩家点击触发，所以清掉
        // rolling 让按钮重新可用就够了——不要退回 2D，那会把玩家想看的动画
        // 悄悄换成一个直接蹦出来的数字。
        inFlight3DRollRef.current = null
        resetRolling(requestId)
        return
      }
      arm3DWatchdog(token)
      return
    }
    roll2D(requestId)
  }

  /**
   * 检定由玩家点「掷骰」触发，和左下角的自由投掷完全同一条路径。
   *
   * 这里曾经在弹窗打开的同一个 commit 里自动掷骰。那一刻 3D 舞台刚挂载、懒加载
   * chunk 还没回来，握手常常拿不到引擎，于是整次掷骰退回 2D——玩家看到的就是
   * 「选完技能它自己跳到结果，没有动画」。骰点本来就由服务端决定，动画只是把
   * 这个结果演出来，所以让玩家自己点、在舞台就绪之后再跑，既拿回了动画也拿回
   * 了掷骰的仪式感。
   */
  useEffect(() => {
    setRevisedMethod('')
  }, [autoRollKey])

  /**
   * 3D 不可用。可能在掷骰之前（环境不支持），也可能在掷骰之后——懒加载 chunk
   * 是一个网络请求，移动端抖一下就会失败。
   *
   * 后者必须把这一次掷骰补完：`roll()` 已经置了 rolling 并走 3D 分支返回，没有
   * 排任何定时器。只翻 use3D 的话 rolling 永远不清，检定会卡在"骰子还在滚"，
   * 既没有结果也没有重掷入口——恰好是这套降级本该防住的情况（PR #219 review）。
   */
  const handle3DUnsupported = (token: DiceRollToken | null) => {
    const pending = inFlight3DRollRef.current
    if (token !== null && pending?.token !== token) return
    clear3DWatchdog()
    inFlight3DRollRef.current = null
    setUse3D(false)
    if (pending) roll2D(pending.requestId)
  }

  const handle3DSettled = (value: number, token: DiceRollToken) => {
    const pending = inFlight3DRollRef.current
    if (!pending || pending.token !== token) return
    clear3DWatchdog()
    inFlight3DRollRef.current = null
    if (pending.requestId !== currentRequestId()) return
    settle(value, pending.requestId)
  }

  useEffect(() => {
    if (open) return
    clear3DWatchdog()
    const pending = inFlight3DRollRef.current
    if (!pending) return
    inFlight3DRollRef.current = null
    resetRolling(pending.requestId)
  }, [open, resetRolling, clear3DWatchdog])

  // 组件卸载时别把闹钟留在后台。
  useEffect(() => clear3DWatchdog, [clear3DWatchdog])

  const canRoll = !activeRolling && !activeShowResult && activeResult === null && !activeCheckDice?.submitted

  const confirmResult = () => {
    if (isSequentialMode) {
      if (activeResult === null) return
      onSequentialRoll?.(activeResult, sequentialIndex)
      if (sequentialIndex >= (sequentialTargets?.length ?? 1) - 1) {
        onClose()
      } else {
        setSequentialIndex(index => index + 1)
        setFreeResult(null)
        setFreeShowResult(false)
        setFreeRolling(false)
      }
      return
    }
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

  const submitPostRollOption = (optionId: string, method?: string) => {
    if (
      presetResult === null ||
      !checkRequest ||
      !activeCheckDice ||
      activeResult === null ||
      !onPostRollOption ||
      submitLockRef.current ||
      activeCheckDice.submitted
    ) {
      return
    }
    submitLockRef.current = true
    setCheckDiceState((current) => {
      if (!current || current.clientActionId !== checkRequest.clientActionId) return current
      return { ...current, submitted: true }
    })
    onPostRollOption(optionId, method)
    onClose()
  }

  const renderDiceDisplay = () => {
    if (use3D && open) {
      return (
        <Dice3DStage
          key={checkRequest?.clientActionId ?? `free-${activeDiceType}`}
          ref={dice3dRef}
          kind={activeDiceType}
          className="w-full h-48"
          onSettled={handle3DSettled}
          onUnsupported={handle3DUnsupported}
          onRollAbandoned={finish3DRollWithout3D}
        />
      )
    }
    const glow = activeRolling ? 'opacity-40' : ''
    return (
      <div className={`relative w-full h-48 flex items-center justify-center select-none ${glow}`}>
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
            className="text-[64px] font-bold font-mono text-[#eeead8] transition-transform duration-150"
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
    if (presetDegree !== null) {
      const labels: Record<UiCheckRunView['roll']['degree'], string> = {
        critical_success: '大成功',
        extreme_success: '极难成功',
        hard_success: '困难成功',
        regular_success: '成功',
        failure: '失败',
        fumble: '大失败',
      }
      return {
        label: labels[presetDegree],
        color:
          presetDegree === 'failure' || presetDegree === 'fumble'
            ? DIFFICULTY_COLORS.fail
            : DIFFICULTY_COLORS.success,
      }
    }
    if (activeResult === 1) return { label: '大成功', color: DIFFICULTY_COLORS.crit }
    if (activeResult <= Math.floor(targetValue / 5)) return { label: '极难成功', color: DIFFICULTY_COLORS.success }
    if (activeResult <= Math.floor(targetValue / 2)) return { label: '困难成功', color: DIFFICULTY_COLORS.success }
    if (activeResult <= targetValue) return { label: '成功', color: DIFFICULTY_COLORS.success }
    return { label: '失败', color: DIFFICULTY_COLORS.fail }
  }

  const verdict = getVerdict()
  const acceptOption = postRollOptions.find((option) => option.kind === 'accept_result')
  const alternativeOptions = postRollOptions.filter(
    (option) => option.kind !== 'accept_result',
  )
  const spendLuckOption = alternativeOptions.find(
    (option) => option.kind === 'spend_resource',
  )
  const difficultyTarget = checkRequest
    ? checkRequest.difficulty === 'hard'
      ? Math.floor(targetValue / 2)
      : checkRequest.difficulty === 'extreme'
        ? Math.floor(targetValue / 5)
        : targetValue
    : targetValue
  const neededLuck = activeResult === null
    ? null
    : Math.max(0, activeResult - difficultyTarget)
  const unavailableLuckLabel =
    presetResult === null ||
    activeResult === null ||
    spendLuckOption ||
    neededLuck === null ||
    neededLuck <= 0
      ? null
      : presetDegree === 'fumble'
        ? '大失败无法消耗幸运'
        : luckValue === null
          ? `需要 ${neededLuck} 点幸运；当前幸运值不可用`
          : luckValue < neededLuck
            ? `幸运不足：需要 ${neededLuck} 点，当前 ${luckValue} 点`
            : '本次检定规则不允许消耗幸运'

  return (
    <BottomPanel
      open={open}
      onClose={onClose}
      title="骰子检定"
      className="room-play__bottom-panel--dice"
    >
      {!isCheckMode && !isSequentialMode && (
        <div className="flex gap-1.5 mb-3.5">
          {DICE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              onClick={() => {
                if (!freeRolling) {
                  setFreeDiceType(opt.id)
                  setFreeResult(null)
                  setFreeShowResult(false)
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
        className="rounded-md px-4 pt-5 pb-4 flex flex-col items-center relative overflow-hidden"
        style={{
          // 暖调骰盘而不是冷近黑：骰子是亮面树脂材质，深底才有对比；
          // 中心略亮、边缘压暗，配合内阴影读起来像一个打着光的托盘。
          background:
            'radial-gradient(120% 95% at 50% 30%, #3d3327 0%, #262019 55%, #171310 100%)',
          boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.06), inset 0 -14px 28px rgba(0,0,0,0.45)',
        }}
      >
        {renderDiceDisplay()}

        {canRoll && (
          <button
            type="button"
            onClick={roll}
            className="mt-3 px-8 py-2.5 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark active:scale-[0.97] transition-all"
          >
            掷骰
          </button>
        )}

        {activeRolling && (
          <div className="text-center mt-3 text-xs text-[#9088a0] animate-pulse">
            🎲 骰子还在滚……
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
            {!isSequentialMode && presetResult !== null && (
              <p className="mt-1 text-[11px] text-text-muted">
                骰点已保存；刷新或重试不会重新投掷
              </p>
            )}
          </div>

          {!isSequentialMode && presetResult !== null && acceptOption ? (
            <div className="w-full space-y-2">
              <button
                type="button"
                onClick={() => submitPostRollOption(acceptOption.option_id)}
                disabled={!!activeCheckDice?.submitted}
                className="w-full py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark active:scale-[0.97] transition-all disabled:opacity-60"
              >
                接受结果并发送
              </button>
              {unavailableLuckLabel && (
                <button
                  type="button"
                  disabled
                  className="w-full rounded-sm border border-border-light bg-panel py-2.5 text-sm font-semibold text-text-muted opacity-70"
                >
                  {unavailableLuckLabel}
                </button>
              )}
              {alternativeOptions.map((option) => (
                <div key={option.option_id} className="rounded-lg border border-border-light bg-panel p-3">
                  {option.kind === 'push' && (
                    <>
                      <label
                        htmlFor={`dice-push-method-${autoRollKey ?? 'current'}`}
                        className="mb-1 block text-xs font-medium text-text-primary"
                      >
                        说明改变后的做法
                      </label>
                      <textarea
                        id={`dice-push-method-${autoRollKey ?? 'current'}`}
                        value={revisedMethod}
                        disabled={!!activeCheckDice?.submitted}
                        onChange={(event) => setRevisedMethod(event.target.value)}
                        placeholder="例如：先缩小范围，再重新尝试"
                        className="mb-2 min-h-16 w-full rounded-lg border border-border-light bg-white p-2 text-xs"
                      />
                      <p className="mb-2 text-[11px] text-[#9b3f35]">
                        {option.player_safe_risk_summary}
                      </p>
                    </>
                  )}
                  <button
                    type="button"
                    disabled={
                      !!activeCheckDice?.submitted ||
                      (option.kind === 'push' && !revisedMethod.trim())
                    }
                    onClick={() =>
                      submitPostRollOption(
                        option.option_id,
                        option.kind === 'push' ? revisedMethod.trim() : undefined,
                      )
                    }
                    className="w-full rounded-sm border border-brass bg-white py-2.5 text-sm font-semibold text-brass-dark active:bg-brass/10 disabled:opacity-50"
                  >
                    {option.kind === 'spend_resource'
                      ? `消耗 ${option.cost} 点幸运${luckValue === null ? '' : `（当前 ${luckValue} 点）`}并发送`
                      : '强推一次'}
                  </button>
                </div>
              ))}
            </div>
          ) : (
            <button
              onClick={confirmResult}
              disabled={isCheckMode && !!activeCheckDice?.submitted}
              className="w-full py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark active:scale-[0.97] transition-all disabled:opacity-60"
            >
              {isSequentialMode
                ? sequentialIndex >= (sequentialTargets?.length ?? 1) - 1 ? '确认幸运值' : '继续投骰'
                : '确认并发送'}
            </button>
          )}
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
  const characterId = useRoomStore((s) => s.characterId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const nickname = useAuthStore((s) => s.nickname)
  // 以后端为准，本地缓存只作首屏占位。原来这里只读 useCharacterStore，而那个
  // store 全仓库只有建卡向导的两处提交会写——任何绕开向导的建卡路径（#337 的
  // 「从卡库选卡」就是一条）在准备页看着正常，进游戏这个面板就是空的。
  const { character } = useRoomCharacter()
  const senderName = character?.info.name || nickname || '你'
  const { ruleset } = useRuleset()
  const roomInfo = useRoomPlayers(roomCode)
  const roomPlayers = roomInfo?.players ?? EMPTY_ROOM_PLAYERS
  const portraitVersionOverride = usePortraitGenerationStore((s) => roomId ? s.portraitVersions[roomId] : undefined)
  const clearPortraitVersion = usePortraitGenerationStore((s) => s.clearPortraitVersion)
  const portraitPlayers = useMemo(() => roomPlayers.map((player) => player.playerId === playerId && portraitVersionOverride
    ? { ...player, hasPortrait: true, portraitVersion: portraitVersionOverride } : player), [roomPlayers, playerId, portraitVersionOverride])
  const portraitUrls = usePlayerPortraits(roomId, reconnectToken, portraitPlayers)
  useEffect(() => {
    const current = roomPlayers.find((player) => player.playerId === playerId)
    if (roomId && portraitVersionOverride && current?.portraitVersion === portraitVersionOverride) {
      clearPortraitVersion(roomId)
    }
  }, [roomId, playerId, roomPlayers, portraitVersionOverride, clearPortraitVersion])
  const hostSpeech = useHostSpeech({ roomId, reconnectToken, accountToken: getAuthToken() })
  const enqueueHostSpeech = hostSpeech.enqueue
  const markHostSpeechSeen = hostSpeech.markSeen
  const handleHostSpeechSettingsUpdated = hostSpeech.handleSettingsUpdated
  const isHost = roomInfo?.players.find((p) => p.playerId === playerId)?.isHost ?? false
  const [roomPhase, setRoomPhase] = useState<string | null>(null)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [ending, setEnding] = useState(false)
  const [endingDraft, setEndingDraft] = useState<EndingDraft | null>(null)
  const endingDraftRequestId = useRef(randomActionId())
  const endingConfirmRequestId = useRef(randomActionId())
  const [endError, setEndError] = useState('')
  const [confirmExit, setConfirmExit] = useState(false)
  const [showPortraitGenerator, setShowPortraitGenerator] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [channel, setChannel] = useState<'action' | 'discussion'>('action')
  const isActionChannel = channel === 'action'
  /**
   * 草稿按频道各存各的（issue #304）。
   *
   * 输入框在两个频道复用，但一份共享草稿会跟着频道漂移：在讨论区打了一半、
   * 检定到达把频道切回行动区，那段本来要说给队友听的话再一按发送就提交给了
   * 引擎——`sendMessage` 只看当前 `channel` 决定走 sendChat 还是提交行动。
   * 手动切频道同样漏，只是自动切换让它在玩家毫无预期时发生。
   */
  const [drafts, setDrafts] = useState<Record<'action' | 'discussion', string>>({
    action: '',
    discussion: '',
  })
  const input = drafts[channel]
  const setInput = useCallback(
    (next: string | ((current: string) => string)) => {
      setDrafts((current) => ({
        ...current,
        [channel]: typeof next === 'function' ? next(current[channel]) : next,
      }))
    },
    [channel],
  )
  const handleSpeechTranscript = useCallback((transcript: string) => {
    // 使用函数式更新读取回调到达那一刻的输入，避免覆盖识别期间玩家新键入的文字。
    setInput((current) => appendSpeechTranscript(current, transcript))
  }, [setInput])
  const speechInput = useSpeechInput(handleSpeechTranscript)
  // 单独取稳定方法，避免 effect 依赖每次渲染都会新建的 Hook 返回对象。
  const cancelSpeechInput = speechInput.cancel
  const [typing, setTyping] = useState(false)
  const [pendingAction, setPendingAction] = useState<{ clientActionId: string; utterance: string } | null>(null)
  const [pendingCheck, setPendingCheck] = useState<CheckRequestPayload | null>(null)
  const [pendingAdjudication, setPendingAdjudication] =
    useState<AdjudicationPendingPayload | null>(null)
  const [pendingTimeAdvance, setPendingTimeAdvance] =
    useState<TimeAdvancePendingPayload | null>(null)
  const [pendingSceneTransition, setPendingSceneTransition] =
    useState<SceneTransitionPendingPayload | null>(null)
  const [roomActionState, setRoomActionState] = useState<RoomActionStatePayload | null>(null)
  const [timeAdvanceResponding, setTimeAdvanceResponding] = useState(false)
  const selectedAdjudicationOptionRef = useRef<{
    correlationId: string
    option: UiPendingCheckDecisionView['options'][number]
  } | null>(null)
  const shownAdjudicationRollRef = useRef<string | null>(null)
  const [authoritativeDiceRoll, setAuthoritativeDiceRoll] =
    useState<AuthoritativeDiceRoll | null>(null)
  /**
   * 收起已经结算完的检定面板。
   *
   * 单动作（不属于任何 ActionPlan）走完检定后不会有 plan.* 事件，而
   * `turn.completed` 被 SDK 用来兑现 submit 的 Promise、不会转发给订阅者——
   * 于是"服务端 D100 · 失败"那块面板会一直留在页面上。留着的按钮还能再点，
   * 第二次提交带的是同一个已经过期的 sourceRevision，服务端只能回
   * SOURCE_REVISION_STALE。
   *
   * 权威叙事是这个动作确实结算完的信号，按 correlationId 精确匹配，不会误清掉
   * 另一个仍在等玩家的检定。
   */
  const clearSettledAdjudication = useCallback((correlationId?: string | null) => {
    // 开场叙事等没有 messageId 的推送不属于任何动作，不能拿来收面板。
    if (!correlationId) return
    setPendingAdjudication((current) =>
      current?.correlationId === correlationId ? null : current,
    )
  }, [])
  const [activePlanId, setActivePlanId] = useState<string | null>(null)
  const clearSettledAction = useCallback((correlationId?: string | null) => {
    clearSettledAdjudication(correlationId)
    if (!correlationId) return
    setActivePlanId((current) => current === correlationId ? null : current)
  }, [clearSettledAdjudication])
  const [pendingCheckDice, setPendingCheckDice] = useState<PendingCheckDiceState | null>(null)
  const [playerView, setPlayerView] = useState<AgentPlayerView | null>(() => {
    const cached = sdk.roomSocket.getPlayerView()
    return cached?.room_id === roomId ? cached : null
  })
  const [progressLabel, setProgressLabel] = useState<string | null>(null)
  const [secondaryProgressLabel, setSecondaryProgressLabel] = useState<string | null>(null)
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
  /**
   * 引擎在等玩家掷骰时唯一的开面板入口（issue #304）。
   *
   * 讨论区只承载玩家之间的讨论，不出现骰子。但玩家停在讨论区时不能只是把面板
   * 藏起来——那会让这次检定静默卡住，回合一直悬着。所以先把频道切回行动区再
   * 呈现：「在讨论区掷骰」这件事因此从不发生，检定也不会挂起。
   */
  const openDiceForCheck = useCallback(() => {
    setChannel('action')
    setShowDice(true)
  }, [])
  const notesKey = roomId ? `aidm-notes-${roomId}` : null
  // ★ 之前"📋 案件笔记"标题是直接塞进 textarea 初始内容里的普通文本，用户
  // 一编辑/全选删除就会把标题本身也删掉。改成占位符（placeholder），真正
  // 的内容默认是空白，标题不会被误删，也不占用户还没写的正文空间。
  const [notes, setNotes] = useState(
    () => (notesKey && localStorage.getItem(notesKey)) || ''
  )
  const [lastSaved, setLastSaved] = useState<string | null>(() => (notesKey ? localStorage.getItem(notesKey) : null) ? new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const composerInputRef = useRef<HTMLTextAreaElement>(null)
  const pendingNarrationActionIdRef = useRef<string | null>(null)
  const organizingPhaseStartedAtRef = useRef<number | null>(null)
  const progressClearTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const suspended = (roomPhase || roomInfo?.phase) === 'Suspended'
  const ownsRoomAction = roomActionState?.playerId === playerId
  const mustAnswerCurrent =
    ownsRoomAction &&
    roomActionState?.status === 'awaiting_player' &&
    (pendingAdjudication !== null || pendingTimeAdvance !== null || pendingSceneTransition !== null)
  const actionSubmissionBlocked = mustAnswerCurrent
  const queuedActions = roomActionState?.queued ?? []
  const waitingForPlayerAction =
    roomActionState?.status === 'awaiting_player' && (
      pendingAdjudication !== null ||
      pendingTimeAdvance !== null ||
      pendingSceneTransition !== null
    )
  const showRoomActionBanner =
    roomActionState !== null &&
    roomActionState.status !== 'idle' &&
    (roomActionState.status === 'processing' || waitingForPlayerAction)
  const composerDisabled = suspended
  const actionOwnerName = roomActionState?.playerId === playerId
    ? senderName
    : displayName(
        roomPlayers.find((player) => player.playerId === roomActionState?.playerId)?.characterName,
        roomPlayers.find((player) => player.playerId === roomActionState?.playerId)?.nickname,
        '其他调查员',
      )
  const mapLocations = mapLocationsFromPlayerView(playerView)
  const sceneTransitionTargetName = pendingSceneTransition
    ? mapLocations.find((location) => location.id === pendingSceneTransition.targetSceneId)?.name
      ?? pendingSceneTransition.targetSceneId
    : null
  const currentLocationImage = playerView ? LOCATION_IMAGE_BY_ID[playerView.scene.id] : undefined
  const liveResources = liveResourcesOf(playerView)
  const currentHp = resourceValue(playerView, 'hp') ?? character?.derived.hp ?? null
  const currentSan = resourceValue(playerView, 'san') ?? character?.derived.san ?? null
  // 权限请求、识别和整理结果期间都占用语音会话。UI 用同一个布尔值切换
  // “发送/取消”按钮，保持移动端输入栏始终只有四列，不挤压输入框。
  const speechInputActive =
    speechInput.status === 'requesting_permission' ||
    speechInput.status === 'listening' ||
    speechInput.status === 'processing'

  const showBackendPhase = useCallback((phase: AgentTurnPhase) => {
    if (progressClearTimerRef.current !== null) {
      clearTimeout(progressClearTimerRef.current)
      progressClearTimerRef.current = null
    }
    const label = PHASE_LABELS[phase]
    if (label === '守秘人组织语言中') {
      organizingPhaseStartedAtRef.current ??= Date.now()
    } else {
      organizingPhaseStartedAtRef.current = null
    }
    setProgressLabel(label)
  }, [])

  const clearBackendProgress = useCallback(() => {
    const startedAt = organizingPhaseStartedAtRef.current
    const remaining =
      startedAt === null ? 0 : ORGANIZING_PHASE_MIN_MS - (Date.now() - startedAt)
    if (remaining <= 0) {
      organizingPhaseStartedAtRef.current = null
      setProgressLabel(null)
      return
    }
    if (progressClearTimerRef.current !== null) {
      clearTimeout(progressClearTimerRef.current)
    }
    progressClearTimerRef.current = setTimeout(() => {
      progressClearTimerRef.current = null
      organizingPhaseStartedAtRef.current = null
      setProgressLabel(null)
    }, remaining)
  }, [])

  useEffect(
    () => () => {
      if (progressClearTimerRef.current !== null) {
        clearTimeout(progressClearTimerRef.current)
      }
    },
    [],
  )

  useEffect(() => {
    // 输入框在行动和讨论区复用；切换频道时丢弃尚未完成的识别，避免结果进入新频道。
    cancelSpeechInput()
  }, [cancelSpeechInput, channel])

  useEffect(() => {
    if (suspended) cancelSpeechInput()
  }, [cancelSpeechInput, suspended])

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
          item.type === 'narr' && item.narrationId ? [item.narrationId] : [],
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
        setSecondaryProgressLabel(null)
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
    enqueueHostSpeech(authoritativeId)
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
        narrationId: authoritativeId,
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
        clearBackendProgress()
        setSecondaryProgressLabel(null)
        clearSettledAction(envelope.payload.messageId)
        setStreamingNarration((current) =>
          accumulateNarrationChunk(current, {
            messageId: conversationMessageId('narration.push', envelope.payload.messageId),
            sequence: envelope.payload.sequence,
            text: envelope.payload.text,
          }),
        )
      } else if (envelope.type === 'narration.push') {
        setTyping(false)
        clearBackendProgress()
        setSecondaryProgressLabel(null)
        clearSettledAction(envelope.payload.messageId)
        // 不在这里直接落地：权威消息比最后一个片段只晚到半毫秒，立刻接管会让
        // 刚开始的渐进展示当场被整段覆盖。入队，交给上面的 effect 按序裁决。
        setPendingNarrations((current) => [...current, envelope.payload])
      } else if (envelope.type === 'opening.started') {
        setTyping(true)
        setProgressLabel('守秘人正在生成开场叙事')
      } else if (envelope.type === 'room.state') {
        setRoomPhase(envelope.payload.phase)
      } else if (envelope.type === 'room.action.state') {
        setRoomActionState(envelope.payload)
        if (envelope.payload.status === 'idle') {
          // idle 是服务端的完整终态快照；重连时用它清除浏览器残留的旧检定控件。
          setPendingAdjudication(null)
          setPendingCheck(null)
          setPendingCheckDice(null)
          setAuthoritativeDiceRoll(null)
          setPendingAction(null)
        }
      } else if (envelope.type === 'host_speech.settings_updated') {
        handleHostSpeechSettingsUpdated(envelope.payload.voiceType)
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
            playerId: envelope.payload.playerId,
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
          playerId: envelope.payload.playerId,
        }))
      } else if (envelope.type === 'check.request') {
        setTyping(false)
        showBackendPhase('waiting_for_check')
        setPendingCheck(envelope.payload)
        setPendingCheckDice((current) =>
          current?.clientActionId === envelope.payload.clientActionId
            ? current
            : createPendingCheckDiceState(envelope.payload)
        )
        openDiceForCheck()
      } else if (envelope.type === 'check.result') {
        setTyping(true)
        showBackendPhase('executing_action')
        setMessages(prev => appendLiveMessage(prev, {
          type: 'dice',
          channel: 'action',
          messageId: conversationMessageId('check.result', envelope.payload.clientActionId),
          sender: displayName(
            envelope.payload.characterName,
            envelope.payload.playerId === playerId ? senderName : null,
          ),
          content: checkResultContent(envelope.payload),
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
      } else if (envelope.type === 'adjudication.pending') {
        setTyping(false)
        setProgressLabel(
          envelope.payload.status === 'awaiting_skill_choice'
            ? '守秘人等待玩家掷骰子'
            : '守秘人等待玩家决定检定结果',
        )
        setPendingAdjudication(envelope.payload)
        // One-step TurnRuns intentionally suppress plan progress events. The
        // pending payload is therefore the authoritative cancellation handle
        // for both one-step and multi-step runs.
        if (envelope.payload.planId) {
          setActivePlanId(envelope.payload.correlationId)
        }
        const checkRun = envelope.payload.checkRun
        const selected = selectedAdjudicationOptionRef.current
        if (
          envelope.payload.status === 'awaiting_post_roll_decision' &&
          checkRun &&
          selected?.correlationId === envelope.payload.correlationId &&
          selected.option.candidate_id === checkRun.selected_candidate_id
        ) {
          const rollKey = `${checkRun.check_id}:${checkRun.roll_count}`
          if (shownAdjudicationRollRef.current !== rollKey) {
            shownAdjudicationRollRef.current = rollKey
            setAuthoritativeDiceRoll({
              correlationId: envelope.payload.correlationId,
              checkId: checkRun.check_id,
              rollCount: checkRun.roll_count,
              value: checkRun.roll.value,
              degree: checkRun.roll.degree,
            })
            const checkRequest: CheckRequestPayload = {
              playerId: playerId ?? '',
              clientActionId: envelope.payload.correlationId,
              summary: selected.option.method_summary,
              difficulty: selected.option.difficulty,
              skills: [
                {
                  id: selected.option.candidate_id,
                  name: selected.option.display_name,
                  targetValue: selected.option.target_value,
                },
              ],
            }
            setPendingCheck(checkRequest)
            setPendingCheckDice(createPendingCheckDiceState(checkRequest))
            openDiceForCheck()
          }
        }
      } else if (envelope.type === 'time.advance.pending') {
        setPendingTimeAdvance(envelope.payload)
        setTimeAdvanceResponding(false)
        setTyping(false)
        setProgressLabel('等待全员确认时间推进')
      } else if (envelope.type === 'time.advance.resolved') {
        setPendingTimeAdvance((current) =>
          current?.proposalId === envelope.payload.proposalId ? null : current,
        )
        setTimeAdvanceResponding(false)
        setProgressLabel(null)
      } else if (envelope.type === 'scene.transition.pending') {
        setPendingSceneTransition(envelope.payload)
        setTimeAdvanceResponding(false)
        setTyping(false)
        setProgressLabel('等待全员确认场景切换')
      } else if (envelope.type === 'scene.transition.resolved') {
        setPendingSceneTransition((current) =>
          current?.proposalId === envelope.payload.proposalId ? null : current,
        )
        setTimeAdvanceResponding(false)
        setProgressLabel(null)
      } else if (
        envelope.type === 'plan.started' ||
        envelope.type === 'plan.step_changed' ||
        envelope.type === 'plan.stopped' ||
        envelope.type === 'plan.completed'
      ) {
        // A plan step change supersedes any prior check decision. The server
        // sends a fresh adjudication.pending when the new step is waiting for
        // the player; clearing first prevents stale decision IDs from being
        // submitted during the transition or after a terminal event.
        setPendingAdjudication(null)
        setAuthoritativeDiceRoll(null)
        setActivePlanId(
          envelope.type === 'plan.completed' || envelope.type === 'plan.stopped'
            ? null
            : envelope.payload.correlationId,
        )
        setSecondaryProgressLabel(
          envelope.type === 'plan.completed' || envelope.type === 'plan.stopped'
            ? null
            : envelope.payload.publicProgressLabel ??
              `第 ${envelope.payload.currentStep}/${envelope.payload.totalSteps} 步`,
        )
        if (envelope.type !== 'plan.completed' && envelope.type !== 'plan.stopped') {
          setProgressLabel((current) => current ?? '守秘人理解玩家意图中')
        }
      } else if (envelope.type === 'turn.started') {
        setTyping(true)
        showBackendPhase('reading_player_view')
        setSecondaryProgressLabel(null)
      } else if (envelope.type === 'turn.phase_changed') {
        setTyping(envelope.payload.phase !== 'waiting_for_check')
        showBackendPhase(envelope.payload.phase)
      } else if (envelope.type === 'tool.started') {
        setTyping(true)
        setProgressLabel((current) => current ?? '守秘人理解玩家意图中')
        setSecondaryProgressLabel(envelope.payload.publicProgressLabel)
      } else if (envelope.type === 'turn.failed') {
        setTyping(false)
        setProgressLabel(null)
        setSecondaryProgressLabel(null)
        setPendingAdjudication(null)
        // 片段只在叙事落库成功后才会下发，回合失败时不存在对应的权威消息——
        // 留着半截文字会让玩家以为那是这回合的结果。
        //
        // 只中止揭示，不清待提交队列：队列里的都是已经落库的权威消息（push 紧跟
        // 片段到达），清掉等于丢服务端认定已发生的叙事。中止后它们会立即落地。
        setStreamingNarration(null)
        pendingNarrationActionIdRef.current = null
        if (envelope.payload.code === 'ACTION_CANCELLED') {
          return
        }
        setActionError(envelope.payload.publicMessage)
        setActionErrorRetryable(envelope.payload.retryable)
        setActionErrorIsGuidance(envelope.payload.code === 'HOST_AGENT_INVALID_OUTPUT')
        setActionErrorCode(envelope.payload.code)
        setActionErrorCorrelationId(envelope.payload.correlationId)
      } else if (envelope.type === 'view.updated') {
        if (envelope.payload.playerId === playerId) {
          setPlayerView(envelope.payload.playerView)
        }
      } else if (envelope.type === 'error') {
        setTyping(false)
        setProgressLabel(null)
        setSecondaryProgressLabel(null)
        setPendingAdjudication(null)
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
  }, [clearBackendProgress, clearSettledAction, enqueueHostSpeech, handleHostSpeechSettingsUpdated, openDiceForCheck, playerId, senderName, showBackendPhase])

  const submitPlayerAction = (action: { clientActionId: string; utterance: string }) => {
    if (!playerId || suspended || actionSubmissionBlocked) return
    pendingNarrationActionIdRef.current = action.clientActionId
    setPendingAction(action)
    setActionError('')
    setActionErrorRetryable(false)
    setActionErrorIsGuidance(false)
    setActionErrorCode(null)
    setActionErrorCorrelationId(null)
    setTyping(true)
    showBackendPhase('reading_player_view')
    setSecondaryProgressLabel(null)
    void sdk.roomSocket.submitPlannedAction(playerId, action)
      .then((result) => {
        setPlayerView(result.player_view)
        // 这个动作已经拿到权威结果，属于它的检定面板不能再留在页面上。比等
        // narration 更早，也覆盖了叙事走重放而不是逐片推送的情况。
        clearSettledAction(action.clientActionId)
        setPendingAction((current) =>
          current?.clientActionId === action.clientActionId ? null : current
        )
      })
      .catch((error: unknown) => {
        setTyping(false)
        setProgressLabel(null)
        setSecondaryProgressLabel(null)
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

  const insertHostMention = () => {
    if (suspended) return
    setChannel('action')
    setDrafts((current) => {
      const value = current.action
      return {
        ...current,
        action: value.includes('@主持人')
          ? value
          : value.trim()
            ? `@主持人 ${value.trim()}`
            : '@主持人 ',
      }
    })
    requestAnimationFrame(() => {
      const field = composerInputRef.current
      if (!field) return
      field.focus()
      const cursor = field.value.length
      field.setSelectionRange(cursor, cursor)
    })
  }

  const sendMessage = (e?: FormEvent) => {
    e?.preventDefault()
    const text = input.trim()
    if (!text || !playerId || suspended) return
    // 发送前先关闭识别结果闸门，防止浏览器稍后返回的文本写入已清空的输入框。
    cancelSpeechInput()
    setInput('')
    if (channel === 'discussion') {
      sdk.roomSocket.sendChat(playerId, { text, clientMessageId: randomActionId() })
      return
    }
    const hostUtterance = hostUtteranceFromActionInput(text)
    if (hostUtterance) {
      if (actionSubmissionBlocked) return
      submitPlayerAction({ clientActionId: randomActionId(), utterance: hostUtterance })
      return
    }
    sdk.roomSocket.sendActionChat(playerId, { text, clientMessageId: randomActionId() })
  }

  useEffect(() => {
    const field = composerInputRef.current
    if (!field) return
    if (!input) {
      field.style.height = ''
      return
    }
    field.style.height = 'auto'
    field.style.height = `${field.scrollHeight}px`
  }, [input])

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
    // 自由骰：玩家自己点骰子按钮掷的，引擎没有发起任何检定。这里只报点数。
    //
    // 此前会按 `result <= 5 / <= 65` 编一个「极限成功 / 成功 / 失败」出来。那个
    // 65 是个魔数，跟角色技能值、跟模组、跟任何东西都没关系，渲染出来却和权威
    // 检定结果长得一模一样，玩家会以为自己过了什么判定（#310）。没有技能、没有
    // 难度、没有目标值，就没有判定可言。
    const typeLabel = diceType.toUpperCase()
    setMessages(prev => [...prev, {
      type: 'dice', channel: 'action', sender: senderName, content: `${typeLabel} · ${result} · 自由掷骰`, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), isSelf: true,
    }])
  }

  const submitAdjudicationPostRoll = (optionId: string, revisedMethod?: string) => {
    if (!playerId || !pendingAdjudication) return
    const pending = pendingAdjudication
    const checkRun = pending.checkRun
    if (!checkRun) return
    setTyping(true)
    showBackendPhase('executing_action')
    setShowDice(false)
    setPendingCheck(null)
    setPendingCheckDice(null)
    setAuthoritativeDiceRoll(null)
    setPendingAdjudication(null)
    shownAdjudicationRollRef.current = null
    sdk.roomSocket.decidePostRoll(playerId, {
      clientActionId: pending.correlationId,
      requestId: randomActionId(),
      sourceRevision: pending.sourceRevision,
      checkId: checkRun.check_id,
      checkVersion: checkRun.version,
      optionId,
      revisedMethod,
    })
  }

  // 结束游戏——仅房主可操作。房间转「已完成」后只能在「我的游戏」里查看复盘，不能再回到聊天室。
  const handleEndGame = async () => {
    if (!roomId) return
    setEnding(true)
    setEndError('')
    try {
      if (playerView?.world.ending_available) {
        if (!endingDraft) {
          const draft = await createEndingDraft(
            roomId,
            playerView.revision,
            endingDraftRequestId.current,
          )
          setEndingDraft(draft)
          setEnding(false)
          return
        }
        await confirmEndingDraft(roomId, endingDraft, endingConfirmRequestId.current)
      } else {
        // Legacy/admin room shutdown remains available only outside the v3
        // player ending flow. A v3 terminal story outcome always confirms a draft.
        await endGame(roomId)
      }
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
    <div className="room-play h-full flex flex-col relative max-w-[430px] mx-auto">
      {/* Header */}
      <header data-onboarding-target="scene-header" className="room-play__header flex items-center flex-shrink-0">
        <button
          type="button"
          aria-label="退出游戏"
          title="退出游戏"
          onClick={() => setConfirmExit(true)}
          className="room-play__round-button"
        >
          <ArrowLeft strokeWidth={2.2} />
        </button>
        <div className="room-play__scene flex-1 min-w-0">
          <div className="room-play__module-title">{roomInfo?.moduleTitle || '当前模组'}</div>
          <div className="room-play__location" title={playerView?.scene.name || '场景同步中'}>
            <MapPin aria-hidden="true" />
            <span>{playerView?.scene.name || '场景同步中'}</span>
          </div>
        </div>
        <OnboardingTrigger className="room-play__guide-button" />
        <button
          onClick={() => setOpenPanel(openPanel === 'speech' ? null : 'speech')}
          aria-label="主持人语音"
          title="主持人语音"
          className={`room-play__round-button ${hostSpeech.status === 'playing' ? 'is-active' : ''}`}
        >
          <Volume2 strokeWidth={2.2} />
        </button>
        <button
          onClick={() => setOpenPanel(openPanel === 'members' ? null : 'members')}
          aria-label="房间成员"
          title="房间成员"
          className="room-play__round-button"
        >
          <Users strokeWidth={2.2} />
        </button>
      </header>

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

      <section className="room-play__paper">
      {/* Messages */}
      <div className="room-play__tabs" aria-label="游戏消息频道">
        {([{ id: 'action', label: '行动' }, { id: 'discussion', label: '讨论区' }] as const).map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={channel === item.id}
            onClick={() => setChannel(item.id)}
            className={`room-play__tab ${channel === item.id ? 'is-active' : ''}`}
          >
            <span aria-hidden="true" className="room-play__tab-paw">●</span>
            {item.label}
          </button>
        ))}
      </div>
      <div data-onboarding-target="narration-feed" className="room-play__feed" id="chatScroll">
        {messages.filter((msg) => (msg.channel ?? 'action') === channel).map((msg, i) => {
          if (msg.type === 'system') {
            return (
              <div key={i} className="room-play__system-message animate-[fadeIn_0.3s_ease]">
                <span>{msg.content}</span>
              </div>
            )
          }

          if (msg.type === 'dice') {
            return (
              <div key={i} className="room-play__message room-play__message--self room-play__message--dice animate-[msgIn_0.3s_ease]">
                <div className="room-play__avatar room-play__avatar--dice">
                  🎲
                </div>
                <div className="room-play__message-body">
                  <div className="room-play__sender">{msg.sender} · 掷骰</div>
                  <div className="room-play__message-card room-play__dice-card">
                    {msg.content}
                  </div>
                  <div className="room-play__message-meta">{msg.time}</div>
                </div>
              </div>
            )
          }

          const isPlayer = msg.type === 'player' && msg.isSelf
          const isNarr = msg.type === 'narr'
          const portraitUrl = msg.playerId ? portraitUrls[msg.playerId] : undefined

          return (
            <div key={i} className={`room-play__message ${isPlayer ? 'room-play__message--self' : ''} ${isNarr ? 'room-play__message--narration' : ''} animate-[msgIn_0.3s_ease]`}>
              {isNarr ? (
                <KeeperAvatar onLongPress={insertHostMention} />
              ) : (
                <div className="room-play__avatar">
                  {msg.type === 'player' && portraitUrl ? (
                    <img
                      src={portraitUrl}
                      alt={`${msg.sender ?? '玩家'}的头像`}
                      className="h-full w-full object-cover"
                    />
                  ) : msg.type === 'player' ? '🔍' : '🤖'}
                </div>
              )}
              <div className="room-play__message-body">
                <div className="room-play__sender">
                  {msg.sender}
                </div>
                <div className={`room-play__message-card ${isNarr ? 'room-play__narration-card' : ''}`}>
                  <div className="room-play__narration-text whitespace-pre-wrap">
                    {isNarr && msg.narrationId === hostSpeech.currentMessageId && hostSpeech.currentSentences.length > 0
                      ? hostSpeech.currentSentences.map((sentence) => (
                          <span
                            key={sentence.index}
                            className={sentence.index === hostSpeech.currentSentenceIndex ? 'bg-brass/20 rounded-sm' : ''}
                          >
                            {sentence.text}
                          </span>
                        ))
                      : msg.content}
                  </div>
                </div>
                <div className="room-play__message-meta">
                  <span>{msg.time}</span>
                  {isNarr && (
                    <button
                      type="button"
                      aria-label="重新朗读"
                      title="重新朗读"
                      disabled={!hostSpeech.available || !msg.narrationId}
                      onClick={() => hostSpeech.replay(msg.narrationId)}
                    >
                      <RotateCcw aria-hidden="true" />
                      重播
                    </button>
                  )}
                </div>
              </div>
            </div>
          )
        })}

        {/* 渐进到达的主持叙事（issue #203）。没有"重播"按钮：它还不是权威
            消息，语音朗读只认最终 narration.push。

            频道判断不能只做在上面那条历史消息的 filter 上：这个气泡和下面的
            进度指示器都不经过 messages，漏进讨论区过（issue #304）。*/}
        {isActionChannel && streamingNarration && streamingNarration.revealed > 0 && (
          <div className="room-play__message room-play__message--narration animate-[msgIn_0.3s_ease]">
            <KeeperAvatar onLongPress={insertHostMention} />
            <div className="room-play__message-body">
              <div className="room-play__sender">守秘人</div>
              <div className="room-play__message-card room-play__narration-card">
                <div className="room-play__narration-text whitespace-pre-wrap">
                  {streamingNarrationText(streamingNarration).slice(0, streamingNarration.revealed)}
                </div>
              </div>
              <div className="room-play__message-meta">生成中…</div>
            </div>
          </div>
        )}

        {/* Typing indicator。第一个片段到达后还没揭示出字的那一瞬间也留着它，
            避免出现一个空气泡。*/}
        {isActionChannel && (progressLabel !== null || typing || (streamingNarration !== null && streamingNarration.revealed === 0)) && (
          <div className="room-play__message room-play__message--narration animate-[msgIn_0.3s_ease]">
            <KeeperAvatar onLongPress={insertHostMention} />
            <div className="room-play__typing">
              <div className="inline-flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="w-1.5 h-1.5 bg-brass rounded-full animate-bounce"
                    style={{ animationDelay: `${i * 0.2}s`, animationDuration: '1.4s' }} />
                ))}
              </div>
              {progressLabel && (
                <span className="text-[11px] text-text-muted">
                  {progressLabel}
                  {secondaryProgressLabel && (
                    <span className="ml-1.5 text-text-dim">· {secondaryProgressLabel}</span>
                  )}
                </span>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Action Bar */}
      <div data-onboarding-target="tool-bar" className="room-play__toolbar">
        {[
          { icon: ScrollText, label: '角色卡', key: 'sheet' },
          { icon: Star, label: '技能', key: 'skills' },
          { icon: Map, label: '地图', key: 'map' },
          { icon: BookOpen, label: '笔记', key: 'notes' },
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={openPanel === item.key}
            onClick={() => setOpenPanel(openPanel === item.key ? null : item.key)}
            className={openPanel === item.key ? 'is-active' : ''}
          >
            <item.icon aria-hidden="true" strokeWidth={1.7} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>

      {/* HP/SAN 实时状态条——放在角色卡/技能等快捷面板和输入框之间，聊天时想随时
          瞄一眼当前状态不用点开面板。HP 目前没有"当前值/上限值"两套数字（还没
          做受伤扣血的机制，见已知局限），先按"当前即满值"画满条，以后接了扣血
          机制这里会自然跟着变化。 */}
      {currentHp !== null && currentSan !== null && (
        <div className="room-play__vitals" aria-label="调查员实时状态">
          <div className="room-play__vital">
            <Heart aria-hidden="true" strokeWidth={2.5} />
            <span>生命</span>
            <div className="room-play__vital-track">
              <div className="room-play__vital-fill room-play__vital-fill--hp" style={{ width: '100%' }} />
            </div>
            <strong>{currentHp}</strong>
          </div>
          <div className="room-play__vital">
            <Brain aria-hidden="true" strokeWidth={2.3} />
            <span>理智</span>
            <div className="room-play__vital-track">
              <div className="room-play__vital-fill room-play__vital-fill--san" style={{ width: `${Math.min(100, currentSan)}%` }} />
            </div>
            <strong>{currentSan}</strong>
          </div>
        </div>
      )}
      </section>

      {pendingTimeAdvance && (
        <div className="room-play__time-consent" role="status" aria-live="polite">
          <div className="room-play__time-consent-summary">
            <Clock3 aria-hidden="true" strokeWidth={2} />
            <div>
              <strong>{formatWorldTime(
                pendingTimeAdvance.targetDayIndex,
                pendingTimeAdvance.targetHourOfDay,
              )}</strong>
              <span>
                {pendingTimeAdvance.acceptedPlayerIds.length}/
                {pendingTimeAdvance.requiredPlayerIds.length} 人已确认
              </span>
            </div>
          </div>
          <div className="room-play__time-consent-actions">
            <button
              type="button"
              className="room-play__time-consent-button room-play__time-consent-button--reject"
              disabled={
                timeAdvanceResponding ||
                !playerId ||
                pendingTimeAdvance.acceptedPlayerIds.includes(playerId)
              }
              onClick={() => {
                if (!playerId) return
                setTimeAdvanceResponding(true)
                sdk.roomSocket.respondToTimeAdvance(playerId, {
                  proposalId: pendingTimeAdvance.proposalId,
                  proposalVersion: pendingTimeAdvance.proposalVersion,
                  sourceRevision: pendingTimeAdvance.sourceRevision,
                  accept: false,
                })
              }}
            >
              <X aria-hidden="true" />
              拒绝
            </button>
            <button
              type="button"
              className="room-play__time-consent-button room-play__time-consent-button--accept"
              disabled={
                timeAdvanceResponding ||
                !playerId ||
                pendingTimeAdvance.acceptedPlayerIds.includes(playerId)
              }
              onClick={() => {
                if (!playerId) return
                setTimeAdvanceResponding(true)
                sdk.roomSocket.respondToTimeAdvance(playerId, {
                  proposalId: pendingTimeAdvance.proposalId,
                  proposalVersion: pendingTimeAdvance.proposalVersion,
                  sourceRevision: pendingTimeAdvance.sourceRevision,
                  accept: true,
                })
              }}
            >
              <Check aria-hidden="true" />
              {playerId && pendingTimeAdvance.acceptedPlayerIds.includes(playerId)
                ? '已同意'
                : '同意'}
            </button>
          </div>
        </div>
      )}

      {pendingSceneTransition && (
        <div className="room-play__time-consent" role="status" aria-live="polite">
          <div className="room-play__time-consent-summary">
            <MapPin aria-hidden="true" strokeWidth={2} />
            <div>
              <strong>前往 {sceneTransitionTargetName}</strong>
              <span>
                {pendingSceneTransition.acceptedPlayerIds.length}/
                {pendingSceneTransition.requiredPlayerIds.length} 人已确认
              </span>
            </div>
          </div>
          <div className="room-play__time-consent-actions">
            <button
              type="button"
              className="room-play__time-consent-button room-play__time-consent-button--reject"
              disabled={
                timeAdvanceResponding ||
                !playerId ||
                pendingSceneTransition.acceptedPlayerIds.includes(playerId)
              }
              onClick={() => {
                if (!playerId) return
                setTimeAdvanceResponding(true)
                sdk.roomSocket.respondToSceneTransition(playerId, {
                  proposalId: pendingSceneTransition.proposalId,
                  proposalVersion: pendingSceneTransition.proposalVersion,
                  sourceRevision: pendingSceneTransition.sourceRevision,
                  accept: false,
                })
              }}
            >
              <X aria-hidden="true" />
              拒绝
            </button>
            <button
              type="button"
              className="room-play__time-consent-button room-play__time-consent-button--accept"
              disabled={
                timeAdvanceResponding ||
                !playerId ||
                pendingSceneTransition.acceptedPlayerIds.includes(playerId)
              }
              onClick={() => {
                if (!playerId) return
                setTimeAdvanceResponding(true)
                sdk.roomSocket.respondToSceneTransition(playerId, {
                  proposalId: pendingSceneTransition.proposalId,
                  proposalVersion: pendingSceneTransition.proposalVersion,
                  sourceRevision: pendingSceneTransition.sourceRevision,
                  accept: true,
                })
              }}
            >
              <Check aria-hidden="true" />
              {playerId && pendingSceneTransition.acceptedPlayerIds.includes(playerId)
                ? '已同意'
                : '同意'}
            </button>
          </div>
        </div>
      )}

      {showRoomActionBanner && roomActionState && (
        <div className="room-play__action-state" role="status" aria-live="polite">
          <LoaderCircle
            aria-hidden="true"
            className={roomActionState.status === 'processing' ? 'animate-spin' : ''}
          />
          <strong>{actionOwnerName}</strong>
          <span>
            {roomActionState.status === 'processing'
              ? '的行动正在处理中'
              : ownsRoomAction
                ? '的行动正在等待你操作'
                : '的行动正在等待其操作'}
          </span>
        </div>
      )}
      {queuedActions.length > 0 && (
        <div className="room-play__action-state" role="status" aria-live="polite">
          <span>等待主持：</span>
          {queuedActions.map((item) => {
            const name = displayName(
              roomPlayers.find((player) => player.playerId === item.playerId)?.characterName,
              roomPlayers.find((player) => player.playerId === item.playerId)?.nickname,
              '调查员',
            )
            const isSelf = item.playerId === playerId
            return (
              <span key={item.clientActionId} className="inline-flex items-center gap-1">
                <strong>{name}</strong>
                <span>{item.utterance}</span>
                {isSelf && playerId && (
                  <button
                    type="button"
                    className="text-[11px] underline"
                    onClick={() => sdk.roomSocket.cancelActionPlan(playerId, {
                      clientActionId: item.clientActionId,
                      requestId: randomActionId(),
                    })}
                  >
                    取消
                  </button>
                )}
              </span>
            )
          })}
        </div>
      )}

      {/* Input area */}
      <div className="room-play__composer">
        {suspended && (
          <p className="text-[11px] text-[#9a6a30] text-center pb-1.5">
            游戏已挂起，恢复后才能继续提交行动
          </p>
        )}
        {isActionChannel && actionError && !suspended && (
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
        {(speechInput.status !== 'idle' || speechInput.error) && !suspended && (
          <p
            aria-live="polite"
            className={`pb-1.5 px-1 text-[11px] ${
              speechInput.status === 'failed' || speechInput.status === 'unsupported'
                ? 'text-[#c04040]'
                : 'text-text-muted'
            }`}
          >
            {speechInput.status === 'unsupported'
              ? speechInput.unavailableReason
              : speechInput.status === 'requesting_permission'
                ? '正在请求麦克风权限…'
                : speechInput.status === 'listening'
                  ? '正在聆听，点击停止后将文字填入输入框'
                  : speechInput.status === 'processing'
                    ? '正在整理识别结果…'
                    : speechInput.error}
          </p>
        )}
        <form data-onboarding-target="action-input" onSubmit={sendMessage} className="room-play__composer-form">
          {/* 讨论区只承载玩家之间的讨论，不提供掷骰入口（issue #304）。 */}
          {isActionChannel && (
            <button
              type="button"
              aria-label="骰子"
              data-onboarding-target="dice-button"
              onClick={() => setShowDice(true)}
              disabled={composerDisabled}
              className="room-play__composer-button room-play__dice-button"
            >
              <IsometricDiceIcon />
            </button>
          )}
          {isActionChannel && (
            <button
              type="button"
              aria-label="插入 @主持人"
              title="@主持人"
              onClick={insertHostMention}
              disabled={composerDisabled}
              className={`room-play__composer-button room-play__host-mention-button${input.includes('@主持人') ? ' is-active' : ''}`}
            >
              <span aria-hidden="true">@</span>
            </button>
          )}
          <textarea
            ref={composerInputRef}
            rows={1}
            wrap="soft"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== 'Enter' || e.shiftKey || e.nativeEvent.isComposing) return
              e.preventDefault()
              sendMessage()
            }}
            disabled={composerDisabled}
            placeholder={
              suspended
                ? '游戏已挂起'
                : isActionChannel
                    ? '输入消息…'
                    : '输入行动…'
            }
            className="room-play__input"
          />
          {speechInput.status === 'listening' ? (
            <button
              type="button"
              aria-label="停止语音输入并采用文字"
              title="停止并采用识别文字"
              onClick={speechInput.stop}
              disabled={composerDisabled}
              className="room-play__composer-button room-play__composer-button--danger"
            >
              <Square className="w-4 h-4" fill="currentColor" strokeWidth={2} />
            </button>
          ) : (
            <button
              type="button"
              aria-label={speechInput.supported ? '开始语音输入' : '语音输入不可用'}
              title={speechInput.unavailableReason ?? '开始语音输入'}
              onClick={speechInput.start}
              disabled={
                composerDisabled ||
                !speechInput.supported ||
                speechInput.status === 'requesting_permission' ||
                speechInput.status === 'processing'
              }
              className="room-play__composer-button"
            >
              {speechInput.status === 'requesting_permission' || speechInput.status === 'processing' ? (
                <LoaderCircle className="w-[18px] h-[18px] animate-spin" strokeWidth={2} />
              ) : (
                <Mic className="w-[18px] h-[18px]" strokeWidth={2} />
              )}
            </button>
          )}
          {speechInputActive && (
            <button
              type="button"
              aria-label="取消语音输入"
              title="取消并丢弃本次识别"
              onClick={speechInput.cancel}
              className="room-play__composer-button"
            >
              <X className="w-[18px] h-[18px]" strokeWidth={2} />
            </button>
          )}
          {!speechInputActive && (
            <button
              type="submit"
              aria-label="发送消息"
              disabled={composerDisabled || !input.trim()}
              className="room-play__composer-button room-play__send-button"
            >
              <SendHorizontal className="w-[18px] h-[18px]" strokeWidth={2.5} />
            </button>
          )}
        </form>
      </div>

      {/* ── Panels ── */}

      {/* Panel: 角色卡（真实建卡数据，不再是写死的示例角色）。分两页——技能已经有
          单独的底部按钮，这里不重复放。 */}
      <BottomPanel
        open={openPanel === 'sheet'}
        onClose={() => setOpenPanel(null)}
        title={`调查员 · ${character?.info.name || '未建卡'}`}
        className="room-play__bottom-panel--character-paper room-play__bottom-panel--character-sheet"
        heightVh={70}
      >
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
              <div className="character-ready-sheet__content space-y-4">
                <CharacterBasicInfo
                  character={character}
                  portraitUrl={playerId ? portraitUrls[playerId] : undefined}
                  occupationName={character.info.occupationId
                    ? ruleset?.occupations.find(o => o.id === character.info.occupationId)?.name
                    : null}
                  attributes={ruleset?.attributes ?? []}
                  liveResources={liveResources}
                  portraitAction={{ kind: 'generate', onActivate: () => setShowPortraitGenerator(true) }}
                />
              </div>
            )}

            {sheetPage === 'background' && (
              <>
                <h4 className="text-xs font-semibold text-brass-dark mb-2.5">装备</h4>
                <p className="text-sm text-text-body leading-[1.7] mb-4">
                  {playerView?.inventory?.length
                    ? playerView.inventory.map(item => `${item.name}${item.quantity > 1 ? ` ×${item.quantity}` : ''}`).join('、')
                    : character.equipment || '未填写装备'}
                </p>
                <h4 className="text-xs font-semibold text-brass-dark mb-2.5">背景故事</h4>
                <p className="text-sm text-text-body leading-[1.7] mb-4 whitespace-pre-wrap">{character.background || '未填写背景故事'}</p>
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
      <BottomPanel
        open={openPanel === 'skills'}
        onClose={() => setOpenPanel(null)}
        title="技能"
        heightVh={60}
        className="room-play__bottom-panel--character-paper room-play__bottom-panel--skills"
      >
        {character ? (
          <>
            <div className="room-play__skill-tabs" role="group" aria-label="技能分类">
              {[{ key: 'occupation', label: '职业技能' }, { key: 'interest', label: '兴趣技能' }].map((t) => (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setSkillsTab(t.key as typeof skillsTab)}
                  aria-pressed={skillsTab === t.key}
                  className={`room-play__skill-tab ${skillsTab === t.key ? 'is-active' : ''}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            <div className="room-play__skill-grid">
              {(() => {
                const occSkillIds = character.info.occupationId
                  ? [
                      ...(ruleset?.occupations.find(o => o.id === character.info.occupationId)?.skillIds ?? []),
                      ...(character.occupationChoiceSkillIds ?? []),
                    ]
                  : []
                const list = (ruleset?.skills ?? [])
                  .filter((skill) => skillsTab === 'occupation' ? occSkillIds.includes(skill.id) : !occSkillIds.includes(skill.id))
                  .map((skill) => ({
                    skill,
                    value: character.skillFinalValues?.[skill.id] ?? 0,
                  }))
                  .sort((a, b) => b.value - a.value)
                return list.map(({ skill, value }) => (
                  <div
                    key={skill.id}
                    className="room-play__skill-pill"
                    style={skillPillColors(value)}
                  >
                    <span className="room-play__skill-name">{skill.name}</span>
                    <strong className="room-play__skill-value">{value}%</strong>
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
        <div className={`room-play__location-preview ${currentLocationImage ? 'has-image' : ''}`}>
          {currentLocationImage ? (
            <img
              src={currentLocationImage}
              alt=""
              className="room-play__location-image"
              aria-hidden="true"
            />
          ) : (
            <Map className="w-10 h-10 text-text-dim mb-2" />
          )}
          <div className="room-play__location-caption">
          <span className="text-xs text-text-dim">
            {playerView?.scene.name || '等待规则引擎同步当前场景'}
          </span>
          {playerView?.world && (
            <span className="text-[10px] text-text-dim mt-1">
              {TIME_OF_DAY_LABELS[playerView.world.time_of_day]} ·{' '}
              {formatWorldTime(playerView.world.day_index, playerView.world.hour_of_day)}
            </span>
          )}
          </div>
        </div>
        {playerView?.world && (playerView.world.core_resolved || playerView.world.ending_available) && (
          <div
            aria-label="主线进度"
            className="mb-3.5 rounded-md border border-[#c7ad73] bg-[#fffaf0] px-3 py-2"
          >
            <div className="text-xs font-semibold text-brass-dark">
              {playerView.world.ending_id
                ? '本次调查已经结束'
                : playerView.world.ending_available
                  ? '主线已经收束，可以选择如何收尾'
                  : '主线目标已经达成'}
            </div>
            <div className="text-[11px] text-text-muted mt-0.5">
              {playerView.world.ending_id
                ? '你可以回顾已经发生的事，但不能再改变结局。'
                : '继续扮演或主动收束都可以，由你决定何时结束。'}
            </div>
          </div>
        )}
        <div className="h-px bg-border-light mb-3.5" />
        {playerView?.location_context?.position_context && (
          <div
            aria-label="当前位置边界"
            className="mb-3 rounded-md border border-[#c7ad73] bg-[#fffaf0] px-3 py-2"
          >
            <div className="text-xs font-semibold text-brass-dark">
              已抵达：{playerView.location_context.position_context.label}
            </div>
            <div className="mt-0.5 text-[11px] text-text-muted">
              {playerView.location_context.position_context.state === 'locked'
                ? '前方被锁住；当前位置仍保持在门外。'
                : playerView.location_context.position_context.state === 'interaction_required'
                  ? '继续前进前需要先处理这里的交互。'
                  : '前方路线暂时受阻。'}
            </div>
          </div>
        )}
        <h4 className="text-xs font-semibold text-brass-dark mb-2.5">已知地点（按层级）</h4>
        <div className="space-y-1.5">
          {mapLocations.map((loc) => (
            <div key={loc.id} style={{ paddingLeft: `${12 + loc.depth * 18}px` }} className={`flex items-center gap-3 pr-3 py-2 rounded ${
              loc.isCurrent ? 'bg-[rgba(74,138,74,0.06)] border border-[rgba(74,138,74,0.15)]' : 'hover:bg-panel'
            }`}>
              <span className="text-lg">{loc.icon}</span>
              <div className="flex-1">
                <div className="text-sm font-medium text-text-primary">{loc.name}</div>
                <div className="text-[11px] text-text-muted">{loc.desc}</div>
              </div>
              {!loc.isCurrent && loc.access === 'blocked' && (
                <span className="text-[10px] font-semibold text-amber-700 flex-shrink-0">受阻</span>
              )}
              {loc.isCurrent && <span className="text-[10px] font-semibold text-mold flex-shrink-0">▶ 当前位置</span>}
            </div>
          ))}
        </div>
        {playerView?.scene.loose_items?.length ? (
          <>
            <div className="h-px bg-border-light my-3.5" />
            <h4 className="text-xs font-semibold text-brass-dark mb-2.5">当前场景物品</h4>
            <div className="space-y-2">
              {playerView.scene.loose_items.map(item => (
                <div key={item.id} className="rounded-md bg-panel px-3 py-2">
                  <div className="text-sm font-medium text-text-primary">
                    {item.name}{item.quantity > 1 ? ` ×${item.quantity}` : ''}
                  </div>
                  <div className="text-[11px] text-text-muted mt-0.5">
                    状态：{item.condition}
                  </div>
                </div>
              ))}
            </div>
          </>
        ) : null}
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
      <BottomPanel
        open={openPanel === 'notes'}
        onClose={() => setOpenPanel(null)}
        title="速记本"
        heightVh={65}
        className="room-play__bottom-panel--character-paper room-play__bottom-panel--notes"
      >
        <div className="flex gap-2 mb-3">
          <button onClick={() => setNotes(prev => {
              const tag = `[🔍 新线索 ${new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}]`
              const existingNotes = prev.trimStart()
              return existingNotes ? `${tag}\n\n${existingNotes}` : `${tag}\n`
            })}
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
          className="room-play__notes-textarea w-full text-sm text-text-body px-1 py-2 resize-none outline-none font-mono placeholder:text-text-dim"
        />
        <div className="room-play__notes-save-status mt-2 text-right">{lastSaved ? `最后保存: ${lastSaved}` : '尚未保存'}</div>
      </BottomPanel>

      {/* Panel: 主持人语音 */}
      <BottomPanel open={openPanel === 'speech'} onClose={() => setOpenPanel(null)} title="主持人语音">
        {!hostSpeech.available ? (
          <p className="text-sm text-text-dim py-6 text-center">
            {hostSpeech.provider === 'disabled'
              ? '主持人语音模块已加载，但服务端尚未配置语音供应商凭证和音色'
              : '主持人语音服务当前不可用，文本消息和游戏操作仍可正常使用'}
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
              {isHost ? (
                <select
                  aria-label="主持人音色"
                  value={hostSpeech.voiceType ?? ''}
                  onChange={(event) => { void hostSpeech.updateVoice(event.target.value) }}
                  disabled={hostSpeech.voices.length === 0}
                  className="w-full bg-input border border-border-light rounded-md px-3 py-2 text-sm text-text-primary disabled:opacity-50"
                >
                  {hostSpeech.voices.map((voice) => (
                    <option key={voice.voiceType} value={voice.voiceType}>{voice.label}</option>
                  ))}
                </select>
              ) : (
                <div className="w-full bg-panel border border-border-light rounded-md px-3 py-2 text-sm text-text-primary">
                  {hostSpeech.voices.find((voice) => voice.voiceType === hostSpeech.voiceType)?.label ?? hostSpeech.voiceType}
                </div>
              )}
              <span className="block text-[10px] text-text-dim mt-1">情绪由 DouBao TTS 2.0 根据当前句自动表达</span>
            </label>

            <label className="block text-xs text-text-muted">
              播放速度：{hostSpeech.playbackRate.toFixed(2)}×
              <input type="range" min="0.75" max="1.25" step="0.05" value={hostSpeech.playbackRate}
                onChange={(event) => hostSpeech.setPlaybackRate(Number(event.target.value))}
                className="w-full accent-brass" aria-label="主持人语音播放速度" />
            </label>

            <label className="block text-xs text-text-muted">
              音量：{Math.round(hostSpeech.volume * 100)}%
              <input type="range" min="0" max="1" step="0.05" value={hostSpeech.volume}
                onChange={(event) => hostSpeech.setVolume(Number(event.target.value))}
                className="w-full accent-brass" aria-label="主持人语音音量" />
            </label>

            <div className="flex items-center justify-between text-[11px] text-text-muted">
              <span>
                {hostSpeech.status === 'synthesizing' ? '正在合成' : hostSpeech.status === 'buffering' ? '正在缓冲' : hostSpeech.status === 'playing' ? '正在朗读' : hostSpeech.status === 'paused' ? '已暂停' : hostSpeech.status === 'failed' ? '播放失败' : '空闲'}
              </span>
              <span>待播放 {hostSpeech.queueLength} 条</span>
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                aria-label="暂停朗读"
                title="暂停朗读"
                onClick={hostSpeech.pause}
                disabled={hostSpeech.status !== 'playing'}
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
            {hostSpeech.error && <p className="text-xs text-danger">{hostSpeech.error}</p>}
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

        {(playerView?.world.ending_available || (isHost && !playerView)) && (
          <div className="mt-4 pt-4 border-t border-border-light">
            {endError && <p className="text-[11px] text-[#c04040] text-center mb-2">{endError}</p>}
            {confirmEnd ? (
              <div className="space-y-2">
                {endingDraft ? (
                  <div className="rounded-md border border-[#c7ad73] bg-[#fffaf0] p-3">
                    <h4 className="text-sm font-semibold text-brass-dark">{endingDraft.title}</h4>
                    <p className="mt-2 text-xs leading-relaxed text-text-body">{endingDraft.summary}</p>
                    <p className="mt-2 text-xs leading-relaxed text-text-muted">{endingDraft.epilogue}</p>
                  </div>
                ) : (
                  <p className="text-xs text-text-muted text-center">
                    {playerView?.world.ending_available
                      ? '先生成一份基于已提交证据的结局草稿；审阅前不会结束游戏。'
                      : '确定要结束本局游戏吗？结束后将无法再回到聊天室。'}
                  </p>
                )}
                <div className="flex gap-2">
                  <button onClick={() => { setConfirmEnd(false); setEndingDraft(null); endingDraftRequestId.current = randomActionId(); endingConfirmRequestId.current = randomActionId() }} disabled={ending}
                    className="flex-1 py-2 rounded-sm bg-panel border border-border-light text-text-muted text-xs font-medium active:bg-border-light disabled:opacity-60">
                    取消
                  </button>
                  <button onClick={handleEndGame} disabled={ending}
                    className="flex-1 py-2 rounded-sm bg-[#c04040] text-white text-xs font-medium active:bg-[#a03030] disabled:opacity-60">
                    {ending
                      ? endingDraft ? '确认中…' : '生成中…'
                      : endingDraft ? '确认这份结局' : playerView?.world.ending_available ? '生成草稿' : '确认结束'}
                  </button>
                </div>
              </div>
            ) : (
              <button onClick={() => setConfirmEnd(true)}
                className="w-full py-2 rounded-sm bg-transparent text-[#c04040] border border-[#c04040]/40 text-xs font-medium flex items-center justify-center gap-1.5 active:bg-[#c04040]/5">
                <FlagOff className="w-3.5 h-3.5" /> {playerView?.world.ending_available ? '生成结局与后日谈' : '结束游戏'}
              </button>
            )}
          </div>
        )}
      </BottomPanel>

      {/* ── Dice Modal ── */}
      {activePlanId && playerId && (
        <div className="mx-4 mb-3">
          <button
            type="button"
            className="w-full rounded-lg border border-border-light bg-white px-3 py-2 text-xs text-text-muted"
            onClick={() => sdk.roomSocket.cancelActionPlan(playerId, {
              clientActionId: activePlanId,
              requestId: randomActionId(),
            })}
          >
            停止后续行动（已完成步骤会保留）
          </button>
        </div>
      )}
      <CheckWorkflowPanel
        decision={pendingDecisionForUi(pendingAdjudication)}
        checkRun={authoritativeDiceRoll ? null : checkRunForUi(pendingAdjudication)}
        busy={typing}
        onSelectSkill={(candidateId) => {
          if (!playerId || !pendingAdjudication?.pendingDecision) return
          const decision = pendingAdjudication.pendingDecision
          const option = decision.options.find((item) => item.candidate_id === candidateId)
          if (!option) return
          selectedAdjudicationOptionRef.current = {
            correlationId: pendingAdjudication.correlationId,
            option,
          }
          setTyping(true)
          showBackendPhase('waiting_for_check')
          sdk.roomSocket.selectAdjudication(playerId, {
            clientActionId: pendingAdjudication.correlationId,
            requestId: randomActionId(),
            sourceRevision: pendingAdjudication.sourceRevision,
            decisionId: decision.decision_id,
            decisionVersion: decision.decision_version,
            candidateId,
          })
        }}
        onCancel={() => {
          if (!playerId || !pendingAdjudication?.pendingDecision) return
          const decision = pendingAdjudication.pendingDecision
          setTyping(true)
          showBackendPhase('executing_action')
          sdk.roomSocket.selectAdjudication(playerId, {
            clientActionId: pendingAdjudication.correlationId,
            requestId: randomActionId(),
            sourceRevision: pendingAdjudication.sourceRevision,
            decisionId: decision.decision_id,
            decisionVersion: decision.decision_version,
            cancel: true,
          })
          // 选技能之后服务端会回一条新的 adjudication.pending（掷骰结果）把面板换掉，
          // 取消则没有任何东西来接替它：面板要一直等到权威叙事回来才收，而叙事这一
          // 趟是整回合里最慢的。于是"选择检定方式"和"守秘人组织语言中"会同屏并存好
          // 几秒——两个互斥状态一起显示。这个决策在服务端已经作废（取消不可撤销，
          // 重试也只会撞 SOURCE_REVISION_STALE），所以本地立刻收面板；万一取消本身被
          // 拒，turn.failed / error 分支同样会清掉它并给出错误，行为一致。
          setPendingAdjudication(null)
        }}
        onPostRollOption={submitAdjudicationPostRoll}
      />
      <DiceModal
        open={showDice}
        onClose={() => setShowDice(false)}
        onResult={handleDiceResult}
        checkRequest={pendingCheck}
        checkDiceState={pendingCheckDice}
        setCheckDiceState={setPendingCheckDice}
        presetResult={authoritativeDiceRoll?.value ?? null}
        presetDegree={authoritativeDiceRoll?.degree ?? null}
        autoRollKey={
          authoritativeDiceRoll
            ? `${authoritativeDiceRoll.checkId}:${authoritativeDiceRoll.rollCount}`
            : undefined
        }
        postRollOptions={checkRunForUi(pendingAdjudication)?.post_roll_options ?? []}
        luckValue={resourceValue(playerView, 'luck')}
        onPostRollOption={submitAdjudicationPostRoll}
      />
      {showPortraitGenerator && character && roomId && characterId && (
        <PortraitGenerationModal
          roomId={roomId}
          characterId={characterId}
          characterName={character.info.name}
          portraitUrl={playerId ? portraitUrls[playerId] : undefined}
          onClose={() => setShowPortraitGenerator(false)}
        />
      )}
    </div>
  )
}

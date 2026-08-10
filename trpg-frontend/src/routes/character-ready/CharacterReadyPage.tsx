import { useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { PortraitGenerationResult, RoomPlayerSummary } from 'trpg-sdk'
import {
  User,
  UserPlus,
  Eye,
  ImagePlus,
  Heart,
  Brain,
  WandSparkles,
  Sword,
  BicepsFlexed,
  Footprints,
  type LucideIcon,
} from 'lucide-react'
import { useCharacterStore } from '@/stores/character-store'
import { fetchCharacter } from '@/services/character/character-api'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { connectWebSocket, disconnectWebSocket, sdk, waitForWsOpen } from '@/services/api-client'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'
import { usePlayerPortraits } from '@/hooks/usePlayerPortraits'
import { useRuleset } from '@/hooks/useRuleset'
import { PortraitGenerationModal } from './PortraitGenerationModal'
import { DERIVED_STAT_DEFINITIONS, normalizeDerivedStats, type DerivedStatKey } from '@/data/derived-stats'
import { OnboardingTrigger } from '@/features/onboarding'
import { PortraitImage } from '@/features/portrait/PortraitImage'

const SHEET_PAGES = [
  { key: 'info', label: '基本信息' },
  { key: 'skills', label: '技能' },
  { key: 'background', label: '背景装备' },
] as const
const DERIVED_STAT_ICONS: Record<DerivedStatKey, LucideIcon> = {
  hp: Heart,
  san: Brain,
  mp: WandSparkles,
  db: Sword,
  build: BicepsFlexed,
  move: Footprints,
}
const EMPTY_PLAYERS: RoomPlayerSummary[] = []

interface RadarAttribute {
  key: string
  label: string
}

function AttributeRadarChart({
  attributes,
  values,
}: {
  attributes: readonly RadarAttribute[]
  values: Readonly<Partial<Record<string, number>>>
}) {
  if (attributes.length < 3) return null

  const centerX = 180
  const centerY = 155
  const radius = 98
  const labelRadius = 112
  const angleAt = (index: number) => -Math.PI / 2 + (index * Math.PI * 2) / attributes.length
  const pointAt = (index: number, pointRadius: number) => {
    const angle = angleAt(index)
    return `${centerX + Math.cos(angle) * pointRadius},${centerY + Math.sin(angle) * pointRadius}`
  }
  const polygonAt = (pointRadius: number) => attributes.map((_, index) => pointAt(index, pointRadius)).join(' ')
  const resolvedValues = attributes.map((attribute) => {
    const value = values[attribute.key]
    return typeof value === 'number' && Number.isFinite(value) ? value : null
  })
  const completeValues = resolvedValues.every((value): value is number => value !== null)
    ? resolvedValues
    : null
  const valuePolygon = completeValues
    ? completeValues.map((rawValue, index) => {
        const value = Math.max(0, Math.min(100, rawValue))
        return pointAt(index, radius * value / 100)
      }).join(' ')
    : null

  return (
    <div className="character-ready-sheet__radar" data-testid="attribute-radar-chart">
      <svg viewBox="0 28 360 260" role="img" aria-label="基础属性雷达图">
        {[0.25, 0.5, 0.75, 1].map(level => (
          <polygon
            key={level}
            points={polygonAt(radius * level)}
            className="character-ready-sheet__radar-grid"
          />
        ))}
        {attributes.map((attribute, index) => (
          <line
            key={attribute.key}
            x1={centerX}
            y1={centerY}
            x2={centerX + Math.cos(angleAt(index)) * radius}
            y2={centerY + Math.sin(angleAt(index)) * radius}
            className="character-ready-sheet__radar-axis"
          />
        ))}
        {valuePolygon ? (
          <polygon points={valuePolygon} className="character-ready-sheet__radar-value" />
        ) : (
          <text
            x={centerX}
            y={centerY}
            textAnchor="middle"
            dominantBaseline="middle"
            className="character-ready-sheet__radar-empty"
          >
            属性数据不完整
          </text>
        )}
        {attributes.map((attribute, index) => {
          const angle = angleAt(index)
          const x = centerX + Math.cos(angle) * labelRadius
          const y = centerY + Math.sin(angle) * labelRadius
          const anchor = Math.cos(angle) > 0.2 ? 'start' : Math.cos(angle) < -0.2 ? 'end' : 'middle'
          return (
            <text
              key={attribute.key}
              x={x}
              y={y}
              textAnchor={anchor}
              dominantBaseline="middle"
              className="character-ready-sheet__radar-label"
            >
              <tspan>{attribute.label}</tspan>
              <tspan className="character-ready-sheet__radar-number"> {resolvedValues[index] ?? '—'}</tspan>
            </text>
          )
        })}
      </svg>
    </div>
  )
}

function CharacterSheetModal({ character, portraitUrl, onClose }: { character: NonNullable<ReturnType<typeof useCharacterStore.getState>['character']>; portraitUrl?: string; onClose: () => void }) {
  const [page, setPage] = useState<typeof SHEET_PAGES[number]['key']>('info')
  const { ruleset } = useRuleset()
  const occupation = character.info.occupationId
    ? ruleset?.occupations.find(o => o.id === character.info.occupationId)
    : null

  return (
    <>
      <div className="character-ready-sheet-backdrop fixed inset-0 z-30 animate-fade-in" onClick={onClose} />
      <div className="character-ready-sheet fixed inset-x-0 bottom-0 z-40 animate-slide-up max-h-[82vh] overflow-hidden">
        <div className="character-ready-sheet__scroll">
        <div className="character-ready-sheet__header flex items-center justify-between px-5 pt-4 pb-2">
          <h3 className="text-base font-bold text-text-primary">调查员 · <span className="character-ready-sheet__numbered">{character.info.name}</span></h3>
          <button onClick={onClose} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center">
            <svg className="w-4 h-4 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Page tabs */}
        <div className="character-ready-sheet__tabs flex gap-1.5 px-5 pb-3">
          {SHEET_PAGES.map(p => (
            <button key={p.key} onClick={() => setPage(p.key)}
              className={`flex-1 text-center text-[12px] font-semibold py-1.5 rounded-[99px] border transition-all ${
                page === p.key ? 'bg-brass text-white border-brass' : 'bg-panel text-text-muted border-border-light'
              }`}>
              {p.label}
            </button>
          ))}
        </div>

        <div className="character-ready-sheet__content px-5 pb-6 space-y-4">
          {page === 'info' && (
            <>
              <div className="character-ready-sheet__profile">
                <div className="character-ready-sheet__portrait rounded-sm flex items-center justify-center text-2xl overflow-hidden"
                  style={{ background: 'linear-gradient(135deg,#e8e0d0,#d8cfb8)', border: '2px solid #b8976a' }}>
                  {portraitUrl ? (
                    <PortraitImage
                      src={portraitUrl}
                      alt={`${character.info.name}的头像`}
                      buttonClassName="h-full w-full"
                      imageClassName="h-full w-full object-cover"
                    />
                  ) : '🕵️'}
                </div>
                <div className="character-ready-sheet__identity">
                  <div className="character-ready-sheet__identity-name font-bold text-text-primary">{character.info.name}</div>
                  <div className="character-ready-sheet__identity-summary character-ready-sheet__numbered text-text-muted">{character.info.age}岁 · {character.info.gender} · {occupation?.name ?? '未选择职业'}</div>
                  <div className="character-ready-sheet__locations">
                    <span>居住地：{character.info.residence || '—'}</span>
                    <span>出生地：{character.info.birthplace || '—'}</span>
                  </div>
                </div>
              </div>
              <div className="character-ready-sheet__derived" data-testid="derived-stats-grid">
                {DERIVED_STAT_DEFINITIONS.map(definition => {
                  const StatIcon = DERIVED_STAT_ICONS[definition.key]
                  return (
                    <div key={definition.key} className="character-ready-sheet__derived-item">
                      <StatIcon className="character-ready-sheet__derived-icon" aria-hidden="true" />
                      <span className="character-ready-sheet__derived-label">{definition.label}</span>
                      <span
                        className="character-ready-sheet__derived-value character-ready-sheet__numbered"
                        style={{ color: definition.color }}
                      >
                        {character.derived[definition.key] ?? '—'}
                      </span>
                    </div>
                  )
                })}
              </div>
              <div className="character-ready-sheet__attributes">
                <h4 className="character-ready-sheet__section-title">基础属性</h4>
                <AttributeRadarChart attributes={ruleset?.attributes ?? []} values={character.attr} />
              </div>
            </>
          )}

          {page === 'skills' && (
            <div>
              <h4 className="text-[11px] font-semibold text-brass-dark mb-2">全部技能（按数值从高到低）</h4>
              <div className="space-y-1.5">
                {(ruleset?.skills ?? []).map(skill => ({
                  skill,
                  value: character.skillFinalValues?.[skill.id] ?? 0,
                }))
                  .sort((a, b) => b.value - a.value)
                  .map(({ skill, value }) => (
                    <div key={skill.id} className="flex items-center gap-3 py-1">
                      <div className="flex-1 min-w-0 text-[12px] font-medium text-text-primary truncate">{skill.name}</div>
                      <div className="flex-1 h-1.5 rounded-full bg-border-light overflow-hidden">
                        <div className="h-full rounded-full bg-brass transition-all" style={{ width: `${value}%` }} />
                      </div>
                      <span className="text-[11px] font-bold font-mono text-text-muted min-w-[32px] text-right">{value}%</span>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {page === 'background' && (
            <>
              <div>
                <h4 className="text-[11px] font-semibold text-brass-dark mb-2">装备</h4>
                <p className="text-[13px] text-text-primary whitespace-pre-wrap">{character.equipment || '暂未填写'}</p>
              </div>
              <div>
                <h4 className="text-[11px] font-semibold text-brass-dark mb-2">背景故事</h4>
                <p className="text-[13px] text-text-primary whitespace-pre-wrap">{character.background || '暂未填写'}</p>
              </div>
              <div>
                <h4 className="text-[11px] font-semibold text-brass-dark mb-2">备注</h4>
                <p className="text-[13px] text-text-primary whitespace-pre-wrap">{character.notes || '暂未填写'}</p>
              </div>
            </>
          )}
        </div>
        </div>
      </div>
    </>
  )
}

// 第二个等待界面：每个人各自建完卡之后，先看看队友是不是也都建完了，
// 全员建完卡房主才能真正开始游戏（发 game.start），其他人靠轮询房间
// phase 变成 InGame 各自跟上、一起进入聊天室。
export default function CharacterReadyPage() {
  const navigate = useNavigate()
  const [showSelfSheet, setShowSelfSheet] = useState(false)
  const [showPortraitGenerator, setShowPortraitGenerator] = useState(false)
  const [portraitResult, setPortraitResult] = useState<PortraitGenerationResult | null>(null)
  const [portraitVersionOverride, setPortraitVersionOverride] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')
  const roomId = useRoomStore((s) => s.roomId)
  const cachedCharacter = useCharacterStore((s) => (roomId ? s.getForRoom(roomId) : null))
  const characterId = useRoomStore((s) => s.characterId)
  const { ruleset: readyRuleset } = useRuleset()

  // 角色卡以**后端**为准，本地缓存只作首屏占位（issue #96）。
  //
  // 之前这里只读 localStorage：清掉缓存（或换浏览器）后，明明后端有这张卡，
  // 页面却显示成"还没建卡"。现在有了 GET 端点，就该以后端那份为准——本地缓存
  // 保留是为了拉取回来之前不闪空白，不是权威源。
  const [remoteCharacter, setRemoteCharacter] = useState<typeof cachedCharacter>(null)
  useEffect(() => {
    if (!roomId || !characterId || !readyRuleset) return
    let cancelled = false
    fetchCharacter(roomId, characterId)
      .then((saved) => {
        if (cancelled || !saved.name) return
        const occupationId =
          readyRuleset.occupations.find((o) => o.name === saved.occupation)?.id ?? null
        const derived = normalizeDerivedStats(saved.derivedStats ?? {})
        setRemoteCharacter({
          info: {
            name: saved.name,
            playerName: '',
            age: saved.age != null ? String(saved.age) : '',
            gender: saved.gender ?? '',
            residence: saved.residence ?? '',
            birthplace: saved.birthplace ?? '',
            occupationId,
          },
          attr: { ...saved.attributes },
          skillAlloc: {},
          skillFinalValues: { ...saved.skills },
          occupationChoiceSkillIds: saved.occupationChoiceSkillIds ?? [],
          equipment: (saved.equipment ?? []).join('、'),
          background: saved.background ?? '',
          notes: saved.notes ?? '',
          derived,
        })
      })
      .catch(() => {
        // 拉不到就沿用本地缓存（比如还没建过卡），不打断这个页面。
      })
    return () => {
      cancelled = true
    }
  }, [roomId, characterId, readyRuleset])

  const character = remoteCharacter ?? cachedCharacter
  const roomCode = useRoomStore((s) => s.roomCode)
  const isHost = useRoomStore((s) => s.isHost)
  const playerId = useRoomStore((s) => s.playerId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const nickname = useAuthStore((s) => s.nickname)
  const hasCharacter = character !== null
  const info = useRoomPlayers(roomCode)
  const players = info?.players ?? EMPTY_PLAYERS
  // 生图成功响应里的版本先覆盖轮询旧值，使当前玩家无需等待下一轮房间请求。
  const portraitPlayers = useMemo(() => players.map((player) => (
    player.playerId === playerId && portraitVersionOverride
      ? { ...player, hasPortrait: true, portraitVersion: portraitVersionOverride }
      : player
  )), [players, playerId, portraitVersionOverride])
  const portraitUrls = usePlayerPortraits(roomId, reconnectToken, portraitPlayers)
  const allHaveCharacters = players.length > 0 && players.every((p) => p.hasCharacter)
  const advancedRef = useRef(false)

  useEffect(() => {
    const current = players.find((player) => player.playerId === playerId)
    if (portraitVersionOverride && current?.portraitVersion === portraitVersionOverride) {
      // 房间轮询追上刚生成的版本后撤掉临时覆盖，后续跨设备重生成仍能被发现。
      setPortraitVersionOverride(null)
    }
  }, [playerId, players, portraitVersionOverride])

  // ★ 房主点"开始游戏"之后，后端 _on_game_start 会把房间 phase 改成
  // InGame——其他玩家没有 WS 广播可用，只能靠轮询这个字段发现"游戏真的开始
  // 了"，然后自己跟上进 /room，而不是自己一厢情愿地提前进去。
  useEffect(() => {
    if (info?.phase === 'InGame' && !advancedRef.current) {
      advancedRef.current = true
      navigate('/room/play')
    }
  }, [info?.phase, navigate])

  const handleStartGame = async () => {
    if (!isHost || !playerId || !roomId) return
    setStartError('')
    setStarting(true)
    try {
      // ★ 这个页面从来没有主动建立过 WS 连接（只有 LobbyPage 会连）——如果
      // 刷新过页面、或者从没经过 Lobby 直接落到这里，connectWebSocket 拿到
      // 的连接是关闭的，startGame 会静默丢弃 game.start，后端 phase
      // 永远停在 Building，其他玩家会一直卡在轮询里。这里跟 RoomPage 一样，
      // 发 game.start 前先确保连接是通的、且已经 room.join 过（对已经连过
      // 的情况是幂等空操作）。
      const ws = connectWebSocket(roomId)
      await waitForWsOpen(ws)
      sdk.roomSocket.joinRoom(playerId, {
        reconnectToken: reconnectToken || '',
        roomCode,
        nickname: nickname || '玩家',
      })
      sdk.roomSocket.startGame(playerId)
    } catch {
      setStartError('无法开始游戏，请检查连接后重试。')
      setStarting(false)
      return
    }
    // ★ 房主要立刻本地跳转，不能也靠轮询 phase 等——AI 生成开场旁白要好几秒，
    // 但如果房主自己还要等下一次轮询（最多 3 秒）才进 RoomPage，RoomPage
    // 还没挂载、没人订阅 onWsMessage，narration.push 广播到达时就直接被
    // 丢弃收不到了。访客那边则没有这个问题：靠轮询进入的等待时间通常短于
    // AI 生成旁白的时间，RoomPage 大概率已经挂载好在等了。
    advancedRef.current = true
    navigate('/room/play')
  }

  const handleEditCharacter = () => {
    navigate('/room/character', { state: { fromCharacterReady: true } })
  }

  const handleGoBack = () => {
    disconnectWebSocket()
    navigate('/home')
  }

  return (
    <div className="lobby-scene character-ready-scene animate-screen-in">
      <img className="lobby-scene__background" src="/assets/rooms/lobby/background.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__map" src="/assets/rooms/lobby/map.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__note" src="/assets/rooms/lobby/gather-note.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__poster" src="/assets/rooms/lobby/camp-poster.webp" alt="" aria-hidden="true" />

      <header className="lobby-scene__header character-ready-scene__header">
        <button type="button" className="lobby-scene__back" onClick={handleGoBack} aria-label="返回首页">
          <img src="/assets/rooms/create/back-button.webp" alt="" aria-hidden="true" />
        </button>
        <OnboardingTrigger className="character-ready-scene__guide" />
      </header>

      <main className="lobby-scene__dossier character-ready-scene__dossier" aria-labelledby="character-ready-room-code">
        <img className="lobby-scene__dossier-art" src="/assets/rooms/ready/player-dossier.webp" alt="" aria-hidden="true" />

        <section className="lobby-scene__masthead character-ready-scene__masthead" aria-label="房间信息">
          <h1 id="character-ready-room-code" className="lobby-scene__room-code" aria-label={`房间码 ${roomCode || '未获取'}`}>
            {Array.from(roomCode || '------').map((character, index) => (
              <span className={/\d/.test(character) ? 'lobby-scene__room-code-digit' : undefined} key={`${character}-${index}`}>
                {character}
              </span>
            ))}
          </h1>
          <p className="lobby-scene__connection character-ready-scene__connection" aria-live="polite">
            <span className={`lobby-scene__connection-dot ${allHaveCharacters ? 'is-connected' : ''}`} aria-hidden="true" />
            <span className="character-ready-scene__connection-text">
              人物卡准备 · {allHaveCharacters ? '全员已完成' : '等待成员建卡'}
              {info && <span> · {players.length}/{info.maxPlayers} 人</span>}
            </span>
            <span className="character-ready-scene__connection-spacer" aria-hidden="true" />
          </p>
        </section>

        <section className="lobby-scene__roster character-ready-scene__roster" aria-labelledby="character-ready-roster-title">
          <h2 id="character-ready-roster-title" className="sr-only">调查员档案</h2>
          <div className="lobby-scene__player-list character-ready-scene__player-list" data-onboarding-target="player-status" aria-busy={!info}>
            {players.length === 0 && (
              <div className="lobby-player lobby-player--loading" role="status">
                <img className="lobby-player__paper" src="/assets/rooms/lobby/seat.webp" alt="" aria-hidden="true" />
                正在整理调查员档案…
              </div>
            )}
            {players.map((player) => {
              const isSelf = player.playerId === playerId
              return (
                <article
                  key={player.playerId}
                  data-onboarding-target={isSelf ? 'character-summary' : undefined}
                  className={`lobby-player character-ready-player ${player.hasCharacter ? 'is-ready' : ''}`}
                >
                  <img className="lobby-player__paper" src="/assets/rooms/lobby/seat.webp" alt="" aria-hidden="true" />
                  <span className="lobby-player__avatar character-ready-player__avatar">
                    {portraitUrls[player.playerId] ? (
                      <PortraitImage
                        src={portraitUrls[player.playerId]}
                        alt={`${isSelf && character ? character.info.name : player.nickname}的头像`}
                        buttonClassName="h-full w-full"
                        imageClassName="h-full w-full object-cover"
                      />
                    ) : <User aria-hidden="true" />}
                  </span>
                  <span className="lobby-player__identity character-ready-player__identity">
                    <strong title={player.nickname}>{player.nickname}{isSelf && '（你）'}</strong>
                    <small>
                      {isSelf && hasCharacter
                        ? `调查员：${character.info.name}`
                        : player.hasCharacter ? '调查员档案已完成' : '尚未创建调查员档案'}
                    </small>
                  </span>
                  {isSelf && (
                    <span className="character-ready-player__actions">
                      {hasCharacter ? (
                        <>
                          <button type="button" onClick={() => setShowSelfSheet(true)}><Eye /><span>查看</span></button>
                          {characterId && (
                            <button type="button" onClick={() => setShowPortraitGenerator(true)} aria-label="生成角色图片" title="生成角色图片"><ImagePlus /><span>生图</span></button>
                          )}
                          <button type="button" onClick={handleEditCharacter}><span>编辑</span></button>
                        </>
                      ) : (
                        <button type="button" className="is-create" onClick={handleEditCharacter}><UserPlus /><span>创建人物卡</span></button>
                      )}
                    </span>
                  )}
                  {!isSelf && (
                    <span className={`lobby-player__status ${player.hasCharacter ? 'is-ready' : ''}`}>
                      <img src="/assets/rooms/lobby/status-badge.webp" alt="" aria-hidden="true" />
                      <span>{player.hasCharacter ? '已建卡' : '建卡中'}</span>
                    </span>
                  )}
                </article>
              )
            })}
          </div>
        </section>
      </main>

      <footer className="lobby-scene__footer character-ready-scene__footer">
        {startError && <p className="lobby-scene__start-error" role="alert">{startError}</p>}
        {isHost ? (
          <button
            type="button"
            onClick={handleStartGame}
            disabled={!allHaveCharacters || starting}
            data-onboarding-target="start-game"
            className="lobby-scene__start-action"
            aria-describedby="character-ready-action-hint"
          >
            <img src="/assets/rooms/lobby/start-game.webp" alt="" aria-hidden="true" />
            <span className={starting ? 'lobby-scene__start-progress' : 'sr-only'}>{starting ? '进入中…' : '开始游戏'}</span>
          </button>
        ) : (
          <div className="character-ready-scene__waiting-action" aria-describedby="character-ready-action-hint">等待房主开始游戏</div>
        )}
        <p id="character-ready-action-hint" className="lobby-scene__action-hint" aria-live="polite">
          <span aria-hidden="true">✥</span>
          {isHost
            ? allHaveCharacters ? '调查员已经集结完毕，可以开始冒险' : '等待所有玩家完成调查员档案'
            : allHaveCharacters ? '全员已完成建卡，等待房主开始游戏' : '等待其他玩家完成调查员档案'}
          <span aria-hidden="true">✥</span>
        </p>
      </footer>

      {/* Character Sheet Modal */}
      {showSelfSheet && character && (
        <CharacterSheetModal
          character={character}
          portraitUrl={playerId ? portraitUrls[playerId] : undefined}
          onClose={() => setShowSelfSheet(false)}
        />
      )}
      {showPortraitGenerator && character && roomId && characterId && (
        <PortraitGenerationModal
          roomId={roomId}
          characterId={characterId}
          characterName={character.info.name}
          result={portraitResult}
          portraitUrl={playerId ? portraitUrls[playerId] : undefined}
          onResult={(result) => {
            setPortraitResult(result)
            setPortraitVersionOverride(result.portraitVersion)
          }}
          onClose={() => setShowPortraitGenerator(false)}
        />
      )}
    </div>
  )
}

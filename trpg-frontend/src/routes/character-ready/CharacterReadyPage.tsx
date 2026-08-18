import { useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { RoomPlayerSummary } from 'trpg-sdk'
import {
  User,
  UserPlus,
  Eye,
  ImagePlus,
  BookmarkPlus,
  BookmarkCheck,
} from 'lucide-react'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomCharacter } from '@/hooks/useRoomCharacter'
import {
  createCharacterTemplate,
  deleteCharacterTemplate,
  templateDataFromBuilt,
} from '@/services/character/template-api'
import { ApiError, friendlyErrorMessage } from '@/services/api-client'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { connectWebSocket, disconnectWebSocket, sdk, waitForWsOpen } from '@/services/api-client'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'
import { usePlayerPortraits } from '@/hooks/usePlayerPortraits'
import { useRuleset } from '@/hooks/useRuleset'
import { PortraitGenerationModal } from './PortraitGenerationModal'
import { OnboardingTrigger } from '@/features/onboarding'
import { PortraitImage } from '@/features/portrait/PortraitImage'
import { CharacterBasicInfo } from '@/features/character/CharacterBasicInfo'
import { usePortraitGenerationStore } from '@/stores/portrait-generation-store'

const SHEET_PAGES = [
  { key: 'info', label: '基本信息' },
  { key: 'skills', label: '技能' },
  { key: 'background', label: '背景装备' },
] as const
const EMPTY_PLAYERS: RoomPlayerSummary[] = []

function CharacterSheetModal({ character, portraitUrl, onClose }: { character: NonNullable<ReturnType<typeof useCharacterStore.getState>['character']>; portraitUrl?: string; onClose: () => void }) {
  const [page, setPage] = useState<typeof SHEET_PAGES[number]['key']>('info')
  const { ruleset } = useRuleset()
  const occupation = character.info.occupationId
    ? ruleset?.occupations.find(o => o.id === character.info.occupationId)
    : null

  return (
    <>
      <div className="character-ready-sheet-backdrop fixed inset-0 z-30 animate-fade-in" onClick={onClose} />
      <div className="character-ready-sheet fixed inset-x-0 bottom-0 z-40 animate-slide-up overflow-hidden">
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
            <CharacterBasicInfo
              character={character}
              portraitUrl={portraitUrl}
              occupationName={occupation?.name}
              attributes={ruleset?.attributes ?? []}
            />
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
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState('')
  const [confirmExit, setConfirmExit] = useState(false)
  // 「存入卡库」放在这一页而不是建卡向导里（#337）：手动「完成创建」和一键生成
  // 都落在这里，这才是"卡已经建好"的时刻。放在向导第一步时卡还是空的，而且一键
  // 生成会直接跳到本页，那个按钮玩家根本来不及看见。
  const [savingToLibrary, setSavingToLibrary] = useState(false)
  // 存的是"这一次存进去的那张卡库卡的 id"，不是一个布尔。只有记下 id 才撤得掉：
  // 存卡每次都会新建一条卡库记录，撤销就是把刚建的那条删掉。
  const [savedTemplateId, setSavedTemplateId] = useState<string | null>(null)
  const [libraryError, setLibraryError] = useState('')
  const cancelExitRef = useRef<HTMLButtonElement>(null)
  const roomId = useRoomStore((s) => s.roomId)
  const characterId = useRoomStore((s) => s.characterId)
  const { ruleset: readyRuleset } = useRuleset()
  // 以后端为准、缓存只作首屏占位（issue #96）。这段逻辑原本就长在这一页，#337
  // 之后抽成了 hook——游戏内的 RoomPage 需要同一份，那里原来只读本地缓存。
  const { character, basedOnTemplateId } = useRoomCharacter()
  // 这张房间卡是从卡库播种来的，那它**本来就在卡库里**，按钮一进来就该是"已存卡"。
  //
  // 不能只靠内容哈希判断：卡库里那张可能是服务端背书的 roll，而重新保存时客户端
  // 不被允许声称 roll（会被压成 pointbuy），内容必然不同，永远判不出"存过"——
  // 实测就是这样多出一张重复卡的。出处才是可靠判据。
  const alreadyInLibrary = savedTemplateId ?? basedOnTemplateId
  // 从卡库播种的房间卡只是源卡的一份拷贝，准备页只能显示“已存卡”状态，不能把
  // 源卡当成当前页面可撤销的新保存记录。只有本页刚创建的 savedTemplateId 可撤销。
  const librarySourceIsReadOnly = savedTemplateId === null && basedOnTemplateId !== null
  const libraryButtonLabel = librarySourceIsReadOnly
    ? '这张调查员已在我的角色卡库'
    : alreadyInLibrary
      ? '已存进我的角色卡库，点击撤销'
      : '把这张调查员存进我的角色卡库'
  const libraryButtonTitle = librarySourceIsReadOnly
    ? '这张房间角色来自我的角色卡库，源卡会一直保留'
    : alreadyInLibrary
      ? '已存进卡库，点击把刚存的这张删掉'
      : '存进我的角色卡库，下次开局可以直接选'
  const roomCode = useRoomStore((s) => s.roomCode)
  const isHost = useRoomStore((s) => s.isHost)
  const playerId = useRoomStore((s) => s.playerId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const portraitVersionOverride = usePortraitGenerationStore((s) => roomId ? s.portraitVersions[roomId] : undefined)
  const clearPortraitVersion = usePortraitGenerationStore((s) => s.clearPortraitVersion)
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
    if (roomId && portraitVersionOverride && current?.portraitVersion === portraitVersionOverride) {
      clearPortraitVersion(roomId)
    }
  }, [roomId, playerId, players, portraitVersionOverride, clearPortraitVersion])

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

  const handleToggleLibrary = async () => {
    if (!character || savingToLibrary || librarySourceIsReadOnly) return
    setSavingToLibrary(true)
    setLibraryError('')
    // 已经存过就是撤销：删掉刚才那一条。存卡每次新建一条记录，所以撤销只需要
    // 删掉这次建的，不会碰到玩家卡库里别的卡。
    if (savedTemplateId) {
      try {
        await deleteCharacterTemplate(savedTemplateId)
        setSavedTemplateId(null)
        setLibraryError('')
      } catch (err) {
        setLibraryError(friendlyErrorMessage(err, '取消存卡失败'))
      } finally {
        setSavingToLibrary(false)
      }
      return
    }
    try {
      // 这一页拿到的是已经完成的卡：`skillFinalValues` 就是后端权威算过的最终值，
      // 不需要再跑一次 preview。
      const saved = await createCharacterTemplate(
        character.info.name.trim() || '未命名调查员',
        templateDataFromBuilt({
          name: character.info.name,
          age: character.info.age ? Number(character.info.age) : null,
          gender: character.info.gender || null,
          residence: character.info.residence,
          birthplace: character.info.birthplace,
          attr: character.attr,
          derived: character.derived,
          skillValues: character.skillFinalValues ?? {},
          occupationChoiceSkillIds: character.occupationChoiceSkillIds ?? [],
          equipment: character.equipment,
          occupationName:
            readyRuleset?.occupations.find((o) => o.id === character.info.occupationId)?.name ?? null,
          background: character.background,
          notes: character.notes,
        }),
      )
      setSavedTemplateId(saved.templateId)
    } catch (err) {
      // 卡库里已经有一张一模一样的（比如刷新后又点了一次）。这不是失败——那张卡
      // 就在库里。如实说明，并把按钮指向既有那张，撤销依然可用。
      if (err instanceof ApiError && err.code === 'CHARACTER_TEMPLATE_DUPLICATE') {
        const existingId = err.details?.[0]?.templateId
        if (existingId) setSavedTemplateId(existingId)
        setLibraryError('这张角色卡已经在卡库里了，没有重复保存。')
      } else {
        setLibraryError(friendlyErrorMessage(err, '存入角色卡库失败'))
      }
    } finally {
      setSavingToLibrary(false)
    }
  }

  const handleEditCharacter = () => {
    navigate('/room/character', { state: { fromCharacterReady: true } })
  }

  const handleGoBack = () => {
    setConfirmExit(true)
  }

  const handleConfirmExit = () => {
    disconnectWebSocket()
    navigate('/home')
  }

  useEffect(() => {
    if (!confirmExit) return
    cancelExitRef.current?.focus()
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setConfirmExit(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [confirmExit])

  return (
    <div className="lobby-scene character-ready-scene animate-screen-in">
      <div className="lobby-scene__artboard character-ready-scene__artboard">
      <img className="lobby-scene__background" src="/assets/rooms/lobby/background.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__map" src="/assets/rooms/lobby/map.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__note" src="/assets/rooms/lobby/gather-note.webp" alt="" aria-hidden="true" />
      <img className="lobby-scene__poster" src="/assets/rooms/lobby/camp-poster.webp" alt="" aria-hidden="true" />

      <header className="lobby-scene__header character-ready-scene__header">
        <button type="button" className="lobby-scene__back" onClick={handleGoBack} aria-label="退出房间">
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
                          <button
                            type="button"
                            onClick={handleToggleLibrary}
                            disabled={savingToLibrary || librarySourceIsReadOnly}
                            aria-pressed={alreadyInLibrary !== null}
                            aria-label={libraryButtonLabel}
                            title={libraryButtonTitle}
                          >
                            {alreadyInLibrary ? <BookmarkCheck /> : <BookmarkPlus />}
                            <span>
                              {savingToLibrary ? '处理中' : alreadyInLibrary ? '已存卡' : '存卡'}
                            </span>
                          </button>
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
        {libraryError && <p className="lobby-scene__start-error" role="alert">{libraryError}</p>}
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
      </div>

      {confirmExit && (
        <div className="lobby-leave-dialog" onMouseDown={() => setConfirmExit(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="character-ready-exit-title"
            className="lobby-leave-dialog__paper"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <img
              className="lobby-leave-dialog__art"
              src="/assets/rooms/lobby/leave-dialog.webp"
              alt=""
              aria-hidden="true"
            />
            <span className="lobby-leave-dialog__eyebrow">调查员档案</span>
            <h2 id="character-ready-exit-title">退出房间？</h2>
            <div className="lobby-leave-dialog__divider" aria-hidden="true"><span>◆</span></div>
            <p>确定要退出房间吗？房间会保留，之后可以从「我的游戏」继续。</p>
            <div className="lobby-leave-dialog__actions">
              <button ref={cancelExitRef} type="button" onClick={() => setConfirmExit(false)}>取消</button>
              <button type="button" className="is-danger" onClick={handleConfirmExit}>确认退出</button>
            </div>
          </section>
        </div>
      )}

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
          portraitUrl={playerId ? portraitUrls[playerId] : undefined}
          onClose={() => setShowPortraitGenerator(false)}
        />
      )}
    </div>
  )
}

import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import type { ModuleDetail } from 'trpg-sdk'
import { Plus, Minus } from 'lucide-react'
import { ModuleCover } from '@/components/ModuleCover'
import { FIXED_TRPG } from '@/config/games'
import { ROUTES } from '@/config/routes'
import { useGameStore } from '@/stores/game-store'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { createGameRoom, getModuleDetail, selectModule } from '@/services/room'
import { friendlyErrorMessage } from '@/services/api-client'

const MIN_PLAYERS = 1
// 与后端 RoomCreate.room_name 的 max_length=200 以及 rooms.room_name 的
// String(200) 保持一致，避免前端静默拒绝 API 本来允许的房间名。
const MAX_ROOM_NAME_LENGTH = 200
// 后端 RoomCreate.max_players 的校验是 le=20（trpg-backend/app/dto/room.py），
// 这里的加减号/输入框都要跟着限制到 20，否则提交时只会收到一个 422（见
// PR #67 review）。
const MAX_PLAYERS = 20

export function clampPlayerCount(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

export default function CreateRoomPage() {
  const navigate = useNavigate()
  const store = useGameStore()
  const nickname = useAuthStore((s) => s.nickname)
  const setRoomIdentity = useRoomStore((s) => s.setRoomIdentity)
  const setStoreModuleId = useRoomStore((s) => s.setModuleId)
  const setCreateForm = useRoomStore((s) => s.setCreateForm)
  const setHost = useRoomStore((s) => s.setHost)
  const savedRoomName = useRoomStore((s) => s.createFormRoomName)
  const savedMaxPlayers = useRoomStore((s) => s.createFormMaxPlayers)
  const [roomName, setRoomName] = useState(savedRoomName || '')
  const [maxPlayers, setMaxPlayers] = useState(savedMaxPlayers || 4)
  const [maxPlayersInput, setMaxPlayersInput] = useState(String(savedMaxPlayers || 4))
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState('')

  const [selectedScenario, setSelectedScenario] = useState<ModuleDetail | null>(null)
  const [scenarioStatus, setScenarioStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const [scenarioError, setScenarioError] = useState('')
  const hasSelection = !!store.sceneId
  const playerMin = selectedScenario?.playersMin ?? MIN_PLAYERS
  const playerMax = selectedScenario?.playersMax ?? MAX_PLAYERS

  useEffect(() => {
    if (!store.sceneId) {
      setSelectedScenario(null)
      setScenarioStatus('idle')
      setScenarioError('')
      return
    }
    let cancelled = false
    setSelectedScenario(null)
    setScenarioStatus('loading')
    setScenarioError('')
    getModuleDetail(store.sceneId)
      .then((module) => {
        if (!cancelled) {
          setSelectedScenario(module)
          setScenarioStatus('ready')
        }
      })
      .catch((error) => {
        if (!cancelled) {
          setSelectedScenario(null)
          setScenarioStatus('error')
          setScenarioError(friendlyErrorMessage(error, '模组详情加载失败'))
        }
      })
    return () => {
      cancelled = true
    }
  }, [store.sceneId])

  useEffect(() => {
    if (!selectedScenario) return
    const next = clampPlayerCount(maxPlayers, selectedScenario.playersMin, selectedScenario.playersMax)
    setMaxPlayers(next)
    setMaxPlayersInput(String(next))
  }, [maxPlayers, selectedScenario])

  const handleCreate = async () => {
    if (!roomName.trim() || !hasSelection || !selectedScenario) return
    setCreating(true)
    setCreateError('')
    try {
      const room = await createGameRoom(nickname || undefined, roomName.trim(), maxPlayers)
      // 必须先把房间身份（含 reconnectToken）写进 store，selectModule 等
      // 需要重连凭证的接口才能读到它——见 issue #66，真机联调时发现的顺序 bug。
      setRoomIdentity(room)
      if (!store.sceneId) throw new Error('请先选择模组')
      await selectModule(room.roomId, store.sceneId)
      setStoreModuleId(store.sceneId)
      setHost(true)
      navigate('/room/lobby')
    } catch (err) {
      setCreateError(friendlyErrorMessage(err, '创建房间失败'))
    } finally {
      setCreating(false)
    }
  }

  const canCreate = roomName.trim().length > 0 && hasSelection && !!selectedScenario && !creating

  const handleSelectModule = () => {
    // 输入框允许用户在编辑过程中暂时留空，因此数值 state 会在 blur 时才同步。
    // 点击模组入口本身会触发 blur，但 React 可能把 blur/click 放在同一批更新中，
    // 这里直接从当前输入文本归一化，确保刚输入的人数也能跨页面保留。
    const parsedMaxPlayers = parseInt(maxPlayersInput, 10)
    const nextMaxPlayers = Number.isNaN(parsedMaxPlayers)
      ? maxPlayers
      : clampPlayerCount(parsedMaxPlayers, playerMin, playerMax)
    setMaxPlayers(nextMaxPlayers)
    setMaxPlayersInput(String(nextMaxPlayers))
    setCreateForm({ roomName, maxPlayers: nextMaxPlayers })
    navigate(ROUTES.MODULES)
  }

  const stampLabel = selectedScenario
    ? `更改模组：${selectedScenario.title}`
    : scenarioStatus === 'loading'
      ? '正在加载已选模组'
      : scenarioStatus === 'error'
        ? `更改模组：当前模组加载失败，${scenarioError}`
        : '选择模组'

  return (
    <div className="create-room-scene animate-screen-in">
      <div className="create-room-scene__artboard">
      <img
        className="create-room-scene__background"
        src="/assets/rooms/create/background.webp"
        alt=""
        aria-hidden="true"
      />

      <header className="create-room-scene__header">
        <button
          type="button"
          className="create-room-scene__back"
          aria-label="返回首页"
          onClick={() => {
            store.reset()
            setCreateForm({ roomName: '', maxPlayers: 4 })
            navigate('/home')
          }}
        >
          <img src="/assets/rooms/create/back-button.webp" alt="" aria-hidden="true" />
        </button>
        <h1 className="sr-only">创建房间</h1>
        <img
          className="create-room-scene__page-title"
          src="/assets/rooms/create/page-title.webp"
          alt=""
          aria-hidden="true"
        />
      </header>

      <section className="create-room-scene__settings" aria-labelledby="room-settings-title">
        <img
          className="create-room-scene__archive"
          src="/assets/rooms/create/archive.webp"
          alt=""
          aria-hidden="true"
        />
        <h2 id="room-settings-title" className="sr-only">房间设置</h2>
        <img
          className="create-room-scene__settings-title"
          src="/assets/rooms/create/settings-title.webp"
          alt=""
          aria-hidden="true"
        />

        <label className="create-room-scene__room-name-label" htmlFor="create-room-name">
          房间名称
        </label>
        <input
          id="create-room-name"
          className="create-room-scene__room-name-input"
          value={roomName}
          maxLength={MAX_ROOM_NAME_LENGTH}
          onChange={(event) => setRoomName(event.target.value)}
          placeholder="请输入一个房间名"
          autoComplete="off"
        />

        <span className="create-room-scene__player-label">最大人数</span>
        <span className="create-room-scene__player-hint">
          {selectedScenario
            ? `本模组要求 ${playerMin === playerMax ? playerMin : `${playerMin}-${playerMax}`} 人`
            : `最多 ${MAX_PLAYERS} 人`}
        </span>
        <div className="create-room-scene__player-control">
          <button
            type="button"
            aria-label="减少人数"
            onClick={() => {
              const next = Math.max(playerMin, maxPlayers - 1)
              setMaxPlayers(next)
              setMaxPlayersInput(String(next))
            }}
            disabled={maxPlayers <= playerMin}
          >
            <Minus aria-hidden="true" />
          </button>
          <div className="create-room-scene__player-value">
            <input
              type="number"
              inputMode="numeric"
              aria-label="人数上限"
              min={playerMin}
              max={playerMax}
              value={maxPlayersInput}
              onChange={(event) => setMaxPlayersInput(event.target.value)}
              onBlur={() => {
                const value = parseInt(maxPlayersInput, 10)
                const clamped = Number.isNaN(value)
                  ? maxPlayers
                  : clampPlayerCount(value, playerMin, playerMax)
                setMaxPlayers(clamped)
                setMaxPlayersInput(String(clamped))
              }}
            />
            <span>人</span>
          </div>
          <button
            type="button"
            aria-label="增加人数"
            onClick={() => {
              const next = Math.min(playerMax, maxPlayers + 1)
              setMaxPlayers(next)
              setMaxPlayersInput(String(next))
            }}
            disabled={maxPlayers >= playerMax}
          >
            <Plus aria-hidden="true" />
          </button>
        </div>
      </section>

      <button
        type="button"
        className="create-room-scene__game-stamp"
        aria-label={stampLabel}
        onClick={handleSelectModule}
      >
        <img
          className="create-room-scene__stamp-paper"
          src="/assets/rooms/create/game-stamp.webp"
          alt=""
          aria-hidden="true"
        />
        {scenarioStatus === 'ready' && selectedScenario && store.sceneId ? (
          <span className="create-room-scene__selected-module">
            <ModuleCover
              moduleId={store.sceneId}
              title={selectedScenario.title}
              className="create-room-scene__selected-module-cover"
              imageClassName="create-room-scene__selected-module-cover-image"
              framed={false}
            />
            <span className="create-room-scene__selected-module-copy">
              <strong>{selectedScenario.title}</strong>
              <span>更改模组</span>
            </span>
          </span>
        ) : scenarioStatus === 'loading' ? (
          <span className="create-room-scene__module-status" aria-live="polite">
            <span className="create-room-scene__module-spinner" aria-hidden="true" />
            <strong>正在加载模组</strong>
            <span>请稍候…</span>
          </span>
        ) : scenarioStatus === 'error' ? (
          <span className="create-room-scene__module-status create-room-scene__module-status--error" role="alert">
            <strong>模组加载失败</strong>
            <span>前往更改模组</span>
          </span>
        ) : (
          <>
            <img
              className="create-room-scene__dice"
              src="/assets/rooms/create/dice.webp"
              alt=""
              aria-hidden="true"
            />
            <span className="create-room-scene__select-module-title" aria-hidden="true">
              选择模组
            </span>
          </>
        )}
      </button>

      <img
        className="create-room-scene__cat"
        src="/assets/rooms/create/detective-cat.webp"
        alt=""
        aria-hidden="true"
      />

      <section className="create-room-scene__summary" aria-labelledby="room-summary-title">
        <img
          className="create-room-scene__folder"
          src="/assets/rooms/create/folder.webp"
          alt=""
          aria-hidden="true"
        />
        <img
          className="create-room-scene__summary-flourish create-room-scene__summary-flourish--left"
          src="/assets/rooms/create/summary-flourish.webp"
          alt=""
          aria-hidden="true"
        />
        <img
          className="create-room-scene__summary-flourish create-room-scene__summary-flourish--right"
          src="/assets/rooms/create/summary-flourish.webp"
          alt=""
          aria-hidden="true"
        />
        <h2 id="room-summary-title" className="sr-only">房间概览</h2>
        <img
          className="create-room-scene__summary-title"
          src="/assets/rooms/create/summary-title.webp"
          alt=""
          aria-hidden="true"
        />

        <dl className="create-room-scene__summary-list">
          <div><dt>房间名</dt><dd>{roomName || '未设置'}</dd></div>
          <div><dt>游戏</dt><dd>{FIXED_TRPG.gameName}</dd></div>
          <div><dt>规则</dt><dd>{FIXED_TRPG.systemCatalogName}</dd></div>
          <div><dt>模组</dt><dd>{selectedScenario?.title || store.sceneId || '未选择'}</dd></div>
          <div>
            <dt>人数上限</dt>
            <dd className="create-room-scene__summary-player-limit">
              <span>{maxPlayers}</span><span>人</span>
            </dd>
          </div>
        </dl>
      </section>

      <img
        className="create-room-scene__folder-tie"
        src="/assets/rooms/create/folder-tie.webp"
        alt=""
        aria-hidden="true"
      />

      {createError && (
        <p className="create-room-scene__error" role="alert">{createError}</p>
      )}
      <button
        type="button"
        className="create-room-scene__create"
        onClick={handleCreate}
        disabled={!canCreate}
        aria-label={creating ? '创建中' : '创建房间'}
      >
        <img src="/assets/rooms/create/create-button.webp" alt="" aria-hidden="true" />
        {creating && <span>创建中…</span>}
      </button>
      </div>
    </div>
  )
}

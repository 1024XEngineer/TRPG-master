import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import type { ModuleDetail } from 'trpg-sdk'
import { Plus, Minus } from 'lucide-react'
import { GAME_REGISTRY, getSystemVisualKey, SYSTEM_COLORS } from '@/config/games'
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

  const selectedGame = store.gameId ? GAME_REGISTRY.find(g => g.id === store.gameId) : null
  const [selectedScenario, setSelectedScenario] = useState<ModuleDetail | null>(null)
  const sysColors = store.systemId
    ? SYSTEM_COLORS[getSystemVisualKey(selectedScenario?.gameSystemName || store.systemId)]
    : null
  const hasSelection = !!(store.gameId && store.systemId && store.sceneId)
  const playerMin = selectedScenario?.playersMin ?? MIN_PLAYERS
  const playerMax = selectedScenario?.playersMax ?? MAX_PLAYERS

  useEffect(() => {
    if (!store.sceneId) {
      setSelectedScenario(null)
      return
    }
    let cancelled = false
    getModuleDetail(store.sceneId)
      .then((module) => {
        if (!cancelled) setSelectedScenario(module)
      })
      .catch(() => {
        if (!cancelled) setSelectedScenario(null)
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

  const handleSelectGame = () => {
    setCreateForm({ roomName, maxPlayers })
    store.reset()
    store.setReturnFromGameSelect(true)
    navigate('/home/create/games')
  }

  const handleChangeGame = () => {
    setCreateForm({ roomName, maxPlayers })
    store.reset()
    store.setReturnFromGameSelect(true)
    navigate('/home/create/games')
  }

  return (
    <div className="create-room-scene animate-screen-in">
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
        aria-label={hasSelection ? '更换游戏' : '选择游戏'}
        onClick={hasSelection ? handleChangeGame : handleSelectGame}
      >
        <img
          className="create-room-scene__stamp-paper"
          src="/assets/rooms/create/game-stamp.webp"
          alt=""
          aria-hidden="true"
        />
        <img
          className="create-room-scene__dice"
          src="/assets/rooms/create/dice.webp"
          alt=""
          aria-hidden="true"
        />
        <img
          className="create-room-scene__select-game-title"
          src="/assets/rooms/create/select-game-title.webp"
          alt=""
          aria-hidden="true"
        />
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
          <div><dt>游戏</dt><dd>{selectedGame?.name || store.gameId || '未选择'}</dd></div>
          <div><dt>规则</dt><dd>{sysColors?.name || store.systemId || '未选择'}</dd></div>
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
  )
}

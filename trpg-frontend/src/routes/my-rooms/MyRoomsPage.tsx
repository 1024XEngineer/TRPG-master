import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  BookOpen,
  ChevronRight,
  CircleUserRound,
  Hash,
  PawPrint,
  Play,
  Plus,
  RotateCcw,
  ScrollText,
} from 'lucide-react'
import { listMyRooms, joinRoomByCode, getRoomInfo, type MyRoomSummary } from '@/services/room'
import { friendlyErrorMessage } from '@/services/api-client'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import { archiveNumber } from '@/utils/archive-number'

const PHASE_LABEL: Record<string, string> = {
  Lobby: '大厅等待中',
  Building: '角色准备中',
  InGame: '游戏进行中',
  Suspended: '游戏已挂起',
  Completed: '游戏已完成',
}

const RESUME_ROUTE: Record<string, string> = {
  Lobby: '/room/lobby',
  Building: '/room/ready',
  InGame: '/room/play',
  Suspended: '/room/play',
}

const ROOM_SCENES = [
  '/assets/rooms/play/location-library.webp',
  '/assets/rooms/play/location-cemetery.webp',
  '/assets/rooms/play/location-kimball-study.webp',
  '/assets/rooms/play/location-neighborhood.webp',
  '/assets/rooms/play/location-newspaper-office.webp',
  '/assets/rooms/play/location-surveillance-point.webp',
  '/assets/rooms/play/location-thomas-office.webp',
  '/assets/rooms/play/location-arnoldsburg-streets.webp',
]

export function formatRoomDate(timestamp: string): string {
  const parsed = Date.parse(timestamp)
  if (Number.isNaN(parsed)) return '未知时间'
  return new Date(parsed).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
  })
}

export function roomScene(roomId: string): string {
  let hash = 0
  for (const character of roomId) hash = (hash * 31 + character.charCodeAt(0)) >>> 0
  return ROOM_SCENES[hash % ROOM_SCENES.length]
}

export function renderRoomName(roomName: string) {
  return roomName.split(/(\d+)/g).map((part, index) => (
    <span className={/^\d+$/.test(part) ? 'my-games-scene__record-number' : undefined} key={`${part}-${index}`}>
      {part}
    </span>
  ))
}

export default function MyRoomsPage() {
  const navigate = useNavigate()
  const userId = useAuthStore((state) => state.userId)
  const nickname = useAuthStore((state) => state.nickname)
  const setRoomIdentity = useRoomStore((state) => state.setRoomIdentity)
  const setModuleId = useRoomStore((state) => state.setModuleId)
  const setHost = useRoomStore((state) => state.setHost)
  const [rooms, setRooms] = useState<MyRoomSummary[] | null>(null)
  const [error, setError] = useState('')
  const [resumingCode, setResumingCode] = useState<string | null>(null)

  const loadRooms = useCallback(async () => {
    setRooms(null)
    setError('')
    try {
      setRooms(await listMyRooms())
    } catch (caughtError) {
      setError(friendlyErrorMessage(caughtError, '加载房间列表失败'))
    }
  }, [])

  useEffect(() => {
    void loadRooms()
  }, [loadRooms])

  const handleResume = async (room: MyRoomSummary) => {
    if (resumingCode) return
    setResumingCode(room.roomCode)
    setError('')
    try {
      const identity = await joinRoomByCode(room.roomCode, nickname || undefined)
      const info = await getRoomInfo(room.roomCode)
      const me = info.players.find((player) => player.playerId === identity.playerId)
      setRoomIdentity(identity)
      if (info.moduleId) setModuleId(info.moduleId)
      setHost(me?.isHost ?? false)
      navigate(RESUME_ROUTE[room.phase] ?? '/room/lobby')
    } catch (caughtError) {
      setError(friendlyErrorMessage(caughtError, '继续游戏失败'))
    } finally {
      setResumingCode(null)
    }
  }

  return (
    <section className="my-games-scene" aria-labelledby="my-games-title">
      <div className="my-games-scene__artboard">
        <img
          className="my-games-scene__background"
          src="/assets/rooms/my-games/background.webp"
          alt=""
          aria-hidden="true"
          width={853}
          height={1844}
        />

        <button
          type="button"
          className="my-games-scene__back"
          onClick={() => navigate('/home')}
          aria-label="返回首页"
        >
          <ArrowLeft aria-hidden="true" />
        </button>

        <header className="my-games-scene__header">
          <PawPrint aria-hidden="true" />
          <h1 id="my-games-title">我的游戏</h1>
          <PawPrint aria-hidden="true" />
        </header>

        <img
          className="my-games-scene__case-note"
          src="/assets/rooms/my-games/cat-poster.webp"
          alt=""
          aria-hidden="true"
          width={320}
          height={481}
        />

        <section className="my-games-scene__identity" aria-label="当前玩家档案">
          <img
            src="/assets/rooms/my-games/cat-avatar.webp"
            alt="当前玩家头像"
            width={193}
            height={224}
          />
          <div className="my-games-scene__identity-copy">
            <strong title={nickname || '未设置昵称'}>{nickname || '未设置昵称'}</strong>
            <span>
              <PawPrint aria-hidden="true" />
              调查员编号：<b>{archiveNumber(userId)}</b>
            </span>
          </div>
          <div className="my-games-scene__identity-actions">
            <button
              type="button"
              className="my-games-scene__profile"
              onClick={() => navigate('/home/profile')}
            >
              <CircleUserRound aria-hidden="true" />
              <span>个人档案</span>
              <ChevronRight aria-hidden="true" />
            </button>
            <button
              type="button"
              className="my-games-scene__character-library"
              onClick={() => navigate('/home/characters')}
            >
              <BookOpen aria-hidden="true" />
              <span>角色卡管理</span>
              <ChevronRight aria-hidden="true" />
            </button>
          </div>
        </section>

        <section className="my-games-scene__records" aria-labelledby="recent-games-title">
          <div className="my-games-scene__section-title">
            <span />
            <div>
              <PawPrint aria-hidden="true" />
              <h2 id="recent-games-title">最近游戏</h2>
              <PawPrint aria-hidden="true" />
            </div>
            <span />
          </div>

          {error && (
            <div className="my-games-scene__error" role="alert">
              <span>{error}</span>
              {rooms === null && (
                <button type="button" onClick={() => void loadRooms()}>
                  <RotateCcw aria-hidden="true" />
                  重试
                </button>
              )}
            </div>
          )}

          {rooms === null && !error && (
            <div className="my-games-scene__loading" role="status" aria-label="正在加载游戏记录">
              {[0, 1, 2, 3].map((item) => <span key={item} />)}
            </div>
          )}

          {rooms?.length === 0 && (
            <div className="my-games-scene__empty">
              <ScrollText aria-hidden="true" />
              <p>档案中还没有游戏记录</p>
              <div>
                <button type="button" onClick={() => navigate('/home/create')}>
                  <Plus aria-hidden="true" />
                  创建房间
                </button>
                <button type="button" onClick={() => navigate('/home/join')}>
                  <Hash aria-hidden="true" />
                  加入房间
                </button>
              </div>
            </div>
          )}

          {rooms && rooms.length > 0 && (
            <>
              <div className="my-games-scene__list" role="list" aria-busy={Boolean(resumingCode)}>
                {rooms.map((room) => {
                  const completed = room.phase === 'Completed'
                  const busy = resumingCode === room.roomCode
                  return (
                    <article className="my-games-scene__record" role="listitem" key={room.roomCode}>
                      <div className="my-games-scene__thumbnail">
                        <img src={roomScene(room.roomId)} alt="" aria-hidden="true" />
                      </div>
                      <div className="my-games-scene__record-copy">
                        <h3 title={room.roomName}>{renderRoomName(room.roomName)}</h3>
                        <p>
                          <span title={room.moduleTitle || '尚未选择模组'}>
                            {room.moduleTitle || '尚未选择模组'}
                          </span>
                          <i aria-hidden="true">·</i>
                          <span>{PHASE_LABEL[room.phase] || room.phase}</span>
                          <i aria-hidden="true">·</i>
                          <time className="my-games-scene__record-number" dateTime={room.updatedAt}>
                            {formatRoomDate(room.updatedAt)}
                          </time>
                        </p>
                      </div>
                      <button
                        type="button"
                        className={completed ? 'is-review' : undefined}
                        disabled={!completed && Boolean(resumingCode)}
                        onClick={() => {
                          if (completed) navigate(`/home/my-rooms/review/${room.roomCode}`)
                          else void handleResume(room)
                        }}
                        aria-label={completed ? `查看${room.roomName}的复盘` : `继续${room.roomName}`}
                      >
                        {completed ? <ScrollText aria-hidden="true" /> : <Play aria-hidden="true" />}
                        <span>{completed ? '复盘' : busy ? '进入中' : '继续'}</span>
                      </button>
                    </article>
                  )
                })}
              </div>
              <div className="my-games-scene__end" role="status">
                <span />
                <PawPrint aria-hidden="true" />
                已加载全部记录
                <PawPrint aria-hidden="true" />
                <span />
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  )
}

import { useRef, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { friendlyErrorMessage } from '@/services/api-client'
import { joinRoomByCode } from '@/services/room'
import { useAuthStore } from '@/stores/auth-store'
import { useRoomStore } from '@/stores/room-store'
import './JoinRoomPage.css'

const ROOM_CODE_LENGTH = 6

export function normalizeRoomCode(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, ROOM_CODE_LENGTH)
}

export default function JoinRoomPage() {
  const navigate = useNavigate()
  const nickname = useAuthStore((state) => state.nickname)
  const setRoomIdentity = useRoomStore((state) => state.setRoomIdentity)
  const setHost = useRoomStore((state) => state.setHost)
  const joiningRef = useRef(false)
  const [roomCode, setRoomCode] = useState('')
  const [error, setError] = useState('')
  const [joining, setJoining] = useState(false)
  const [inputFocused, setInputFocused] = useState(false)

  const canJoin = roomCode.length === ROOM_CODE_LENGTH && !joining

  const handleJoin = async () => {
    const code = normalizeRoomCode(roomCode)
    if (code.length !== ROOM_CODE_LENGTH || joiningRef.current) return

    joiningRef.current = true
    setError('')
    setJoining(true)
    try {
      const room = await joinRoomByCode(code, nickname || undefined)
      setRoomIdentity(room)
      setHost(false)
      navigate('/room/lobby')
    } catch (err) {
      setError(friendlyErrorMessage(err, '加入房间失败，请稍后重试'))
    } finally {
      joiningRef.current = false
      setJoining(false)
    }
  }

  return (
    <div className="join-room-scene animate-screen-in">
      <div className="join-room-scene__artboard">
        <img
          className="join-room-scene__background"
          src="/assets/rooms/join/background.webp"
          alt=""
          aria-hidden="true"
        />

        <header className="join-room-scene__header">
          <button
            type="button"
            className="join-room-scene__back"
            onClick={() => navigate('/home')}
            aria-label="返回首页"
          >
            <ArrowLeft aria-hidden="true" />
          </button>

          <div className="join-room-scene__heading">
            <span className="join-room-scene__heading-flourish" aria-hidden="true" />
            <h1>加入房间</h1>
            <span className="join-room-scene__heading-flourish" aria-hidden="true" />
          </div>
          <p>输入房主分享的房间号加入冒险</p>
        </header>

        <main>
          <form
            className="join-room-scene__dossier"
            onSubmit={(event) => {
              event.preventDefault()
              void handleJoin()
            }}
          >
            <img
              className="join-room-scene__dossier-art"
              src="/assets/rooms/join/join-dossier.webp"
              alt=""
              aria-hidden="true"
            />
            <label htmlFor="join-room-code">输入 6 位房间码</label>

            <div
              className={`join-room-scene__code ${inputFocused ? 'join-room-scene__code--focused' : ''}`}
              aria-hidden="true"
            >
              {Array.from({ length: ROOM_CODE_LENGTH }, (_, index) => (
                <span
                  key={index}
                  className={inputFocused && index === roomCode.length
                    ? 'join-room-scene__code-cell join-room-scene__code-cell--cursor'
                    : 'join-room-scene__code-cell'}
                >
                  {roomCode[index] ?? ''}
                </span>
              ))}
            </div>

            <input
              id="join-room-code"
              className="join-room-scene__code-input"
              value={roomCode}
              onChange={(event) => {
                setRoomCode(normalizeRoomCode(event.target.value))
                setError('')
              }}
              onFocus={() => setInputFocused(true)}
              onBlur={() => setInputFocused(false)}
              aria-describedby={error ? 'join-room-code-error' : 'join-room-code-hint'}
              aria-invalid={!!error}
              autoCapitalize="characters"
              autoComplete="one-time-code"
              autoFocus
              inputMode="text"
              maxLength={ROOM_CODE_LENGTH}
              spellCheck={false}
            />
            <span id="join-room-code-hint" className="sr-only">
              房间码由 6 位英文字母或数字组成
            </span>

            <div className="join-room-scene__error-slot">
              {error && (
                <p id="join-room-code-error" role="alert">{error}</p>
              )}
            </div>

            <button
              type="submit"
              className="join-room-scene__join"
              disabled={!canJoin}
            >
              <span className="sr-only">{joining ? '加入中…' : '加入房间'}</span>
              {joining && <span aria-hidden="true">加入中…</span>}
            </button>
          </form>

          <img
            className="join-room-scene__poster"
            src="/assets/rooms/join/detective-poster.webp"
            alt=""
            aria-hidden="true"
          />

          <section className="join-room-scene__create-entry" aria-labelledby="join-create-title">
            <p id="join-create-title">没有房间号？</p>
            <button type="button" onClick={() => navigate('/home/create')}>
              <img
                src="/assets/rooms/join/create-room-button.webp"
                alt=""
                aria-hidden="true"
              />
              <span className="sr-only">创建房间</span>
            </button>
          </section>
        </main>
      </div>
    </div>
  )
}

import { useNavigate } from 'react-router-dom'
import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, UserPlus, Swords, Eye } from 'lucide-react'
import { useCharacterStore } from '@/stores/character-store'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { ALL_SKILLS, calculateBaseValue } from '@/data/skills'
import { ATTRIBUTE_LABELS } from '@/data/character-model'
import { getOccupationById } from '@/data/occupations'
import { connectWebSocket, disconnectWebSocket, sendWsMessage, waitForWsOpen } from '@/services/api-client'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'

const ATTR_KEY_LIST = ['str', 'con', 'pow', 'dex', 'app', 'siz', 'int', 'edu'] as const

const SHEET_PAGES = [
  { key: 'info', label: '基本信息' },
  { key: 'skills', label: '技能' },
  { key: 'background', label: '背景装备' },
] as const

function CharacterSheetModal({ character, onClose }: { character: NonNullable<ReturnType<typeof useCharacterStore.getState>['character']>; onClose: () => void }) {
  const [page, setPage] = useState<typeof SHEET_PAGES[number]['key']>('info')
  const occupation = character.info.occupationId ? getOccupationById(character.info.occupationId) : null

  return (
    <>
      <div className="fixed inset-0 bg-black/50 z-30 animate-fade-in" onClick={onClose} />
      <div className="fixed inset-x-0 bottom-0 z-40 bg-card rounded-t-2xl animate-slide-up max-h-[80vh] overflow-y-auto">
        <div className="flex items-center justify-between px-5 pt-4 pb-2">
          <h3 className="text-base font-bold text-text-primary">调查员 · {character.info.name}</h3>
          <button onClick={onClose} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center">
            <svg className="w-4 h-4 text-text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Page tabs */}
        <div className="flex gap-1.5 px-5 pb-3">
          {SHEET_PAGES.map(p => (
            <button key={p.key} onClick={() => setPage(p.key)}
              className={`flex-1 text-center text-[12px] font-semibold py-1.5 rounded-[99px] border transition-all ${
                page === p.key ? 'bg-brass text-white border-brass' : 'bg-panel text-text-muted border-border-light'
              }`}>
              {p.label}
            </button>
          ))}
        </div>

        <div className="px-5 pb-6 space-y-4">
          {page === 'info' && (
            <>
              <div className="flex items-center gap-3">
                <div className="w-12 h-14 rounded-sm flex items-center justify-center text-2xl"
                  style={{ background: 'linear-gradient(135deg,#e8e0d0,#d8cfb8)', border: '2px solid #b8976a' }}>
                  🕵️
                </div>
                <div>
                  <div className="font-bold text-text-primary text-[17px]">{character.info.name}</div>
                  <div className="text-xs text-text-muted">{character.info.age}岁 · {character.info.gender} · {occupation?.name ?? '未选择职业'}</div>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                <div className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                  <span className="text-[11px] text-text-muted">居住地</span>
                  <span className="text-sm font-medium text-text-primary">{character.info.residence || '—'}</span>
                </div>
                <div className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                  <span className="text-[11px] text-text-muted">出生地</span>
                  <span className="text-sm font-medium text-text-primary">{character.info.birthplace || '—'}</span>
                </div>
              </div>
              <div className="flex gap-2">
                {[
                  { label: 'HP', value: `${character.derived.hp}`, color: 'text-mold' },
                  { label: 'SAN', value: `${character.derived.san}`, color: 'text-[#7050a0]' },
                  { label: 'MP', value: `${character.derived.mp}`, color: 'text-[#4a7098]' },
                  { label: 'DB', value: character.derived.db, color: 'text-text-muted' },
                  { label: 'MOV', value: `${character.derived.move}`, color: 'text-text-muted' },
                ].map(pill => (
                  <div key={pill.label} className="flex-1 bg-panel rounded-md px-2.5 py-2 text-center">
                    <div className="text-[10px] text-text-muted font-semibold">{pill.label}</div>
                    <div className={`text-[16px] font-bold font-mono ${pill.color}`}>{pill.value}</div>
                  </div>
                ))}
              </div>
              <div>
                <h4 className="text-[11px] font-semibold text-brass-dark mb-2">基础属性</h4>
                <div className="grid grid-cols-2 gap-1.5">
                  {ATTR_KEY_LIST.map(key => (
                    <div key={key} className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
                      <span className="font-mono text-[11px] font-bold text-text-muted">{ATTRIBUTE_LABELS[key].short}</span>
                      <span className="font-mono text-sm font-bold text-text-primary">{character.attr[key]}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {page === 'skills' && (
            <div>
              <h4 className="text-[11px] font-semibold text-brass-dark mb-2">全部技能（按数值从高到低）</h4>
              <div className="space-y-1.5">
                {ALL_SKILLS.map(skill => ({
                  skill,
                  value: calculateBaseValue(skill, character.attr) + (character.skillAlloc[skill.id] || 0),
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
    </>
  )
}

// 第二个等待界面：每个人各自建完卡之后，先看看队友是不是也都建完了，
// 全员建完卡房主才能真正开始游戏（发 game.start），其他人靠轮询房间
// phase 变成 InGame 各自跟上、一起进入聊天室。
export default function CharacterReadyPage() {
  const navigate = useNavigate()
  const [showSelfSheet, setShowSelfSheet] = useState(false)
  const [starting, setStarting] = useState(false)
  const roomId = useRoomStore((s) => s.roomId)
  // 按房间取角色卡，而不是直接读 store 顶层的 character——本地缓存不按
  // 房间区分的话，换房间会把上一个房间的角色数据错误地当成"已建卡"
  // 展示出来（见 PR #67 review）。
  const character = useCharacterStore((s) => (roomId ? s.getForRoom(roomId) : null))
  const roomCode = useRoomStore((s) => s.roomCode)
  const isHost = useRoomStore((s) => s.isHost)
  const playerId = useRoomStore((s) => s.playerId)
  const reconnectToken = useRoomStore((s) => s.reconnectToken)
  const nickname = useAuthStore((s) => s.nickname)
  const hasCharacter = character !== null
  const info = useRoomPlayers(roomCode)
  const players = info?.players ?? []
  const allHaveCharacters = players.length > 0 && players.every((p) => p.hasCharacter)
  const advancedRef = useRef(false)

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
    setStarting(true)
    try {
      // ★ 这个页面从来没有主动建立过 WS 连接（只有 LobbyPage 会连）——如果
      // 刷新过页面、或者从没经过 Lobby 直接落到这里，connectWebSocket 拿到
      // 的连接是关闭的，sendWsMessage 会静默丢弃 game.start，后端 phase
      // 永远停在 Building，其他玩家会一直卡在轮询里。这里跟 RoomPage 一样，
      // 发 game.start 前先确保连接是通的、且已经 room.join 过（对已经连过
      // 的情况是幂等空操作）。
      const ws = connectWebSocket(roomId)
      await waitForWsOpen(ws)
      sendWsMessage('room.join', playerId, {
        reconnectToken: reconnectToken || '',
        roomCode,
        nickname: nickname || '玩家',
      })
      sendWsMessage('game.start', playerId, {})
    } catch {
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
    <div className="animate-screen-in px-5 pt-6">
      {/* Header */}
      <button
        onClick={handleGoBack}
        className="w-[34px] h-[34px] rounded-full bg-card border border-border-light flex items-center justify-center flex-shrink-0 active:bg-panel active:scale-[0.94] transition-all duration-150 mb-3"
      >
        <ArrowLeft className="w-[18px] h-[18px] text-text-muted" strokeWidth={2.5} />
      </button>

      <div className="flex items-center justify-center gap-2 mb-1">
        <span className="font-mono text-2xl font-bold text-text-primary tracking-[0.15em] bg-card border border-dashed border-border-mid px-4 py-1.5 rounded-sm">
          {roomCode || '------'}
        </span>
      </div>
      <p className="text-center text-xs text-text-muted mb-5">
        人物卡准备 · 等待所有玩家创建角色
        {info && ` · ${players.length}/${info.maxPlayers} 人已加入`}
      </p>

      {/* Player List：自己能看查看/编辑，队友只能看到"建完了没有"——角色卡内容是私密的 */}
      <div className="flex flex-col gap-2">
        {players.length === 0 && (
          <div className="text-center py-6 text-xs text-text-dim">正在获取房间成员…</div>
        )}
        {players.map((p) => {
          const isSelf = p.playerId === playerId
          return (
            <div key={p.playerId} className="flex items-center gap-3 px-3.5 py-3 bg-card border border-border-light rounded-md">
              <div className={`w-10 h-10 rounded-full bg-panel border border-border-mid flex items-center justify-center text-lg flex-shrink-0 ${p.hasCharacter ? 'border-brass' : 'border-dashed border-border-light'}`}>
                {p.hasCharacter ? '🔍' : '○'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-semibold text-text-primary">{p.nickname}{isSelf && ' (你)'}</div>
                <div className="text-xs text-text-muted">
                  {isSelf && hasCharacter ? (
                    <span className="text-mold">人物卡：{character!.info.name}</span>
                  ) : p.hasCharacter ? (
                    <span className="text-mold">已完成建卡</span>
                  ) : (
                    <span className="text-text-dim">尚未创建人物卡</span>
                  )}
                </div>
              </div>
              {isSelf && (
                <div className="flex items-center gap-1.5">
                  {hasCharacter ? (
                    <>
                      <button onClick={() => setShowSelfSheet(true)}
                        className="text-[11px] font-semibold px-2 py-1 rounded-[99px] bg-brass/10 text-brass-dark flex items-center gap-1 active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap cursor-pointer">
                        <Eye className="w-3 h-3" /> 查看
                      </button>
                      <button onClick={handleEditCharacter}
                        className="text-[11px] font-semibold px-2 py-1 rounded-[99px] bg-panel text-text-muted active:scale-[0.95] transition-all border border-border-light font-sans whitespace-nowrap cursor-pointer">
                        编辑
                      </button>
                    </>
                  ) : (
                    <button onClick={handleEditCharacter}
                      className="text-[11px] font-semibold px-2.5 py-1 rounded-[99px] bg-brass text-white flex items-center gap-1 active:scale-[0.95] transition-all border-none font-sans whitespace-nowrap cursor-pointer">
                      <UserPlus className="w-3 h-3" /> 创建人物卡
                    </button>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Waiting message */}
      <p className="text-center text-xs text-text-muted mt-6 mb-4">
        {isHost
          ? '将房间号分享给好友，让他们加入游戏并创建角色'
          : allHaveCharacters
            ? '全员已完成建卡，等待房主开始游戏…'
            : '等待所有玩家完成建卡'}
      </p>

      {/* 只有房主能真正开始游戏，且要等全员都建完卡才能点 */}
      {isHost ? (
        <button
          onClick={handleStartGame}
          disabled={!allHaveCharacters || starting}
          className="w-full mt-2 px-6 py-3.5 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark transition-all disabled:opacity-50 flex items-center justify-center gap-2"
        >
          <Swords className="w-4 h-4" />
          {starting ? '进入中…' : '开始游戏'}
        </button>
      ) : (
        <div className="w-full mt-2 px-6 py-3.5 rounded-sm bg-panel text-text-dim text-sm font-semibold text-center">
          等待房主开始游戏…
        </div>
      )}

      {/* Character Sheet Modal */}
      {showSelfSheet && character && (
        <CharacterSheetModal character={character} onClose={() => setShowSelfSheet(false)} />
      )}
    </div>
  )
}

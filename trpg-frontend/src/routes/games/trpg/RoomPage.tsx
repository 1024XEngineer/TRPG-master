import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Users, Map, BookOpen, ScrollText, Star, X, SendHorizontal, Dice6, Plus, Save, FlagOff, Heart } from 'lucide-react'
import { useState, useRef, useEffect, type FormEvent } from 'react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { useCharacterStore } from '@/stores/character-store'
import { connectWebSocket, waitForWsOpen, sdk, onWsMessage, disconnectWebSocket, friendlyErrorMessage } from '@/services/api-client'
import { endGame } from '@/services/room'
import { useRoomPlayers } from '@/hooks/useRoomPlayers'
import { useRuleset } from '@/hooks/useRuleset'

// ─── Types ───────────────────────────────────────────
interface Message {
  type: 'system' | 'narr' | 'player' | 'dice'
  sender?: string
  content: string
  time: string
  isSelf?: boolean
}

interface MapLocation { icon: string; name: string; desc: string; isCurrent?: boolean }

const MAP_LOCATIONS: MapLocation[] = [
  { icon: '🏚️', name: '惠特利旧宅 · 正门', desc: '当前所在 · 铁门虚掩', isCurrent: true },
  { icon: '🌿', name: '前院 · 花园', desc: '杂草丛生，喷泉干涸' },
  { icon: '🚪', name: '门厅', desc: '一楼入口，尚未探索' },
  { icon: '📚', name: '书房', desc: '教授最后出现的地点' },
  { icon: '🪟', name: '二楼走廊', desc: '蓝绿色光芒的来源' },
  { icon: '🔻', name: '地下室', desc: '门锁着，钥匙未知' },
]

const DICE_OPTIONS = [
  { id: 'd100', label: 'D100' },
  { id: 'd20', label: 'D20' },
  { id: 'd6', label: 'D6' },
] as const

type DiceType = typeof DICE_OPTIONS[number]['id']

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
          <button onClick={onClose} className="w-7 h-7 rounded-full bg-panel flex items-center justify-center active:scale-90 transition-transform">
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
function DiceModal({ open, onClose, onResult }: { open: boolean; onClose: () => void; onResult: (result: number, diceType: DiceType) => void }) {
  const [diceType, setDiceType] = useState<DiceType>('d100')
  const [shakeLevel, setShakeLevel] = useState(0)
  const [result, setResult] = useState<number | null>(null)
  const [rolling, setRolling] = useState(false)
  const [showResult, setShowResult] = useState(false)
  const [tens, setTens] = useState(0)
  const [ones, setOnes] = useState(0)
  const tableRef = useRef<HTMLDivElement>(null)
  const isGrabbed = useRef(false)
  const directionChanges = useRef(0)
  const lastDirX = useRef(0)
  const lastDirY = useRef(0)

  useEffect(() => {
    if (open) {
      setDiceType('d100')
      setResult(null)
      setShowResult(false)
      setRolling(false)
      setShakeLevel(0)
    }
  }, [open])

  const roll = (power: number) => {
    setRolling(true)
    setShowResult(false)

    let finalResult: number
    let t = 0, o = 0

    if (diceType === 'd100') {
      t = Math.floor(Math.random() * 10)
      o = Math.floor(Math.random() * 10)
      finalResult = t * 10 + o
      if (finalResult === 0) finalResult = 100
      setTens(t)
      setOnes(o)
    } else if (diceType === 'd20') {
      finalResult = Math.floor(Math.random() * 20) + 1
    } else {
      finalResult = Math.floor(Math.random() * 6) + 1
    }

    const dur = 500 + power * 100
    setTimeout(() => {
      setResult(finalResult)
      setShowResult(true)
      setRolling(false)
    }, dur)
  }

  const handleMouseDown = () => {
    if (rolling || showResult) return
    isGrabbed.current = true
    directionChanges.current = 0
    lastDirX.current = 0
    lastDirY.current = 0
    setShakeLevel(0)
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
      setShakeLevel(level)
    }
  }

  const handleMouseUp = () => {
    if (!isGrabbed.current) return
    isGrabbed.current = false
    if (shakeLevel >= 1) {
      roll(shakeLevel)
    } else {
      roll(1)
    }
  }

  const confirmResult = () => {
    if (result === null) return
    onResult(result, diceType)
    onClose()
  }

  const renderDiceDisplay = () => {
    const glow = rolling ? 'opacity-40' : ''
    return (
      <div ref={tableRef} className={`relative w-full h-48 flex items-center justify-center select-none ${isGrabbed.current ? 'cursor-grabbing' : 'cursor-grab'} ${glow}`}>
        {diceType === 'd100' ? (
          <div className="flex items-center gap-6">
            <div className="text-center">
              <div className={`text-[42px] font-bold font-mono tracking-wider ${tens === 0 ? 'text-[#c8c0b8]' : 'text-[#eeead8]'} transition-colors`}>
                {String(tens * 10).padStart(2, '0')}
              </div>
              <div className="text-[10px] text-[#9088a0] mt-1 font-mono">十位</div>
            </div>
            <div className="text-[28px] text-[#9088a0] font-mono">+</div>
            <div className="text-center">
              <div className={`text-[42px] font-bold font-mono ${ones === 0 ? 'text-[#c8c0b8]' : 'text-[#eeead8]'} transition-colors`}>
                {ones}
              </div>
              <div className="text-[10px] text-[#9088a0] mt-1 font-mono">个位</div>
            </div>
          </div>
        ) : (
          <div
            className={`text-[64px] font-bold font-mono text-[#eeead8] ${isGrabbed.current ? 'scale-105' : ''} transition-transform duration-150`}
            style={{
              clipPath: diceType === 'd20' ? 'polygon(50% 0%, 95% 25%, 95% 75%, 50% 100%, 5% 75%, 5% 25%)' : undefined,
              background: 'linear-gradient(145deg, #2a2630, #1a1620)',
              width: diceType === 'd20' ? '90px' : '80px',
              height: diceType === 'd20' ? '96px' : '80px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: diceType === 'd6' ? '12px' : undefined,
              border: '1px solid rgba(255,255,255,0.08)',
            }}
          >
            {rolling ? (diceType === 'd20' ? Math.floor(Math.random() * 20) + 1 : Math.floor(Math.random() * 6) + 1) : result || '-'}
          </div>
        )}
      </div>
    )
  }

  const getVerdict = (): { label: string; color: string } | null => {
    if (result === null || diceType !== 'd100') return null
    const skill = 65
    if (result <= 5) return { label: '极限成功', color: DIFFICULTY_COLORS.crit }
    if (result <= 33) return { label: '困难成功', color: DIFFICULTY_COLORS.success }
    if (result <= skill) return { label: '成功', color: DIFFICULTY_COLORS.success }
    return { label: '失败', color: DIFFICULTY_COLORS.fail }
  }

  const verdict = getVerdict()

  return (
    <BottomPanel open={open} onClose={onClose} title="骰子检定">
      {/* Dice type selector */}
      <div className="flex gap-1.5 mb-3.5">
        {DICE_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            onClick={() => { if (!rolling) { setDiceType(opt.id); setResult(null); setShowResult(false); setShakeLevel(0) } }}
            className={`flex-1 text-center text-[12px] font-semibold py-1.5 rounded-[99px] border transition-all ${
              diceType === opt.id ? 'bg-brass text-white border-brass' : 'bg-panel text-text-muted border-border-light'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Dice context info */}
      <div className="text-center mb-3">
        <span className="text-xs text-brass-dark font-semibold bg-brass/10 px-4 py-1 rounded-full inline-block">
          侦察
        </span>
        <div className="font-mono text-xs text-text-muted mt-1">
          {diceType === 'd100' ? '目标: 65 · D% = 十位 + 个位' : '自由检定'}
        </div>
      </div>

      {/* Dice table——保留深色"赌桌"质感，作为浅色面板里的一个独立区块，
          不再是撑满整个屏幕的深色页面 */}
      <div
        className="rounded-md bg-[#1a1620] px-4 pt-5 pb-4 flex flex-col items-center relative overflow-hidden"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        onTouchStart={handleMouseDown}
        onTouchMove={handleMouseMove}
        onTouchEnd={handleMouseUp}
      >
        {/* Shake glow ring */}
        {shakeLevel >= 2 && !rolling && !showResult && (
          <div
            className="absolute w-52 h-52 rounded-full pointer-events-none transition-all duration-200"
            style={{
              background: `radial-gradient(circle, rgba(184,151,106,${0.04 + shakeLevel * 0.04}) 0%, transparent 70%)`,
              transform: `scale(${1 + shakeLevel * 0.05})`,
            }}
          />
        )}

        {renderDiceDisplay()}

        {!rolling && !showResult && (
          <div className="text-center mt-2">
            <span className="text-xs text-[#9088a0]">
              {shakeLevel === 0 ? '👆 按住这里来回拖动 · 摇动后松手' :
               shakeLevel <= 2 ? '⚡ 再用力一点……' :
               shakeLevel <= 4 ? '🔥 快了！' :
               '💥 松手投出！'}
            </span>
          </div>
        )}

        {/* Shake meter */}
        {!rolling && !showResult && (
          <div className="flex gap-1 mt-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <div key={i} className={`w-6 h-1 rounded-full transition-all duration-200 ${
                i < shakeLevel ? (i >= 3 ? 'bg-brass' : 'bg-[rgba(184,151,106,0.5)]') : 'bg-[rgba(255,255,255,0.08)]'
              }`} />
            ))}
          </div>
        )}

        {rolling && (
          <div className="text-center mt-2 text-xs text-[#9088a0] animate-pulse">
            🎲 骰子飞出去了……
          </div>
        )}
      </div>

      {/* Result */}
      {showResult && result !== null && (
        <div className="flex flex-col items-center pt-4 gap-3 animate-[fadeIn_0.3s_ease]">
          <div className="text-center">
            {diceType === 'd100' ? (
              <>
                <div className="flex items-center justify-center gap-2 text-text-dim font-mono text-sm">
                  <span>{String(tens * 10).padStart(2, '0')}</span>
                  <span>+</span>
                  <span>{ones}</span>
                  <span>=</span>
                </div>
                <div className={`text-[44px] font-bold font-mono ${result <= 5 ? 'text-[#5aaa5a]' : result > 65 ? 'text-[#d45050]' : 'text-[#4a8a4a]'}`}>
                  {String(result).padStart(2, '0')}
                </div>
              </>
            ) : (
              <div className="text-[44px] font-bold font-mono text-text-primary">{result}</div>
            )}
            {verdict && (
              <div className="text-base font-bold mt-1" style={{ color: verdict.color }}>{verdict.label}</div>
            )}
            <div className="text-xs text-text-dim mt-1 font-mono">
              {diceType === 'd100' ? `侦察 65% · 需求 ≤65` : `${diceType.toUpperCase()} · 自由检定`}
            </div>
          </div>

          <button
            onClick={confirmResult}
            className="w-full py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark active:scale-[0.97] transition-all"
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
  const isHost = roomInfo?.players.find((p) => p.playerId === playerId)?.isHost ?? false
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [ending, setEnding] = useState(false)
  const [endError, setEndError] = useState('')
  const [confirmExit, setConfirmExit] = useState(false)
  const [messages, setMessages] = useState<Message[]>([
    { type: 'system', content: '案件档案已加载 · 惠特利旧宅', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
  ])
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
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

  // 真实 AI 主持人回复：订阅 narration.push（不再是本地假打字模拟）
  useEffect(() => {
    const off = onWsMessage((envelope) => {
      if (envelope.type === 'narration.push') {
        setTyping(false)
        setMessages(prev => [...prev, {
          type: 'narr', sender: '守秘人',
          content: envelope.payload.text,
          time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
        }])
      }
    })
    return off
  }, [])

  const sendMessage = (e?: FormEvent) => {
    e?.preventDefault()
    const text = input.trim()
    if (!text || !playerId) return
    setMessages(prev => [...prev, {
      type: 'player', sender: senderName, content: text, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), isSelf: true,
    }])
    setInput('')
    setTyping(true)
    sdk.roomSocket.submitAction(playerId, { utterance: text })
  }

  const handleDiceResult = (result: number, diceType: DiceType) => {
    const typeLabel = diceType.toUpperCase()
    const resultLabel = diceType === 'd100' ? (result <= 5 ? '极限成功' : result <= 65 ? '成功' : '失败') : `掷出 ${result}`
    setMessages(prev => [...prev, {
      type: 'dice', sender: senderName, content: `${typeLabel} · ${result}`, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), isSelf: true,
    }, {
      type: 'narr', sender: '守秘人', content: `检定结果: ${resultLabel}`, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    }])
  }

  // 结束游戏——仅房主可操作。房间转「已完成」后只能在「我的游戏」里查看复盘，不能再回到聊天室。
  const handleEndGame = async () => {
    if (!roomId) return
    setEnding(true)
    setEndError('')
    try {
      await endGame(roomId)
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
          <div className="text-sm font-semibold text-text-primary">惠特利旧宅</div>
          <div className="text-[11px] text-text-muted">
            {roomInfo ? `${roomInfo.players.length} 位调查员` : '克苏鲁的呼唤'}
          </div>
        </div>
        <button
          onClick={() => setOpenPanel(openPanel === 'members' ? null : 'members')}
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
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3" id="chatScroll">
        {messages.map((msg, i) => {
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
                  ${isNarr ? 'bg-[#fdfaf4] border-l-[3px] border-brass rounded-r-sm rounded-l-none italic text-[#4a4030] text-left' : ''}
                  ${!isPlayer && !isNarr ? 'bg-panel rounded-md' : ''}
                `}>
                  {msg.content}
                </div>
                <div className="text-[10px] text-text-dim mt-0.5">{msg.time}</div>
              </div>
            </div>
          )
        })}

        {/* Typing indicator */}
        {typing && (
          <div className="flex gap-2.5 animate-[msgIn_0.3s_ease]">
            <div className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-sm bg-[#faf5eb] border border-brass">
              📜
            </div>
            <div className="bg-panel inline-flex gap-1 items-center px-4 py-3 rounded-md">
              {[0, 1, 2].map((i) => (
                <span key={i} className="w-1.5 h-1.5 bg-brass rounded-full animate-bounce"
                  style={{ animationDelay: `${i * 0.2}s`, animationDuration: '1.4s' }} />
              ))}
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
      {character && (
        <div className="flex items-center gap-4 px-4 py-2 border-t border-border-light bg-page flex-shrink-0">
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <Heart className="w-3 h-3 text-mold flex-shrink-0" strokeWidth={2.5} />
            <span className="text-[10px] font-semibold text-text-muted flex-shrink-0">HP</span>
            <div className="flex-1 h-1.5 rounded-full bg-border-light overflow-hidden">
              <div className="h-full rounded-full bg-mold" style={{ width: '100%' }} />
            </div>
            <span className="text-[11px] font-bold font-mono text-mold flex-shrink-0">{character.derived.hp}</span>
          </div>
          <div className="flex items-center gap-1.5 flex-1 min-w-0">
            <span className="text-[10px] font-semibold text-text-muted flex-shrink-0">SAN</span>
            <div className="flex-1 h-1.5 rounded-full bg-border-light overflow-hidden">
              <div className="h-full rounded-full bg-[#7050a0]" style={{ width: `${Math.min(100, character.derived.san)}%` }} />
            </div>
            <span className="text-[11px] font-bold font-mono text-[#7050a0] flex-shrink-0">{character.derived.san}</span>
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-border-light px-3 pb-3 pt-1.5 bg-page flex-shrink-0">
        <form onSubmit={sendMessage} className="flex gap-2 items-end">
          <button
            type="button"
            onClick={() => setShowDice(true)}
            className="w-10 h-10 rounded-full bg-card border border-border-light text-text-muted flex items-center justify-center flex-shrink-0 active:scale-[0.92] active:border-brass active:text-brass-dark transition-all"
          >
            <Dice6 className="w-[18px] h-[18px]" strokeWidth={2} />
          </button>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入行动…"
            className="flex-1 bg-input border border-border-mid rounded-[20px] px-4 py-2.5 text-sm text-text-primary font-sans outline-none min-h-[40px] placeholder:text-text-dim focus:border-brass transition-colors"
          />
          <button
            type="submit"
            className="w-10 h-10 rounded-full bg-brass border-none text-white flex items-center justify-center flex-shrink-0 active:scale-[0.92] transition-all hover:bg-brass-dark"
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
          <span className="text-xs text-text-dim">惠特利旧宅 · 阿卡姆郊区</span>
        </div>
        <div className="h-px bg-border-light mb-3.5" />
        <h4 className="text-xs font-semibold text-brass-dark mb-2.5">已知地点</h4>
        <div className="space-y-1.5">
          {MAP_LOCATIONS.map((loc) => (
            <div key={loc.name} className={`flex items-center gap-3 px-3 py-2 rounded ${
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
      <DiceModal open={showDice} onClose={() => setShowDice(false)} onResult={handleDiceResult} />
    </div>
  )
}

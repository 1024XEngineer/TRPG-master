import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Users, Map, BookOpen, ScrollText, Star, X, SendHorizontal, Dice6, Plus, Save } from 'lucide-react'
import { useState, useRef, useEffect, type FormEvent } from 'react'
import { useRoomStore } from '@/stores/room-store'
import { useAuthStore } from '@/stores/auth-store'
import { useCharacterStore } from '@/stores/character-store'
import { sendWsMessage, onWsMessage } from '@/services/api-client'

// ─── Types ───────────────────────────────────────────
interface Message {
  type: 'system' | 'narr' | 'player' | 'dice'
  sender?: string
  content: string
  time: string
  isSelf?: boolean
}

interface StatItem { label: string; name: string; value: number; color: string }
interface SkillItem { name: string; nameEn: string; value: number }
interface MapLocation { icon: string; name: string; desc: string; isCurrent?: boolean }

// ─── Sample data ─────────────────────────────────────
const ATTRIBUTES: StatItem[] = [
  { label: '力量', name: 'STR', value: 50, color: '#c04040' },
  { label: '体质', name: 'CON', value: 60, color: '#c08050' },
  { label: '体型', name: 'SIZ', value: 55, color: '#b8976a' },
  { label: '敏捷', name: 'DEX', value: 65, color: '#4a8a4a' },
  { label: '智力', name: 'INT', value: 70, color: '#4a7098' },
  { label: '意志', name: 'POW', value: 65, color: '#7050a0' },
  { label: '外貌', name: 'APP', value: 60, color: '#8a4070' },
  { label: '教育', name: 'EDU', value: 70, color: '#6a6050' },
]

const SKILLS: SkillItem[] = [
  { name: '侦察', nameEn: 'Spot Hidden', value: 65 },
  { name: '聆听', nameEn: 'Listen', value: 50 },
  { name: '图书馆', nameEn: 'Library Use', value: 60 },
  { name: '说服', nameEn: 'Persuade', value: 45 },
  { name: '斗殴', nameEn: 'Fighting', value: 35 },
  { name: '潜行', nameEn: 'Stealth', value: 40 },
  { name: '心理学', nameEn: 'Psychology', value: 30 },
  { name: '急救', nameEn: 'First Aid', value: 40 },
  { name: '神秘学', nameEn: 'Occult', value: 25 },
]

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
function BottomPanel({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  useEffect(() => {
    if (open) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />}
      <div
        className={`fixed bottom-0 left-0 right-0 z-50 bg-card rounded-t-2xl shadow-xl transition-transform duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] max-w-[430px] mx-auto ${open ? 'translate-y-0' : 'translate-y-full'}`}
        style={{ maxHeight: '72vh' }}
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
        <div className="overflow-y-auto px-5 pb-6" style={{ maxHeight: 'calc(64vh - 60px)' }}>
          {children}
        </div>
      </div>
    </>
  )
}

// ─── Dice System ─────────────────────────────────────
function DiceModal({ onClose, onResult }: { onClose: () => void; onResult: (result: number, diceType: DiceType) => void }) {
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
    <div className="fixed inset-0 z-50 flex flex-col bg-[#0d0b10] max-w-[430px] mx-auto">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3.5 flex-shrink-0">
        <button onClick={onClose} className="w-8 h-8 rounded-full bg-[rgba(255,255,255,0.08)] border border-[rgba(255,255,255,0.12)] flex items-center justify-center text-[#a09888] active:bg-[rgba(255,255,255,0.15)]">
          <ArrowLeft className="w-[18px] h-[18px]" strokeWidth={2.5} />
        </button>
        <span className="text-sm font-semibold text-[#d4cfc8] tracking-[0.05em]">骰子检定</span>
        <div className="w-8" />
      </div>

      {/* Dice type selector */}
      <div className="flex justify-center gap-2 px-4 flex-shrink-0">
        {DICE_OPTIONS.map((opt) => (
          <button
            key={opt.id}
            onClick={() => { if (!rolling) { setDiceType(opt.id); setResult(null); setShowResult(false); setShakeLevel(0) } }}
            className={`px-5 py-1.5 rounded-full text-xs font-semibold transition-all ${
              diceType === opt.id
                ? 'bg-brass text-white'
                : 'bg-[rgba(255,255,255,0.06)] text-[#9088a0] border border-[rgba(255,255,255,0.1)]'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Dice context info */}
      <div className="text-center pt-3 pb-1 flex-shrink-0">
        <span className="text-xs text-brass font-semibold bg-[rgba(184,151,106,0.12)] px-4 py-1 rounded-full inline-block">
          侦察
        </span>
        <div className="font-mono text-xs text-[#9088a0] mt-1">
          {diceType === 'd100' ? '目标: 65 · D% = 十位 + 个位' : '自由检定'}
        </div>
      </div>

      {/* Dice area */}
      <div className="flex-1 flex flex-col items-center justify-center px-4 relative"
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
      </div>

      {/* Result overlay */}
      {showResult && result !== null && (
        <div className="flex flex-col items-center px-6 pb-6 gap-4 animate-[fadeIn_0.3s_ease]">
          <div className="text-center">
            {diceType === 'd100' ? (
              <>
                <div className="flex items-center justify-center gap-2 text-[#9088a0] font-mono text-sm">
                  <span>{String(tens * 10).padStart(2, '0')}</span>
                  <span>+</span>
                  <span>{ones}</span>
                  <span>=</span>
                </div>
                <div className={`text-[52px] font-bold font-mono ${result <= 5 ? 'text-[#5aaa5a]' : result > 65 ? 'text-[#d45050]' : 'text-[#4a8a4a]'}`}
                  style={{ textShadow: result <= 5 ? '0 0 40px rgba(74,138,74,0.3)' : result > 65 ? '0 0 40px rgba(196,64,64,0.3)' : undefined }}>
                  {String(result).padStart(2, '0')}
                </div>
              </>
            ) : (
              <div className="text-[52px] font-bold font-mono text-[#eeead8]">{result}</div>
            )}
            {verdict && (
              <div className="text-base font-bold mt-1" style={{ color: verdict.color }}>{verdict.label}</div>
            )}
            <div className="text-xs text-[#9088a0] mt-1 font-mono">
              {diceType === 'd100' ? `侦察 65% · 需求 ≤65` : `${diceType.toUpperCase()} · 自由检定`}
            </div>
          </div>

          <button
            onClick={confirmResult}
            className="w-full max-w-[200px] py-3 rounded-sm bg-brass text-white text-sm font-semibold active:bg-brass-dark active:scale-[0.97] transition-all"
          >
            确认并发送
          </button>
        </div>
      )}

      {rolling && (
        <div className="text-center pb-6 text-xs text-[#9088a0] animate-pulse">
          🎲 骰子飞出去了……
        </div>
      )}
    </div>
  )
}

// ─── Main RoomPage ───────────────────────────────────
export default function RoomPage() {
  const navigate = useNavigate()
  const playerId = useRoomStore((s) => s.playerId)
  const nickname = useAuthStore((s) => s.nickname)
  const character = useCharacterStore((s) => s.character)
  const senderName = character?.info.name || nickname || '你'
  const [messages, setMessages] = useState<Message[]>([
    { type: 'system', content: '案件档案已加载 · 惠特利旧宅', time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) },
  ])
  const [input, setInput] = useState('')
  const [typing, setTyping] = useState(false)
  const [openPanel, setOpenPanel] = useState<string | null>(null)
  const [showDice, setShowDice] = useState(false)
  const [notes, setNotes] = useState('📋 案件笔记\n═══════════════════════════')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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
    sendWsMessage('action.submit', playerId, { utterance: text })
  }

  const handleDiceResult = (result: number, diceType: DiceType) => {
    const typeLabel = diceType.toUpperCase()
    const isSuccess = diceType === 'd100' ? result <= 65 : true
    const resultLabel = diceType === 'd100' ? (result <= 5 ? '极限成功' : result <= 65 ? '成功' : '失败') : `掷出 ${result}`
    setMessages(prev => [...prev, {
      type: 'dice', sender: senderName, content: `${typeLabel} · ${result}`, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), isSelf: true,
    }, {
      type: 'narr', sender: '守秘人', content: `检定结果: ${resultLabel}`, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
    }])
  }

  const quickActions = [
    { label: '🎲 掷骰', action: () => setShowDice(true) },
    { label: '🔍 调查', action: () => sendMessageText('调查一下周围环境') },
    { label: '💬 对话', action: () => sendMessageText('我想和NPC对话') },
    { label: '🚶 移动', action: () => sendMessageText('前往下一个地点') },
  ]

  const sendMessageText = (text: string) => {
    if (!playerId) return
    setMessages(prev => [...prev, {
      type: 'player', sender: senderName, content: text, time: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }), isSelf: true,
    }])
    setTyping(true)
    sendWsMessage('action.submit', playerId, { utterance: text })
  }

  return (
    <div className="h-screen flex flex-col bg-card relative max-w-[430px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-2.5 px-4 py-2.5 border-b border-border-light bg-page flex-shrink-0">
        <button onClick={() => navigate('/lobby')} className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel">
          <ArrowLeft className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
        </button>
        <div className="w-8 h-8 rounded-full bg-[#f3eef8] flex items-center justify-center text-base flex-shrink-0">
          🏚️
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-text-primary">惠特利旧宅</div>
          <div className="text-[11px] text-text-muted">3 位调查员 · 克苏鲁的呼唤</div>
        </div>
        <button className="w-8 h-8 rounded-full bg-card border border-border-light flex items-center justify-center active:bg-panel">
          <Users className="w-4 h-4 text-text-muted" strokeWidth={2.5} />
        </button>
      </div>

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

      {/* Input area */}
      <div className="border-t border-border-light px-3 pb-3 pt-1.5 bg-page flex-shrink-0">
        <div className="flex gap-1.5 overflow-x-auto pb-1.5 scrollbar-hide">
          {quickActions.map((q) => (
            <button key={q.label} onClick={q.action} className="px-3 py-1 text-[11px] bg-card border border-border-light rounded-[20px] text-text-muted whitespace-nowrap flex-shrink-0 font-sans active:bg-panel active:border-brass active:text-brass-dark transition-colors">
              {q.label}
            </button>
          ))}
        </div>
        <form onSubmit={sendMessage} className="flex gap-2 items-end">
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

      {/* Panel: 角色卡 */}
      <BottomPanel open={openPanel === 'sheet'} onClose={() => setOpenPanel(null)} title="调查员 · 杰克·布朗">
        <div className="flex items-center gap-3 mb-3.5">
          <div className="w-12 h-14 rounded-sm flex items-center justify-center text-2xl"
            style={{ background: 'linear-gradient(135deg,#e8e0d0,#d8cfb8)', border: '2px solid #b8976a' }}>
            🕵️
          </div>
          <div>
            <div className="text-sm font-semibold text-text-primary">私家侦探 · 32 岁 · 波士顿</div>
            <div className="text-[11px] text-text-muted font-mono">
              STR 50 CON 60 SIZ 55 DEX 65 · INT 70 POW 65 APP 60 EDU 70
            </div>
          </div>
        </div>

        {/* HP / SAN / Luck */}
        <div className="flex gap-2 mb-4">
          {[
            { label: '生命 HP', value: '12/14', color: 'text-mold' },
            { label: '理智 SAN', value: '65', color: 'text-brass-dark' },
            { label: '幸运', value: '55', color: 'text-text-primary' },
          ].map((pill) => (
            <div key={pill.label} className="flex-1 bg-panel rounded-md px-3 py-2 text-center">
              <div className="text-[10px] text-text-muted font-medium">{pill.label}</div>
              <div className={`text-base font-bold font-mono ${pill.color}`}>{pill.value}</div>
            </div>
          ))}
        </div>

        <div className="h-px bg-border-light mb-3.5" />

        <h4 className="text-xs font-semibold text-brass-dark mb-2.5">基础属性</h4>
        <div className="grid grid-cols-2 gap-1.5 mb-4">
          {ATTRIBUTES.map((attr) => (
            <div key={attr.name} className="flex items-center justify-between bg-input border border-border-light rounded px-3 py-1.5">
              <span className="font-mono text-[11px] font-bold text-text-muted">{attr.name}</span>
              <span className="font-mono text-sm font-bold text-text-primary">{attr.value}</span>
            </div>
          ))}
        </div>

        <div className="h-px bg-border-light mb-3.5" />
        <h4 className="text-xs font-semibold text-brass-dark mb-2.5">装备</h4>
        <ul className="space-y-1.5">
          {['🔦 手电筒', '📓 笔记本 & 钢笔', '🔫 左轮手枪 (.38) · 6/6 发', '🪪 私家侦探执照', '💊 急救包'].map((item) => (
            <li key={item} className="text-sm text-text-body flex items-center gap-2">
              <span className="text-text-dim">·</span> {item}
            </li>
          ))}
        </ul>
      </BottomPanel>

      {/* Panel: 技能 */}
      <BottomPanel open={openPanel === 'skills'} onClose={() => setOpenPanel(null)} title="技能">
        <div className="space-y-2">
          {SKILLS.map((skill) => (
            <div key={skill.name} className="flex items-center gap-3 py-1.5">
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-text-primary">{skill.name}</div>
                <div className="text-[10px] text-text-dim font-mono">{skill.nameEn}</div>
              </div>
              <div className="flex-1 h-2 rounded-full bg-border-light overflow-hidden">
                <div className="h-full rounded-full bg-brass transition-all" style={{ width: `${skill.value}%` }} />
              </div>
              <span className="text-xs font-bold font-mono text-text-muted min-w-[36px] text-right">{skill.value}%</span>
            </div>
          ))}
        </div>
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
          <button onClick={() => {/* would persist to localStorage */}}
            className="px-4 py-2 rounded-sm bg-brass text-white text-xs font-medium flex items-center justify-center gap-1 active:bg-brass-dark">
            <Save className="w-3.5 h-3.5" /> 保存
          </button>
        </div>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full min-h-[180px] text-sm leading-[1.7] text-text-body bg-input border border-border-light rounded-md px-3.5 py-3 resize-none outline-none focus:border-brass transition-colors font-mono"
        />
        <div className="text-[10px] text-text-dim mt-2 text-right">最后编辑: {new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})} · 自动保存</div>
      </BottomPanel>

      {/* ── Dice Modal ── */}
      {showDice && <DiceModal onClose={() => setShowDice(false)} onResult={handleDiceResult} />}
    </div>
  )
}

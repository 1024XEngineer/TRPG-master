import type { GameManifest } from '@/types/game'

export const GAME_REGISTRY: GameManifest[] = [
  {
    id: 'trpg',
    name: '跑团',
    icon: 'scroll-text',
    description: '经典 TRPG 体验\n支持多规则系统',
    color: 'ink-blue',
    borderColor: 'border-ink-blue',
    iconBg: 'bg-[#eef3f8]',
    iconColor: 'text-ink-blue',
    status: 'recommended',
    systems: [
      { id: 'coc', name: '克苏鲁的呼唤 7th', status: 'ready' },
      { id: 'dnd', name: '龙与地下城 5e', status: 'wip' },
    ],
  },
  {
    id: 'blood-clock',
    name: '血染钟楼',
    icon: 'clock',
    description: '社交推理\n找出恶魔与爪牙',
    color: 'rose',
    borderColor: 'border-[#8a4070]',
    iconBg: 'bg-[#f5eef4]',
    iconColor: 'text-[#8a4070]',
    status: 'coming-soon',
  },
  {
    id: 'werewolf',
    name: '狼人杀',
    icon: 'wolf',
    description: '经典发言推理\n谁是潜伏的狼人',
    color: 'rust',
    borderColor: 'border-[#c04040]',
    iconBg: 'bg-[#f8eeee]',
    iconColor: 'text-[#c04040]',
    status: 'coming-soon',
  },
  {
    id: 'script-murder',
    name: '剧本杀',
    icon: 'theater',
    description: '沉浸式剧情推演\n扮演你的角色',
    color: 'brown',
    borderColor: 'border-[#6a6050]',
    iconBg: 'bg-[#f2f0ec]',
    iconColor: 'text-[#6a6050]',
    status: 'coming-soon',
  },
]

export const GAME_COLORS: Record<string, { border: string; iconBg: string; iconColor: string }> = {
  'trpg': { border: 'border-ink-blue', iconBg: 'bg-[#eef3f8]', iconColor: 'text-ink-blue' },
  'blood-clock': { border: 'border-[#8a4070]', iconBg: 'bg-[#f5eef4]', iconColor: 'text-[#8a4070]' },
  'werewolf': { border: 'border-[#c04040]', iconBg: 'bg-[#f8eeee]', iconColor: 'text-[#c04040]' },
  'script-murder': { border: 'border-[#6a6050]', iconBg: 'bg-[#f2f0ec]', iconColor: 'text-[#6a6050]' },
}

export const SYSTEM_COLORS: Record<string, { border: string; iconBg: string; iconColor: string; name: string }> = {
  'coc': { border: 'border-[#7050a0]', iconBg: 'bg-[#f3eef8]', iconColor: 'text-[#7050a0]', name: '克苏鲁的呼唤 7th' },
  'dnd': { border: 'border-[#c08050]', iconBg: 'bg-[#f8f2ec]', iconColor: 'text-[#c08050]', name: '龙与地下城 5e' },
}

export function getSystemVisualKey(value: string | null | undefined): string {
  const normalized = value?.toLowerCase() ?? ''
  if (normalized.includes('dnd') || normalized.includes('龙与地下城')) return 'dnd'
  return 'coc'
}

export function getGameById(id: string): GameManifest | undefined {
  return GAME_REGISTRY.find(g => g.id === id)
}

export interface SkillDefinition {
  id: string
  name: string
  nameEn: string
  /** Base value: number for fixed, string formula for calculated (e.g. 'DEX/2') */
  base: number | string
  category: 'combat' | 'social' | 'knowledge' | 'perception' | 'physical' | 'technical' | 'language'
  /** An attribute key this skill relates to for specialty substitutions */
  relatedAttr?: string
}

export const ALL_SKILLS: SkillDefinition[] = [
  // ── Combat ──
  { id: 'fighting-brawl', name: '格斗：斗殴', nameEn: 'Fighting (Brawl)', base: 25, category: 'combat' },
  { id: 'fighting-sword', name: '格斗：剑', nameEn: 'Fighting (Sword)', base: 20, category: 'combat' },
  { id: 'fighting-axe', name: '格斗：斧', nameEn: 'Fighting (Axe)', base: 15, category: 'combat' },
  { id: 'fighting-spear', name: '格斗：矛', nameEn: 'Fighting (Spear)', base: 20, category: 'combat' },
  { id: 'fighting-whip', name: '格斗：鞭', nameEn: 'Fighting (Whip)', base: 5, category: 'combat' },
  { id: 'fighting-chain', name: '格斗：链枷', nameEn: 'Fighting (Flail)', base: 10, category: 'combat' },
  { id: 'fighting-knife', name: '格斗：刀', nameEn: 'Fighting (Knife)', base: 25, category: 'combat' },
  { id: 'firearm-handgun', name: '射击：手枪', nameEn: 'Firearms (Handgun)', base: 20, category: 'combat' },
  { id: 'firearm-rifle', name: '射击：步枪', nameEn: 'Firearms (Rifle/Shotgun)', base: 25, category: 'combat' },
  { id: 'firearm-smg', name: '射击：冲锋枪', nameEn: 'Firearms (SMG)', base: 15, category: 'combat' },
  { id: 'firearm-machine-gun', name: '射击：机枪', nameEn: 'Firearms (Machine Gun)', base: 10, category: 'combat' },
  { id: 'firearm-bow', name: '射击：弓', nameEn: 'Firearms (Bow)', base: 15, category: 'combat' },
  { id: 'firearm-flamethrower', name: '射击：火焰喷射器', nameEn: 'Firearms (Flamethrower)', base: 10, category: 'combat' },
  { id: 'dodge', name: '闪避', nameEn: 'Dodge', base: 'DEX/2', category: 'combat' },
  { id: 'throw', name: '投掷', nameEn: 'Throw', base: 20, category: 'combat' },

  // ── Social ──
  { id: 'charm', name: '取悦', nameEn: 'Charm', base: 15, category: 'social' },
  { id: 'fast-talk', name: '话术', nameEn: 'Fast Talk', base: 5, category: 'social' },
  { id: 'intimidate', name: '恐吓', nameEn: 'Intimidate', base: 15, category: 'social' },
  { id: 'persuade', name: '说服', nameEn: 'Persuade', base: 10, category: 'social' },
  { id: 'psychology', name: '心理学', nameEn: 'Psychology', base: 10, category: 'social' },
  { id: 'disguise', name: '乔装', nameEn: 'Disguise', base: 5, category: 'social' },

  // ── Knowledge ──
  { id: 'accounting', name: '会计', nameEn: 'Accounting', base: 5, category: 'knowledge' },
  { id: 'anthropology', name: '人类学', nameEn: 'Anthropology', base: 1, category: 'knowledge' },
  { id: 'appraise', name: '估价', nameEn: 'Appraise', base: 5, category: 'knowledge' },
  { id: 'archaeology', name: '考古学', nameEn: 'Archaeology', base: 1, category: 'knowledge' },
  { id: 'history', name: '历史', nameEn: 'History', base: 5, category: 'knowledge' },
  { id: 'law', name: '法律', nameEn: 'Law', base: 5, category: 'knowledge' },
  { id: 'library-use', name: '图书馆使用', nameEn: 'Library Use', base: 20, category: 'knowledge' },
  { id: 'medicine', name: '医学', nameEn: 'Medicine', base: 1, category: 'knowledge' },
  { id: 'occult', name: '神秘学', nameEn: 'Occult', base: 5, category: 'knowledge' },
  { id: 'science-pharmacy', name: '科学：药学', nameEn: 'Science (Pharmacy)', base: 1, category: 'knowledge' },
  { id: 'science-biology', name: '科学：生物学', nameEn: 'Science (Biology)', base: 1, category: 'knowledge' },
  { id: 'science-chemistry', name: '科学：化学', nameEn: 'Science (Chemistry)', base: 1, category: 'knowledge' },
  { id: 'science-physics', name: '科学：物理学', nameEn: 'Science (Physics)', base: 1, category: 'knowledge' },
  { id: 'science-geology', name: '科学：地质学', nameEn: 'Science (Geology)', base: 1, category: 'knowledge' },
  { id: 'science-astronomy', name: '科学：天文学', nameEn: 'Science (Astronomy)', base: 1, category: 'knowledge' },
  { id: 'science-forensics', name: '科学：法医学', nameEn: 'Science (Forensics)', base: 1, category: 'knowledge' },
  { id: 'science-mathematics', name: '科学：数学', nameEn: 'Science (Mathematics)', base: 10, category: 'knowledge' },
  { id: 'science-engineering', name: '科学：工程学', nameEn: 'Science (Engineering)', base: 1, category: 'knowledge' },
  { id: 'science-botany', name: '科学：植物学', nameEn: 'Science (Botany)', base: 1, category: 'knowledge' },
  { id: 'science-zoology', name: '科学：动物学', nameEn: 'Science (Zoology)', base: 1, category: 'knowledge' },
  { id: 'science-cryptography', name: '科学：密码学', nameEn: 'Science (Cryptography)', base: 1, category: 'knowledge' },
  { id: 'science-metallurgy', name: '科学：冶金学', nameEn: 'Science (Metallurgy)', base: 1, category: 'knowledge' },
  { id: 'science-meteorology', name: '科学：气象学', nameEn: 'Science (Meteorology)', base: 1, category: 'knowledge' },
  { id: 'natural-world', name: '博物学', nameEn: 'Natural World', base: 10, category: 'knowledge' },
  { id: 'navigation', name: '导航', nameEn: 'Navigation', base: 10, category: 'knowledge' },
  { id: 'cthulhu-mythos', name: '克苏鲁神话', nameEn: 'Cthulhu Mythos', base: 0, category: 'knowledge' },

  // ── Perception ──
  { id: 'listen', name: '聆听', nameEn: 'Listen', base: 20, category: 'perception' },
  { id: 'spot-hidden', name: '侦察', nameEn: 'Spot Hidden', base: 25, category: 'perception' },
  { id: 'track', name: '追踪', nameEn: 'Track', base: 10, category: 'perception' },

  // ── Physical ──
  { id: 'climb', name: '攀爬', nameEn: 'Climb', base: 20, category: 'physical' },
  { id: 'jump', name: '跳跃', nameEn: 'Jump', base: 20, category: 'physical' },
  { id: 'swim', name: '游泳', nameEn: 'Swim', base: 20, category: 'physical' },
  { id: 'ride', name: '骑术', nameEn: 'Ride', base: 5, category: 'physical' },
  { id: 'stealth', name: '潜行', nameEn: 'Stealth', base: 20, category: 'physical' },
  { id: 'drive-auto', name: '汽车驾驶', nameEn: 'Drive Auto', base: 20, category: 'physical' },
  { id: 'drive-carriage', name: '驾驶：马车', nameEn: 'Drive (Carriage)', base: 5, category: 'physical' },
  { id: 'pilot-aircraft', name: '驾驶：飞行器', nameEn: 'Pilot (Aircraft)', base: 1, category: 'physical' },
  { id: 'pilot-boat', name: '驾驶：船舶', nameEn: 'Pilot (Boat)', base: 1, category: 'physical' },
  { id: 'pilot-spacecraft', name: '驾驶：航天器', nameEn: 'Pilot (Spacecraft)', base: 1, category: 'physical' },
  { id: 'survival', name: '生存', nameEn: 'Survival', base: 10, category: 'physical' },

  // ── Technical ──
  { id: 'first-aid', name: '急救', nameEn: 'First Aid', base: 30, category: 'technical' },
  { id: 'heavy-machinery', name: '操作重型机械', nameEn: 'Heavy Machinery', base: 1, category: 'technical' },
  { id: 'electrical-repair', name: '电气维修', nameEn: 'Electrical Repair', base: 10, category: 'technical' },
  { id: 'mechanical-repair', name: '机械维修', nameEn: 'Mechanical Repair', base: 10, category: 'technical' },
  { id: 'lock-smith', name: '锁匠', nameEn: 'Locksmith', base: 1, category: 'technical' },
  { id: 'art-craft-1', name: '艺术与手艺①', nameEn: 'Art & Craft 1', base: 5, category: 'technical' },
  { id: 'art-craft-2', name: '艺术与手艺②', nameEn: 'Art & Craft 2', base: 5, category: 'technical' },
  { id: 'art-craft-3', name: '艺术与手艺③', nameEn: 'Art & Craft 3', base: 5, category: 'technical' },
  { id: 'computer-use', name: '计算机使用', nameEn: 'Computer Use', base: 5, category: 'technical' },
  { id: 'electronics', name: '电子学', nameEn: 'Electronics', base: 1, category: 'technical' },
  { id: 'photography', name: '摄影', nameEn: 'Photography', base: 5, category: 'technical' },

  // ── Language ──
  { id: 'language-native', name: '母语', nameEn: 'Language (Own)', base: 'EDU', category: 'language' },
  { id: 'language-foreign-1', name: '外语①', nameEn: 'Language (Foreign 1)', base: 1, category: 'language' },
  { id: 'language-foreign-2', name: '外语②', nameEn: 'Language (Foreign 2)', base: 1, category: 'language' },
  { id: 'language-foreign-3', name: '外语③', nameEn: 'Language (Foreign 3)', base: 1, category: 'language' },
]

export function getSkillById(id: string): SkillDefinition | undefined {
  return ALL_SKILLS.find(s => s.id === id)
}

export function getSkillsByCategory(cat: SkillDefinition['category']): SkillDefinition[] {
  return ALL_SKILLS.filter(s => s.category === cat)
}

export function calculateBaseValue(skill: SkillDefinition, attributes: Record<string, number>): number {
  if (typeof skill.base === 'number') return skill.base
  // Formula like 'DEX/2', 'EDU'
  const formula = skill.base as string
  if (formula.includes('/')) {
    const [attr, divisor] = formula.split('/')
    return Math.floor((attributes[attr.toLowerCase()] || 0) / parseInt(divisor))
  }
  return attributes[formula.toLowerCase()] || 0
}

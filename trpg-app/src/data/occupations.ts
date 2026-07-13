export interface OccupationDefinition {
  id: number
  name: string
  creditRange: string
  /** Skill points formula for occupation skills (e.g. 'EDU×4', 'EDU×2+STR×2') */
  skillPoints: string
  icon: string
  /** IDs of skills this occupation provides (occupation skills) */
  skillIds: string[]
  shortDesc: string
}

/**
 * Core COC7 occupation data.
 * In production, this data would come from a backend API/database.
 * The interface is kept compatible so the mock service can be swapped out
 * with a real API call without changing the frontend code.
 */
export const ALL_OCCUPATIONS: OccupationDefinition[] = [
  {
    id: 1, name: '会计师', creditRange: '30-70', skillPoints: 'EDU×4',
    icon: '📊', shortDesc: '精于数字和财务分析',
    skillIds: ['accounting', 'law', 'library-use', 'listen', 'persuade', 'psychology', 'science-mathematics', 'spot-hidden'],
  },
  {
    id: 2, name: '考古学家', creditRange: '10-40', skillPoints: 'EDU×4',
    icon: '🏛️', shortDesc: '挖掘远古秘密的学者',
    skillIds: ['appraise', 'archaeology', 'history', 'library-use', 'natural-world', 'science-geology', 'spot-hidden', 'language-foreign-1'],
  },
  {
    id: 3, name: '古董商', creditRange: '30-50', skillPoints: 'EDU×4',
    icon: '🔮', shortDesc: '鉴定与交易古代物品',
    skillIds: ['accounting', 'appraise', 'art-craft-1', 'charm', 'fast-talk', 'history', 'occult', 'persuade'],
  },
  {
    id: 4, name: '艺术家', creditRange: '9-50', skillPoints: 'EDU×2+DEX×2',
    icon: '🎨', shortDesc: '以创作表达内心的观察者',
    skillIds: ['art-craft-1', 'art-craft-2', 'charm', 'illusion', 'natural-world', 'psychology', 'spot-hidden', 'stealth'],
  },
  {
    id: 5, name: '作家', creditRange: '9-30', skillPoints: 'EDU×4',
    icon: '✍️', shortDesc: '用文字编织真相与虚构',
    skillIds: ['history', 'library-use', 'natural-world', 'occult', 'persuade', 'psychology', 'language-native', 'science-physics'],
  },
  {
    id: 6, name: '神职人员', creditRange: '9-60', skillPoints: 'EDU×4',
    icon: '⛪', shortDesc: '信仰的守护者与心灵的导师',
    skillIds: ['anthropology', 'history', 'library-use', 'listen', 'occult', 'persuade', 'psychology', 'language-native'],
  },
  {
    id: 7, name: '医生', creditRange: '30-80', skillPoints: 'EDU×4',
    icon: '🏥', shortDesc: '医治身心创伤的专业人士',
    skillIds: ['first-aid', 'medicine', 'persuade', 'psychology', 'science-biology', 'science-chemistry', 'science-pharmacy', 'language-native'],
  },
  {
    id: 8, name: '工程师', creditRange: '30-60', skillPoints: 'EDU×4',
    icon: '⚙️', shortDesc: '设计与构建复杂系统',
    skillIds: ['electrical-repair', 'mechanical-repair', 'heavy-machinery', 'library-use', 'navigate', 'science-engineering', 'science-physics', 'carpentry'],
  },
  {
    id: 9, name: '联邦探员', creditRange: '20-40', skillPoints: 'EDU×4',
    icon: '🕵️', shortDesc: '维护法律与调查重大案件',
    skillIds: ['disguise', 'drive-auto', 'fast-talk', 'firearm-handgun', 'fighting-brawl', 'law', 'persuade', 'spot-hidden'],
  },
  {
    id: 10, name: '消防员', creditRange: '9-30', skillPoints: 'EDU×2+STR×2',
    icon: '🚒', shortDesc: '冒着危险拯救生命的勇士',
    skillIds: ['climb', 'dodge', 'drive-auto', 'first-aid', 'heavy-machinery', 'jump', 'mechanical-repair', 'throw'],
  },
  {
    id: 11, name: '记者', creditRange: '9-30', skillPoints: 'EDU×4',
    icon: '📰', shortDesc: '追逐真相的新闻工作者',
    skillIds: ['history', 'library-use', 'listen', 'persuade', 'psychology', 'language-native', 'spot-hidden', 'fast-talk'],
  },
  {
    id: 12, name: '法官', creditRange: '50-80', skillPoints: 'EDU×4',
    icon: '⚖️', shortDesc: '裁决公正的法律权威',
    skillIds: ['history', 'law', 'library-use', 'listen', 'persuade', 'psychology', 'language-native', 'accounting'],
  },
  {
    id: 13, name: '律师', creditRange: '30-80', skillPoints: 'EDU×4',
    icon: '📜', shortDesc: '在法庭上辩护的专业人士',
    skillIds: ['fast-talk', 'history', 'intimidate', 'law', 'library-use', 'persuade', 'psychology', 'language-native'],
  },
  {
    id: 14, name: '图书馆管理员', creditRange: '9-35', skillPoints: 'EDU×4',
    icon: '📚', shortDesc: '知识的看门人与信息猎手',
    skillIds: ['history', 'library-use', 'listen', 'natural-world', 'occult', 'psychology', 'language-foreign-1', 'language-native'],
  },
  {
    id: 15, name: '护士', creditRange: '9-30', skillPoints: 'EDU×4',
    icon: '💉', shortDesc: '在医疗一线照料病患',
    skillIds: ['first-aid', 'listen', 'medicine', 'persuade', 'psychology', 'science-biology', 'science-chemistry', 'spot-hidden'],
  },
  {
    id: 16, name: '私家侦探', creditRange: '9-30', skillPoints: 'EDU×2+STR×2',
    icon: '🔍', shortDesc: '调查隐秘真相的独立探员',
    skillIds: ['disguise', 'drive-auto', 'fighting-brawl', 'fast-talk', 'law', 'listen', 'persuade', 'spot-hidden'],
  },
  {
    id: 17, name: '教授', creditRange: '20-70', skillPoints: 'EDU×4',
    icon: '🎓', shortDesc: '研究与传授高深学问',
    skillIds: ['library-use', 'listen', 'persuade', 'psychology', 'language-foreign-1', 'language-native', 'spot-hidden', 'science-physics'],
  },
  {
    id: 18, name: '科学家', creditRange: '9-50', skillPoints: 'EDU×4',
    icon: '🔬', shortDesc: '探索自然规律的实验者',
    skillIds: ['library-use', 'science-biology', 'science-chemistry', 'science-physics', 'science-geology', 'science-astronomy', 'science-mathematics', 'photography'],
  },
  {
    id: 19, name: '士兵', creditRange: '9-30', skillPoints: 'EDU×2+STR×2',
    icon: '🎖️', shortDesc: '受过战斗训练的职业军人',
    skillIds: ['climb', 'dodge', 'fighting-brawl', 'firearm-handgun', 'firearm-rifle', 'stealth', 'survival', 'throw'],
  },
  {
    id: 20, name: '学生', creditRange: '5-10', skillPoints: 'EDU×4',
    icon: '🎒', shortDesc: '正在学习中的年轻人',
    skillIds: ['library-use', 'listen', 'psychology', 'language-native', 'spot-hidden', 'history', 'science-biology', 'swim'],
  },
  {
    id: 21, name: '猎人', creditRange: '20-50', skillPoints: 'EDU×2+STR×2',
    icon: '🏹', shortDesc: '追踪猎物的野外专家',
    skillIds: ['climb', 'firearm-rifle', 'listen', 'natural-world', 'spot-hidden', 'stealth', 'survival', 'track'],
  },
  {
    id: 22, name: '音乐家', creditRange: '9-30', skillPoints: 'EDU×2+DEX×2',
    icon: '🎵', shortDesc: '用乐器表达情感的艺术家',
    skillIds: ['art-craft-1', 'charm', 'fast-talk', 'listen', 'persuade', 'psychology', 'spot-hidden', 'stealth'],
  },
  {
    id: 23, name: '摄影师', creditRange: '9-30', skillPoints: 'EDU×4',
    icon: '📷', shortDesc: '用镜头捕捉瞬间与证据',
    skillIds: ['art-craft-1', 'charm', 'fast-talk', 'listen', 'photography', 'psychology', 'spot-hidden', 'science-chemistry'],
  },
  {
    id: 24, name: '警察', creditRange: '9-30', skillPoints: 'EDU×2+STR×2',
    icon: '👮', shortDesc: '维护公共秩序的执法者',
    skillIds: ['drive-auto', 'fighting-brawl', 'firearm-handgun', 'first-aid', 'intimidate', 'law', 'listen', 'spot-hidden'],
  },
  {
    id: 25, name: '酒保', creditRange: '8-25', skillPoints: 'EDU×2+APP×2',
    icon: '🍺', shortDesc: '倾听着各色顾客的故事',
    skillIds: ['accounting', 'charm', 'fast-talk', 'fighting-brawl', 'intimidate', 'listen', 'psychology', 'spot-hidden'],
  },
  {
    id: 26, name: '罪犯', creditRange: '5-65', skillPoints: 'EDU×2+APP×2',
    icon: '🔫', shortDesc: '游走在法律边缘的危险分子',
    skillIds: ['disguise', 'dodge', 'drive-auto', 'fast-talk', 'fighting-brawl', 'firearm-handgun', 'stealth', 'spot-hidden'],
  },
  {
    id: 27, name: '心理学家', creditRange: '10-40', skillPoints: 'EDU×4',
    icon: '🧠', shortDesc: '解析人类心智的学者',
    skillIds: ['listen', 'medicine', 'persuade', 'psychology', 'science-biology', 'library-use', 'language-native', 'fast-talk'],
  },
  {
    id: 28, name: '间谍', creditRange: '20-60', skillPoints: 'EDU×4',
    icon: '🕶️', shortDesc: '在暗中收集情报的专家',
    skillIds: ['disguise', 'dodge', 'drive-auto', 'fast-talk', 'fighting-brawl', 'firearm-handgun', 'psychology', 'stealth'],
  },
  {
    id: 29, name: '杂技演员', creditRange: '9-20', skillPoints: 'EDU×2+DEX×2',
    icon: '🤸', shortDesc: '以灵活身姿表演的特技者',
    skillIds: ['climb', 'dodge', 'jump', 'swim', 'art-craft-1', 'charm', 'fighting-brawl', 'throw'],
  },
  {
    id: 30, name: '事务所侦探', creditRange: '20-45', skillPoints: 'EDU×2+STR×2',
    icon: '🕵️', shortDesc: '受雇调查案件的专业侦探',
    skillIds: ['fighting-brawl', 'firearm-handgun', 'law', 'library-use', 'listen', 'persuade', 'psychology', 'spot-hidden'],
  },
]

/** Grouped occupations for UI filtering */
export const OCCUPATION_GROUPS = [
  { label: '学术研究', icon: '📚', ids: [2, 12, 14, 17, 18, 27] },
  { label: '执法安全', icon: '🔒', ids: [9, 19, 24, 10, 30] },
  { label: '文化艺术', icon: '🎨', ids: [4, 5, 22, 23] },
  { label: '医疗保健', icon: '🏥', ids: [7, 15] },
  { label: '法律金融', icon: '⚖️', ids: [1, 12, 13] },
  { label: '社交服务', icon: '🤝', ids: [6, 11, 16, 25, 28] },
  { label: '野外生存', icon: '🏔️', ids: [21, 3] },
  { label: '社会边缘', icon: '🎭', ids: [26, 20, 29] },
  { label: '专业人员', icon: '🔧', ids: [8, 10] },
]

export function getOccupationById(id: number): OccupationDefinition | undefined {
  return ALL_OCCUPATIONS.find(o => o.id === id)
}

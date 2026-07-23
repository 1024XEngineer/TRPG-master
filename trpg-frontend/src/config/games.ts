import type { GameManifest } from '@/types/game'
import type { Scenario } from '@/types/game'

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

export function getGameById(id: string): GameManifest | undefined {
  return GAME_REGISTRY.find(g => g.id === id)
}

export const SCENARIO_REGISTRY: Scenario[] = [
  // 克苏鲁的呼唤 — 预设模组
  {
    id: 'whateley',
    name: '惠特利旧宅',
    nameEn: 'The Whateley Estate',
    systemId: 'coc',
    description: '一封匿名信将调查员们召集到阿卡姆郊外废弃已久的惠特利宅邸。铁门上的挂锁旁有新鲜的划痕——有人比你们先到了。',
    difficulty: '入门',
    playerCount: '2-4 人',
    estimatedTime: '3-4 小时',
    storyLabel: '案件档案 #1927-03',
    subtitle: 'THE WHATELEY ESTATE',
    storyPages: [
      '阿卡姆，1927 年 3 月。一封匿名信将你们召集到这座废弃已久的宅邸前。',
      '铁门上挂着一把崭新的挂锁，但锁孔旁有新鲜的划痕——有人比你们先到了。',
      '夕阳西下，宅邸的窗户像空洞的眼窝注视着你们。<span class="text-[#b0a0d0] italic">风里带着一股若有若无的霉味。</span>',
    ],
  },
  {
    id: 'dark-edge',
    name: '暗黑边缘',
    nameEn: 'The Dark Edge',
    systemId: 'coc',
    description: '波士顿一家报社的记者在调查一系列离奇失踪案时失去联系。最后一篇报道提到了一座位于郊外的废弃疗养院。',
    difficulty: '进阶',
    playerCount: '3-5 人',
    estimatedTime: '6-8 小时',
    storyLabel: '案件档案 #1927-07',
    subtitle: 'THE DARK EDGE',
    storyPages: [
      '波士顿，1927 年 7 月。记者威廉·哈珀已经失踪三周了。',
      '他留下了一篇未完成的报道，标题潦草地写着「暗黑边缘——疗养院之下」。',
      '编辑把哈珀最后的笔记本交给了你们。<span class="text-[#b0a0d0] italic">最后一页只有一句话：「地下的东西醒了。」</span>',
    ],
  },
  {
    id: 'dead-light',
    name: '死光',
    nameEn: 'The Dead Light',
    systemId: 'coc',
    description: '一场暴雨将你们困在一个偏僻的加油站。黑暗中，有什么东西在林中移动。无线电里传来断断续续的求救信号。',
    difficulty: '入门',
    playerCount: '2-4 人',
    estimatedTime: '2-3 小时',
    storyLabel: '案件档案 #1927-09',
    subtitle: 'THE DEAD LIGHT',
    storyPages: [
      '暴雨如注，你们不得不驶入路边这个几乎废弃的加油站躲避。',
      '加油站老板看起来焦虑不安，他反复看向树林的方向。',
      '收音机里突然传来一个颤抖的声音：「它……它跟着我……请帮帮我……」<span class="text-[#b0a0d0] italic">信号断了。</span>',
    ],
  },
  {
    id: 'book-hunter',
    name: '追书人',
    nameEn: 'The Book-Hunter',
    systemId: 'coc',
    description: '调查员受命调查一起简单的失踪案。道格拉斯·金博尔离奇失踪一年后，他的侄子雇用了调查员来追回失窃的藏书——并查明他的叔叔是否尚在人世。',
    difficulty: '入门',
    playerCount: '1-2 人',
    estimatedTime: '2-3 小时',
    storyLabel: '案件档案 #1927-01',
    subtitle: 'THE BOOK-HUNTER',
    storyPages: [
      '密歇根州，阿诺兹堡市。托马斯·金博尔最近遭遇了一件怪事——他叔叔的五本藏书被人偷了。',
      '这些书并不值钱，但他的叔叔道格拉斯一年前就已经失踪，没有留下任何痕迹。托马斯想知道叔叔是否还活着。',
      '调查员们沿着线索来到公墓附近。<span class="text-[#b0a0d0] italic">远处传来翻动书页的沙沙声，似乎来自墓碑的方向。</span>',
    ],
  },
  // 龙与地下城 — 预设模组
  {
    id: 'lost-mine',
    name: '失落矿坑',
    nameEn: 'The Lost Mine',
    systemId: 'dnd',
    description: '剑湾北部的法尔姆小村近日来饱受地精侵扰。村长悬赏召集冒险者，而线索指向了一座被遗忘的矮人矿坑。',
    difficulty: '入门',
    playerCount: '3-5 人',
    estimatedTime: '4-6 小时',
    storyLabel: '剑湾日志 #1372',
    subtitle: 'THE LOST MINE',
    storyPages: [
      '法尔姆村的村长在村口迎接你们，脸上写满了疲惫。',
      '「地精从北边来了，抢走了我们的粮食和工具。有几个年轻人追过去就再也没回来。」',
      '他指向远处山脚下的一片废墟：「那座矿坑……最近夜里总有光透出来。<span class="text-[#b0a0d0] italic">地精就是从那里来的。</span>」',
    ],
  },
  {
    id: 'dragon-barrow',
    name: '龙之古冢',
    nameEn: 'The Dragon Barrow',
    systemId: 'dnd',
    description: '一群盗墓者从北境古龙冢中盗出了一件被诅咒的龙鳞神器，整个地区的动物开始变得异常狂暴。',
    difficulty: '进阶',
    playerCount: '3-5 人',
    estimatedTime: '6-8 小时',
    storyLabel: '北境传闻 #1373',
    subtitle: 'THE DRAGON BARROW',
    storyPages: [
      '北境边境小镇的旅店老板低声告诉你们：「三天前，一伙盗墓贼从龙冢回来了。」',
      '「他们带着一块发光的鳞片。从那以后，村子周围的野兽就开始发狂了。」',
      '远处传来一声低沉的咆哮。<span class="text-[#b0a0d0] italic">今晚你们最好待在屋里。</span>',
    ],
  },
]

export function getScenariosBySystem(systemId: string): Scenario[] {
  return SCENARIO_REGISTRY.filter(s => s.systemId === systemId)
}

export function getScenarioById(id: string): Scenario | undefined {
  return SCENARIO_REGISTRY.find(s => s.id === id)
}

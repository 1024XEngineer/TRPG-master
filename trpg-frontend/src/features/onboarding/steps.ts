export type OnboardingAudience = 'host' | 'player'

export interface OnboardingStep {
  id: string
  route: string
  target: string
  title: string
  description: string
  audience?: OnboardingAudience
}

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  {
    id: 'lobby-players',
    route: '/room/lobby',
    target: 'lobby-players',
    title: '先确认房间成员',
    description: '这里会显示已经加入房间的玩家。房主和玩家都从同一个大厅开始准备。',
  },
  {
    id: 'lobby-ready',
    route: '/room/lobby',
    target: 'lobby-ready',
    title: '表达你的准备状态',
    description: '普通玩家点击“标记为已就绪”，房主会在所有玩家准备好后开始故事。',
    audience: 'player',
  },
  {
    id: 'lobby-start-story',
    route: '/room/lobby',
    target: 'lobby-start-story',
    title: '房主开始准备流程',
    description: '房主确认所有玩家就绪后，点击这里进入故事介绍和角色创建。',
    audience: 'host',
  },
  {
    id: 'story-content',
    route: '/room/story',
    target: 'story-content',
    title: '先了解案件背景',
    description: '阅读模组的背景和当前处境。理解发生了什么，会更容易决定调查员接下来要做什么。',
  },
  {
    id: 'story-continue',
    route: '/room/story',
    target: 'story-continue',
    title: '进入角色创建',
    description: '阅读完成后点击“继续”，开始创建这次冒险要使用的调查员。',
  },
  {
    id: 'character-progress',
    route: '/room/character',
    target: 'character-progress',
    title: '按四步完成角色卡',
    description: '角色卡分为信息、属性、技能和完成四步。已填写的内容会保留，也可以返回修改。',
  },
  {
    id: 'character-info',
    route: '/room/character',
    target: 'character-info',
    title: '填写调查员信息',
    description: '姓名、年龄和出身让调查员成为一个具体的人物；姓名会显示在游戏对话中。',
  },
  {
    id: 'occupation-picker',
    route: '/room/character',
    target: 'occupation-picker',
    title: '选择一个职业',
    description: '职业决定职业技能点数和擅长方向。第一次游玩可以选择自己最容易理解的职业。',
  },
  {
    id: 'attribute-editor',
    route: '/room/character',
    target: 'attribute-editor',
    title: '分配基础属性',
    description: '属性代表调查员的基础能力。调整时可以同时查看 HP、SAN、MP 等派生属性的变化。',
  },
  {
    id: 'skill-editor',
    route: '/room/character',
    target: 'skill-editor',
    title: '把点数分给技能',
    description: '技能会影响调查和检定。优先强化与你选择的职业或想尝试的玩法相关的技能即可。',
  },
  {
    id: 'background-editor',
    route: '/room/character',
    target: 'background-editor',
    title: '补充背景和装备',
    description: '背景故事和装备帮助你代入角色，本阶段可以留空，之后仍能在角色卡中查看。',
  },
  {
    id: 'character-submit',
    route: '/room/character',
    target: 'character-submit',
    title: '完成并保存角色卡',
    description: '点击这里提交角色卡。保存成功后会进入角色准备页，等待其他玩家。',
  },
  {
    id: 'character-summary',
    route: '/room/ready',
    target: 'character-summary',
    title: '检查你的角色卡',
    description: '准备页会显示角色完成状态。你可以查看或编辑自己的角色卡，直到房主开始游戏。',
  },
  {
    id: 'player-status',
    route: '/room/ready',
    target: 'player-status',
    title: '等待全员完成建卡',
    description: '角色卡内容对其他玩家保密，但大家可以看到谁已经完成。房主会在全员完成后开始游戏。',
  },
  {
    id: 'start-game',
    route: '/room/ready',
    target: 'start-game',
    title: '房主进入游戏',
    description: '房主确认全员完成后点击“开始游戏”，所有玩家会进入同一个游戏房间。',
    audience: 'host',
  },
  {
    id: 'scene-header',
    route: '/room/play',
    target: 'scene-header',
    title: '这是当前调查现场',
    description: '顶部显示模组和当前场景。先阅读主持人的叙事，再决定调查员要采取的行动。',
  },
  {
    id: 'action-input',
    route: '/room/play',
    target: 'action-input',
    title: '用自然语言描述行动',
    description: '你可以直接输入“检查门锁”“询问侦探”或“前往走廊”等行动，不限于固定选项。',
  },
  {
    id: 'dice-button',
    route: '/room/play',
    target: 'dice-button',
    title: '需要时使用骰子',
    description: '需要检定时，系统会提示你选择技能并掷骰。最终结果由规则引擎负责结算。',
  },
  {
    id: 'tool-bar',
    route: '/room/play',
    target: 'tool-bar',
    title: '随时查看调查工具',
    description: '角色卡、技能、地图和速记本都可以从底部打开，不需要离开当前游戏页面。',
  },
] as const

export function stepsForAudience(isHost: boolean): OnboardingStep[] {
  const audience: OnboardingAudience = isHost ? 'host' : 'player'
  return ONBOARDING_STEPS.filter((step) => !step.audience || step.audience === audience)
}

export function firstStepForPath(
  pathname: string,
  isHost: boolean,
  startAt = 0,
): OnboardingStep | null {
  const steps = stepsForAudience(isHost)
  return steps.find((step, index) => index >= startAt && step.route === pathname) ?? null
}

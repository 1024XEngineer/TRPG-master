export type OnboardingAudience = 'host' | 'player'

export interface OnboardingStep {
  id: string
  route: string
  target: string
  title: string
  description: string
  audience?: OnboardingAudience
  waitForTarget?: boolean
}

export const ONBOARDING_STEPS: readonly OnboardingStep[] = [
  {
    id: 'character-progress',
    route: '/room/character',
    target: 'character-progress',
    title: '按四步完成角色卡',
    description: '角色卡分为基础信息、属性、技能、背景四部分。先填写姓名等身份信息，已填写的内容会保留，也可以返回修改。',
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
    target: 'attribute-example-row',
    title: '先了解属性，再分配点数',
    description: '点击属性名旁的圆形说明按钮，可以查看每项属性的用途，幸运也可以查看。了解后再用 +/- 调整数值，并留意 HP、SAN、MP 等衍生属性的变化。',
    waitForTarget: true,
  },
  {
    id: 'skill-editor',
    route: '/room/character',
    target: 'skill-editor',
    title: '认清两种技能点',
    description: '上方两种点数是两份建卡预算。职业列表里的技能可以先花职业点，职业点用完后还能继续花兴趣点；兴趣列表里的技能则只能花兴趣点。优先强化符合职业或玩法方向的技能即可。',
    waitForTarget: true,
  },
  {
    id: 'credit-rating',
    route: '/room/character',
    target: 'credit-rating-editor',
    title: '单独设置信用评级',
    description: '信用评级代表调查员的经济状况与社会地位，必须落在当前职业标出的范围内。职业下限会占用职业技能点；高于下限的部分会占用兴趣技能点。',
    waitForTarget: true,
  },
  {
    id: 'character-submit',
    route: '/room/character',
    target: 'character-submit',
    title: '完成并保存角色卡',
    description: '背景和装备可以留空。确认关键信息后提交角色卡，保存成功会进入玩家准备页。',
    waitForTarget: true,
  },
  {
    id: 'player-status',
    route: '/room/ready',
    target: 'player-status',
    title: '确认玩家准备状态',
    description: '这里能查看谁已完成建卡；自己的角色卡可以查看或编辑。全员完成后由房主开始游戏。',
  },
  {
    id: 'action-input',
    route: '/room/play',
    target: 'action-input',
    title: '用自然语言描述行动',
    description: '你可以直接输入“检查门锁”“询问侦探”或“前往走廊”等行动，不限于固定选项。',
  },
  {
    id: 'tool-bar',
    route: '/room/play',
    target: 'tool-bar',
    title: '随时使用游戏工具',
    description: '底部可以打开角色卡、技能、地图和速记；需要主动掷骰时，使用输入框左侧的骰子按钮。',
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

export function firstReplayStepForPath(
  pathname: string,
  isHost: boolean,
  isTargetAvailable: (target: string) => boolean,
): OnboardingStep | null {
  const availableSteps = stepsForAudience(isHost).filter(
    (step) => step.route === pathname && isTargetAvailable(step.target),
  )

  if (pathname === '/room/character') {
    return availableSteps.find((step) => step.id !== 'character-progress')
      ?? availableSteps[0]
      ?? null
  }

  return availableSteps[0] ?? null
}

export type GameStatus = 'recommended' | 'coming-soon' | 'wip' | 'ready'

export type SystemStatus = 'ready' | 'wip'

export interface GameSystem {
  id: string
  name: string
  status: SystemStatus
}

export interface Scenario {
  id: string
  name: string
  nameEn: string
  description: string
  systemId: string
  difficulty: '入门' | '进阶' | '挑战'
  // 目前 SCENARIO_REGISTRY 里没有任何一条设置这个字段（本期只有一款内置
  // 模组真的能玩，其余都是展示用的预设数据），可选是为了如实反映现状。
  status?: 'ready' | 'wip'
  playerCount: string
  estimatedTime: string
  storyLabel: string
  subtitle: string
  storyPages: string[]
}

export interface GameManifest {
  id: string
  name: string
  icon: string
  description: string
  color: string
  borderColor: string
  iconBg: string
  iconColor: string
  status: GameStatus
  systems?: GameSystem[]
}

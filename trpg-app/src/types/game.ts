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

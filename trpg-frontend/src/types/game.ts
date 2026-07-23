export type GameStatus = 'recommended' | 'coming-soon' | 'wip' | 'ready'

export type SystemStatus = 'ready' | 'wip'

export interface GameSystem {
  id: string
  name: string
  status: SystemStatus
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

export type MessageType =
  | 'narration'
  | 'npc_dialogue'
  | 'player_speech'
  | 'player_action'
  | 'skill_check'
  | 'system'
  | 'whisper'

export type Visibility = 'public' | `whisper:${string}` | 'gm_only'

export interface CheckResult {
  skill: string
  roll: number
  target: number
  grade: string
}

export interface GameMessage {
  id: string
  type: MessageType
  content: string
  sender: 'ai_kp' | `player:${string}`
  visibility: Visibility
  timestamp: string
  metadata?: {
    checkResult?: CheckResult
    sceneTransition?: string
    promptActions?: string[]
  }
}

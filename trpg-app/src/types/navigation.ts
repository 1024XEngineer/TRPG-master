export type AppRoute =
  | '/login'
  | '/games'
  | `/games/${string}`
  | '/story'
  | '/character'
  | '/lobby'
  | '/room'

export interface RouteParams {
  gameId?: string
  systemId?: string
  roomCode?: string
}

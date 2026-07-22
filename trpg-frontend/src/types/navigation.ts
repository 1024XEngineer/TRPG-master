export type AppRoute =
  | '/auth/login'
  | '/auth/register'
  | '/home'
  | '/home/join'
  | '/home/create'
  | '/home/create/games'
  | `/home/create/games/${string}`
  | '/home/my-rooms'
  | `/home/my-rooms/review/${string}`
  | '/home/profile'
  | '/room/lobby'
  | '/room/story'
  | '/room/character'
  | '/room/ready'
  | '/room/play'

export interface RouteParams {
  gameId?: string
  systemId?: string
  roomCode?: string
}

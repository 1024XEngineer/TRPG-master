export type AppRoute =
  | '/auth/login'
  | '/auth/register'
  | '/home'
  | '/home/join'
  | '/home/create'
  | '/home/create/modules'
  | '/home/my-rooms'
  | `/home/my-rooms/review/${string}`
  | '/home/profile'
  | '/room/lobby'
  | '/room/story'
  | '/room/character'
  | '/room/ready'
  | '/room/play'

export interface RouteParams {
  roomCode?: string
}

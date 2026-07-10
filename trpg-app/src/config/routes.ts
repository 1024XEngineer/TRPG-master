export const ROUTES = {
  LOGIN: '/login',
  GAMES: '/games',
  SYSTEM: (gameId: string) => `/games/${gameId}`,
  SCENARIOS: (gameId: string, systemId: string) => `/games/${gameId}/scenarios/${systemId}`,
  STORY: '/story',
  CHARACTER: '/character',
  LOBBY: '/lobby',
  ROOM: '/room',
} as const

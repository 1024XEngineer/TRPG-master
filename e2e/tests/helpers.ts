import { createTrpgSdk, type TrpgSdk } from 'trpg-sdk'

const BASE_URL = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8000'

export function makeSdk(): TrpgSdk {
  return createTrpgSdk({ baseUrl: `${BASE_URL}/api/v1` })
}

/** 每个用例用不同账号，避免互相干扰（数据库虽然每次是新的，但同一次运行里
 *  多个用例共用一个后端，重名会真的撞上）。 */
export function unique(prefix: string): string {
  return `${prefix}_${Date.now()}${Math.floor(Math.random() * 10_000)}`
}

export interface TestPlayer {
  sdk: TrpgSdk
  token: string
  account: string
}

export async function registerPlayer(prefix = 'e2e'): Promise<TestPlayer> {
  const sdk = makeSdk()
  const account = unique(prefix)
  const result = await sdk.auth.register({
    account,
    password: 'e2e-test-1234',
    nickname: account,
  })
  return { sdk, token: result.token, account }
}

export interface TestRoom {
  host: TestPlayer
  roomId: string
  roomCode: string
  reconnectToken: string
  hostPlayerId: string
}

/** 建一个已经选好内置模组的房间，回到「可以开始建卡」的状态。 */
export async function createRoomWithModule(prefix = 'e2e'): Promise<TestRoom> {
  const host = await registerPlayer(prefix)
  const room = await host.sdk.rooms.create(
    {
      roomName: `${prefix} 房间`,
      nickname: host.account,
      maxPlayers: 6,
    },
    host.token
  )
  const modules = await host.sdk.rooms.listModules()
  await host.sdk.rooms.selectModule(
    room.roomId,
    { moduleId: modules[0].id, attributeGenMethod: 'point_buy' },
    room.reconnectToken
  )
  return {
    host,
    roomId: room.roomId,
    roomCode: room.roomCode,
    reconnectToken: room.reconnectToken,
    hostPlayerId: room.playerId,
  }
}

/** 内置 COC7 规则系统的 ruleset——很多用例都要拿它算合法数值。 */
export async function fetchCoc7Ruleset(sdk: TrpgSdk) {
  const games = await sdk.games.list()
  for (const game of games) {
    const systems = await sdk.games.listSystems(game.id)
    const coc7 = systems.find((s) => s.name === 'COC7')
    if (coc7) return { systemId: coc7.id, ruleset: await sdk.games.getRuleset(coc7.id) }
  }
  throw new Error('种子数据里没有 COC7 规则系统')
}

/** 一张能通过 complete 校验的合法角色卡（点数购买法）。 */
export function legalCharacterPayload(attributes: Record<string, number>) {
  return {
    name: 'E2E 调查员',
    age: 32,
    gender: '女',
    residence: '阿卡姆',
    birthplace: '波士顿',
    attributes,
    derivedStats: {},
    // 会计师信用区间 [30, 70]，取下限即可——信用是必填技能，不填会被
    // CREDIT_OUT_OF_RANGE 拒。
    skills: { 'credit-rating': 30 },
    equipment: [],
    occupation: '会计师',
    background: '',
    notes: '',
  }
}

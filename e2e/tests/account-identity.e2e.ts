/**
 * 账号身份贯通与断线重连（issue #106）。
 *
 * 这条链路是 SDK 层 e2e 最该守的东西之一：它跨越「账号」和「房间」两套凭证，
 * 而两套凭证互相搞混正是这个 issue 的由来。浏览器层测同样的东西要开两个上下文、
 * 还得模拟断线；这里在一个进程里换个 SDK 实例就等价于「换了台设备」。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { createRoomWithModule, makeSdk, registerPlayer } from './helpers.ts'

test('🔴 老成员重连：同一账号再次 join 拿回同一个身份，人数不变', async () => {
  const room = await createRoomWithModule('rejoin')
  const guest = await registerPlayer('rejoinguest')

  const first = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)
  const second = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  assert.equal(second.playerId, first.playerId, '重连必须拿回同一个 playerId')
  assert.equal(second.reconnectToken, first.reconnectToken)

  // 改动前这里会变成 3：join 不检查调用者是不是已经在房间里，无条件新建 Player，
  // 同一个人重复加入就虚增人数，直到撞满员。
  const preview = await room.host.sdk.rooms.getInfo(room.roomCode)
  assert.equal(preview.players.length, 2, '重复加入不该多出一个玩家')
})

test('🔴 换设备重连：新的客户端实例只凭账号 token 就能拿回房间身份', async () => {
  // 这条是账号体系存在的理由本身。`reconnectToken` 存在浏览器会话里，换设备就
  // 没了；只有按账号幂等，才谈得上「换台设备继续这局」。
  const room = await createRoomWithModule('device')
  const guest = await registerPlayer('deviceguest')
  const original = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  // 全新的 SDK 实例 = 另一台设备：没有任何本地状态，只有账号 token
  const otherDevice = makeSdk()
  const recovered = await otherDevice.rooms.join(
    room.roomCode,
    { nickname: '访客' },
    guest.token
  )

  assert.equal(recovered.playerId, original.playerId)
  assert.equal(recovered.reconnectToken, original.reconnectToken, '换设备也要能拿回房间凭证')
})

test('🔴 游戏开始后：老成员能重连，新人被拒', async () => {
  // 一对互为对照的断言。改动前这里是一刀切 `if phase != Lobby: 409`，把「中途
  // 加入」和「掉线重连」当成同一件事拒掉——只测其中一边的话，「一刀切拒绝」和
  // 「一刀切放行」各能通过一条。
  const room = await createRoomWithModule('phase')
  const guest = await registerPlayer('phaseguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  await room.host.sdk.rooms.startStory(room.roomId, room.reconnectToken)

  const rejoined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)
  assert.equal(rejoined.playerId, joined.playerId, '老成员在 Building 阶段必须能重连')

  const latecomer = await registerPlayer('latecomer')
  await assert.rejects(
    () => latecomer.sdk.rooms.join(room.roomCode, { nickname: '迟到' }, latecomer.token),
    (error: Error) => {
      assert.match(error.message, /已开始|CONFLICT/)
      return true
    },
    '新人在 Building 阶段必须被拒'
  )
})

test('🔴 换设备重连能拿回角色卡 id（否则会被引导重建一张）', async () => {
  // PR #110 review [1]：客户端靠 `characterId` 才知道去拉哪张卡，而在此之前这个
  // id 只在建卡那一刻由客户端自己存着——换台设备就永远拿不回来，已经建完卡的人
  // 重连后会显示成「还没建卡」。这条正好补上「换设备重连」那条用例的缺口：光有
  // 房间身份不够，角色身份也要能恢复。
  const room = await createRoomWithModule('charid')
  const guest = await registerPlayer('charidguest')
  const joined = await guest.sdk.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)
  assert.equal(joined.characterId, null, '还没建卡时应该是 null')

  const draft = await guest.sdk.characters.createDraft(room.roomId, joined.reconnectToken)

  // 全新 SDK 实例 = 另一台设备，只有账号 token
  const otherDevice = makeSdk()
  const recovered = await otherDevice.rooms.join(room.roomCode, { nickname: '访客' }, guest.token)

  assert.equal(recovered.characterId, draft.characterId)
})

test('我的游戏：按账号返回全部房间，且不泄漏别人的', async () => {
  const first = await createRoomWithModule('mine1')
  // 同一个账号再建一个房间——用它自己的 sdk/token
  const second = await first.host.sdk.rooms.create(
    { roomName: '第二间', nickname: first.host.account, maxPlayers: 4 },
    first.host.token
  )

  const mine = await first.host.sdk.rooms.listMyRooms(first.host.token)
  const myIds = new Set(mine.map((room) => room.roomId))

  // 改动前按 reconnectToken 查、只返回一个房间——「我的游戏」实际是
  // 「这个浏览器的最后一个房间」。
  assert.ok(myIds.has(first.roomId), '第一个房间应该在我的列表里')
  assert.ok(myIds.has(second.roomId), '第二个房间也应该在')

  // 对照面：别人的房间不能出现。只断言「我的两个都在」的话，一个"返回全部
  // 房间"的错误实现照样能通过。
  const stranger = await createRoomWithModule('stranger')
  assert.ok(!myIds.has(stranger.roomId), '别人的房间不该出现在我的列表里')
})

test('创建/加入房间要求登录', async () => {
  // 不带账号 token 的裸客户端
  const anonymous = makeSdk()
  await assert.rejects(
    () => anonymous.rooms.create({ roomName: '匿名房', nickname: '匿名', maxPlayers: 4 }, ''),
    (error: Error) => {
      assert.match(error.message, /登录|UNAUTHORIZED/)
      return true
    },
    '未登录不该能创建房间'
  )

  const room = await createRoomWithModule('authreq')
  await assert.rejects(
    () => anonymous.rooms.join(room.roomCode, { nickname: '匿名' }, ''),
    (error: Error) => {
      assert.match(error.message, /登录|UNAUTHORIZED/)
      return true
    },
    '未登录不该能加入房间'
  )
})

test('建房会把房间关联到账号（否则我的游戏查不到它）', async () => {
  const room = await createRoomWithModule('linked')

  const mine = await room.host.sdk.rooms.listMyRooms(room.host.token)

  assert.deepEqual(
    mine.map((r) => r.roomId),
    [room.roomId],
    'host_user_id 没落上的话，这里会是空列表'
  )
})

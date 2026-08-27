/** Published module and player-facing catalog contract for issue #154. */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { makeSdk, registerPlayer } from './helpers.ts'

test('世界标签、追书人 v3 发布元数据和玩家安全开局简介正确', async () => {
  const sdk = makeSdk()
  const games = await sdk.games.list()
  const coc = games.find((game) => game.name === '克苏鲁的呼唤')
  assert.ok(coc)
  assert.deepEqual(coc.tags, ['1920年代', '调查悬疑', '宇宙恐怖'])

  const systems = await sdk.games.listSystems(coc.id)
  assert.equal(systems[0]?.name, 'COC7')

  const modules = await sdk.rooms.listModules()
  const paperChase = modules.find((module) => module.id === 'paper-chase-zh-coc7')
  assert.ok(paperChase)
  assert.equal(paperChase.title, '追书人')
  assert.equal(paperChase.nameEn, 'Paper Chase')
  assert.equal(paperChase.version, '3.0.10')
  assert.equal(paperChase.playersMin, 1)
  assert.equal(paperChase.playersMax, 4)
  assert.equal(paperChase.estimatedDuration, '1-2 小时')
  assert.ok(!paperChase.synopsis?.includes('MS1'))

  const detail = await sdk.modules.getDetail(paperChase.id)
  assert.equal(detail.storyPages.length, 2)
  const publicText = detail.storyPages.map((page) => page.content).join(' ')
  assert.ok(!publicText.includes('食尸鬼'))
  assert.ok(!publicText.includes('地穴'))
})

test('房间人数必须符合追书人发布范围', async () => {
  const player = await registerPlayer('module-range')
  const module = (await player.sdk.rooms.listModules()).find(
    (item) => item.id === 'paper-chase-zh-coc7'
  )
  assert.ok(module)

  const four = await player.sdk.rooms.create(
    { roomName: '四人校验', nickname: player.account, maxPlayers: 4 },
    player.token,
  )
  await player.sdk.rooms.selectModule(
    four.roomId,
    { moduleId: module.id, attributeGenMethod: 'point_buy' },
    four.reconnectToken,
  )

  const five = await player.sdk.rooms.create(
    { roomName: '五人校验', nickname: player.account, maxPlayers: 5 },
    player.token,
  )
  await assert.rejects(
    () =>
      player.sdk.rooms.selectModule(
        five.roomId,
        { moduleId: module.id, attributeGenMethod: 'point_buy' },
        five.reconnectToken,
      ),
    (error: Error) => {
      assert.match(error.message, /MODULE_PLAYER_COUNT_MISMATCH|要求 1-4/)
      return true
    },
  )
})

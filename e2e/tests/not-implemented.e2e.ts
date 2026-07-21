/**
 * 钉住「目前还是桩」的那些接口。
 *
 * 这类用例的作用不是保护现状，而是**当它们变红时提醒我们去接**：队友把
 * 掷骰检定 / 模组导入 / 复盘摘要真正实现之后，这里会失败，我们就知道该把
 * 对应的客户端接入补上，而不是等到某天有人手工发现"后端早就能用了"。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { createRoomWithModule } from './helpers.ts'

test('复盘摘要仍是 NOT_IMPLEMENTED（依赖 AI 编排）', async () => {
  const room = await createRoomWithModule('stub')
  await assert.rejects(
    () => room.host.sdk.rooms.getSummary(room.roomId, room.reconnectToken),
    '这条变绿说明复盘摘要已经实现，该去接客户端了'
  )
})

test('常用角色卡库仍是 NOT_IMPLEMENTED', async () => {
  const room = await createRoomWithModule('stub2')
  await assert.rejects(
    () => room.host.sdk.characterTemplates.list(room.host.token),
    '这条变绿说明常用卡库已经实现，该去接客户端了'
  )
})

test('复盘事件流已经是真实现（不是桩）', async () => {
  // 跟上面两条相反：replay 是真的，客户端却从没调用过——属于「后端能力就绪
  // 但没接」，不是功能缺失。
  const room = await createRoomWithModule('replay')
  const events = await room.host.sdk.rooms.getReplay(room.roomId, room.reconnectToken)
  assert.ok(Array.isArray(events), 'replay 应该返回事件数组')
})

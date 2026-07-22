/**
 * 钉住「目前还是桩」的那些接口。
 *
 * 这类用例的作用不是保护现状，而是**当它们变红时提醒我们去接**：队友把
 * 掷骰检定 / 模组导入 / 复盘摘要真正实现之后，这里会失败，我们就知道该把
 * 对应的客户端接入补上，而不是等到某天有人手工发现"后端早就能用了"。
 */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ApiError } from 'trpg-sdk'

import { createRoomWithModule } from './helpers.ts'

/**
 * 断言的是**具体的 501 / NOT_IMPLEMENTED 契约**，不是「这个调用会失败」。
 *
 * 只要求 Promise 拒绝的话，路由被删成 404、后端内部报错变成 500、甚至响应解析
 * 失败，这里都会继续绿——真正的回归会被误判成「仍是桩」，正好和这两条用例想
 * 提供的信号相反。后端刻意用 501 而不是 500，就是为了让客户端能区分「服务器出
 * bug 了」和「这个功能确实还没做」（见 `app/core/errors.py::not_implemented`），
 * 那这里就该把这个区分钉住。
 */
function assertNotImplemented(hint: string) {
  return (error: unknown) => {
    assert.ok(error instanceof ApiError, `${hint}（期望 ApiError，实际 ${String(error)}）`)
    assert.equal(error.code, 'NOT_IMPLEMENTED', hint)
    assert.equal(error.status, 501, hint)
    return true
  }
}

test('复盘摘要仍是 NOT_IMPLEMENTED（依赖 AI 编排）', async () => {
  const room = await createRoomWithModule('stub')
  await assert.rejects(
    () => room.host.sdk.rooms.getSummary(room.roomId, room.reconnectToken),
    assertNotImplemented('这条变红说明复盘摘要已经实现（或者坏了），该去看客户端要不要接')
  )
})

test('常用角色卡库仍是 NOT_IMPLEMENTED', async () => {
  const room = await createRoomWithModule('stub2')
  await assert.rejects(
    () => room.host.sdk.characterTemplates.list(room.host.token),
    assertNotImplemented('这条变红说明常用卡库已经实现（或者坏了），该去看客户端要不要接')
  )
})

test('复盘事件流已经是真实现（不是桩）', async () => {
  // 跟上面两条相反：replay 是真的，客户端却从没调用过——属于「后端能力就绪
  // 但没接」，不是功能缺失。
  const room = await createRoomWithModule('replay')
  const events = await room.host.sdk.rooms.getReplay(room.roomId, room.reconnectToken)
  assert.ok(Array.isArray(events), 'replay 应该返回事件数组')
})

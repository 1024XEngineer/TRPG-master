/**
 * RoomSocket 的运行时校验 + waitForOpen 测试（issue #75 决策 5、SDK 缺陷修复）。
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { isValidServerEvent, RoomSocket } from './room-socket';

test('isValidServerEvent：接受已知类型的合法事件', () => {
  assert.equal(
    isValidServerEvent({ type: 'session.bound', payload: { roomId: 'r1', playerId: 'p1' } }),
    true
  );
  assert.equal(isValidServerEvent({ type: 'narration.push', payload: { text: 'hi' } }), true);
});

test('isValidServerEvent：拒绝未知 type', () => {
  assert.equal(isValidServerEvent({ type: 'not.a.real.event', payload: {} }), false);
});

test('isValidServerEvent：拒绝缺 payload / payload 不是对象 / 顶层不是对象', () => {
  assert.equal(isValidServerEvent({ type: 'session.bound' }), false);
  assert.equal(isValidServerEvent({ type: 'session.bound', payload: 'nope' }), false);
  assert.equal(isValidServerEvent(null), false);
  assert.equal(isValidServerEvent('session.bound'), false);
});

test('waitForOpen：连接失败时 reject 的是 Error，且 cause 是原始 Event', async () => {
  const socket = new RoomSocket('ws://127.0.0.1');
  // 连一个必然被拒绝的端口，触发真实的 WebSocket error 事件。
  const ws = new WebSocket('ws://127.0.0.1:1');
  try {
    await assert.rejects(
      () => socket.waitForOpen(ws),
      (err: unknown) => {
        assert.ok(err instanceof Error);
        assert.ok(err.cause instanceof Event);
        return true;
      }
    );
  } finally {
    ws.close();
  }
});

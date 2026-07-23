/**
 * RoomSocket 的运行时校验 + waitForOpen 测试（issue #75 决策 5、SDK 缺陷修复）。
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { TurnCompletedEvent } from '../types';
import { isValidServerEvent, isValidTurnCompleted, RoomSocket } from './room-socket';

const completedEvent = {
  protocol_version: '1',
  message_type: 'turn.completed',
  correlation_id: 'action-123',
  payload: {
    room_id: 'room-1',
    player_id: 'player-1',
    actor_id: 'actor-1',
    narration: {
      kind: 'narration',
      text: '规则已经确认了这次行动。',
      claimed_fact_ids: [],
      suggested_actions: [],
    },
    player_view: {
      room_id: 'room-1',
      player_id: 'player-1',
      actor_id: 'actor-1',
      scene_id: 'scene-1',
      phase: 'playing',
      revision: '1',
      visible_facts: [],
      visible_entities: [],
      checkpoint_options: [],
    },
  },
} satisfies TurnCompletedEvent;

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

// 回归测试：type 对、payload 是对象，但 payload 里的字段缺失或类型不对。
// 这类消息一度能通过校验并被当成合法事件下发给订阅者——而这个函数向
// TypeScript 断言了 `value is ServerToClientEvent`，等于让下游在
// payload.text 实际是 undefined/number 时仍以为自己拿到的是 string
// （PR #76 review 指出）。
test('isValidServerEvent：拒绝 payload 字段缺失或类型不对', () => {
  // 缺字段
  assert.equal(isValidServerEvent({ type: 'narration.push', payload: {} }), false);
  assert.equal(isValidServerEvent({ type: 'session.bound', payload: {} }), false);
  assert.equal(isValidServerEvent({ type: 'session.bound', payload: { roomId: 'r1' } }), false);
  // 字段类型不对
  assert.equal(isValidServerEvent({ type: 'narration.push', payload: { text: 123 } }), false);
  assert.equal(
    isValidServerEvent({ type: 'session.bound', payload: { roomId: 'r1', playerId: 42 } }),
    false
  );
});

test('isValidTurnCompleted：接受 Agent v1 回合结果', () => {
  assert.equal(isValidTurnCompleted(completedEvent), true);
});

test('isValidTurnCompleted：拒绝未知版本、身份不一致和非法 PlayerView', () => {
  assert.equal(
    isValidTurnCompleted({ ...completedEvent, protocol_version: '2' }),
    false
  );
  assert.equal(
    isValidTurnCompleted({
      ...completedEvent,
      payload: {
        ...completedEvent.payload,
        player_view: { ...completedEvent.payload.player_view, player_id: 'another-player' },
      },
    }),
    false
  );
  assert.equal(
    isValidTurnCompleted({
      ...completedEvent,
      payload: {
        ...completedEvent.payload,
        player_view: { ...completedEvent.payload.player_view, revision: 2 },
      },
    }),
    false
  );
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

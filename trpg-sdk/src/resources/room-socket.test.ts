/**
 * RoomSocket 的运行时校验 + waitForOpen 测试（issue #75 决策 5、SDK 缺陷修复）。
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { TurnCompletedEvent } from '../types';
import {
  isValidServerEvent,
  isValidTurnCompleted,
  RoomSocket,
  RoomSocketServerError,
  RoomSocketTransportError,
  TurnFailedError,
} from './room-socket';

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
      self_actor: {
        id: 'actor-1',
        name: '调查员',
        occupation: null,
        attributes: [],
        skills: [],
        resources: [],
        conditions: [],
        equipment: [],
        background_summary: '',
      },
      scene: {
        id: 'scene-1',
        name: '书房',
        description: '一间安静的书房。',
        time: 'night',
        visible_entities: [],
        visible_actors: [],
        available_exits: [],
      },
      world: {
        elapsed_minutes: 0,
        time_of_day: 'night',
        core_resolved: false,
        ending_available: false,
        ending_id: null,
      },
      known_information: [],
      checkpoint_options: [],
    },
  },
} satisfies TurnCompletedEvent;

test('isValidServerEvent：接受已知类型的合法事件', () => {
  assert.equal(
    isValidServerEvent({ type: 'session.bound', payload: { roomId: 'r1', playerId: 'p1' } }),
    true
  );
  assert.equal(
    isValidServerEvent({
      type: 'action.broadcast',
      payload: {
        playerId: 'player-1',
        clientActionId: 'action-1',
        nickname: '房主',
        characterName: '陈探员',
        utterance: '我查看书架',
      },
    }),
    true
  );
  assert.equal(isValidServerEvent({ type: 'narration.push', payload: { text: 'hi' } }), true);
  assert.equal(
    isValidServerEvent({
      type: 'narration.push',
      payload: { messageId: 'game-opening', text: 'hi' },
    }),
    true
  );
  assert.equal(
    isValidServerEvent({
      type: 'opening.started',
      payload: { messageId: 'game-opening' },
    }),
    true
  );
  assert.equal(
    isValidServerEvent({
      type: 'turn.phase_changed',
      payload: { correlationId: 'a1', phase: 'understanding_action' },
    }),
    true
  );
  assert.equal(
    isValidServerEvent({
      type: 'turn.failed',
      payload: {
        correlationId: 'a1',
        code: 'HOST_AGENT_TIMEOUT',
        publicMessage: '请重试',
        retryable: true,
      },
    }),
    true
  );
  assert.equal(
    isValidServerEvent({
      type: 'view.updated',
      payload: {
        playerId: 'player-1',
        playerView: completedEvent.payload.player_view,
      },
    }),
    true
  );
});

test('isValidServerEvent：拒绝未知 type', () => {
  assert.equal(isValidServerEvent({ type: 'not.a.real.event', payload: {} }), false);
});

test('isValidServerEvent：接受缺少 characterName 的旧 action.broadcast', () => {
  assert.equal(
    isValidServerEvent({
      type: 'action.broadcast',
      payload: {
        playerId: 'player-1',
        clientActionId: 'action-1',
        nickname: '房主',
        utterance: '我查看书架',
      },
    }),
    true
  );
});

test('isValidServerEvent：narration.chunk 需要非空 messageId、非负整数 sequence 和字符串 text', () => {
  assert.equal(
    isValidServerEvent({
      type: 'narration.chunk',
      payload: { messageId: 'game-opening', sequence: 0, text: '雨点敲打着窗框。' },
    }),
    true
  );
  // 空 messageId 无法把片段归到某一条消息上。
  assert.equal(
    isValidServerEvent({
      type: 'narration.chunk',
      payload: { messageId: '', sequence: 0, text: '雨点敲打着窗框。' },
    }),
    false
  );
  // sequence 决定拼接顺序，小数或负数都会让去重与排序失去意义。
  assert.equal(
    isValidServerEvent({
      type: 'narration.chunk',
      payload: { messageId: 'game-opening', sequence: 1.5, text: '片段' },
    }),
    false
  );
  assert.equal(
    isValidServerEvent({
      type: 'narration.chunk',
      payload: { messageId: 'game-opening', sequence: -1, text: '片段' },
    }),
    false
  );
  assert.equal(
    isValidServerEvent({
      type: 'narration.chunk',
      payload: { messageId: 'game-opening', sequence: 0, text: 42 },
    }),
    false
  );
  assert.equal(
    isValidServerEvent({ type: 'narration.chunk', payload: { messageId: 'game-opening' } }),
    false
  );
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
    isValidServerEvent({ type: 'narration.push', payload: { messageId: '', text: 'hi' } }),
    false
  );
  assert.equal(
    isValidServerEvent({ type: 'narration.push', payload: { messageId: 42, text: 'hi' } }),
    false
  );
  assert.equal(
    isValidServerEvent({ type: 'opening.started', payload: { messageId: '' } }),
    false
  );
  assert.equal(
    isValidServerEvent({ type: 'session.bound', payload: { roomId: 'r1', playerId: 42 } }),
    false
  );
  assert.equal(
    isValidServerEvent({
      type: 'action.broadcast',
      payload: {
        playerId: 'player-1',
        clientActionId: 'action-1',
        nickname: '房主',
        characterName: 42,
        utterance: '我查看书架',
      },
    }),
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
        assert.ok(err instanceof RoomSocketTransportError);
        assert.ok(err.cause instanceof Event);
        return true;
      }
    );
  } finally {
    ws.close();
  }
});

test('turn.failed reject pending action，view.updated 更新同一份缓存', async () => {
  class FakeWebSocket {
    static readonly OPEN = 1;
    static readonly CONNECTING = 0;
    readonly readyState = FakeWebSocket.OPEN;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    sent: string[] = [];

    constructor(readonly url: string) {}

    send(data: string) {
      this.sent.push(data);
    }

    close() {}

    addEventListener() {}

    emit(value: unknown) {
      this.onmessage?.({ data: JSON.stringify(value) });
    }

    emitClose() {
      this.onclose?.();
    }
  }

  const original = globalThis.WebSocket;
  Object.defineProperty(globalThis, 'WebSocket', {
    configurable: true,
    value: FakeWebSocket,
  });
  try {
    const socket = new RoomSocket('ws://example.test');
    const transport = socket.connect('room-1', 'token') as unknown as FakeWebSocket;
    transport.emit({
      type: 'view.updated',
      payload: {
        playerId: 'player-1',
        playerView: completedEvent.payload.player_view,
      },
    });
    assert.deepEqual(socket.getPlayerView(), completedEvent.payload.player_view);

    transport.emit({
      type: 'opening.started',
      payload: { messageId: 'game-opening' },
    });
    assert.equal(socket.getOpeningMessageId(), 'game-opening');
    transport.emit({
      type: 'narration.push',
      payload: { messageId: 'game-opening', text: '权威开场' },
    });
    assert.equal(socket.getOpeningMessageId(), null);

    transport.emit({
      type: 'opening.started',
      payload: { messageId: 'game-opening' },
    });
    transport.emit({
      type: 'error',
      payload: { code: 'OPENING_FAILED', message: '开场失败' },
    });
    assert.equal(socket.getOpeningMessageId(), null);

    const pending = socket.submitAction('player-1', {
      clientActionId: 'failed-action',
      utterance: '调查书架',
    });
    transport.emit({
      type: 'turn.failed',
      payload: {
        correlationId: 'failed-action',
        code: 'HOST_AGENT_TIMEOUT',
        publicMessage: '主持 Agent 响应超时，请重试',
        retryable: true,
      },
    });
    await assert.rejects(
      pending,
      (error: unknown) =>
        error instanceof TurnFailedError &&
        error.message === '主持 Agent 响应超时，请重试' &&
        error.code === 'HOST_AGENT_TIMEOUT' &&
        error.retryable &&
        error.correlationId === 'failed-action'
    );

    const rejectedAction = socket.submitAction('player-1', {
      clientActionId: 'busy-action',
      utterance: '继续调查书架',
    });
    transport.emit({
      type: 'error',
      payload: {
        code: 'ACTION_IN_PROGRESS',
        message: '守秘人正在处理其他行动，请稍候',
        correlationId: 'busy-action',
      },
    });
    await assert.rejects(
      rejectedAction,
      (error: unknown) =>
        error instanceof RoomSocketServerError &&
        error.code === 'ACTION_IN_PROGRESS' &&
        error.correlationId === 'busy-action'
    );

    const retriedAction = socket.submitAction('player-1', {
      clientActionId: 'busy-action',
      utterance: '继续调查书架',
    });
    assert.notEqual(retriedAction, rejectedAction);
    transport.emit({
      ...completedEvent,
      correlation_id: 'busy-action',
    });
    await assert.doesNotReject(retriedAction);

    const interruptedAction = socket.submitAction('player-1', {
      clientActionId: 'interrupted-action',
      utterance: '查看门外',
    });
    transport.emitClose();
    await assert.rejects(
      interruptedAction,
      (error: unknown) =>
        error instanceof RoomSocketTransportError &&
        error.message === 'WebSocket connection closed'
    );
  } finally {
    Object.defineProperty(globalThis, 'WebSocket', {
      configurable: true,
      value: original,
    });
  }
});

test('未连接时 submitAction reject RoomSocketTransportError', async () => {
  const socket = new RoomSocket('ws://example.test');
  await assert.rejects(
    socket.submitAction('player-1', {
      clientActionId: 'not-connected',
      utterance: '调查书架',
    }),
    (error: unknown) =>
      error instanceof RoomSocketTransportError &&
      error.message === 'WebSocket is not connected'
  );
});

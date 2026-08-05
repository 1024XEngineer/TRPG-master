import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiClient } from '../client';
import { RoomsResource } from './rooms';

function captureRequest(): {
  rooms: RoomsResource;
  captured: () => { url: string; headers: Headers; signal: AbortSignal | null } | undefined;
} {
  let captured: { url: string; headers: Headers; signal: AbortSignal | null } | undefined;
  const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    captured = {
      url: String(input),
      headers: new Headers(init?.headers),
      signal: init?.signal ?? null,
    };
    return new Response(JSON.stringify({ success: true, data: [], error: null }));
  }) as typeof fetch;

  const client = new ApiClient({ baseUrl: 'http://test/api/v1', fetch: fakeFetch });
  return { rooms: new RoomsResource(client), captured: () => captured };
}

test('listConversation 调用房间对话历史接口并携带房间凭证', async () => {
  const { rooms, captured } = captureRequest();

  await rooms.listConversation('room-1', 'reconnect-token-1');

  assert.equal(captured()?.url, 'http://test/api/v1/rooms/room-1/conversation');
  assert.equal(captured()?.headers.get('x-reconnect-token'), 'reconnect-token-1');
});

test('主持人语音 manifest 对路径编码并同时携带两种身份', async () => {
  const { rooms, captured } = captureRequest();
  await rooms.getHostSpeechManifest('room/1', 'message/1', 'account-token', 'reconnect-token');
  assert.equal(
    captured()?.url,
    'http://test/api/v1/rooms/room%2F1/narrations/message%2F1/speech',
  );
  assert.equal(captured()?.headers.get('authorization'), 'Bearer account-token');
  assert.equal(captured()?.headers.get('x-reconnect-token'), 'reconnect-token');
});

test('主持人语音单句读取 MP3 并透传取消信号', async () => {
  const controller = new AbortController();
  const { rooms, captured } = captureRequest();
  const blob = await rooms.getHostSpeechSentence(
    'room-1', 'message-1', 2, 'account-token', 'reconnect-token', controller.signal,
  );
  assert.ok(blob instanceof Blob);
  assert.equal(
    captured()?.url,
    'http://test/api/v1/rooms/room-1/narrations/message-1/speech/sentences/2',
  );
  assert.equal(captured()?.signal, controller.signal);
});

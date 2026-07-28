import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiClient } from '../client';
import { RoomsResource } from './rooms';

function captureRequest(): {
  rooms: RoomsResource;
  captured: () => { url: string; headers: Headers } | undefined;
} {
  let captured: { url: string; headers: Headers } | undefined;
  const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    captured = {
      url: String(input),
      headers: new Headers(init?.headers),
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

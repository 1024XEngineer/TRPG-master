import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createTrpgSdk } from '../index';

test('rooms.listConversation calls the room conversation endpoint with reconnect token', async () => {
  let capturedUrl = '';
  let capturedHeaders: Headers | undefined;
  const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    capturedUrl = String(input);
    capturedHeaders = new Headers(init?.headers);
    return new Response(JSON.stringify({ success: true, data: [], error: null }));
  }) as typeof fetch;

  const sdk = createTrpgSdk({ baseUrl: 'http://test/api/v1', fetch: fakeFetch });
  const history = await sdk.rooms.listConversation('room-1', 'reconnect-1');

  assert.deepEqual(history, []);
  assert.equal(capturedUrl, 'http://test/api/v1/rooms/room-1/conversation');
  assert.equal(capturedHeaders?.get('x-reconnect-token'), 'reconnect-1');
});

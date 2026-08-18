import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiClient } from '../client';
import { CharacterTemplatesResource } from './character-templates';

test('getPortrait 编码路径和版本并返回账号鉴权 Blob', async () => {
  let captured: { url: string; method?: string; headers: Headers } | undefined;
  const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    captured = {
      url: String(input),
      method: init?.method,
      headers: new Headers(init?.headers)
    };
    return new Response(new Blob(['template-portrait'], { type: 'image/png' }), {
      headers: { 'Content-Type': 'image/png' }
    });
  }) as typeof fetch;
  const templates = new CharacterTemplatesResource(
    new ApiClient({ baseUrl: 'http://test/api/v1', fetch: fakeFetch })
  );

  const result = await templates.getPortrait('template /一', 'hash +/=', 'account-token');

  assert.equal(
    captured?.url,
    'http://test/api/v1/me/character-templates/template%20%2F%E4%B8%80/portrait?v=hash%20%2B%2F%3D'
  );
  assert.equal(captured?.method, 'GET');
  assert.equal(captured?.headers.get('authorization'), 'Bearer account-token');
  assert.equal(await result.text(), 'template-portrait');
});

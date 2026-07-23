/**
 * `ApiClient` 的 header 合并逻辑测试（issue #75）。
 *
 * 用 node:test（不引入 vitest 之类的 devDependency——SDK 已经零运行时依赖，
 * 测试跑起来也不需要更重的框架，node 自带的 test runner 加 tsx 转译足够）。
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiClient } from './client';

/** 造一个记录下"实际发给 fetch 的 headers"的假 fetch，用来断言合并结果。 */
function captureHeaders(): { client: ApiClient; captured: () => Headers | undefined } {
  let captured: Headers | undefined;
  const fakeFetch = (async (_input: string, init?: RequestInit) => {
    captured = new Headers(init?.headers);
    return new Response(JSON.stringify({ success: true, data: null, error: null }));
  }) as typeof fetch;

  const client = new ApiClient({ baseUrl: 'http://test', fetch: fakeFetch });
  return { client, captured: () => captured };
}

test('header 合并：Record<string,string> 形态', async () => {
  const { client, captured } = captureHeaders();
  await client.get('/x', { headers: { Authorization: 'Bearer abc' } });
  assert.equal(captured()?.get('authorization'), 'Bearer abc');
  assert.equal(captured()?.get('content-type'), 'application/json');
});

test('header 合并：Headers 实例形态', async () => {
  const { client, captured } = captureHeaders();
  await client.get('/x', { headers: new Headers({ Authorization: 'Bearer abc' }) });
  assert.equal(captured()?.get('authorization'), 'Bearer abc');
  assert.equal(captured()?.get('content-type'), 'application/json');
});

test('header 合并：string[][] 形态', async () => {
  const { client, captured } = captureHeaders();
  await client.get('/x', { headers: [['Authorization', 'Bearer abc']] });
  assert.equal(captured()?.get('authorization'), 'Bearer abc');
  assert.equal(captured()?.get('content-type'), 'application/json');
});

test('调用方传的 header 可以覆盖默认的 Content-Type', async () => {
  const { client, captured } = captureHeaders();
  await client.get('/x', { headers: { 'Content-Type': 'text/plain' } });
  assert.equal(captured()?.get('content-type'), 'text/plain');
});

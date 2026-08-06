/**
 * `ApiClient` 的 header 合并逻辑测试（issue #75）。
 *
 * 用 node:test（不引入 vitest 之类的 devDependency——SDK 已经零运行时依赖，
 * 测试跑起来也不需要更重的框架，node 自带的 test runner 加 tsx 转译足够）。
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiClient, ApiError } from './client';

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

test('二进制成功响应读取 Blob，且不强加 JSON Content-Type', async () => {
  let headers: Headers | undefined;
  const client = new ApiClient({
    baseUrl: 'http://test',
    fetch: (async (_input, init) => {
      headers = new Headers(init?.headers);
      return new Response(new Blob(['mp3']), { headers: { 'Content-Type': 'audio/mpeg' } });
    }) as typeof fetch,
  });
  const blob = await client.requestBlob('/audio', { signal: new AbortController().signal });
  assert.equal(blob.type, 'audio/mpeg');
  assert.equal(headers?.has('content-type'), false);
});

test('二进制接口失败时解析统一 JSON 错误', async () => {
  const client = new ApiClient({
    baseUrl: 'http://test',
    fetch: (async () => new Response(JSON.stringify({
      success: false,
      data: null,
      error: { code: 'HOST_SPEECH_FAILED', message: '合成失败' },
    }), { status: 502, headers: { 'Content-Type': 'application/json' } })) as typeof fetch,
  });
  await assert.rejects(
    client.requestBlob('/audio'),
    (error: unknown) => error instanceof ApiError && error.code === 'HOST_SPEECH_FAILED' && error.status === 502,
  );
});

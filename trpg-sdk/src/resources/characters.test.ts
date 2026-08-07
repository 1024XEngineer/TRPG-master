import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ApiClient } from '../client';
import { CharactersResource } from './characters';

test('generatePortrait 调用角色生图接口并携带房间凭证', async () => {
  let captured:
    | { url: string; method: string | undefined; headers: Headers; body: string | null | undefined }
    | undefined;
  const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    captured = {
      url: String(input),
      method: init?.method,
      headers: new Headers(init?.headers),
      body: typeof init?.body === 'string' ? init.body : null
    };
    return new Response(
      JSON.stringify({
        success: true,
        data: {
          generationId: 'generation-1',
          status: 'completed',
          imageUrl: 'https://images.example/portrait.png',
          prompt: 'portrait prompt',
          negativePrompt: 'watermark',
          promptSummary: '根据职业与背景生成',
          promptSource: 'deepseek'
        },
        error: null
      })
    );
  }) as typeof fetch;
  const characters = new CharactersResource(
    new ApiClient({ baseUrl: 'http://test/api/v1', fetch: fakeFetch })
  );

  const result = await characters.generatePortrait(
    'room-1',
    'character-1',
    { style: 'realistic', size: '1024x1024' },
    'reconnect-token-1'
  );

  assert.equal(
    captured?.url,
    'http://test/api/v1/rooms/room-1/characters/character-1/portrait-generations'
  );
  assert.equal(captured?.method, 'POST');
  assert.equal(captured?.headers.get('x-reconnect-token'), 'reconnect-token-1');
  assert.deepEqual(JSON.parse(captured?.body ?? '{}'), {
    style: 'realistic',
    size: '1024x1024'
  });
  assert.equal(result.promptSource, 'deepseek');
});

test('quickGenerate 调用一键生成接口并携带房间凭证', async () => {
  let captured:
    | { url: string; method: string | undefined; headers: Headers; body: string | null | undefined }
    | undefined;
  const fakeFetch = (async (input: string | URL | Request, init?: RequestInit) => {
    captured = {
      url: String(input),
      method: init?.method,
      headers: new Headers(init?.headers),
      body: typeof init?.body === 'string' ? init.body : null
    };
    return new Response(JSON.stringify({
      success: true,
      data: {
        character: { id: 'character-1', status: 'draft', generationMethod: 'roll' },
        occupationId: 1,
        compute: {
          derivedStats: {},
          occupationSkillPoints: { budget: 0, spent: 0, remaining: 0 },
          interestSkillPoints: { budget: 0, spent: 0, remaining: 0 },
          skillView: [],
          resolvedOccupationChoiceSkillIds: [],
          validation: [],
        },
      },
      error: null,
    }));
  }) as typeof fetch;
  const characters = new CharactersResource(
    new ApiClient({ baseUrl: 'http://test/api/v1', fetch: fakeFetch })
  );

  const result = await characters.quickGenerate(
    'room-1',
    'character-1',
    'reconnect-token-1',
    { name: '玩家调查员', age: 28, gender: '女', residence: '阿卡姆', birthplace: '波士顿' }
  );

  assert.equal(
    captured?.url,
    'http://test/api/v1/rooms/room-1/characters/character-1/quick-generate'
  );
  assert.equal(captured?.method, 'POST');
  assert.equal(captured?.headers.get('x-reconnect-token'), 'reconnect-token-1');
  assert.deepEqual(JSON.parse(captured?.body ?? '{}'), {
    name: '玩家调查员',
    age: 28,
    gender: '女',
    residence: '阿卡姆',
    birthplace: '波士顿'
  });
  assert.equal(result.character.generationMethod, 'roll');
});

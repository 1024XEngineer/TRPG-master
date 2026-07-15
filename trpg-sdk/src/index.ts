/**
 * trpg-sdk 的公开入口。打包后 `trpg-frontend` 通过 `import { createTrpgSdk } from
 * 'trpg-sdk'` 使用，实际解析到的是 dist/ 下 rollup 打出来的产物（见 rollup.config.mjs）。
 */

import { ApiClient, type ApiClientOptions } from './client';
import { AuthResource } from './resources/auth';
import { CharactersResource } from './resources/characters';
import { ExamplesResource } from './resources/examples';
import { RoomsResource } from './resources/rooms';

export * from './types';
export { ApiClient, ApiError } from './client';
export type { ApiClientOptions } from './client';

/**
 * SDK 的顶层门面：每种业务资源挂一个只读属性，
 * 调用方用 `sdk.rooms.create(...)` 或 `sdk.examples.list()` 的形式访问。
 */
export class TrpgSdk {
  readonly examples: ExamplesResource;
  readonly rooms: RoomsResource;
  readonly auth: AuthResource;
  readonly characters: CharactersResource;

  constructor(options: ApiClientOptions) {
    const client = new ApiClient(options);
    this.examples = new ExamplesResource(client);
    this.rooms = new RoomsResource(client);
    this.auth = new AuthResource(client);
    this.characters = new CharactersResource(client);
  }
}

/** 工厂函数，比直接 `new TrpgSdk(...)` 更符合大多数 JS SDK 的惯用写法。 */
export function createTrpgSdk(options: ApiClientOptions): TrpgSdk {
  return new TrpgSdk(options);
}

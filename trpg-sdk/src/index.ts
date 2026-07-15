/**
 * trpg-sdk 的公开入口。打包后 `trpg-frontend` 通过 `import { createTrpgSdk } from
 * 'trpg-sdk'` 使用，实际解析到的是 dist/ 下 rollup 打出来的产物（见 rollup.config.mjs）。
 */

import { ApiClient, type ApiClientOptions } from './client';
import { AuthResource } from './resources/auth';
import { CharactersResource } from './resources/characters';
import { ExamplesResource } from './resources/examples';
import { RoomSocket } from './resources/room-socket';
import { RoomsResource } from './resources/rooms';

export * from './types';
export { ApiClient, ApiError } from './client';
export type { ApiClientOptions } from './client';
export { RoomSocket } from './resources/room-socket';
export type { RoomSocketHandler } from './resources/room-socket';

export interface TrpgSdkOptions extends ApiClientOptions {
  /** WS 连接的根地址，比如 "ws://127.0.0.1:8000"（不含 /api/v1，也不含
   * /ws/{roomId} 路径本身）。不传时从 baseUrl 自动推导：去掉尾部的
   * /api/vN 前缀，再把 http(s) 换成 ws(s)。 */
  wsBaseUrl?: string;
}

function deriveWsBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/api\/v\d+\/?$/, '').replace(/^http/, 'ws');
}

/**
 * SDK 的顶层门面：每种业务资源挂一个只读属性，
 * 调用方用 `sdk.rooms.create(...)` 或 `sdk.examples.list()` 的形式访问。
 */
export class TrpgSdk {
  readonly examples: ExamplesResource;
  readonly rooms: RoomsResource;
  readonly auth: AuthResource;
  readonly characters: CharactersResource;
  readonly roomSocket: RoomSocket;

  constructor(options: TrpgSdkOptions) {
    const client = new ApiClient(options);
    this.examples = new ExamplesResource(client);
    this.rooms = new RoomsResource(client);
    this.auth = new AuthResource(client);
    this.characters = new CharactersResource(client);
    this.roomSocket = new RoomSocket(options.wsBaseUrl ?? deriveWsBaseUrl(options.baseUrl));
  }
}

/** 工厂函数，比直接 `new TrpgSdk(...)` 更符合大多数 JS SDK 的惯用写法。 */
export function createTrpgSdk(options: TrpgSdkOptions): TrpgSdk {
  return new TrpgSdk(options);
}

import type { ApiClient } from '../client';
import type { Game, GameSystem, Ruleset } from '../types';

/**
 * `/api/v1/games` 和 `/api/v1/systems` 的类型化封装——游戏大类 / 规则系统 /
 * 建卡所需的规则数据（issue #77 新增）。都是公开的浏览类接口，不需要鉴权。
 */
export class GamesResource {
  constructor(private readonly client: ApiClient) {}

  /** GET /api/v1/games — 游戏大类列表 */
  list(): Promise<Game[]> {
    return this.client.get<Game[]>('/games');
  }

  /** GET /api/v1/games/{gameId}/systems — 某个大类下的规则系统列表 */
  listSystems(gameId: string): Promise<GameSystem[]> {
    return this.client.get<GameSystem[]>(`/games/${gameId}/systems`);
  }

  /** GET /api/v1/systems/{systemId}/ruleset — 建卡所需的规则数据（属性/技能/职业目录） */
  getRuleset(systemId: string): Promise<Ruleset> {
    return this.client.get<Ruleset>(`/systems/${systemId}/ruleset`);
  }
}

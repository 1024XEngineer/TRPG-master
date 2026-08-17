import type { ApiClient } from '../client';
import type { CharacterComputeResult, Game, GameSystem, PreviewCharacterInput, Ruleset } from '../types';

/**
 * `/api/v1/games` 和 `/api/v1/systems` 的类型化封装——游戏大类 / 规则系统 /
 * 建卡所需的规则数据（issue #77 新增）/ 建卡计算预览（issue #84 S2）。
 * 都要求登录，但不要求是房间成员。
 */
export class GamesResource {
  constructor(private readonly client: ApiClient) {}

  private authenticated(token: string): RequestInit {
    return { headers: { Authorization: `Bearer ${token}` } };
  }

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

  /**
   * POST /api/v1/systems/{systemId}/character/preview — 建卡过程中的权威计算
   * 预览（issue #84 S2，路线乙的接缝）：把当前草稿（属性/职业/技能分配）发
   * 上去，拿后端权威算出的衍生值/技能点预算/校验报告来渲染，前端不再本地
   * 重算 COC7 规则数值。
   */
  previewCharacter(
    systemId: string,
    payload: PreviewCharacterInput,
    token: string
  ): Promise<CharacterComputeResult> {
    return this.client.post<CharacterComputeResult>(
      `/systems/${systemId}/character/preview`,
      payload,
      this.authenticated(token)
    );
  }
}
